"""app/ui/template_creator.py — Template Creator dialog.

Lets users build parametric slot-based templates interactively:

  • Drag slots to move them
  • Drag resize handles to resize
  • Choose slot shape (rectangle, rounded, circle, ellipse, polygon, heart)
  • Add / delete / duplicate slots
  • Save and load JSON templates
  • Apply to the current project immediately

All geometry is stored in relative [0..1] units; pixel conversion only
happens at paint time so resizing the dialog never corrupts the layout.
"""
from __future__ import annotations

import copy
import math
import os
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

# Default directory for user templates — always writable
_DEFAULT_TEMPLATES_DIR = os.path.join(
    os.path.expanduser('~'), 'Documents', 'SmartCollageTemplates'
)

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from app.models.template import SHAPE_TYPES, SlotShape, Template, TemplateSlot
from app.core.template_io import load_template, save_template

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
_BG          = QColor('#1a1a1a')
_CANVAS_BG   = QColor('#252525')
_CANVAS_BORDER = QColor('#3a3a3a')
_SLOT_FILL   = QColor(45, 75, 115, 200)
_SLOT_BORDER = QColor(100, 150, 210)
_SLOT_SEL    = QColor(74, 158, 255)
_SLOT_TEXT   = QColor(180, 210, 255)
_HANDLE_FILL = QColor('#ffffff')
_HANDLE_SIZE = 8
_MIN_REL     = 0.02   # minimum slot dimension in relative units


# ---------------------------------------------------------------------------
# Shape path builders
# ---------------------------------------------------------------------------

def _slot_path(slot: TemplateSlot, rect: QRect) -> Optional[QPainterPath]:
    """Return a QPainterPath for shaped slots (None → use drawRect/Ellipse)."""
    st = slot.shape.shape_type
    if st == 'polygon':
        sides = max(3, int(slot.shape.params.get('sides', 6)))
        rot   = slot.shape.params.get('rotation', 0.0)
        return _polygon_path(rect, sides, rot)
    if st == 'heart':
        return _heart_path(rect)
    return None


def _polygon_path(rect: QRect, sides: int, rot_deg: float) -> QPainterPath:
    cx = rect.x() + rect.width()  / 2.0
    cy = rect.y() + rect.height() / 2.0
    rx = rect.width()  / 2.0
    ry = rect.height() / 2.0
    path = QPainterPath()
    for i in range(sides):
        a = math.radians(rot_deg + i * 360.0 / sides - 90.0)
        x = cx + rx * math.cos(a)
        y = cy + ry * math.sin(a)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    return path


def _heart_path(rect: QRect) -> QPainterPath:
    try:
        import numpy as np
        n  = 180
        ts = np.linspace(0, 2 * math.pi, n)
        px = 16 * np.sin(ts) ** 3
        py = -(13 * np.cos(ts) - 5 * np.cos(2*ts) - 2 * np.cos(3*ts) - np.cos(4*ts))
        mnx, mxx = float(px.min()), float(px.max())
        mny, mxy = float(py.min()), float(py.max())
        sx = rect.width()  / max(1e-9, mxx - mnx)
        sy = rect.height() / max(1e-9, mxy - mny)
        ox = rect.x() - mnx * sx
        oy = rect.y() - mny * sy
        path = QPainterPath()
        path.moveTo(float(px[0]) * sx + ox, float(py[0]) * sy + oy)
        for i in range(1, n):
            path.lineTo(float(px[i]) * sx + ox, float(py[i]) * sy + oy)
        path.closeSubpath()
        return path
    except Exception:
        # Fallback: simple ellipse if numpy unavailable
        path = QPainterPath()
        path.addEllipse(rect)
        return path


# ---------------------------------------------------------------------------
# TemplateCanvas
# ---------------------------------------------------------------------------

# Handle indices (clockwise from TL):
# 0=TL  1=TM  2=TR  3=MR  4=BR  5=BM  6=BL  7=ML
_HANDLE_CURSORS = [
    Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor,
    Qt.SizeHorCursor,   Qt.SizeFDiagCursor, Qt.SizeVerCursor,
    Qt.SizeBDiagCursor, Qt.SizeHorCursor,
]

# Which edges each handle moves (left, top, right, bottom as booleans)
_HANDLE_EDGES = [
    (True,  True,  False, False),   # 0 TL
    (False, True,  False, False),   # 1 TM
    (False, True,  True,  False),   # 2 TR
    (False, False, True,  False),   # 3 MR
    (False, False, True,  True),    # 4 BR
    (False, False, False, True),    # 5 BM
    (True,  False, False, True),    # 6 BL
    (True,  False, False, False),   # 7 ML
]


