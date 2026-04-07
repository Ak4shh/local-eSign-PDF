from __future__ import annotations
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QPixmap, QTransform,
    QKeyEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsScene, QGraphicsView, QGraphicsSimpleTextItem,
)

from app.models import OverlayItem, OverlayType, PdfRect
from app.image_service import load_preview_pixmap
from app.settings import THEME
from app.tools import PendingPlacement
from app.utils import (
    aspect_fit, color_name_to_qcolor, normalize_rect, fit_font_size,
)

_HANDLE_SIZE = 6.0
_HANDLE_HALF = _HANDLE_SIZE / 2.0
_MIN_RECT = 10.0
_PAGE_GAP = 24.0


def _theme_color(hex_value: str, alpha: int | None = None) -> QColor:
    color = QColor(hex_value)
    if alpha is not None:
        color.setAlpha(alpha)
    return color

_HANDLE_CURSORS = [
    Qt.CursorShape.SizeFDiagCursor,
    Qt.CursorShape.SizeVerCursor,
    Qt.CursorShape.SizeBDiagCursor,
    Qt.CursorShape.SizeHorCursor,
    Qt.CursorShape.SizeFDiagCursor,
    Qt.CursorShape.SizeVerCursor,
    Qt.CursorShape.SizeBDiagCursor,
    Qt.CursorShape.SizeHorCursor,
]

_HANDLE_EDGES = [
    0b0101,
    0b0100,
    0b0110,
    0b0010,
    0b1010,
    0b1000,
    0b1001,
    0b0001,
]


