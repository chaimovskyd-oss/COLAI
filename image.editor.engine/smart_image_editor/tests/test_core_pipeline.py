from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image, ImageDraw

from smart_image_editor.core.adjustment_pipeline import apply_adjustments, create_preview
from smart_image_editor.ai.face_detection_service import detect_faces, face_mask
from smart_image_editor.ai.upscaler_service import fallback_upscale
from smart_image_editor.ai.segmentation_service import person_mask
from smart_image_editor.ai.smart_auto_fix_service import suggest_smart_auto_fix
from smart_image_editor.core.cache_manager import PreviewCache
from smart_image_editor.core.export_service import export_image
from smart_image_editor.core.histogram import calculate_histogram, suggest_auto_levels
from smart_image_editor.core.hsl_preview_overlay import create_hsl_affected_overlay, create_hsl_color_mask
from smart_image_editor.core.image_state import DEFAULT_PARAMS
from smart_image_editor.core.image_state import ImageState
from smart_image_editor.core.lut import apply_cube_lut
from smart_image_editor.core.photo_tips import PhotoTipsService
from smart_image_editor.core.presets import blend_preset_params
from smart_image_editor.core.target_color import (
    apply_target_color_adjustment,
    create_target_color_mask,
    sample_target_color,
    update_target_color_params,
)
from smart_image_editor.integration.editor_api import process_image_edit


