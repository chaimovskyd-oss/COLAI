"""Project save / load serialises ProjectState to a JSON file."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from app.models.project import (
    AnalysisBox,
    CellRect,
    ColorEqualizerState,
    CropRisk,
    ElementOverlay,
    FaceDetectionData,
    ImageAnalysis,
    ImageState,
    LayoutSuggestion,
    PersonDetectionData,
    ProjectSettings,
    ProjectState,
    SafeRegions,
    TextOverlay,
)

_FORMAT_VERSION = 1


def save_project(project: ProjectState, path: str) -> None:
    data: Dict[str, Any] = {
        'version': _FORMAT_VERSION,
        'settings': _settings_to_dict(project.settings),
        'images': [_image_to_dict(s) for s in project.images],
        'text_overlay': _text_to_dict(project.text_overlay),
        'text_overlays': [_text_to_dict(o) for o in project.text_overlays],
        'selected_layout_index': (
            project.suggestions.index(project.selected_layout)
            if project.selected_layout in project.suggestions else -1
        ),
        'suggestions': [_layout_to_dict(l) for l in project.suggestions],
        'elements': [_element_to_dict(e) for e in project.elements],
    }
    album_state = getattr(project, 'album_state', None)
    if album_state is not None:
        data['album_state'] = _album_to_dict(album_state)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def load_project(path: str) -> ProjectState:
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    if raw.get('version', 0) != _FORMAT_VERSION:
        raise ValueError(f"Unsupported project file version: {raw.get('version')}")

    project = ProjectState()
    project.settings = _settings_from_dict(raw['settings'])
    project.images = [_image_from_dict(d) for d in raw.get('images', [])]
    project.text_overlay = _text_from_dict(raw.get('text_overlay', {}))
    project.text_overlays = [_text_from_dict(d) for d in raw.get('text_overlays', [])]
    project.suggestions = [_layout_from_dict(d) for d in raw.get('suggestions', [])]

    sel_idx = raw.get('selected_layout_index', -1)
    if 0 <= sel_idx < len(project.suggestions):
        project.selected_layout = project.suggestions[sel_idx]

    project.elements = [_element_from_dict(d) for d in raw.get('elements', [])]
    if raw.get('album_state'):
        project.album_state = _album_from_dict(raw.get('album_state', {}))
    return project


def _box_to_dict(box: AnalysisBox | None) -> Dict | None:
    if box is None:
        return None
    return {
        'left': box.left,
        'top': box.top,
        'right': box.right,
        'bottom': box.bottom,
    }


def _box_from_dict(d: Dict | None) -> AnalysisBox | None:
    if not d:
        return None
    return AnalysisBox(
        left=float(d.get('left', 0.0)),
        top=float(d.get('top', 0.0)),
        right=float(d.get('right', 0.0)),
        bottom=float(d.get('bottom', 0.0)),
    )


def _settings_to_dict(s: ProjectSettings) -> Dict:
    return {
        'width_cm': s.width_cm,
        'height_cm': s.height_cm,
        'dpi': s.dpi,
        'margin_mm': s.margin_mm,
        'spacing_mm': s.spacing_mm,
        'background_rgb': list(s.background_rgb),
        'background_type': s.background_type,
        'background_gradient': [list(c) for c in s.background_gradient],
        'background_gradient_angle': s.background_gradient_angle,
        'background_image_path': s.background_image_path,
        'corner_radius_mm': s.corner_radius_mm,
        'border_width_mm': s.border_width_mm,
        'border_color_rgb': list(s.border_color_rgb),
        'shadow_enabled': s.shadow_enabled,
        'shadow_offset_mm': s.shadow_offset_mm,
        'shadow_blur_mm': s.shadow_blur_mm,
        'shadow_opacity': s.shadow_opacity,
        'soft_fade_enabled': s.soft_fade_enabled,
        'soft_fade_amount_px': s.soft_fade_amount_px,
        'soft_fade_mode': s.soft_fade_mode,
        'soft_fade_sides': s.soft_fade_sides,
        'soft_fade_overlap_px': s.soft_fade_overlap_px,
        'soft_fade_overlap_sides': s.soft_fade_overlap_sides,
        'soft_fade_curve': s.soft_fade_curve,
        'soft_fade_spacing_override_enabled': s.soft_fade_spacing_override_enabled,
        'soft_fade_spacing_override_px': s.soft_fade_spacing_override_px,
        'bleed_mm': s.bleed_mm,
        'safe_area_mm': s.safe_area_mm,
        'smart_crop_enabled': s.smart_crop_enabled,
        'smart_crop_debug': s.smart_crop_debug,
        'analysis_mode': s.analysis_mode,
        'advanced_face_backend': s.advanced_face_backend,
    }


def _settings_from_dict(d: Dict) -> ProjectSettings:
    s = ProjectSettings()
    s.width_cm = d.get('width_cm', s.width_cm)
    s.height_cm = d.get('height_cm', s.height_cm)
    s.dpi = d.get('dpi', s.dpi)
    if 'margin_mm' in d:
        s.margin_mm = float(d.get('margin_mm', s.margin_mm))
    else:
        s.margin_px = d.get('margin_px', s.margin_px)
    if 'spacing_mm' in d:
        s.spacing_mm = float(d.get('spacing_mm', s.spacing_mm))
    else:
        s.spacing_px = d.get('spacing_px', s.spacing_px)
    s.background_rgb = tuple(d.get('background_rgb', list(s.background_rgb)))
    s.background_type = d.get('background_type', s.background_type)
    raw_grad = d.get('background_gradient')
    if raw_grad:
        s.background_gradient = tuple(tuple(c) for c in raw_grad)
    s.background_gradient_angle = d.get('background_gradient_angle', s.background_gradient_angle)
    s.background_image_path = d.get('background_image_path', s.background_image_path)
    s.corner_radius_mm = d.get('corner_radius_mm', s.corner_radius_mm)
    s.border_width_mm = d.get('border_width_mm', s.border_width_mm)
    s.border_color_rgb = tuple(d.get('border_color_rgb', list(s.border_color_rgb)))
    s.shadow_enabled = d.get('shadow_enabled', s.shadow_enabled)
    s.shadow_offset_mm = d.get('shadow_offset_mm', s.shadow_offset_mm)
    s.shadow_blur_mm = d.get('shadow_blur_mm', s.shadow_blur_mm)
    s.shadow_opacity = d.get('shadow_opacity', s.shadow_opacity)
    s.soft_fade_enabled = d.get('soft_fade_enabled', s.soft_fade_enabled)
    s.soft_fade_amount_px = int(d.get('soft_fade_amount_px', s.soft_fade_amount_px))
    s.soft_fade_mode = d.get('soft_fade_mode', s.soft_fade_mode)
    s.soft_fade_sides = d.get('soft_fade_sides', s.soft_fade_sides)
    s.soft_fade_overlap_px = int(d.get('soft_fade_overlap_px', s.soft_fade_overlap_px))
    s.soft_fade_overlap_sides = d.get('soft_fade_overlap_sides', s.soft_fade_overlap_sides)
    s.soft_fade_curve = d.get('soft_fade_curve', s.soft_fade_curve)
    s.soft_fade_spacing_override_enabled = d.get(
        'soft_fade_spacing_override_enabled', s.soft_fade_spacing_override_enabled
    )
    s.soft_fade_spacing_override_px = int(d.get('soft_fade_spacing_override_px', s.soft_fade_spacing_override_px))
    s.bleed_mm = d.get('bleed_mm', s.bleed_mm)
    s.safe_area_mm = d.get('safe_area_mm', s.safe_area_mm)
    s.smart_crop_enabled = d.get('smart_crop_enabled', s.smart_crop_enabled)
    s.smart_crop_debug = d.get('smart_crop_debug', s.smart_crop_debug)
    s.analysis_mode = d.get('analysis_mode', s.analysis_mode)
    s.advanced_face_backend = d.get('advanced_face_backend', s.advanced_face_backend)
    return s


def _analysis_to_dict(a: ImageAnalysis) -> Dict:
    return {
        'image_id': a.image_id,
        'source_path': a.source_path,
        'image_size': list(a.image_size),
        'preview_size': list(a.preview_size),
        'faces': [{
            'bbox': _box_to_dict(f.bbox),
            'confidence': f.confidence,
            'area_ratio': f.area_ratio,
            'center': list(f.center),
            'keypoints': {k: list(v) for k, v in f.keypoints.items()},
        } for f in a.faces],
        'persons': [{
            'bbox': _box_to_dict(p.bbox),
            'confidence': p.confidence,
            'area_ratio': p.area_ratio,
            'center': list(p.center),
        } for p in a.persons],
        'image_type': a.image_type,
        'crop_tolerance': a.crop_tolerance,
        'safe_regions': {
            'face_safe_region': _box_to_dict(a.safe_regions.face_safe_region),
            'person_safe_region': _box_to_dict(a.safe_regions.person_safe_region),
            'combined_safe_region': _box_to_dict(a.safe_regions.combined_safe_region),
        },
        'warnings_metadata': [{
            'warning_type': w.warning_type,
            'message': w.message,
            'severity': w.severity,
            'suggestion': w.suggestion,
        } for w in a.warnings_metadata],
        'analyzed_at': a.analyzed_at,
        'cache_key': a.cache_key,
        'detector_versions': dict(a.detector_versions),
        'future_hooks': dict(a.future_hooks),
    }


def _analysis_from_dict(d: Dict | None) -> ImageAnalysis | None:
    if not d:
        return None
    safe = d.get('safe_regions', {})
    analysis = ImageAnalysis(
        image_id=d.get('image_id', ''),
        source_path=d.get('source_path', ''),
        image_size=tuple(d.get('image_size', [0, 0])),
        preview_size=tuple(d.get('preview_size', [0, 0])),
        image_type=d.get('image_type', 'no people'),
        crop_tolerance=d.get('crop_tolerance', 'low'),
        safe_regions=SafeRegions(
            face_safe_region=_box_from_dict(safe.get('face_safe_region')),
            person_safe_region=_box_from_dict(safe.get('person_safe_region')),
            combined_safe_region=_box_from_dict(safe.get('combined_safe_region')),
        ),
        warnings_metadata=[
            CropRisk(
                warning_type=w.get('warning_type', ''),
                message=w.get('message', ''),
                severity=w.get('severity', 'info'),
                suggestion=w.get('suggestion', ''),
            )
            for w in d.get('warnings_metadata', [])
        ],
        analyzed_at=d.get('analyzed_at', ''),
        cache_key=d.get('cache_key', ''),
        detector_versions=dict(d.get('detector_versions', {})),
        future_hooks=dict(d.get('future_hooks', {})),
    )
    analysis.faces = [
        FaceDetectionData(
            bbox=_box_from_dict(f.get('bbox')) or AnalysisBox(0.0, 0.0, 0.0, 0.0),
            confidence=float(f.get('confidence', 0.0)),
            area_ratio=float(f.get('area_ratio', 0.0)),
            center=tuple(f.get('center', [0.5, 0.5])),
            keypoints={k: tuple(v) for k, v in f.get('keypoints', {}).items()},
        )
        for f in d.get('faces', [])
    ]
    analysis.persons = [
        PersonDetectionData(
            bbox=_box_from_dict(p.get('bbox')) or AnalysisBox(0.0, 0.0, 0.0, 0.0),
            confidence=float(p.get('confidence', 0.0)),
            area_ratio=float(p.get('area_ratio', 0.0)),
            center=tuple(p.get('center', [0.5, 0.5])),
        )
        for p in d.get('persons', [])
    ]
    return analysis


def _color_equalizer_to_dict(ce: ColorEqualizerState) -> Dict:
    return {
        'enabled': ce.enabled,
        'active_mode': ce.active_mode,
        'hue_values': list(ce.hue_values),
        'saturation_values': list(ce.saturation_values),
        'brightness_values': list(ce.brightness_values),
        'version': ce.version,
    }


def _color_equalizer_from_dict(d: Dict | None) -> ColorEqualizerState:
    ce = ColorEqualizerState()
    if not d:
        return ce
    ce.enabled = bool(d.get('enabled', ce.enabled))
    ce.active_mode = d.get('active_mode', ce.active_mode)
    for attr in ('hue_values', 'saturation_values', 'brightness_values'):
        raw = d.get(attr)
        if raw:
            setattr(ce, attr, [float(v) for v in raw[: len(getattr(ce, attr))]])
            current = getattr(ce, attr)
            if len(current) < 8:
                current.extend([0.0] * (8 - len(current)))
    ce.version = int(d.get('version', ce.version))
    return ce


def _image_to_dict(s: ImageState) -> Dict:
    return {
        'path': s.path,
        'asset_type': getattr(s, 'asset_type', 'photo'),
        'pan_x': s.pan_x,
        'pan_y': s.pan_y,
        'zoom': s.zoom,
        'rotation': s.rotation,
        'brightness': s.brightness,
        'contrast': s.contrast,
        'saturation': s.saturation,
        'sharpness': s.sharpness,
        'is_bw': s.is_bw,
        'face_regions': [list(f) for f in s.face_regions],
        'exposure_ev': s.exposure_ev,
        'levels_r': list(s.levels_r),
        'levels_g': list(s.levels_g),
        'levels_b': list(s.levels_b),
        'clahe_enabled': s.clahe_enabled,
        'clahe_clip': s.clahe_clip,
        'vignette_strength': s.vignette_strength,
        'color_equalizer': _color_equalizer_to_dict(s.color_equalizer),
        'analysis_status': s.analysis_status,
        'analysis': _analysis_to_dict(s.analysis) if s.analysis else None,
    }


def _image_from_dict(d: Dict) -> ImageState:
    return ImageState(
        path=d['path'],
        asset_type=d.get('asset_type', 'photo'),
        pan_x=d.get('pan_x', 0.5),
        pan_y=d.get('pan_y', 0.5),
        zoom=d.get('zoom', 1.0),
        rotation=d.get('rotation', 0),
        brightness=d.get('brightness', 1.0),
        contrast=d.get('contrast', 1.0),
        saturation=d.get('saturation', 1.0),
        sharpness=d.get('sharpness', 1.0),
        is_bw=d.get('is_bw', False),
        face_regions=[tuple(f) for f in d.get('face_regions', [])],
        exposure_ev=d.get('exposure_ev', 0.0),
        levels_r=tuple(d.get('levels_r', [0, 255])),
        levels_g=tuple(d.get('levels_g', [0, 255])),
        levels_b=tuple(d.get('levels_b', [0, 255])),
        clahe_enabled=d.get('clahe_enabled', False),
        clahe_clip=d.get('clahe_clip', 2.0),
        vignette_strength=d.get('vignette_strength', 0.0),
        color_equalizer=_color_equalizer_from_dict(d.get('color_equalizer')),
        analysis_status=d.get('analysis_status', 'pending'),
        analysis=_analysis_from_dict(d.get('analysis')),
    )


def _text_to_dict(o: TextOverlay) -> Dict:
    return {
        'text': o.text,
        'font_family': o.font_family,
        'font_size_pt': o.font_size_pt,
        'font_bold': getattr(o, 'font_bold', False),
        'font_italic': getattr(o, 'font_italic', False),
        'color_rgb': list(o.color_rgb),
        'position': o.position,
        'h_align': o.h_align,
        'padding_mm': o.padding_mm,
        'background_rgb': list(o.background_rgb) if o.background_rgb else None,
        'background_opacity': getattr(o, 'background_opacity', 100),
        'stroke_width_px': getattr(o, 'stroke_width_px', 0),
        'stroke_color_rgb': list(getattr(o, 'stroke_color_rgb', (0, 0, 0))),
        'text_shadow': getattr(o, 'text_shadow', False),
        'text_shadow_offset_px': getattr(o, 'text_shadow_offset_px', 3),
        'text_shadow_color_rgb': list(getattr(o, 'text_shadow_color_rgb', (80, 80, 80))),
        'pos_x_frac': o.pos_x_frac,
        'pos_y_frac': o.pos_y_frac,
    }


def _text_from_dict(d: Dict) -> TextOverlay:
    o = TextOverlay()
    o.text = d.get('text', '')
    o.font_family = d.get('font_family', 'Arial')
    o.font_size_pt = d.get('font_size_pt', 36)
    o.font_bold = d.get('font_bold', False)
    o.font_italic = d.get('font_italic', False)
    o.color_rgb = tuple(d.get('color_rgb', [0, 0, 0]))
    o.position = d.get('position', 'bottom')
    o.h_align = d.get('h_align', 'center')
    o.padding_mm = d.get('padding_mm', 5.0)
    bg = d.get('background_rgb')
    o.background_rgb = tuple(bg) if bg else None
    o.background_opacity = d.get('background_opacity', 100)
    o.stroke_width_px = d.get('stroke_width_px', 0)
    o.stroke_color_rgb = tuple(d.get('stroke_color_rgb', [0, 0, 0]))
    o.text_shadow = d.get('text_shadow', False)
    o.text_shadow_offset_px = d.get('text_shadow_offset_px', 3)
    o.text_shadow_color_rgb = tuple(d.get('text_shadow_color_rgb', [80, 80, 80]))
    o.pos_x_frac = d.get('pos_x_frac', -1.0)
    o.pos_y_frac = d.get('pos_y_frac', -1.0)
    return o


def _layout_to_dict(layout: LayoutSuggestion) -> Dict:
    from app.core.layout_tree_engine import layout_tree_to_dict

    d = {
        'name': layout.name,
        'score': layout.score,
        'shape': getattr(layout, 'shape', ''),
        'cells': [_cell_to_dict(c) for c in layout.cells],
        'tree': layout_tree_to_dict(getattr(layout, 'tree', None)),
    }
    tid = getattr(layout, 'template_id', '')
    if tid:
        d['template_id'] = tid
    return d


def _cell_to_dict(c: CellRect) -> Dict:
    d: Dict = {'x': c.x, 'y': c.y, 'w': c.w, 'h': c.h, 'image_index': c.image_index}
    if getattr(c, 'id', ''):
        d['id'] = c.id
    if getattr(c, 'slot_type', 'photo') != 'photo':
        d['slot_type'] = c.slot_type
    if getattr(c, 'aspect_ratio', None) is not None:
        d['aspect_ratio'] = c.aspect_ratio
    if getattr(c, 'fit_mode', 'fill') != 'fill':
        d['fit_mode'] = c.fit_mode
    if getattr(c, 'locked', False):
        d['locked'] = bool(c.locked)
    if getattr(c, 'cell_text', ''):
        d['cell_text'] = c.cell_text
        d['cell_text_color'] = list(c.cell_text_color)
        d['cell_text_font'] = c.cell_text_font
        d['cell_text_size_pt'] = c.cell_text_size_pt
        d['cell_text_align'] = c.cell_text_align
        d['cell_bg_rgb'] = list(c.cell_bg_rgb) if c.cell_bg_rgb else None
    shape_type = getattr(c, 'shape_type', 'rectangle')
    if shape_type and shape_type != 'rectangle':
        d['shape_type'] = shape_type
        d['shape_params'] = dict(getattr(c, 'shape_params', {}))
    if getattr(c, 'edge_style', 'hard') != 'hard':
        d['edge_style'] = c.edge_style
    if int(getattr(c, 'fade_amount', 16)) != 16:
        d['fade_amount'] = int(getattr(c, 'fade_amount', 16))
    if getattr(c, 'fade_sides', 'all') != 'all':
        d['fade_sides'] = c.fade_sides
    if getattr(c, 'fade_curve', 'smooth') != 'smooth':
        d['fade_curve'] = c.fade_curve
    if float(getattr(c, 'rotation_deg', 0.0)) != 0.0:
        d['rotation_deg'] = float(getattr(c, 'rotation_deg', 0.0))
    if int(getattr(c, 'z_index', 0)) != 0:
        d['z_index'] = int(getattr(c, 'z_index', 0))
    if int(getattr(c, 'mask_seed', 0)) != 0:
        d['mask_seed'] = int(getattr(c, 'mask_seed', 0))
    return d


def _layout_from_dict(d: Dict) -> LayoutSuggestion:
    from app.core.layout_tree_engine import layout_tree_from_dict

    cells = [_cell_from_dict(c) for c in d.get('cells', [])]
    layout = LayoutSuggestion(name=d['name'], cells=cells, score=d.get('score', 0.0))
    layout.shape = d.get('shape', '')
    layout.tree = layout_tree_from_dict(d.get('tree'))
    layout.template_id = d.get('template_id', '')
    return layout


def _cell_from_dict(c: Dict) -> CellRect:
    cell = CellRect(x=c['x'], y=c['y'], w=c['w'], h=c['h'], image_index=c.get('image_index'))
    cell.id = c.get('id', '')
    cell.slot_type = c.get('slot_type', 'photo')
    cell.aspect_ratio = c.get('aspect_ratio')
    cell.fit_mode = c.get('fit_mode', 'fill')
    cell.locked = bool(c.get('locked', False))
    if 'cell_text' in c:
        cell.cell_text = c['cell_text']
        cell.cell_text_color = tuple(c.get('cell_text_color', [0, 0, 0]))
        cell.cell_text_font = c.get('cell_text_font', 'Arial')
        cell.cell_text_size_pt = c.get('cell_text_size_pt', 24.0)
        cell.cell_text_align = c.get('cell_text_align', 'center')
        bg = c.get('cell_bg_rgb')
        cell.cell_bg_rgb = tuple(bg) if bg else None
    cell.shape_type = c.get('shape_type', 'rectangle')
    raw_params = c.get('shape_params', {})
    cell.shape_params = {k: float(v) for k, v in raw_params.items()}
    cell.edge_style = c.get('edge_style', 'hard')
    cell.fade_amount = int(c.get('fade_amount', 16))
    cell.fade_sides = c.get('fade_sides', 'all')
    cell.fade_curve = c.get('fade_curve', 'smooth')
    cell.rotation_deg = float(c.get('rotation_deg', 0.0))
    cell.z_index = int(c.get('z_index', 0))
    cell.mask_seed = int(c.get('mask_seed', 0))
    return cell


def _element_to_dict(e: ElementOverlay) -> Dict:
    return {
        'path': e.path,
        'pos_x_frac': e.pos_x_frac,
        'pos_y_frac': e.pos_y_frac,
        'width_frac': e.width_frac,
        'rotation_deg': e.rotation_deg,
        'opacity': e.opacity,
    }


def _element_from_dict(d: Dict) -> ElementOverlay:
    return ElementOverlay(
        path=d.get('path', ''),
        pos_x_frac=d.get('pos_x_frac', 0.5),
        pos_y_frac=d.get('pos_y_frac', 0.5),
        width_frac=d.get('width_frac', 0.2),
        rotation_deg=d.get('rotation_deg', 0.0),
        opacity=d.get('opacity', 1.0),
    )


def _album_settings_to_dict(settings) -> Dict:
    return {
        'density': getattr(settings, 'density', 'mixed'),
        'min_per_page': getattr(settings, 'min_per_page', 1),
        'max_per_page': getattr(settings, 'max_per_page', 9),
        'hero_pages': getattr(settings, 'hero_pages', True),
        'hero_threshold': getattr(settings, 'hero_threshold', 0.75),
        'title': getattr(settings, 'title', ''),
        'target_pages': getattr(settings, 'target_pages', 0),
    }


def _album_settings_from_dict(d: Dict):
    from app.album_builder.models import AlbumSettings

    settings = AlbumSettings()
    settings.density = d.get('density', settings.density)
    settings.min_per_page = int(d.get('min_per_page', settings.min_per_page))
    settings.max_per_page = int(d.get('max_per_page', settings.max_per_page))
    settings.hero_pages = bool(d.get('hero_pages', settings.hero_pages))
    settings.hero_threshold = float(d.get('hero_threshold', settings.hero_threshold))
    settings.title = d.get('title', settings.title)
    settings.target_pages = int(d.get('target_pages', settings.target_pages))
    return settings


def _photo_meta_to_dict(meta) -> Dict:
    return {
        'path': getattr(meta, 'path', ''),
        'width': getattr(meta, 'width', 0),
        'height': getattr(meta, 'height', 0),
        'orientation': getattr(meta, 'orientation', 'landscape'),
        'sharpness': getattr(meta, 'sharpness', 0.5),
        'brightness': getattr(meta, 'brightness', 0.5),
        'face_count': getattr(meta, 'face_count', 0),
        'is_screenshot': getattr(meta, 'is_screenshot', False),
        'importance': getattr(meta, 'importance', 0.5),
        'phash': getattr(meta, 'phash', ''),
    }


def _photo_meta_from_dict(d: Dict):
    from app.album_builder.models import PhotoMeta

    return PhotoMeta(
        path=d.get('path', ''),
        width=int(d.get('width', 0)),
        height=int(d.get('height', 0)),
        orientation=d.get('orientation', 'landscape'),
        sharpness=float(d.get('sharpness', 0.5)),
        brightness=float(d.get('brightness', 0.5)),
        face_count=int(d.get('face_count', 0)),
        is_screenshot=bool(d.get('is_screenshot', False)),
        importance=float(d.get('importance', 0.5)),
        phash=d.get('phash', ''),
    )


def _album_to_dict(album) -> Dict:
    return {
        'current_page_index': getattr(album, 'current_page_index', 0),
        'settings': _album_settings_to_dict(getattr(album, 'settings', None)),
        'generated': bool(getattr(album, 'generated', False)),
        'photo_metas': [_photo_meta_to_dict(m) for m in getattr(album, 'photo_metas', [])],
        'pages': [
            {
                'page_index': getattr(page, 'page_index', idx),
                'image_indices': list(getattr(page, 'image_indices', [])),
                'layout': _layout_to_dict(page.layout) if getattr(page, 'layout', None) else None,
                'locked': bool(getattr(page, 'locked', False)),
                'label': getattr(page, 'label', ''),
                'text_overlays': [_text_to_dict(o) for o in getattr(page, 'text_overlays', [])],
                'elements': [_element_to_dict(e) for e in getattr(page, 'elements', [])],
            }
            for idx, page in enumerate(getattr(album, 'pages', []))
        ],
    }


def _album_from_dict(d: Dict):
    from app.album_builder.models import AlbumPage, AlbumState

    album = AlbumState()
    album.current_page_index = int(d.get('current_page_index', 0))
    album.settings = _album_settings_from_dict(d.get('settings', {}))
    album.generated = bool(d.get('generated', False))
    album.photo_metas = [_photo_meta_from_dict(m) for m in d.get('photo_metas', [])]
    for idx, raw_page in enumerate(d.get('pages', [])):
        layout_raw = raw_page.get('layout')
        page = AlbumPage(
            page_index=int(raw_page.get('page_index', idx)),
            image_indices=[int(i) for i in raw_page.get('image_indices', [])],
            layout=_layout_from_dict(layout_raw) if layout_raw else None,
            locked=bool(raw_page.get('locked', False)),
            label=raw_page.get('label', ''),
        )
        page.text_overlays = [_text_from_dict(o) for o in raw_page.get('text_overlays', [])]
        page.elements = [_element_from_dict(e) for e in raw_page.get('elements', [])]
        album.pages.append(page)
    return album
