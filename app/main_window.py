from __future__ import annotations

import copy
import os
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QUndoCommand,
    QUndoStack,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.image_service import validate_image_path
from app.models import OverlayItem, OverlayType, PdfRect
from app.paths import resource_path
from app.persistence import AppPersistence, ZOOM_MODE_CUSTOM, ZOOM_MODE_FIT
from app.pdf_viewer import PdfViewer
from app.settings import (
    APP_NAME,
    DEFAULT_DATE_FORMAT,
    SIGNATURE_FONTS,
    SUPPORTED_COLORS,
    THEME,
    ZOOM_DEFAULT,
    ZOOM_MAX,
    ZOOM_MIN,
    ZOOM_STEP,
)
from app.theme import build_palette, build_stylesheet
from app.tools import (
    PendingPlacement,
    validate_date,
    validate_name,
    validate_signature_image,
    validate_typed_signature,
)
from app.widgets import StableComboBox


class OverlayStateCommand(QUndoCommand):
    def __init__(
        self,
        window: "MainWindow",
        text: str,
        before_overlays: list[OverlayItem],
        before_selection: list[str],
        after_overlays: list[OverlayItem],
        after_selection: list[str],
        redo_status: str = "",
        undo_status: str = "",
    ) -> None:
        super().__init__(text)
        self._window = window
        self._before_overlays = copy.deepcopy(before_overlays)
        self._before_selection = list(before_selection)
        self._after_overlays = copy.deepcopy(after_overlays)
        self._after_selection = list(after_selection)
        self._redo_status = redo_status
        self._undo_status = undo_status

    def undo(self) -> None:
        self._window._apply_overlays_state(
            self._before_overlays,
            self._before_selection,
            status_msg=self._undo_status,
        )

    def redo(self) -> None:
        self._window._apply_overlays_state(
            self._after_overlays,
            self._after_selection,
            status_msg=self._redo_status,
        )