class TemplateCanvas(QWidget):
    """Interactive canvas for editing template slots.

    Responsibilities:
      • Convert relative slot coords → widget pixels for display
      • Convert mouse deltas → relative coord updates
      • Paint slots in their configured shapes
      • Handle selection, drag-to-move, and drag-handle-to-resize
    """
    slotSelected    = Signal(object)   # TemplateSlot | None
    templateChanged = Signal()

    # Snap threshold in relative units
    _SNAP_THRESH = 0.018
    # Standard grid snap positions
    _GRID_SNAPS = (0.0, 1/3, 0.5, 2/3, 1.0)

    def __init__(self, template: Template, parent=None):
        super().__init__(parent)
        self._template  = template
        self._selected: Optional[TemplateSlot] = None
        self._preview   = False
        self.snap_enabled: bool = True          # controlled by toolbar checkbox
        self._snap_active: List[Tuple[str, float]] = []  # ('v'|'h', value) active lines

        # Drag state
        self._drag_mode:  str             = ''      # '' | 'move' | 'handle_N'
        self._drag_start: Optional[QPoint] = None
        self._drag_orig:  Optional[Tuple[float, float, float, float]] = None

        self.setMinimumSize(400, 280)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ── Coordinate helpers ────────────────────────────────────────────────

    def _template_rect(self) -> QRect:
        """Pixel area allocated to the template, maintaining its aspect ratio."""
        M  = 20
        aw = max(1, self.width()  - 2 * M)
        ah = max(1, self.height() - 2 * M)
        ar = self._template.base_aspect_w / max(1e-9, self._template.base_aspect_h)
        if aw / ah > ar:
            th = ah; tw = max(1, int(th * ar))
        else:
            tw = aw; th = max(1, int(tw / ar))
        x0 = M + (aw - tw) // 2
        y0 = M + (ah - th) // 2
        return QRect(x0, y0, tw, th)

    def _to_widget(self, rx: float, ry: float) -> Tuple[int, int]:
        r = self._template_rect()
        return int(r.x() + rx * r.width()), int(r.y() + ry * r.height())

    def _to_rel(self, wx: float, wy: float) -> Tuple[float, float]:
        r = self._template_rect()
        if r.width() == 0 or r.height() == 0:
            return 0.5, 0.5
        return (wx - r.x()) / r.width(), (wy - r.y()) / r.height()

    def _slot_qrect(self, slot: TemplateSlot) -> QRect:
        x, y   = self._to_widget(slot.x, slot.y)
        x2, y2 = self._to_widget(slot.x + slot.w, slot.y + slot.h)
        return QRect(x, y, max(1, x2 - x), max(1, y2 - y))

    def _handle_rects(self, slot: TemplateSlot) -> List[QRect]:
        r  = self._slot_qrect(slot)
        hs = _HANDLE_SIZE
        hw = hs // 2
        rx, ry, rw, rh = r.x(), r.y(), r.width(), r.height()
        cx = rx + rw // 2;  cy = ry + rh // 2
        ri = rx + rw;        bi = ry + rh
        pts = [
            (rx, ry),   (cx, ry),   (ri, ry),   (ri, cy),
            (ri, bi),   (cx, bi),   (rx, bi),    (rx, cy),
        ]
        return [QRect(px - hw, py - hw, hs, hs) for px, py in pts]

    def _hit_handle(self, slot: TemplateSlot, pos: QPoint) -> int:
        for i, hr in enumerate(self._handle_rects(slot)):
            if hr.contains(pos):
                return i
        return -1

    def _hit_slot(self, pos: QPoint) -> Optional[TemplateSlot]:
        for slot in reversed(self._template.slots):
            if self._slot_qrect(slot).contains(pos):
                return slot
        return None

    # ── Paint ─────────────────────────────────────────────────────────────

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Widget background
        p.fillRect(self.rect(), _BG)

        # Template area
        tr = self._template_rect()
        p.fillRect(tr, _CANVAS_BG)
        p.setPen(QPen(_CANVAS_BORDER, 1))
        p.drawRect(tr)

        # Slots
        for slot in self._template.slots:
            self._draw_slot(p, slot, slot is self._selected)

        # Snap guide lines
        if self._snap_active:
            p.setPen(QPen(QColor(0, 200, 120, 210), 1))
            for kind, frac in self._snap_active:
                if kind == 'v':
                    x = tr.x() + int(frac * tr.width())
                    p.drawLine(x, tr.y(), x, tr.y() + tr.height())
                else:
                    y = tr.y() + int(frac * tr.height())
                    p.drawLine(tr.x(), y, tr.x() + tr.width(), y)

        p.end()

    def _draw_slot(self, p: QPainter, slot: TemplateSlot,
                   selected: bool) -> None:
        r   = self._slot_qrect(slot)
        if r.width() < 2 or r.height() < 2:
            return

        fill   = _SLOT_SEL if selected else _SLOT_FILL
        border = _SLOT_SEL if selected else _SLOT_BORDER
        st     = slot.shape.shape_type

        p.setBrush(QBrush(fill))
        p.setPen(QPen(border, 2 if selected else 1))

        path = _slot_path(slot, r)
        if path:
            p.drawPath(path)
        elif st == 'circle':
            # Always render as a perfect circle inscribed in the shorter dimension
            d = min(r.width(), r.height())
            cx2 = r.x() + r.width() // 2
            cy2 = r.y() + r.height() // 2
            circle_r = QRect(cx2 - d // 2, cy2 - d // 2, d, d)
            p.drawEllipse(circle_r)
        elif st == 'ellipse':
            p.drawEllipse(r)
        elif st == 'rounded':
            cr_frac = slot.shape.params.get('corner_radius', 0.15)
            cr      = cr_frac * min(r.width(), r.height())
            p.drawRoundedRect(r, cr, cr)
        else:
            p.drawRect(r)

        # Slot number (hidden in preview mode)
        if not self._preview:
            idx = self._template.slots.index(slot) + 1
            p.setPen(QPen(_SLOT_TEXT))
            p.setFont(QFont('Segoe UI', 9, QFont.Bold))
            p.drawText(r, Qt.AlignCenter, str(idx))

        # Resize handles (selected only, edit mode only)
        if selected and not self._preview:
            p.setBrush(QBrush(_HANDLE_FILL))
            p.setPen(QPen(_SLOT_SEL, 1))
            for hr in self._handle_rects(slot):
                p.fillRect(hr, _HANDLE_FILL)
                p.drawRect(hr)

    # ── Mouse ─────────────────────────────────────────────────────────────

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        pos = ev.pos()

        # Try handles first on the selected slot
        if self._selected:
            h = self._hit_handle(self._selected, pos)
            if h >= 0:
                self._start_drag(f'handle_{h}', pos, self._selected)
                return

        # Try slot body
        hit = self._hit_slot(pos)
        if hit is not self._selected:
            self._selected = hit
            self.slotSelected.emit(hit)
        if hit:
            self._start_drag('move', pos, hit)
        else:
            self._drag_mode = ''
        self.update()

    def _start_drag(self, mode: str, pos: QPoint, slot: TemplateSlot):
        self._drag_mode  = mode
        self._drag_start = pos
        self._drag_orig  = (slot.x, slot.y, slot.w, slot.h)

    def mouseMoveEvent(self, ev):
        pos = ev.pos()

        if not self._drag_mode:
            self._update_hover_cursor(pos)
            return

        if not self._drag_start or not self._drag_orig or not self._selected:
            return

        tr = self._template_rect()
        dx = (pos.x() - self._drag_start.x()) / max(1, tr.width())
        dy = (pos.y() - self._drag_start.y()) / max(1, tr.height())
        ox, oy, ow, oh = self._drag_orig

        if self._drag_mode == 'move':
            nx, ny = ox + dx, oy + dy
            if self.snap_enabled:
                nx, ny, snaps = self._apply_move_snap(nx, ny, ow, oh)
                self._snap_active = snaps
            else:
                self._snap_active = []
            self._selected.x = nx
            self._selected.y = ny
            self._selected.clamp()
        else:
            h = int(self._drag_mode.split('_')[1])
            if self.snap_enabled:
                dx, dy, snaps = self._apply_resize_snap(h, ox, oy, ow, oh, dx, dy)
                self._snap_active = snaps
            else:
                self._snap_active = []
            self._resize_slot(self._selected, h, ox, oy, ow, oh, dx, dy)

        self.update()
        self.templateChanged.emit()

    def mouseReleaseEvent(self, ev):
        self._drag_mode  = ''
        self._drag_start = None
        self._drag_orig  = None
        self._snap_active = []
        self.setCursor(QCursor(Qt.ArrowCursor))

    # ── Snap helpers ─────────────────────────────────────────────────────

    def _snap_points_x(self) -> List[float]:
        pts = list(self._GRID_SNAPS)
        for s in self._template.slots:
            if s is not self._selected:
                pts += [s.x, s.cx, s.right]
        return pts

    def _snap_points_y(self) -> List[float]:
        pts = list(self._GRID_SNAPS)
        for s in self._template.slots:
            if s is not self._selected:
                pts += [s.y, s.cy, s.bottom]
        return pts

    def _nearest_snap(self, v: float, pts: List[float]) -> Tuple[float, bool]:
        """Return (snapped_value, did_snap)."""
        best, dist = v, self._SNAP_THRESH
        for p in pts:
            d = abs(v - p)
            if d < dist:
                dist = d; best = p
        return best, (best != v)

    def _apply_move_snap(self, nx: float, ny: float, nw: float, nh: float,
                         ) -> Tuple[float, float, list]:
        sx = self._snap_points_x()
        sy = self._snap_points_y()
        snaps = []
        # Try snapping left, center, right edge (x axis)
        for offset in (0.0, nw / 2, nw):
            sv, hit = self._nearest_snap(nx + offset, sx)
            if hit:
                nx = sv - offset
                snaps.append(('v', sv))
                break
        # Try snapping top, center, bottom edge (y axis)
        for offset in (0.0, nh / 2, nh):
            sv, hit = self._nearest_snap(ny + offset, sy)
            if hit:
                ny = sv - offset
                snaps.append(('h', sv))
                break
        return nx, ny, snaps

    def _apply_resize_snap(self, h: int, ox: float, oy: float, ow: float, oh: float,
                           dx: float, dy: float) -> Tuple[float, float, list]:
        move_l, move_t, move_r, move_b = _HANDLE_EDGES[h]
        sx = self._snap_points_x()
        sy = self._snap_points_y()
        snaps = []
        if move_l:
            edge = ox + dx
            sv, hit = self._nearest_snap(edge, sx)
            if hit:
                dx = sv - ox
                snaps.append(('v', sv))
        elif move_r:
            edge = ox + ow + dx
            sv, hit = self._nearest_snap(edge, sx)
            if hit:
                dx = sv - ox - ow
                snaps.append(('v', sv))
        if move_t:
            edge = oy + dy
            sv, hit = self._nearest_snap(edge, sy)
            if hit:
                dy = sv - oy
                snaps.append(('h', sv))
        elif move_b:
            edge = oy + oh + dy
            sv, hit = self._nearest_snap(edge, sy)
            if hit:
                dy = sv - oy - oh
                snaps.append(('h', sv))
        return dx, dy, snaps

    def _update_hover_cursor(self, pos: QPoint):
        if self._selected:
            h = self._hit_handle(self._selected, pos)
            if h >= 0:
                self.setCursor(QCursor(_HANDLE_CURSORS[h]))
                return
        for slot in reversed(self._template.slots):
            if self._slot_qrect(slot).contains(pos):
                self.setCursor(QCursor(Qt.SizeAllCursor))
                return
        self.setCursor(QCursor(Qt.ArrowCursor))

    @staticmethod
    def _resize_slot(slot: TemplateSlot, h: int,
                     ox: float, oy: float, ow: float, oh: float,
                     dx: float, dy: float) -> None:
        """Apply a handle drag to the slot geometry."""
        move_l, move_t, move_r, move_b = _HANDLE_EDGES[h]
        nx, ny, nw, nh = ox, oy, ow, oh

        if move_l: nx = ox + dx;  nw = ow - dx
        if move_t: ny = oy + dy;  nh = oh - dy
        if move_r: nw = ow + dx
        if move_b: nh = oh + dy

        slot.w = max(_MIN_REL, min(nw, 1.0))
        slot.h = max(_MIN_REL, min(nh, 1.0))
        # Keep right/bottom fixed when dragging opposite edge hits minimum
        if move_l:
            slot.x = max(0.0, min(nx, (ox + ow) - slot.w))
        else:
            slot.x = max(0.0, min(nx, 1.0 - slot.w))
        if move_t:
            slot.y = max(0.0, min(ny, (oy + oh) - slot.h))
        else:
            slot.y = max(0.0, min(ny, 1.0 - slot.h))

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected()

    # ── Public API ────────────────────────────────────────────────────────

    def set_template(self, template: Template):
        self._template = template
        self._selected = None
        self.slotSelected.emit(None)
        self.update()

    def set_preview(self, on: bool):
        self._preview = on
        self.update()

    def add_slot(self):
        slot = TemplateSlot.new(x=0.05, y=0.05, w=0.30, h=0.30)
        self._template.slots.append(slot)
        self._selected = slot
        self.slotSelected.emit(slot)
        self.update()
        self.templateChanged.emit()

    def delete_selected(self):
        if self._selected and self._selected in self._template.slots:
            self._template.slots.remove(self._selected)
            self._selected = None
            self.slotSelected.emit(None)
            self.update()
            self.templateChanged.emit()

    def duplicate_selected(self):
        if not self._selected:
            return
        new_slot         = copy.deepcopy(self._selected)
        new_slot.id      = uuid.uuid4().hex[:8]
        new_slot.x       = min(new_slot.x + 0.04, 1.0 - new_slot.w)
        new_slot.y       = min(new_slot.y + 0.04, 1.0 - new_slot.h)
        self._template.slots.append(new_slot)
        self._selected = new_slot
        self.slotSelected.emit(new_slot)
        self.update()
        self.templateChanged.emit()

    def align_selected(self, axis: str, reference: str):
        """Align all slots to the selected slot's edge.

        axis      — 'x' (left) or 'y' (top)
        reference — 'left'/'top'/'right'/'bottom'/'center'
        """
        if not self._selected:
            return
        s = self._selected
        if reference == 'left':   ref = s.x
        elif reference == 'right':  ref = s.x + s.w
        elif reference == 'top':    ref = s.y
        elif reference == 'bottom': ref = s.y + s.h
        elif reference == 'center_h': ref = s.cx
        elif reference == 'center_v': ref = s.cy
        else: return

        for slot in self._template.slots:
            if reference in ('left',):     slot.x = ref
            elif reference in ('right',):  slot.x = ref - slot.w
            elif reference in ('top',):    slot.y = ref
            elif reference in ('bottom',): slot.y = ref - slot.h
            elif reference == 'center_h':  slot.x = ref - slot.w / 2
            elif reference == 'center_v':  slot.y = ref - slot.h / 2
            slot.clamp()

        self.update()
        self.templateChanged.emit()

    def distribute_h(self):
        """Distribute slots evenly across horizontal space."""
        if len(self._template.slots) < 2:
            return
        slots = sorted(self._template.slots, key=lambda s: s.cx)
        total_w = sum(s.w for s in slots)
        gap = (1.0 - total_w) / (len(slots) + 1)
        x = gap
        for slot in slots:
            slot.x = max(0.0, x)
            x += slot.w + gap
            slot.clamp()
        self.update()
        self.templateChanged.emit()

    def distribute_v(self):
        """Distribute slots evenly across vertical space."""
        if len(self._template.slots) < 2:
            return
        slots = sorted(self._template.slots, key=lambda s: s.cy)
        total_h = sum(s.h for s in slots)
        gap = (1.0 - total_h) / (len(slots) + 1)
        y = gap
        for slot in slots:
            slot.y = max(0.0, y)
            y += slot.h + gap
            slot.clamp()
        self.update()
        self.templateChanged.emit()


# ---------------------------------------------------------------------------
# SlotPropertiesPanel
# ---------------------------------------------------------------------------

class SlotPropertiesPanel(QWidget):
    """Sidebar showing editable properties of the currently selected slot."""
    slotChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slot:     Optional[TemplateSlot] = None
        self._updating: bool                   = False
        self._build_ui()
        self.setEnabled(False)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        hdr = QLabel('Slot Properties')
        hdr.setStyleSheet('font-weight:bold; color:#aaa; font-size:11px;')
        layout.addWidget(hdr)

        form = QFormLayout()
        form.setSpacing(4)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignRight)

        def dspin(lo, hi, val=0.0, step=0.01, dec=3):
            s = QDoubleSpinBox()
            s.setRange(lo, hi); s.setSingleStep(step)
            s.setDecimals(dec); s.setValue(val)
            return s

        self.x_spin = dspin(0.0, 0.98, step=0.005)
        self.y_spin = dspin(0.0, 0.98, step=0.005)
        self.w_spin = dspin(0.02, 1.0, step=0.005)
        self.h_spin = dspin(0.02, 1.0, step=0.005)
        form.addRow('X', self.x_spin)
        form.addRow('Y', self.y_spin)
        form.addRow('W', self.w_spin)
        form.addRow('H', self.h_spin)

        self.shape_combo = QComboBox()
        self.shape_combo.addItems(SHAPE_TYPES)
        form.addRow('Shape', self.shape_combo)

        # Shape-specific params (shown/hidden based on shape)
        self.cr_label = QLabel('Corner R')
        self.cr_spin  = dspin(0.01, 0.50, 0.15, 0.01, 2)
        form.addRow(self.cr_label, self.cr_spin)

        self.sides_label = QLabel('Sides')
        self.sides_spin  = QSpinBox()
        self.sides_spin.setRange(3, 12); self.sides_spin.setValue(6)
        form.addRow(self.sides_label, self.sides_spin)

        self.rot_label = QLabel('Rotation')
        self.rot_spin  = QDoubleSpinBox()
        self.rot_spin.setRange(0, 360); self.rot_spin.setSuffix('°')
        form.addRow(self.rot_label, self.rot_spin)

        self.role_edit  = QLineEdit()
        self.role_edit.setPlaceholderText('center / outer / …')
        self.label_edit = QLineEdit()
        form.addRow('Role', self.role_edit)
        form.addRow('Label', self.label_edit)

        layout.addLayout(form)
        layout.addStretch()

        # Connections
        for w in (self.x_spin, self.y_spin, self.w_spin, self.h_spin,
                  self.cr_spin, self.rot_spin):
            w.valueChanged.connect(self._on_changed)
        self.sides_spin.valueChanged.connect(self._on_changed)
        self.shape_combo.currentIndexChanged.connect(self._on_shape_changed)
        self.role_edit.textChanged.connect(self._on_changed)
        self.label_edit.textChanged.connect(self._on_changed)

    def _update_param_rows(self):
        st = self.shape_combo.currentText()
        show_cr    = st == 'rounded'
        show_sides = st == 'polygon'
        show_rot   = st == 'polygon'
        self.cr_label.setVisible(show_cr);    self.cr_spin.setVisible(show_cr)
        self.sides_label.setVisible(show_sides); self.sides_spin.setVisible(show_sides)
        self.rot_label.setVisible(show_rot);   self.rot_spin.setVisible(show_rot)

    def set_slot(self, slot: Optional[TemplateSlot]):
        self._slot = slot
        self.setEnabled(slot is not None)
        if slot is None:
            return
        self._updating = True
        self.x_spin.setValue(slot.x)
        self.y_spin.setValue(slot.y)
        self.w_spin.setValue(slot.w)
        self.h_spin.setValue(slot.h)
        idx = self.shape_combo.findText(slot.shape.shape_type)
        if idx >= 0:
            self.shape_combo.setCurrentIndex(idx)
        self.cr_spin.setValue(slot.shape.params.get('corner_radius', 0.15))
        self.sides_spin.setValue(int(slot.shape.params.get('sides', 6)))
        self.rot_spin.setValue(slot.shape.params.get('rotation', 0.0))
        self.role_edit.setText(slot.role)
        self.label_edit.setText(slot.label)
        self._updating = False
        self._update_param_rows()

    def _on_shape_changed(self):
        self._update_param_rows()
        self._on_changed()

    def _on_changed(self):
        if self._updating or not self._slot:
            return
        self._slot.x = self.x_spin.value()
        self._slot.y = self.y_spin.value()
        self._slot.w = self.w_spin.value()
        self._slot.h = self.h_spin.value()
        self._slot.role  = self.role_edit.text()
        self._slot.label = self.label_edit.text()
        st = self.shape_combo.currentText()
        if self._slot.shape.shape_type != st:
            self._slot.shape = SlotShape.make(st)
        if st == 'rounded':
            self._slot.shape.params['corner_radius'] = self.cr_spin.value()
        elif st == 'polygon':
            self._slot.shape.params['sides']    = float(self.sides_spin.value())
            self._slot.shape.params['rotation'] = self.rot_spin.value()
        self._slot.clamp()
        self.slotChanged.emit()


