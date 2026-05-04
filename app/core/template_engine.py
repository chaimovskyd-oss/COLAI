"""app/core/template_engine.py — Bridge between Template and the collage system.

Converts relative Template geometry → pixel-based LayoutSuggestion so the
existing canvas, exporter, and project IO work unchanged.

Public API:
    template_to_layout(template, canvas_px)  → LayoutSuggestion
    layout_to_template(layout, canvas_px)    → Template  (round-trip)
    apply_template_to_project(template, project) → LayoutSuggestion
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Tuple

from app.models.project import CellRect, LayoutSuggestion
from app.models.template import SlotShape, Template, TemplateSlot

if TYPE_CHECKING:
    from app.models.project import ProjectState


def template_to_layout(
    template: Template,
    canvas_px: Tuple[int, int],
) -> LayoutSuggestion:
    """Map template relative slots → pixel CellRects for *canvas_px*.

    The resulting LayoutSuggestion is fully compatible with the existing
    canvas, exporter, and project-IO — no changes needed in those layers.

    image_index is assigned sequentially (slot 0 → image 0, etc.).
    Slots beyond target_image_count get image_index=None.
    """
    cw, ch = canvas_px
    cells = []
    for i, slot in enumerate(template.slots):
        cell = CellRect(
            x           = round(slot.x * cw),
            y           = round(slot.y * ch),
            w           = max(1, round(slot.w * cw)),
            h           = max(1, round(slot.h * ch)),
            image_index = i if i < template.target_image_count else None,
        )
        # Carry per-cell shape from the template slot
        cell.shape_type   = slot.shape.shape_type
        cell.shape_params = dict(slot.shape.params)
        cells.append(cell)

    layout = LayoutSuggestion(name=template.name, cells=cells, score=1.0)
    layout.shape       = ''    # no global shape mask
    layout.tree        = None  # not a tree-based layout
    layout.template_id = template.id   # for round-trip editing
    return layout


def layout_to_template(
    layout: LayoutSuggestion,
    canvas_px: Tuple[int, int],
    name: str = 'Imported Layout',
) -> Template:
    """Convert any existing pixel-based layout to a reusable Template.

    Useful for turning a generated or dynamic layout into a saved template.
    """
    cw, ch = canvas_px
    slots = []
    for cell in layout.cells:
        slots.append(TemplateSlot(
            id    = uuid.uuid4().hex[:8],
            x     = round(cell.x / cw, 4),
            y     = round(cell.y / ch, 4),
            w     = round(cell.w / cw, 4),
            h     = round(cell.h / ch, 4),
            shape = SlotShape.make('rectangle'),
        ))

    return Template(
        id                  = uuid.uuid4().hex[:12],
        name                = name,
        base_aspect_w       = float(cw),
        base_aspect_h       = float(ch),
        target_image_count  = len(slots),
        slots               = slots,
    )


def apply_template_to_project(
    template: Template,
    project: 'ProjectState',
) -> LayoutSuggestion:
    """Apply *template* to *project*, returning the new selected layout.

    Inserts the layout at the front of project.suggestions (or replaces an
    existing entry with the same template_id).  Sets it as selected.
    Images are assigned in order up to the number of available images.
    """
    layout = template_to_layout(template, project.settings.canvas_px)

    # Assign images
    for i, cell in enumerate(layout.cells):
        cell.image_index = i if i < len(project.images) else None

    # Replace existing template layout or insert at front
    existing_idx = next(
        (i for i, s in enumerate(project.suggestions)
         if getattr(s, 'template_id', '') == template.id),
        None,
    )
    if existing_idx is not None:
        project.suggestions[existing_idx] = layout
    else:
        project.suggestions.insert(0, layout)

    project.selected_layout = layout
    return layout
