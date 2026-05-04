from __future__ import annotations

import math
from copy import deepcopy
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QMouseEvent,
    QPainter, QPaintEvent, QPen, QPixmap,
)
from PySide6.QtWidgets import QMenu, QTextEdit, QWidget

from app.models.project import CellRect, ProjectState, TextOverlay
from app.utils.image_utils import (
    apply_adjustments,
    apply_cell_shape,
    crop_with_bg,
    fit_crop_box,
    get_preview_image,
    has_visible_adjustments,
    make_background_pil,
    make_debug_overlay_lines,
    mm_to_px,
    pil_to_qpixmap,
    render_element_qt,
    render_styled_cell,
    render_text_overlay_qt,
    shaped_pan_bounds,
)
from app.utils.cell_edge_render import (
    SOFT_FADE_MIN_ZOOM,
    detect_neighbor_sides,
    expand_crop_box_for_padding,
    resolve_render_padding,
)

_CANVAS_BG = QColor(50, 50, 50)

# Drag index sentinels
_DRAG_NONE  = -2   # nothing being dragged
_DRAG_DRAFT = -1   # dragging the draft overlay

# Free Transform constants
_HANDLE_HALF = 6    # half-size of handle square in widget pixels
_ROTATE_ZONE = 16   # extra pixels outside corner where rotation cursor appears

# Mapping handle name → Qt cursor
# Corner handles = zoom in/out (diagonal arrows)
# Edge handles = pan in one axis (open hand)
_HANDLE_CURSORS = {
    'tl': Qt.SizeFDiagCursor, 'br': Qt.SizeFDiagCursor,
    'tr': Qt.SizeBDiagCursor, 'bl': Qt.SizeBDiagCursor,
    'tc': Qt.OpenHandCursor,  'bc': Qt.OpenHandCursor,
    'ml': Qt.OpenHandCursor,  'mr': Qt.OpenHandCursor,
}

# Per-handle (sign_x, sign_y): positive = outward = zoom in for corners,
# outward = pan shift for edges.
# Corners have both signs non-zero; edges have one zero.
_HANDLE_SIGN = {
    'tl': (-1, -1), 'tc': (0, -1), 'tr': (1, -1),
    'ml': (-1,  0),                 'mr': (1,  0),
    'bl': (-1,  1), 'bc': (0,  1), 'br': (1,  1),
}


# ---------------------------------------------------------------------------
# Inline text editor
# ---------------------------------------------------------------------------

class _InlineEditor(QTextEdit):
    committed = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.SubWindow)
        self.setStyleSheet(
            'QTextEdit {'
            '  background: rgba(255,255,255,200);'
            '  border: 2px dashed #4488cc;'
            '  padding: 3px;'
            '}'
        )
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._committing = False

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._do_commit()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        self._do_commit()
        super().focusOutEvent(event)

    def _do_commit(self) -> None:
        if not self._committing:
            self._committing = True
            self.committed.emit(self.toPlainText())
            self.hide()
            self._committing = False


# ---------------------------------------------------------------------------
# Canvas widget
# ---------------------------------------------------------------------------

