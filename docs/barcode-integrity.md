# Barcode Integrity research — 2026-10-08

Recommendation: **keep this offline; do not deploy it as a rejection rule.** Intrinsic scanline analysis detects some internal disruptions, but cannot infer an originally taller barcode from a uniformly surviving short band. Stronger completeness checks require independent label/template geometry or real-data modelling. Agreement on what constitutes complete visibility comes first.

## Why current metrics miss overlap

backend/gate/pipeline.py measures the decoder-selected bounding box. A Code128 covered across the top 90% is still decoded from the lower 10%; the returned box excludes the mask. Sharpness, luminance, contrast and saturated/dark ratios therefore resemble the clean surviving bars. Its area ratio remains 0.023908 > 0.015 and width 0.755 > 0.15. Barcode height ratio is reported but not a hard gate. Increasing that gate without real geometry priors would reject legitimate short symbols.

Even an internal 50%-height white band can preserve strong edges/contrast and remain below the saturation rejection ratio. Laplacian variance measures edges, not continuity, and mask boundaries can add edges. The current glare heuristic checks wide almost-fully-bright **columns** bordered by dark columns; a horizontal mask need not satisfy that condition. Crop checks concern the returned box relative to the frame, not an unknown original label extent. Saturated score signals can all reach one, producing 100 even with incomplete visibility. Correct decoding and full visual integrity are distinct requirements.

## Three technical approaches

| Approach | Strength | Main failure/requirement |
|---|---|---|
| Rectify decoder geometry, compare bar edge energy/pattern consistency across scanlines | Lightweight, no learned model; reveals central white/black gaps and partial patches | Surviving-band ROI has no evidence of original height; matrix codes need a different structural model; printing, curved labels and texture can cause false flags |
| Independently locate label/symbol extent, optionally use known label template/fiducials and scale, then compare visible rows/quiet zones/frame clipping | Can expose missing outer bands/crops outside decoder ROI | Independent localization is essential; label box is not necessarily barcode box. Printed borders/text, unknown layouts, perspective and legitimate short symbols complicate it |
| Train explicit symbol/label and occlusion segmentation with visible-region masks | Potential coverage of texture, translucent overlaps and complex geometry | Requires consented, labelled real photographs, proper holdout and uncertainty handling. No model/data/training added here; synthetic artifacts are not real GOOD/BAD |

## Isolated prototype

experiments/barcode_integrity.py is imported only by offline research/test code. experiments/ is excluded from Docker context. No API, Decision Engine, metric, threshold or ACCEPT/RETAKE change exists.

Intrinsic mode supports Code128 only: rectify its decoder polygon, calculate mean absolute horizontal edge difference for each row and flag long weak row runs or relative row-energy drops. Experimental design constants: support=0.30 of reference, row-drop=0.25, gap=0.10 of ROI height. They are **research parameters, not calibrated production thresholds** and were not searched or optimized on the results.

A separate optional expected_box mode tests the idea of an independently known expected region; row coverage <0.90 is flagged. In this study the box comes from **synthetic generator ground truth** for unrotated controls/occlusions, so it is an oracle upper-bound experiment, not a working image-only localization method. Intrinsic flags do not read that box. QR/no four-point geometry/weak signal are **unknown**, not certified intact. Warped/rotated external priors are not implemented.

```powershell
docker compose up -d --wait
python -m experiments.run_integrity --base http://127.0.0.1:8080 --output reports/barcode-integrity
```

Outputs: private ignored PNGs, results.json and report.md. The runner submits every image to the real unchanged HTTP API, stores its decision/metrics and separate experimental findings, redacts decoded values, and verifies stable config before/after. Output is confined to reports and symlink redirection is refused. Technical/API/config failures abort the research run; they are never counted as RETAKE. No synthetic labels enter dataset/holdout or calibration.

## Actual comparison: 185 images

The original 164 stress images retain **46 ACCEPT / 118 RETAKE**. Added 21 valid synthetic controls: four legitimate bar heights (20/40/100/200 px) × four rotations, moderate blur/dimming, brighter background, external text clutter and a short symbol on a tall white label. Those yield 17 ACCEPT / 4 RETAKE; the four existing rejections are short symbols rotated 90/270 triggering BARCODE_TOO_SMALL. They remain unmodified and are a separate orientation/size-policy observation.

| Comparison | Result |
|---|---|
| Current API across all 185 | 63 ACCEPT / 122 RETAKE |
| Existing accepted occlusion candidates | 29: 28 Code128 + 1 QR |
| Intrinsic prototype flags | **8 of 29**, all Code128 (8 of 28 supported candidates) |
| Intrinsic + oracle expected-region flags | **24 of 29**; 16 additional cases detected only with the oracle |
| Normal controls (21 additional + 2 original) | 23 total; 22 Code128 supported, 1 QR unknown |
| Intrinsic false flags on supported normal controls | **0 of 22**; this small designed sample does not establish real-world specificity |
| Unknown/unsupported across all inputs | **118 of 185**; no completeness conclusion for these |
| Crop cases | All 6 current RETAKE; prototype unknown for all 6, so crop detection has NOT been demonstrated |

Intrinsic flags include five accepted middle horizontal-mask cases and three accepted gray central patches. Uniform start/end masking is missed intrinsically. The oracle makes 90%-height masking detectable by comparing row support over the original expected region. Five accepted occlusions remain unflagged even in combined mode: four 10%-height end/start masks and the QR patch. This is not a production false-accept rate, because the images are deliberately synthetic and business completeness labels remain unagreed.

One of six glare scenarios is intrinsically flagged (three Code128 supported); no perspective scenarios are flagged (three supported). The prototype is not a universal glare/perspective classifier.

## Identifiability control

The normal short-on-tall-white-label control is **pixel-identical** to the 90%-occluded-white Code128 scenario. It has the same API decode and intrinsic findings. A test locks this equivalence: any deterministic image-only method receives the same evidence for these two interpretations. A different expected extent/layout or external capture context is required to distinguish them. Do not solve this by raising minimum bar height indiscriminately.

## Recommendation and limits

Retain intrinsic continuity as a diagnostic research signal. Before integration, agree completeness requirements, obtain real independent label/symbol extent annotations and expand clean controls with naturally nonuniform printing, wrinkles, backgrounds, payload lengths and device capture. Design a distinct QR structural/visible-region experiment. Validate any proposed completeness classifier on private real data and untouched holdout; review false flags and unknown handling before proposing a production rule/API extension.

The synthetic oracle gain (8→24) is evidence that independent geometry could help, **not evidence that localization has been solved**. Zero false flags on these clean controls cannot justify deployment. Current ACCEPT/RETAKE, score, shipped thresholds and public API remain unchanged.

## Verification

Eight prototype regression tests cover clean/rotated short symbols, internal gaps, severe masking with/without external prior, pixel-identical ambiguity, QR/absent geometry unknown states, outside-frame priors and allocation bounds. Full suite: **123 passed in Linux Docker**, **121 passed / 2 symlink skips on Windows**. Existing Starlette warning remains. Docker Compose rebuild passed (frontend build cached; frontend source unchanged). Threshold SHA256 remains e346e8121e8419c5e630bb0289ab41f688d6a1f067f297551f87072a3e25e1fc. All 185 fresh HTTP comparisons preserve the unchanged config; no prototype flags alter API decisions.