class OverlayGraphicsItem(QGraphicsRectItem):
    SEL_COLOR = _theme_color(THEME.colors.active_fill, alpha=85)
    HANDLE_BORDER_COLOR = _theme_color(THEME.colors.active_border)
    HANDLE_FILL_COLOR = _theme_color(THEME.colors.surface_bg)
    BORDER_COLOR = _theme_color(THEME.colors.active_border)
    IDLE_BORDER_COLOR = _theme_color(THEME.colors.border)

    _IMAGE_CACHE: Dict[str, QPixmap] = {}

    def __init__(
        self,
        overlay: OverlayItem,
        zoom: float,
        model_to_scene_rect: Callable[[OverlayItem], QRectF],
        on_changed: Callable[[OverlayItem, QRectF], QRectF],
        on_resized=None,
        parent: QGraphicsItem | None = None,
    ):
        super().__init__(model_to_scene_rect(overlay), parent)
        self.overlay = overlay
        self._zoom = zoom
        self._model_to_scene_rect = model_to_scene_rect
        self._on_changed = on_changed
        self._on_resized = on_resized
        self._label: Optional[QGraphicsSimpleTextItem] = None
        self._image_item: Optional[QGraphicsPixmapItem] = None

        self._drag_mode: int | str | None = None
        self._drag_start_scene = QPointF()
        self._drag_start_rect = QRectF()

        self._setup()

    def _setup(self) -> None:
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)
        self.setPen(self._idle_pen())
        self._refresh_label()

    def _selected_pen(self) -> QPen:
        pen = QPen(self.BORDER_COLOR, 1.0, Qt.PenStyle.DashLine)
        pen.setDashPattern([3.0, 2.0])
        return pen

    def _idle_pen(self) -> QPen:
        return QPen(self.IDLE_BORDER_COLOR, 0.9, Qt.PenStyle.SolidLine)

    def _hs(self) -> float:
        return _HANDLE_HALF / max(self._zoom, 0.1)

    def _handle_rects(self) -> list[QRectF]:
        r = self.rect()
        hs = self._hs()
        s = hs * 2
        cx = r.x() + r.width() / 2
        cy = r.y() + r.height() / 2
        return [
            QRectF(r.left() - hs, r.top() - hs, s, s),
            QRectF(cx - hs, r.top() - hs, s, s),
            QRectF(r.right() - hs, r.top() - hs, s, s),
            QRectF(r.right() - hs, cy - hs, s, s),
            QRectF(r.right() - hs, r.bottom() - hs, s, s),
            QRectF(cx - hs, r.bottom() - hs, s, s),
            QRectF(r.left() - hs, r.bottom() - hs, s, s),
            QRectF(r.left() - hs, cy - hs, s, s),
        ]

    def _hit_handle(self, pos: QPointF) -> int:
        for i, hr in enumerate(self._handle_rects()):
            if hr.contains(pos):
                return i
        return -1

    def boundingRect(self) -> QRectF:
        hs = self._hs()
        return self.rect().adjusted(-hs, -hs, hs, hs)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self.boundingRect())
        return path

    @staticmethod
    def _screen_dpi_for_item(item: "OverlayGraphicsItem") -> float:
        scene = item.scene()
        if scene:
            views = scene.views()
            if views:
                return max(views[0].logicalDpiY(), 1.0)
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        return max(screen.logicalDotsPerInch(), 1.0) if screen else 96.0

    def _pdf_pt_to_qt_pt(self, pdf_pt: float) -> float:
        return pdf_pt * 72.0 / self._screen_dpi_for_item(self)

    def _refresh_label(self) -> None:
        ov = self.overlay
        r = self.rect()
        text = ov.text or ""

        if ov.type == OverlayType.signature_image:
            self._refresh_image()
            if self._label is not None:
                self._label.setVisible(False)
            return

        if self._image_item is not None:
            self._image_item.setVisible(False)

        if not text:
            if self._label is not None:
                self._label.setVisible(False)
            return

        if self._label is None:
            self._label = QGraphicsSimpleTextItem(self)
            self._label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

        self._label.setVisible(True)
        self._label.setText(text)
        self._label.setBrush(color_name_to_qcolor(ov.color or "black"))

        font = QFont()
        if ov.type == OverlayType.typed_signature and ov.font_name:
            font.setFamily(ov.font_name)

        if ov.font_size and ov.font_size > 0:
            qt_pt = self._pdf_pt_to_qt_pt(ov.font_size)
        else:
            qt_pt = self._pdf_pt_to_qt_pt(
                fit_font_size(text, ov.font_name or "", ov.rect_pdf.width, ov.rect_pdf.height)
            )

        font.setPointSizeF(max(qt_pt, 1.0))
        self._label.setFont(font)

        lb = self._label.boundingRect()
        lx = r.x() + (r.width() - lb.width()) / 2
        ly = r.y() + (r.height() - lb.height()) / 2
        self._label.setPos(lx, ly)

    def _refresh_image(self) -> None:
        path = self.overlay.image_path or ""
        if not path:
            if self._image_item is not None:
                self._image_item.setVisible(False)
            return

        source = self._IMAGE_CACHE.get(path)
        if source is None:
            pixmap, err = load_preview_pixmap(path)
            if err or pixmap is None or pixmap.isNull():
                if self._image_item is not None:
                    self._image_item.setVisible(False)
                return
            source = pixmap
            self._IMAGE_CACHE[path] = source

        if self._image_item is None:
            self._image_item = QGraphicsPixmapItem(self)
            self._image_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._image_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)

        self._image_item.setVisible(True)
        self._image_item.setPixmap(source)

        r = self.rect()
        x, y, w, h = aspect_fit(
            float(source.width()),
            float(source.height()),
            float(r.width()),
            float(r.height()),
        )
        self._image_item.setPos(r.x() + x, r.y() + y)

        sx = (w / max(float(source.width()), 1.0))
        sy = (h / max(float(source.height()), 1.0))
        transform = QTransform()
        transform.scale(sx, sy)
        self._image_item.setTransform(transform)

    def refresh(self) -> None:
        self.prepareGeometryChange()
        self.setRect(self._model_to_scene_rect(self.overlay))
        self.setPen(self._selected_pen() if self.isSelected() else self._idle_pen())
        self._refresh_label()
        self.update()

    def set_zoom(self, zoom: float) -> None:
        self._zoom = zoom
        self.prepareGeometryChange()
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        self.setPen(self._selected_pen() if self.isSelected() else self._idle_pen())
        if self.isSelected():
            painter.fillRect(self.rect(), self.SEL_COLOR)
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.setPen(QPen(self.HANDLE_BORDER_COLOR, 0.9))
            painter.setBrush(self.HANDLE_FILL_COLOR)
            for hr in self._handle_rects():
                painter.drawRect(hr)

    def hoverMoveEvent(self, event) -> None:
        i = self._hit_handle(event.pos())
        self.setCursor(QCursor(_HANDLE_CURSORS[i] if i >= 0 else Qt.CursorShape.SizeAllCursor))

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_scene = event.scenePos()
            self._drag_start_rect = QRectF(self.rect())
            i = self._hit_handle(event.pos())
            if i >= 0:
                self._drag_mode = i
                if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    sc = self.scene()
                    if sc:
                        sc.clearSelection()
                self.setSelected(True)
                event.accept()
                return
            self._drag_mode = "move"
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_mode is None:
            super().mouseMoveEvent(event)
            return

        delta = event.scenePos() - self._drag_start_scene
        r = QRectF(self._drag_start_rect)

        if self._drag_mode == "move":
            r.translate(delta)
        else:
            edges = _HANDLE_EDGES[self._drag_mode]
            if edges & 0b0001:
                r.setLeft(min(r.left() + delta.x(), r.right() - _MIN_RECT))
            if edges & 0b0010:
                r.setRight(max(r.right() + delta.x(), r.left() + _MIN_RECT))
            if edges & 0b0100:
                r.setTop(min(r.top() + delta.y(), r.bottom() - _MIN_RECT))
            if edges & 0b1000:
                r.setBottom(max(r.bottom() + delta.y(), r.top() + _MIN_RECT))

        r = self._on_changed(self.overlay, r)
        self.prepareGeometryChange()
        self.setRect(r)
        self._refresh_label()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        mode = self._drag_mode
        self._drag_mode = None
        super().mouseReleaseEvent(event)
        if mode is not None and mode != "move" and self._on_resized:
            self._on_resized(self.overlay)


