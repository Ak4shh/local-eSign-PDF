from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QComboBox


class StableComboBox(QComboBox):
    """QComboBox with reliable single-click popup selection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.view().viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.view().viewport() and event.type() == QEvent.Type.MouseButtonPress:
            idx = self.view().indexAt(event.pos())
            if idx.isValid():
                self.setCurrentIndex(idx.row())
                self.activated.emit(idx.row())
                self.hidePopup()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)
