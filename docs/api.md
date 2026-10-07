# Integration API

Base URL local pilot: `http://localhost:8080`. OpenAPI: `/openapi.json`, Swagger: `/docs`.

```sh
curl -F "image=@photo.jpg;type=image/jpeg" http://localhost:8080/api/v1/analyze
```

POST `/api/v1/analyze` accepts one multipart field `image`. Formats JPEG/PNG/WEBP; limit 12 MiB, 24 million pixels. Response is strictly typed: decision, quality_score, barcode detected/decoded/type/value/bounding_box/polygon/decode_method/count; ROI/global metrics; issues and recommendations; processing_time_ms, timestamp, request_id, algorithm_version, config_version. Box is `[x1,y1,x2,y2]` in EXIF-orientation-normalized source pixels, before analysis downscaling.

RETAKE is HTTP 200, a normal business outcome. Invalid format/MIME/dimensions/corrupted image: HTTP 422. Oversize: HTTP 413. System failure: HTTP 500 with `SYSTEM_ERROR` and request ID. `X-Request-ID` is server-generated. Never trust ACCEPT from UI alone; corporate submission flow must enforce the final backend result and bind it to the exact image (submission storage/signatures are integration responsibilities).

GET `/api/v1/health`: liveness and algorithm version. GET `/api/v1/config`: thresholds, schema/ranges, version, initial calibration notice. PUT `/api/v1/config`: validated full threshold JSON, requires `X-Admin-Token`. GET `/api/v1/history`: latest 100 analyses, requires `X-Admin-Token`; decoded values redacted. Missing ADMIN_TOKEN disables admin operations. API is language-independent; localize recommendation codes in the client.

Recommendations: FIND_BARCODE, ONE_BARCODE, MOVE_CLOSER, SHOW_ENTIRE_BARCODE, HOLD_STEADY, ADD_LIGHT, REDUCE_LIGHT, IMPROVE_CONTRAST, REDUCE_GLARE, ALIGN_CAMERA, MAKE_READABLE, RETAKE.

Analyze endpoint has no SSO in this local pilot. Place it behind a trusted authenticated gateway before wider corporate exposure. Decoded inventory values may be sensitive: avoid response logging in gateways. Runtime original-image storage is disabled by default; opt-in retention uses private UUID files without HTTP routes. Debug/export reports are offline private artifacts.

## Final audit input and capacity contract

Exactly one image field is accepted; duplicate files and extra multipart fields are rejected. Actual file content is checked independently of filename. Empty/octet-stream MIME is allowed only for valid JPEG/PNG/WEBP content; explicit mismatches are rejected. HEIC/HEIF is unsupported (422 UNSUPPORTED_HEIF); export JPEG/PNG or capture a new photo. Animated inputs are rejected. Transparency is flattened onto white. All eight EXIF orientations are normalized.

Incomplete/malformed multipart and interrupted oversized uploads close spooled files. Validation responses have safe codes and opaque request IDs; identifiers may be UUIDs from the backend or hex IDs from Nginx. Nginx oversize responses are also JSON. BUSY (503) means retry later, not a quality rejection. MAX_CONCURRENT_ANALYSES defaults to two per process; Compose runs two workers, allowing four native analyses. Client timeout is 60 seconds. This pilot does not implement submission idempotency: a deliberate repeat creates a new analysis/request ID.
