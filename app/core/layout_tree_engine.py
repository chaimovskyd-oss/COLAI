"""Layout tree engine – computation, traversal, manipulation, serialisation.

Public API
----------
compute_rects(tree, w, h)
    Recursively assign x/y/w/h (in canvas pixels) to every node.

cells_from_tree(tree, canvas_w, canvas_h) -> List[CellRect]
    Run compute_rects then collect leaves as CellRect objects.

collect_leaves(node) -> List[LeafNode]
    Depth-first, left-to-right order.

collect_dividers(node) -> List[(SplitNode, Rect4)]
    Each divider as (node, (x, y, w, h)) in CANVAS pixel coords.
    Rect covers the full-length of the split axis with DIV_HALF_W half-thickness.

hit_divider(dividers, canvas_x, canvas_y, tol) -> Optional[SplitNode]
    Return the first SplitNode whose divider strip is within tol px.

clamp_ratio(node, new_ratio, min_cell_px) -> float
    Ensure both children stay at least min_cell_px pixels wide/tall.

build_tree(n_images, spacing) -> LayoutTree
    Balanced binary tree, alternating H/V splits.

tree_to_dict / tree_from_dict / layout_tree_to_dict / layout_tree_from_dict
    JSON-serialisable round-trip.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.models.layout_tree import SplitNode, LeafNode, Node, LayoutTree
from app.models.project import CellRect

# Minimum usable cell size before clamping prevents further drag
MIN_CELL_PX: float = 80.0

# Half-width of the divider hit-test strip in canvas pixels
# (made wide so it is easy to grab even at small preview scales)
DIV_HALF_W: float = 18.0

Rect4 = Tuple[float, float, float, float]   # x, y, w, h


# ---------------------------------------------------------------------------
# Layout computation
# ---------------------------------------------------------------------------

def compute_rects(
    tree: LayoutTree,
    canvas_w: float,
    canvas_h: float,
) -> None:
    """Fill x/y/w/h on every node using full-canvas pixel coordinates.

    The root covers the entire canvas; spacing is the gap (in pixels)
    reserved between the two halves of each split.
    """
    if tree.root is None:
        return
    _compute(tree.root, 0.0, 0.0, float(canvas_w), float(canvas_h), tree.spacing)


def _compute(
    node: Node,
    x: float, y: float, w: float, h: float,
    sp: int,
) -> None:
    node.x, node.y, node.w, node.h = x, y, w, h
    if isinstance(node, SplitNode):
        half = sp / 2.0
        if node.direction == 'H':
            w1 = max(1.0, w * node.ratio - half)
            w2 = max(1.0, w - w1 - sp)
            _compute(node.first,  x,           y, w1, h, sp)
            _compute(node.second, x + w1 + sp, y, w2, h, sp)
        else:                               # 'V'
            h1 = max(1.0, h * node.ratio - half)
            h2 = max(1.0, h - h1 - sp)
            _compute(node.first,  x, y,           w, h1, sp)
            _compute(node.second, x, y + h1 + sp, w, h2, sp)


# ---------------------------------------------------------------------------
# CellRect conversion
# ---------------------------------------------------------------------------

def cells_from_tree(
    tree: LayoutTree,
    canvas_w: float,
    canvas_h: float,
) -> List[CellRect]:
    """Run compute_rects and return leaves as CellRect objects."""
    compute_rects(tree, canvas_w, canvas_h)
    return [
        CellRect(x=leaf.x, y=leaf.y, w=leaf.w, h=leaf.h,
                 image_index=leaf.image_index)
        for leaf in collect_leaves(tree.root)
    ]


# ---------------------------------------------------------------------------
# Tree traversal
# ---------------------------------------------------------------------------

def collect_leaves(node: Optional[Node]) -> List[LeafNode]:
    """All leaves in depth-first left-to-right order."""
    if node is None:
        return []
    if isinstance(node, LeafNode):
        return [node]
    return collect_leaves(node.first) + collect_leaves(node.second)


def collect_dividers(node: Optional[Node]) -> List[Tuple[SplitNode, Rect4]]:
    """Return (SplitNode, hit-rect) pairs for every SplitNode in DFS order.

    The hit-rect is centred on the divider line with DIV_HALF_W half-thickness,
    and spans the full length of the perpendicular axis.
    """
    if node is None or isinstance(node, LeafNode):
        return []
    assert isinstance(node, SplitNode)

    if node.direction == 'H':
        # Vertical line between first and second children
        div_cx = node.x + node.w * node.ratio   # centre of the divider in canvas X
        rect: Rect4 = (
            div_cx - DIV_HALF_W,  # x
            node.y,               # y
            DIV_HALF_W * 2,       # w
            node.h,               # h
        )
    else:
        # Horizontal line between first and second children
        div_cy = node.y + node.h * node.ratio
        rect = (
            node.x,
            div_cy - DIV_HALF_W,
            node.w,
            DIV_HALF_W * 2,
        )

    return (
        [(node, rect)]
        + collect_dividers(node.first)
        + collect_dividers(node.second)
    )


# ---------------------------------------------------------------------------
# Hit testing
# ---------------------------------------------------------------------------

def hit_divider(
    dividers: List[Tuple[SplitNode, Rect4]],
    canvas_x: float,
    canvas_y: float,
) -> Optional[SplitNode]:
    """Return the first SplitNode whose divider strip contains (canvas_x, canvas_y)."""
    for split_node, (dx, dy, dw, dh) in dividers:
        if dx <= canvas_x <= dx + dw and dy <= canvas_y <= dy + dh:
            return split_node
    return None


def leaf_at(
    node: Optional[Node],
    canvas_x: float,
    canvas_y: float,
) -> Optional[LeafNode]:
    """Return the LeafNode whose rect contains (canvas_x, canvas_y)."""
    if node is None:
        return None
    if canvas_x < node.x or canvas_x > node.x + node.w:
        return None
    if canvas_y < node.y or canvas_y > node.y + node.h:
        return None
    if isinstance(node, LeafNode):
        return node
    hit = leaf_at(node.first, canvas_x, canvas_y)
    return hit if hit is not None else leaf_at(node.second, canvas_x, canvas_y)


# ---------------------------------------------------------------------------
# Ratio clamping
# ---------------------------------------------------------------------------

def clamp_ratio(
    node: SplitNode,
    new_ratio: float,
    min_px: float = MIN_CELL_PX,
) -> float:
    """Clamp ratio so both children are at least min_px wide/tall."""
    size = node.w if node.direction == 'H' else node.h
    if size <= 0:
        return new_ratio
    lo = max(0.02, min_px / size)
    hi = min(0.98, 1.0 - min_px / size)
    return max(lo, min(hi, new_ratio))


# ---------------------------------------------------------------------------
# Tree construction
# ---------------------------------------------------------------------------

def build_tree(n_images: int, spacing: int = 10) -> LayoutTree:
    """Build a balanced binary tree for n_images, alternating H/V splits.

    The ratio at each split is chosen to give roughly equal-area children.
    Returns a tree with root=None if n_images <= 0.
    """
    if n_images <= 0:
        return LayoutTree(root=None, spacing=spacing)
    indices = list(range(n_images))
    root = _build(indices, depth=0)
    return LayoutTree(root=root, spacing=spacing)


def _build(indices: List[int], depth: int) -> Node:
    if len(indices) == 1:
        return LeafNode(image_index=indices[0])
    mid = len(indices) // 2
    direction = 'H' if depth % 2 == 0 else 'V'
    ratio = mid / len(indices)
    return SplitNode(
        direction=direction,
        ratio=float(ratio),
        first=_build(indices[:mid], depth + 1),
        second=_build(indices[mid:], depth + 1),
    )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def tree_to_dict(node: Optional[Node]) -> Optional[Dict[str, Any]]:
    if node is None:
        return None
    if isinstance(node, LeafNode):
        return {'type': 'leaf', 'image_index': node.image_index}
    return {
        'type': 'split',
        'direction': node.direction,
        'ratio': round(node.ratio, 6),
        'first': tree_to_dict(node.first),
        'second': tree_to_dict(node.second),
    }


def tree_from_dict(d: Optional[Dict[str, Any]]) -> Optional[Node]:
    if d is None:
        return None
    if d.get('type') == 'leaf':
        return LeafNode(image_index=d.get('image_index'))
    return SplitNode(
        direction=str(d['direction']),
        ratio=float(d['ratio']),
        first=tree_from_dict(d['first']),   # type: ignore[arg-type]
        second=tree_from_dict(d['second']),  # type: ignore[arg-type]
    )


def layout_tree_to_dict(tree: Optional[LayoutTree]) -> Optional[Dict[str, Any]]:
    if tree is None:
        return None
    return {'root': tree_to_dict(tree.root), 'spacing': tree.spacing}


def layout_tree_from_dict(d: Optional[Dict[str, Any]]) -> Optional[LayoutTree]:
    if d is None:
        return None
    return LayoutTree(
        root=tree_from_dict(d.get('root')),
        spacing=int(d.get('spacing', 10)),
    )