class CorePipelineTests(unittest.TestCase):
    def test_adjustments_keep_image_size_and_mode(self):
        image = Image.new("RGB", (160, 100), (80, 100, 140))
        result = apply_adjustments(
            image,
            {
                "exposure": 0.2,
                "contrast": 12,
                "shadows": 10,
                "temperature": 8,
                "vibrance": 15,
                "sharpness": 8,
                "vignette_amount": -12,
            },
        )
        self.assertEqual(result.size, image.size)
        self.assertEqual(result.mode, "RGB")

    def test_preview_histogram_and_export_contract(self):
        image = Image.new("RGB", (180, 120), (35, 42, 50))
        draw = ImageDraw.Draw(image)
        for x in range(image.width):
            value = int(30 + x / image.width * 180)
            draw.line((x, 0, x, image.height), fill=(value, value + 8, value + 18))
        preview = create_preview(image, max_size=80)
        stats = calculate_histogram(preview)
        self.assertEqual(len(stats.luminance), 256)
        self.assertTrue(suggest_auto_levels(preview))
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.jpg"
            out = Path(tmp) / "edited.jpg"
            preview_out = Path(tmp) / "preview.png"
            image.save(path)
            exported = export_image(image, {"brightness": 10}, out)
            self.assertTrue(exported.exists())
            self.assertTrue(out.with_suffix(".jpg.smartedit.json").exists())
            result = process_image_edit(path, {"contrast": 5}, out, preview_path=preview_out)
            self.assertTrue(result.accepted)
            self.assertTrue(result.exported_path.exists())
            self.assertTrue(result.edited_preview_path.exists())

    def test_tips_preset_intensity_and_cache(self):
        tips = PhotoTipsService().load_tips()
        self.assertGreaterEqual(len(tips), 24)
        self.assertIn("Print", PhotoTipsService().get_categories())
        self.assertTrue(PhotoTipsService().get_suggested_params("dark_photo"))

        blended = blend_preset_params(DEFAULT_PARAMS, {"contrast": 20, "black_white": True}, 50)
        self.assertEqual(blended["contrast"], 10)
        self.assertTrue(blended["black_white"])

        cache = PreviewCache(max_items=1)
        image = Image.new("RGB", (10, 10), (1, 2, 3))
        key = cache.make_key(Path("a.jpg"), {"contrast": 1}, image.size)
        cache.put(key, image)
        self.assertIsNotNone(cache.get(key))
        cache.put(cache.make_key(Path("b.jpg"), {"contrast": 2}, image.size), image)
        self.assertEqual(len(cache), 1)

    def test_v3_ai_services_are_safe_on_synthetic_images(self):
        image = Image.new("RGB", (96, 128), (90, 110, 130))
        mask = person_mask(image)
        self.assertEqual(mask.shape, (128, 96))
        self.assertGreaterEqual(float(mask.max()), 0.0)
        self.assertLessEqual(float(mask.max()), 1.0)
        faces = detect_faces(image)
        self.assertIsInstance(faces, list)
        self.assertEqual(face_mask(image).shape, (128, 96))
        params = suggest_smart_auto_fix(image)
        self.assertTrue(params)
        out = apply_adjustments(
            image,
            {
                "ai_background_blur": 20,
                "ai_background_darkening": 10,
                "ai_subject_enhance": 12,
                "ai_face_brighten": 10,
                "ai_skin_tone_protection": 10,
            },
        )
        self.assertEqual(out.size, image.size)

    def test_adjustment_stack_history_enable_disable_and_undo(self):
        state = ImageState()
        state.update_param("exposure", 0.35)
        self.assertEqual(state.edit_params["exposure"], 0.35)
        self.assertEqual(state.active_adjustments()[0].id, "exposure")
        self.assertIn("Changed Exposure", state.timeline_entries()[0].action)

        state.set_adjustment_enabled("exposure", False)
        self.assertEqual(state.edit_params["exposure"], DEFAULT_PARAMS["exposure"])
        self.assertFalse(next(adj for adj in state.active_adjustments() if adj.id == "exposure").enabled)

        state.undo()
        self.assertEqual(state.edit_params["exposure"], 0.35)
        self.assertTrue(next(adj for adj in state.active_adjustments() if adj.id == "exposure").enabled)

        state.redo()
        self.assertEqual(state.edit_params["exposure"], DEFAULT_PARAMS["exposure"])

        state.remove_adjustment("exposure")
        self.assertFalse(any(adj.id == "exposure" for adj in state.active_adjustments()))
        self.assertIn("Removed Exposure", state.timeline_entries()[0].action)

    def test_v4_lut_and_fallback_upscale(self):
        image = Image.new("RGB", (8, 6), (64, 96, 128))
        with TemporaryDirectory() as tmp:
            lut_path = Path(tmp) / "identity.cube"
            lut_path.write_text(
                "\n".join(
                    [
                        "TITLE \"identity\"",
                        "LUT_3D_SIZE 2",
                        "0 0 0",
                        "0 0 1",
                        "0 1 0",
                        "0 1 1",
                        "1 0 0",
                        "1 0 1",
                        "1 1 0",
                        "1 1 1",
                    ]
                ),
                encoding="utf-8",
            )
            graded = apply_cube_lut(image, str(lut_path), 100)
            self.assertEqual(graded.size, image.size)
        upscaled = fallback_upscale(image, 2)
        self.assertEqual(upscaled.size, (16, 12))

    def test_hsl_affected_area_mask_ignores_neutral_pixels(self):
        image = Image.new("RGB", (4, 2), (128, 128, 128))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 1, 1), fill=(220, 20, 20))
        mask = create_hsl_color_mask(image, "red", feather=False)
        self.assertGreater(float(mask[0, 0]), 0.1)
        self.assertLess(float(mask[0, 3]), 0.05)
        overlay = create_hsl_affected_overlay(image, "red")
        self.assertEqual(overlay.size, image.size)
        original_neutral = image.getpixel((3, 0))
        overlay_neutral = overlay.getpixel((3, 0))
        self.assertEqual(overlay_neutral[0], overlay_neutral[1])
        self.assertEqual(overlay_neutral[1], overlay_neutral[2])
        self.assertNotEqual(overlay.getpixel((0, 0)), original_neutral)

    def test_classic_hsl_sliders_affect_matching_colour(self):
        image = Image.new("RGB", (2, 1))
        image.putpixel((0, 0), (220, 30, 30))
        image.putpixel((1, 0), (30, 220, 30))

        edited = apply_adjustments(
            image,
            {
                "hsl": {
                    "red": {
                        "hue": 45,
                        "saturation": -40,
                        "luminance": 20,
                    }
                }
            },
        )

        self.assertNotEqual(edited.getpixel((0, 0)), image.getpixel((0, 0)))
        self.assertEqual(edited.getpixel((1, 0)), image.getpixel((1, 0)))

    def test_target_color_sampling_mask_and_adjustment(self):
        image = Image.new("RGB", (20, 10), (120, 120, 120))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 9, 9), fill=(220, 20, 80))
        draw.rectangle((10, 0, 19, 9), fill=(20, 120, 220))
        sample = sample_target_color(image, 4, 5, radius=2)
        target = update_target_color_params(None, sample, mode="include")
        mask = create_target_color_mask(image, target, feather=False)
        self.assertGreater(float(mask[5, 4]), 0.2)
        self.assertLess(float(mask[5, 15]), 0.1)
        target["saturation"] = -50
        adjusted = apply_target_color_adjustment(image, target)
        self.assertEqual(adjusted.size, image.size)
        self.assertNotEqual(adjusted.getpixel((4, 5)), image.getpixel((4, 5)))
        self.assertEqual(adjusted.getpixel((15, 5)), image.getpixel((15, 5)))


if __name__ == "__main__":
    unittest.main()
