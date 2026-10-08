# Synthetic barcode stress study — 2026-10-08

The study calls the real local Docker HTTP API at http://127.0.0.1:8080/api/v1/analyze. No analysis implementation, metrics, Decision Engine or thresholds were changed. Configuration remains 01752f78a17d, algorithm 1.0.1. This is a deterministic synthetic experiment, not customer accuracy, FAR/FRR or calibration data.

## Reproduce

```powershell
docker compose up -d --wait
python -m tools.barcode_stress --base http://127.0.0.1:8080 --output reports/barcode-stress
```

The CLI streams 164 generated PNG cases, sequentially submits multipart image uploads and writes NOTICE.txt, images/, results.json, results.csv and report.md. All artifacts are ignored by Git. Output must be inside a workspace reports subdirectory; dataset/holdout destinations and symlink redirection are refused. No GOOD/BAD labels or training/calibration integration are created. Request errors/BUSY/schema failures are recorded as technical errors, never RETAKE, and cause a nonzero CLI exit. Configuration drift aborts the study. Decoded values are removed from reports; only equality against the known synthetic payload is retained.

Families: Gaussian blur (five levels), lighting attenuation (four), white elliptical glare (three), true image-boundary crop (three), projective warp (three), controls and partial occlusion (63 per symbol). Occlusion includes horizontal/vertical masks at start/middle/end, 10/25/50/75/90 percent span, white/black fill and gray central patches. Code128 and QR controls use different fixture scales so both are visibly large in the same 1000x600 frame. An initial too-small QR control was corrected in the generator, without changing production thresholds. Both controls now have ACCEPT/payload-equality regression checks.

## Actual results

**46 ACCEPT, 118 RETAKE, zero technical errors, 34 review candidates.** No incorrect decoded payload was observed. Both clean controls accepted.

| Family | Code128 ACCEPT / RETAKE | QR ACCEPT / RETAKE |
|---|---|---|
| Control | 1 / 0 | 1 / 0 |
| Blur | 2 / 3 | 3 / 2 |
| Poor lighting | 2 / 2 | 2 / 2 |
| Glare | 3 / 0 | 0 / 3 |
| Crop | 0 / 3 | 0 / 3 |
| Perspective | 1 / 2 | 2 / 1 |
| Partial occlusion | 28 / 35 | 1 / 62 |

The generated report links every image to its decision, score, active issue codes, sharpness/brightness/contrast/glare/perspective/area metrics and review flags. JSON/CSV preserve every API metric, configuration thresholds, versions, geometry, image SHA256 and known-payload equality. Rule correspondence: BLUR→sharpness; TOO_DARK→brightness/dark ratio; OVEREXPOSED→brightness/saturation ratio; LOW_CONTRAST→contrast; GLARE→glare; PERSPECTIVE→perspective; size/crop→box ratios and edge flags. Missing/failed/multiple decode are hard gates. An issue can be advisory on ACCEPT; score also combines signals without issue codes.

## Occluded ACCEPT investigation

The most severe example is code128-occlusion-horizontal-start-0.9-white (and the equivalent black mask): **90% of generated symbol height hidden, ACCEPT, score 100, no issues, correct decoded value**. The returned decoder ROI covers only the remaining 10% of original symbol height and has zero overlap with the occluding mask. Its area ratio is 0.023908, width ratio 0.755, sharpness 17546.43, brightness 122.78 and contrast 127.41. These pass the current unchanged checks. The system evaluates the surviving readable band; it does not establish full-symbol visibility.

Middle horizontal 50% white occlusion also accepts at score 100: ROI still spans the whole height, but half is masked; sharpness 9623.01, contrast 111.75, saturated ratio 0.74074 and glare 0. A central gray patch covering **56.25% of symbol area** also accepts at 100, with sharpness 7927.00 and contrast 84.30. Thus expanding the ROI alone would not address every case.

QR's accepted central patch covers 6.25% of symbol area and returns the correct value. This is compatible with QR's error-correction behavior. Geometric mask coverage is not the percentage of encoded information destroyed. Decoder-box conventions can also differ by a pixel from generator bounds; the reported geometry ratios are observations, not a new decision metric.

These are **candidate false ACCEPTs only if the business requirement demands a fully visible, undamaged barcode/label**. If the requirement is reliable correct reading, accepting a surviving Code128 scanline or corrected QR is not inherently wrong. No real-world false-accept rate follows from these cases. The 29 accepted occlusion scenarios are marked for review rather than relabelled as customer BAD data.

## Other suspicious signals

All three elliptical Code128 glare fixtures accepted with glare=0 and no advisory. These masks demonstrate a blind spot of the present structural glare heuristic; they are not physically realistic reflection simulations. Mild perspective can be accepted without advisory while still reducing score (Code128 example: perspective 0.2988, score 97.23, below advisory threshold 0.45). This is expected threshold behavior, not automatically a bug. All six actual boundary-crop cases rejected.

## Proposed next steps — not implemented

1. Agree whether acceptance requires readability, complete symbol visibility, complete label visibility, or a combination. Review these synthetic examples alongside real Samsung/customer photographs privately.
2. If completeness is required, explore localization independent of decoder-selected ROI and row-wise bar continuity/occlusion evidence across the expected symbol area. Avoid treating a normal white quiet zone or valid shorter barcode as damage.
3. Treat barcode readability and label completeness as separate documented signals. Evaluate any new check on real GOOD/BAD and untouched holdout before approving algorithm/config changes.
4. Expand the fixture corpus later with multiple payload lengths, rotated occlusions, textured/soft/translucent masks, compression and realistic lighting. Current tests cover one payload per format and controlled masks; no generalization claim is made.

No proposals above were implemented in production. No threshold search or classifier training was run.

## Checks

Backend Windows: **113 passed, 2 skipped** (symlink permissions), Linux Docker: **115 passed**. Frontend: **19 passed**; TypeScript/Vite build passed. Eleven infrastructure tests cover generation repeatability, mask extent/outside preservation, both clean controls, report redaction/artifacts, technical-error classification, config drift and dataset/symlink output safety. Existing non-failing Starlette TestClient warning remains. Threshold SHA256 remains e346e8121e8419c5e630bb0289ab41f688d6a1f067f297551f87072a3e25e1fc.
