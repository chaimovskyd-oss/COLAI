"""ICCService — ICC color-profile management for the print preview module.

Profile discovery, transform building, caching, and application.
All expensive state is cached at the class level so multiple ICCService
instances (side-panel, renderer, export) share the same work.

Requires Pillow built with littlecms2 (default on Windows and macOS).
Gracefully degrades when PIL is absent or profiles cannot be loaded.
"""

import logging
import os

_log = logging.getLogger(__name__)

# Rendering intent name → littlecms integer constant
_INTENT_MAP: dict[str, int] = {
    "Perceptual":            0,
    "Relative Colorimetric": 1,
    "Saturation":            2,
    "Absolute Colorimetric": 3,
}

# littlecms cmsFLAGS_SOFTPROOFING — works even if Pillow's Flags enum is absent
_FLAG_SOFTPROOFING = 0x4000

# Standard OS directories that hold ICC / ICM profiles
_PROFILE_DIRS = [
    r"C:\Windows\System32\spool\drivers\color",
    "/Library/ColorSync/Profiles",
    "/Library/ColorSync/Profiles/Displays",
    "/usr/share/color/icc",
    "/usr/share/color/icc/colord",
    os.path.expanduser("~/.local/share/icc"),
]


class ICCService:
    """Manages ICC profiles and color transforms for the print preview module.

    Instances share class-level caches for profile discovery and built
    transforms so the filesystem is only scanned once per process.
    """

    # Class-level caches — shared across all instances
    _profiles:   dict[str, str | None] | None = None  # name → path (None = built-in sRGB)
    _transforms: dict[tuple, object]           = {}    # key → CmsTransform | None

    # ── Construction ──────────────────────────────────────────────────────────

    def __init__(self):
        self._pil = self._check_pil()
        if ICCService._profiles is None:
            ICCService._profiles = self._discover_profiles()

    def _check_pil(self) -> bool:
        try:
            import PIL.ImageCms  # noqa: F401
            return True
        except ImportError:
            _log.warning("PIL.ImageCms not available — ICC transforms disabled")
            return False

    def _discover_profiles(self) -> dict[str, str | None]:
        """Scan OS profile directories; always include built-in sRGB."""
        found: dict[str, str | None] = {"sRGB IEC61966-2.1": None}  # None = PIL built-in
        for directory in _PROFILE_DIRS:
            if not os.path.isdir(directory):
                continue
            try:
                for entry in os.scandir(directory):
                    if entry.name.lower().endswith((".icc", ".icm")) and entry.is_file():
                        name = os.path.splitext(entry.name)[0]
                        found.setdefault(name, entry.path)
            except OSError:
                pass
        _log.debug("ICC profiles discovered: %d", len(found))
        return found

    # ── Public API ────────────────────────────────────────────────────────────

    def available_source_profiles(self) -> list[str]:
        return list(ICCService._profiles or {"sRGB IEC61966-2.1": None})

    def available_output_profiles(self) -> list[str]:
        return list(ICCService._profiles or {"sRGB IEC61966-2.1": None})

    def available_rendering_intents(self) -> list[str]:
        return list(_INTENT_MAP)

    def profile_exists(self, name: str | None) -> bool:
        """Return True when *name* refers to a loadable ICC profile."""
        if not name:
            return False
        profiles = ICCService._profiles or {}
        if name in profiles:
            path = profiles[name]
            return path is None or os.path.isfile(path)  # None = built-in
        return os.path.isfile(name)  # allow raw filesystem paths

    def apply_transform(self, image, settings) -> tuple:
        """Apply ICC color transform to a PIL Image.

        Returns ``(image, warning)`` where *warning* is a ``str`` when
        something went wrong and ``None`` on clean success.
        The original *image* is returned unchanged on any failure so the
        caller always gets a displayable result.
        """
        if not self._pil:
            return image, "PIL.ImageCms unavailable — ICC transform skipped."

        if not getattr(settings, "enable_color_management", False):
            return image, None

        src_name    = getattr(settings, "source_profile",    "sRGB IEC61966-2.1")
        out_name    = getattr(settings, "output_profile",    None)
        intent_name = getattr(settings, "rendering_intent",  "Perceptual")
        soft_proof  = getattr(settings, "soft_proof_preview", False)

        if not self.profile_exists(out_name):
            msg = f"ICC output profile '{out_name or '(none)'}' not found — transform skipped."
            _log.warning(msg)
            return image, msg

        try:
            from PIL import ImageCms

            src_p = self._load(src_name)
            out_p = self._load(out_name)
            if src_p is None or out_p is None:
                return image, "Could not load ICC profile(s) — transform skipped."

            intent    = _INTENT_MAP.get(intent_name, 0)
            cache_key = (src_name, out_name, intent, soft_proof)
            transform = self._get_transform(cache_key, src_p, out_p, intent, soft_proof)
            if transform is None:
                return image, "Failed to build ICC transform — skipped."

            # Preserve alpha channel through the transform (ImageCms is RGB-only)
            if image.mode == "RGBA":
                alpha = image.split()[3]
                rgb   = image.convert("RGB")
                out   = ImageCms.applyTransform(rgb, transform)
                out.putalpha(alpha)
            elif image.mode == "RGB":
                out = ImageCms.applyTransform(image, transform)
            else:
                out = ImageCms.applyTransform(image.convert("RGB"), transform)

            return out, None

        except Exception as exc:
            _log.error("ICC apply_transform error: %s", exc, exc_info=True)
            return image, f"ICC error: {exc}"

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load(self, name: str | None):
        """Return an open CmsProfile object, or None on failure."""
        if not name:
            return None
        try:
            from PIL import ImageCms
            profiles = ICCService._profiles or {}
            if name in profiles:
                path = profiles[name]
                if path is None:
                    return ImageCms.createProfile("sRGB")
                return ImageCms.getOpenProfile(path)
            if os.path.isfile(name):
                return ImageCms.getOpenProfile(name)
            return None
        except Exception as exc:
            _log.warning("Failed to load ICC profile '%s': %s", name, exc)
            return None

    def _get_transform(self, key, src_p, out_p, intent: int, soft_proof: bool):
        """Return a cached transform, building it on first use."""
        if key in ICCService._transforms:
            return ICCService._transforms[key]

        try:
            from PIL import ImageCms

            if soft_proof:
                # Soft-proof: source → simulate printer → show on sRGB monitor.
                # Parameter order: inputProfile, outputProfile(display), proofProfile(printer).
                display_p = ImageCms.createProfile("sRGB")
                transform = ImageCms.buildProofTransformFromOpenProfiles(
                    src_p,
                    display_p,
                    out_p,
                    "RGB", "RGB",
                    renderingIntent=intent,
                    proofRenderingIntent=1,   # Relative Colorimetric for proof→display
                    flags=_FLAG_SOFTPROOFING,
                )
            else:
                transform = ImageCms.buildTransformFromOpenProfiles(
                    src_p, out_p, "RGB", "RGB", intent,
                )

            ICCService._transforms[key] = transform
            _log.debug("Built ICC transform key=%s soft_proof=%s", key[:2], soft_proof)
            return transform

        except Exception as exc:
            _log.error("Failed to build ICC transform (key=%s): %s", key, exc, exc_info=True)
            ICCService._transforms[key] = None
            return None
