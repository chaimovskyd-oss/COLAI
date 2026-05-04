"""
app/ui/float_panel.py
Glass-morphism floating panels for in-canvas image adjustment and text editing.
Panels are child widgets of CollageCanvas, positioned automatically near the
selected cell / text overlay.  They are draggable by their title bar.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QMouseEvent, QPainter, QPainterPath,
    QPen, QRegion,
)
from PySide6.QtWidgets import (
    QCheckBox, QFontComboBox, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from app.models.project import ColorEqualizerState
from app.ui.color_equalizer_widget import ColorEqualizerWidget
from app.utils.color_equalizer_processor import reset_all as reset_color_equalizer

# ── colour tokens ──────────────────────────────────────────────────────────────
_BG_BODY   = QColor(13, 15, 25, 255)      # dark navy, fully opaque inside mask
_BG_TITLE  = QColor(22, 26, 42, 255)      # slightly lighter title bar
_SHINE0    = QColor(255, 255, 255, 28)     # glass top-edge shimmer (start)
_BORDER    = QColor(255, 255, 255, 38)     # subtle white border
_ACCENT    = QColor(80, 160, 255, 60)      # blue divider under title
_TEXT      = QColor(220, 225, 240)
_DIM       = QColor(150, 160, 180)

_CORNER    = 13    # border-radius px
_TH        = 30    # title-bar height px
_SHADOW_M  = 4     # extra margin for shadow (px each side)

# ── shared stylesheets ─────────────────────────────────────────────────────────
_SL_QSS = """
    QSlider { margin: 0px; }
    QSlider::groove:horizontal {
        height: 4px;  background: rgba(255,255,255,30);  border-radius: 2px;
    }
    QSlider::handle:horizontal {
        width: 13px;  height: 13px;  margin: -5px 0;
        background: #50a0ff;  border-radius: 6px;
        border: 2px solid rgba(255,255,255,100);
    }
    QSlider::sub-page:horizontal { background: #50a0ff;  border-radius: 2px; }
"""

_BTN_QSS = """
    QPushButton {
        background: rgba(255,255,255,14);  color: rgba(220,225,240,220);
        font-size: 10px;  border: 1px solid rgba(255,255,255,26);
        border-radius: 5px;  padding: 3px 7px;
    }
    QPushButton:hover   { background: rgba(255,255,255,26); }
    QPushButton:pressed { background: rgba(80,160,255,130); border-color: #50a0ff; }
"""

_BTN_ACTIVE_QSS = (
    "QPushButton { background: rgba(80,160,255,140); border-color: #50a0ff; "
    "color: rgba(230,240,255,240); }"
)

_CHK_QSS = """
    QCheckBox { color: rgba(210,218,235,210);  font-size: 10px;  spacing: 5px; }
    QCheckBox::indicator {
        width: 13px;  height: 13px;  border-radius: 3px;
        border: 1px solid rgba(255,255,255,50);
        background: rgba(255,255,255,10);
    }
    QCheckBox::indicator:checked { background: #50a0ff;  border-color: #50a0ff; }
"""

_LBL_QSS = "color: rgba(148,158,178,220);  font-size: 10px;"
_VAL_QSS  = "color: rgba(215,224,242,240);  font-size: 10px;  font-weight: bold;"


# ── tiny helpers ───────────────────────────────────────────────────────────────
def _sl(lo: int, hi: int, val: int) -> QSlider:
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    s.setFixedHeight(18)
    s.setStyleSheet(_SL_QSS)
    return s


def _btn(text: str, w: int = 0) -> QPushButton:
    b = QPushButton(text)
    b.setStyleSheet(_BTN_QSS)
    b.setFocusPolicy(Qt.NoFocus)
    if w:
        b.setFixedWidth(w)
    return b


def _spin(lo: int, hi: int, val: int) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(val)
    s.setFixedHeight(20)
    s.setFixedWidth(46)
    s.setStyleSheet("""
        QSpinBox {
            background: rgba(255,255,255,12);  color: rgba(215,224,242,240);
            border: 1px solid rgba(255,255,255,28);  border-radius: 4px;
            font-size: 10px;  padding: 0 2px;
        }
        QSpinBox::up-button, QSpinBox::down-button { width: 12px; }
    """)
    s.setFocusPolicy(Qt.ClickFocus)
    return s


def _sep() -> QWidget:
    """Thin horizontal rule."""
    line = QWidget()
    line.setFixedHeight(1)
    line.setStyleSheet("background: rgba(255,255,255,18);")
    return line


# ── base glass panel ───────────────────────────────────────────────────────────
class _GlassPanel(QWidget):
    """
    Draggable, closeable, glass-morphism panel (child of CollageCanvas).

    Subclasses implement ``_build(layout)`` to add their widgets.
    The mask is updated on resize so the corners are genuinely transparent.
    """

    closed = Signal()

    def __init__(self, title: str, width: int = 252, parent=None):
        super().__init__(parent)
        self._title   = title
        self._drag_pt: Optional[QPoint] = None
        self._sidebar_mode = (width == 0)   # True → no drag, fills parent width

        # No Qt system background — we paint everything ourselves
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)

        if width:
            self.setFixedWidth(width)
        self.setFocusPolicy(Qt.ClickFocus)

        # Content layout sits below the painted title bar
        root = QVBoxLayout(self)
        root.setContentsMargins(10, _TH + 6, 10, 10)
        root.setSpacing(6)
        self._build(root)
        self.adjustSize()
        self._refresh_mask()

    # ── subclass hook ─────────────────────────────────────────────────────
    def _build(self, layout: QVBoxLayout) -> None:  # noqa: B027
        """Add content to *layout*; called once during __init__."""

    # ── mask ─────────────────────────────────────────────────────────────
    def _refresh_mask(self) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), _CORNER, _CORNER)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_mask()

    # ── painting ──────────────────────────────────────────────────────────
    def paintEvent(self, _) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        r      = QRectF(self.rect())
        r_body = r.adjusted(0, 0, -1, -1)          # body
        r_top  = QRectF(r_body.x(), r_body.y(), r_body.width(), _TH)

        # Body fill
        p.setPen(Qt.NoPen)
        p.setBrush(_BG_BODY)
        p.drawRoundedRect(r_body, _CORNER, _CORNER)

        # Title bar — slightly lighter, rounded only at top
        path = QPainterPath()
        path.addRoundedRect(r_top, _CORNER, _CORNER)
        # square off bottom corners of title bar
        path.addRect(QRectF(r_top.x(), r_top.y() + _CORNER,
                            r_top.width(), _TH - _CORNER))
        p.setBrush(_BG_TITLE)
        p.drawPath(path)

        # Glass shimmer — top-edge gradient
        grad = QLinearGradient(r_body.topLeft(), r_body.adjusted(0, 38, 0, 0).bottomLeft())
        grad.setColorAt(0.0, _SHINE0)
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(grad)
        p.drawRoundedRect(r_body, _CORNER, _CORNER)

        # Accent line under title
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_ACCENT, 1))
        p.drawLine(int(r_body.x() + _CORNER), int(r_body.y() + _TH),
                   int(r_body.right() - _CORNER), int(r_body.y() + _TH))

        # Border
        p.setPen(QPen(_BORDER, 1))
        p.drawRoundedRect(r_body.adjusted(0.5, 0.5, -0.5, -0.5), _CORNER, _CORNER)

        # Title text
        font = p.font()
        font.setBold(True)
        font.setPointSize(9)
        p.setFont(font)
        p.setPen(_TEXT)
        from PySide6.QtCore import QRectF as _RF
        p.drawText(
            _RF(r_body.x() + 10, r_body.y(), r_body.width() - 44, _TH),
            Qt.AlignVCenter | Qt.AlignLeft,
            self._title,
        )

        # Close × button
        font.setBold(False)
        font.setPointSize(13)
        p.setFont(font)
        p.setPen(QPen(QColor(200, 200, 218, 140), 1))
        p.drawText(
            _RF(r_body.right() - 32, r_body.y(), 28, _TH),
            Qt.AlignVCenter | Qt.AlignHCenter,
            '×',
        )
        p.end()

    # ── drag / close ──────────────────────────────────────────────────────
    def _in_title(self, pos: QPoint) -> bool:
        return pos.y() < _TH

    def _in_close(self, pos: QPoint) -> bool:
        return self._in_title(pos) and pos.x() > self.width() - 36

    def mousePressEvent(self, ev: QMouseEvent) -> None:
        pt = ev.position().toPoint()
        if ev.button() == Qt.LeftButton and self._in_title(pt):
            if self._in_close(pt):
                self.hide()
                self.closed.emit()
            elif not self._sidebar_mode:
                self._drag_pt = pt
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:
        if self._drag_pt and ev.buttons() & Qt.LeftButton:
            new = self.pos() + ev.position().toPoint() - self._drag_pt
            par = self.parentWidget()
            if par:
                new.setX(max(0, min(new.x(), par.width()  - self.width())))
                new.setY(max(0, min(new.y(), par.height() - self.height())))
            self.move(new)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        self._drag_pt = None
        super().mouseReleaseEvent(ev)

    # ── helpers for subclasses ────────────────────────────────────────────
    def _slider_row(self, layout: QVBoxLayout, label: str,
                    lo: int, hi: int, val: int):
        """Add a [label][slider][value] row. Returns (QSlider, value QLabel)."""
        row = QHBoxLayout()
        row.setSpacing(5)
        row.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(label)
        lbl.setStyleSheet(_LBL_QSS)
        lbl.setFixedWidth(62)

        s = _sl(lo, hi, val)

        v = QLabel(str(val))
        v.setStyleSheet(_VAL_QSS)
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        v.setFixedWidth(28)

        row.addWidget(lbl)
        row.addWidget(s, 1)
        row.addWidget(v)
        layout.addLayout(row)
        return s, v

    def set_title(self, title: str) -> None:
        self._title = title
        self.update()


# ── Collapsible Advanced Section ──────────────────────────────────────────────
_ADV_TOGGLE_QSS = """
    QPushButton {
        background: rgba(255,255,255,10);  color: rgba(180,192,215,220);
        font-size: 10px;  border: none;  border-radius: 4px;
        padding: 2px 4px;  text-align: left;
    }
    QPushButton:hover { background: rgba(255,255,255,18); }
"""
_ADV_CH_COLORS = [
    ('R', 'rgba(255,90,90,200)',  'rgba(255,60,60,140)'),
    ('G', 'rgba(80,210,100,200)', 'rgba(60,190,80,140)'),
    ('B', 'rgba(90,160,255,200)', 'rgba(60,130,230,140)'),
]

class _AdvancedSection(QWidget):
    """
    Collapsible 'Advanced' area for the image-adjust panel.

    Emits ``changed`` whenever any value is modified.
    """
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._expanded = False
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── toggle header ────────────────────────────────────────────────
        self._toggle_btn = QPushButton('▶  Advanced')
        self._toggle_btn.setStyleSheet(_ADV_TOGGLE_QSS)
        self._toggle_btn.setFocusPolicy(Qt.NoFocus)
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle)
        root.addWidget(self._toggle_btn)

        # ── collapsible body ─────────────────────────────────────────────
        self._body = QWidget()
        body_lay = QVBoxLayout(self._body)
        body_lay.setContentsMargins(4, 6, 0, 2)
        body_lay.setSpacing(6)

        # Exposure — range ±3.00 EV in 0.01 steps → slider int range ±300
        self.exp_sl, self.exp_val = self._row(body_lay, 'Exposure', -300, 300, 0, val_fmt=self._fmt_ev)

        # Vignette — darken edges for a cinematic frame
        self.vig_sl, self.vig_val = self._row(body_lay, 'Vignette', 0, 100, 0, val_fmt=lambda v: f'{v}%')

        # Levels per channel
        ch_hdr = QLabel('Levels  (black → white)')
        ch_hdr.setStyleSheet(_LBL_QSS)
        body_lay.addWidget(ch_hdr)
        self._lvl_lo: list = []
        self._lvl_hi: list = []
        for ch_name, col_hi, col_lo in _ADV_CH_COLORS:
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(ch_name)
            lbl.setStyleSheet(f"color: {col_hi};  font-size: 10px;  font-weight: bold;")
            lbl.setFixedWidth(12)
            lo = _spin(0, 254, 0)
            hi = _spin(1, 255, 255)
            lo.setStyleSheet(lo.styleSheet() + f"border-color: {col_lo};")
            hi.setStyleSheet(hi.styleSheet() + f"border-color: {col_lo};")
            dash = QLabel('–')
            dash.setStyleSheet(_LBL_QSS)
            row.addWidget(lbl)
            row.addWidget(lo)
            row.addWidget(dash)
            row.addWidget(hi)
            row.addStretch()
            body_lay.addLayout(row)
            self._lvl_lo.append(lo)
            self._lvl_hi.append(hi)
            lo.valueChanged.connect(self._on_levels_changed)
            hi.valueChanged.connect(self._on_levels_changed)

        # CLAHE
        clahe_row = QHBoxLayout()
        clahe_row.setSpacing(6)
        self.clahe_chk = QCheckBox('CLAHE contrast')
        self.clahe_chk.setStyleSheet(_CHK_QSS)
        self.clahe_chk.setFocusPolicy(Qt.NoFocus)
        # CLAHE clip 0.00–8.00 in 0.01 steps → slider int range 0–800, default 200 (=2.00)
        self.clahe_sl, self.clahe_val = self._row_inline(clahe_row, 0, 800, 200, val_fmt=lambda v: f'{v/100:.2f}')
        clahe_row.insertWidget(0, self.clahe_chk)
        body_lay.addLayout(clahe_row)

        # Auto Adjust button
        self.auto_btn = _btn('⚡ Auto Adjust')
        self.auto_btn.setToolTip('Automatically stretch per-channel levels (1%–99% histogram)')
        body_lay.addWidget(self.auto_btn)

        root.addWidget(self._body)
        self._body.setVisible(False)

        # wiring
        self.exp_sl.valueChanged.connect(self._on_changed)
        self.vig_sl.valueChanged.connect(self._on_changed)
        self.clahe_chk.stateChanged.connect(self._on_changed)
        self.clahe_sl.valueChanged.connect(self._on_changed)

    # ── layout helpers ────────────────────────────────────────────────────
    def _row(self, layout, label, lo, hi, val, *, val_fmt=None):
        """Add label+slider+value row. Returns (slider, value_label)."""
        row = QHBoxLayout()
        row.setSpacing(5)
        lbl = QLabel(label)
        lbl.setStyleSheet(_LBL_QSS)
        lbl.setFixedWidth(62)
        s = _sl(lo, hi, val)
        display = val_fmt(val) if val_fmt else str(val)
        v = QLabel(display)
        v.setStyleSheet(_VAL_QSS)
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        v.setFixedWidth(34)
        if val_fmt:
            s.valueChanged.connect(lambda x, vl=v, fmt=val_fmt: vl.setText(fmt(x)))
        else:
            s.valueChanged.connect(lambda x, vl=v: vl.setText(str(x)))
        row.addWidget(lbl)
        row.addWidget(s, 1)
        row.addWidget(v)
        layout.addLayout(row)
        return s, v

    def _row_inline(self, h_layout, lo, hi, val, *, val_fmt=None):
        """Add a compact slider+value directly into an existing HBoxLayout."""
        s = _sl(lo, hi, val)
        s.setFixedWidth(70)
        display = val_fmt(val) if val_fmt else str(val)
        v = QLabel(display)
        v.setStyleSheet(_VAL_QSS)
        v.setFixedWidth(28)
        if val_fmt:
            s.valueChanged.connect(lambda x, vl=v, fmt=val_fmt: vl.setText(fmt(x)))
        else:
            s.valueChanged.connect(lambda x, vl=v: vl.setText(str(x)))
        h_layout.addWidget(s)
        h_layout.addWidget(v)
        return s, v

    @staticmethod
    def _fmt_ev(v: int) -> str:
        ev = v / 100.0
        return f'{ev:+.2f}'

    # ── toggle ────────────────────────────────────────────────────────────
    def _toggle(self):
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        arrow = '▼' if self._expanded else '▶'
        self._toggle_btn.setText(f'{arrow}  Advanced')
        # Resize the floating panel only — never touch the main window
        p = self.parentWidget()
        if p is not None:
            p.adjustSize()

    # ── populate from state ───────────────────────────────────────────────
    def load_state(self, state) -> None:
        self._loading = True

        ev_int = int(round(getattr(state, 'exposure_ev', 0.0) * 100))
        self.exp_sl.blockSignals(True)
        self.exp_sl.setValue(ev_int)
        self.exp_sl.blockSignals(False)
        self.exp_val.setText(self._fmt_ev(ev_int))

        for i, attr in enumerate(['levels_r', 'levels_g', 'levels_b']):
            lo_v, hi_v = getattr(state, attr, (0, 255))
            self._lvl_lo[i].blockSignals(True)
            self._lvl_hi[i].blockSignals(True)
            self._lvl_lo[i].setValue(lo_v)
            self._lvl_hi[i].setValue(hi_v)
            self._lvl_lo[i].blockSignals(False)
            self._lvl_hi[i].blockSignals(False)

        clahe_on = getattr(state, 'clahe_enabled', False)
        clip_int = int(round(getattr(state, 'clahe_clip', 2.0) * 100))
        self.clahe_chk.blockSignals(True)
        self.clahe_chk.setChecked(clahe_on)
        self.clahe_chk.blockSignals(False)
        self.clahe_sl.blockSignals(True)
        self.clahe_sl.setValue(clip_int)
        self.clahe_sl.blockSignals(False)
        self.clahe_val.setText(f'{clip_int/100:.2f}')

        vig_int = int(round(getattr(state, 'vignette_strength', 0.0) * 100))
        self.vig_sl.blockSignals(True)
        self.vig_sl.setValue(vig_int)
        self.vig_sl.blockSignals(False)
        self.vig_val.setText(f'{vig_int}%')

        self._loading = False

    def write_state(self, state) -> None:
        """Write current control values back into *state*."""
        state.exposure_ev    = self.exp_sl.value() / 100.0
        state.vignette_strength = self.vig_sl.value() / 100.0
        state.levels_r       = (self._lvl_lo[0].value(), self._lvl_hi[0].value())
        state.levels_g       = (self._lvl_lo[1].value(), self._lvl_hi[1].value())
        state.levels_b       = (self._lvl_lo[2].value(), self._lvl_hi[2].value())
        state.clahe_enabled  = self.clahe_chk.isChecked()
        state.clahe_clip     = self.clahe_sl.value() / 100.0

    def reset(self) -> None:
        """Reset all advanced controls to defaults (does NOT emit changed)."""
        self._loading = True
        self.exp_sl.setValue(0)
        self.exp_val.setText('+0.00')
        self.vig_sl.setValue(0)
        self.vig_val.setText('0%')
        for i in range(3):
            self._lvl_lo[i].setValue(0)
            self._lvl_hi[i].setValue(255)
        self.clahe_chk.setChecked(False)
        self.clahe_sl.setValue(200)
        self.clahe_val.setText('2.00')
        self._loading = False

    # ── slots ─────────────────────────────────────────────────────────────
    def _on_changed(self):
        if not self._loading:
            self.changed.emit()

    def _on_levels_changed(self):
        if self._loading:
            return
        # Enforce lo < hi
        sender = self.sender()
        for i in range(3):
            lo, hi = self._lvl_lo[i], self._lvl_hi[i]
            if sender is lo and lo.value() >= hi.value():
                hi.blockSignals(True)
                hi.setValue(lo.value() + 1)
                hi.blockSignals(False)
            elif sender is hi and hi.value() <= lo.value():
                lo.blockSignals(True)
                lo.setValue(hi.value() - 1)
                lo.blockSignals(False)
        self.changed.emit()


# ── Image Adjust Panel ─────────────────────────────────────────────────────────
class ImageAdjustPanel(_GlassPanel):
    """
    Floating panel with 4 tone sliders + B&W toggle for the selected image.

    Usage::

        panel = ImageAdjustPanel(parent=canvas)
        panel.load_state(image_state)
        panel.move(x, y)
        panel.show()

    Connect ``panel.changed`` to ``canvas.refresh_preview``.
    """

    changed = Signal()   # emitted after any value changes
    previewOriginalPressed = Signal(bool)

    def __init__(self, parent=None, width=256):
        self._state   = None
        self._loading = False
        super().__init__('Adjust Image', width=width, parent=parent)

    # ── build ─────────────────────────────────────────────────────────────
    def _build(self, layout: QVBoxLayout) -> None:
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(6)
        self.adjust_toggle_btn = _btn('כוונון תמונה')
        self.equalizer_toggle_btn = _btn('כוונון צבע מדויק')
        self.adjust_toggle_btn.clicked.connect(lambda: self._set_tool_mode('adjust'))
        self.equalizer_toggle_btn.clicked.connect(lambda: self._set_tool_mode('equalizer'))
        toggle_row.addWidget(self.adjust_toggle_btn)
        toggle_row.addWidget(self.equalizer_toggle_btn)
        layout.addLayout(toggle_row)
        layout.addWidget(_sep())

        self.tools_stack = QStackedWidget()
        self.tools_stack.setStyleSheet('QStackedWidget { background: transparent; }')
        layout.addWidget(self.tools_stack)

        adjust_page = QWidget()
        adjust_layout = QVBoxLayout(adjust_page)
        adjust_layout.setContentsMargins(0, 0, 0, 0)
        adjust_layout.setSpacing(6)
        self.br_sl, self.br_val = self._slider_row(adjust_layout, 'Brightness', 20, 200, 100)
        self.ct_sl, self.ct_val = self._slider_row(adjust_layout, 'Contrast',   20, 200, 100)
        self.st_sl, self.st_val = self._slider_row(adjust_layout, 'Saturation',  0, 200, 100)
        self.sh_sl, self.sh_val = self._slider_row(adjust_layout, 'Sharpness',   0, 200, 100)
        adjust_layout.addWidget(_sep())
        self.adv = _AdvancedSection()
        self.adv.changed.connect(self._on_adv_changed)
        adjust_layout.addWidget(self.adv)
        adjust_layout.addWidget(_sep())

        bot = QHBoxLayout()
        bot.setSpacing(6)
        self.bw_check = QCheckBox('B & W')
        self.bw_check.setStyleSheet(_CHK_QSS)
        self.bw_check.setFocusPolicy(Qt.NoFocus)
        self.reset_btn = _btn('↺ Reset')
        bot.addWidget(self.bw_check)
        bot.addStretch()
        bot.addWidget(self.reset_btn)
        adjust_layout.addLayout(bot)
        adjust_layout.addStretch(1)

        equalizer_page = QWidget()
        equalizer_layout = QVBoxLayout(equalizer_page)
        equalizer_layout.setContentsMargins(0, 0, 0, 0)
        equalizer_layout.setSpacing(6)
        self.equalizer_widget = ColorEqualizerWidget()
        self.equalizer_widget.changed.connect(self._on_equalizer_changed)
        self.equalizer_widget.previewOriginalPressed.connect(self.previewOriginalPressed.emit)
        equalizer_layout.addWidget(self.equalizer_widget)

        self.tools_stack.addWidget(adjust_page)
        self.tools_stack.addWidget(equalizer_page)
        self._tool_mode = 'adjust'
        self._refresh_tool_mode_ui()

        for sl, val_lbl in [
            (self.br_sl, self.br_val), (self.ct_sl, self.ct_val),
            (self.st_sl, self.st_val), (self.sh_sl, self.sh_val),
        ]:
            sl.valueChanged.connect(lambda v, l=val_lbl: l.setText(str(v)))
            sl.valueChanged.connect(self._on_changed)

        self.bw_check.stateChanged.connect(self._on_changed)
        self.reset_btn.clicked.connect(self._on_reset)
        return
        self.br_sl, self.br_val = self._slider_row(layout, 'Brightness', 20, 200, 100)
        self.ct_sl, self.ct_val = self._slider_row(layout, 'Contrast',   20, 200, 100)
        self.st_sl, self.st_val = self._slider_row(layout, 'Saturation',  0, 200, 100)
        self.sh_sl, self.sh_val = self._slider_row(layout, 'Sharpness',   0, 200, 100)

        # ── advanced section (collapsible) ──────────────────────────────
        layout.addWidget(_sep())
        self.adv = _AdvancedSection()
        self.adv.changed.connect(self._on_adv_changed)
        layout.addWidget(self.adv)
        # ── reserved area for future tool additions ─────────────────────
        self._extra_layout = QVBoxLayout()
        self._extra_layout.setSpacing(6)
        layout.addLayout(self._extra_layout)
        # ────────────────────────────────────────────────────────────────

        layout.addWidget(_sep())

        bot = QHBoxLayout()
        bot.setSpacing(6)
        self.bw_check = QCheckBox('B & W')
        self.bw_check.setStyleSheet(_CHK_QSS)
        self.bw_check.setFocusPolicy(Qt.NoFocus)
        self.reset_btn = _btn('↺ Reset')
        bot.addWidget(self.bw_check)
        bot.addStretch()
        bot.addWidget(self.reset_btn)
        layout.addLayout(bot)

        # wiring
        for sl, val_lbl in [
            (self.br_sl, self.br_val), (self.ct_sl, self.ct_val),
            (self.st_sl, self.st_val), (self.sh_sl, self.sh_val),
        ]:
            sl.valueChanged.connect(lambda v, l=val_lbl: l.setText(str(v)))
            sl.valueChanged.connect(self._on_changed)

        self.bw_check.stateChanged.connect(self._on_changed)
        self.reset_btn.clicked.connect(self._on_reset)

    # ── public API ────────────────────────────────────────────────────────
    def load_state(self, state) -> None:
        """Populate controls from an ImageState object."""
        self._state   = state
        self._loading = True

        pairs = [
            (self.br_sl, self.br_val, state.brightness),
            (self.ct_sl, self.ct_val, state.contrast),
            (self.st_sl, self.st_val, state.saturation),
            (self.sh_sl, self.sh_val, state.sharpness),
        ]
        for sl, lbl, v in pairs:
            ival = int(round(v * 100))
            sl.blockSignals(True)
            sl.setValue(ival)
            sl.blockSignals(False)
            lbl.setText(str(ival))

        self.bw_check.blockSignals(True)
        self.bw_check.setChecked(state.is_bw)
        self.bw_check.blockSignals(False)

        self.adv.load_state(state)
        ce_state = getattr(state, 'color_equalizer', None)
        if ce_state is None:
            state.color_equalizer = ColorEqualizerState()
            ce_state = state.color_equalizer
        self.equalizer_widget.load_state(ce_state)
        self._loading = False

        # wire auto-adjust now that state is loaded
        try:
            self.adv.auto_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.adv.auto_btn.clicked.connect(self._on_auto_adjust)

    def retranslate(self) -> None:
        from app.i18n import tr
        self.set_title(tr('Adjust Image'))

    # ── private ───────────────────────────────────────────────────────────
    def _on_changed(self) -> None:
        if self._loading or self._state is None:
            return
        self._state.brightness = self.br_sl.value() / 100.0
        self._state.contrast   = self.ct_sl.value() / 100.0
        self._state.saturation = self.st_sl.value() / 100.0
        self._state.sharpness  = self.sh_sl.value() / 100.0
        self._state.is_bw      = self.bw_check.isChecked()
        self.changed.emit()

    def _on_equalizer_changed(self) -> None:
        if self._loading or self._state is None:
            return
        self.changed.emit()

    def _on_adv_changed(self) -> None:
        if self._loading or self._state is None:
            return
        self.adv.write_state(self._state)
        self.changed.emit()

    def _on_auto_adjust(self) -> None:
        if self._state is None:
            return
        try:
            from PIL import Image
            from app.utils.image_utils import auto_adjust_levels
            img = Image.open(self._state.path).convert('RGB')
            lvl_r, lvl_g, lvl_b = auto_adjust_levels(img)
        except Exception:
            return
        self._state.levels_r = lvl_r
        self._state.levels_g = lvl_g
        self._state.levels_b = lvl_b
        self.adv.load_state(self._state)   # refresh spinboxes (no signal loop)
        self.changed.emit()

    def _on_reset(self) -> None:
        if self._state is None:
            return
        self._loading = True
        for sl, lbl in [
            (self.br_sl, self.br_val), (self.ct_sl, self.ct_val),
            (self.st_sl, self.st_val), (self.sh_sl, self.sh_val),
        ]:
            sl.blockSignals(True)
            sl.setValue(100)
            sl.blockSignals(False)
            lbl.setText('100')
        self.bw_check.blockSignals(True)
        self.bw_check.setChecked(False)
        self.bw_check.blockSignals(False)
        self.adv.reset()
        self._loading = False

        self._state.brightness = self._state.contrast = 1.0
        self._state.saturation = self._state.sharpness = 1.0
        self._state.is_bw = False
        self._state.exposure_ev   = 0.0
        self._state.vignette_strength = 0.0
        self._state.levels_r      = (0, 255)
        self._state.levels_g      = (0, 255)
        self._state.levels_b      = (0, 255)
        self._state.clahe_enabled = False
        self._state.clahe_clip    = 2.0
        reset_color_equalizer(self._state.color_equalizer)
        self._state.color_equalizer.enabled = False
        self.equalizer_widget.load_state(self._state.color_equalizer)
        self.changed.emit()

    def _set_tool_mode(self, mode: str) -> None:
        self._tool_mode = 'equalizer' if mode == 'equalizer' else 'adjust'
        self._refresh_tool_mode_ui()

    def _refresh_tool_mode_ui(self) -> None:
        is_adjust = self._tool_mode == 'adjust'
        self.tools_stack.setCurrentIndex(0 if is_adjust else 1)
        self.adjust_toggle_btn.setStyleSheet(_BTN_ACTIVE_QSS if is_adjust else _BTN_QSS)
        self.equalizer_toggle_btn.setStyleSheet(_BTN_ACTIVE_QSS if not is_adjust else _BTN_QSS)


# ── Text Float Panel ───────────────────────────────────────────────────────────
class TextFloatPanel(_GlassPanel):
    """
    Floating panel for quick editing of a selected committed text overlay.

    Provides position/alignment toggle buttons, font-size slider,
    colour picker, and a delete button.

    Signals:
        changed  — overlay was modified; caller should refresh canvas.
        deleted(int) — user clicked Delete; int is the overlay index.
    """

    changed = Signal()
    deleted = Signal(int)

    def __init__(self, parent=None, width=242):
        self._overlay = None
        self._idx     = -1
        self._loading = False
        super().__init__('Edit Text', width=width, parent=parent)

    # ── build ─────────────────────────────────────────────────────────────
    def _build(self, layout: QVBoxLayout) -> None:
        # Position
        pos_row = QHBoxLayout()
        pos_row.setSpacing(4)
        lbl_p = QLabel('↕')
        lbl_p.setStyleSheet(_LBL_QSS)
        lbl_p.setFixedWidth(16)
        pos_row.addWidget(lbl_p)
        self._pos_btns: dict = {}
        for key, icon in [('top', '⬆ Top'), ('center', '● Mid'), ('bottom', '⬇ Bot')]:
            b = _btn(icon)
            self._pos_btns[key] = b
            b.clicked.connect(lambda _, k=key: self._set_pos(k))
            pos_row.addWidget(b, 1)
        layout.addLayout(pos_row)

        # Align
        align_row = QHBoxLayout()
        align_row.setSpacing(4)
        lbl_a = QLabel('↔')
        lbl_a.setStyleSheet(_LBL_QSS)
        lbl_a.setFixedWidth(16)
        align_row.addWidget(lbl_a)
        self._align_btns: dict = {}
        for key, icon in [('left', '⬛ L'), ('center', '⬛ C'), ('right', '⬛ R')]:
            b = _btn(icon, w=58)
            self._align_btns[key] = b
            b.clicked.connect(lambda _, k=key: self._set_align(k))
            align_row.addWidget(b)
        align_row.addStretch()
        layout.addLayout(align_row)

        layout.addWidget(_sep())

        # Font family
        font_row = QHBoxLayout()
        font_row.setSpacing(5)
        lbl_fnt = QLabel('Font')
        lbl_fnt.setStyleSheet(_LBL_QSS)
        lbl_fnt.setFixedWidth(32)
        self.font_combo = QFontComboBox()
        self.font_combo.setStyleSheet("""
            QFontComboBox {
                background: rgba(255,255,255,12);  color: rgba(215,224,242,240);
                border: 1px solid rgba(255,255,255,28);  border-radius: 4px;
                font-size: 10px;  padding: 1px 4px;
            }
            QFontComboBox::drop-down { width: 16px; }
            QFontComboBox QAbstractItemView {
                background: rgb(22, 26, 42);  color: rgba(215,224,242,240);
                selection-background-color: rgba(80,160,255,140);
                border: 1px solid rgba(255,255,255,40);
            }
        """)
        self.font_combo.setFocusPolicy(Qt.ClickFocus)
        self.font_combo.currentFontChanged.connect(self._set_font)
        font_row.addWidget(lbl_fnt)
        font_row.addWidget(self.font_combo, 1)
        layout.addLayout(font_row)

        layout.addWidget(_sep())

        # Font size
        self.sz_sl, self.sz_val = self._slider_row(layout, 'Size (pt)', 6, 200, 36)
        self.sz_sl.valueChanged.connect(lambda v: (self.sz_val.setText(str(v)),
                                                    self._set_size(v)))

        layout.addWidget(_sep())

        # Colour + Delete
        act = QHBoxLayout()
        act.setSpacing(6)
        self.colour_btn = _btn('🎨 Colour')
        self.del_btn    = _btn('🗑 Delete')
        self.del_btn.setStyleSheet(
            _BTN_QSS + 'QPushButton { color: #e07878; border-color: rgba(220,80,80,45); }'
        )
        self.colour_btn.clicked.connect(self._pick_colour)
        self.del_btn.clicked.connect(self._on_delete)
        act.addWidget(self.colour_btn, 1)
        act.addWidget(self.del_btn, 1)
        layout.addLayout(act)

    # ── public API ────────────────────────────────────────────────────────
    def load_overlay(self, overlay, idx: int) -> None:
        """Populate controls from a TextOverlay and its list index."""
        self._overlay = overlay
        self._idx     = idx
        self._loading = True

        self.font_combo.blockSignals(True)
        self.font_combo.setCurrentFont(QFont(getattr(overlay, 'font_family', 'Arial')))
        self.font_combo.blockSignals(False)

        self.sz_sl.blockSignals(True)
        self.sz_sl.setValue(int(overlay.font_size_pt))
        self.sz_sl.blockSignals(False)
        self.sz_val.setText(str(int(overlay.font_size_pt)))

        self._highlight_pos(overlay.position)
        self._highlight_align(overlay.h_align)

        self._loading = False

    def retranslate(self) -> None:
        from app.i18n import tr
        self.set_title(tr('Edit Text'))

    # ── private ───────────────────────────────────────────────────────────
    def _set_pos(self, pos: str) -> None:
        if self._overlay:
            self._overlay.position    = pos
            # reset manual drag so position button takes effect
            self._overlay.pos_x_frac = -1.0
            self._overlay.pos_y_frac = -1.0
            self._highlight_pos(pos)
            self.changed.emit()

    def _set_align(self, align: str) -> None:
        if self._overlay:
            self._overlay.h_align = align
            self._highlight_align(align)
            self.changed.emit()

    def _set_font(self, font: QFont) -> None:
        if not self._loading and self._overlay:
            self._overlay.font_family = font.family()
            self.changed.emit()

    def _set_size(self, v: int) -> None:
        if self._loading or not self._overlay:
            return
        self._overlay.font_size_pt = v
        self.changed.emit()

    def _pick_colour(self) -> None:
        if not self._overlay:
            return
        from PySide6.QtGui import QColor as _QC
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(_QC(*self._overlay.color_rgb), self)
        if c.isValid():
            self._overlay.color_rgb = (c.red(), c.green(), c.blue())
            self.changed.emit()

    def _on_delete(self) -> None:
        self.deleted.emit(self._idx)
        self.hide()

    def _highlight_pos(self, active: str) -> None:
        for k, b in self._pos_btns.items():
            b.setStyleSheet(_BTN_QSS + (_BTN_ACTIVE_QSS if k == active else ''))

    def _highlight_align(self, active: str) -> None:
        for k, b in self._align_btns.items():
            b.setStyleSheet(_BTN_QSS + (_BTN_ACTIVE_QSS if k == active else ''))
