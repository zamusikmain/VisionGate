# Final MVP audit — 2026-10-07

## Barcode orientation fallback — 2026-10-08

The reported clean Code128 180-degree failure was not reproduced on available synthetic controls; the original failing customer image is unavailable. A genuine orientation-sensitive failure was reproduced with the existing QR glare fixture on real Compose HTTP (0/270 failed, 90/180 decoded). Added only a bounded decoder fallback: after all five existing variants fail, at most three original-pixel rotations (180/90/270) with inverse geometry mapping, native validity checks and preserved multiple-code counts. Successful fast path unchanged. Thresholds, metrics, Decision Engine, frontend and API schema unchanged. EXIF normalization and full-frame camera capture reviewed; no changes needed. Completeness of partially obstructed but still decodable symbols remains an existing separate research limitation.

Final Windows backend **179 passed / 2 symlink skips**; Linux Docker **181 passed**; frontend **35 passed**, TypeScript/Vite build passed. Compose build passed and both services healthy. Real HTTP matrix: all nine formats at four rotations plus EXIF, 40 ordinary results unchanged; degraded QR now decodes correctly in all four orientations; 74 requests before and after, no wrong payload observed. Median Code128 processing 0 degrees 9.35→10.68 ms / 180 degrees 9.04→10.50 ms; empty 1000×600 38.33→69.59 ms. Docker HTTP smoke passed including size/corruption/MIME/HEIF/concurrency; blank 24 MP 3535.87 ms. Host measurements, not latency guarantees. Threshold SHA256/config version unchanged. Details, limitations and reproduction: docs/barcode-orientation.md; ignored raw reports/orientation-before.json and reports/orientation-after.json. No calibration or customer dataset ingestion.

## Mobile capture assistance — 2026-10-08

Optional local preview hints reuse the existing bounded scheduler, off by default; no network preview or shutter gating. Capability-probed continuous autofocus is nonblocking with default-camera fallback; UI distinguishes requested from reported mode. RETAKE now offers direct camera reopening and alternative selection. Synchronous in-flight submission lock covers same-event double clicks while preserving retry/replacement. Full-frame capture unchanged. Frontend 35 tests and local/Docker build passed, services healthy; real browser RETAKE/mobile RU/EN checked using synthetic blur input. Physical focus accuracy and hint reliability remain unverified. Backend/thresholds/Decision Engine/metrics/API unchanged; no calibration. Details: docs/mobile-camera.md.

## Mobile camera UX — 2026-10-08

Whole-label visual guide and concise RU/EN instructions added, with object-fit-aware live geometry and responsive resize/orientation handling. Full-frame capture and existing button readiness/busy rules unchanged; no barcode-position gating or guide cropping. Frontend 27 tests and TypeScript/Vite build passed; Docker frontend rebuilt, both Compose services healthy. Browser idle-screen RU/EN inspection at 320x568,390x844,430x932,844x390,1024x768 shows no horizontal overflow. Live stream/canvas behavior tested using simulated video, not physical mobile cameras. Details and limits: docs/mobile-camera.md. Backend/config/Decision Engine/metrics/API unchanged; threshold hash unchanged.

## Offline Barcode Integrity research — 2026-10-08

Prototype exists only in experiments/ and is excluded from Docker context. No application imports, production/API changes or threshold changes. Full results: docs/barcode-integrity.md; private per-image artifacts: reports/barcode-integrity. Comparison covers all 164 existing scenarios plus 21 normal controls through real HTTP API. Intrinsic continuity flags 8/29 accepted occlusions; with generator-ground-truth expected region, 24/29 (oracle gain, not demonstrated localization). Zero intrinsic false flags among 22 supported normal Code128 controls; QR/absent geometry are unknown, not intact. Crop detection not demonstrated. Pixel-identical short-valid/90%-occluded control proves need for external extent/context in that case. No production integration recommended yet.

Eight additional prototype tests; full Windows 121 passed / 2 symlink skips, Linux Docker 123 passed. Compose rebuild passed; unchanged frontend build reused. API config before/after stable, production diff empty, threshold SHA256 unchanged. Generated artifacts remain outside datasets and Git. No training, threshold search or calibration occurred.

