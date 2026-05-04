from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout
from PIL.ImageQt import ImageQt


class PreviewCanvas(QFrame):
    image_clicked = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.setObjectName("PreviewFrame")
        self.label = QLabel("Open an image to start")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumSize(640, 440)
        self.label.setStyleSheet("color: #aaa6c9; font-size: 18px;")
        self.overlay_label = QLabel("")
        self.overlay_label.setObjectName("PreviewOverlayLabel")
        self.overlay_label.setAlignment(Qt.AlignCenter)
        self.overlay_label.setVisible(False)
        self.current_image = None
        self.original_image = None
        self.overlay_image = None
        self.before_after_mode = "edited"
        self.zoom = 1.0
        layout = QVBoxLayout(self)
        layout.addWidget(self.overlay_label)
        layout.addWidget(self.label)
        self.label.mousePressEvent = self._label_mouse_press

    def set_image(self, pil_image, original_image=None):
        self.current_image = pil_image
        self.overlay_image = None
        self.overlay_label.clear()
        self.overlay_label.setVisible(False)
        if original_image is not None:
            self.original_image = original_image
        self._render()

    def set_overlay_image(self, pil_image, label: str | None = None) -> None:
        self.overlay_image = pil_image
        if label:
            self.overlay_label.setText(label)
            self.overlay_label.setVisible(True)
        self._render()

    def clear_overlay(self) -> None:
        if self.overlay_image is not None:
            self.overlay_image = None
            self.overlay_label.clear()
            self.overlay_label.setVisible(False)
            self._render()

    def set_before_after_mode(self, mode: str) -> None:
        self.before_after_mode = mode
        self._render()

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.1, min(4.0, zoom))
        self._render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self.set_zoom(self.zoom + (0.1 if delta > 0 else -0.1))

    def _label_mouse_press(self, event):
        if self.current_image is None or self.label.pixmap() is None:
            return
        pixmap = self.label.pixmap()
        label_size = self.label.size()
        pixmap_size = pixmap.size()
        offset_x = max(0, (label_size.width() - pixmap_size.width()) // 2)
        offset_y = max(0, (label_size.height() - pixmap_size.height()) // 2)
        x = event.position().x() - offset_x
        y = event.position().y() - offset_y
        if x < 0 or y < 0 or x > pixmap_size.width() or y > pixmap_size.height():
            return
        image_x = int(x / max(1, pixmap_size.width()) * self.current_image.width)
        image_y = int(y / max(1, pixmap_size.height()) * self.current_image.height)
        self.image_clicked.emit(image_x, image_y)

    def _render(self):
        if self.current_image is None:
            return
        image = self.overlay_image if self.overlay_image is not None else self._compose_mode()
        qimage = QImage(ImageQt(image))
        pixmap = QPixmap.fromImage(qimage)
        target_size = self.label.size() * self.zoom
        self.label.setPixmap(pixmap.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _compose_mode(self):
        if self.before_after_mode == "before" and self.original_image is not None:
            return self.original_image
        if self.before_after_mode == "side_by_side" and self.original_image is not None:
            width = min(self.original_image.width, self.current_image.width)
            height = min(self.original_image.height, self.current_image.height)
            left = self.original_image.resize((width, height))
            right = self.current_image.resize((width, height))
            canvas = left.copy()
            canvas = canvas.resize((width * 2, height))
            canvas.paste(left, (0, 0))
            canvas.paste(right, (width, 0))
            return canvas
        if self.before_after_mode == "split" and self.original_image is not None:
            width = min(self.original_image.width, self.current_image.width)
            height = min(self.original_image.height, self.current_image.height)
            before = self.original_image.resize((width, height))
            after = self.current_image.resize((width, height))
            split = width // 2
            canvas = after.copy()
            canvas.paste(before.crop((0, 0, split, height)), (0, 0))
            return canvas
        return self.current_image
