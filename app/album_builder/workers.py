"""Background worker for album generation — runs AlbumBuilder off the main thread."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

from .builder import AlbumBuilder
from .models import AlbumSettings, AlbumState

if TYPE_CHECKING:
    from app.models.project import ProjectState

logger = logging.getLogger(__name__)


class AlbumBuilderWorker(QThread):
    """Runs all 6 generation stages and emits progress signals.

    Signals
    -------
    stage(label, current, total)  — emitted at each progress tick
    page_ready(page_index)        — emitted after each page layout is built
    album_ready(AlbumState)       — emitted when fully done
    failed(error_message)         — emitted on unrecoverable error
    """

    stage = Signal(str, int, int)        # label, current, total
    page_ready = Signal(int)
    album_ready = Signal(object)         # AlbumState
    failed = Signal(str)

    def __init__(
        self,
        project: 'ProjectState',
        settings: AlbumSettings,
        parent=None,
    ):
        super().__init__(parent)
        self._project = project
        self._settings = settings
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            builder = AlbumBuilder(self._project)
            album = builder.build(self._settings, progress_cb=self._cb)
            if not self._cancelled:
                self.album_ready.emit(album)
        except _Cancelled:
            logger.info('Album generation cancelled by user')
        except Exception as exc:
            logger.exception('Album generation failed: %s', exc)
            self.failed.emit(str(exc))

    def _cb(self, label: str, current: int, total: int) -> None:
        if self._cancelled:
            raise _Cancelled()
        self.stage.emit(label, current, total)


class _Cancelled(Exception):
    pass