## Synthetic stress extension — 2026-10-08

Added tools/barcode_stress.py and eleven infrastructure regression tests without changes to backend analysis/metrics/Decision Engine/thresholds. Real Compose HTTP run: 164 synthetic cases, 46 ACCEPT, 118 RETAKE, zero technical errors; 34 review candidates. Accepted occlusions: Code128 28/63, QR 1/63, all with expected payload. Severe 90%-height Code128 masking can ACCEPT at score100 because the decoder ROI is the surviving band; this is a completeness-policy risk, not an observed wrong decode. Full findings and proposals (not implemented): docs/barcode-stress.md. Generated images/JSON/CSV/Markdown remain ignored under reports, outside real datasets.

Final regressions: Windows 113 passed / 2 symlink skips; Linux Docker 115 passed; frontend 19 passed and production build passed. API config stable before/after study; threshold SHA256 remains unchanged. No synthetic inputs were added to a customer training/calibration dataset and no calibration search was performed.

## Result and immutable baseline

IMPLEMENTED / VERIFIED: final audit release algorithm_version **1.0.1**. Only objective validation, lifecycle, concurrency and UX bugs were fixed. Decision Engine rules, score weights and thresholds were not changed. No accuracy tuning or calibration grid was run during this audit.

config_version: **01752f78a17d**. config/thresholds.json SHA256: **e346e8121e8419c5e630bb0289ab41f688d6a1f067f297551f87072a3e25e1fc**.

Initial thresholds remain uncalibrated. Scores are deterministic quality indicators, not probabilities. Customer-domain accuracy/FAR/FRR is **NOT VERIFIED**, because real GOOD/BAD data has not arrived.

## Verification evidence

| Check | Final result |
|---|---|
| Windows backend | **93 passed, 1 skipped**; 6.49 s. Skip: symlink creation privileges unavailable |
| Linux backend in Docker | **94 passed**; 4.61 s, including symlink security case |
| Frontend | **19 passed** |
| TypeScript / Vite production build | Passed locally and in Docker |
| Docker Compose | Both services rebuilt and healthy; non-root backend/frontend |
| npm audit | Zero known vulnerabilities reported |
| Backend dependency audit | Exact Docker installed set: 29 packages, zero reported vulnerabilities |
| Docker HTTP scenarios | reports/audit/docker-audit.json; all assertions passed |
| Runtime privacy sample | STORE_ANALYSIS_IMAGES=false; zero retained private images; sampled history values redacted |