class CollageCanvas(QWidget):
    cellSelected        = Signal(int)
    swapPerformed       = Signal()
    cellPanChanged      = Signal()          # emitted after cell image is panned/zoomed
    replaceImageRequested = Signal(int)
    removeImageFromCell = Signal(int)
    editImageInColorLab = Signal(int)   # right-click → Open in Color Lab
    editImageInPhotoshop = Signal(int)  # right-click -> Open original file in Photoshop
    textMoved           = Signal()          # any overlay moved
    textContentChanged  = Signal(str)       # draft edited inline
    textSelected        = Signal(int)       # committed overlay clicked (-1 = draft)
    textRemoveRequested = Signal(int)       # right-click → remove overlay
    elementSelected     = Signal(int)       # element overlay clicked
    displayZoomChanged  = Signal(float)    # canvas display-zoom changed
    panChanged          = Signal()         # canvas pan offset changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Optional[ProjectState] = None

        self._preview_pixmap: Optional[QPixmap] = None
        self._base_pixmap:    Optional[QPixmap] = None
        self._drag_cell_pixmap: Optional[QPixmap] = None
        self._drag_cell_widget_rect: QRect = QRect()

        # Text overlay tracking
        # _draft_rect: pixmap-coord rect of the draft overlay
        # _overlay_rects: pixmap-coord rects of committed overlays (same indexing)
        self._draft_rect: Optional[QRect] = None
        self._overlay_rects: List[Optional[QRect]] = []

        # _text_drag_index: _DRAG_NONE / _DRAG_DRAFT / ≥0 (committed index)
        self._text_drag_index: int = _DRAG_NONE

        self._inline_editor: Optional[_InlineEditor] = None
        self._inline_target_index: int = _DRAG_NONE   # which overlay the editor is editing

        self.selected_cell_index: int = -1
        self.drag_active: bool = False
        self.last_pos: QPoint = QPoint()
        self.scale_x: float = 1.0
        self.scale_y: float = 1.0

        self.swap_mode: bool = False
        self._swap_source: int = -1
        self._swap_circle_source: int = -1   # quick-swap: index of first-clicked cell circle
        self._compare_eye_rects: dict[int, QRect] = {}
        self._compare_preview_cell: int = -1

        self._display_zoom: float = 1.0
        self._canvas_pan: QPoint = QPoint(0, 0)   # viewport pan in widget pixels
        self._snap_lines: list = []

        # Free Transform state
        self._ft_handle: Optional[str] = None       # handle/zone name being dragged
        self._ft_drag_start: QPoint = QPoint()      # mouse pos at drag start
        self._ft_cell_orig: tuple = ()              # (x,y,w,h) of cell at drag start
        self._ft_hover: Optional[str] = None        # handle under mouse (for cursor)

        # Tree divider drag state
        self._tree_drag_node = None             # SplitNode being dragged, or None
        self._tree_drag_start_canvas: Tuple[float, float] = (0.0, 0.0)
        self._tree_drag_start_ratio: float = 0.0
        self._tree_hover_node = None            # SplitNode under mouse (for cursor/highlight)

        # Element overlay state
        self._element_rects: List[tuple] = []   # (x,y,w,h) in pixmap coords per element
        self._selected_element: int = -1
        self._element_drag_active: bool = False
        self._element_drag_start: QPoint = QPoint()
        self._element_orig_pos: tuple = ()      # (pos_x_frac, pos_y_frac) at drag start
        self._element_rotate_active: bool = False
        self._element_rotate_start_angle: float = 0.0
        self._element_rotate_orig_deg: float = 0.0

        self.setMinimumSize(600, 400)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_project(self, project: ProjectState) -> None:
        self.project = project
        self._canvas_pan = QPoint(0, 0)
        self.selected_cell_index = -1
        self.refresh_preview()

    def set_swap_mode(self, enabled: bool) -> None:
        self.swap_mode = enabled
        self._swap_source = -1
        self.setCursor(QCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor))
        self.update()

    def refresh_preview(self) -> None:
        self._base_pixmap = None
        self._drag_cell_pixmap = None
        if not self.project:
            self._preview_pixmap = None
            self.update()
            return
        self._preview_pixmap = self._build_full_pixmap(exclude_cell=-1)
        self.update()

    def _sync_tree_leaves_from_layout(self) -> None:
        """Persist manual cell/image assignments back into the dynamic layout tree."""
        if not self.project or not self.project.selected_layout:
            return
        layout = self.project.selected_layout
        tree = getattr(layout, 'tree', None)
        if tree is None:
            return
        try:
            from app.core.layout_tree_engine import collect_leaves
            leaves = collect_leaves(tree.root)
        except Exception:
            return
        for idx, leaf in enumerate(leaves):
            if idx < len(layout.cells):
                leaf.image_index = layout.cells[idx].image_index

    def _dynamic_cells_from_tree_preserving_images(self, tree, canvas_w: int, canvas_h: int):
        """Rebuild dynamic cells without undoing manual image swaps."""
        if not self.project or not self.project.selected_layout:
            from app.core.layout_tree_engine import cells_from_tree
            return cells_from_tree(tree, canvas_w, canvas_h)
        old_assignments = [cell.image_index for cell in self.project.selected_layout.cells]
        from app.core.layout_tree_engine import cells_from_tree, collect_leaves
        cells = cells_from_tree(tree, canvas_w, canvas_h)
        leaves = collect_leaves(tree.root)
        for idx, img_idx in enumerate(old_assignments):
            if idx < len(cells):
                cells[idx].image_index = img_idx
            if idx < len(leaves):
                leaves[idx].image_index = img_idx
        return cells

    def set_compare_preview(self, cell_index: int) -> None:
        if cell_index == self._compare_preview_cell:
            return
        self._compare_preview_cell = cell_index
        self.refresh_preview()

    def clear_compare_preview(self) -> None:
        if self._compare_preview_cell < 0:
            return
        self._compare_preview_cell = -1
        self.refresh_preview()

    def zoom_in(self):
        self.zoom_to(min(4.0, self._display_zoom * 1.15))

    def zoom_out(self):
        self.zoom_to(max(0.1, self._display_zoom / 1.15))

    def fit_to_screen(self):
        self._canvas_pan = QPoint(0, 0)
        self.zoom_to(1.0)

    def zoom_to(self, value: float) -> None:
        """Set canvas display-zoom, clamp pan, emit signals."""
        self._display_zoom = max(0.1, min(4.0, value))
        self._clamp_pan()
        self.displayZoomChanged.emit(self._display_zoom)
        self.panChanged.emit()
        self.update()

    def set_pan(self, px: int, py: int) -> None:
        """Set absolute pan offset (widget pixels), clamped to bounds."""
        self._canvas_pan = QPoint(px, py)
        self._clamp_pan()
        self.panChanged.emit()
        self.update()

    def _clamp_pan(self) -> None:
        pix = self._preview_pixmap or self._base_pixmap
        if not pix:
            self._canvas_pan = QPoint(0, 0)
            return
        available = self.rect().adjusted(12, 12, -12, -12)
        scaled = pix.size().scaled(available.size(), Qt.KeepAspectRatio)
        w = int(scaled.width()  * self._display_zoom)
        h = int(scaled.height() * self._display_zoom)
        max_px = max(0, (w - available.width())  // 2)
        max_py = max(0, (h - available.height()) // 2)
        self._canvas_pan = QPoint(
            max(-max_px, min(max_px, self._canvas_pan.x())),
            max(-max_py, min(max_py, self._canvas_pan.y())),
        )

    def pan_bounds(self) -> tuple:
        """Return (max_pan_x, max_pan_y, current_pan_x, current_pan_y)."""
        pix = self._preview_pixmap or self._base_pixmap
        if not pix:
            return (0, 0, 0, 0)
        available = self.rect().adjusted(12, 12, -12, -12)
        scaled = pix.size().scaled(available.size(), Qt.KeepAspectRatio)
        w = int(scaled.width()  * self._display_zoom)
        h = int(scaled.height() * self._display_zoom)
        max_px = max(0, (w - available.width())  // 2)
        max_py = max(0, (h - available.height()) // 2)
        return (max_px, max_py, self._canvas_pan.x(), self._canvas_pan.y())

    # ------------------------------------------------------------------
    # PIL cell canvas
    # ------------------------------------------------------------------

    def _render_spacing_inset(self, logical_w: int, logical_h: int) -> float:
        if not self.project:
            return 0.0
        settings = self.project.settings
        if not getattr(settings, 'soft_fade_spacing_override_enabled', False):
            return 0.0
        base_spacing = float(getattr(settings, 'spacing_px', 0))
        target_spacing = float(getattr(settings, 'soft_fade_spacing_override_px', base_spacing))
        delta = (target_spacing - base_spacing) / 2.0
        max_shrink = max(0.0, min(logical_w, logical_h) / 2.0 - 1.0)
        return max(-max(logical_w, logical_h), min(max_shrink, delta))

    def _cell_render_rect(self, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
        inset = self._render_spacing_inset(w, h)
        rx = int(round(x + inset))
        ry = int(round(y + inset))
        rw = max(1, int(round(w - inset * 2.0)))
        rh = max(1, int(round(h - inset * 2.0)))
        return rx, ry, rw, rh

    def _cell_render_padding(self, cell: CellRect, width: int, height: int) -> tuple[int, int, int, int]:
        if not self.project or not self.project.selected_layout:
            return (0, 0, 0, 0)
        settings = self.project.settings
        if not getattr(settings, 'soft_fade_enabled', False):
            return (0, 0, 0, 0)
        if getattr(self.project.selected_layout, 'shape', ''):
            # TODO: support soft fade together with whole-layout masks once we
            # can feather them without changing current shape-layout behaviour.
            return (0, 0, 0, 0)
        if getattr(cell, 'edge_style', 'hard') == 'torn_paper':
            return (0, 0, 0, 0)
        if getattr(cell, 'shape_type', 'rectangle') != 'rectangle':
            # TODO: support shape-aware feathered slot masks without changing
            # the current per-slot clipping semantics.
            return (0, 0, 0, 0)
        scale_x = width / max(1.0, float(cell.w))
        scale_y = height / max(1.0, float(cell.h))
        scale = min(scale_x, scale_y)
        mode = getattr(settings, 'soft_fade_mode', 'soft_edge')
        softness_px = float(getattr(settings, 'soft_fade_amount_px', 16)) * scale
        overlap_px = float(getattr(settings, 'soft_fade_overlap_px', 28)) * scale
        overlap_sides = getattr(settings, 'soft_fade_overlap_sides', getattr(settings, 'soft_fade_sides', 'all'))
        auto_sides = None
        if overlap_sides == 'auto_neighbors':
            cells = self.project.selected_layout.cells
            try:
                cell_index = cells.index(cell)
            except ValueError:
                cell_index = -1
            auto_sides = detect_neighbor_sides(
                cells,
                cell_index,
                max_gap=max(
                    float(getattr(settings, 'spacing_px', 0)) + float(getattr(settings, 'soft_fade_overlap_px', 0)),
                    float(getattr(settings, 'soft_fade_overlap_px', 0)),
                ) * scale,
            )
        return resolve_render_padding(
            'soft_fade',
            mode,
            softness_px,
            overlap_px,
            overlap_sides if mode == 'overlap_fade' else getattr(settings, 'soft_fade_sides', 'all'),
            width,
            height,
            auto_neighbor_sides=auto_sides,
        )

    def _render_zoom_for_cell(self, state) -> float:
        if not self.project:
            return getattr(state, 'zoom', 1.0)
        if getattr(self.project.settings, 'soft_fade_enabled', False):
            return max(float(getattr(state, 'zoom', 1.0)), SOFT_FADE_MIN_ZOOM)
        return float(getattr(state, 'zoom', 1.0))

    def _focus_on_cell(self, cell_index: int) -> None:
        if not self.project or not self.project.selected_layout:
            return
        if cell_index < 0 or cell_index >= len(self.project.selected_layout.cells):
            return
        pix = self._preview_pixmap or self._base_pixmap
        if not pix:
            return

        cell = self.project.selected_layout.cells[cell_index]
        available = self.rect().adjusted(12, 12, -12, -12)
        if available.isEmpty():
            return
        scaled = pix.size().scaled(available.size(), Qt.KeepAspectRatio)
        base_target_w = max(1, scaled.width())
        base_target_h = max(1, scaled.height())
        cell_w_at_100 = max(1.0, cell.w * base_target_w / max(1, self.project.settings.canvas_px[0]))
        cell_h_at_100 = max(1.0, cell.h * base_target_h / max(1, self.project.settings.canvas_px[1]))
        target_zoom = min(
            4.0,
            max(
                1.0,
                min(
                    available.width() * 0.8 / cell_w_at_100,
                    available.height() * 0.8 / cell_h_at_100,
                ),
            ),
        )
        self.zoom_to(target_zoom)

        target_w = int(base_target_w * target_zoom)
        target_h = int(base_target_h * target_zoom)
        cell_center_x = (cell.x + cell.w / 2.0) * target_w / max(1, self.project.settings.canvas_px[0])
        cell_center_y = (cell.y + cell.h / 2.0) * target_h / max(1, self.project.settings.canvas_px[1])
        target_left_no_pan = available.x() + (available.width() - target_w) // 2
        target_top_no_pan = available.y() + (available.height() - target_h) // 2
        desired_pan_x = int(round(self.rect().center().x() - (target_left_no_pan + cell_center_x)))
        desired_pan_y = int(round(self.rect().center().y() - (target_top_no_pan + cell_center_y)))
        self.set_pan(desired_pan_x, desired_pan_y)

    def _build_cell_canvas(self, exclude_cell: int = -1):
        assert self.project is not None
        settings = self.project.settings
        width, height = settings.canvas_px
        scale = min(1.0, 1400 / max(width, height))
        pw = max(1, int(width * scale))
        ph = max(1, int(height * scale))
        sx = pw / width
        sy = ph / height

        def sty(mm):
            return max(0, int(round(mm_to_px(mm, settings.dpi) * scale)))

        corner_r   = sty(settings.corner_radius_mm)
        border_w   = sty(settings.border_width_mm)
        shadow_off = sty(settings.shadow_offset_mm)
        shadow_blur= sty(settings.shadow_blur_mm)

        canvas = make_background_pil(pw, ph, settings)
        draw   = ImageDraw.Draw(canvas)
        layout = self.project.selected_layout
        is_shaped = bool(layout and getattr(layout, 'shape', ''))

        if layout:
            draw_items = sorted(
                enumerate(layout.cells),
                key=lambda item: (int(getattr(item[1], 'z_index', 0)), item[0]),
            )
            for idx, cell in draw_items:
                x = int(round(cell.x * sx))
                y = int(round(cell.y * sy))
                w = max(1, int(round(cell.w * sx)))
                h = max(1, int(round(cell.h * sy)))
                render_x, render_y, render_w, render_h = self._cell_render_rect(x, y, w, h)
                if idx == exclude_cell:
                    pad_l, pad_t, pad_r, pad_b = self._cell_render_padding(cell, render_w, render_h)
                    draw.rectangle([render_x - pad_l, render_y - pad_t, render_x + render_w + pad_r - 1, render_y + render_h + pad_b - 1],
                                   fill=settings.background_rgb, outline=(180,180,180), width=1)
                    continue
                if cell.image_index is not None and cell.image_index < len(self.project.images):
                    state = self.project.images[cell.image_index]
                    try:
                        cached = get_preview_image(state.path, state.rotation)
                        cell_shape  = getattr(cell, 'shape_type', 'rectangle')
                        cell_params = getattr(cell, 'shape_params', {})
                        has_cell_shape = bool(cell_shape and cell_shape != 'rectangle')
                        # For shaped cells we allow the image to bleed outside the
                        # crop box (crop_with_bg fills outside pixels with bg colour);
                        # for the whole-layout shape mask we do the same.
                        clamp_crop = not (is_shaped or has_cell_shape)
                        render_zoom = self._render_zoom_for_cell(state)
                        crop   = fit_crop_box(cached.size, (w,h), state.pan_x, state.pan_y, render_zoom,
                                              clamp=clamp_crop)
                        fade_padding = self._cell_render_padding(cell, render_w, render_h)
                        if any(fade_padding):
                            env_w = render_w + fade_padding[0] + fade_padding[2]
                            env_h = render_h + fade_padding[1] + fade_padding[3]
                            env_crop = expand_crop_box_for_padding(crop, (w, h), fade_padding)
                            rend = crop_with_bg(cached, env_crop, settings.background_rgb)
                            rend = rend.resize((env_w, env_h), Image.Resampling.BILINEAR)
                        elif is_shaped or has_cell_shape:
                            rend = crop_with_bg(cached, crop, settings.background_rgb)
                            rend = rend.resize((render_w,render_h), Image.Resampling.BILINEAR)
                        else:
                            rend = cached.crop(crop)
                            rend = rend.resize((render_w,render_h), Image.Resampling.BILINEAR)
                        if idx != self._compare_preview_cell:
                            rend = apply_adjustments(rend, state)
                        if getattr(settings, 'smart_crop_debug', False) and getattr(state, 'analysis', None):
                            ddraw = ImageDraw.Draw(rend)
                            for label, rect, color in make_debug_overlay_lines(
                                state.analysis, crop, cached.size, (w, h)
                            ):
                                l, t, r, b = rect
                                ddraw.rectangle([l, t, r, b], outline=color, width=2)
                                ddraw.text((max(0, l + 2), max(0, t + 2)), label, fill=color)
                        # Apply per-cell shape mask before styled rendering
                        if has_cell_shape:
                            rend = apply_cell_shape(rend, cell_shape, cell_params,
                                                    settings.background_rgb)
                            cell_corner_r = 0   # shape mask already handles clipping
                        else:
                            cell_corner_r = corner_r
                        canvas = render_styled_cell(
                            canvas, render_x, render_y, render_w, render_h, rend,
                            corner_radius=cell_corner_r, border_width=border_w,
                            border_color=settings.border_color_rgb,
                            shadow_enabled=(
                                settings.shadow_enabled
                                or getattr(cell, 'edge_style', '') == 'torn_paper'
                                or getattr(cell, 'shape_type', '') == 'ring_segment'
                            ),
                            shadow_offset=shadow_off, shadow_blur=shadow_blur,
                            shadow_opacity=settings.shadow_opacity,
                            edge_style=getattr(cell, 'edge_style', 'hard') if getattr(cell, 'edge_style', '') == 'torn_paper' else 'soft_fade',
                            fade_padding=fade_padding,
                            fade_curve=getattr(settings, 'soft_fade_curve', 'smooth'),
                            rotation_deg=getattr(cell, 'rotation_deg', 0.0),
                            mask_seed=getattr(cell, 'mask_seed', idx),
                        )
                        # render_styled_cell may return a new canvas object (e.g. RGBA
                        # conversion for shadows/rounded corners). Refresh draw so that
                        # any subsequent drawing lands on the current canvas, not the old one.
                        draw = ImageDraw.Draw(canvas)
                        continue
                    except Exception:
                        pass
                # Text cell
                if cell.cell_text:
                    bg = cell.cell_bg_rgb or settings.background_rgb
                    draw.rectangle([x, y, x+w-1, y+h-1], fill=bg)
                    try:
                        from PIL import ImageFont
                        try:
                            fnt = ImageFont.truetype(cell.cell_text_font + '.ttf', max(8, int(cell.cell_text_size_pt * scale * 96 / 72)))
                        except Exception:
                            fnt = ImageFont.load_default()
                        bbox = draw.textbbox((0, 0), cell.cell_text, font=fnt)
                        tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
                        tx = x + (w - tw) // 2
                        ty = y + (h - th) // 2
                        draw.text((tx, ty), cell.cell_text, font=fnt, fill=cell.cell_text_color)
                    except Exception:
                        pass
                    continue
                draw.rectangle([x, y, x+w-1, y+h-1], outline=(190,190,190), width=2)
                draw.line([x, y, x+w, y+h], fill=(200,200,200), width=1)
                draw.line([x+w, y, x, y+h], fill=(200,200,200), width=1)

        # Apply shape mask if this is a shaped layout
        if layout and getattr(layout, 'shape', ''):
            from app.utils.image_utils import apply_shape_mask
            canvas = apply_shape_mask(canvas, layout.shape, settings, scale=scale)

        return canvas, pw, ph, sx, sy

    def _build_full_pixmap(self, exclude_cell: int = -1) -> QPixmap:
        canvas, pw, ph, sx, sy = self._build_cell_canvas(exclude_cell)
        self.scale_x = sx
        self.scale_y = sy
        pixmap = pil_to_qpixmap(canvas)

        if not self.project:
            self._draft_rect = None
            self._overlay_rects = []
            return pixmap

        # Render element overlays (above grid, below text overlays)
        self._element_rects = []
        cw, ch = self.project.settings.canvas_px
        for el in self.project.elements:
            pixmap, rect_t = render_element_qt(
                pixmap, el, cw, ch, scale=self.scale_x)
            self._element_rects.append(rect_t)

        # Render committed overlays first (bottom layers)
        self._overlay_rects = []
        for ov in self.project.text_overlays:
            if ov.text.strip():
                pixmap, rect_t = render_text_overlay_qt(
                    pixmap, ov, self.project.settings.dpi, scale=self.scale_x)
                self._overlay_rects.append(
                    QRect(rect_t[0], rect_t[1], rect_t[2], rect_t[3]) if rect_t else None)
            else:
                self._overlay_rects.append(None)

        # Draft overlay on top (semi-transparent hint while composing)
        draft = self.project.text_overlay
        if draft.text.strip():
            pixmap, rect_t = render_text_overlay_qt(
                pixmap, draft, self.project.settings.dpi, scale=self.scale_x)
            self._draft_rect = (
                QRect(rect_t[0], rect_t[1], rect_t[2], rect_t[3]) if rect_t else None)
        else:
            self._draft_rect = None

        return pixmap

    # ------------------------------------------------------------------
    # Single-cell fast render (drag)
    # ------------------------------------------------------------------

    def _render_single_cell_pixmap(self, cell_index: int) -> Tuple[QPixmap, QRect]:
        assert self.project and self.project.selected_layout
        cell = self.project.selected_layout.cells[cell_index]
        widget_rect = self._cell_rect_in_widget(cell)
        w, h = max(1, widget_rect.width()), max(1, widget_rect.height())
        settings = self.project.settings
        corner_r = max(0, int(round(mm_to_px(settings.corner_radius_mm, settings.dpi) * self.scale_x)))
        border_w = max(0, int(round(mm_to_px(settings.border_width_mm, settings.dpi) * self.scale_x)))
        render_x, render_y, render_w, render_h = self._cell_render_rect(widget_rect.x(), widget_rect.y(), w, h)
        fade_padding = self._cell_render_padding(cell, render_w, render_h)

        if cell.image_index is None or cell.image_index >= len(self.project.images):
            pix = QPixmap(w, h); pix.fill(QColor(220,220,220)); return pix, widget_rect

        state = self.project.images[cell.image_index]
        is_shaped    = bool(getattr(self.project.selected_layout, 'shape', ''))
        cell_shape   = getattr(cell, 'shape_type', 'rectangle')
        cell_params  = getattr(cell, 'shape_params', {})
        has_cell_shape = bool(cell_shape and cell_shape != 'rectangle')
        try:
            cached = get_preview_image(state.path, state.rotation)
            clamp_crop = not (is_shaped or has_cell_shape)
            render_zoom = self._render_zoom_for_cell(state)
            crop   = fit_crop_box(cached.size, (w,h), state.pan_x, state.pan_y, render_zoom,
                                  clamp=clamp_crop)
            if any(fade_padding):
                env_w = render_w + fade_padding[0] + fade_padding[2]
                env_h = render_h + fade_padding[1] + fade_padding[3]
                env_crop = expand_crop_box_for_padding(crop, (w, h), fade_padding)
                rend = crop_with_bg(cached, env_crop, settings.background_rgb)
                rend = rend.resize((env_w, env_h), Image.Resampling.BILINEAR)
            elif is_shaped or has_cell_shape:
                rend = crop_with_bg(cached, crop, settings.background_rgb)
                rend = rend.resize((render_w,render_h), Image.Resampling.BILINEAR)
            else:
                rend = cached.crop(crop)
                rend = rend.resize((render_w,render_h), Image.Resampling.BILINEAR)
            if cell_index != self._compare_preview_cell:
                rend = apply_adjustments(rend, state)
            if getattr(settings, 'smart_crop_debug', False) and getattr(state, 'analysis', None):
                ddraw = ImageDraw.Draw(rend)
                for label, rect, color in make_debug_overlay_lines(
                    state.analysis, crop, cached.size, (w, h)
                ):
                    l, t, r, b = rect
                    ddraw.rectangle([l, t, r, b], outline=color, width=2)
                    ddraw.text((max(0, l + 2), max(0, t + 2)), label, fill=color)
            if has_cell_shape:
                rend = apply_cell_shape(rend, cell_shape, cell_params,
                                        settings.background_rgb)
                cell_corner_r = 0
            else:
                cell_corner_r = corner_r
            tile = Image.new(
                'RGB',
                (render_w + fade_padding[0] + fade_padding[2], render_h + fade_padding[1] + fade_padding[3]),
                settings.background_rgb,
            )
            tile = render_styled_cell(tile, fade_padding[0], fade_padding[1], render_w, render_h, rend,
                                      corner_radius=cell_corner_r, border_width=border_w,
                                      border_color=settings.border_color_rgb,
                                      shadow_enabled=(
                                          getattr(cell, 'edge_style', '') == 'torn_paper'
                                          or getattr(cell, 'shape_type', '') == 'ring_segment'
                                      ),
                                      edge_style=getattr(cell, 'edge_style', 'hard') if getattr(cell, 'edge_style', '') == 'torn_paper'
                                      else ('soft_fade' if getattr(settings, 'soft_fade_enabled', False) else 'hard'),
                                      fade_padding=fade_padding,
                                      fade_curve=getattr(settings, 'soft_fade_curve', 'smooth'),
                                      rotation_deg=getattr(cell, 'rotation_deg', 0.0),
                                      mask_seed=getattr(cell, 'mask_seed', cell_index))
            padded_rect = QRect(
                render_x - fade_padding[0],
                render_y - fade_padding[1],
                render_w + fade_padding[0] + fade_padding[2],
                render_h + fade_padding[1] + fade_padding[3],
            )
            return pil_to_qpixmap(tile), padded_rect
        except Exception:
            pix = QPixmap(w, h); pix.fill(QColor(200,200,200)); return pix, widget_rect

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._clamp_pan()
        self.panChanged.emit()

    def _target_rect(self) -> QRect:
        pix = self._preview_pixmap or self._base_pixmap
        if not pix:
            return QRect()
        available = self.rect().adjusted(12, 12, -12, -12)
        scaled = pix.size().scaled(available.size(), Qt.KeepAspectRatio)
        w = int(scaled.width()  * self._display_zoom)
        h = int(scaled.height() * self._display_zoom)
        x = available.x() + (available.width()  - w) // 2 + self._canvas_pan.x()
        y = available.y() + (available.height() - h) // 2 + self._canvas_pan.y()
        return QRect(x, y, w, h)

    def _cell_rect_in_widget(self, cell: CellRect) -> QRect:
        rect = self._target_rect()
        pix  = self._preview_pixmap or self._base_pixmap
        if rect.isEmpty() or not pix:
            return QRect()
        sx = self.scale_x * rect.width()  / max(1, pix.width())
        sy = self.scale_y * rect.height() / max(1, pix.height())
        return QRect(
            rect.x() + int(round(cell.x * sx)),
            rect.y() + int(round(cell.y * sy)),
            max(1, int(round(cell.w * sx))),
            max(1, int(round(cell.h * sy))),
        )

    def _cell_has_compare_preview(self, idx: int) -> bool:
        if not self.project or not self.project.selected_layout:
            return False
        if idx < 0 or idx >= len(self.project.selected_layout.cells):
            return False
        cell = self.project.selected_layout.cells[idx]
        if cell.image_index is None or cell.image_index >= len(self.project.images):
            return False
        return has_visible_adjustments(self.project.images[cell.image_index])

    def _compare_eye_rect(self, cell_rect: QRect) -> QRect:
        size = max(18, min(26, min(cell_rect.width(), cell_rect.height()) // 4))
        return QRect(cell_rect.right() - size - 6, cell_rect.y() + 6, size, size)

    def _find_compare_eye_at(self, pos: QPoint) -> int:
        for idx, rect in self._compare_eye_rects.items():
            if rect.contains(pos):
                return idx
        return -1

    # Swap-circle radius (px). Circles smaller than this skip the circle.
    _SWAP_CIRCLE_R = 12
    _SWAP_CIRCLE_MIN_CELL = 44   # minimum cell dimension to show circle

    def _swap_circle_center(self, cell) -> Optional[QPoint]:
        """Return the widget-coordinate center of a cell's swap circle, or None."""
        cr = self._cell_rect_in_widget(cell)
        if cr.width() < self._SWAP_CIRCLE_MIN_CELL or cr.height() < self._SWAP_CIRCLE_MIN_CELL:
            return None
        return QPoint(cr.x() + cr.width() // 2, cr.y() + cr.height() // 2)

    def _find_swap_circle_at(self, pos: QPoint) -> int:
        """Return cell index whose swap circle contains *pos*, or -1."""
        if not self.project or not self.project.selected_layout:
            return -1
        r = self._SWAP_CIRCLE_R
        for idx, cell in enumerate(self.project.selected_layout.cells):
            c = self._swap_circle_center(cell)
            if c is None:
                continue
            dx, dy = pos.x() - c.x(), pos.y() - c.y()
            if dx * dx + dy * dy <= r * r:
                return idx
        return -1

    def _pixmap_rect_to_widget(self, r: QRect) -> QRect:
        """Convert a rect in pixmap coordinates to widget coordinates."""
        target = self._target_rect()
        pix    = self._preview_pixmap
        if target.isEmpty() or not pix:
            return QRect()
        sx = target.width()  / max(1, pix.width())
        sy = target.height() / max(1, pix.height())
        return QRect(
            int(target.x() + r.x() * sx),
            int(target.y() + r.y() * sy),
            int(r.width()  * sx),
            int(r.height() * sy),
        )

    def _all_text_widget_rects(self) -> List[Tuple[int, QRect]]:
        """Return (index, widget_rect) for every non-empty text overlay.
        index = _DRAG_DRAFT for draft, ≥0 for committed overlays.
        """
        result: List[Tuple[int, QRect]] = []
        for i, pr in enumerate(self._overlay_rects):
            if pr and not pr.isEmpty():
                result.append((i, self._pixmap_rect_to_widget(pr)))
        if self._draft_rect and not self._draft_rect.isEmpty():
            result.append((_DRAG_DRAFT, self._pixmap_rect_to_widget(self._draft_rect)))
        return result

    def _find_text_at(self, pos: QPoint) -> int:
        """Return the text index (_DRAG_DRAFT or committed idx) under pos, or _DRAG_NONE."""
        # Check draft last (topmost), check committed in reverse order
        for idx, wr in reversed(self._all_text_widget_rects()):
            if wr.contains(pos):
                return idx
        return _DRAG_NONE

    # ------------------------------------------------------------------
    # Tree layout helpers
    # ------------------------------------------------------------------

    def _get_active_tree(self):
        """Return the LayoutTree of the selected layout, or None."""
        if not self.project or not self.project.selected_layout:
            return None
        return getattr(self.project.selected_layout, 'tree', None)

    def _widget_to_canvas(self, pos: QPoint) -> Tuple[float, float]:
        """Convert a widget-coordinate point to canvas pixel coordinates."""
        target = self._target_rect()
        if target.isEmpty() or not self.project:
            return 0.0, 0.0
        cw, ch = self.project.settings.canvas_px
        cx = (pos.x() - target.x()) / max(1, target.width())  * cw
        cy = (pos.y() - target.y()) / max(1, target.height()) * ch
        return float(cx), float(cy)

    def _canvas_rect_to_widget(self, x: float, y: float, w: float, h: float) -> QRect:
        """Convert a canvas-pixel rect to widget coordinates."""
        target = self._target_rect()
        if target.isEmpty() or not self.project:
            return QRect()
        cw, ch = self.project.settings.canvas_px
        sx = target.width()  / max(1, cw)
        sy = target.height() / max(1, ch)
        return QRect(
            int(target.x() + x * sx),
            int(target.y() + y * sy),
            max(1, int(w * sx)),
            max(1, int(h * sy)),
        )

    # ------------------------------------------------------------------
    # Free Transform helpers
    # ------------------------------------------------------------------

    def _cell_handles(self, cr: QRect) -> dict:
        """8 scale handles (corner + edge-mid) around the cell widget rect."""
        H = self._handle_half_for_rect(cr)
        cx, cy = cr.x(), cr.y()
        ex, ey = cx + cr.width(), cy + cr.height()
        mx, my = cx + cr.width() // 2, cy + cr.height() // 2
        def h(x, y): return QRect(x - H, y - H, 2 * H, 2 * H)
        return {
            'tl': h(cx, cy), 'tc': h(mx, cy), 'tr': h(ex, cy),
            'ml': h(cx, my),                   'mr': h(ex, my),
            'bl': h(cx, ey), 'bc': h(mx, ey), 'br': h(ex, ey),
        }

    def _cell_rotation_zones(self, cr: QRect) -> dict:
        """Small squares just outside each corner where rotation drag starts."""
        H = self._handle_half_for_rect(cr)
        R = max(8, min(_ROTATE_ZONE, max(8, min(cr.width(), cr.height()) // 2)))
        cx, cy = cr.x(), cr.y()
        ex, ey = cx + cr.width(), cy + cr.height()
        return {
            'rot_tl': QRect(cx - H - R, cy - H - R, R, R),
            'rot_tr': QRect(ex + H,     cy - H - R, R, R),
            'rot_bl': QRect(cx - H - R, ey + H,     R, R),
            'rot_br': QRect(ex + H,     ey + H,     R, R),
        }

    def _handle_half_for_rect(self, cr: QRect) -> int:
        shortest = max(1, min(cr.width(), cr.height()))
        return max(3, min(_HANDLE_HALF, shortest // 5))

    def _should_draw_ft_handles(self, cr: QRect) -> bool:
        return min(cr.width(), cr.height()) >= 28

    def _find_ft_element_at(self, pos: QPoint) -> Optional[str]:
        """Return the handle/rotation-zone name under pos (for selected cell), or None."""
        if (self.selected_cell_index < 0 or not self.project
                or not self.project.selected_layout
                or self.selected_cell_index >= len(self.project.selected_layout.cells)):
            return None
        cell = self.project.selected_layout.cells[self.selected_cell_index]
        cr = self._cell_rect_in_widget(cell)
        if cr.isEmpty():
            return None
        if not self._should_draw_ft_handles(cr):
            return None
        for name, rect in self._cell_rotation_zones(cr).items():
            if rect.contains(pos):
                return name
        for name, rect in self._cell_handles(cr).items():
            if rect.contains(pos):
                return name
        return None

    def _apply_ft_transform(self, pos: QPoint) -> None:
        """Apply zoom/pan to the selected image based on FT handle drag.

        Corner handles change state.zoom (zoom in/out inside the fixed cell).
        Edge handles (tc/bc/ml/mr) shift state.pan_x or state.pan_y.
        The cell's layout position (x, y, w, h) is never touched.
        """
        if not self._ft_cell_orig or not self.project or not self.project.selected_layout:
            return
        cell = self.project.selected_layout.cells[self.selected_cell_index]
        if cell.image_index is None or cell.image_index >= len(self.project.images):
            return
        state = self.project.images[cell.image_index]

        cr = self._cell_rect_in_widget(cell)
        cw = max(1, cr.width())
        ch = max(1, cr.height())

        handle = self._ft_handle
        dx = pos.x() - self._ft_drag_start.x()
        dy = pos.y() - self._ft_drag_start.y()

        sign_x, sign_y = _HANDLE_SIGN.get(handle, (0, 0))
        orig_zoom  = self._ft_cell_orig[4]
        orig_pan_x = self._ft_cell_orig[5]
        orig_pan_y = self._ft_cell_orig[6]

        is_shaped = bool(getattr(self.project.selected_layout, 'shape', ''))

        if sign_x != 0 and sign_y != 0:
            # Corner handle → zoom in/out (image stays same cell size on canvas)
            # Dragging outward (away from cell center) = zoom in = see image closer
            expansion = (sign_x * dx / cw + sign_y * dy / ch) / 2.0
            state.zoom = max(1.0, min(5.0, orig_zoom * (1.0 + expansion)))
        elif sign_x != 0:
            # Left/right edge handle → shift horizontal pan
            new_pan_x = orig_pan_x + sign_x * dx / cw * 0.5
            if is_shaped:
                try:
                    cached = get_preview_image(state.path, state.rotation)
                    px_min, px_max, _, _ = shaped_pan_bounds(cached.size, (cw, ch), state.zoom)
                    state.pan_x = max(px_min, min(px_max, new_pan_x))
                except Exception:
                    state.pan_x = new_pan_x
            else:
                state.pan_x = max(0.0, min(1.0, new_pan_x))
        elif sign_y != 0:
            # Top/bottom edge handle → shift vertical pan
            new_pan_y = orig_pan_y + sign_y * dy / ch * 0.5
            if is_shaped:
                try:
                    cached = get_preview_image(state.path, state.rotation)
                    _, _, py_min, py_max = shaped_pan_bounds(cached.size, (cw, ch), state.zoom)
                    state.pan_y = max(py_min, min(py_max, new_pan_y))
                except Exception:
                    state.pan_y = new_pan_y
            else:
                state.pan_y = max(0.0, min(1.0, new_pan_y))

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), _CANVAS_BG)

        if not self._preview_pixmap and not self._base_pixmap:
            painter.setPen(QColor(200,200,200))
            painter.drawText(self.rect(), Qt.AlignCenter, 'Import images and generate a collage')
            return

        target = self._target_rect()

        if self.drag_active and self._base_pixmap:
            painter.drawPixmap(target, self._base_pixmap)
            if self._drag_cell_pixmap and not self._drag_cell_widget_rect.isEmpty():
                painter.drawPixmap(self._drag_cell_widget_rect, self._drag_cell_pixmap)
        else:
            painter.drawPixmap(target, self._preview_pixmap)

        # Guides
        if self.project:
            settings = self.project.settings
            cw, ch = settings.canvas_px

            def _guide_rect(mm: float) -> QRect:
                px = mm_to_px(mm, settings.dpi)
                ow = max(1, int(px * target.width()  / max(1, cw)))
                oh = max(1, int(px * target.height() / max(1, ch)))
                return QRect(target.x()+ow, target.y()+oh,
                             target.width()-2*ow, target.height()-2*oh)

            if settings.bleed_mm > 0:
                painter.setPen(QPen(QColor(210,50,50,220), 2, Qt.DashLine))
                painter.drawRect(_guide_rect(settings.bleed_mm))
            if settings.safe_area_mm > 0:
                painter.setPen(QPen(QColor(0,100,200,180), 2, Qt.DashLine))
                painter.drawRect(_guide_rect(settings.safe_area_mm))

        # Cell selection highlights + Free Transform handles
        if self.project and self.project.selected_layout:
            self._compare_eye_rects = {}
            for idx, cell in enumerate(self.project.selected_layout.cells):
                cr = self._cell_rect_in_widget(cell)
                if self.swap_mode:
                    if idx == self._swap_source:
                        painter.setPen(QPen(QColor(230,120,0), 3)); painter.drawRect(cr)
                    elif idx == self.selected_cell_index:
                        painter.setPen(QPen(QColor(0,180,80), 3)); painter.drawRect(cr)
                elif idx == self.selected_cell_index:
                    painter.setPen(QPen(QColor(0,120,215), 3)); painter.drawRect(cr)
                    # --- Free Transform handles ---
                    if not self.swap_mode and not cr.isEmpty() and self._should_draw_ft_handles(cr):
                        handles = self._cell_handles(cr)
                        # Corner handles (zoom) → filled blue squares
                        painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
                        painter.setBrush(QColor(0, 120, 215, 220))
                        for hname in ('tl', 'tr', 'bl', 'br'):
                            painter.drawRect(handles[hname])
                        # Edge handles (pan) → open white circles
                        painter.setBrush(QColor(255, 255, 255, 200))
                        painter.setPen(QPen(QColor(0, 120, 215, 220), 1))
                        for hname in ('tc', 'bc', 'ml', 'mr'):
                            painter.drawEllipse(handles[hname])
                        # Rotation zones (click to rotate 90°) → yellow dashed arcs
                        painter.setBrush(Qt.NoBrush)
                        painter.setPen(QPen(QColor(255, 220, 0, 170), 1, Qt.DashLine))
                        for rname, rrect in self._cell_rotation_zones(cr).items():
                            painter.drawEllipse(rrect)
                if not cr.isEmpty() and self._cell_has_compare_preview(idx):
                    eye_rect = self._compare_eye_rect(cr)
                    self._compare_eye_rects[idx] = eye_rect
                    active = idx == self._compare_preview_cell
                    painter.setPen(QPen(QColor(255, 255, 255, 210), 1))
                    painter.setBrush(QColor(24, 32, 44, 220 if active else 180))
                    painter.drawEllipse(eye_rect)
                    iris_rect = eye_rect.adjusted(4, 6, -4, -6)
                    painter.setPen(QPen(QColor(235, 240, 248, 235), 1.5))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(iris_rect)
                    pupil = eye_rect.adjusted(eye_rect.width() // 3, eye_rect.height() // 3,
                                              -eye_rect.width() // 3, -eye_rect.height() // 3)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(120, 200, 255, 240 if active else 210))
                    painter.drawEllipse(pupil)
        else:
            self._compare_eye_rects = {}

        # Tree divider lines
        tree = self._get_active_tree()
        if tree and self.project:
            from app.core.layout_tree_engine import compute_rects, collect_dividers
            cw, ch = self.project.settings.canvas_px
            compute_rects(tree, cw, ch)
            dividers = collect_dividers(tree.root)
            for split_node, (dx, dy, dw, dh) in dividers:
                wr_div = self._canvas_rect_to_widget(dx, dy, dw, dh)
                is_active = (split_node is self._tree_drag_node
                             or split_node is self._tree_hover_node)
                line_color = QColor(255, 255, 255, 220 if is_active else 150)
                line_width  = 4 if is_active else 2
                painter.setPen(QPen(line_color, line_width))
                if split_node.direction == 'H':
                    lx = wr_div.x() + wr_div.width() // 2
                    painter.drawLine(lx, wr_div.y(), lx, wr_div.y() + wr_div.height())
                else:
                    ly = wr_div.y() + wr_div.height() // 2
                    painter.drawLine(wr_div.x(), ly, wr_div.x() + wr_div.width(), ly)
            # Draw small drag-handle grip icons on active divider
            if self._tree_hover_node is not None or self._tree_drag_node is not None:
                active_node = self._tree_drag_node or self._tree_hover_node
                for split_node, (dx, dy, dw, dh) in dividers:
                    if split_node is not active_node:
                        continue
                    wr_div = self._canvas_rect_to_widget(dx, dy, dw, dh)
                    painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
                    painter.setBrush(QColor(80, 80, 80, 180))
                    if split_node.direction == 'H':
                        lx = wr_div.x() + wr_div.width() // 2
                        cy2 = wr_div.y() + wr_div.height() // 2
                        painter.drawRoundedRect(lx - 5, cy2 - 14, 10, 28, 3, 3)
                        # three grip dots
                        painter.setBrush(QColor(220, 220, 220, 230))
                        painter.setPen(Qt.NoPen)
                        for dy2 in (-7, 0, 7):
                            painter.drawEllipse(lx - 2, cy2 + dy2 - 2, 4, 4)
                    else:
                        cx2 = wr_div.x() + wr_div.width() // 2
                        ly = wr_div.y() + wr_div.height() // 2
                        painter.drawRoundedRect(cx2 - 14, ly - 5, 28, 10, 3, 3)
                        painter.setBrush(QColor(220, 220, 220, 230))
                        painter.setPen(Qt.NoPen)
                        for dx2 in (-7, 0, 7):
                            painter.drawEllipse(cx2 + dx2 - 2, ly - 2, 4, 4)

        # Text overlay handles
        for idx, wr in self._all_text_widget_rects():
            if self._text_drag_index == idx:
                painter.setPen(QPen(QColor(255,200,0,220), 2, Qt.DashLine))
            elif idx == _DRAG_DRAFT:
                painter.setPen(QPen(QColor(255,255,255,80), 1, Qt.DashLine))
            else:
                painter.setPen(QPen(QColor(200,200,255,100), 1, Qt.DashLine))
            painter.drawRect(wr)

        # Snap guide lines
        for kind, frac in self._snap_lines:
            painter.setPen(QPen(QColor(0, 200, 100, 200), 1, Qt.DashLine))
            if kind == 'v':
                x = int(target.x() + frac * target.width())
                painter.drawLine(x, target.y(), x, target.y() + target.height())
            else:
                y = int(target.y() + frac * target.height())
                painter.drawLine(target.x(), y, target.x() + target.width(), y)

        # Element overlay hit boxes (selection indicator)
        if self.project:
            for i, rect_t in enumerate(self._element_rects):
                if rect_t is None:
                    continue
                el_target = self._target_rect()
                pix = self._preview_pixmap
                if not pix or el_target.isEmpty():
                    continue
                sx = el_target.width() / max(1, pix.width())
                sy = el_target.height() / max(1, pix.height())
                wr = QRect(
                    int(el_target.x() + rect_t[0]*sx),
                    int(el_target.y() + rect_t[1]*sy),
                    int(rect_t[2]*sx),
                    int(rect_t[3]*sy),
                )
                if i == self._selected_element:
                    painter.setPen(QPen(QColor(255, 140, 0, 230), 2, Qt.DashLine))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRect(wr)
                    # Corner handles
                    painter.setPen(QPen(QColor(255, 255, 255, 220), 1))
                    painter.setBrush(QColor(255, 140, 0, 200))
                    H = 6
                    for hx, hy in [(wr.x(), wr.y()), (wr.right(), wr.y()),
                                   (wr.x(), wr.bottom()), (wr.right(), wr.bottom())]:
                        painter.drawRect(hx-H, hy-H, 2*H, 2*H)
                    # Rotation handle (circle above center)
                    cx2 = wr.x() + wr.width()//2
                    rot_y = wr.y() - 22
                    painter.setPen(QPen(QColor(255, 220, 0, 200), 2))
                    painter.setBrush(QColor(255, 220, 0, 180))
                    painter.drawEllipse(cx2-8, rot_y-8, 16, 16)
                    painter.setPen(QPen(QColor(255, 220, 0, 200), 1))
                    painter.drawLine(cx2, wr.y(), cx2, rot_y)

        # ── Swap circles (quick-swap without enabling swap mode) ──────────────
        if self.project and self.project.selected_layout and not self.drag_active:
            r = self._SWAP_CIRCLE_R
            painter.setRenderHint(QPainter.Antialiasing, True)
            font = painter.font()
            font.setPointSize(9)
            painter.setFont(font)
            for idx, cell in enumerate(self.project.selected_layout.cells):
                c = self._swap_circle_center(cell)
                if c is None:
                    continue
                is_src = (idx == self._swap_circle_source)
                if is_src:
                    # Orange: this cell is the swap source waiting for target
                    painter.setPen(QPen(QColor(230, 120, 0), 2))
                    painter.setBrush(QColor(230, 120, 0, 220))
                elif self._swap_circle_source >= 0:
                    # Another cell is already selected → show as target hint
                    painter.setPen(QPen(QColor(80, 200, 120, 220), 2))
                    painter.setBrush(QColor(30, 80, 40, 170))
                else:
                    painter.setPen(QPen(QColor(255, 255, 255, 160), 1))
                    painter.setBrush(QColor(30, 30, 30, 150))
                painter.drawEllipse(c.x() - r, c.y() - r, 2 * r, 2 * r)
                painter.setPen(QColor(255, 255, 255, 230))
                painter.drawText(
                    QRect(c.x() - r, c.y() - r, 2 * r, 2 * r),
                    Qt.AlignCenter, '⇄')

        if self.swap_mode:
            painter.setPen(QColor(230,120,0))
            painter.drawText(
                self.rect().adjusted(0,4,0,-self.rect().height()+22),
                Qt.AlignCenter, 'SWAP MODE – click first cell, then second cell')

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            return
        pos = event.position().toPoint()

        compare_hit = self._find_compare_eye_at(pos)
        if compare_hit >= 0:
            self.set_compare_preview(compare_hit)
            return

        # Close inline editor if open and click is outside it
        if self._inline_editor and self._inline_editor.isVisible():
            if not self._inline_editor.geometry().contains(pos):
                self._inline_editor._do_commit()
            return

        # Text overlay drag (checked before cells)
        if self.project:
            hit = self._find_text_at(pos)
            if hit != _DRAG_NONE:
                self._text_drag_index = hit
                self.last_pos = pos
                if hit != _DRAG_DRAFT:
                    self.textSelected.emit(hit)
                return

        # Element overlay interaction
        if self.project and not self.swap_mode:
            el_hit = self._find_element_at(pos)
            if el_hit >= 0:
                self._selected_element = el_hit
                self.elementSelected.emit(el_hit)
                # Check for rotation handle
                if self._is_element_rotate_handle(pos, el_hit):
                    self._element_rotate_active = True
                    self._element_drag_start = pos
                    self._element_rotate_orig_deg = self.project.elements[el_hit].rotation_deg
                    # Compute start angle from center to mouse
                    el_target = self._target_rect()
                    pix = self._preview_pixmap
                    if pix and not el_target.isEmpty():
                        sx = el_target.width()/max(1, pix.width())
                        sy = el_target.height()/max(1, pix.height())
                        rt = self._element_rects[el_hit]
                        if rt:
                            import math
                            cx2 = el_target.x() + int((rt[0]+rt[2]/2)*sx)
                            cy2 = el_target.y() + int((rt[1]+rt[3]/2)*sy)
                            self._element_rotate_start_angle = math.degrees(math.atan2(pos.y()-cy2, pos.x()-cx2))
                else:
                    self._element_drag_active = True
                    self._element_drag_start = pos
                    el = self.project.elements[el_hit]
                    self._element_orig_pos = (el.pos_x_frac, el.pos_y_frac)
                self.last_pos = pos
                self.update()
                return
            elif not self._find_ft_element_at(pos):
                self._selected_element = -1

        # Free Transform handle / rotation zone click
        ft_elem = self._find_ft_element_at(pos)
        if ft_elem is not None and not self.swap_mode:
            if ft_elem.startswith('rot_') and self.project and self.project.selected_layout:
                # Rotate the image 90° clockwise
                cell = self.project.selected_layout.cells[self.selected_cell_index]
                if cell.image_index is not None and cell.image_index < len(self.project.images):
                    state = self.project.images[cell.image_index]
                    state.rotation = (state.rotation + 90) % 360
                    self.refresh_preview()
            elif self.project and self.project.selected_layout:
                # Start FT drag — record handle and original image state
                cell = self.project.selected_layout.cells[self.selected_cell_index]
                self._ft_handle = ft_elem
                self._ft_drag_start = pos
                # Capture image zoom/pan at drag start (indices 4/5/6).
                # Indices 0-3 keep cell geometry (read-only reference, never modified).
                if cell.image_index is not None and cell.image_index < len(self.project.images):
                    s = self.project.images[cell.image_index]
                    self._ft_cell_orig = (cell.x, cell.y, cell.w, cell.h,
                                          s.zoom, s.pan_x, s.pan_y)
                else:
                    self._ft_cell_orig = (cell.x, cell.y, cell.w, cell.h,
                                          1.0, 0.5, 0.5)
            return

        # Tree divider drag — must be checked before cell selection
        tree = self._get_active_tree()
        if tree and self.project and not self.swap_mode:
            from app.core.layout_tree_engine import compute_rects, collect_dividers, hit_divider
            cw, ch = self.project.settings.canvas_px
            compute_rects(tree, cw, ch)
            dividers = collect_dividers(tree.root)
            cx, cy = self._widget_to_canvas(pos)
            hit_node = hit_divider(dividers, cx, cy)
            if hit_node is not None:
                self._tree_drag_node = hit_node
                self._tree_drag_start_canvas = (cx, cy)
                self._tree_drag_start_ratio = hit_node.ratio
                self.setCursor(QCursor(
                    Qt.SplitHCursor if hit_node.direction == 'H' else Qt.SplitVCursor))
                return

        # Swap mode (toolbar button)
        if self.swap_mode and self.project and self.project.selected_layout:
            self._handle_swap_click(self._find_cell_at(pos))
            return

        # Quick-swap via cell circles (works without enabling swap mode)
        if not self.swap_mode and self.project and self.project.selected_layout:
            circle_hit = self._find_swap_circle_at(pos)
            if circle_hit >= 0:
                if self._swap_circle_source < 0:
                    # First click: mark as swap source
                    self._swap_circle_source = circle_hit
                    self.update()
                else:
                    src, dst = self._swap_circle_source, circle_hit
                    self._swap_circle_source = -1
                    if src != dst:
                        cells = self.project.selected_layout.cells
                        cells[src].image_index, cells[dst].image_index = (
                            cells[dst].image_index, cells[src].image_index)
                        self._sync_tree_leaves_from_layout()
                        self.swapPerformed.emit()
                    self.refresh_preview()
                return
            elif self._swap_circle_source >= 0:
                # Clicked elsewhere → cancel pending quick-swap
                self._swap_circle_source = -1
                self.update()

        # Cell pan drag
        if not self.project or not self.project.selected_layout:
            return
        clicked = self._find_cell_at(pos)
        if clicked >= 0:
            self.selected_cell_index = clicked
            self.cellSelected.emit(clicked)
            self._base_pixmap = self._build_full_pixmap(exclude_cell=clicked)
            self._drag_cell_pixmap, self._drag_cell_widget_rect = \
                self._render_single_cell_pixmap(clicked)
            self.drag_active = True
            self.last_pos = pos
        else:
            self.selected_cell_index = -1
            self.drag_active = False
            self.cellSelected.emit(-1)   # notify panels to hide
            if self._display_zoom != 1.0 or not self._canvas_pan.isNull():
                self.fit_to_screen()
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        hit = self._find_text_at(pos)
        if hit != _DRAG_NONE and self.project:
            # Find the widget rect for this overlay
            for idx, wr in self._all_text_widget_rects():
                if idx == hit:
                    self._open_inline_editor(wr, hit)
                    return
        clicked = self._find_cell_at(pos)
        if clicked >= 0:
            self.selected_cell_index = clicked
            self.cellSelected.emit(clicked)
            self._focus_on_cell(clicked)
            self.update()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos   = event.position().toPoint()
        delta = pos - self.last_pos
        self.last_pos = pos

        # Tree divider drag
        if self._tree_drag_node is not None and self.project:
            tree = self._get_active_tree()
            if tree:
                from app.core.layout_tree_engine import (
                    compute_rects, clamp_ratio, cells_from_tree)
                cw, ch = self.project.settings.canvas_px
                compute_rects(tree, cw, ch)
                node = self._tree_drag_node
                cx, cy = self._widget_to_canvas(pos)
                if node.direction == 'H':
                    new_ratio = (cx - node.x) / max(1.0, node.w)
                else:
                    new_ratio = (cy - node.y) / max(1.0, node.h)
                node.ratio = clamp_ratio(node, new_ratio)
                layout = self.project.selected_layout
                layout.cells = self._dynamic_cells_from_tree_preserving_images(tree, cw, ch)
                self._preview_pixmap = self._build_full_pixmap()
                self.update()
            return

        # Element drag
        if self._element_drag_active and self._selected_element >= 0 and self.project:
            el_target = self._target_rect()
            pix = self._preview_pixmap or self._base_pixmap
            if not el_target.isEmpty() and pix:
                el = self.project.elements[self._selected_element]
                dx_frac = delta.x() / max(1, el_target.width())
                dy_frac = delta.y() / max(1, el_target.height())
                el.pos_x_frac = max(0.0, min(1.0, el.pos_x_frac + dx_frac))
                el.pos_y_frac = max(0.0, min(1.0, el.pos_y_frac + dy_frac))
                self._preview_pixmap = self._build_full_pixmap()
                self.update()
            return

        # Element rotate
        if self._element_rotate_active and self._selected_element >= 0 and self.project:
            el_target = self._target_rect()
            pix = self._preview_pixmap or self._base_pixmap
            if not el_target.isEmpty() and pix:
                rt = self._element_rects[self._selected_element] if self._selected_element < len(self._element_rects) else None
                if rt:
                    import math
                    sx = el_target.width()/max(1, pix.width())
                    sy = el_target.height()/max(1, pix.height())
                    cx2 = el_target.x() + int((rt[0]+rt[2]/2)*sx)
                    cy2 = el_target.y() + int((rt[1]+rt[3]/2)*sy)
                    cur_angle = math.degrees(math.atan2(pos.y()-cy2, pos.x()-cx2))
                    delta_ang = cur_angle - self._element_rotate_start_angle
                    el = self.project.elements[self._selected_element]
                    el.rotation_deg = (self._element_rotate_orig_deg + delta_ang) % 360
                    self._preview_pixmap = self._build_full_pixmap()
                    self.update()
            return

        # Free Transform drag (zoom/pan image inside cell)
        if self._ft_handle is not None and not self._ft_handle.startswith('rot_'):
            self._apply_ft_transform(pos)
            self._preview_pixmap = self._build_full_pixmap(exclude_cell=-1)
            self.update()
            return

        # Update cursor based on FT element / tree divider under mouse (when not dragging)
        if self._text_drag_index == _DRAG_NONE and not self.drag_active and self._ft_handle is None:
            # Tree divider hover
            tree = self._get_active_tree()
            if tree and self.project:
                from app.core.layout_tree_engine import compute_rects, collect_dividers, hit_divider
                cw, ch = self.project.settings.canvas_px
                compute_rects(tree, cw, ch)
                dividers = collect_dividers(tree.root)
                cx, cy = self._widget_to_canvas(pos)
                hover_node = hit_divider(dividers, cx, cy)
                if hover_node != self._tree_hover_node:
                    self._tree_hover_node = hover_node
                    if hover_node is not None:
                        self.setCursor(QCursor(
                            Qt.SplitHCursor if hover_node.direction == 'H'
                            else Qt.SplitVCursor))
                    else:
                        self.setCursor(QCursor(Qt.ArrowCursor))
                    self.update()
            else:
                if self._tree_hover_node is not None:
                    self._tree_hover_node = None
                    self.update()

            ft_elem = self._find_ft_element_at(pos)
            if ft_elem != self._ft_hover:
                self._ft_hover = ft_elem
                if ft_elem is None:
                    if self._tree_hover_node is None:
                        self.setCursor(QCursor(Qt.ArrowCursor))
                elif ft_elem.startswith('rot_'):
                    self.setCursor(QCursor(Qt.CrossCursor))
                else:
                    self.setCursor(QCursor(_HANDLE_CURSORS.get(ft_elem, Qt.SizeAllCursor)))

        if self._text_drag_index != _DRAG_NONE and self.project:
            target = self._target_rect()
            pix    = self._preview_pixmap or self._base_pixmap
            if not target.isEmpty() and pix:
                px = (pos.x() - target.x()) / max(1, target.width())
                py = (pos.y() - target.y()) / max(1, target.height())
                px = max(0.0, min(1.0, px))
                py = max(0.0, min(1.0, py))
                SNAP_THRESH = 0.03
                # Base snap positions: canvas edges and centre
                snap_x = [0.0, 0.5, 1.0]
                snap_y = [0.0, 0.5, 1.0]
                # Add snap positions from other text overlay bounding boxes
                pw, ph = max(1, pix.width()), max(1, pix.height())
                for i, pr in enumerate(self._overlay_rects):
                    if pr and not pr.isEmpty() and i != self._text_drag_index:
                        snap_x += [pr.x()/pw,
                                   (pr.x() + pr.width()/2)/pw,
                                   (pr.x() + pr.width())/pw]
                        snap_y += [pr.y()/ph,
                                   (pr.y() + pr.height()/2)/ph,
                                   (pr.y() + pr.height())/ph]
                if self._draft_rect and not self._draft_rect.isEmpty() \
                        and self._text_drag_index != _DRAG_DRAFT:
                    dr = self._draft_rect
                    snap_x += [dr.x()/pw, (dr.x()+dr.width()/2)/pw, (dr.x()+dr.width())/pw]
                    snap_y += [dr.y()/ph, (dr.y()+dr.height()/2)/ph, (dr.y()+dr.height())/ph]
                self._snap_lines = []
                for sv in snap_x:
                    if abs(px - sv) < SNAP_THRESH:
                        px = sv
                        self._snap_lines.append(('v', sv))
                        break
                for sv in snap_y:
                    if abs(py - sv) < SNAP_THRESH:
                        py = sv
                        self._snap_lines.append(('h', sv))
                        break
                if self._text_drag_index == _DRAG_DRAFT:
                    self.project.text_overlay.pos_x_frac = px
                    self.project.text_overlay.pos_y_frac = py
                else:
                    ov = self.project.text_overlays[self._text_drag_index]
                    ov.pos_x_frac = px
                    ov.pos_y_frac = py
                self._preview_pixmap = self._build_full_pixmap(exclude_cell=-1)
                self.update()
            return

        if not self.drag_active or self.selected_cell_index < 0:
            return
        if not self.project or not self.project.selected_layout:
            return
        cell = self.project.selected_layout.cells[self.selected_cell_index]
        if cell.image_index is None or cell.image_index >= len(self.project.images):
            return
        state = self.project.images[cell.image_index]
        cr = self._cell_rect_in_widget(cell)
        is_shaped = bool(getattr(self.project.selected_layout, 'shape', ''))
        has_cell_shape = bool(getattr(cell, 'shape_type', 'rectangle') != 'rectangle')
        if is_shaped or has_cell_shape:
            # Shaped cells: unclamped pan so the subject can be positioned inside
            # the visible masked region even if the crop extends beyond the source image.
            # Clamp to the physical 1-pixel-overlap boundary to prevent infinite drift.
            if cr.width() > 0:
                state.pan_x -= delta.x() / cr.width()
            if cr.height() > 0:
                state.pan_y -= delta.y() / cr.height()
            try:
                cached = get_preview_image(state.path, state.rotation)
                cw_px = max(1, int(round(cell.w * self.scale_x)))
                ch_px = max(1, int(round(cell.h * self.scale_y)))
                px_min, px_max, py_min, py_max = shaped_pan_bounds(
                    cached.size, (cw_px, ch_px), state.zoom)
                state.pan_x = max(px_min, min(px_max, state.pan_x))
                state.pan_y = max(py_min, min(py_max, state.pan_y))
            except Exception:
                pass
        else:
            if cr.width()  > 0: state.pan_x = min(1.0, max(0.0, state.pan_x - delta.x()/cr.width()))
            if cr.height() > 0: state.pan_y = min(1.0, max(0.0, state.pan_y - delta.y()/cr.height()))
        self._drag_cell_pixmap, self._drag_cell_widget_rect = \
            self._render_single_cell_pixmap(self.selected_cell_index)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._compare_preview_cell >= 0:
            self.clear_compare_preview()
            return
        # Tree divider drag release
        if self._tree_drag_node is not None:
            self._tree_drag_node = None
            self.setCursor(QCursor(Qt.ArrowCursor))
            self.refresh_preview()
            return

        # Element drag/rotate release
        if self._element_drag_active or self._element_rotate_active:
            self._element_drag_active = False
            self._element_rotate_active = False
            self.refresh_preview()
            return

        # Finish Free Transform resize drag
        if self._ft_handle is not None:
            self._ft_handle = None
            self._ft_cell_orig = ()
            self.refresh_preview()
            return

        if self._text_drag_index != _DRAG_NONE:
            self._text_drag_index = _DRAG_NONE
            self._snap_lines = []
            self.textMoved.emit()
            self.refresh_preview()
            return
        if self.drag_active:
            self.drag_active = False
            self._base_pixmap = None
            self._drag_cell_pixmap = None
            self.refresh_preview()
            self.cellPanChanged.emit()   # notify main window to update quality warnings

    def contextMenuEvent(self, event) -> None:
        pos = event.pos()

        # Right-click on text overlay → offer remove
        if self.project:
            hit = self._find_text_at(pos)
            if hit != _DRAG_NONE and hit != _DRAG_DRAFT:
                menu = QMenu(self)
                rem  = menu.addAction('Remove this text overlay')
                if menu.exec(event.globalPos()) == rem:
                    self.textRemoveRequested.emit(hit)
                return

        if not self.project or not self.project.selected_layout:
            return
        idx = self._find_cell_at(pos)
        if idx < 0:
            return
        self.selected_cell_index = idx
        self.cellSelected.emit(idx)

        # Determine whether this cell has an image (needed for Color Lab option)
        cell = self.project.selected_layout.cells[idx]
        has_image = (
            cell.image_index is not None
            and cell.image_index < len(self.project.images)
        )

        menu = QMenu(self)
        replace_act   = menu.addAction('Replace image in cell…')
        remove_act    = menu.addAction('Remove image from cell')
        color_lab_act = None
        photoshop_act = None
        if has_image:
            menu.addSeparator()
            photoshop_act = menu.addAction('ערוך בפוטושופ')
            color_lab_act = menu.addAction('Open in Color Lab…')

        action = menu.exec(event.globalPos())
        if action == replace_act:
            self.replaceImageRequested.emit(idx)
        elif action == remove_act:
            self.removeImageFromCell.emit(idx)
        elif photoshop_act and action == photoshop_act:
            self.editImageInPhotoshop.emit(idx)
        elif color_lab_act and action == color_lab_act:
            self.editImageInColorLab.emit(idx)

    def wheelEvent(self, event) -> None:
        delta_y = event.angleDelta().y()
        delta_x = event.angleDelta().x()

        # Ctrl+wheel → canvas display zoom
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_to(self._display_zoom * (1.1 if delta_y > 0 else 0.9))
            event.accept()
            return

        # Plain wheel over a selected image cell → image zoom within cell
        if (self.selected_cell_index >= 0
                and self.project and self.project.selected_layout
                and not (event.modifiers() & Qt.ShiftModifier)):
            cell = self.project.selected_layout.cells[self.selected_cell_index]
            if cell.image_index is not None and cell.image_index < len(self.project.images):
                state = self.project.images[cell.image_index]
                state.zoom = min(5.0, max(1.0, state.zoom + (0.1 if delta_y > 0 else -0.1)))
                self.refresh_preview()
                event.accept()
                return

        # Otherwise → pan canvas viewport (Shift swaps axes)
        if event.modifiers() & Qt.ShiftModifier:
            delta_x, delta_y = delta_y, delta_x
        step = 40
        new_x = self._canvas_pan.x() + (step if delta_x > 0 else -step if delta_x < 0 else 0)
        new_y = self._canvas_pan.y() + (step if delta_y > 0 else -step if delta_y < 0 else 0)
        self.set_pan(new_x, new_y)
        event.accept()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        step = 30
        if key == Qt.Key_Left:
            self.set_pan(self._canvas_pan.x() + step, self._canvas_pan.y())
            event.accept(); return
        if key == Qt.Key_Right:
            self.set_pan(self._canvas_pan.x() - step, self._canvas_pan.y())
            event.accept(); return
        if key == Qt.Key_Up:
            self.set_pan(self._canvas_pan.x(), self._canvas_pan.y() + step)
            event.accept(); return
        if key == Qt.Key_Down:
            self.set_pan(self._canvas_pan.x(), self._canvas_pan.y() - step)
            event.accept(); return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Inline editor
    # ------------------------------------------------------------------

    def _open_inline_editor(self, widget_rect: QRect, target_index: int) -> None:
        if self._inline_editor is None:
            self._inline_editor = _InlineEditor(self)
            self._inline_editor.committed.connect(self._commit_inline_text)
        self._inline_target_index = target_index
        overlay = (self.project.text_overlay if target_index == _DRAG_DRAFT
                   else self.project.text_overlays[target_index])
        font_size_px = max(8, int(overlay.font_size_pt / 72.0 * 96))
        f = self._inline_editor.font()
        f.setFamily(overlay.font_family)
        f.setPixelSize(font_size_px)
        f.setBold(getattr(overlay, 'font_bold', False))
        f.setItalic(getattr(overlay, 'font_italic', False))
        self._inline_editor.setFont(f)
        self._inline_editor.setPlainText(overlay.text)
        has_rtl   = any('\u0590' <= c <= '\u05FF' for c in overlay.text)
        h_align   = getattr(overlay, 'h_align', 'center')
        qt_align  = (Qt.AlignRight if (has_rtl or h_align == 'right')
                     else Qt.AlignLeft if h_align == 'left' else Qt.AlignHCenter)
        self._inline_editor.setAlignment(qt_align)
        geom = widget_rect.adjusted(-12, -8, 12, 8)
        geom.setWidth(max(geom.width(), 220))
        geom.setHeight(max(geom.height(), 40))
        self._inline_editor.setGeometry(geom)
        self._inline_editor.show()
        self._inline_editor.raise_()
        self._inline_editor.setFocus()
        self._inline_editor.selectAll()

    def _commit_inline_text(self, text: str) -> None:
        if not self.project:
            return
        if self._inline_target_index == _DRAG_DRAFT:
            self.project.text_overlay.text = text
            self.textContentChanged.emit(text)
        elif 0 <= self._inline_target_index < len(self.project.text_overlays):
            self.project.text_overlays[self._inline_target_index].text = text
        self._inline_target_index = _DRAG_NONE
        self.refresh_preview()
        self.textMoved.emit()

    # ------------------------------------------------------------------
    # Element helpers
    # ------------------------------------------------------------------

    def _element_widget_rect(self, idx: int) -> QRect:
        """Widget-coordinate bounding rect of element idx."""
        if idx < 0 or idx >= len(self._element_rects):
            return QRect()
        rt = self._element_rects[idx]
        if rt is None:
            return QRect()
        target = self._target_rect()
        pix = self._preview_pixmap
        if not pix or target.isEmpty():
            return QRect()
        sx = target.width() / max(1, pix.width())
        sy = target.height() / max(1, pix.height())
        return QRect(int(target.x()+rt[0]*sx), int(target.y()+rt[1]*sy),
                     int(rt[2]*sx), int(rt[3]*sy))

    def _find_element_at(self, pos: QPoint) -> int:
        """Return element index under pos, or -1."""
        for i in range(len(self._element_rects)-1, -1, -1):
            wr = self._element_widget_rect(i)
            if not wr.isEmpty() and wr.contains(pos):
                return i
        return -1

    def _is_element_rotate_handle(self, pos: QPoint, idx: int) -> bool:
        """True if pos is over the rotation handle of element idx."""
        wr = self._element_widget_rect(idx)
        if wr.isEmpty():
            return False
        cx2 = wr.x() + wr.width()//2
        rot_y = wr.y() - 22
        return ((pos.x()-cx2)**2 + (pos.y()-rot_y)**2) <= 12**2

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_cell_at(self, pos: QPoint) -> int:
        if not self.project or not self.project.selected_layout:
            return -1
        cells = self.project.selected_layout.cells
        for idx, cell in sorted(
            enumerate(cells),
            key=lambda item: (int(getattr(item[1], 'z_index', 0)), item[0]),
            reverse=True,
        ):
            if getattr(cell, 'shape_type', '') == 'ring_segment':
                if self._ring_segment_contains(cell, pos):
                    return idx
                continue
            if self._cell_rect_in_widget(cell).contains(pos):
                return idx
        return -1

    def _ring_segment_contains(self, cell: CellRect, pos: QPoint) -> bool:
        cr = self._cell_rect_in_widget(cell)
        if cr.isEmpty() or not cr.contains(pos):
            return False
        sx = cr.width() / max(1.0, float(cell.w))
        sy = cr.height() / max(1.0, float(cell.h))
        lx = (pos.x() - cr.x()) / max(1e-6, sx)
        ly = (pos.y() - cr.y()) / max(1e-6, sy)
        params = getattr(cell, 'shape_params', {})
        cx = float(params.get('center_x', cell.w / 2.0))
        cy = float(params.get('center_y', cell.h / 2.0))
        dx = lx - cx
        dy = ly - cy
        radius = (dx * dx + dy * dy) ** 0.5
        inner_r = float(params.get('inner_radius', 0.0))
        outer_r = float(params.get('outer_radius', max(cell.w, cell.h)))
        if radius < inner_r or radius > outer_r:
            return False
        angle = math.degrees(math.atan2(dy, dx))
        start = float(params.get('start_angle', 0.0)) + float(params.get('gap_angle', 0.0)) / 2.0
        end = float(params.get('end_angle', 360.0)) - float(params.get('gap_angle', 0.0)) / 2.0
        while angle < start:
            angle += 360.0
        return start <= angle <= end

    def _handle_swap_click(self, idx: int) -> None:
        if idx < 0:
            return
        if self._swap_source < 0:
            self._swap_source = idx
            self.selected_cell_index = idx
            self.update()
        else:
            src, dst = self._swap_source, idx
            if src != dst:
                cells = self.project.selected_layout.cells
                cells[src].image_index, cells[dst].image_index = \
                    cells[dst].image_index, cells[src].image_index
                self._sync_tree_leaves_from_layout()
                self.swapPerformed.emit()
            self._swap_source = -1
            self.selected_cell_index = -1
            self.set_swap_mode(False)
            self.refresh_preview()
