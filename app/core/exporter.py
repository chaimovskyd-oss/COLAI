from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from app.models.project import ProjectState
from app.utils.image_utils import (
    apply_adjustments,
    apply_cell_shape,
    make_background_pil,
    mm_to_px,
    pil_to_qpixmap,
    qpixmap_to_pil,
    render_element_qt,
    render_image_to_size,
    render_text_overlay_qt,
    render_styled_cell,
    crop_with_bg,
    fit_crop_box,
)
from app.utils.cell_edge_render import (
    SOFT_FADE_MIN_ZOOM,
    detect_neighbor_sides,
    expand_crop_box_for_padding,
    resolve_render_padding,
)


def render_project(project: ProjectState, include_bleed: bool = False) -> Image.Image:
    """Full-resolution render from original image files.

    include_bleed=True extends the canvas by bleed_mm on all sides (for export).
    """
    settings = project.settings
    width, height = settings.canvas_px

    bleed_px = mm_to_px(settings.bleed_mm, settings.dpi) if include_bleed else 0

    # Canvas including bleed
    canvas_w = width + 2 * bleed_px
    canvas_h = height + 2 * bleed_px
    canvas = make_background_pil(canvas_w, canvas_h, settings)

    layout = project.selected_layout
    if not layout:
        return canvas

    is_shaped = bool(getattr(layout, 'shape', ''))

    # Style params in full-res pixels
    corner_r = mm_to_px(settings.corner_radius_mm, settings.dpi)
    border_w = mm_to_px(settings.border_width_mm, settings.dpi)
    shadow_off = mm_to_px(settings.shadow_offset_mm, settings.dpi)
    shadow_blur = mm_to_px(settings.shadow_blur_mm, settings.dpi)
    spacing_inset = 0.0
    if getattr(settings, 'soft_fade_spacing_override_enabled', False):
        base_spacing = float(getattr(settings, 'spacing_px', 0))
        target_spacing = float(getattr(settings, 'soft_fade_spacing_override_px', base_spacing))
        spacing_inset = (target_spacing - base_spacing) / 2.0

    # Pre-compute depth maps for all unique images when depth features are active
    _depth_maps: dict = {}
    _depth_enabled = (
        getattr(settings, 'depth_layers_enabled', False)
        or getattr(settings, 'depth_overlap_enabled', False)
    )
    if _depth_enabled:
        try:
            from app.core.depth_service import compute_depth_map
            _seen_paths: set = set()
            for _cell in layout.cells:
                if _cell.image_index is None or _cell.image_index >= len(project.images):
                    continue
                _st = project.images[_cell.image_index]
                if not _st.path or _st.path in _seen_paths:
                    continue
                _seen_paths.add(_st.path)
                try:
                    with Image.open(_st.path) as _raw:
                        _thumb = ImageOps.exif_transpose(_raw).convert('RGB')
                        _thumb.thumbnail((512, 512), Image.Resampling.BILINEAR)
                    _depth_maps[_st.path] = compute_depth_map(_thumb, _st.path)
                except Exception:
                    _depth_maps[_st.path] = None
        except ImportError:
            _depth_enabled = False

    # חפיפת עומק: pre-compute z-boost and soft-expansion per cell index
    _depth_z: dict = {}    # cell_index → extra z_index (foreground renders on top)
    _depth_exp: dict = {}  # cell_index → expand_px added to fade_padding
    if _depth_enabled and getattr(settings, 'depth_overlap_enabled', False):
        try:
            from app.core.depth_service import (
                average_depth_score, compute_depth_z_boost, compute_depth_expand_px,
            )
            _ov_intensity = float(getattr(settings, 'depth_overlap_intensity', 0.5))
            for _ci, _cell in enumerate(layout.cells):
                if _cell.image_index is None or _cell.image_index >= len(project.images):
                    continue
                _dm = _depth_maps.get(project.images[_cell.image_index].path)
                if _dm is None:
                    continue
                _sc = average_depth_score(_dm)
                _depth_z[_ci] = compute_depth_z_boost(_sc)
                _depth_exp[_ci] = compute_depth_expand_px(
                    _sc,
                    max(1, int(min(round(_cell.w), round(_cell.h)))),
                    _ov_intensity,
                )
        except Exception:
            pass

    draw_cells = sorted(
        enumerate(layout.cells),
        key=lambda item: (
            int(getattr(item[1], 'z_index', 0)) + _depth_z.get(item[0], 0),
            item[0],
        ),
    )
    for cell_index, cell in draw_cells:
        if cell.image_index is None or cell.image_index >= len(project.images):
            continue
        state = project.images[cell.image_index]
        x = int(round(cell.x)) + bleed_px
        y = int(round(cell.y)) + bleed_px
        w = max(1, int(round(cell.w)))
        h = max(1, int(round(cell.h)))
        clamped_inset = max(-max(w, h), min(max(0.0, min(w, h) / 2.0 - 1.0), spacing_inset))
        render_x = int(round(x + clamped_inset))
        render_y = int(round(y + clamped_inset))
        render_w = max(1, int(round(w - clamped_inset * 2.0)))
        render_h = max(1, int(round(h - clamped_inset * 2.0)))
        cell_shape  = getattr(cell, 'shape_type', 'rectangle')
        cell_params = getattr(cell, 'shape_params', {})
        has_cell_shape = bool(cell_shape and cell_shape != 'rectangle')
        if (
            (not getattr(settings, 'soft_fade_enabled', False))
            or getattr(layout, 'shape', '')
            or has_cell_shape
            or getattr(cell, 'edge_style', 'hard') == 'torn_paper'
        ):
            # TODO: extend soft fade to shaped layouts once we have shape-aware
            # feathering that preserves current masking semantics.
            fade_padding = (0, 0, 0, 0)
        else:
            overlap_sides = getattr(
                settings, 'soft_fade_overlap_sides', getattr(settings, 'soft_fade_sides', 'all')
            )
            auto_sides = None
            if overlap_sides == 'auto_neighbors':
                auto_sides = detect_neighbor_sides(
                    layout.cells,
                    layout.cells.index(cell),
                    max_gap=max(
                        float(getattr(settings, 'spacing_px', 0)) + float(getattr(settings, 'soft_fade_overlap_px', 0)),
                        float(getattr(settings, 'soft_fade_overlap_px', 0)),
                    ),
                )
            fade_padding = resolve_render_padding(
                'soft_fade',
                getattr(settings, 'soft_fade_mode', 'soft_edge'),
                getattr(settings, 'soft_fade_amount_px', 16),
                getattr(settings, 'soft_fade_overlap_px', 28),
                overlap_sides if getattr(settings, 'soft_fade_mode', 'soft_edge') == 'overlap_fade'
                else getattr(settings, 'soft_fade_sides', 'all'),
                render_w,
                render_h,
                auto_neighbor_sides=auto_sides,
            )
        # חפיפת עומק: add soft expansion to fade_padding for foreground cells.
        # Full expansion zone is feathered → natural edge bleed, zero ghosting.
        _exp = _depth_exp.get(cell_index, 0)
        if _exp > 0:
            fade_padding = tuple(fade_padding[i] + _exp for i in range(4))

        if any(fade_padding):
            with Image.open(state.path) as raw:
                src = ImageOps.exif_transpose(raw).convert('RGB')
            if getattr(state, 'rotation', 0) and state.rotation % 360 != 0:
                src = src.rotate(-state.rotation, expand=True)
            render_zoom = max(float(getattr(state, 'zoom', 1.0)), SOFT_FADE_MIN_ZOOM)
            crop_box = fit_crop_box(
                src.size, (w, h), state.pan_x, state.pan_y, render_zoom,
                clamp=not (is_shaped or has_cell_shape),
            )
            env_crop = expand_crop_box_for_padding(crop_box, (w, h), fade_padding)
            cell_img = crop_with_bg(src, env_crop, settings.background_rgb).resize(
                (render_w + fade_padding[0] + fade_padding[2], render_h + fade_padding[1] + fade_padding[3]),
                Image.Resampling.LANCZOS,
            )
            cell_img = apply_adjustments(cell_img, state)
        else:
            cell_img = render_image_to_size(
                state.path, (w, h), state.pan_x, state.pan_y, state.zoom,
                state=state, use_cache=False,
                clamp=not (is_shaped or has_cell_shape),
                bg_rgb=settings.background_rgb,
            )
            if (render_w, render_h) != (w, h):
                cell_img = cell_img.resize((render_w, render_h), Image.Resampling.LANCZOS)
        if has_cell_shape:
            cell_img = apply_cell_shape(cell_img, cell_shape, cell_params,
                                        settings.background_rgb)
            cell_corner_r = 0
        else:
            cell_corner_r = corner_r

        # שכבות עומק — apply depth-aware visual finishing per cell
        if getattr(settings, 'depth_layers_enabled', False) and _depth_enabled:
            _dm = _depth_maps.get(state.path)
            if _dm is not None:
                try:
                    from app.core.depth_service import apply_depth_layers
                    cell_img = apply_depth_layers(
                        cell_img, _dm,
                        getattr(settings, 'depth_layers_intensity', 0.5),
                    )
                except Exception:
                    pass

        canvas = render_styled_cell(
            canvas, render_x, render_y, render_w, render_h, cell_img,
            corner_radius=cell_corner_r,
            border_width=border_w,
            border_color=settings.border_color_rgb,
            shadow_enabled=(
                settings.shadow_enabled
                or getattr(cell, 'edge_style', '') == 'torn_paper'
                or getattr(cell, 'shape_type', '') == 'ring_segment'
            ),
            shadow_offset=shadow_off,
            shadow_blur=shadow_blur,
            shadow_opacity=settings.shadow_opacity,
            edge_style=getattr(cell, 'edge_style', 'hard') if getattr(cell, 'edge_style', '') == 'torn_paper'
            else ('soft_fade' if any(fade_padding) else 'hard'),
            fade_padding=fade_padding,
            fade_curve=getattr(settings, 'soft_fade_curve', 'smooth'),
            rotation_deg=getattr(cell, 'rotation_deg', 0.0),
            mask_seed=getattr(cell, 'mask_seed', cell_index),
        )

    # Apply shape mask if this is a shaped layout
    if layout and getattr(layout, 'shape', ''):
        from app.utils.image_utils import apply_shape_mask
        canvas = apply_shape_mask(canvas, layout.shape, settings, scale=1.0)

    # חפיפת עומק: Z-order + soft expansion handled inside the main render loop above.
    # No second pass required.

    # Element overlays (above grid, below text overlays)
    if project.elements:
        pixmap_for_el = pil_to_qpixmap(canvas)
        cw, ch = settings.canvas_px
        for el in project.elements:
            pixmap_for_el, _ = render_element_qt(pixmap_for_el, el, cw, ch, scale=1.0)
        canvas = qpixmap_to_pil(pixmap_for_el)

    # Text overlays via Qt (handles RTL, system fonts, bold, italic, stroke, shadow)
    all_overlays = list(project.text_overlays) + (
        [project.text_overlay] if project.text_overlay.text.strip() else []
    )
    if all_overlays:
        pixmap = pil_to_qpixmap(canvas)
        for ov in all_overlays:
            if ov.text.strip():
                pixmap, _ = render_text_overlay_qt(pixmap, ov, settings.dpi, scale=1.0)
        canvas = qpixmap_to_pil(pixmap)

    # Convert back to RGB if RGBA (from shadows)
    if canvas.mode == 'RGBA':
        bg = Image.new('RGB', canvas.size, settings.background_rgb)
        bg.paste(canvas, mask=canvas.split()[3])
        canvas = bg

    return canvas


def export_project(project: ProjectState, output_path: str) -> str:
    settings = project.settings
    suffix = Path(output_path).suffix.lower()
    include_bleed = settings.bleed_mm > 0 and suffix != '.pdf'

    image = render_project(project, include_bleed=include_bleed)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    save_kwargs: dict = {}
    if suffix in {'.jpg', '.jpeg'}:
        save_kwargs = {'quality': 95, 'subsampling': 0,
                       'dpi': (settings.dpi, settings.dpi)}
    elif suffix == '.png':
        save_kwargs = {'dpi': (settings.dpi, settings.dpi)}
    elif suffix == '.pdf':
        # Pillow PDF: bleed handled differently (just use canvas size)
        if include_bleed:
            image = render_project(project, include_bleed=True)
        save_kwargs = {'resolution': settings.dpi}

    image.save(out, **save_kwargs)
    return str(out)