Backend runs emit one non-failing Starlette TestClient warning recommending httpx2. Dependency checks cover reported package vulnerabilities, not an OS image audit or penetration test. Tests are in tests/test_gate.py, tests/test_audit.py, tests/test_dataset_intake.py and frontend/src/*.test.tsx.

## Requested scenario coverage

| Area | Evidence and limits |
|---|---|
| Camera / upload | Portrait 720x1280 full intrinsic capture, canplay readiness, track stopping, denied-camera fallback, late callback/request cleanup, invalid replacement clearing old preview, blob URL revocation, cancellation and 60-second timeout tested |
| Repeated submission | Pending button disabled; intentional completed repeat allowed with new ID. No submission idempotency contract |
| Decision Engine | Hard failure precedence, missing/decode failure/multiple codes/crop/critical signals and unchanged score rules covered |
| ZXing | Real fixtures: Code128, Code39, EAN13/8, UPC-A/E, ITF, QR, DataMatrix. UPC-A canonicalizes to EAN13; UPC-E text expands to GTIN13 while retaining type |
| Rotation / EXIF | Real decode and ACCEPT at 0/90/180/270; all eight EXIF orientations, including mirrors, normalize correctly |
| Large images | Real 24 MP input processed; above-limit dimensions rejected before expanded array allocation; decompression bomb and byte limits covered; extreme legal aspect ratio no longer resizes to zero |
| HEIC/HEIF | Explicit friendly rejection; no decoding support claimed. Synthetic ISO-BMFF header fixture only, not a real phone HEIC decoding test |
| Corruption / animation / alpha | Corrupt PNG/JPEG paths return validation errors; animated PNG/WEBP rejected; alpha flattened white so invisible barcode cannot ACCEPT |
| No / multiple / edge barcode | Missing code RETAKE; real two-code images including identical values rejected; readable near-edge code accepted, actual crop RETAKE |
| API validation | Actual content/MIME, octet-stream valid image, duplicate/extra fields, finite metrics, invalid content-length, safe errors/request IDs, size cap and OpenAPI multipart schema covered |
| Temp cleanup | Complete, malformed, truncated and mid-stream oversized multipart close every spooled file; actual incremental ASGI receive regression |
| Concurrency | Per-process bounded capacity; cancellation/failure releases permits; 16 varied analyses preserve value/ID isolation; 24 concurrent SQLite writes retain rows |
| Private storage | Default off, UUID exclusive writes, POSIX 0600, symlink/foreign-name safe retention and closed SQLite handles. Windows relies on directory ACLs; retention runs on later saves, not a strict timer |
| RU/EN | Matching translation keys, source AST check for hardcoded user-facing JSX/accessible strings, errors retranslate on language switch, localized admin labels; brand/language IDs/version remain invariant |
| Mobile UX | Responsive frontend and portrait component tests. Physical Android/iPhone camera, permissions and browser combinations NOT VERIFIED |

Browser QA of the rebuilt app verified RU corrupted-image error, removal of preview and submit/retry controls after validation, and recovery controls. EXIF upload produced backend ACCEPT in browser. Browser automation later timed out opening the EN upload chooser; no claim of a completed final physical/mobile browser matrix is made.

## Objective fixes

- Added a complete multipart parser that closes spooled files even when the closing boundary never arrives. It uses tested Starlette parser hooks; upgrades must retain these regressions.
- Fixed stale upload state, localized error lifecycle, camera readiness/unmount/capture races and failed canvas capture handling. Invalid backend inputs now require a new photo rather than retrying identical bad bytes.
- Hardened content/MIME, HEIF, animated/transparent inputs, corrupt Pillow paths and extreme aspect ratios; rejected NaN/Infinity metrics.
- Added bounded native analysis concurrency, reliably closed SQLite connections, safe private-file retention and bounded Windows atomic-config replace retries.
- Normalized HTTP errors and added JSON/request ID/no-store headers to Nginx oversize rejection.
- Added private dataset exclusion, integrity intake, exact duplicate/conflicting-label checks, source hashes/change detection and collision-safe Unicode debug output.

## Actual Docker HTTP measurements

Synthetic rotations: processing 9.43–12.95 ms, roundtrip 25.78–63.21 ms. EXIF6: 9.61 ms processing. No barcode: RETAKE in 41.64 ms. Valid 24 MP blank image: RETAKE, **2039.16 ms processing / 2285.35 ms roundtrip**. These are single-host measurements, not production latency guarantees.

Corrupt image: 422 CORRUPTED_IMAGE. HEIF header: 422 UNSUPPORTED_HEIF. Spoof MIME: 422 INVALID_IMAGE_TYPE. Valid PNG/octet-stream accepted. Above 24 MP rejected. Backend above 12 MiB and Nginx 14 MiB requests both return 413; proxy response is JSON with request ID/no-store.

24 submissions using eight client workers yielded **5 HTTP200 and 19 HTTP503 BUSY**, unique IDs, successful decisions ACCEPT. This demonstrates capacity protection, not quality failure or throughput capacity. Compose has two workers with two active native analyses each. Uvicorn separately limits concurrent requests; larger loads can also receive transport-level 503.

## Dataset readiness for tomorrow

IMPLEMENTED: python -m tools.dataset_audit dataset --output reports/intake.json. It checks bounded real content, normalized dimensions, SHA256, exact duplicates, label conflicts and path/symlink safety. It does not score, tune thresholds or detect near duplicates.

Current dataset is empty: GOOD=0, BAD=0, ready=false, EMPTY_CLASS in reports/audit/customer-intake-pending.json; intake fails appropriately. Only demo/synthetic was evaluated without --grid, into reports/audit/synthetic-baseline. Demo/audit fixtures are explicitly synthetic.

1. Place private labelled originals in dataset/good and dataset/bad. Export unsupported HEIC/HEIF to JPEG/PNG separately. Preserve originals and device/session/asset metadata.
2. Run intake and review invalid files and exact duplicates. Separate related assets/sessions/devices into calibration and untouched holdout; manually review near duplicates.
3. Run baseline without tuning: python -m tools.calibrate dataset --output reports/baseline --debug. Outputs must be outside the input dataset. Inputs are hashed before and after evaluation.
4. Review real false accepts/rejects with the business owner. Only then consider a separate search, holdout validation and manually approved config change. Reports/debug copies remain private and omit decoded values.

## Remaining limits

PARTIALLY VERIFIED: camera lifecycle/mobile presentation via tests and desktop browser; physical phone checks pending. HEIC/HEIF decoding is unsupported. Glare/perspective are advisory heuristics and require real-domain evaluation. No trained classifier, live server preview guidance or whole-label detector is claimed.

BLOCKED BY MISSING DATA: real accuracy, threshold selection and deployment quality acceptance. Wider corporate rollout still requires authenticated gateway/SSO, HTTPS, rate limits and operating policy. Local Compose is a pilot, not production certification.

## GitHub / Render preparation — 2026-10-07

No Git repository existed initially. Initialized main; no prior commit history or tracked credentials needed removal. GitHub CLI is absent (including standard installation paths), so remote repository creation/push has not occurred. No GitHub URL or private/public status is claimed until that operation completes.

Added single-service Dockerfile.render and backend/render_app.py packaging adapter. Existing backend.main, Decision Engine, metrics, decoder, image pipeline, thresholds and local Compose behavior are unchanged. Static index/assets and existing API/docs share one origin. Runtime/source/config paths are not publicly mounted. Non-root runtime; PORT is interpolated at startup, tested at 12345 rather than a fixed default. render.yaml uses existing /api/v1/health, no external database or persistent disk. Image retention defaults false; history/admin configuration on Free are explicitly ephemeral. See docs/deployment.md for settings and security boundaries.

Final deployment regressions: **103 passed / 1 skipped on Windows (6.61 s), 104 passed in Linux production Docker image (4.52 s), 19 frontend tests**, TypeScript/Vite builds passed locally and in both Docker packaging modes. Expected Windows symlink skip and Starlette warning remain. Initial sandbox runs encountered temporary-file access failures; unrestricted reruns passed. Existing Compose rebuilt and both services healthy. Production image healthy at PORT=12345, UID1000. HTTP smoke verifies frontend built assets, API/docs/OpenAPI, private paths 404, sequential repeat IDs, corrupt rejection, 12MiB cap, and 24MP input. The existing Compose synthetic ACCEPT/RETAKE smoke also passed. The 24MP smoke was on the local Docker host; Free memory/latency guarantees are not inferred.

Publication review: .env.example is empty of credentials; no images, real datasets, uploads, SQLite, reports, logs, caches, node_modules, dist or IDE files enter the index. GOOD/BAD and holdout .gitkeep remain trackable; hypothetical photos and environment variants are ignored. Raster photo exclusion also applies outside dataset folders. tools.release_check rejects sensitive paths/symlinks in the index, including force-added files; run it for every future release. .gitignore alone cannot enforce an absolute prohibition against deliberate git add -f.

Gitleaks **v8.30.1**, default rules, redacted output, network-disabled scan of exact staged diff: **no leaks found**. Final index policy and secret scan are rerun immediately before commit. This is pattern-based review, not a guarantee that every possible secret is detectable. Reports/staged-review.patch stays excluded from Git. No credentials are placed into Docker build arguments or image layers.

Threshold file SHA256 remains e346e8121e8419c5e630bb0289ab41f688d6a1f067f297551f87072a3e25e1fc; config_version remains 01752f78a17d. No calibration or threshold changes were performed during deployment preparation.
