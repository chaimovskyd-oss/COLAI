# Smart Collage Maker

Windows desktop collage generator — Python + PySide6.

---

## Features

### Core
- Project size presets (15×10, A4, A3, 30×40, 20×20, 50×70, 60×40 cm) + custom
- Image import via file picker and drag & drop (PNG / JPG / BMP / WebP)
- 7 automatic layout suggestions, **scored by aspect-ratio match** (best first)
- All images always appear in the collage — every image gets a cell, last row fills the full width
- Layout thumbnail previews in the suggestion panel
- Undo / Redo history

### Smart Automation
- Default import flow stays **fast**: images are arranged with basic aspect-ratio / orientation heuristics
- **Scan photos** is an explicit advanced step: it analyzes people/faces and re-arranges layouts accordingly
- **Face detection** with MediaPipe, with optional RetinaFace hook for stronger group-photo detection
- Smart crop preserves faces; no forced rotation to match cell orientation
- Low-resolution warning per cell
- Face-near-edge warning when a detected face is cropped close to the cell boundary
- **Smart Crop Analysis** with MediaPipe + YOLO11 person detection
- Face-safe / person-safe / combined safe regions
- Group photo, portrait, full-body, and no-people heuristics for safer placement
- Smart crop debug overlay and analyzed-image indicator

### Manual Editing
- Click a cell to select it; drag to pan the image inside the frame
- Mouse wheel to zoom in/out per cell
- Rotation in **90° clockwise / counter-clockwise** steps per image
- Swap image positions between two cells (Swap mode button)
- Replace image in cell (right-click → "Replace image…")
- Remove image from cell (right-click → "Remove image from cell")
- Reset single image or all images to smart-crop defaults

### Image Adjustments (per cell)
- Brightness (20 %–200 %)
- Contrast (20 %–200 %)
- Saturation (0 %–200 %)
- Sharpness (0 %–200 %)
- Black & White toggle
- Reset adjustments

### Canvas Style
- Corner radius (mm)
- Border width (mm) + colour picker
- Drop shadow (offset mm, opacity)
- Background colour
- Outer margin (px) and spacing between cells (px)

### Text / Caption
- Global text overlay (any text string)
- Font size (pt), colour, position (top / bottom / centre)
- Horizontal alignment (left / centre / right)
- Optional background box behind text

### Bleed & Safe Area
- Bleed (mm) — extends the export canvas; shown as red dashed guide in preview
- Safe area (mm) — shown as blue dashed guide in preview

### Export & Print
- Export at full DPI from original files (LANCZOS resampling — no quality loss)
- Formats: **JPG**, **PNG**, **PDF** (Pillow PDF, 300 DPI)
- **Direct print** via system print dialog (no intermediate export file needed)
- All adjustments (tone, rotation, style) applied at export quality

---

## Python Libraries Used

| Library | Purpose | Install |
|---------|---------|---------|
| **PySide6** | Qt6 UI framework — windows, widgets, paint, print | `pip install PySide6` |
| **Pillow** | Image loading, cropping, resizing, adjustments, PDF/PNG/JPG save | `pip install Pillow` |
| **MediaPipe** | Face detection (smart crop centering on faces) | `pip install mediapipe` |
| **NumPy** | Array conversion for MediaPipe image input | `pip install numpy` |
| **Ultralytics** | YOLO11 person detection and scene-aware crop protection | `pip install ultralytics` |

### Optional / Future
| Library | Purpose |
|---------|---------|
| **retina-face** | Stronger face detection for group photos and small / angled faces |
| **YOLO11 pose / segmentation** | Future body landmarks, masks, and deeper safe-region logic |
| **PyInstaller** | Package app as standalone Windows `.exe` |
| **opencv-python** | Alternative image I/O and face detection |

---

## Installation

```bash
pip install -r requirements.txt
python main.py
```

### Smart Crop setup notes

1. Install the requirements with `pip install -r requirements.txt`.
2. If `ultralytics` fails to install on Windows, install/update PyTorch first from the official PyTorch installer, then run `pip install ultralytics`.
3. On the first run with YOLO11 enabled, Ultralytics downloads `yolo11n.pt` automatically.
4. Optional advanced face detection: install `retina-face` if you want stronger group-photo scanning.
5. If `retina-face` fails on your Python version, keep the app on the built-in MediaPipe path or use a Python 3.10/3.11 environment for advanced scanning.
6. If YOLO11 is unavailable, the app still runs with MediaPipe-based face protection, but person/group understanding is reduced.

### Quick vs Scanned flow

1. Import photos and use **Generate layouts** for the fast default flow.
2. Use **Scan selected photos** or **Scan all photos** when you want people-aware placement, face-aware crop protection, and stronger warnings.
3. After a scan, the layout engine uses the analysis results for placement scoring, not only for warnings.

Quick test set:

1. Close-up portrait: confirm the crop keeps breathing room around the face.
2. Group photo: confirm warnings appear in narrow cells and larger layouts rank better.
3. Full-body vertical photo: confirm taller cells score better and the subject is less likely to be cut.
4. No-people image: confirm cropping remains more flexible.

**requirements.txt**
```
PySide6>=6.6
Pillow>=10.0
mediapipe>=0.10
numpy>=1.24
```

> MediaPipe is optional — the app runs without it and falls back to centre-crop.

---

## Build Windows EXE

```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --name SmartCollageMaker main.py
```

---

## Architecture

```
collage_mvp/
├── main.py                      Entry point
└── app/
    ├── models/
    │   └── project.py           Data model (ProjectState, ImageState, CellRect, …)
    ├── core/
    │   ├── collage_engine.py    Layout generation & scoring
    │   ├── face_detector.py     MediaPipe face detection (optional)
    │   ├── smart_crop_service.py Smart crop analysis, YOLO11 person detection, crop safety
    │   └── exporter.py          High-res render → JPG / PNG / PDF
    ├── ui/
    │   ├── main_window.py       Main window & all panels
    │   └── canvas.py            Interactive collage canvas (preview, drag, swap)
    └── utils/
        └── image_utils.py       Cache, crop, adjustments, cell styling, text overlay
```

---

## Roadmap

- [ ] YOLO object detection (multi-subject awareness)
- [ ] Project save / load (JSON)
- [ ] Batch collage generation
- [ ] Product presets (canvas print, framed print, photo book)
- [ ] Per-cell style overrides (override global corner radius / border)
- [ ] AI-based layout recommendations
