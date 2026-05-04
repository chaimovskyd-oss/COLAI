# AI module

V3 uses local CPU-friendly AI helpers:

- `mediapipe` Selfie Segmentation for person/subject masks.
- `mediapipe` Face Detection for faces, with OpenCV Haar fallback.
- Background blur / bokeh approximation using segmentation masks.
- Subject enhancement with masked contrast/sharpness.
- Face brighten and skin tone protection.
- Smart Auto Fix suggestions from histogram, saturation, subject coverage, and face brightness.
- Real-ESRGAN x4plus adapter for 2x/4x upscale, with Lanczos/Unsharp fallback.
- GFPGAN v1.4 adapter for face restoration, with local face-mask fallback.

The app remains usable if MediaPipe is unavailable. Segmentation falls back to a conservative central soft mask, and face detection falls back to OpenCV when possible.
Real-ESRGAN and GFPGAN weights are downloaded lazily into `smart_image_editor/models` when the tool is first used.

Future candidates:

- CodeFormer adapter as an alternative face restoration engine.
- Batch AI correction UI.
- Model settings dialog.