class MainWindow(QMainWindow):
    def __init__(self, fonts_dir: str) -> None:
        super().__init__()
        self._fonts_dir = fonts_dir
        self._pdf_service = None   # created lazily on first PDF action
        self._persistence = AppPersistence()
        self._undo_stack = QUndoStack(self)
        self._overlays: List[OverlayItem] = []
        self._current_page: int = 0
        self._zoom: float = ZOOM_DEFAULT
        self._zoom_mode: str = ZOOM_MODE_FIT
        self._image_path: Optional[str] = None
        self._current_mode: int = 0
        self._copied_overlay: Optional[OverlayItem] = None
        self._paste_count: int = 0
        self._selected_overlay_ids: list[str] = []

        self.setObjectName("mainWindow")
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 820)

        self._apply_theme()
        self._build_ui()
        self._restore_persisted_inputs()
        self._persistence.restore_window_geometry(self)
        self._update_controls()

    @property
    def _pdf(self):
        """Lazily create PdfService on first PDF-related action.

        Deferring construction keeps the window boot path free of the
        fitz/PyMuPDF import cost (~37 MB DLL, visible on cold starts).
        """
        if self._pdf_service is None:
            from app.pdf_service import PdfService
            self._pdf_service = PdfService(self._fonts_dir)
        return self._pdf_service

    def _svg_icon(self, filename: str) -> QIcon:
        svg_path = resource_path("SVGs", filename)
        return QIcon(svg_path) if os.path.isfile(svg_path) else QIcon()

    @staticmethod
    def _apply_button_icon(button: QPushButton, icon: QIcon, size: int = 14) -> None:
        if icon.isNull():
            return
        button.setIcon(icon)
        button.setIconSize(QSize(size, size))

    def _svg_icon_tinted(self, filename: str, color: str, size: int = 14) -> QIcon:
        base = self._svg_icon(filename)
        if base.isNull():
            return base
        source = base.pixmap(size, size)
        if source.isNull():
            return base
        tinted = QPixmap(source.size())
        tinted.fill(Qt.GlobalColor.transparent)
        painter = QPainter(tinted)
        painter.drawPixmap(0, 0, source)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), QColor(color))
        painter.end()
        return QIcon(tinted)

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        app.setStyle("Fusion")
        app.setPalette(build_palette(THEME))
        app.setStyleSheet(build_stylesheet(THEME))

    def _build_ui(self) -> None:
        self._create_actions()
        self._build_menu_bar()
        self._build_toolbar()

        central = QWidget()
        central.setObjectName("centralShell")
        self.setCentralWidget(central)

        layout = QHBoxLayout(central)
        layout.setContentsMargins(
            THEME.spacing.outer,
            THEME.spacing.outer,
            THEME.spacing.outer,
            THEME.spacing.outer,
        )
        layout.setSpacing(THEME.spacing.section_gap)

        layout.addWidget(self._build_left_panel(), 0)

        self._viewer = PdfViewer()
        self._viewer.setObjectName("pdfViewer")
        self._viewer.overlay_placement_requested.connect(self._on_overlay_placement_requested)
        self._viewer.delete_requested.connect(self._on_delete_requested)
        self._viewer.overlay_edit_requested.connect(self._on_overlay_edit_requested)
        self._viewer.overlay_geometry_change_committed.connect(
            self._on_overlay_geometry_change_committed
        )
        self._viewer.selection_changed.connect(self._on_viewer_selection_changed)
        self._viewer.viewport_page_changed.connect(self._on_viewport_page_changed)
        layout.addWidget(self._viewer, stretch=1)

        layout.addWidget(self._build_right_panel(), 0)
        self._build_statusbar()

    def _create_actions(self) -> None:
        self._act_open = QAction("Open PDF", self)
        self._act_open.setIcon(self._svg_icon("open.svg"))
        self._act_open.setShortcuts(QKeySequence.keyBindings(QKeySequence.StandardKey.Open))
        self._act_open.triggered.connect(self._open_pdf)

        self._act_save = QAction("Save As", self)
        self._act_save.setShortcuts(QKeySequence.keyBindings(QKeySequence.StandardKey.Save))
        self._act_save.triggered.connect(self._save_pdf)

        self._act_undo = self._undo_stack.createUndoAction(self, "Undo")
        self._act_undo.setShortcuts(QKeySequence.keyBindings(QKeySequence.StandardKey.Undo))

        self._act_redo = self._undo_stack.createRedoAction(self, "Redo")
        redo_shortcuts = QKeySequence.keyBindings(QKeySequence.StandardKey.Redo)
        redo_shortcuts.append(QKeySequence("Ctrl+Y"))
        redo_shortcuts.append(QKeySequence("Ctrl+Shift+Z"))
        self._act_redo.setShortcuts(redo_shortcuts)

        self._act_copy = QAction("Copy Overlay", self)
        self._act_copy.setShortcuts(QKeySequence.keyBindings(QKeySequence.StandardKey.Copy))
        self._act_copy.triggered.connect(self._copy_selected_overlay)

        self._act_paste = QAction("Paste Overlay", self)
        self._act_paste.setShortcuts(QKeySequence.keyBindings(QKeySequence.StandardKey.Paste))
        self._act_paste.triggered.connect(self._paste_overlay)

        self._act_delete = QAction("Delete Selected", self)
        self._act_delete.setShortcuts([QKeySequence(Qt.Key.Key_Delete), QKeySequence(Qt.Key.Key_Backspace)])
        self._act_delete.triggered.connect(self._delete_selected)

        self._act_clear_page = QAction("Clear Current Page Overlays", self)
        self._act_clear_page.triggered.connect(self._clear_overlays)

        self._act_zoom_out = QAction("Zoom -", self)
        self._act_zoom_out.triggered.connect(self._zoom_out)

        self._act_zoom_in = QAction("Zoom +", self)
        self._act_zoom_in.triggered.connect(self._zoom_in)

        self._act_zoom_reset = QAction("Reset", self)
        self._act_zoom_reset.setIcon(self._svg_icon("reset.svg"))
        self._act_zoom_reset.triggered.connect(self._zoom_reset)

        self._act_fit_page = QAction("Fit Page", self)
        self._act_fit_page.setIcon(self._svg_icon("fitpage.svg"))
        self._act_fit_page.triggered.connect(self._fit_page)

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self._act_open)
        self._menu_recent = file_menu.addMenu("Open Recent")
        self._menu_recent.aboutToShow.connect(self._rebuild_recent_menu)
        file_menu.addAction(self._act_save)

        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addAction(self._act_undo)
        edit_menu.addAction(self._act_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self._act_copy)
        edit_menu.addAction(self._act_paste)
        edit_menu.addAction(self._act_delete)
        edit_menu.addSeparator()
        edit_menu.addAction(self._act_clear_page)

        self._rebuild_recent_menu()

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setObjectName("mainToolbar")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setIconSize(QSize(16, 16))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        tb.addAction(self._act_open)

        tb.addAction(self._act_save)
        tb.addAction(self._act_undo)
        tb.addAction(self._act_redo)

        tb.addWidget(self._toolbar_gap(14))

        self._lbl_page = QLabel("Page 0 / 0")
        self._lbl_page.setObjectName("toolbarPageLabel")
        self._lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_page.setMinimumWidth(120)
        tb.addWidget(self._lbl_page)

        tb.addWidget(self._toolbar_gap(8))

        tb.addAction(self._act_zoom_out)

        self._lbl_zoom = QLabel("100%")
        self._lbl_zoom.setObjectName("toolbarZoomLabel")
        self._lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_zoom.setMinimumWidth(64)
        tb.addWidget(self._lbl_zoom)

        tb.addAction(self._act_zoom_in)

        tb.addAction(self._act_zoom_reset)

        tb.addAction(self._act_fit_page)

    @staticmethod
    def _toolbar_gap(width: int) -> QWidget:
        spacer = QWidget()
        spacer.setFixedWidth(width)
        return spacer

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("leftPanel")
        panel.setFixedWidth(THEME.sizes.left_panel_width)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(
            THEME.spacing.panel_padding,
            THEME.spacing.panel_padding,
            THEME.spacing.panel_padding,
            THEME.spacing.panel_padding,
        )
        layout.setSpacing(THEME.spacing.section_gap)

        title = QLabel("Overlay Tools")
        title.setProperty("role", "sectionTitle")
        layout.addWidget(title)

        tools_card = QFrame()
        tools_card.setObjectName("panelCard")
        tools_layout = QVBoxLayout(tools_card)
        tools_layout.setContentsMargins(8, 8, 8, 8)
        tools_layout.setSpacing(THEME.spacing.field_gap)

        lbl_mode = QLabel("Select tool")
        lbl_mode.setProperty("role", "subTitle")
        tools_layout.addWidget(lbl_mode)

        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_group.idClicked.connect(self._on_mode_changed)
        self._tool_buttons: list[QPushButton] = []

        for idx, label in enumerate(("Typed Signature", "Signature Image", "Name", "Date")):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("role", "tool")
            btn.setMinimumHeight(THEME.sizes.control_height)
            self._tool_group.addButton(btn, idx)
            self._tool_buttons.append(btn)
            tools_layout.addWidget(btn)

        self._tool_buttons[0].setChecked(True)
        layout.addWidget(tools_card)

        context_card = QFrame()
        context_card.setObjectName("contextCard")
        context_layout = QVBoxLayout(context_card)
        context_layout.setContentsMargins(8, 8, 8, 8)
        context_layout.setSpacing(THEME.spacing.field_gap)

        ctx_title = QLabel("Tool Settings")
        ctx_title.setProperty("role", "subTitle")
        context_layout.addWidget(ctx_title)

        self._grp_typed = QWidget()
        gl = QVBoxLayout(self._grp_typed)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(THEME.spacing.field_gap)

        sig_label = QLabel("Signature text")
        sig_label.setProperty("role", "fieldLabel")
        gl.addWidget(sig_label)

        self._sig_text = QLineEdit()
        self._sig_text.setPlaceholderText("Your name...")
        gl.addWidget(self._sig_text)

        font_label = QLabel("Font")
        font_label.setProperty("role", "fieldLabel")
        gl.addWidget(font_label)

        self._combo_font = StableComboBox()
        for font in SIGNATURE_FONTS:
            self._combo_font.addItem(font["name"])
        gl.addWidget(self._combo_font)
        context_layout.addWidget(self._grp_typed)

        self._grp_image = QWidget()
        il = QVBoxLayout(self._grp_image)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(THEME.spacing.field_gap)

        image_label = QLabel("Image file")
        image_label.setProperty("role", "fieldLabel")
        il.addWidget(image_label)

        image_row = QHBoxLayout()
        image_row.setContentsMargins(0, 0, 0, 0)
        image_row.setSpacing(THEME.spacing.compact_gap)

        self._lbl_image = QLabel("(none)")
        self._lbl_image.setProperty("role", "helper")
        self._lbl_image.setWordWrap(True)
        image_row.addWidget(self._lbl_image, stretch=1)

        btn_browse = QPushButton("Browse...")
        btn_browse.setProperty("role", "quiet")
        btn_browse.clicked.connect(self._browse_image)
        image_row.addWidget(btn_browse)
        il.addLayout(image_row)
        context_layout.addWidget(self._grp_image)

        self._grp_name = QWidget()
        nl = QVBoxLayout(self._grp_name)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(THEME.spacing.field_gap)

        name_label = QLabel("Name")
        name_label.setProperty("role", "fieldLabel")
        nl.addWidget(name_label)

        self._name_text = QLineEdit()
        nl.addWidget(self._name_text)
        context_layout.addWidget(self._grp_name)

        self._grp_date = QWidget()
        dl = QVBoxLayout(self._grp_date)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(THEME.spacing.field_gap)

        date_label = QLabel("Date")
        date_label.setProperty("role", "fieldLabel")
        dl.addWidget(date_label)

        self._date_text = QLineEdit()
        self._date_text.setText(datetime.now().strftime(DEFAULT_DATE_FORMAT))
        dl.addWidget(self._date_text)
        context_layout.addWidget(self._grp_date)

        self._lbl_color = QLabel("Color")
        self._lbl_color.setProperty("role", "fieldLabel")
        context_layout.addWidget(self._lbl_color)

        self._combo_color = StableComboBox()
        self._combo_color.addItems([c.capitalize() for c in SUPPORTED_COLORS])
        context_layout.addWidget(self._combo_color)
        layout.addWidget(context_card)

        action_card = QFrame()
        action_card.setObjectName("actionCard")
        action_layout = QVBoxLayout(action_card)
        action_layout.setContentsMargins(8, 8, 8, 8)
        action_layout.setSpacing(THEME.spacing.field_gap)

        self._btn_place = QPushButton("Place eSign")
        self._btn_place.setProperty("role", "quiet")
        self._btn_place.clicked.connect(self._start_placement)
        self._apply_button_icon(self._btn_place, self._svg_icon("pen.svg"))
        action_layout.addWidget(self._btn_place)

        self._btn_delete = QPushButton("Delete Selected")
        self._btn_delete.setProperty("role", "quiet")
        self._btn_delete.clicked.connect(self._act_delete.trigger)
        self._apply_button_icon(self._btn_delete, self._svg_icon("delete.svg"))
        action_layout.addWidget(self._btn_delete)

        self._btn_clear = QPushButton("Clear Current Page")
        self._btn_clear.setProperty("role", "danger")
        self._btn_clear.clicked.connect(self._act_clear_page.trigger)
        self._apply_button_icon(self._btn_clear, self._svg_icon("Clear.svg"))
        action_layout.addWidget(self._btn_clear)

        self._btn_save_doc = QPushButton("Save Document")
        self._btn_save_doc.setProperty("role", "primary")
        self._btn_save_doc.clicked.connect(self._act_save.trigger)
        self._apply_button_icon(
            self._btn_save_doc,
            self._svg_icon_tinted("save.svg", THEME.colors.primary_text),
        )
        action_layout.addWidget(self._btn_save_doc)

        layout.addWidget(action_card)
        layout.addStretch()

        self._apply_mode_ui(0)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("rightPanel")
        panel.setFixedWidth(THEME.sizes.right_panel_width)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(
            THEME.spacing.panel_padding,
            THEME.spacing.panel_padding,
            THEME.spacing.panel_padding,
            THEME.spacing.panel_padding,
        )
        layout.setSpacing(THEME.spacing.section_gap)

        lbl = QLabel("Pages")
        lbl.setProperty("role", "sectionTitle")
        layout.addWidget(lbl)

        self._list_pages = QListWidget()
        self._list_pages.setObjectName("pageList")
        self._list_pages.setViewMode(QListView.ViewMode.IconMode)
        self._list_pages.setFlow(QListView.Flow.TopToBottom)
        self._list_pages.setMovement(QListView.Movement.Static)
        self._list_pages.setResizeMode(QListView.ResizeMode.Adjust)
        self._list_pages.setWrapping(False)
        self._list_pages.setSpacing(8)
        self._list_pages.setIconSize(QSize(108, 148))
        self._list_pages.setGridSize(QSize(126, 184))
        self._list_pages.setSelectionRectVisible(False)
        self._list_pages.currentRowChanged.connect(self._on_page_list_selected)
        layout.addWidget(self._list_pages, stretch=1)
        return panel

    def _build_statusbar(self) -> None:
        sb = QStatusBar()
        sb.setSizeGripEnabled(False)
        self.setStatusBar(sb)

        self._sb_file = QLabel("No file open")
        self._sb_file.setProperty("role", "helper")

        self._sb_page = QLabel("")
        self._sb_page.setProperty("role", "helper")

        self._sb_zoom = QLabel("")
        self._sb_zoom.setProperty("role", "helper")

        self._sb_msg = QLabel("")
        self._sb_msg.setProperty("role", "helper")

        sb.addWidget(self._sb_file, 1)
        sb.addPermanentWidget(self._sb_page)
        sb.addPermanentWidget(self._sb_zoom)
        sb.addPermanentWidget(self._sb_msg, 1)

    def _restore_persisted_inputs(self) -> None:
        inputs = self._persistence.tool_inputs()
        self._sig_text.setText(inputs["signature_text"])
        self._name_text.setText(inputs["name_text"])
        self._date_text.setText(inputs["date_text"] or datetime.now().strftime(DEFAULT_DATE_FORMAT))

        font_name = inputs["font_name"]
        if font_name:
            for idx, font in enumerate(SIGNATURE_FONTS):
                if font["name"] == font_name:
                    self._combo_font.setCurrentIndex(idx)
                    break

        color = inputs["color"]
        if color in SUPPORTED_COLORS:
            self._combo_color.setCurrentIndex(SUPPORTED_COLORS.index(color))

        self._sig_text.textChanged.connect(self._persist_tool_inputs)
        self._name_text.textChanged.connect(self._persist_tool_inputs)
        self._date_text.textChanged.connect(self._persist_tool_inputs)
        self._combo_font.currentIndexChanged.connect(self._persist_tool_inputs)
        self._combo_color.currentIndexChanged.connect(self._persist_tool_inputs)
        self._undo_stack.indexChanged.connect(lambda _index: self._update_controls())
        self._persist_tool_inputs()

    def _persist_tool_inputs(self) -> None:
        self._persistence.save_tool_inputs(
            signature_text=self._sig_text.text(),
            name_text=self._name_text.text(),
            date_text=self._date_text.text(),
            font_name=self._combo_font.currentText(),
            color=SUPPORTED_COLORS[self._combo_color.currentIndex()],
        )

    def _open_dialog_directory(self) -> str:
        return self._persistence.last_open_dir() or os.path.dirname(self._pdf.path or "") or ""

    def _save_dialog_directory(self) -> str:
        return (
            self._persistence.last_save_dir()
            or os.path.dirname(self._pdf.path or "")
            or self._persistence.last_open_dir()
            or ""
        )

    def _open_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open PDF",
            self._open_dialog_directory(),
            "PDF Files (*.pdf)",
        )
        if path:
            self._open_pdf_path(path)

    def _open_recent_pdf(self, path: str) -> None:
        if not os.path.isfile(path):
            self._persistence.remove_recent_file(path)
            self._rebuild_recent_menu()
            QMessageBox.warning(self, "Recent file missing", "That PDF is no longer available.")
            return
        self._open_pdf_path(path)

    def _open_pdf_path(self, path: str) -> None:
        try:
            self._pdf.open(path)
        except Exception as exc:
            QMessageBox.critical(self, "Error opening PDF", str(exc))
            return

        self._overlays.clear()
        self._viewer.clear_selection()
        self._selected_overlay_ids = []
        self._copied_overlay = None
        self._paste_count = 0
        self._undo_stack.clear()
        self._current_page = 0
        self._zoom = ZOOM_DEFAULT
        self._zoom_mode = ZOOM_MODE_FIT
        self._sb_file.setText(os.path.basename(path))

        opened_dir = os.path.dirname(path)
        self._persistence.set_last_open_dir(opened_dir)
        self._persistence.add_recent_file(path)
        self._rebuild_recent_menu()

        self._load_document()
        self._populate_page_list()
        self._set_page_list_current(self._current_page)

        zoom_mode, zoom_value = self._persistence.zoom_preference()
        if zoom_mode == ZOOM_MODE_CUSTOM:
            self._set_zoom(zoom_value, persist=True)
        else:
            self._fit_page()

        self._status_msg(f"Opened: {os.path.basename(path)}")
        self._update_controls()

    def _save_pdf(self) -> None:
        if not self._pdf.is_open:
            QMessageBox.warning(self, "No PDF", "Please open a PDF first.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save PDF As",
            self._save_dialog_directory(),
            "PDF Files (*.pdf)",
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        if os.path.normcase(os.path.abspath(path)) == os.path.normcase(
            os.path.abspath(self._pdf.path or "")
        ):
            ans = QMessageBox.question(
                self,
                "Overwrite original?",
                "You are about to overwrite the original PDF. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        try:
            self._pdf.save(self._overlays, path)
            self._persistence.set_last_save_dir(os.path.dirname(path))
            self._status_msg(f"Saved: {os.path.basename(path)}")
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def _zoom_in(self) -> None:
        self._set_zoom(min(self._zoom + ZOOM_STEP, ZOOM_MAX))

    def _zoom_out(self) -> None:
        self._set_zoom(max(self._zoom - ZOOM_STEP, ZOOM_MIN))

    def _zoom_reset(self) -> None:
        self._set_zoom(ZOOM_DEFAULT)

    def _fit_page(self) -> None:
        if not self._pdf.is_open:
            return
        page_index = self._viewer.current_viewport_page()
        fit_zoom = self._viewer.fit_zoom_for_page(page_index, padding_px=24)
        if fit_zoom is None:
            return
        fit_zoom = max(ZOOM_MIN, min(fit_zoom, ZOOM_MAX))
        self._set_zoom(fit_zoom, persist=False)
        self._zoom_mode = ZOOM_MODE_FIT
        self._persistence.set_zoom_preference(ZOOM_MODE_FIT, fit_zoom)
        self._viewer.scroll_to_page(page_index)

    def _set_zoom(self, zoom: float, persist: bool = True) -> None:
        if not self._pdf.is_open:
            return
        focus_page = self._viewer.current_viewport_page()
        self._zoom = zoom
        self._zoom_mode = ZOOM_MODE_CUSTOM
        self._pdf.invalidate_cache()
        self._load_document()
        self._viewer.scroll_to_page(focus_page)
        if persist:
            self._persistence.set_zoom_preference(ZOOM_MODE_CUSTOM, zoom)
        self._update_controls()

    def _on_mode_changed(self, index: int) -> None:
        self._current_mode = index
        self._apply_mode_ui(index)

    def _apply_mode_ui(self, index: int) -> None:
        if 0 <= index < len(self._tool_buttons) and not self._tool_buttons[index].isChecked():
            self._tool_buttons[index].setChecked(True)

        self._grp_typed.setVisible(index == 0)
        self._grp_image.setVisible(index == 1)
        self._grp_name.setVisible(index == 2)
        self._grp_date.setVisible(index == 3)
        color_visible = index in (0, 2, 3)
        self._lbl_color.setVisible(color_visible)
        self._combo_color.setVisible(color_visible)
        self._btn_place.setText(self._place_label_for_mode(index))

    @staticmethod
    def _place_label_for_mode(index: int) -> str:
        if index in (0, 1):
            return "Place eSign"
        if index == 2:
            return "Place Name"
        return "Place Date"

    def _browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Signature Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.tif *.webp)",
        )
        if not path:
            return
        err = validate_image_path(path)
        if err:
            QMessageBox.warning(self, "Invalid image", err)
            return
        self._image_path = path
        self._lbl_image.setText(os.path.basename(path))

    def _start_placement(self) -> None:
        if not self._pdf.is_open:
            QMessageBox.warning(self, "No PDF", "Please open a PDF first.")
            return

        mode = self._current_mode
        color = SUPPORTED_COLORS[self._combo_color.currentIndex()]

        if mode == 0:
            text = self._sig_text.text().strip()
            font_name = self._combo_font.currentText()
            err = validate_typed_signature(text, font_name)
            if err:
                QMessageBox.warning(self, "Input required", err)
                return
            pending = PendingPlacement(
                overlay_type=OverlayType.typed_signature,
                text=text,
                font_name=font_name,
                color=color,
            )
        elif mode == 1:
            err = validate_signature_image(self._image_path)
            if err:
                QMessageBox.warning(self, "Input required", err)
                return
            pending = PendingPlacement(
                overlay_type=OverlayType.signature_image,
                image_path=self._image_path,
            )
        elif mode == 2:
            text = self._name_text.text().strip()
            err = validate_name(text)
            if err:
                QMessageBox.warning(self, "Input required", err)
                return
            pending = PendingPlacement(
                overlay_type=OverlayType.name,
                text=text,
                color=color,
            )
        else:
            text = self._date_text.text().strip()
            err = validate_date(text)
            if err:
                QMessageBox.warning(self, "Input required", err)
                return
            pending = PendingPlacement(
                overlay_type=OverlayType.date,
                text=text,
                color=color,
            )

        self._viewer.set_pending(pending)
        self._status_msg("Draw a rectangle on the page to place the overlay.")

    def _delete_selected(self) -> None:
        self._viewer.delete_selected()

    def _clear_overlays(self) -> None:
        if not self._pdf.is_open:
            return
        page_index = self._viewer.current_viewport_page()
        page_ids = [ov.id for ov in self._overlays if ov.page_index == page_index]
        if not page_ids:
            return
        before_overlays = self._snapshot_overlays()
        after_overlays = [ov for ov in before_overlays if ov.id not in set(page_ids)]
        self._push_state_command(
            "Clear Current Page Overlays",
            before_overlays,
            self._selected_overlay_ids,
            after_overlays,
            [],
            redo_status="Cleared overlays on the current page.",
            undo_status="Restored overlays on the current page.",
        )

    def _compute_overlay_font_size(self, overlay: OverlayItem) -> None:
        if overlay.type == OverlayType.signature_image or not overlay.text:
            return
        if not self._pdf.is_open:
            return
        font_name = overlay.font_name if overlay.type == OverlayType.typed_signature else None
        overlay.font_size = self._pdf.compute_font_size(
            overlay.text,
            font_name,
            overlay.rect_pdf.width,
            overlay.rect_pdf.height,
        )

    def _compute_overlay_font_sizes(self, overlays: list[OverlayItem]) -> None:
        if not self._pdf.is_open:
            return
        for overlay in overlays:
            self._compute_overlay_font_size(overlay)

    def _snapshot_overlays(self) -> list[OverlayItem]:
        return copy.deepcopy(self._overlays)

    def _overlay_by_id(self, overlay_id: str, overlays: Optional[list[OverlayItem]] = None) -> Optional[OverlayItem]:
        source = self._overlays if overlays is None else overlays
        return next((overlay for overlay in source if overlay.id == overlay_id), None)

    def _selected_overlay(self) -> Optional[OverlayItem]:
        selected_id = self._viewer.primary_selected_overlay_id()
        if selected_id is None:
            return None
        return self._overlay_by_id(selected_id)

    def _apply_overlay_snapshot(self, overlays: list[OverlayItem], overlay_snapshot: OverlayItem) -> None:
        for index, overlay in enumerate(overlays):
            if overlay.id == overlay_snapshot.id:
                overlays[index] = copy.deepcopy(overlay_snapshot)
                return

    def _push_state_command(
        self,
        text: str,
        before_overlays: list[OverlayItem],
        before_selection: list[str],
        after_overlays: list[OverlayItem],
        after_selection: list[str],
        *,
        redo_status: str = "",
        undo_status: str = "",
    ) -> None:
        if before_overlays == after_overlays and list(before_selection) == list(after_selection):
            return
        self._undo_stack.push(
            OverlayStateCommand(
                self,
                text,
                before_overlays,
                before_selection,
                after_overlays,
                after_selection,
                redo_status=redo_status,
                undo_status=undo_status,
            )
        )

    def _apply_overlays_state(
        self,
        overlays: list[OverlayItem],
        selected_overlay_ids: list[str],
        status_msg: str = "",
    ) -> None:
        if not self._pdf.is_open:
            return
        focus_page = self._current_page
        if selected_overlay_ids:
            selected_overlay = next(
                (overlay for overlay in overlays if overlay.id == selected_overlay_ids[-1]),
                None,
            )
            if selected_overlay is not None:
                focus_page = selected_overlay.page_index

        self._overlays = copy.deepcopy(overlays)
        self._compute_overlay_font_sizes(self._overlays)
        self._load_document()
        if self._pdf.page_count:
            focus_page = max(0, min(focus_page, self._pdf.page_count - 1))
            self._viewer.scroll_to_page(focus_page)
        self._viewer.set_selected_overlay_ids(selected_overlay_ids)
        self._selected_overlay_ids = [
            overlay_id for overlay_id in selected_overlay_ids
            if self._overlay_by_id(overlay_id) is not None
        ]
        self._update_controls()
        if status_msg:
            self._status_msg(status_msg)

    def _copy_selected_overlay(self) -> None:
        overlay = self._selected_overlay()
        if overlay is None:
            return
        self._copied_overlay = copy.deepcopy(overlay)
        self._paste_count = 0
        self._status_msg("Overlay copied.")
        self._update_controls()

    def _paste_overlay(self) -> None:
        if not self._pdf.is_open or self._copied_overlay is None:
            return

        page_index = self._viewer.current_viewport_page()
        self._paste_count += 1
        pasted_overlay = copy.deepcopy(self._copied_overlay)
        pasted_overlay.id = OverlayItem(
            page_index=page_index,
            type=pasted_overlay.type,
            rect_pdf=PdfRect(0, 0, 1, 1),
        ).id
        pasted_overlay.page_index = page_index
        pasted_overlay.rect_pdf = self._viewer.clamp_rect_to_page(
            page_index,
            PdfRect(
                pasted_overlay.rect_pdf.x + (12.0 * self._paste_count),
                pasted_overlay.rect_pdf.y + (12.0 * self._paste_count),
                pasted_overlay.rect_pdf.width,
                pasted_overlay.rect_pdf.height,
            ),
        )

        before_overlays = self._snapshot_overlays()
        after_overlays = before_overlays + [pasted_overlay]
        self._push_state_command(
            "Paste Overlay",
            before_overlays,
            self._selected_overlay_ids,
            after_overlays,
            [pasted_overlay.id],
            redo_status="Overlay pasted.",
            undo_status="Paste undone.",
        )

    def _on_overlay_placement_requested(self, overlay: OverlayItem) -> None:
        before_overlays = self._snapshot_overlays()
        after_overlays = before_overlays + [copy.deepcopy(overlay)]
        self._push_state_command(
            "Add Overlay",
            before_overlays,
            self._selected_overlay_ids,
            after_overlays,
            [overlay.id],
            redo_status="Overlay placed. Draw another or click Place to continue.",
            undo_status="Overlay removed.",
        )

    def _on_delete_requested(self, overlay_ids: list[str]) -> None:
        if not overlay_ids:
            return
        overlay_id_set = set(overlay_ids)
        before_overlays = self._snapshot_overlays()
        after_overlays = [ov for ov in before_overlays if ov.id not in overlay_id_set]
        self._push_state_command(
            "Delete Overlay",
            before_overlays,
            self._selected_overlay_ids,
            after_overlays,
            [],
            redo_status="Overlay deleted.",
            undo_status="Overlay restored.",
        )

    def _on_overlay_geometry_change_committed(
        self,
        overlay_id: str,
        before_rect: PdfRect,
        after_rect: PdfRect,
    ) -> None:
        overlay = self._overlay_by_id(overlay_id)
        if overlay is None or before_rect == after_rect:
            return

        self._compute_overlay_font_size(overlay)
        self._viewer.refresh_overlay(overlay_id)

        before_overlays = self._snapshot_overlays()
        before_overlay = self._overlay_by_id(overlay_id, before_overlays)
        if before_overlay is None:
            return
        before_overlay.rect_pdf = copy.deepcopy(before_rect)
        self._compute_overlay_font_size(before_overlay)

        self._push_state_command(
            "Adjust Overlay",
            before_overlays,
            self._selected_overlay_ids,
            self._snapshot_overlays(),
            self._selected_overlay_ids,
            redo_status="Overlay updated.",
            undo_status="Overlay change undone.",
        )

    def _on_overlay_edit_requested(self, overlay: OverlayItem) -> None:
        original_overlay = copy.deepcopy(overlay)
        dialog = EditOverlayDialog(overlay, self)
        dialog.preview_changed.connect(lambda: self._on_overlay_live_changed(overlay))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply_to(overlay)
            self._compute_overlay_font_size(overlay)
            self._viewer.refresh_overlay(overlay.id)
            before_overlays = self._snapshot_overlays()
            original_in_snapshot = self._overlay_by_id(overlay.id, before_overlays)
            if original_in_snapshot is None:
                return
            self._restore_overlay(original_in_snapshot, original_overlay)
            self._compute_overlay_font_size(original_in_snapshot)
            self._push_state_command(
                "Edit Overlay",
                before_overlays,
                self._selected_overlay_ids,
                self._snapshot_overlays(),
                self._selected_overlay_ids,
                redo_status="Overlay updated.",
                undo_status="Overlay edit undone.",
            )
        else:
            self._restore_overlay(overlay, original_overlay)
            self._viewer.refresh_overlay(overlay.id)

    def _on_overlay_live_changed(self, overlay: OverlayItem) -> None:
        self._compute_overlay_font_size(overlay)
        self._viewer.refresh_overlay(overlay.id)

    @staticmethod
    def _restore_overlay(target: OverlayItem, source: OverlayItem) -> None:
        target.page_index = source.page_index
        target.type = source.type
        target.rect_pdf = source.rect_pdf
        target.text = source.text
        target.font_name = source.font_name
        target.color = source.color
        target.image_path = source.image_path
        target.font_size = source.font_size

    def _on_viewer_selection_changed(self, overlay_ids: list[str]) -> None:
        self._selected_overlay_ids = list(overlay_ids)
        self._update_controls()

    def _on_viewport_page_changed(self, page_index: int) -> None:
        self._current_page = page_index
        self._set_page_list_current(page_index)
        self._update_controls()

    def _on_page_list_selected(self, page_index: int) -> None:
        if not self._pdf.is_open or page_index < 0:
            return
        self._viewer.scroll_to_page(page_index)
        self._current_page = page_index
        self._update_controls()

    def _load_document(self) -> None:
        if not self._pdf.is_open:
            return
        pixmaps = self._pdf.render_document(self._zoom)
        self._viewer.load_document(pixmaps, self._overlays, self._zoom)

    def _populate_page_list(self) -> None:
        self._list_pages.clear()
        if not self._pdf.is_open:
            return
        for i in range(self._pdf.page_count):
            thumb = self._pdf.render_thumbnail(i, max_width=110, max_height=150)
            item = QListWidgetItem(QIcon(thumb), str(i + 1))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._list_pages.addItem(item)

    def _set_page_list_current(self, page_index: int) -> None:
        if not hasattr(self, "_list_pages"):
            return
        if page_index < 0 or page_index >= self._list_pages.count():
            return
        prev = self._list_pages.blockSignals(True)
        self._list_pages.setCurrentRow(page_index)
        self._list_pages.scrollToItem(self._list_pages.item(page_index))
        self._list_pages.blockSignals(prev)

    def _rebuild_recent_menu(self) -> None:
        self._menu_recent.clear()
        recent_files = self._persistence.recent_files()
        self._menu_recent.setEnabled(bool(recent_files))
        if not recent_files:
            action = self._menu_recent.addAction("(No recent files)")
            action.setEnabled(False)
            return

        for path in recent_files:
            action = self._menu_recent.addAction(path)
            action.triggered.connect(lambda checked=False, p=path: self._open_recent_pdf(p))

    def _update_controls(self) -> None:
        open_ = self._pdf.is_open
        pc = self._pdf.page_count if open_ else 0
        pg = self._current_page
        has_selection = bool(self._selected_overlay_ids)
        has_page_overlays = any(ov.page_index == pg for ov in self._overlays)

        self._act_save.setEnabled(open_)
        self._act_copy.setEnabled(open_ and has_selection)
        self._act_paste.setEnabled(open_ and self._copied_overlay is not None)
        self._act_delete.setEnabled(open_ and has_selection)
        self._act_clear_page.setEnabled(open_ and has_page_overlays)
        self._act_zoom_in.setEnabled(open_ and self._zoom < ZOOM_MAX)
        self._act_zoom_out.setEnabled(open_ and self._zoom > ZOOM_MIN)
        self._act_zoom_reset.setEnabled(open_)
        self._act_fit_page.setEnabled(open_)

        self._btn_place.setEnabled(open_)
        self._btn_delete.setEnabled(self._act_delete.isEnabled())
        self._btn_clear.setEnabled(self._act_clear_page.isEnabled())
        self._btn_save_doc.setEnabled(self._act_save.isEnabled())
        self._list_pages.setEnabled(open_)

        if open_:
            self._lbl_page.setText(f"Page {pg + 1} / {pc}")
            self._lbl_zoom.setText(f"{int(self._zoom * 100)}%")
            self._sb_page.setText(f"Page {pg + 1}/{pc}")
            self._sb_zoom.setText(f"Zoom {int(self._zoom * 100)}%")
        else:
            self._lbl_page.setText("Page 0 / 0")
            self._lbl_zoom.setText("--")
            self._sb_page.setText("")
            self._sb_zoom.setText("")

    def _status_msg(self, msg: str) -> None:
        self._sb_msg.setText(msg)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._persist_tool_inputs()
        self._persistence.save_window_geometry(self)
        super().closeEvent(event)


