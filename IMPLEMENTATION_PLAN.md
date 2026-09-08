# RideWeave — Browser-Only FIT Merger Implementation Plan

Status: implementation in progress  
Last updated: 2026-09-08  
Source of truth: this file. Update its checkboxes and decision log in the same pull request as implementation changes.

## 1. Core merge design

### 1.1 Product boundary

Build an open-source proof of concept that combines the best record-level data from two to four recordings of the same activity and downloads one valid FIT file. The entire workflow runs in the browser. Vercel serves only static HTML, CSS, JavaScript, WebAssembly, and Python source; there is no application server, upload endpoint, database, account system, telemetry, or cloud file storage.

Files remain in browser memory and Pyodide's temporary in-memory filesystem. Refreshing or closing the page discards them.

### 1.2 Base-activity invariant

The user must select exactly one input as the main/base activity. The output is the base activity with selected record fields copied from donor files.

The base owns, and the merger preserves by default:

- the master record timeline and all absolute timestamps;
- activity, session, lap, event, pause/resume, device-info, and developer-data messages;
- message order and definitions, except where record definitions must be extended for donated fields;
- GPS (`position_lat` and `position_long`), distance, speed, altitude, and enhanced variants when already present;
- protocol/profile header bytes and all uninterpreted payloads.

The merger does not concatenate activities or rebuild the activity from scratch.

### 1.3 Timestamp and matching policy

All matching uses absolute FIT timestamps. The merger must never shift recordings so that their first samples line up. Independently started devices can begin minutes apart while still sharing the correct real-world clock.

The default manual offset for every donor is zero. A future advanced control may allow an explicit per-file correction after the user reviews alignment diagnostics; offsets must never be inferred only from start times.

For each selected donor field and each base record timestamp:

1. Find the nearest valid donor sample by absolute timestamp.
2. Accept it only when the absolute delta is within that field's tolerance.
3. If two samples are equally close, choose the earlier sample.
4. If no sample qualifies, write the FIT invalid value when adding/overwriting that field; never invent, interpolate, or carry a value across a gap in the POC.
5. If a donor has duplicate samples at one timestamp, the last valid sample in file order wins deterministically.

Initial tolerances:

| Field | Matching policy | Default tolerance |
| --- | --- | ---: |
| Timestamp | Base only; never donated | 0 s |
| GPS position | Base by default; latitude/longitude must share one source | 1 s |
| Distance | Base by default | 1 s |
| Speed / enhanced speed | Base by default | 1 s |
| Altitude / enhanced altitude | Base by default | 2 s |
| Heart rate | Nearest real sample | 5 s |
| Power | Nearest real sample | 1 s |
| Cadence | Nearest real sample | 2 s |
| Temperature | Nearest real sample | 10 s |
| Other scalar record fields | Nearest real sample | 1 s until explicitly profiled |

Power and cadence donors are optional. No error is raised when the user does not add them. They become part of the output only when a source is selected and the file actually contains valid samples.

### 1.4 Field discovery and authority

After upload, inspect every record definition and record message. Enumerate the union of available record fields across all inputs, with a friendly name, FIT field number, sample count, and coverage percentage. Unknown fields remain visible as `Field <number>` so the tool does not silently hide device data.

Every output field has exactly one authority:

- **Base file:** preserve its existing bytes for this field.
- **One donor file:** overwrite or add the field using nearest-sample matching.
- **Do not add:** available only when the base does not already contain that field.

Recommended automatic mapping:

- keep every field already present in the base mapped to the base;
- keep timestamp locked to the base;
- recommend a donor for a missing heart-rate, power, cadence, or temperature field, choosing the source with the most valid samples;
- leave other donor-only fields unselected until the user opts in;
- never silently replace base GPS, speed, distance, or altitude.

### 1.5 Conflict rules

1. Exactly one file is the base; Merge is disabled until this is true.
2. Exactly one source may own each included field. There is no averaging across files.
3. Base structure messages always win. Donor laps, events, sessions, activities, file IDs, and device metadata are never copied in the POC.
4. Timestamp always comes from the base and cannot be overridden.
5. Latitude and longitude form an atomic GPS pair. A future GPS override must select the same donor for both and must reject partial coordinates.
6. A selected donor must actually expose the field and at least one valid sample.
7. When an existing base field is overridden, unmatched records receive the field's FIT invalid value rather than falling back to the base. This makes authority unambiguous and makes gaps visible.
8. Values are copied in their FIT wire representation. The donor field must be a supported scalar primitive; arrays and unsupported developer fields are detected but not selectable until encoding support exists.
9. Input files are immutable. A merge always starts again from the original base bytes.
10. Existing private ride files must never be added to Git or test fixtures.

