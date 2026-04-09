from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.image_service import load_preview_pixmap
from app.models import SignaturePreset, SignaturePresetType
from app.settings import THEME
from app.utils import color_name_to_qcolor


class SignaturePresetRow(QWidget):
    def __init__(self, preset: SignaturePreset, parent=None) -> None:
        super().__init__(parent)
        self._preset = preset
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(THEME.spacing.field_gap)

        preview = QLabel()
        preview.setFixedSize(92, 42)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setFrameShape(QFrame.Shape.StyledPanel)
        layout.addWidget(preview)

        details = QVBoxLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(2)
        layout.addLayout(details, stretch=1)

        name_label = QLabel(self._preset.name)
        name_label.setProperty("role", "fieldLabel")
        details.addWidget(name_label)

        detail_label = QLabel()
        detail_label.setProperty("role", "helper")
        detail_label.setWordWrap(True)
        details.addWidget(detail_label)

        if self._preset.preset_type == SignaturePresetType.typed:
            preview.setText(self._preset.text or "Signature")
            font = QFont(self._preset.font_name or THEME.typography.family)
            font.setPointSize(12)
            preview.setFont(font)
            palette = preview.palette()
            palette.setColor(preview.foregroundRole(), color_name_to_qcolor(self._preset.color or "black"))
            preview.setPalette(palette)
            detail_label.setText(self._preset.font_name or "Typed signature")
            return

        pixmap = None
        if self._preset.resolved_image_path:
            pixmap, _ = load_preview_pixmap(self._preset.resolved_image_path)
        if pixmap is not None and not pixmap.isNull():
            preview.setPixmap(
                pixmap.scaled(
                    preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            detail_label.setText("Saved image signature")
        else:
            preview.setText("Missing")
            detail_label.setText(self._preset.load_error or "Preview unavailable")


class SignaturePresetsPanel(QFrame):
    save_requested = Signal()
    use_requested = Signal(str)
    rename_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._presets: list[SignaturePreset] = []
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("panelCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(THEME.spacing.field_gap)

        title = QLabel("Presets")
        title.setProperty("role", "subTitle")
        layout.addWidget(title)

        self._helper = QLabel("Save a signature once, then reuse it here.")
        self._helper.setProperty("role", "helper")
        self._helper.setWordWrap(True)
        layout.addWidget(self._helper)

        self._empty = QLabel("No saved presets yet.")
        self._empty.setProperty("role", "helper")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setMinimumHeight(68)
        layout.addWidget(self._empty)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.itemDoubleClicked.connect(lambda _item: self._emit_use_selected())
        self._list.itemSelectionChanged.connect(self._refresh_actions)
        layout.addWidget(self._list)

        buttons_row = QHBoxLayout()
        buttons_row.setContentsMargins(0, 0, 0, 0)
        buttons_row.setSpacing(THEME.spacing.compact_gap)
        layout.addLayout(buttons_row)

        self._btn_save = QPushButton("Save as Preset")
        self._btn_save.setProperty("role", "quiet")
        self._btn_save.clicked.connect(self.save_requested.emit)
        buttons_row.addWidget(self._btn_save)

        self._btn_use = QPushButton("Use Selected")
        self._btn_use.setProperty("role", "primary")
        self._btn_use.clicked.connect(self._emit_use_selected)
        buttons_row.addWidget(self._btn_use)

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(THEME.spacing.compact_gap)
        layout.addLayout(actions_row)

        self._btn_rename = QPushButton("Rename")
        self._btn_rename.setProperty("role", "quiet")
        self._btn_rename.clicked.connect(self._emit_rename_selected)
        actions_row.addWidget(self._btn_rename)

        self._btn_delete = QPushButton("Delete")
        self._btn_delete.setProperty("role", "danger")
        self._btn_delete.clicked.connect(self._emit_delete_selected)
        actions_row.addWidget(self._btn_delete)

        self._refresh_visibility()
        self._refresh_actions()

    def set_presets(self, presets: list[SignaturePreset], *, label: str = "signatures") -> None:
        self._presets = list(presets)
        self._helper.setText(f"Saved {label} appear here for quick reuse.")
        self._refresh_items()

    def set_save_enabled(self, enabled: bool) -> None:
        self._btn_save.setEnabled(enabled)

    def selected_preset_id(self) -> str | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _refresh_items(self) -> None:
        current_id = self.selected_preset_id()
        self._list.clear()
        selected_row = -1
        for row, preset in enumerate(self._presets):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, preset.id)
            widget = SignaturePresetRow(preset, self._list)
            item.setSizeHint(widget.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, widget)
            if preset.id == current_id:
                selected_row = row
        if selected_row >= 0:
            self._list.setCurrentRow(selected_row)
        self._refresh_visibility()
        self._refresh_actions()

    def _refresh_visibility(self) -> None:
        has_items = self._list.count() > 0
        self._list.setVisible(has_items)
        self._empty.setVisible(not has_items)

    def _refresh_actions(self) -> None:
        preset_id = self.selected_preset_id()
        preset = next((p for p in self._presets if p.id == preset_id), None)
        self._btn_use.setEnabled(bool(preset and preset.is_available))
        self._btn_rename.setEnabled(preset is not None)
        self._btn_delete.setEnabled(preset is not None)

    def _emit_use_selected(self) -> None:
        preset_id = self.selected_preset_id()
        if preset_id:
            self.use_requested.emit(preset_id)

    def _emit_rename_selected(self) -> None:
        preset_id = self.selected_preset_id()
        if preset_id:
            self.rename_requested.emit(preset_id)

    def _emit_delete_selected(self) -> None:
        preset_id = self.selected_preset_id()
        if preset_id:
            self.delete_requested.emit(preset_id)
