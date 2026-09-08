#!/usr/bin/env python3
"""
Merge sensor streams into a main FIT activity.

Designed for this workflow:
  --base  main.fit        authoritative GPS/speed/distance/activity
  --hr    heart-rate.fit  authoritative heart-rate donor
  --power power.fit       optional power/cadence donor

No third-party Python packages are required.

Important design choices:
- The base FIT is preserved byte-for-byte except for Record-message definitions/data
  that need HR/power/cadence fields, plus FIT header/data CRCs.
- Absolute FIT timestamps are used directly. We DO NOT infer an offset from activity
  start times because independently-started recordings may begin at different times
  while still sharing the same clock.
- Missing donor samples are written as FIT invalid values rather than invented.
- Heart rate is copied from the nearest real donor sample within a configurable
  tolerance (default 5 s), allowing for irregular sampling intervals.
- Power uses a tighter default tolerance (1 s).

This implementation supports normal FIT data records and compressed-timestamp donor
records. The base file must use normal (non-compressed) Record messages.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# FIT global message number for Record.
RECORD_MSG_NUM = 20

# FIT Record field numbers.
FIELD_TIMESTAMP = 253
FIELD_HEART_RATE = 3
FIELD_CADENCE = 4
FIELD_POWER = 7

FIELD_NAMES = {
    0: "position_lat",
    1: "position_long",
    2: "altitude",
    3: "heart_rate",
    4: "cadence",
    5: "distance",
    6: "speed",
    7: "power",
    8: "compressed_speed_distance",
    9: "grade",
    10: "resistance",
    13: "temperature",
    29: "accumulated_power",
    30: "left_right_balance",
    31: "gps_accuracy",
    32: "vertical_speed",
    33: "calories",
    73: "enhanced_speed",
    78: "enhanced_altitude",
    253: "timestamp",
}

# FIT base types used here.
BASE_UINT8 = 0x02
BASE_UINT16 = 0x84
BASE_UINT32 = 0x86

INVALID_UINT8 = 0xFF
INVALID_UINT16 = 0xFFFF
INVALID_UINT32 = 0xFFFFFFFF

# Re-declare after the base-type constants so browser-facing code has canonical
# definitions without importing any third-party FIT profile package.
DONATABLE_FIELDS = {
    "heart_rate": (FIELD_HEART_RATE, 1, BASE_UINT8, 5.0),
    "cadence": (FIELD_CADENCE, 1, BASE_UINT8, 2.0),
    "power": (FIELD_POWER, 2, BASE_UINT16, 1.0),
}

CRC_TABLE = [
    0x0000, 0xCC01, 0xD801, 0x1400,
    0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401,
    0x5000, 0x9C01, 0x8801, 0x4400,
]


@dataclass
class FieldDef:
    number: int
    size: int
    base_type: int


@dataclass
class DevFieldDef:
    number: int
    size: int
    developer_data_index: int


@dataclass
class Definition:
    local_num: int
    global_num: int
    architecture: int
    fields: List[FieldDef]
    dev_fields: List[DevFieldDef]
    header_byte: int
    reserved: int = 0

    @property
    def endian(self) -> str:
        return ">" if self.architecture else "<"


@dataclass
class ParsedChunk:
    """One FIT data-section chunk: either a definition or a data message."""

    kind: str  # "definition" | "data" | "compressed"
    raw: bytes
    local_num: int
    definition: Definition
    values: Optional[Dict[int, object]] = None
    timestamp: Optional[int] = None


@dataclass
class Stream:
    timestamps: List[int]
    values: List[int]


def fit_crc(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc ^= tmp ^ CRC_TABLE[byte & 0xF]

        tmp = CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc ^= tmp ^ CRC_TABLE[(byte >> 4) & 0xF]
    return crc


def _unpack_scalar(raw: bytes, base_type: int, endian: str):
    """Decode only the FIT primitive types needed for timestamp/sensor extraction."""
    formats = {
        0x00: "B",   # enum
        0x01: "b",   # sint8
        0x02: "B",   # uint8
        0x83: "h",   # sint16
        0x84: "H",   # uint16
        0x85: "i",   # sint32
        0x86: "I",   # uint32
        0x0A: "B",   # uint8z
        0x8B: "H",   # uint16z
        0x8C: "I",   # uint32z
        0x0D: "B",   # byte
        0x88: "f",   # float32
        0x89: "d",   # float64
        0x8E: "q",   # sint64
        0x8F: "Q",   # uint64
        0x90: "Q",   # uint64z
    }
    invalid = {
        0x00: 0xFF,
        0x01: 0x7F,
        0x02: 0xFF,
        0x83: 0x7FFF,
        0x84: 0xFFFF,
        0x85: 0x7FFFFFFF,
        0x86: 0xFFFFFFFF,
    }

    if base_type == 0x07:  # string
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    fmt = formats.get(base_type)
    if fmt is None:
        return raw

    size = struct.calcsize(fmt)
    if len(raw) != size:
        # Array fields are irrelevant to this merger; keep bytes intact.
        return raw

    value = struct.unpack(endian + fmt, raw)[0]
    if base_type in invalid and value == invalid[base_type]:
        return None
    return value


def _decode_payload(payload: bytes, definition: Definition, skip_timestamp: bool = False):
    values: Dict[int, object] = {}
    pos = 0

    fields = definition.fields
    for field in fields:
        if skip_timestamp and field.number == FIELD_TIMESTAMP:
            # In a compressed-timestamp message, the timestamp field is represented
            # by the record header and omitted from the payload.
            continue
        raw = payload[pos:pos + field.size]
        if len(raw) != field.size:
            raise ValueError("Truncated FIT data message")
        pos += field.size
        values[field.number] = _unpack_scalar(raw, field.base_type, definition.endian)

    # Developer fields are preserved but not interpreted.
    for field in definition.dev_fields:
        pos += field.size

    return values, pos


def parse_fit(path: Path) -> Tuple[bytes, int, int, List[ParsedChunk]]:
    blob = path.read_bytes()
    if len(blob) < 14:
        raise ValueError(f"{path}: too small to be a FIT file")

    header_size = blob[0]
    if blob[8:12] != b".FIT":
        raise ValueError(f"{path}: missing .FIT signature")

    data_size = struct.unpack_from("<I", blob, 4)[0]
    data_start = header_size
    data_end = data_start + data_size
    if data_end + 2 > len(blob):
        raise ValueError(f"{path}: truncated FIT data section")

    # Validate header CRC when present (14-byte standard header).
    if header_size >= 14:
        stored_header_crc = struct.unpack_from("<H", blob, 12)[0]
        calc_header_crc = fit_crc(blob[:12])
        if stored_header_crc != calc_header_crc:
            raise ValueError(
                f"{path}: bad header CRC: stored=0x{stored_header_crc:04x}, "
                f"calculated=0x{calc_header_crc:04x}"
            )

    stored_file_crc = struct.unpack_from("<H", blob, data_end)[0]
    calc_file_crc = fit_crc(blob[:data_end])
    if stored_file_crc != calc_file_crc:
        raise ValueError(
            f"{path}: bad file CRC: stored=0x{stored_file_crc:04x}, "
            f"calculated=0x{calc_file_crc:04x}"
        )

    data = blob[data_start:data_end]
    definitions: Dict[int, Definition] = {}
    chunks: List[ParsedChunk] = []
    pos = 0
    last_timestamp: Optional[int] = None

    while pos < len(data):
        chunk_start = pos
        header = data[pos]
        pos += 1

        # Compressed timestamp data header.
        if header & 0x80:
            local_num = (header >> 5) & 0x03
            time_offset = header & 0x1F
            definition = definitions.get(local_num)
            if definition is None:
                raise ValueError(f"{path}: compressed record uses undefined local message {local_num}")
            if last_timestamp is None:
                raise ValueError(f"{path}: compressed timestamp without a previous timestamp")

            payload_size = sum(f.size for f in definition.fields if f.number != FIELD_TIMESTAMP)
            payload_size += sum(f.size for f in definition.dev_fields)
            payload = data[pos:pos + payload_size]
            pos += payload_size

            values, _ = _decode_payload(payload, definition, skip_timestamp=True)
            timestamp = (last_timestamp & ~0x1F) + time_offset
            if timestamp < last_timestamp:
                timestamp += 0x20
            values[FIELD_TIMESTAMP] = timestamp
            last_timestamp = timestamp

            chunks.append(ParsedChunk(
                kind="compressed",
                raw=data[chunk_start:pos],
                local_num=local_num,
                definition=definition,
                values=values,
                timestamp=timestamp,
            ))
            continue

        local_num = header & 0x0F

        # Definition message.
        if header & 0x40:
            has_dev_fields = bool(header & 0x20)
            if pos + 5 > len(data):
                raise ValueError(f"{path}: truncated FIT definition")

            reserved = data[pos]
            architecture = data[pos + 1]
            pos += 2
            endian = ">" if architecture else "<"
            global_num = struct.unpack_from(endian + "H", data, pos)[0]
            pos += 2
            num_fields = data[pos]
            pos += 1

            fields: List[FieldDef] = []
            for _ in range(num_fields):
                number, size, base_type = data[pos:pos + 3]
                pos += 3
                fields.append(FieldDef(number, size, base_type))

            dev_fields: List[DevFieldDef] = []
            if has_dev_fields:
                num_dev = data[pos]
                pos += 1
                for _ in range(num_dev):
                    number, size, dev_index = data[pos:pos + 3]
                    pos += 3
                    dev_fields.append(DevFieldDef(number, size, dev_index))

            definition = Definition(
                local_num=local_num,
                global_num=global_num,
                architecture=architecture,
                fields=fields,
                dev_fields=dev_fields,
                header_byte=header,
                reserved=reserved,
            )
            definitions[local_num] = definition
            chunks.append(ParsedChunk(
                kind="definition",
                raw=data[chunk_start:pos],
                local_num=local_num,
                definition=definition,
            ))
            continue

        # Normal data message.
        definition = definitions.get(local_num)
        if definition is None:
            raise ValueError(f"{path}: data message uses undefined local message {local_num}")

        payload_size = sum(f.size for f in definition.fields) + sum(f.size for f in definition.dev_fields)
        payload = data[pos:pos + payload_size]
        pos += payload_size
        values, _ = _decode_payload(payload, definition)
        timestamp = values.get(FIELD_TIMESTAMP)
        if isinstance(timestamp, int):
            last_timestamp = timestamp

        chunks.append(ParsedChunk(
            kind="data",
            raw=data[chunk_start:pos],
            local_num=local_num,
            definition=definition,
            values=values,
            timestamp=timestamp if isinstance(timestamp, int) else None,
        ))

    return blob, header_size, data_size, chunks


def extract_stream(chunks: Sequence[ParsedChunk], field_num: int, offset_seconds: int = 0) -> Stream:
    pairs: Dict[int, int] = {}
    for chunk in chunks:
        if chunk.kind not in ("data", "compressed"):
            continue
        if chunk.definition.global_num != RECORD_MSG_NUM or chunk.values is None:
            continue
        timestamp = chunk.values.get(FIELD_TIMESTAMP)
        value = chunk.values.get(field_num)
        if not isinstance(timestamp, int) or not isinstance(value, (int, float)):
            continue
        value = int(round(value))
        # HR/cadence=0 is physiologically/sensor-wise invalid for this workflow.
        if field_num in (FIELD_HEART_RATE, FIELD_CADENCE) and value <= 0:
            continue
        if field_num == FIELD_POWER and value < 0:
            continue
        pairs[timestamp + offset_seconds] = value

    timestamps = sorted(pairs)
    return Stream(timestamps=timestamps, values=[pairs[t] for t in timestamps])


def nearest_sample(stream: Stream, timestamp: int, tolerance_seconds: float) -> Optional[int]:
    value, _ = nearest_sample_with_distance(stream, timestamp, tolerance_seconds)
    return value


def nearest_sample_with_distance(
    stream: Stream,
    timestamp: int,
    tolerance_seconds: float,
) -> Tuple[Optional[int], Optional[int]]:
    if not stream.timestamps:
        return None, None
    i = bisect.bisect_left(stream.timestamps, timestamp)
    candidates: List[Tuple[int, int]] = []
    if i < len(stream.timestamps):
        candidates.append((abs(stream.timestamps[i] - timestamp), i))
    if i > 0:
        candidates.append((abs(stream.timestamps[i - 1] - timestamp), i - 1))
    if not candidates:
        return None, None
    distance, idx = min(candidates)
    if distance > tolerance_seconds:
        return None, None
    return stream.values[idx], distance


def inspect_fit(path: Path) -> Dict[str, object]:
    """Return JSON-safe metadata used by the browser without exposing file data."""
    blob, header_size, data_size, chunks = parse_fit(path)
    record_chunks = [
        chunk for chunk in chunks
        if chunk.kind in ("data", "compressed")
        and chunk.definition.global_num == RECORD_MSG_NUM
        and chunk.values is not None
    ]
    timestamps = [
        chunk.timestamp for chunk in record_chunks
        if isinstance(chunk.timestamp, int)
    ]
    definitions = [
        chunk.definition for chunk in chunks
        if chunk.kind == "definition" and chunk.definition.global_num == RECORD_MSG_NUM
    ]
    definitions_by_number: Dict[int, List[FieldDef]] = {}
    for definition in definitions:
        for field in definition.fields:
            definitions_by_number.setdefault(field.number, []).append(field)

    fields = []
    for field_number in sorted(definitions_by_number):
        samples = 0
        for chunk in record_chunks:
            value = chunk.values.get(field_number) if chunk.values else None
            if isinstance(value, (int, float)) and not (
                isinstance(value, float) and math.isnan(value)
            ):
                samples += 1
        name = FIELD_NAMES.get(field_number, f"field_{field_number}")
        canonical = DONATABLE_FIELDS.get(name)
        compatible = False
        if canonical:
            _, expected_size, expected_type, _ = canonical
            compatible = any(
                field.size == expected_size and field.base_type == expected_type
                for field in definitions_by_number[field_number]
            )
        fields.append({
            "name": name,
            "number": field_number,
            "samples": samples,
            "coverage": (samples / len(record_chunks)) if record_chunks else 0.0,
            "donatable": bool(canonical and compatible and samples),
        })

    compressed_records = sum(1 for chunk in record_chunks if chunk.kind == "compressed")
    return {
        "sizeBytes": len(blob),
        "headerSize": header_size,
        "dataSize": data_size,
        "crcValid": True,
        "recordCount": len(record_chunks),
        "startTimestamp": min(timestamps) if timestamps else None,
        "endTimestamp": max(timestamps) if timestamps else None,
        "durationSeconds": (max(timestamps) - min(timestamps)) if timestamps else 0,
        "compressedRecordCount": compressed_records,
        "fields": fields,
    }


def preview_selected(
    base_path: Path,
    selections: Dict[str, Tuple[Path, float]],
) -> Dict[str, object]:
    """Predict field coverage using the exact matching policy used by merge."""
    _, _, _, base_chunks = parse_fit(base_path)
    base_timestamps = [
        chunk.timestamp for chunk in base_chunks
        if chunk.kind in ("data", "compressed")
        and chunk.definition.global_num == RECORD_MSG_NUM
        and isinstance(chunk.timestamp, int)
    ]
    donor_cache: Dict[str, Sequence[ParsedChunk]] = {}
    diagnostics: Dict[str, object] = {}

    for name, (path, tolerance) in selections.items():
        field_number = DONATABLE_FIELDS[name][0]
        path_key = str(path)
        if path_key not in donor_cache:
            _, _, _, donor_cache[path_key] = parse_fit(path)
        stream = extract_stream(donor_cache[path_key], field_number)
        distances = []
        matched = 0
        for timestamp in base_timestamps:
            value, distance = nearest_sample_with_distance(stream, timestamp, tolerance)
            if value is not None and distance is not None:
                matched += 1
                distances.append(distance)
        distances.sort()
        median = distances[len(distances) // 2] if distances else None
        p95_index = math.ceil(len(distances) * 0.95) - 1 if distances else None
        diagnostics[name] = {
            "matched": matched,
            "baseRecords": len(base_timestamps),
            "coverage": matched / len(base_timestamps) if base_timestamps else 0.0,
            "sourceSamples": len(stream.timestamps),
            "medianDeltaSeconds": median,
            "p95DeltaSeconds": distances[p95_index] if p95_index is not None else None,
            "toleranceSeconds": tolerance,
        }

    return {"baseRecords": len(base_timestamps), "fields": diagnostics}


def encode_definition(defn: Definition, add_fields: Sequence[FieldDef]) -> bytes:
    """Encode a definition, appending only fields not already present."""
    existing = {f.number for f in defn.fields}
    fields = list(defn.fields) + [f for f in add_fields if f.number not in existing]

    # Preserve original definition header flags, including developer-data flag.
    out = bytearray([defn.header_byte, defn.reserved, defn.architecture])
    out += struct.pack(defn.endian + "H", defn.global_num)
    out.append(len(fields))
    for field in fields:
        out += bytes((field.number, field.size, field.base_type))

    if defn.header_byte & 0x20:
        out.append(len(defn.dev_fields))
        for field in defn.dev_fields:
            out += bytes((field.number, field.size, field.developer_data_index))
    return bytes(out)


def _field_bytes(value: Optional[int], field: FieldDef, endian: str) -> bytes:
    if field.number in (FIELD_HEART_RATE, FIELD_CADENCE):
        v = INVALID_UINT8 if value is None else max(0, min(254, int(value)))
        return struct.pack("B", v)
    if field.number == FIELD_POWER:
        v = INVALID_UINT16 if value is None else max(0, min(65534, int(value)))
        return struct.pack(endian + "H", v)
    raise ValueError(f"Unsupported injected field {field.number}")


def rewrite_record_data(
    chunk: ParsedChunk,
    injected: Dict[int, Optional[int]],
    target_fields: Sequence[FieldDef],
) -> bytes:
    """
    Rewrite one normal Record message. Existing target fields are overwritten;
    missing target fields are appended in the same order added to the definition.
    """
    if chunk.kind != "data":
        raise ValueError("Base Record messages must be normal, non-compressed data messages")

    raw = chunk.raw
    payload = raw[1:]
    defn = chunk.definition
    pos = 0
    out_payload = bytearray()
    existing_numbers = {f.number for f in defn.fields}

    for field in defn.fields:
        raw_field = payload[pos:pos + field.size]
        pos += field.size
        if field.number in injected:
            out_payload += _field_bytes(injected[field.number], field, defn.endian)
        else:
            out_payload += raw_field

    # Preserve developer fields exactly.
    dev_size = sum(f.size for f in defn.dev_fields)
    dev_payload = payload[pos:pos + dev_size]

    for field in target_fields:
        if field.number not in existing_numbers:
            out_payload += _field_bytes(injected.get(field.number), field, defn.endian)

    out_payload += dev_payload
    return bytes([raw[0]]) + bytes(out_payload)


def merge_selected(
    base_path: Path,
    output_path: Path,
    selections: Dict[str, Tuple[Path, float]],
) -> Dict[str, object]:
    """Merge any supported donor fields while preserving the base structure."""
    if not selections:
        raise ValueError("Select at least one donor field before merging")
    unsupported = sorted(set(selections) - set(DONATABLE_FIELDS))
    if unsupported:
        raise ValueError(f"Unsupported donor field(s): {', '.join(unsupported)}")

    base_blob, header_size, _, base_chunks = parse_fit(base_path)
    donor_cache: Dict[str, Sequence[ParsedChunk]] = {}
    streams: Dict[str, Stream] = {}
    tolerances: Dict[str, float] = {}
    target_fields: List[FieldDef] = []

    for name, (path, tolerance) in selections.items():
        field_number, size, base_type, _ = DONATABLE_FIELDS[name]
        path_key = str(path)
        if path_key not in donor_cache:
            _, _, _, donor_cache[path_key] = parse_fit(path)
        stream = extract_stream(donor_cache[path_key], field_number)
        if not stream.timestamps:
            raise ValueError(f"Selected {name} donor has no valid samples")
        streams[name] = stream
        tolerances[name] = tolerance
        target_fields.append(FieldDef(field_number, size, base_type))

    output_data = bytearray()
    base_record_count = 0
    matched = {name: 0 for name in selections}

    for chunk in base_chunks:
        if chunk.kind == "definition":
            if chunk.definition.global_num == RECORD_MSG_NUM:
                output_data += encode_definition(chunk.definition, target_fields)
            else:
                output_data += chunk.raw
            continue

        if chunk.definition.global_num != RECORD_MSG_NUM:
            output_data += chunk.raw
            continue

        if chunk.kind == "compressed":
            raise ValueError(
                "The selected base uses compressed-timestamp Record messages. "
                "Choose another base; compressed base rewriting is not supported yet."
            )

        timestamp = chunk.timestamp
        if timestamp is None:
            output_data += chunk.raw
            continue

        base_record_count += 1
        injected: Dict[int, Optional[int]] = {}
        for name, stream in streams.items():
            field_number = DONATABLE_FIELDS[name][0]
            value = nearest_sample(stream, timestamp, tolerances[name])
            injected[field_number] = value
            if value is not None:
                matched[name] += 1
        output_data += rewrite_record_data(chunk, injected, target_fields)

    if base_record_count == 0:
        raise ValueError("The selected base contains no timestamped Record messages")

    header = bytearray(base_blob[:header_size])
    struct.pack_into("<I", header, 4, len(output_data))
    if header_size >= 14:
        struct.pack_into("<H", header, 12, 0)
        struct.pack_into("<H", header, 12, fit_crc(bytes(header[:12])))

    body = bytes(header) + bytes(output_data)
    output_blob = body + struct.pack("<H", fit_crc(body))
    output_path.write_bytes(output_blob)

    _, _, _, verified_chunks = parse_fit(output_path)
    field_stats: Dict[str, object] = {}
    for name, stream in streams.items():
        field_number = DONATABLE_FIELDS[name][0]
        verified = extract_stream(verified_chunks, field_number)
        field_stats[name] = {
            "sourceSamples": len(stream.timestamps),
            "matchedRecords": matched[name],
            "outputSamples": len(verified.timestamps),
            "coverage": matched[name] / base_record_count,
            "toleranceSeconds": tolerances[name],
        }

    return {
        "baseRecords": base_record_count,
        "fields": field_stats,
        "outputBytes": len(output_blob),
        "validation": "PASS",
    }


def merge(
    base_path: Path,
    hr_path: Path,
    output_path: Path,
    power_path: Optional[Path] = None,
    hr_tolerance: float = 5.0,
    power_tolerance: float = 1.0,
    hr_offset: int = 0,
    power_offset: int = 0,
    use_power_cadence: bool = False,
):
    selections: Dict[str, Tuple[Path, float]] = {
        "heart_rate": (hr_path, hr_tolerance),
    }
    if hr_offset:
        raise ValueError("Manual offsets are not supported by the browser-safe merger")
    if power_path is not None:
        if power_offset:
            raise ValueError("Manual offsets are not supported by the browser-safe merger")
        selections["power"] = (power_path, power_tolerance)
        if use_power_cadence:
            selections["cadence"] = (power_path, 2.0)

    result = merge_selected(base_path, output_path, selections)
    fields = result["fields"]
    hr_stats = fields["heart_rate"]
    power_stats = fields.get("power", {})
    cadence_stats = fields.get("cadence", {})
    return {
        "base_records": result["baseRecords"],
        "hr_source_samples": hr_stats["sourceSamples"],
        "hr_matched_records": hr_stats["matchedRecords"],
        "hr_output_samples": hr_stats["outputSamples"],
        "power_source_samples": power_stats.get("sourceSamples", 0),
        "power_matched_records": power_stats.get("matchedRecords", 0),
        "power_output_samples": power_stats.get("outputSamples", 0),
        "cadence_matched_records": cadence_stats.get("matchedRecords", 0),
        "output_bytes": result["outputBytes"],
    }


def preview_web(config_json: str) -> str:
    """JSON bridge used by the Pyodide worker."""
    config = json.loads(config_json)
    selections = {
        name: (Path(value["path"]), float(value["toleranceSeconds"]))
        for name, value in config["selections"].items()
    }
    return json.dumps(preview_selected(Path(config["basePath"]), selections))


def merge_web(config_json: str) -> str:
    """JSON bridge used by the Pyodide worker."""
    config = json.loads(config_json)
    selections = {
        name: (Path(value["path"]), float(value["toleranceSeconds"]))
        for name, value in config["selections"].items()
    }
    result = merge_selected(
        Path(config["basePath"]),
        Path(config["outputPath"]),
        selections,
    )
    return json.dumps(result)


def main():
    parser = argparse.ArgumentParser(description="Merge sensor streams into a main FIT activity")
    parser.add_argument("--base", required=True, type=Path, help="Main FIT activity")
    parser.add_argument("--hr", required=True, type=Path, help="Heart-rate donor FIT")
    parser.add_argument("--power", type=Path, default=None, help="Optional power donor FIT")
    parser.add_argument("--output", type=Path, default=Path("merged.fit"))
    parser.add_argument("--hr-tolerance", type=float, default=5.0, help="Nearest HR sample tolerance in seconds (default 5)")
    parser.add_argument("--power-tolerance", type=float, default=1.0, help="Nearest power/cadence tolerance in seconds (default 1)")
    parser.add_argument("--hr-offset", type=int, default=0, help="Manual HR donor timestamp offset in seconds (default 0)")
    parser.add_argument("--power-offset", type=int, default=0, help="Manual power timestamp offset in seconds (default 0)")
    parser.add_argument("--power-cadence", action="store_true", help="Also copy cadence from the power donor when available")
    args = parser.parse_args()

    stats = merge(
        base_path=args.base,
        hr_path=args.hr,
        output_path=args.output,
        power_path=args.power,
        hr_tolerance=args.hr_tolerance,
        power_tolerance=args.power_tolerance,
        hr_offset=args.hr_offset,
        power_offset=args.power_offset,
        use_power_cadence=args.power_cadence,
    )

    print(f"Output: {args.output}")
    print(f"Base Record messages: {stats['base_records']}")
    print(f"HR source samples:     {stats['hr_source_samples']}")
    print(f"HR matched records:    {stats['hr_matched_records']} / {stats['base_records']} "
          f"({stats['hr_matched_records']/stats['base_records']:.1%})")
    print(f"HR samples in output:  {stats['hr_output_samples']}")
    if args.power:
        print(f"Power source samples:  {stats['power_source_samples']}")
        print(f"Power matched records: {stats['power_matched_records']} / {stats['base_records']}")
        print(f"Power samples output:  {stats['power_output_samples']}")
        if args.power_cadence:
            print(f"Cadence matched:       {stats['cadence_matched_records']}")
    print(f"Output size:            {stats['output_bytes']:,} bytes")
    print("Validation:             PASS (FIT structure + header CRC + file CRC)")


if __name__ == "__main__":
    main()