### 1.6 Coverage and alignment diagnostics

Before Merge, show:

- each file's valid FIT/CRC status, size, record count, UTC start/end time, duration, and detected fields;
- the files on a shared absolute-time range;
- overlap duration and overlap percentage against the base;
- predicted matches for every donated field: matched base records, coverage percentage, median and 95th-percentile timestamp delta, and longest uncovered span;
- warnings for no overlap, less than 80% coverage, clock patterns that suggest a manual offset may be needed, unsupported field types, compressed base record timestamps, or corrupt CRCs.

Diagnostics are advisory except for invalid/corrupt FIT input, no base records, no overlap, unsupported base encoding, or an impossible mapping; those are blocking errors.

### 1.7 FIT output integrity

The initial engine is the supplied dependency-free `merge_fit.py`, adapted behind a browser API. It parses and rewrites FIT bytes directly, which is suitable for Pyodide and avoids runtime Python packages.

For every output:

- retain all base chunks byte-for-byte unless they are record definitions/data being modified;
- preserve developer fields and uninterpreted bytes;
- update record definitions only with fields required by the chosen mappings;
- recompute data size, header CRC when present, and file CRC;
- reparse the output and verify signature, bounds, message structure, header CRC, and file CRC;
- verify base record count and output sample counts;
- fail closed and provide no download if validation fails.

The current engine intentionally rejects a base activity whose Record messages use compressed timestamp headers. Supporting safe rewrite of compressed base records is a v0.3 milestone.

## 2. Frontend proposal

Use one responsive page with a short, guided workflow rather than a dashboard.

### Step 1 — Add files

- Drag-and-drop zone plus a normal file picker with `accept=".fit"`.
- Accept two to four files; reject non-FIT extensions, empty files, a fifth file, and files that fail structural/CRC validation.
- Show a prominent notice: **Private by design — your FIT files never leave this device.**
- File names and ride data must never be written to logs, analytics, local storage, or URLs.

### Step 2 — Choose the base activity

- Render one summary card per file with name, size, time range, duration, record count, detected fields, and validation state.
- Put a required `Use as main activity` radio on every card.
- Recommend, but do not silently choose, the file with the strongest activity structure and GPS coverage.
- Let users remove a file without refreshing.

### Step 3 — Map fields

- Generate a recommended mapping after the base is selected.
- Display one row per detected record field and one dropdown per row.
- Dropdown options include only files containing valid samples for the field, plus `Do not add` when the base lacks it.
- Lock timestamp to the base. Keep base GPS/speed/distance/altitude defaults visibly labeled.
- Include optional power/cadence donors whenever those fields are detected.

### Step 4 — Review alignment

- Show a shared timeline/overlap preview and per-field coverage bars.
- Label low coverage and non-overlap in plain language.
- Keep advanced manual timestamp offsets out of v0.1; add only after diagnostics are reliable.

### Step 5 — Merge and download

- Enable Merge only with 2–4 valid files, one base, valid mappings, and meaningful overlap.
- Run Pyodide and the Python merger in a module Web Worker so the UI remains responsive.
- Show distinct `Loading merger`, `Analyzing`, `Merging`, and `Validating` states.
- On success, display validation and coverage results and a `Download merged.fit` button.
- Revoke object URLs and clear worker files after use.

### Error states

Provide actionable messages for wrong file type, too many/few files, invalid signature, truncated data, bad header/file CRC, no record messages, no absolute timestamp overlap, selected source with no samples, unsupported scalar type, compressed base records, worker/Pyodide load failure, out-of-memory, and output validation failure. Never suggest uploading the file elsewhere as the default remedy.

## 3. Technical architecture

```text
Vercel static CDN
  └─ React + Vite + TypeScript bundle
      ├─ Browser File API (2–4 local files)
      ├─ UI state and mapping recommendations
      └─ module Web Worker
          ├─ pinned Pyodide runtime (WebAssembly)
          ├─ dependency-free merge_fit.py
          ├─ in-memory temporary files
          └─ validated output bytes → Blob download
```

