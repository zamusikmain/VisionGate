# Barcode orientation investigation — 2026-10-08

## Evidence and cause

The reported upside-down Code128 failure could not be reproduced with the available clean synthetic fixture: the pre-change real Compose HTTP API decoded the identical payload at 0/90/180/270 degrees. No failing customer image was supplied or committed. Therefore the exact cause of that particular photograph is **not established**.

ZXing already receives `try_rotate=True`. Its native linear reader searches horizontal/vertical scanlines and reverses scanline patterns for upside-down symbols; simply enabling that option again would not fix anything. Official source: [ZXing linear reader](https://github.com/zxing-cpp/zxing-cpp/blob/master/core/src/oned/ODReader.cpp), [Python wrapper](https://github.com/zxing-cpp/zxing-cpp/blob/master/wrappers/python/zxing.cpp). Native search is heuristic and is not guaranteed to locate a degraded symbol identically after rotating pixels.

A concrete orientation-sensitive failure was reproduced with the existing synthetic `qr-glare-0.1` fixture, through the unchanged real HTTP API: 0/270 degrees failed; 90/180 decoded the expected payload. The application exhausted original/grayscale/CLAHE/adaptive threshold/sharpened reads without any explicit rotated-pixel retry. This fallback gap is the objective defect addressed here, not proof of the original Code128 failure's cause.

## Fix and safeguards

Existing successful reads return immediately. Only if all five original variants fail, three additional native reads use the original pixels rotated 180,90,270 degrees. No additional sharpening/threshold permutations, resizing, permissive decoding or `is_pure` mode are introduced. The maximum is eight reads. Rotated copies are contiguous; polygon and inclusive bounding-box coordinates return to the original image coordinates before existing ROI metrics run. Each rotated read uses ZXing's existing `try_rotate`, downscale and validity behavior.

Only `decoded=True` (ZXing `valid`) results can satisfy a fallback; checksum errors/localization-only results are not promoted. Multiple physical codes, including identical payloads, retain their count and existing RETAKE rule. Thresholds, quality metrics, Decision Engine, response schema and frontend are unchanged. Successful recovery can naturally change a previous DECODE_FAILED result to ACCEPT when existing quality rules pass.

This is a decoding fix, **not Barcode Integrity**. Start/stop truncations in our negative fixtures remain RETAKE. A code with enough intact redundant rows or error-correctable data may remain valid despite partial obstruction, as previously documented in `docs/barcode-integrity.md`. Code39/ITF without optional checksum cannot provide universal wrong-payload detection. No claim of guaranteed completeness or correctness for every damaged customer label is made, and the isolated integrity prototype was not enabled.

## EXIF and camera review

`read_image` uses Pillow `ImageOps.exif_transpose` before RGB/BGR conversion. Existing regression tests cover all eight EXIF orientations and mirrors; new real API tests cover EXIF 1/3/6/8 with matching inverse pixel rotations. Metadata is applied once. The camera copies the full intrinsic video frame to canvas (`videoWidth`/`videoHeight`, full `drawImage`), producing JPEG pixels rather than relying on EXIF. No camera/frame cropping or screen-orientation transform was changed. Physical phone behavior and the missing original failing photograph remain unverified.

## Real API before/after

Run `python -m tools.orientation_check --output reports/orientation-after.json` against Compose, optionally supplying `--base`. Images are generated in memory; JSON remains ignored under reports, outside customer datasets. Both runs used 74 HTTP requests on the same local host: nine formats × four orientations, four glare rotations, four EXIF cases and 30 timing samples. Code128, Code39, EAN13, EAN8, UPC-A, UPC-E, ITF, QR, DataMatrix all decoded expected values at all rotations before and after; UPC values retain native GTIN normalization. All 40 ordinary format/EXIF checks retained payload, decision, issue list and decode method. No wrong payload was observed.

| Scenario | Before | After |
|---|---:|---:|
| Code128 0 degrees, median of 10 processing samples | 9.35 ms | 10.68 ms |
| Code128 180 degrees, median of 10 | 9.04 ms | 10.50 ms |
| Empty 1000×600, median of 10 | 38.33 ms | 69.59 ms |
| QR glare 0 degrees, single read | RETAKE, 39.88 ms | ACCEPT, 46.90 ms |
| QR glare 270 degrees, single read | RETAKE, 34.19 ms | ACCEPT, 44.53 ms |

Normal successful reads still perform one native decode; these timings include host variability and metrics, not a latency guarantee or accuracy estimate. Failed frames pay the bounded fallback cost. Final Docker API smoke: blank 24 MP RETAKE in 3535.87 ms processing / 3737.82 ms roundtrip, size/MIME/corruption/HEIF gates passed, 24 concurrent requests yielded 6 HTTP200 and 18 HTTP503 BUSY with unique request IDs. No customer data or calibration was used.

## Verification

New orientation regressions cover all nine fixture formats via actual ASGI API, EXIF, real glare recovery, non-square coordinate restoration for each fallback rotation, contiguous buffers, early return / maximum attempt counts, truncated/missing symbols, error-only reads, and multiple-code counts. Existing real two-code tests now run in all four orientations.

Final results are recorded in `docs/verification.md`. Threshold SHA256 remains `e346e8121e8419c5e630bb0289ab41f688d6a1f067f297551f87072a3e25e1fc`, config version `01752f78a17d`.
