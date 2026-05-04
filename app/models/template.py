"""app/models/template.py — Parametric template data model.

A Template is a reusable collage layout stored entirely in relative
coordinates (0..1).  This makes it resolution-independent and applicable
to any canvas size or aspect ratio.

Design:
  • TemplateSlot  — one image cell with position, size, and shape
  • SlotShape     — parametric shape descriptor (rectangle, circle, etc.)
  • Template      — collection of slots plus metadata

Future-facing fields (role, group_id, min/max images) are present now so
saved templates are forward-compatible with adaptive logic later.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Dict, List


# ---------------------------------------------------------------------------
# Supported shape types
# ---------------------------------------------------------------------------

SHAPE_TYPES = ('rectangle', 'rounded', 'circle', 'ellipse', 'polygon', 'heart')

_SHAPE_DEFAULT_PARAMS: Dict[str, Dict[str, float]] = {
    'rectangle': {},
    'rounded':   {'corner_radius': 0.15},   # fraction of min(w,h)
    'circle':    {},                          # engine enforces w==h
    'ellipse':   {},
    'polygon':   {'sides': 6.0, 'rotation': 0.0},
    'heart':     {},
}


@dataclass
class SlotShape:
    """Parametric shape for a slot.

    shape_type — one of SHAPE_TYPES
    params     — shape-specific float parameters (see _SHAPE_DEFAULT_PARAMS)
    """
    shape_type: str = 'rectangle'
    params: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def make(cls, shape_type: str) -> 'SlotShape':
        """Create a SlotShape with default parameters for the given type."""
        return cls(
            shape_type=shape_type,
            params=dict(_SHAPE_DEFAULT_PARAMS.get(shape_type, {})),
        )


# ---------------------------------------------------------------------------
# Template slot
# ---------------------------------------------------------------------------

# Smallest allowed slot dimension in relative units
MIN_SLOT_SIZE = 0.02


@dataclass
class TemplateSlot:
    """One image cell inside a template.

    All geometry is in relative units [0..1] where (0,0) is the
    top-left corner of the canvas and (1,1) is the bottom-right.
    """
    id:       str
    x:        float                # left edge
    y:        float                # top edge
    w:        float                # width
    h:        float                # height
    shape:    SlotShape = field(default_factory=SlotShape)

    # Future-facing metadata — safe to leave at defaults in MVP
    role:     str  = ''            # 'center', 'outer', 'accent', …
    group_id: str  = ''
    required: bool = True
    label:    str  = ''

    @classmethod
    def new(cls, x: float = 0.05, y: float = 0.05,
            w: float = 0.30, h: float = 0.30,
            shape_type: str = 'rectangle') -> 'TemplateSlot':
        return cls(
            id    = uuid.uuid4().hex[:8],
            x=x, y=y, w=w, h=h,
            shape = SlotShape.make(shape_type),
        )

    def clamp(self) -> None:
        """Ensure geometry stays within canvas bounds [0..1]."""
        self.w = max(MIN_SLOT_SIZE, min(self.w, 1.0))
        self.h = max(MIN_SLOT_SIZE, min(self.h, 1.0))
        self.x = max(0.0, min(self.x, 1.0 - self.w))
        self.y = max(0.0, min(self.y, 1.0 - self.h))

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

@dataclass
class Template:
    """Reusable parametric collage template.

    Stores layout as relative coordinates so it can be applied to any
    canvas size.  All rendering is deferred to the engine / canvas.
    """
    id:                  str
    name:                str
    base_aspect_w:       float = 3.0   # e.g. 3:2 → landscape
    base_aspect_h:       float = 2.0
    target_image_count:  int   = 4
    slots:               List[TemplateSlot] = field(default_factory=list)

    # Style hints — applied at render time
    spacing: float = 0.010   # inter-slot gap (relative)
    border:  float = 0.005   # outer margin (relative)

    # Future adaptive / template-family support
    family_id:  str = ''
    min_images: int = 0      # 0 means same as target_image_count
    max_images: int = 0      # 0 means same as target_image_count
    version:    int = 1

    # ── Factory ───────────────────────────────────────────────────────────

    @classmethod
    def new(cls, name: str = 'Untitled',
            aspect_w: float = 3.0, aspect_h: float = 2.0,
            n_slots: int = 4) -> 'Template':
        t = cls(
            id              = uuid.uuid4().hex[:12],
            name            = name,
            base_aspect_w   = aspect_w,
            base_aspect_h   = aspect_h,
            target_image_count = n_slots,
        )
        t.auto_grid(n_slots)
        return t

    def auto_grid(self, n: int) -> None:
        """Populate slots with a balanced grid as a starting point."""
        cols = max(1, math.ceil(math.sqrt(n)))
        rows = max(1, math.ceil(n / cols))
        pad  = self.border + self.spacing
        cw   = (1.0 - 2 * pad - (cols - 1) * self.spacing) / cols
        ch   = (1.0 - 2 * pad - (rows - 1) * self.spacing) / rows
        self.slots = []
        for i in range(n):
            c = i % cols
            r = i // cols
            x = pad + c * (cw + self.spacing)
            y = pad + r * (ch + self.spacing)
            self.slots.append(TemplateSlot.new(
                x=round(x, 4), y=round(y, 4),
                w=round(cw, 4), h=round(ch, 4),
            ))
        self.target_image_count = n

    @property
    def aspect_ratio(self) -> float:
        return self.base_aspect_w / max(1e-9, self.base_aspect_h)