There are deliberately no `/api` routes, server functions, cookies, accounts, database clients, analytics SDKs, or environment secrets.

Initial folder layout:

```text
fit-merger/
├── .github/workflows/ci.yml
├── public/python/merge_fit.py
├── src/
│   ├── components/
│   │   ├── FileDropzone.tsx
│   │   ├── FileSummaryCard.tsx
│   │   ├── FieldMappingTable.tsx
│   │   └── CoveragePreview.tsx
│   ├── fit/
│   │   ├── recommendations.ts
│   │   ├── types.ts
│   │   └── workerClient.ts
│   ├── workers/fit.worker.ts
│   ├── App.tsx
│   ├── main.tsx
│   └── styles.css
├── tests/
│   ├── fixtures/README.md
│   └── synthetic/
├── IMPLEMENTATION_PLAN.md
├── README.md
├── LICENSE
├── package.json
├── tsconfig.json
└── vite.config.ts
```

Pyodide is the v0.x bridge because it reuses the tested Python algorithm. A v1.0 TypeScript rewrite may remove the Pyodide download, reduce startup time, and make offline packaging simpler, but must pass the same golden semantic and byte-integrity tests before replacing Python.

## 4. Repository and development setup

### 4.1 Prerequisites

- Node.js 20.19+ or 22.12+ and npm (current Vite requirement).
- Git.
- A GitHub account able to create a public repository.
- A Vercel account connected to that GitHub identity.
- A current browser with WebAssembly and module Web Worker support.

Verify locally:

```bash
node --version
npm --version
git --version
```

### 4.2 Create and connect the GitHub repository

Create the public repository as `rideweave` and add no template files on GitHub if the local folder already contains the scaffold.

```bash
git init
git branch -M main
git add .
git commit -m "chore: scaffold browser-only FIT merger"
git remote add origin git@github.com:<owner>/rideweave.git
git push -u origin main
```

Alternatively create the empty repository with GitHub CLI, if installed:

```bash
gh repo create rideweave --public --source=. --remote=origin --push
```

Repository settings:

- default branch: `main`;
- require pull requests and passing CI before merge when collaborators join;
- enable Dependabot security updates;
- disable Actions that are not required;
- add topics such as `fit`, `cycling`, `strava`, `privacy`, and `webassembly`;
- never enable Git LFS for private ride files—do not commit them at all.

### 4.3 React/Vite/TypeScript setup

The reproducible scaffold command is:

```bash
npm create vite@latest . -- --template react-ts
npm install
```

This repository pins dependencies through `package-lock.json`. Normal local commands:

```bash
npm run dev
npm run typecheck
npm run lint
npm test
npm run build
npm run preview
```

The Pyodide loader and Python source must be version-pinned. Heavy runtime initialization starts only when inspection/merge is first requested and stays inside the worker.

### 4.4 Git workflow

1. Branch from updated `main`: `git switch -c feat/<short-name>`.
2. Update this plan when scope/status changes.
3. Make small conventional commits (`feat:`, `fix:`, `test:`, `docs:`).
4. Open a pull request; CI runs lint, typecheck, unit tests, and production build.
5. Verify the Vercel preview manually with synthetic/public fixtures.
6. Merge only after output CRC and privacy checks pass.

## 5. Test-data policy

Never commit personal FIT activities. They may contain precise home/work locations, workout times, heart rate, device IDs, and other sensitive data.

Use three fixture classes:

1. Tiny synthetic FIT activities generated by test code with obviously fictional coordinates and timestamps.
2. Redistributable samples from an SDK only after recording their license and source in `tests/fixtures/README.md`.
3. Private local files in `tests/private/`, ignored by Git, for developer-only interoperability checks.

CI must use only synthetic or explicitly redistributable fixtures. Bug reports should prefer a minimal redacted reproduction and must warn contributors before they attach real rides.

## 6. Testing strategy

### Unit tests

- CRC known vectors and corrupted CRC rejection.
- FIT header/data bounds and truncated input.
- normal and compressed donor timestamp parsing.
- absolute-timestamp nearest matching, tolerance boundaries, earlier-sample tie break, duplicate timestamps, and gaps.
- field discovery, friendly/unknown names, source recommendations, and conflict validation.
- scalar encoding and FIT invalid values for supported base types.

