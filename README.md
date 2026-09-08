# RideWeave

**Merge the best data from every cycling sensor into one complete FIT activity.**

RideWeave is a free, open-source, browser-only FIT merger for cyclists who record the same ride with multiple devices. It keeps one recording as the main activity, adds selected sensor fields from the others, and downloads a single validated FIT file that can be uploaded to Strava.

No expensive replacement bike computer is required. No ride files are uploaded to RideWeave. Everything is processed locally in the browser.

## Why this project exists

RideWeave began with a frustratingly common cycling setup.

One bike computer recorded excellent GPS, speed, distance, elevation, laps, and pause events. An Apple Watch captured the rider's heart rate. A power meter recorded the watts being produced at the pedals. Each device was useful, but none of them was able to bring every sensor into the same activity.

At the start of a ride, the rider could start the Blackbird BB16, record with Strava for Apple Watch heart rate, and use the X-LAB app for RS7 power. At the end, however, the result was not one rich ride. It was several incomplete versions of the same ride:

```text
Blackbird BB16 recording
  → best GPS, speed, distance, and ride structure

Strava + Apple Watch recording
  → heart rate, but a separate Strava activity

X-LAB RS7 recording
  → power data in another device or app
```

Some sensors do not integrate with Strava at all. Others can sync to Strava, but every recording arrives as a separate activity. Strava does not combine those overlapping activities into one record, so the rider must either accept missing data, keep duplicates, or replace otherwise useful hardware with an expensive cycling computer that supports every sensor.

RideWeave offers another path:

```text
Main FIT activity  ──────────────┐
                                 │
Heart-rate FIT ── heart rate ────┼──→ one merged, validated FIT
                                 │
Power FIT ─────── power/cadence ─┘
```

The rider chooses the recording with the best overall activity data as the base. RideWeave preserves its timeline, GPS track, laps, pauses, events, and metadata, then weaves in heart rate, power, or cadence from other recordings using their real timestamps.

The result is one activity containing the best available data from the hardware the rider already owns.

## What RideWeave does

1. Accepts two to four FIT files recorded during the same ride.
2. Validates each file's FIT structure and CRC.
3. Requires one file to be selected as the main activity.
4. Detects the record fields available in every input.
5. Recommends sources for missing heart rate, power, and cadence.
6. Shows how much of the main activity can be matched to each donor stream.
7. Merges selected fields using absolute FIT timestamps.
8. Revalidates the generated FIT before making it available to download.

The main activity remains authoritative for:

- timestamps and master timeline;
- GPS position;
- speed, distance, and elevation;
- laps and pause/resume events;
- activity/session structure and device metadata.

Other files act as sensor donors. Each included field has exactly one authoritative source—RideWeave never averages conflicting devices or shifts recordings merely to make their start times match.

## Private by design

FIT files can reveal precise routes, home or work locations, ride times, heart rate, power, and device identifiers. RideWeave therefore has a strict architectural rule:

> **Your FIT files never leave your device.**

The Vercel deployment serves only static application files. FIT parsing and merging run inside a Pyodide Web Worker in the browser. There is no upload endpoint, backend, database, user account, analytics service, or cloud ride history. Refreshing or closing the page clears the working data.

## Current POC capabilities

- Drag-and-drop or file-picker input for two to four `.fit` files.
- Required main/base activity selection.
- Record count, time range, field discovery, and CRC checks.
- Independent heart-rate, power, and cadence donor selection.
- Field-specific nearest-sample tolerances.
- Coverage preview based on absolute timestamps.
- Background processing in a Web Worker so the interface remains responsive.
- Structure and CRC validation before download.
- Static deployment on Vercel with no environment variables.

## Current limitations

- Donor overrides are currently limited to heart rate, power, and cadence.
- The main activity must use normal Record messages; compressed-timestamp donor records are supported, but compressed Record messages in the base are not rewritten yet.
- RideWeave does not connect directly to Strava, Blackbird, Apple Health, or X-LAB. Users must obtain local FIT exports from their recording sources.
- If a device or app does not provide a FIT export, RideWeave cannot recover that sensor stream until an export becomes available.
- The POC does not recalculate every device-specific training metric or proprietary developer field.

See [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) for the complete merge rules, architecture, security model, test strategy, Vercel setup, milestones, and acceptance criteria.

## Local development

Prerequisites:

- Node.js 20.19+ or 22.12+
- npm
- Git
- A current browser with WebAssembly and module Web Worker support

Install and run:

```bash
npm install
npm run dev
```

Quality checks:

```bash
npm run typecheck
npm run lint
npm test
npm run build
```

The first FIT inspection loads a pinned Pyodide runtime from jsDelivr. FIT bytes remain in Pyodide's temporary in-memory filesystem and are never included in that network request.

## Test-file policy

Never commit personal ride files. Developer-only samples belong under `tests/private/`, which is ignored by Git. CI fixtures must be synthetic or have explicit redistribution permission, with their source and license documented.

## Deploying on GitHub Pages

The included `Deploy to GitHub Pages` workflow builds and publishes `dist` after every push to `main`. In the repository, open **Settings → Pages**, choose **GitHub Actions** as the source, and use:

`https://junyanghe.github.io/rideweave/`

Vite applies the `/rideweave/` base path only inside GitHub Actions, so local development and Vercel continue to run from `/`.

## Deploying on Vercel

Import the `rideweave` GitHub repository as a Vite project with these settings:

- Install command: `npm ci`
- Build command: `npm run build`
- Output directory: `dist`
- Environment variables: none

Git integration creates preview deployments for branches and pull requests, then deploys `main` to production.

## Project status

RideWeave is an early proof of concept. Verify a downloaded activity before replacing or deleting any original Strava activity. Contributions, device samples that are safe to redistribute, FIT interoperability testing, and accessibility feedback are welcome.

RideWeave is not affiliated with or endorsed by Strava, Apple, Blackbird, X-LAB, or Garmin.

## License

MIT. The FIT protocol and third-party runtime assets remain subject to their respective terms.
