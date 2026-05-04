"""Binary split-tree layout model.

A LayoutTree divides the canvas recursively into rectangular cells:
  SplitNode — splits its rectangle into two children along one axis
  LeafNode  — terminal node, holds one image slot

Direction convention
--------------------
  'H'  children arranged side-by-side (LEFT | RIGHT)   divider = vertical line
  'V'  children stacked top-to-bottom  (TOP  / BOTTOM)  divider = horizontal line
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass
class LeafNode:
    """Terminal node – displays one image (or an empty placeholder)."""
    image_index: Optional[int] = None

    # Assigned by compute_rects(); never set manually
    x: float = field(default=0.0, compare=False, repr=False)
    y: float = field(default=0.0, compare=False, repr=False)
    w: float = field(default=0.0, compare=False, repr=False)
    h: float = field(default=0.0, compare=False, repr=False)


@dataclass
class SplitNode:
    """Internal node – divides its rectangle along one axis.

    direction='H': first child LEFT  (ratio × width), second child RIGHT
    direction='V': first child TOP   (ratio × height), second child BOTTOM
    ratio: fraction for the first child; 0 < ratio < 1
    """
    direction: str          # 'H' or 'V'
    ratio: float            # 0.0 < ratio < 1.0
    first: 'Node'
    second: 'Node'

    # Assigned by compute_rects(); never set manually
    x: float = field(default=0.0, compare=False, repr=False)
    y: float = field(default=0.0, compare=False, repr=False)
    w: float = field(default=0.0, compare=False, repr=False)
    h: float = field(default=0.0, compare=False, repr=False)


Node = Union[SplitNode, LeafNode]


@dataclass
class LayoutTree:
    """Root wrapper – holds the tree root and per-tree spacing."""
    root: Optional[Node] = None
    spacing: int = 10           # gap between cells, in full-canvas pixels
