from __future__ import annotations
import copy
import os
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton,
    QStatusBar, QToolBar, QVBoxLayout, QWidget,
)

from app.image_service import validate_image_path
from app.models import OverlayItem, OverlayType
from app.pdf_service import PdfService
from app.pdf_viewer import PdfViewer
from app.settings import (
    APP_NAME, DEFAULT_DATE_FORMAT, SIGNATURE_FONTS,
    SUPPORTED_COLORS, ZOOM_DEFAULT, ZOOM_MAX, ZOOM_MIN, ZOOM_STEP,
)
from app.tools import (
    PendingPlacement,
    validate_date, validate_name,
    validate_signature_image, validate_typed_signature,
)
from app.widgets import StableComboBox


class MainWindow(QMainWindow):
    def __init__(self, fonts_dir: str) -> None:
        super().__init__()
        self._fonts_dir = fonts_dir
        self._pdf = PdfService(fonts_dir)
        self._overlays: List[OverlayItem] = []
        self._current_page: int = 0
        self._zoom: float = ZOOM_DEFAULT
        self._image_path: Optional[str] = None

        self.setWindowTitle(APP_NAME)
        self.resize(1100, 800)

        self._build_ui()
        self._update_controls()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_toolbar()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_left_panel())

        self._viewer = PdfViewer()
        self._viewer.overlay_placed.connect(self._on_overlay_placed)
        self._viewer.overlay_deleted.connect(self._on_overlay_deleted)
        self._viewer.overlay_edit_requested.connect(self._on_overlay_edit_requested)
        self._viewer.overlay_resized.connect(self._on_overlay_resized)
        self._viewer.viewport_page_changed.connect(self._on_viewport_page_changed)
        layout.addWidget(self._viewer, stretch=1)

        self._build_statusbar()

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        self.addToolBar(tb)

        self._act_open = QAction("Open PDF…", self)
        self._act_open.setShortcut("Ctrl+O")
        self._act_open.triggered.connect(self._open_pdf)
        tb.addAction(self._act_open)

        self._act_save = QAction("Save As…", self)
        self._act_save.setShortcut("Ctrl+S")
        self._act_save.triggered.connect(self._save_pdf)
        tb.addAction(self._act_save)

        tb.addSeparator()

        self._act_prev = QAction("◀ Prev", self)
        self._act_prev.triggered.connect(self._prev_page)
        tb.addAction(self._act_prev)

        self._lbl_page = QLabel("Page 0 / 0")
        self._lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_page.setMinimumWidth(100)
        tb.addWidget(self._lbl_page)

        self._act_next = QAction("Next ▶", self)
        self._act_next.triggered.connect(self._next_page)
        tb.addAction(self._act_next)

        tb.addSeparator()

        self._act_zoom_out = QAction("Zoom −", self)
        self._act_zoom_out.triggered.connect(self._zoom_out)
        tb.addAction(self._act_zoom_out)

        self._lbl_zoom = QLabel("100%")
        self._lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_zoom.setMinimumWidth(55)
        tb.addWidget(self._lbl_zoom)

        self._act_zoom_in = QAction("Zoom +", self)
        self._act_zoom_in.triggered.connect(self._zoom_in)
        tb.addAction(self._act_zoom_in)

        self._act_zoom_reset = QAction("Reset", self)
        self._act_zoom_reset.triggered.connect(self._zoom_reset)
        tb.addAction(self._act_zoom_reset)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(220)
        panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --- Mode label ---
        lbl = QLabel("Overlay Type")
        lbl.setFont(self._bold_font())
        layout.addWidget(lbl)

        self._combo_mode = StableComboBox()
        self._combo_mode.addItems(["Typed Signature", "Signature Image", "Name", "Date"])
        self._combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self._combo_mode)

        layout.addSpacing(6)

        # --- Typed signature inputs ---
        self._grp_typed = QWidget()
        gl = QVBoxLayout(self._grp_typed)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(4)

        gl.addWidget(QLabel("Signature text:"))
        self._sig_text = QLineEdit()
        self._sig_text.setPlaceholderText("Your name…")
        gl.addWidget(self._sig_text)

        gl.addWidget(QLabel("Font:"))
        self._combo_font = StableComboBox()
        for f in SIGNATURE_FONTS:
            self._combo_font.addItem(f["name"])
        gl.addWidget(self._combo_font)

        layout.addWidget(self._grp_typed)

        # --- Signature image inputs ---
        self._grp_image = QWidget()
        il = QVBoxLayout(self._grp_image)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(4)

        il.addWidget(QLabel("Image file:"))
        img_row = QHBoxLayout()
        self._lbl_image = QLabel("(none)")
        self._lbl_image.setWordWrap(True)
        img_row.addWidget(self._lbl_image, stretch=1)
        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self._browse_image)
        img_row.addWidget(btn_browse)
        il.addLayout(img_row)

        layout.addWidget(self._grp_image)

        # --- Name input ---
        self._grp_name = QWidget()
        nl = QVBoxLayout(self._grp_name)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(4)
        nl.addWidget(QLabel("Name:"))
        self._name_text = QLineEdit()
        nl.addWidget(self._name_text)
        layout.addWidget(self._grp_name)

        # --- Date input ---
        self._grp_date = QWidget()
        dl = QVBoxLayout(self._grp_date)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(4)
        dl.addWidget(QLabel("Date:"))
        self._date_text = QLineEdit()
        self._date_text.setText(datetime.now().strftime(DEFAULT_DATE_FORMAT))
        dl.addWidget(self._date_text)
        layout.addWidget(self._grp_date)

        # --- Color picker (shared for text overlays) ---
        layout.addSpacing(4)
        self._lbl_color = QLabel("Color:")
        layout.addWidget(self._lbl_color)
        self._combo_color = StableComboBox()
        self._combo_color.addItems([c.capitalize() for c in SUPPORTED_COLORS])
        layout.addWidget(self._combo_color)

        layout.addSpacing(8)

        # --- Place button ---
        self._btn_place = QPushButton("Place eSign")
        self._btn_place.setMinimumHeight(32)
        self._btn_place.clicked.connect(self._start_placement)
        layout.addWidget(self._btn_place)

        # --- Delete selected ---
        self._btn_delete = QPushButton("Delete Selected")
        self._btn_delete.clicked.connect(self._delete_selected)
        layout.addWidget(self._btn_delete)

        # --- Clear all ---
        self._btn_clear = QPushButton("Clear All Overlays")
        self._btn_clear.clicked.connect(self._clear_overlays)
        layout.addWidget(self._btn_clear)

        layout.addStretch()
        self._apply_mode_ui(0)
        return panel

    def _build_statusbar(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)

        self._sb_file = QLabel("No file open")
        self._sb_page = QLabel("")
        self._sb_zoom = QLabel("")
        self._sb_msg = QLabel("")

        sb.addWidget(self._sb_file)
        sb.addPermanentWidget(self._sb_page)
        sb.addPermanentWidget(self._sb_zoom)
        sb.addPermanentWidget(self._sb_msg)

    # ------------------------------------------------------------------
    # Toolbar / navigation actions
    # ------------------------------------------------------------------

    def _open_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF Files (*.pdf)"
        )
        if not path:
            return
        try:
            self._pdf.open(path)
        except Exception as exc:
            QMessageBox.critical(self, "Error opening PDF", str(exc))
            return

        self._overlays.clear()
        self._current_page = 0
        self._zoom = ZOOM_DEFAULT
        self._sb_file.setText(os.path.basename(path))
        self._update_controls()
        self._load_document()

    def _save_pdf(self) -> None:
        if not self._pdf.is_open:
            QMessageBox.warning(self, "No PDF", "Please open a PDF first.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF As", "", "PDF Files (*.pdf)"
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        # Warn if overwriting source
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
            self._status_msg(f"Saved: {os.path.basename(path)}")
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def _prev_page(self) -> None:
        self._status_msg("Continuous view enabled. Scroll to navigate pages.")

    def _next_page(self) -> None:
        self._status_msg("Continuous view enabled. Scroll to navigate pages.")

    def _zoom_in(self) -> None:
        self._set_zoom(min(self._zoom + ZOOM_STEP, ZOOM_MAX))

    def _zoom_out(self) -> None:
        self._set_zoom(max(self._zoom - ZOOM_STEP, ZOOM_MIN))

    def _zoom_reset(self) -> None:
        self._set_zoom(ZOOM_DEFAULT)

    def _set_zoom(self, zoom: float) -> None:
        self._zoom = zoom
        self._pdf.invalidate_cache()
        self._load_document()
        self._update_controls()

    # ------------------------------------------------------------------
    # Left panel actions
    # ------------------------------------------------------------------

    def _on_mode_changed(self, index: int) -> None:
        self._apply_mode_ui(index)

    def _apply_mode_ui(self, index: int) -> None:
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
            self, "Select Signature Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.tif *.webp)"
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

        mode = self._combo_mode.currentIndex()
        color = SUPPORTED_COLORS[self._combo_color.currentIndex()]

        if mode == 0:  # typed signature
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

        elif mode == 1:  # signature image
            err = validate_signature_image(self._image_path)
            if err:
                QMessageBox.warning(self, "Input required", err)
                return
            pending = PendingPlacement(
                overlay_type=OverlayType.signature_image,
                image_path=self._image_path,
            )

        elif mode == 2:  # name
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

        else:  # date
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
        page_ids = {
            ov.id for ov in self._overlays if ov.page_index == page_index
        }
        self._overlays = [ov for ov in self._overlays if ov.id not in page_ids]
        self._viewer.clear_overlays_for_page(page_index)
        self._status_msg("Cleared all overlays on this page.")

    # ------------------------------------------------------------------
    # Viewer signal handlers
    # ------------------------------------------------------------------

    def _on_overlay_placed(self, overlay: OverlayItem) -> None:
        self._compute_overlay_font_size(overlay)
        self._viewer.refresh_overlay(overlay.id)
        self._overlays.append(overlay)
        self._status_msg("Overlay placed. Draw another or click Place to continue.")

    def _on_overlay_resized(self, overlay: OverlayItem) -> None:
        self._compute_overlay_font_size(overlay)
        self._viewer.refresh_overlay(overlay.id)

    def _compute_overlay_font_size(self, overlay: OverlayItem) -> None:
        """Compute and store the exact PyMuPDF font size for text overlays."""
        if overlay.type == OverlayType.signature_image or not overlay.text:
            return
        if not self._pdf.is_open:
            return
        font_name = (
            overlay.font_name if overlay.type == OverlayType.typed_signature else None
        )
        overlay.font_size = self._pdf.compute_font_size(
            overlay.text,
            font_name,
            overlay.rect_pdf.width,
            overlay.rect_pdf.height,
        )

    def _on_overlay_deleted(self, overlay_id: str) -> None:
        self._overlays = [ov for ov in self._overlays if ov.id != overlay_id]

    def _on_overlay_edit_requested(self, overlay: OverlayItem) -> None:
        original_overlay = copy.deepcopy(overlay)
        dialog = EditOverlayDialog(overlay, self)
        dialog.preview_changed.connect(lambda: self._on_overlay_live_changed(overlay))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply_to(overlay)
            self._compute_overlay_font_size(overlay)
            self._viewer.refresh_overlay(overlay.id)
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

    def _on_viewport_page_changed(self, page_index: int) -> None:
        self._current_page = page_index
        self._update_controls()

    # ------------------------------------------------------------------
    # Page rendering
    # ------------------------------------------------------------------

    def _load_document(self) -> None:
        if not self._pdf.is_open:
            return
        pixmaps = self._pdf.render_document(self._zoom)
        self._viewer.load_document(pixmaps, self._overlays, self._zoom)

    # ------------------------------------------------------------------
    # UI state helpers
    # ------------------------------------------------------------------

    def _update_controls(self) -> None:
        open_ = self._pdf.is_open
        pc = self._pdf.page_count if open_ else 0
        pg = self._current_page

        self._act_save.setEnabled(open_)
        self._act_prev.setEnabled(False)
        self._act_next.setEnabled(False)
        self._act_zoom_in.setEnabled(open_ and self._zoom < ZOOM_MAX)
        self._act_zoom_out.setEnabled(open_ and self._zoom > ZOOM_MIN)
        self._act_zoom_reset.setEnabled(open_)
        self._btn_place.setEnabled(open_)
        self._btn_delete.setEnabled(open_)
        self._btn_clear.setEnabled(open_)

        if open_:
            self._lbl_page.setText(f"Page {pg + 1} / {pc}")
            self._lbl_zoom.setText(f"{int(self._zoom * 100)}%")
            self._sb_page.setText(f"Page {pg + 1}/{pc}")
            self._sb_zoom.setText(f"Zoom {int(self._zoom * 100)}%")
        else:
            self._lbl_page.setText("Page 0 / 0")
            self._lbl_zoom.setText("—")
            self._sb_page.setText("")
            self._sb_zoom.setText("")

    def _status_msg(self, msg: str) -> None:
        self._sb_msg.setText(msg)

    @staticmethod
    def _bold_font() -> QFont:
        f = QFont()
        f.setBold(True)
        return f


# ---------------------------------------------------------------------------
# Edit overlay dialog
# ---------------------------------------------------------------------------

class EditOverlayDialog(QDialog):
    """
    Lets the user change the text, font, color, or image of an existing overlay.
    Call apply_to(overlay) after accept() to commit the changes.
    """

    def __init__(self, overlay: OverlayItem, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Overlay")
        self.setMinimumWidth(320)
        self._overlay = overlay
        self._new_image_path: Optional[str] = overlay.image_path
        self._suspend_preview = False
        self._build_ui()

    def _build_ui(self) -> None:
        self._suspend_preview = True
        layout = QVBoxLayout(self)
        form = QFormLayout()
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
            self._lbl_img.setWordWrap(True)
            btn_browse = QPushButton("Browse…")
            btn_browse.clicked.connect(self._browse_image)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(self._lbl_img, stretch=1)
            row_layout.addWidget(btn_browse)
            form.addRow("Image file:", row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._suspend_preview = False

    @staticmethod
    def _make_color_combo(current: Optional[str]) -> StableComboBox:
        combo = StableComboBox()
        combo.addItems([c.capitalize() for c in SUPPORTED_COLORS])
        if current in SUPPORTED_COLORS:
            combo.setCurrentIndex(SUPPORTED_COLORS.index(current))
        return combo

    def _browse_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Signature Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.tif *.webp)"
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
    preview_changed = Signal()