class EditOverlayDialog(QDialog):
    preview_changed = Signal()

    def __init__(self, overlay: OverlayItem, parent=None):
        super().__init__(parent)
        self.setObjectName("editOverlayDialog")
        self.setWindowTitle("Edit Overlay")
        self.setMinimumWidth(350)
        self._overlay = overlay
        self._new_image_path: Optional[str] = overlay.image_path
        self._suspend_preview = False
        self._build_ui()

    def _build_ui(self) -> None:
        self._suspend_preview = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(THEME.spacing.section_gap)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(THEME.spacing.field_gap)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.addLayout(form)
        ov = self._overlay

        if ov.type == OverlayType.typed_signature:
            self._text_edit = QLineEdit(ov.text or "")
            self._text_edit.textChanged.connect(self._on_live_input_changed)
            form.addRow("Signature text:", self._text_edit)

            self._font_combo = StableComboBox()
            for f in SIGNATURE_FONTS:
                self._font_combo.addItem(f["name"])
            idx = next((i for i, f in enumerate(SIGNATURE_FONTS) if f["name"] == ov.font_name), 0)
            self._font_combo.setCurrentIndex(idx)
            self._font_combo.currentIndexChanged.connect(self._on_live_input_changed)
            form.addRow("Font:", self._font_combo)

            self._color_combo = self._make_color_combo(ov.color)
            self._color_combo.currentIndexChanged.connect(self._on_live_input_changed)
            form.addRow("Color:", self._color_combo)

        elif ov.type in (OverlayType.name, OverlayType.date):
            label = "Name:" if ov.type == OverlayType.name else "Date:"
            self._text_edit = QLineEdit(ov.text or "")
            self._text_edit.textChanged.connect(self._on_live_input_changed)
            form.addRow(label, self._text_edit)

            self._color_combo = self._make_color_combo(ov.color)
            self._color_combo.currentIndexChanged.connect(self._on_live_input_changed)
            form.addRow("Color:", self._color_combo)

        elif ov.type == OverlayType.signature_image:
            self._lbl_img = QLabel(os.path.basename(ov.image_path or "(none)"))
            self._lbl_img.setProperty("role", "helper")
            self._lbl_img.setWordWrap(True)

            btn_browse = QPushButton("Browse...")
            btn_browse.setProperty("role", "quiet")
            btn_browse.clicked.connect(self._browse_image)

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(THEME.spacing.compact_gap)
            row_layout.addWidget(self._lbl_img, stretch=1)
            row_layout.addWidget(btn_browse)
            form.addRow("Image file:", row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        btn_ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        btn_cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if btn_ok is not None:
            btn_ok.setText("Apply")
            btn_ok.setProperty("role", "primary")
            self._refresh_style(btn_ok)
        if btn_cancel is not None:
            btn_cancel.setProperty("role", "quiet")
            self._refresh_style(btn_cancel)

        self._suspend_preview = False

    @staticmethod
    def _refresh_style(widget: QWidget) -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    @staticmethod
    def _make_color_combo(current: Optional[str]) -> StableComboBox:
        combo = StableComboBox()
        combo.addItems([c.capitalize() for c in SUPPORTED_COLORS])
        if current in SUPPORTED_COLORS:
            combo.setCurrentIndex(SUPPORTED_COLORS.index(current))
        return combo

    def _browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Signature Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.tif *.webp)",
        )
        if path:
            err = validate_image_path(path)
            if err:
                QMessageBox.warning(self, "Invalid image", err)
                return
            self._new_image_path = path
            self._lbl_img.setText(os.path.basename(path))
            self._apply_live_to_overlay()
            self.preview_changed.emit()

    def _on_live_input_changed(self) -> None:
        self._apply_live_to_overlay()
        self.preview_changed.emit()

    def _apply_live_to_overlay(self) -> None:
        if self._suspend_preview:
            return
        ov = self._overlay
        if ov.type == OverlayType.typed_signature:
            ov.text = self._text_edit.text()
            ov.font_name = self._font_combo.currentText()
            ov.color = SUPPORTED_COLORS[self._color_combo.currentIndex()]
        elif ov.type in (OverlayType.name, OverlayType.date):
            ov.text = self._text_edit.text()
            ov.color = SUPPORTED_COLORS[self._color_combo.currentIndex()]
        elif ov.type == OverlayType.signature_image:
            ov.image_path = self._new_image_path

    def apply_to(self, overlay: OverlayItem) -> None:
        ov = self._overlay
        if ov.type == OverlayType.typed_signature:
            text = self._text_edit.text().strip()
            if text:
                overlay.text = text
            overlay.font_name = self._font_combo.currentText()
            overlay.color = SUPPORTED_COLORS[self._color_combo.currentIndex()]
        elif ov.type in (OverlayType.name, OverlayType.date):
            text = self._text_edit.text().strip()
            if text:
                overlay.text = text
            overlay.color = SUPPORTED_COLORS[self._color_combo.currentIndex()]
        elif ov.type == OverlayType.signature_image:
            overlay.image_path = self._new_image_path
