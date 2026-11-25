from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..frame import Frame
from ..geometry import Rect
from .geometry import CanvasFit, canonical_rect, fit_image, image_to_widget, zoomed_fit


@dataclass
class Overlay:
    rect: Rect
    label: str = ""
    color: tuple[int, int, int] = (0, 220, 120)
    dashed: bool = False
    width: int = 2


def numpy_to_qimage(image: np.ndarray) -> QImage:
    if image.ndim == 2:
        gray = np.ascontiguousarray(image)
        height, width = gray.shape[:2]
        return QImage(
            gray.data, width, height, width, QImage.Format.Format_Grayscale8
        ).copy()
    rgb = np.ascontiguousarray(image[:, :, ::-1])
    height, width = rgb.shape[:2]
    return QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()


class ImageCanvas(QWidget):
    selectionChanged = Signal(object)
    hoverChanged = Signal(object)
    clicked = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._frame: Frame | None = None
        self._qimage: QImage | None = None
        self._overlays: list[Overlay] = []
        self._rois: list[Overlay] = []
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._drag_start: QPointF | None = None
        self._drag_current: QPointF | None = None
        self._selection: Rect | None = None
        self.selectable = True

    def set_frame(self, frame: Frame | None) -> None:
        self._frame = frame
        self._qimage = numpy_to_qimage(frame.image) if frame is not None else None
        self._selection = None
        self.update()

    @property
    def frame(self) -> Frame | None:
        return self._frame

    def set_overlays(self, overlays: list[Overlay]) -> None:
        self._overlays = list(overlays)
        self.update()

    def set_rois(self, rois: list[Overlay]) -> None:
        self._rois = list(rois)
        self.update()

    def set_selection(self, rect: Rect | None) -> None:
        self._selection = rect
        self.update()

    @property
    def selection(self) -> Rect | None:
        return self._selection

    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float) -> None:
        self._zoom = max(0.2, min(float(zoom), 12.0))
        self.update()

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()

    def fit(self) -> CanvasFit | None:
        if self._frame is None:
            return None
        base = fit_image(
            self._frame.width, self._frame.height, self.width(), self.height()
        )
        return zoomed_fit(base, self._zoom, self._pan.x(), self._pan.y())

    def selected_image(self) -> np.ndarray | None:
        if self._frame is None or self._selection is None:
            return None
        return self._frame.crop(self._selection).copy()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(24, 26, 30))
        fit = self.fit()
        if fit is None or self._qimage is None:
            painter.setPen(QColor(150, 155, 165))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "没有可显示的帧",
            )
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        target = QRectF(
            fit.offset_x, fit.offset_y, fit.drawn_width, fit.drawn_height
        )
        painter.drawImage(target, self._qimage)
        for overlay in self._rois:
            self._draw_overlay(painter, fit, overlay)
        for overlay in self._overlays:
            self._draw_overlay(painter, fit, overlay)
        if self._drag_start is not None and self._drag_current is not None:
            rect = QRect(
                self._drag_start.toPoint(), self._drag_current.toPoint()
            ).normalized()
            pen = QPen(QColor(255, 210, 80), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(rect)
        elif self._selection is not None:
            x, y = image_to_widget(fit, self._selection.x, self._selection.y)
            width = self._selection.width * fit.scale
            height = self._selection.height * fit.scale
            pen = QPen(QColor(255, 210, 80), 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawRect(QRectF(x, y, width, height))

    def _draw_overlay(self, painter: QPainter, fit: CanvasFit, overlay: Overlay) -> None:
        rect = overlay.rect
        x, y = image_to_widget(fit, rect.x, rect.y)
        width = max(1.0, rect.width * fit.scale)
        height = max(1.0, rect.height * fit.scale)
        style = Qt.PenStyle.DashLine if overlay.dashed else Qt.PenStyle.SolidLine
        painter.setPen(QPen(QColor(*overlay.color), overlay.width, style))
        if rect.width <= 1 and rect.height <= 1:
            painter.drawLine(QPointF(x - 8, y), QPointF(x + 8, y))
            painter.drawLine(QPointF(x, y - 8), QPointF(x, y + 8))
            painter.drawEllipse(QPointF(x, y), 6, 6)
        else:
            painter.drawRect(QRectF(x, y, width, height))
        if overlay.label:
            painter.setPen(QColor(*overlay.color))
            label_y = y - 4 if y > 16 else y + height + 14
            painter.drawText(QPointF(x, label_y), overlay.label)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        self.set_zoom(self._zoom * factor)

    def _canonical(self, point: QPointF) -> tuple[int, int] | None:
        fit = self.fit()
        if fit is None or self._frame is None:
            return None
        if not fit.contains(point.x(), point.y()):
            return None
        from .geometry import canonical_point

        return canonical_point(
            fit, point.x(), point.y(), (self._frame.width, self._frame.height)
        )

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._frame is None:
            return
        point = event.position()
        canonical = self._canonical(point)
        if canonical is None:
            return
        self.clicked.emit(canonical[0], canonical[1])
        if not self.selectable:
            return
        self._drag_start = point
        self._drag_current = point
        self._selection = None
        self.selectionChanged.emit(None)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        point = event.position()
        canonical = self._canonical(point)
        self.hoverChanged.emit(canonical)
        if self._drag_start is not None:
            self._drag_current = point
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_start is None or self._frame is None:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag_current = event.position()
        fit = self.fit()
        start = self._drag_start
        current = self._drag_current
        self._drag_start = None
        self._drag_current = None
        if fit is None:
            self.update()
            return
        rect = canonical_rect(
            fit,
            start.x(),
            start.y(),
            current.x(),
            current.y(),
            (self._frame.width, self._frame.height),
        )
        if rect is None or rect.width < 4 or rect.height < 4:
            self._selection = None
            self.selectionChanged.emit(None)
            self.update()
            return
        self._selection = rect
        self.selectionChanged.emit(rect)
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._selection = None
            self.selectionChanged.emit(None)
            self.update()
            return
        if event.key() == Qt.Key.Key_0:
            self.reset_view()
            return
        super().keyPressEvent(event)