# ---------------------------------------------------------------------------
# TemplateCreatorDialog
# ---------------------------------------------------------------------------

class TemplateCreatorDialog(QDialog):
    """Main Template Creator window.

    Opens modally.  After the user clicks 'Apply to project', the caller
    can retrieve the template via get_template().
    """
    templateSaved = Signal(str)   # emits the saved file path

    def __init__(self, template: Optional[Template] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Template Creator')
        self.resize(1060, 700)
        self.setMinimumSize(720, 480)
        self._template = template or Template.new('Untitled', 3.0, 2.0, 4)
        self._save_path: Optional[str] = None
        self._build_ui()
        self._load_template_to_ui()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())

        body = QSplitter(Qt.Horizontal)
        body.setHandleWidth(2)
        body.setChildrenCollapsible(False)

        self.canvas = TemplateCanvas(self._template)
        body.addWidget(self.canvas)

        sidebar_wrap = QScrollArea()
        sidebar_wrap.setWidgetResizable(True)
        sidebar_wrap.setFixedWidth(230)
        sidebar_wrap.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.props = SlotPropertiesPanel()
        sidebar_wrap.setWidget(self.props)
        body.addWidget(sidebar_wrap)
        body.setSizes([830, 230])

        root.addWidget(body, 1)
        self._wire_signals()

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet('background:#1a1a1a; border-bottom:1px solid #333;')
        hl = QHBoxLayout(w)
        hl.setContentsMargins(10, 6, 10, 6)
        hl.setSpacing(8)

        def lbl(text):
            l = QLabel(text)
            l.setStyleSheet('color:#aaa;')
            return l

        hl.addWidget(lbl('Name:'))
        self.name_edit = QLineEdit()
        self.name_edit.setFixedWidth(160)
        hl.addWidget(self.name_edit)

        # Canvas size presets
        hl.addWidget(lbl('Size:'))
        self.preset_combo = QComboBox()
        self.preset_combo.setFixedWidth(150)
        self.preset_combo.setStyleSheet(
            'QComboBox{background:#2d2d2d;border:1px solid #3d3d3d;'
            'border-radius:4px;padding:2px 6px;color:#ddd;}'
            'QComboBox::drop-down{border:none;}'
            'QComboBox QAbstractItemView{background:#2d2d2d;color:#ddd;'
            'selection-background-color:#3a3a3a;}')
        _PRESETS = [
            ('Custom ratio…',    None,    None),
            ('15 × 10 cm (6×4")',15.0,   10.0),
            ('10 × 15 cm (4×6")',10.0,   15.0),
            ('A4 Landscape',     29.7,   21.0),
            ('A4 Portrait',      21.0,   29.7),
            ('A5 Landscape',     21.0,   14.85),
            ('A5 Portrait',      14.85,  21.0),
            ('Square 1:1',        1.0,    1.0),
            ('16:9 Landscape',   16.0,    9.0),
            ('9:16 Portrait',     9.0,   16.0),
            ('4:3 Landscape',     4.0,    3.0),
            ('3:2 Landscape',     3.0,    2.0),
            ('5:4 Landscape',     5.0,    4.0),
        ]
        self._size_presets = _PRESETS
        for name, _, _ in _PRESETS:
            self.preset_combo.addItem(name)
        hl.addWidget(self.preset_combo)

        hl.addWidget(lbl('Ratio:'))
        self.aw_spin = QDoubleSpinBox()
        self.aw_spin.setRange(0.5, 100); self.aw_spin.setDecimals(2)
        self.aw_spin.setValue(3.0); self.aw_spin.setFixedWidth(64)
        self.ah_spin = QDoubleSpinBox()
        self.ah_spin.setRange(0.5, 100); self.ah_spin.setDecimals(2)
        self.ah_spin.setValue(2.0); self.ah_spin.setFixedWidth(64)
        hl.addWidget(self.aw_spin); hl.addWidget(lbl('×')); hl.addWidget(self.ah_spin)

        hl.addWidget(lbl('Slots:'))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 30); self.count_spin.setValue(4)
        self.count_spin.setFixedWidth(52)
        hl.addWidget(self.count_spin)

        _ts = ('QPushButton{background:#2d2d2d;border-radius:5px;'
               'padding:4px 10px;border:1px solid #3d3d3d;}'
               'QPushButton:hover{background:#383838;}')
        self.regen_btn   = QPushButton('↺ Reset grid')
        self.preview_btn = QPushButton('Preview')
        self.preview_btn.setCheckable(True)
        for b in (self.regen_btn, self.preview_btn):
            b.setStyleSheet(_ts); hl.addWidget(b)

        hl.addStretch()

        self.open_btn  = QPushButton('Open…')
        self.save_btn  = QPushButton('Save…')
        self.apply_btn = QPushButton('✓  Apply to project')
        self.open_btn.setStyleSheet(_ts)
        self.save_btn.setStyleSheet(
            'QPushButton{background:#1a5a90;color:#fff;border:none;'
            'border-radius:5px;padding:5px 12px;}'
            'QPushButton:hover{background:#4a9eff;}')
        self.apply_btn.setStyleSheet(
            'QPushButton{background:#1d7a4a;color:#fff;border:none;'
            'border-radius:5px;padding:5px 12px;}'
            'QPushButton:hover{background:#2ecc71;}')
        for b in (self.open_btn, self.save_btn, self.apply_btn):
            hl.addWidget(b)
        return w

    def _build_toolbar(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet('background:#212121; border-bottom:1px solid #2d2d2d;')
        tl = QHBoxLayout(w)
        tl.setContentsMargins(8, 3, 8, 3)
        tl.setSpacing(4)

        _ts = ('QPushButton{background:#2a2a2a;border-radius:4px;'
               'padding:3px 9px;border:1px solid #383838;}'
               'QPushButton:hover{background:#363636;}')
        btns = [
            ('+ Add',        self._add_slot),
            ('⎘ Duplicate',  self._duplicate),
            ('✕ Delete',     self._delete),
        ]
        for label, slot in btns:
            b = QPushButton(label)
            b.setStyleSheet(_ts); b.clicked.connect(slot); tl.addWidget(b)

        tl.addWidget(self._separator())

        align_btns = [
            ('⬤L Align left',   lambda: self.canvas.align_selected('x', 'left')),
            ('⬤R Align right',  lambda: self.canvas.align_selected('x', 'right')),
            ('⬤T Align top',    lambda: self.canvas.align_selected('y', 'top')),
            ('⬤B Align bottom', lambda: self.canvas.align_selected('y', 'bottom')),
            ('↔ Distribute H',  lambda: self.canvas.distribute_h()),
            ('↕ Distribute V',  lambda: self.canvas.distribute_v()),
        ]
        for label, slot in align_btns:
            b = QPushButton(label)
            b.setStyleSheet(_ts); b.clicked.connect(slot); tl.addWidget(b)

        tl.addWidget(self._separator())

        # Snap toggle
        self.snap_check = QCheckBox('🧲 Snap')
        self.snap_check.setChecked(True)
        self.snap_check.setStyleSheet(
            'QCheckBox{color:#bbb; font-size:11px;}'
            'QCheckBox::indicator{width:14px;height:14px;}')
        self.snap_check.setToolTip(
            'Snap slots to grid positions and to edges of other slots')
        tl.addWidget(self.snap_check)

        tl.addStretch()
        self.info_label = QLabel('')
        self.info_label.setStyleSheet('color:#555; font-size:10px;')
        tl.addWidget(self.info_label)
        return w

    @staticmethod
    def _separator() -> QWidget:
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setStyleSheet('background:#3a3a3a;')
        return sep

    def _wire_signals(self):
        self.canvas.slotSelected.connect(self.props.set_slot)
        self.canvas.slotSelected.connect(self._on_slot_selected)
        self.canvas.templateChanged.connect(self._on_template_changed)
        self.props.slotChanged.connect(self.canvas.update)
        self.props.slotChanged.connect(self._update_info)

        self.name_edit.textChanged.connect(
            lambda t: setattr(self._template, 'name', t))
        self.aw_spin.valueChanged.connect(self._on_ratio_changed)
        self.ah_spin.valueChanged.connect(self._on_ratio_changed)
        self.count_spin.valueChanged.connect(
            lambda v: setattr(self._template, 'target_image_count', v))

        # Preset combo
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)

        # Snap toggle
        self.snap_check.toggled.connect(
            lambda checked: setattr(self.canvas, 'snap_enabled', checked))

        self.regen_btn.clicked.connect(self._regenerate)
        self.preview_btn.toggled.connect(self.canvas.set_preview)
        self.save_btn.clicked.connect(self._save)
        self.open_btn.clicked.connect(self._open)
        self.apply_btn.clicked.connect(self._apply)

    def _on_ratio_changed(self) -> None:
        """Sync ratio spinboxes → template and reset preset combo to 'Custom'."""
        self._template.base_aspect_w = self.aw_spin.value()
        self._template.base_aspect_h = self.ah_spin.value()
        self.canvas.update()
        # Switch preset combo to 'Custom ratio…' without re-triggering
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

    def _on_preset_selected(self, idx: int) -> None:
        """Apply the selected size preset to the ratio spinboxes."""
        _, aw, ah = self._size_presets[idx]
        if aw is None:
            return   # 'Custom ratio…' — do nothing
        self.aw_spin.blockSignals(True)
        self.ah_spin.blockSignals(True)
        self.aw_spin.setValue(aw)
        self.ah_spin.setValue(ah)
        self.aw_spin.blockSignals(False)
        self.ah_spin.blockSignals(False)
        self._template.base_aspect_w = aw
        self._template.base_aspect_h = ah
        self.canvas.update()

    def _load_template_to_ui(self):
        self.name_edit.setText(self._template.name)
        # Block signals so we don't reset preset combo prematurely
        self.aw_spin.blockSignals(True); self.ah_spin.blockSignals(True)
        self.aw_spin.setValue(self._template.base_aspect_w)
        self.ah_spin.setValue(self._template.base_aspect_h)
        self.aw_spin.blockSignals(False); self.ah_spin.blockSignals(False)
        self.count_spin.setValue(self._template.target_image_count)
        self.preset_combo.setCurrentIndex(0)   # reset to "Custom ratio…"
        self._update_info()

    # ── Slots ─────────────────────────────────────────────────────────────

    def _on_slot_selected(self, slot):
        self._update_info()

    def _on_template_changed(self):
        if self.canvas._selected:
            self.props.set_slot(self.canvas._selected)
        self._update_info()

    def _update_info(self):
        n = len(self._template.slots)
        sel = self.canvas._selected
        parts = [f'{n} slot{"s" if n != 1 else ""}']
        if sel:
            parts.append(
                f'  #{self._template.slots.index(sel)+1}  '
                f'{sel.w:.2f}×{sel.h:.2f}  @ ({sel.x:.2f},{sel.y:.2f})')
        self.info_label.setText('  '.join(parts))

    def _add_slot(self):
        self.canvas.add_slot()

    def _duplicate(self):
        self.canvas.duplicate_selected()

    def _delete(self):
        self.canvas.delete_selected()

    def _regenerate(self):
        n = self.count_spin.value()
        self._template.target_image_count = n
        self._template.auto_grid(n)
        self.canvas._selected = None
        self.props.set_slot(None)
        self.canvas.update()
        self._update_info()

    def _save(self):
        os.makedirs(_DEFAULT_TEMPLATES_DIR, exist_ok=True)
        # Suggest a filename based on the template name
        suggested = os.path.join(
            _DEFAULT_TEMPLATES_DIR,
            self._template.name.replace(' ', '_') + '.json',
        )
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save Template', suggested, 'Collage templates (*.json)')
        if not path:
            return
        if not path.lower().endswith('.json'):
            path += '.json'
        self._template.name = self.name_edit.text().strip() or 'Untitled'
        try:
            save_template(self._template, path)
            self._save_path = path
            self.templateSaved.emit(path)
            self.setWindowTitle(f'Template Creator — {self._template.name}')
        except Exception as exc:
            QMessageBox.warning(self, 'Save failed', str(exc))

    def _open(self):
        os.makedirs(_DEFAULT_TEMPLATES_DIR, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self, 'Open Template', _DEFAULT_TEMPLATES_DIR, 'Collage templates (*.json)')
        if not path:
            return
        try:
            t = load_template(path)
            self._template = t
            self.canvas.set_template(t)
            self._load_template_to_ui()
            self._save_path = path
            self.setWindowTitle(f'Template Creator — {t.name}')
        except Exception as exc:
            QMessageBox.warning(self, 'Open failed', str(exc))

    def _apply(self):
        self._template.name = self.name_edit.text().strip() or 'Untitled'
        self.accept()

    # ── Public ────────────────────────────────────────────────────────────

    def get_template(self) -> Template:
        self._template.name = self.name_edit.text().strip() or 'Untitled'
        return self._template