### Integration tests

- base + HR donor;
- base + HR + power/cadence donor;
- two, three, and four inputs with one source per field;
- non-overlapping recordings rejected;
- output reparses, CRCs pass, base message order/counts remain stable, and selected output samples match expectations;
- unsupported compressed base records fail without producing a download.

### Browser tests

- drag/drop and picker paths;
- maximum four files and required base radio;
- recommended mapping plus dropdown override;
- keyboard access, labels, focus, status announcements, and error recovery;
- worker does not block basic UI interaction;
- no network request contains a file name, file bytes, or extracted activity data.

## 7. Privacy and security checklist

- [ ] No backend/API/serverless functions.
- [ ] No `fetch`, beacon, form post, or telemetry call includes file data or metadata.
- [ ] No analytics, session replay, ads, or third-party error reporting in the POC.
- [ ] No file contents/names in URLs, browser storage, console logs, or error-report payloads.
- [ ] Pyodide/runtime assets are pinned; evaluate self-hosting them for supply-chain control and offline use.
- [ ] Apply a restrictive Content Security Policy compatible with the pinned runtime.
- [ ] Limit accepted file count and document a conservative per-file/total-memory ceiling.
- [ ] Treat every decoded string/field as untrusted and render it only as text.
- [ ] Clear the worker filesystem and revoke Blob URLs on removal, completion, and page unload.
- [ ] Document that local processing protects transport/storage privacy but cannot protect a compromised browser/device.

## 8. Open-source readiness

- Use an OSI-approved project license; MIT is the initial choice unless dependency review requires a change.
- Preserve the supplied merger attribution in Git history and confirm the contributor owns or can license it.
- Review FIT protocol/library/runtime licenses before distributing bundled SDK assets.
- README must include the problem, privacy model, supported browsers, quick start, workflow, known limitations, test-data warning, contribution path, and security-reporting instructions.
- Add `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue templates, release notes, and semantic version tags before v0.3.

## 9. Vercel registration and deployment

No Vercel plugin, backend, or environment variable is needed for the POC.

1. Create or sign into a Vercel account using the GitHub identity that owns the repository.
2. In Vercel, choose **New Project**, select the GitHub namespace, and import `rideweave`.
3. Grant the Vercel GitHub app access only to this repository when practical.
4. Confirm project settings:
   - Framework preset: **Vite**;
   - Root directory: repository root (`.`);
   - Install command: `npm ci`;
   - Build command: `npm run build`;
   - Output directory: `dist`;
   - Node.js: a version compatible with the pinned Vite release.
5. Environment variables: **none** for Development, Preview, or Production.
6. Deploy. Verify headers, worker/Pyodide loading, inspect, merge, validation, and download in the generated preview URL.
7. Keep Git integration as the deployment mechanism: branch/PR pushes create previews; merges to `main` create production deployments.
8. Optional custom domain: add it under Project Settings → Domains, follow the DNS records Vercel provides, verify HTTPS, then make it the canonical URL.
9. Before public launch, set security headers (CSP, `X-Content-Type-Options`, `Referrer-Policy`, and an appropriate `Permissions-Policy`) and retest the worker/runtime.

Vercel CLI is optional for local preview/diagnosis. Do not add a custom token-based GitHub Actions deployment while built-in Git integration is sufficient. If custom CI deployment is later required, use pinned Vercel CLI, repository secrets (`VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`), `vercel pull`, `vercel build`, and `vercel deploy --prebuilt`; never commit `.vercel/project.json` secrets or tokens.

References:

- [Vite getting started](https://vite.dev/guide/)
- [Pyodide in a Web Worker](https://pyodide.org/en/stable/usage/webworker.html)
- [Vercel Git deployments](https://vercel.com/docs/git)
- [Vercel for GitHub](https://vercel.com/docs/git/vercel-for-github)

### GitHub Pages deployment option

The repository also includes `.github/workflows/pages.yml` so the same static build can be hosted at `https://junyanghe.github.io/rideweave/`. Vite uses `/rideweave/` as its base path only in GitHub Actions, while local development and Vercel continue to use `/`. In GitHub, choose **Settings → Pages → GitHub Actions** once; subsequent pushes to `main` build and publish automatically. GitHub Pages hosts the same browser-only application and does not add a FIT upload backend.

