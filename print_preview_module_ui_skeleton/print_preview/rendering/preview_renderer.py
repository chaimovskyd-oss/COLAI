from PySide6.QtGui import QImage, QPixmap

import logging

_log = logging.getLogger(__name__)


class PreviewRenderer:
    """Render a page via the adapter and return a QPixmap for display."""

    def __init__(self, adapter):
        self.adapter = adapter
        self._cache_key = None
        self._cached_pixmap: QPixmap | None = None
        self._icc = None
        self._last_raw_pil = None

    def render(self, page, metrics, settings=None) -> QPixmap | None:
        if page is None:
            return None

        cache_key = self._make_cache_key(page, metrics, settings)
        if cache_key == self._cache_key and self._cached_pixmap is not None:
            return self._cached_pixmap

        try:
            result = self.adapter.render_preview_page(page, metrics.scale, settings=settings)
        except Exception as exc:
            _log.warning("render_preview_page raised: %s", exc, exc_info=True)
            return None

        if result is None:
            _log.debug("render_preview_page returned None for page %s", getattr(page, "page_id", "?"))
            return None

        self._last_raw_pil = result

        # Print Color Preset is already applied inside the item render pipeline.
        if settings is not None and getattr(settings, "enable_color_management", False):
            icc = self._get_icc()
            result, warning = icc.apply_transform(result, settings)
            if warning:
                _log.warning("ICC preview: %s", warning)

        pixmap = self._to_pixmap(result)
        if pixmap and not pixmap.isNull():
            self._cache_key = cache_key
            self._cached_pixmap = pixmap
            return pixmap

        _log.warning("_to_pixmap produced null/empty pixmap for page %s", getattr(page, "page_id", "?"))
        return None

    def invalidate_cache(self):
        self._cache_key = None
        self._cached_pixmap = None

    def get_raw_pil(self):
        return self._last_raw_pil

    def _get_icc(self):
        if self._icc is None:
            from print_preview.services.icc_service import ICCService

            self._icc = ICCService()
        return self._icc

    def _make_cache_key(self, page, metrics, settings) -> tuple:
        base = (id(page), round(metrics.scale, 4))

        preset_key: tuple = ()
        if settings is not None and getattr(settings, "print_color_preset_enabled", False):
            pv = getattr(settings, "print_color_preset_values", {})
            if pv:
                try:
                    preset_key = (True, tuple(sorted(pv.items())))
                except TypeError:
                    preset_key = (True, id(pv))

        icc_key: tuple = ()
        if settings is not None and getattr(settings, "enable_color_management", False):
            icc_key = (
                getattr(settings, "source_profile", None),
                getattr(settings, "output_profile", None),
                getattr(settings, "rendering_intent", None),
                getattr(settings, "soft_proof_preview", False),
            )

        return base + preset_key + icc_key

    def _to_pixmap(self, result) -> QPixmap | None:
        if isinstance(result, QPixmap):
            return result

        try:
            from PIL.ImageQt import ImageQt

            if result.mode not in ("RGB", "RGBA"):
                result = result.convert("RGB")
            return QPixmap.fromImage(ImageQt(result))
        except Exception as exc:
            _log.warning("PIL.ImageQt conversion failed: %s; falling back to raw bytes", exc)

        try:
            img = result.convert("RGBA")
            data = bytes(img.tobytes("raw", "RGBA"))
            qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
            if qimg.isNull():
                _log.warning("QImage.isNull() after raw-bytes construction")
                return None
            return QPixmap.fromImage(qimg)
        except Exception as exc:
            _log.warning("Raw-bytes QImage conversion failed: %s", exc)
            return None
