# Алгоритм и ограничения

Version 1.0.0. Config version — SHA-256 первых 12 hex символов канонической типизированной конфигурации. Score — оценка по правилам, не вероятностная уверенность.

Валидация использует Pillow: фактический формат JPEG/PNG/WEBP, соответствие MIME, проверка целостности, лимиты байтов/пикселей, EXIF orientation. Декодер ZXing-C++ получает оригинальное разрешение. Попытки: original → grayscale → CLAHE → adaptive threshold → sharpened, с остановкой при decode. Ошибочные результаты ZXing могут дать геометрию без значения. Если ничего не обнаружено, OpenCV пытается локализовать 1D-кандидат морфологией. Такая локализация может ошибаться; decode обязателен.

Для метрик изображение уменьшается максимум до 2400 px по длинной стороне. Метрики считаются на ROI в этом разрешении; пороги следует калибровать с той же стратегией. Координаты ответа относятся к оригиналу. Bounding box — консервативный axis-aligned envelope; rotated labels могут выглядеть больше. Ширина считается по горизонтали фотографии: вертикальные штрихкоды могут получать излишний RETAKE. Система не доказывает видимость всей наклейки/quiet zones только по decoded polygon.

| Parameter | Initial default | Meaning |
|---|---:|---|
| sharpness_min / critical | 60 / 15 | Laplacian variance target / hard floor |
| brightness_min / max | 45 / 240 | ROI mean luminance 0–255 |
| dark_pixel_max | 0.75 | Fraction with luminance <25 |
| overexposure_max | 0.85 | Fraction with luminance ≥250 |
| contrast_min | 30 | ROI luminance standard deviation |
| barcode_area_min | 0.015 | Bounding box area / image area |
| barcode_width_min | 0.15 | Box width / image width |
| edge_margin_min | 0.02 | Relative safety margin |
| glare_max | 0.15 | Structural bright-gap indicator |
| perspective_max | 0.45 | Opposing polygon side asymmetry |
| quality_score_min | 75 | Required score |
| decode_weight | 0.35 | Score contribution from decoding |

Hard reject: no barcode, decode failure, multiple readable barcodes, critical blur, too-small box/width, box touching image boundary, too-dark exposure, excessive overexposure. Near-edge proximity does not reject an otherwise readable code. Soft signals: moderate blur, contrast, glare, perspective. Successful decode is required regardless of score.

Score: 35% decoded signal, remaining 65% equally divided among normalized sharpness, relative size, contrast, exposure, glare, crop and perspective. Decode weight configurable. ACCEPT requires no hard failure and score ≥ configured minimum. Issues ordered by actionable importance. ACCEPT can carry advisory issues.

Glare heuristic searches wide saturated column gaps bordered by dark bars. Ordinary white background alone does not trigger it. It is orientation-sensitive and is NOT a reliable detector of every specular reflection. Perspective measures geometry asymmetry; camera rotation angle alone does not cause hard rejection. No reliable image motion direction estimator, whole-label detector, learned classifier, perspective rectification or live-preview server guidance is claimed. These are future isolated extensions after dataset analysis. An optional classifier should implement a typed interface and feed Decision Engine as another signal; barcode decode remains mandatory.

There is no target-domain accuracy measurement. Initial thresholds require calibration against target-domain images.

ZXing may canonicalize UPC-A to equivalent EAN-13 (leading zero). Integrations should normalize inventory identifiers according to their own catalogue rules, rather than assume a specific decoder string representation. Synthetic regression verifies Code 128, Code 39, EAN-13/8, UPC-A, ITF, QR and Data Matrix. UPC-E now has a real generated regression fixture; ZXing expands its text to a GTIN-13 representation while retaining the UPC-E type.

Audit release 1.0.1 fixes validation, resource lifecycle and input handling. Decision rules, weights and thresholds remain unchanged. Coordinates use the EXIF-normalized source image. Rotation 0/90/180/270 and all eight EXIF orientations have regression coverage.
