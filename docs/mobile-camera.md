# Mobile camera UX — 2026-10-08

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
