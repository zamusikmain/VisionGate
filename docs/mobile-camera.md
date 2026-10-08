# Mobile camera UX — 2026-10-08

## Capture assistance and retake flow

Optional live hints are now available while the camera is open, **off by default for each camera session**. They reuse frontend/src/live-preview.ts: one bounded check at a time, normally every 1.5 seconds, skipped while the page is hidden. A local canvas samples the whole preview at a maximum side of 160px. No preview API requests, uploads, logging, localStorage image storage or server-side preview analysis occur. Stopping/disabling the camera stops checks and clears the sampling canvas.

Darkness/overbrightness use approximate mean preview luminance (<55/>235). Possible blur uses mean absolute Laplacian edge response (<8), a low-detail indicator that can also fire on a smooth background or a small distant label. These are **uncalibrated browser hint parameters**, not backend thresholds or equivalent backend metrics. RU/EN text explicitly says preliminary hints can be wrong. There is no green/ACCEPT indication, no automatic capture/upload and no shutter gating by these hints. Readback failure silently leaves the camera usable. Capture continues at intrinsic full resolution and never includes the guide/hint overlays.

After API RETAKE, **Retake with camera** reuses openCamera to return directly to camera acquisition, clearing the old preview/result. **Choose another photo** returns to file/camera selection. Camera denial still offers upload fallback. Opening/replacing a photo cancels the old client request and invalidates stale callbacks.

Submission already had a disabled busy button; a synchronous request-generation lock now also prevents two submits in the same event before React has rendered the disabled state. Completion/error releases only its own lock. Technical retry and deliberate re-analysis after completion remain supported. This is an in-flight client safeguard, not server idempotency or cross-tab exactly-once submission; a client abort can occur after the server has started work. No backend contract was added.

### Mobile autofocus research and fallback

The active video track is queried through getCapabilities(). Only if it advertises continuous focus and implements applyConstraints() does the app request focusMode:'continuous' in advanced constraints, preserving existing constraints. The request is asynchronous and never delays/enables/disables capture. Unsupported APIs/modes and rejected constraints use the existing camera behavior without an error screen. getSettings().focusMode is checked when available: only a reported continuous mode receives the confirmed-mode message; otherwise the UI says autofocus was requested. Neither means the photographed label is actually in focus.

No manual focus distance, tap-to-focus/pointsOfInterest, vendor-specific APIs, torch/exposure change or new permissions are introduced. Browser/track support must be probed at runtime; a specific phone brand/browser is not promised to support focus control. Background camera focus may still work without exposed focusMode. Primary references: [W3C Image Capture explainer](https://github.com/w3c/mediacapture-image/blob/main/explainer.md), [W3C constraints](https://www.w3.org/TR/mediacapture-streams/).

### Latest checks

**35 frontend tests passed**, including eight assistance/retake/submission additions; TypeScript/Vite build passed locally and in Docker; both Compose services healthy. Tests cover opt-in/no-network samples, RU/EN, stopping timers, local readback failure, capture despite darkness, focus capability/request/rejection/unconfirmed-setting fallback, same-event duplicate submission, retry/replacement and RETAKE camera-denial fallback. Existing full-frame capture, orientation/resize, stream lifecycle and server-result tests pass unchanged.

Browser inspection used a synthetic blur image through the real local API and verified RETAKE actions at 320x568,390x844,430x932 and 844x390, with no horizontal overflow; RU/EN and replacement flow verified. Live hint UI/stream sampling and autofocus are tested with simulated tracks, not physical camera capture. Backend/config/Decision Engine/API unchanged; threshold SHA256 unchanged.

Physical validation checklist: Samsung/Android Chrome and iPhone Safari over HTTPS; exposed capabilities/settings vs actual near/far focus; low light, glare, textured and plain labels; hint false alarms, battery/thermal cost; rotation/backgrounding; repeated RETAKE and permission denial; preview-vs-captured-photo difference. Keep hints advisory until real-device/data evaluation; no thresholds or quality rules were tuned.

The camera now guides placement of the **whole label and its edges**, rather than only the barcode strip. RU/EN instructions ask the user to hold steady and avoid glare, and explicitly say the guide is visual and the full frame is captured.

The decorative dashed rectangle has visible corner markers, pointer-events:none and aria-hidden. For a live camera, its bounds are calculated inside the actual object-fit:contain video rectangle, including portrait/landscape letterboxing. ResizeObserver and video metadata/canplay/resize events recalculate it when screen or stream dimensions change. A window-resize fallback works when ResizeObserver is unavailable. Until intrinsic video dimensions exist, the live overlay is hidden; capture readiness remains the existing canplay check.

The camera viewport scales with the small viewport height where supported and falls back to vh. Mobile controls have at least 48px target height. On short screens the page can scroll naturally; there is no forced fullscreen camera or sticky shutter. A clean idle guide is shown before camera permission, without duplicated text overlapping its border. Instructions are outside the video and associated with it via aria-describedby. They disappear on the captured/uploaded photo preview.

**Capture and analysis are unchanged:** the canvas still uses video.videoWidth/video.videoHeight and drawImage(video,0,0). No guide coordinates reach canvas, upload data or backend. The guide is not drawn into the photograph, no crop is performed and no barcode position/completeness check disables the shutter. Busy/readiness conditions remain unchanged. Backend, thresholds, metrics, Decision Engine, API and ACCEPT/RETAKE were not modified.

## Verification

- **27 frontend tests passed**, including eight new cases: screen sizes 320x568, 390x844, 430x932, 844x390 and 1024x768, portrait/landscape/square video geometry, missing dimensions, RU/EN, resize/stream orientation, observer cleanup and full 720x1280 capture independent of guide bounds.
- Existing camera denial/fallback, late-capture cleanup, API decisions, localization and upload regression tests still pass.
- TypeScript/Vite production build passed locally and in frontend Docker. Both Compose services healthy.
- Browser inspected RU/EN idle screens at those five viewport sizes. No horizontal overflow; rendered guide has pointer-events:none. Instructions wrap and controls remain readable. Live video/capture geometry is verified with simulated streams in frontend tests, not physical phone camera sessions.
- No changes in backend/config/analysis files. Threshold SHA256 remains e346e8121e8419c5e630bb0289ab41f688d6a1f067f297551f87072a3e25e1fc.

## Remaining limits

Physical Samsung/Android/iPhone hardware, rear-camera selection, autofocus/exposure, mobile browser permission dialogs and actual device rotation still require on-device checks over HTTPS. A visual guide cannot guarantee complete visibility or image quality; the current analysis behavior and offline Barcode Integrity research remain as before. Label shapes vary: the guide is a flexible positioning cue, not an enforced crop/template. No customer photographs were needed or committed.