class PdfViewer(QGraphicsView):
    overlay_placed = Signal(OverlayItem)
    overlay_deleted = Signal(str)
    overlay_edit_requested = Signal(OverlayItem)
    overlay_resized = Signal(OverlayItem)
    viewport_page_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(_theme_color(THEME.colors.workspace_bg)))

        self._zoom = 1.0
        self._pending: Optional[PendingPlacement] = None
        self._drag_start: Optional[QPointF] = None
        self._drag_start_page: Optional[int] = None
        self._rubber_item: Optional[QGraphicsRectItem] = None
        self._overlay_items: Dict[str, OverlayGraphicsItem] = {}
        self._page_items: Dict[int, QGraphicsPixmapItem] = {}
        self._page_rects_scene: Dict[int, QRectF] = {}
        self._current_viewport_page: int = 0

    def load_document(self, pixmaps: List[QPixmap], overlays: List[OverlayItem], zoom: float) -> None:
        self._scene.clear()
        self._overlay_items.clear()
        self._page_items.clear()
        self._page_rects_scene.clear()
        self._rubber_item = None
        self._drag_start = None
        self._drag_start_page = None
        self._zoom = zoom

        if not pixmaps:
            return

        inv_zoom = 1.0 / zoom
        y = 0.0
        max_w = 0.0

        for i, pixmap in enumerate(pixmaps):
            if pixmap.isNull():
                continue
            item = QGraphicsPixmapItem(pixmap)
            item.setScale(inv_zoom)
            item.setPos(0.0, y)
            item.setZValue(0)
            self._scene.addItem(item)
            self._page_items[i] = item

            pdf_w = pixmap.width() * inv_zoom
            pdf_h = pixmap.height() * inv_zoom
            self._page_rects_scene[i] = QRectF(0.0, y, pdf_w, pdf_h)
            y += pdf_h + _PAGE_GAP
            max_w = max(max_w, pdf_w)

        scene_h = max(y - _PAGE_GAP, 0.0)
        self._scene.setSceneRect(0.0, 0.0, max_w, scene_h)

        for ov in overlays:
            self._add_overlay_item(ov)

        self._apply_zoom(zoom)
        self._emit_viewport_page_changed()

    def set_zoom(self, zoom: float) -> None:
        self._zoom = zoom
        for item in self._overlay_items.values():
            item.set_zoom(zoom)
        self._apply_zoom(zoom)
        self._emit_viewport_page_changed()

    def set_pending(self, pending: Optional[PendingPlacement]) -> None:
        self._pending = pending
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor if pending is not None else Qt.CursorShape.ArrowCursor))

    def refresh_overlay(self, overlay_id: str) -> None:
        item = self._overlay_items.get(overlay_id)
        if item:
            item.refresh()

    def delete_selected(self) -> None:
        for item in list(self._scene.selectedItems()):
            if isinstance(item, OverlayGraphicsItem):
                ov_id = item.overlay.id
                self._scene.removeItem(item)
                self._overlay_items.pop(ov_id, None)
                self.overlay_deleted.emit(ov_id)

    def clear_overlays_for_page(self, page_index: int) -> None:
        remove_ids = [
            ov_id for ov_id, item in self._overlay_items.items()
            if item.overlay.page_index == page_index
        ]
        for ov_id in remove_ids:
            item = self._overlay_items.pop(ov_id)
            self._scene.removeItem(item)

    def current_viewport_page(self) -> int:
        return self._current_viewport_page

    def page_count(self) -> int:
        return len(self._page_rects_scene)

    def scroll_to_page(self, page_index: int) -> None:
        rect = self._page_rects_scene.get(page_index)
        if rect is None:
            return
        self.centerOn(rect.center())
        self._emit_viewport_page_changed()

    def fit_zoom_for_page(self, page_index: int, padding_px: int = 24) -> Optional[float]:
        rect = self._page_rects_scene.get(page_index)
        if rect is None:
            return None
        vp = self.viewport().size()
        avail_w = max(vp.width() - padding_px, 1)
        avail_h = max(vp.height() - padding_px, 1)
        return min(avail_w / max(rect.width(), 1.0), avail_h / max(rect.height(), 1.0))

    def _apply_zoom(self, zoom: float) -> None:
        self.resetTransform()
        self.scale(zoom, zoom)

    def _model_to_scene_rect(self, overlay: OverlayItem) -> QRectF:
        page_rect = self._page_rects_scene.get(overlay.page_index)
        if page_rect is None:
            return QRectF()
        return QRectF(
            page_rect.x() + overlay.rect_pdf.x,
            page_rect.y() + overlay.rect_pdf.y,
            overlay.rect_pdf.width,
            overlay.rect_pdf.height,
        )

    def _clamp_scene_rect_to_page(self, scene_rect: QRectF, page_index: int) -> QRectF:
        page_rect = self._page_rects_scene.get(page_index)
        if page_rect is None:
            return scene_rect

        w = min(max(scene_rect.width(), _MIN_RECT), page_rect.width())
        h = min(max(scene_rect.height(), _MIN_RECT), page_rect.height())

        x = scene_rect.x()
        y = scene_rect.y()
        x = max(page_rect.left(), min(x, page_rect.right() - w))
        y = max(page_rect.top(), min(y, page_rect.bottom() - h))
        return QRectF(x, y, w, h)

    def _scene_rect_to_model(self, overlay: OverlayItem, scene_rect: QRectF) -> QRectF:
        page_index = overlay.page_index
        clamped = self._clamp_scene_rect_to_page(scene_rect, page_index)
        page_rect = self._page_rects_scene.get(page_index)
        if page_rect is None:
            return clamped

        overlay.rect_pdf = PdfRect(
            clamped.x() - page_rect.x(),
            clamped.y() - page_rect.y(),
            clamped.width(),
            clamped.height(),
        )
        return clamped

    def _add_overlay_item(self, overlay: OverlayItem) -> Optional[OverlayGraphicsItem]:
        if overlay.page_index not in self._page_rects_scene:
            return None
        item = OverlayGraphicsItem(
            overlay,
            zoom=self._zoom,
            model_to_scene_rect=self._model_to_scene_rect,
            on_changed=self._scene_rect_to_model,
            on_resized=lambda ov: self.overlay_resized.emit(ov),
        )
        item.setZValue(1)
        self._scene.addItem(item)
        self._overlay_items[overlay.id] = item
        return item

    def _page_at_scene_pos(self, pos: QPointF) -> Optional[int]:
        for page_index, rect in self._page_rects_scene.items():
            if rect.contains(pos):
                return page_index
        return None

    def _emit_viewport_page_changed(self) -> None:
        if not self._page_rects_scene:
            self._current_viewport_page = 0
            self.viewport_page_changed.emit(0)
            return

        center_scene = self.mapToScene(self.viewport().rect().center())
        page_index = self._page_at_scene_pos(center_scene)
        if page_index is None:
            nearest = min(
                self._page_rects_scene.items(),
                key=lambda p: abs(p[1].center().y() - center_scene.y()),
            )
            page_index = nearest[0]

        if page_index != self._current_viewport_page:
            self._current_viewport_page = page_index
            self.viewport_page_changed.emit(page_index)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self._emit_viewport_page_changed()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._emit_viewport_page_changed()

    def mousePressEvent(self, event) -> None:
        if self._pending is not None and event.button() == Qt.MouseButton.LeftButton:
            start = self.mapToScene(event.position().toPoint())
            page_index = self._page_at_scene_pos(start)
            if page_index is None:
                return
            self._drag_start = start
            self._drag_start_page = page_index
            pen = QPen(_theme_color(THEME.colors.active_border), 1.0, Qt.PenStyle.DashLine)
            pen.setDashPattern([3.0, 2.0])
            brush = QBrush(_theme_color(THEME.colors.active_fill, alpha=52))
            self._rubber_item = self._scene.addRect(QRectF(start, start), pen, brush)
            self._rubber_item.setZValue(10)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pending is not None and self._drag_start is not None and self._drag_start_page is not None:
            current = self.mapToScene(event.position().toPoint())
            r = QRectF(self._drag_start, current).normalized()
            r = self._clamp_scene_rect_to_page(r, self._drag_start_page)
            if self._rubber_item:
                self._rubber_item.setRect(r)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pending is not None and self._drag_start is not None and self._drag_start_page is not None:
            end = self.mapToScene(event.position().toPoint())
            raw = normalize_rect(self._drag_start.x(), self._drag_start.y(), end.x(), end.y())
            rect = self._clamp_scene_rect_to_page(
                QRectF(raw.x, raw.y, raw.width, raw.height),
                self._drag_start_page,
            )

            if self._rubber_item:
                self._scene.removeItem(self._rubber_item)
                self._rubber_item = None

            start_page = self._drag_start_page
            self._drag_start = None
            self._drag_start_page = None

            if rect.width() < 4 or rect.height() < 4:
                return

            pending = self._pending
            self._pending = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

            page_rect = self._page_rects_scene[start_page]
            overlay = OverlayItem(
                page_index=start_page,
                type=pending.overlay_type,
                rect_pdf=PdfRect(
                    rect.x() - page_rect.x(),
                    rect.y() - page_rect.y(),
                    rect.width(),
                    rect.height(),
                ),
                text=pending.text,
                font_name=pending.font_name,
                color=pending.color,
                image_path=pending.image_path,
            )
            self._add_overlay_item(overlay)
            self.overlay_placed.emit(overlay)
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._pending is not None:
            super().mouseDoubleClickEvent(event)
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        for item in self._scene.items(scene_pos):
            if isinstance(item, OverlayGraphicsItem):
                self.overlay_edit_requested.emit(item.overlay)
                event.accept()
                return
            parent = item.parentItem() if isinstance(item, QGraphicsItem) else None
            if isinstance(parent, OverlayGraphicsItem):
                self.overlay_edit_requested.emit(parent.overlay)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
            return
        if event.key() == Qt.Key.Key_Escape:
            if self._pending is not None:
                if self._rubber_item:
                    self._scene.removeItem(self._rubber_item)
                    self._rubber_item = None
                self._drag_start = None
                self._drag_start_page = None
                self._pending = None
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            return
        super().keyPressEvent(event)
