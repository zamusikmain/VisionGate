# Dataset evaluation and threshold selection

1. Store customer-labelled images in `dataset/good` and `dataset/bad`. Keep them private. No customer data is bundled.
2. Split by device/label/capture session into calibration and holdout folders before tuning, avoiding near-duplicate leakage. Each split has its own `good`/`bad`.
3. Run integrity intake first: `python -m tools.dataset_audit dataset --output reports/intake.json`. Require both classes, inspect invalid inputs and conflicting exact duplicates. Then run baseline: `python -m tools.calibrate dataset --output reports/baseline --debug`.
4. Inspect JSON/CSV/HTML and explicit false_accepts/false_rejects. Debug images are copies with bounding box, safety margin, decision/score/sharpness. Original files remain unchanged. Glare masks are not painted because the heuristic is not reliable enough.
5. Search: `python -m tools.calibrate dataset --grid config/grid.example.json --output reports/search --false-accept-weight 10 --false-reject-weight 1`.
6. Review current config vs suggested config and both confusion matrices. The suggestion is written to `suggested-config.json`; production settings are never updated automatically.
7. Test the suggestion on untouched holdout: `python -m tools.calibrate holdout --config reports/search/suggested-config.json --output reports/holdout`.
8. Approve manually through internal admin settings or deploy the approved JSON. Retain reports/config versions, repeat after preprocessing changes.

False Accept Rate = accepted BAD / all BAD. False Reject Rate = rejected GOOD / all GOOD. Precision = true accepts / all accepts. Recall = true accepts / all GOOD. Accuracy = correct / total. Confusion matrix rows GOOD/BAD, columns ACCEPT/RETAKE. Missing denominators become null, not invented zero accuracy. CLI requires both classes. Loss = configurable false-accept weight × FAR + false-reject weight × FRR. Weights should reflect business costs; grid supports threshold fields and is limited to 10000 combinations. No statistical confidence interval or target-domain guarantee is inferred from tiny datasets.

Invalid/corrupted dataset files abort evaluation, rather than silently counting technical failures as BAD. Reports contain filenames and metrics, not decoded values. Suggested thresholds reuse raw metrics; no decoder change is simulated. Changing preprocessing requires a fresh evaluation. Real-world performance cannot be inferred from `demo/synthetic`.

## Tomorrow's GOOD/BAD intake

No customer dataset is present as of 2026-10-07. Thresholds were not selected during the final audit. Put labelled originals in good/bad, retain capture/device/asset/session metadata separately, and keep report output outside the dataset. Intake reads actual content with size bounds, records SHA256/dimensions, rejects unsafe symlinks/path escapes and conflicting cross-class exact duplicates. Same-class duplicates are reported for review. It does not detect near duplicates; split related assets/sessions manually before evaluation. HEIC/HEIF must be exported to a supported format without overwriting originals.

Run baseline without --grid first. Evaluation checks hashes again to detect changed inputs. JSON/CSV/HTML and debug copies remain private; decoded values are excluded. Debug names preserve the full source extension to prevent same-stem collisions. Only after real-data baseline and failure review should a separate calibration search be considered, followed by untouched holdout evaluation and manual approval. The empty current dataset fails intake with EMPTY_CLASS; it produces no invented accuracy.