## 10. Milestones

### v0.1 — Working private-by-design merge

- [x] Record architecture, UX, setup, privacy, test, and deployment decisions.
- [x] Initialize the local Git repository on `main`; GitHub remote creation remains an account-level setup step.
- [x] Scaffold React + Vite + TypeScript static app.
- [x] Import the supplied dependency-free Python merger.
- [x] Add worker/Pyodide boundary and browser-safe file inspection/merge API.
- [x] Add 2–4 file intake, base selection, discovered-field mapping, and download UI.
- [ ] Complete field-level predicted coverage diagnostics before merge.
- [ ] Add synthetic FIT fixture generator and Python engine unit/integration suite.
- [ ] Verify end-to-end in supported desktop browsers with private local samples.
- [ ] Deploy first Vercel preview.

### v0.2 — Generalized and trustworthy diagnostics

- [ ] Complete coverage timeline, median/p95 delta, and gap diagnostics.
- [ ] Add manual per-file offsets behind an advanced disclosure.
- [ ] Recompute affected session/lap summary fields where semantics are unambiguous.
- [ ] Add explicit GPS-pair donor override and validation.
- [ ] Add total-memory limits, cancellation, progress, and worker cleanup.
- [ ] Add golden interoperability checks with Garmin tooling and a Strava import smoke test.

### v0.3 — Open-source beta

- [ ] Compressed-timestamp base-record support.
- [ ] Accessibility and mobile-browser test pass.
- [ ] CSP/security headers and self-hosted/pinned runtime evaluation.
- [ ] Contribution, conduct, security, issue, and release documentation.
- [ ] Public Vercel production deployment and optional domain.

### v1.0 — Stable merger

- [ ] Stable documented field/tolerance policy and backward-compatible UI.
- [ ] Broad device fixture matrix and deterministic output tests.
- [ ] Installable/offline PWA if runtime assets can be safely self-hosted.
- [ ] Evaluate/complete TypeScript engine rewrite; remove Pyodide only after parity tests pass.
- [ ] Publish signed release artifacts, changelog, support policy, and threat model.

## 11. Acceptance criteria

The POC is accepted when all of the following are true:

1. A user can add exactly 2–4 valid `.fit` files through drag/drop or the picker and cannot proceed with invalid count/type/CRC.
2. The app requires exactly one base selection and visually explains what the base controls.
3. It enumerates record fields from every input and lets each included field have only one authoritative source.
4. Recommended mapping preserves base GPS/structure and recommends missing HR/power/cadence donors without silently replacing base fields.
5. Matching uses absolute timestamps with zero automatic start-time shift and applies field-specific tolerances.
6. The user sees overlap and predicted per-field coverage before merging, including actionable low-coverage/no-overlap warnings.
7. The merge happens in a Web Worker through Pyodide; the main UI remains responsive and no FIT bytes leave the browser.
8. The downloaded FIT preserves base message order/structure, includes selected donor fields, has valid header/file CRCs, and reparses successfully.
9. Missing donor samples remain missing/invalid rather than interpolated or silently falling back to another source.
10. Unit, integration, browser, typecheck, lint, and production-build checks pass in CI.
11. A GitHub-connected Vercel deployment works with Vite settings, `dist` output, and no environment variables.
12. README, license, contribution/privacy limitations, and private test-file policy are complete enough for a public repository.

## 12. Decision log

- **2026-09-08:** Chose a static Vercel frontend with all parsing/merging local in the browser.
- **2026-09-08:** Chose React + Vite + TypeScript and a module Web Worker.
- **2026-09-08:** Chose Pyodide for v0.x to reuse the supplied dependency-free Python merger; a TypeScript rewrite is deferred.
- **2026-09-08:** Chose one required base activity and one authoritative source per record field.
- **2026-09-08:** Prohibited automatic start-time alignment; absolute FIT timestamps are authoritative.
- **2026-09-08:** Private rides are never repository fixtures.
- **2026-09-08:** Initialized the local repository on `main`; no GitHub or Vercel account changes were made.
- **2026-09-08:** Named the project **RideWeave** with the repository slug `rideweave` after checking for obvious software-name conflicts.
- **2026-09-08:** Created the public `JunyangHe/rideweave` repository and added automatic GitHub Pages deployment alongside the original Vercel path.
