import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path


ENGINE_PATH = Path(__file__).parents[1] / "public" / "python" / "merge_fit.py"
SPEC = importlib.util.spec_from_file_location("rideweave_merge_fit", ENGINE_PATH)
ENGINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENGINE
SPEC.loader.exec_module(ENGINE)


def definition(local_num, global_num, fields, dev_fields=()):
    header = 0x40 | local_num | (0x20 if dev_fields else 0)
    result = bytearray((header, 0, 0))
    result += struct.pack("<H", global_num)
    result.append(len(fields))
    for field_number, size, base_type in fields:
        result += bytes((field_number, size, base_type))
    if dev_fields:
        result.append(len(dev_fields))
        for field_number, size, developer_index in dev_fields:
            result += bytes((field_number, size, developer_index))
    return bytes(result)


def data(local_num, *parts):
    return bytes((local_num,)) + b"".join(parts)


def fit_file(*chunks):
    fit_data = b"".join(chunks)
    header = bytearray(14)
    header[0] = 14
    header[1] = 0x20
    struct.pack_into("<H", header, 2, 100)
    struct.pack_into("<I", header, 4, len(fit_data))
    header[8:12] = b".FIT"
    struct.pack_into("<H", header, 12, ENGINE.fit_crc(bytes(header[:12])))
    body = bytes(header) + fit_data
    return body + struct.pack("<H", ENGINE.fit_crc(body))


class MergePreservationTest(unittest.TestCase):
    def test_only_selected_heart_rate_changes_from_main_activity(self):
        record_fields = (
            (ENGINE.FIELD_TIMESTAMP, 4, ENGINE.BASE_UINT32),
            (0, 4, 0x85),  # position_lat
            (5, 4, ENGINE.BASE_UINT32),  # distance
            (6, 2, ENGINE.BASE_UINT16),  # speed
            (ENGINE.FIELD_HEART_RATE, 1, ENGINE.BASE_UINT8),
        )
        no_timestamp_fields = (
            (5, 4, ENGINE.BASE_UINT32),
            (6, 2, ENGINE.BASE_UINT16),
        )
        session_fields = (
            (ENGINE.FIELD_TIMESTAMP, 4, ENGINE.BASE_UINT32),
            (7, 4, ENGINE.BASE_UINT32),  # total_elapsed_time
        )
        donor_fields = (
            (ENGINE.FIELD_TIMESTAMP, 4, ENGINE.BASE_UINT32),
            (ENGINE.FIELD_HEART_RATE, 1, ENGINE.BASE_UINT8),
        )

        base_bytes = fit_file(
            definition(0, ENGINE.RECORD_MSG_NUM, record_fields, ((0, 2, 0),)),
            data(
                0,
                struct.pack("<I", 1_000),
                struct.pack("<i", -123_456),
                struct.pack("<I", 12_345),
                struct.pack("<H", 678),
                bytes((55,)),
                b"\xaa\xbb",
            ),
            data(
                0,
                struct.pack("<I", 1_001),
                struct.pack("<i", -123_455),
                struct.pack("<I", 12_400),
                struct.pack("<H", 680),
                bytes((56,)),
                b"\xcc\xdd",
            ),
            definition(2, ENGINE.RECORD_MSG_NUM, no_timestamp_fields, ((1, 1, 0),)),
            data(2, struct.pack("<I", 77_777), struct.pack("<H", 700), b"\xee"),
            definition(1, 18, session_fields),
            data(1, struct.pack("<I", 1_001), struct.pack("<I", 60_000)),
        )
        donor_bytes = fit_file(
            definition(0, ENGINE.RECORD_MSG_NUM, donor_fields),
            data(0, struct.pack("<I", 1_000), bytes((111,))),
            data(0, struct.pack("<I", 1_001), bytes((112,))),
        )

        with tempfile.TemporaryDirectory() as directory:
            base_path = Path(directory) / "main.fit"
            donor_path = Path(directory) / "donor.fit"
            output_path = Path(directory) / "merged.fit"
            base_path.write_bytes(base_bytes)
            donor_path.write_bytes(donor_bytes)

            stats = ENGINE.merge_selected(
                base_path,
                output_path,
                {"heart_rate": (donor_path, 5.0)},
            )

            _, _, _, base_chunks = ENGINE.parse_fit(base_path)
            _, _, _, output_chunks = ENGINE.parse_fit(output_path)

        self.assertEqual(stats["baseRecords"], 2)
        self.assertEqual(stats["fields"]["heart_rate"]["outputSamples"], 2)
        self.assertEqual(len(output_chunks), len(base_chunks))

        timestamped_output = [
            chunk
            for chunk in output_chunks
            if chunk.kind == "data"
            and chunk.definition.global_num == ENGINE.RECORD_MSG_NUM
            and chunk.timestamp is not None
        ]
        self.assertEqual(
            [chunk.values[ENGINE.FIELD_HEART_RATE] for chunk in timestamped_output],
            [111, 112],
        )

        for base_chunk, output_chunk in zip(base_chunks, output_chunks):
            if base_chunk.definition.global_num != ENGINE.RECORD_MSG_NUM:
                self.assertEqual(output_chunk.raw, base_chunk.raw)
                continue
            if base_chunk.kind != "data":
                continue
            base_native, base_developer = ENGINE._record_payload_parts(base_chunk)
            output_native, output_developer = ENGINE._record_payload_parts(output_chunk)
            for index, field in enumerate(base_chunk.definition.fields):
                if field.number != ENGINE.FIELD_HEART_RATE:
                    self.assertEqual(output_native[index], base_native[index])
            self.assertEqual(output_developer, base_developer)

        no_timestamp_output = next(
            chunk
            for chunk in output_chunks
            if chunk.kind == "data"
            and chunk.definition.global_num == ENGINE.RECORD_MSG_NUM
            and chunk.timestamp is None
        )
        self.assertIsNone(no_timestamp_output.values[ENGINE.FIELD_HEART_RATE])

    def test_rejects_an_existing_target_field_with_an_unsafe_layout(self):
        base_bytes = fit_file(
            definition(
                0,
                ENGINE.RECORD_MSG_NUM,
                (
                    (ENGINE.FIELD_TIMESTAMP, 4, ENGINE.BASE_UINT32),
                    (ENGINE.FIELD_HEART_RATE, 2, ENGINE.BASE_UINT16),
                ),
            ),
            data(0, struct.pack("<I", 1_000), struct.pack("<H", 55)),
        )
        donor_bytes = fit_file(
            definition(
                0,
                ENGINE.RECORD_MSG_NUM,
                (
                    (ENGINE.FIELD_TIMESTAMP, 4, ENGINE.BASE_UINT32),
                    (ENGINE.FIELD_HEART_RATE, 1, ENGINE.BASE_UINT8),
                ),
            ),
            data(0, struct.pack("<I", 1_000), bytes((111,))),
        )

        with tempfile.TemporaryDirectory() as directory:
            base_path = Path(directory) / "main.fit"
            donor_path = Path(directory) / "donor.fit"
            output_path = Path(directory) / "merged.fit"
            base_path.write_bytes(base_bytes)
            donor_path.write_bytes(donor_bytes)

            with self.assertRaisesRegex(ValueError, "unsupported layout for heart_rate"):
                ENGINE.merge_selected(
                    base_path,
                    output_path,
                    {"heart_rate": (donor_path, 5.0)},
                )

            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
