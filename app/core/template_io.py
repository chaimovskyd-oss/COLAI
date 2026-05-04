"""app/core/template_io.py — Save and load Template objects as JSON.

Templates are stored as plain JSON (no binary blobs) so they are:
  • human-readable
  • version-controllable
  • shareable across machines

All geometry values remain in relative [0..1] units in the file.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from app.models.template import SlotShape, Template, TemplateSlot


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def template_to_dict(t: Template) -> Dict[str, Any]:
    return {
        'version':             t.version,
        'id':                  t.id,
        'name':                t.name,
        'base_aspect_w':       t.base_aspect_w,
        'base_aspect_h':       t.base_aspect_h,
        'target_image_count':  t.target_image_count,
        'spacing':             t.spacing,
        'border':              t.border,
        'family_id':           t.family_id,
        'min_images':          t.min_images,
        'max_images':          t.max_images,
        'slots':               [_slot_to_dict(s) for s in t.slots],
    }


def _slot_to_dict(s: TemplateSlot) -> Dict[str, Any]:
    return {
        'id':       s.id,
        'x':        round(s.x, 6),
        'y':        round(s.y, 6),
        'w':        round(s.w, 6),
        'h':        round(s.h, 6),
        'shape':    {'shape_type': s.shape.shape_type, 'params': s.shape.params},
        'role':     s.role,
        'group_id': s.group_id,
        'required': s.required,
        'label':    s.label,
    }


# ---------------------------------------------------------------------------
# Deserialization
# ---------------------------------------------------------------------------

def template_from_dict(d: Dict[str, Any]) -> Template:
    slots: List[TemplateSlot] = []
    for sd in d.get('slots', []):
        sh = sd.get('shape', {})
        slot = TemplateSlot(
            id       = str(sd.get('id', '')),
            x        = float(sd.get('x', 0.0)),
            y        = float(sd.get('y', 0.0)),
            w        = float(sd.get('w', 0.3)),
            h        = float(sd.get('h', 0.3)),
            shape    = SlotShape(
                shape_type = str(sh.get('shape_type', 'rectangle')),
                params     = {k: float(v) for k, v in sh.get('params', {}).items()},
            ),
            role     = str(sd.get('role', '')),
            group_id = str(sd.get('group_id', '')),
            required = bool(sd.get('required', True)),
            label    = str(sd.get('label', '')),
        )
        slot.clamp()
        slots.append(slot)

    return Template(
        id                  = str(d.get('id', '')),
        name                = str(d.get('name', 'Untitled')),
        base_aspect_w       = float(d.get('base_aspect_w', 3.0)),
        base_aspect_h       = float(d.get('base_aspect_h', 2.0)),
        target_image_count  = int(d.get('target_image_count', len(slots))),
        spacing             = float(d.get('spacing', 0.01)),
        border              = float(d.get('border', 0.005)),
        family_id           = str(d.get('family_id', '')),
        min_images          = int(d.get('min_images', 0)),
        max_images          = int(d.get('max_images', 0)),
        version             = int(d.get('version', 1)),
        slots               = slots,
    )


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def save_template(t: Template, path: str) -> None:
    """Save *t* to a JSON file at *path* (creates parent directories)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(template_to_dict(t), f, indent=2, ensure_ascii=False)


def load_template(path: str) -> Template:
    """Load a Template from a JSON file."""
    with open(path, 'r', encoding='utf-8') as f:
        return template_from_dict(json.load(f))


def load_templates_from_dir(directory: str) -> List[Template]:
    """Load all *.json templates from *directory* (silently skips bad files)."""
    templates: List[Template] = []
    for p in sorted(Path(directory).glob('*.json')):
        try:
            templates.append(load_template(str(p)))
        except Exception:
            pass
    return templates
