from __future__ import annotations

import os
import shutil
import tempfile
import warnings
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, Qt
from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF, QImage, QPainter, QPixmap

from app.models import OverlayItem, OverlayType
from app.settings import SIGNATURE_FONTS
from app.utils import color_name_to_mupdf, color_name_to_qcolor

# Map display font name -> file name
_FONT_FILE_MAP: Dict[str, str] = {f["name"]: f["file"] for f in SIGNATURE_FONTS}

# ── Lazy MuPDF backend ───────────────────────────────────────────────────────
# fitz/PyMuPDF is large (~37 MB) and slow to import.  We defer loading it
# until the first PDF operation so the window appears before MuPDF initialises.

_fitz_module = None


def _fitz():
    """Return the fitz module, importing and initialising it on first call."""
    global _fitz_module
    if _fitz_module is None:
        import fitz as _m
        _m.TOOLS.mupdf_display_errors(False)
        _fitz_module = _m
    return _fitz_module


class PdfService:
    def __init__(self, fonts_dir: str) -> None:
        self._fonts_dir = fonts_dir
        self._doc = None          # fitz.Document — typed lazily to avoid import
        self._path: Optional[str] = None
        self._cache: Dict[Tuple[int, float], QPixmap] = {}
        self._thumb_cache: Dict[Tuple[int, int, int], QPixmap] = {}
        self._qt_font_family_cache: Dict[str, str] = {}
        self._last_save_warnings: List[str] = []

    # ------------------------------------------------------------------
    # Open / close
    # ------------------------------------------------------------------

    def open(self, path: str) -> None:
        fitz = _fitz()
        self.close()
        doc = fitz.open(path)
        if doc.is_encrypted:
            doc.close()
            raise ValueError("Encrypted PDFs are not supported.")
        self._doc = doc
        self._path = path
        self._cache.clear()
        self._thumb_cache.clear()

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        self._path = None
        self._cache.clear()
        self._thumb_cache.clear()

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._doc is not None

    @property
    def path(self) -> Optional[str]:
        return self._path

    @property
    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    def page_size(self, page_index: int) -> Tuple[float, float]:
        page = self._doc[page_index]
        r = page.rect
        return (r.width, r.height)

    @property
    def last_save_warnings(self) -> List[str]:
        return list(self._last_save_warnings)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_page(self, page_index: int, zoom: float) -> QPixmap:
        key = (page_index, zoom)
        if key in self._cache:
            return self._cache[key]

        fitz = _fitz()
        page = self._doc[page_index]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        img = QImage(
            pix.samples, pix.width, pix.height, pix.stride,
            QImage.Format.Format_RGB888,
        )
        pixmap = QPixmap.fromImage(img)
        self._cache[key] = pixmap
        return pixmap

    def invalidate_cache(self) -> None:
        self._cache.clear()

    def render_document(self, zoom: float) -> List[QPixmap]:
        if self._doc is None:
            return []
        return [self.render_page(i, zoom) for i in range(self._doc.page_count)]

    def render_thumbnail(
        self,
        page_index: int,
        max_width: int = 120,
        max_height: int = 170,
    ) -> QPixmap:
        key = (page_index, max_width, max_height)
        cached = self._thumb_cache.get(key)
        if cached is not None:
            return cached
        if self._doc is None:
            return QPixmap()

        fitz = _fitz()
        page = self._doc[page_index]
        rect = page.rect
        zoom = min(max_width / max(rect.width, 1.0), max_height / max(rect.height, 1.0))
        zoom = max(zoom, 0.05)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = QImage(
            pix.samples, pix.width, pix.height, pix.stride,
            QImage.Format.Format_RGB888,
        )
        thumb = QPixmap.fromImage(img)
        self._thumb_cache[key] = thumb
        return thumb

    # ------------------------------------------------------------------
    # Font-size computation (ground truth for both preview and save)
    # ------------------------------------------------------------------

    def compute_font_size(
        self,
        text: str,
        font_name: Optional[str],
        rect_w: float,
        rect_h: float,
    ) -> float:
        """
        Binary-search for the largest font size (in PDF points) where *text*
        fits inside a rect of *rect_w* × *rect_h* PDF points.
        Uses fitz.Font.text_length() which is identical to insert_textbox's metric,
        so this value can be used verbatim at save time.
        """
        if not text or rect_w <= 0 or rect_h <= 0:
            return 8.0

        fitz = _fitz()
        try:
            font_file = _FONT_FILE_MAP.get(font_name or "")
            if font_file:
                font_path = os.path.join(self._fonts_dir, font_file)
                fitz_font = (
                    fitz.Font(fontfile=font_path)
                    if os.path.isfile(font_path)
                    else fitz.Font("helv")
                )
            else:
                fitz_font = fitz.Font("helv")

            lo, hi = 1.0, 500.0
            best = lo
            line_height_factor = max(
                (fitz_font.ascender - fitz_font.descender),
                1.0,
            )
            for _ in range(40):  # converges to <0.001 pt precision
                mid = (lo + hi) / 2.0
                w = fitz_font.text_length(text, fontsize=mid)
                h = line_height_factor * mid
                if w <= rect_w and h <= rect_h:
                    best = mid
                    lo = mid
                else:
                    hi = mid
            return best

        except Exception:
            # Rough fallback
            return min(rect_h, rect_w / max(len(text), 1) / 0.55)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self, overlays: List[OverlayItem], output_path: str) -> None:
        if self._doc is None or self._path is None:
            raise RuntimeError("No PDF is open.")
        self._last_save_warnings = []

        fitz = _fitz()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            shutil.copy2(self._path, tmp_path)
            out_doc = fitz.open(tmp_path)

            for overlay in overlays:
                page = out_doc[overlay.page_index]
                rect = fitz.Rect(*overlay.rect_pdf.to_tuple())
                color = color_name_to_mupdf(overlay.color or "black")

                if overlay.type == OverlayType.typed_signature:
                    self._insert_typed_signature(page, rect, overlay, color)

                elif overlay.type in (OverlayType.name, OverlayType.date):
                    self._insert_text(page, rect, overlay.text or "", color,
                                      overlay.font_size)

                elif overlay.type == OverlayType.signature_image:
                    if overlay.image_path and os.path.isfile(overlay.image_path):
                        self._insert_image(page, rect, overlay.image_path)

            out_doc.save(output_path, garbage=4, deflate=True)
            out_doc.close()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _insert_typed_signature(
        self,
        page,
        rect,
        overlay: OverlayItem,
        color: Tuple[float, float, float],
    ) -> None:
        text = (overlay.text or "").strip()
        if not text:
            return

        try:
            png_stream = self._render_typed_signature_png_stream(overlay, rect)
            page.insert_image(
                rect,
                stream=png_stream,
                keep_proportion=False,
                overlay=True,
            )
            return
        except Exception as exc:
            msg = (
                "Typed signature rasterization failed; fell back to text insertion "
                f"for overlay {overlay.id[:8]}. Details: {exc}"
            )
            self._last_save_warnings.append(msg)
            warnings.warn(msg, RuntimeWarning, stacklevel=2)

        self._insert_typed_signature_as_text(page, rect, overlay, color)

    def _insert_typed_signature_as_text(
        self,
        page,
        rect,
        overlay: OverlayItem,
        color: Tuple[float, float, float],
    ) -> None:
        fitz = _fitz()
        font_file = _FONT_FILE_MAP.get(overlay.font_name or "")
        text = overlay.text or ""

        if font_file:
            font_path = os.path.join(self._fonts_dir, font_file)
            if os.path.isfile(font_path):
                font_name = f"sig_{overlay.id[:8]}"
                page.insert_font(fontname=font_name, fontfile=font_path)
                fitz_font = fitz.Font(fontfile=font_path)
                size = overlay.font_size or self.compute_font_size(
                    text, overlay.font_name, rect.width, rect.height
                )
                self._insert_centered_text_line(
                    page=page,
                    rect=rect,
                    text=text,
                    color=color,
                    fitz_font=fitz_font,
                    fontname=font_name,
                    fontsize=size,
                )
                return

        self._insert_text(page, rect, text, color, overlay.font_size)

    def _render_typed_signature_png_stream(
        self,
        overlay: OverlayItem,
        rect,
    ) -> bytes:
        text = (overlay.text or "").strip()
        if not text:
            raise ValueError("Typed signature text is empty.")

        raster_scale = 3.0
        img_w = max(4, int(round(rect.width * raster_scale)))
        img_h = max(4, int(round(rect.height * raster_scale)))

        image = QImage(img_w, img_h, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)

        fontsize_pt = overlay.font_size or self.compute_font_size(
            text,
            overlay.font_name,
            rect.width,
            rect.height,
        )
        font = self._resolve_signature_font_for_render(overlay, fontsize_pt * raster_scale)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setPen(color_name_to_qcolor(overlay.color or "black"))
        painter.setFont(font)

        metrics = QFontMetricsF(font)
        text_w = max(metrics.horizontalAdvance(text), 1.0)
        text_h = max(metrics.height(), 1.0)

        # Keep long signatures inside the requested box even if Qt metrics differ from MuPDF.
        if text_w > img_w or text_h > img_h:
            scale = min((img_w / text_w), (img_h / text_h)) * 0.98
            font.setPixelSize(max(1, int(round(font.pixelSize() * scale))))
            painter.setFont(font)
            metrics = QFontMetricsF(font)
            text_w = max(metrics.horizontalAdvance(text), 1.0)
            text_h = max(metrics.height(), 1.0)

        x = max((img_w - text_w) / 2.0, 0.0)
        y = max((img_h - text_h) / 2.0, 0.0) + metrics.ascent()
        painter.drawText(QPointF(x, y), text)
        painter.end()

        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError("Unable to open image buffer for signature rendering.")
        ok = image.save(buffer, "PNG")
        buffer.close()
        if not ok:
            raise RuntimeError("Unable to encode typed signature image as PNG.")
        return bytes(byte_array)

    def _resolve_signature_font_for_render(
        self,
        overlay: OverlayItem,
        pixel_size: float,
    ) -> QFont:
        font = QFont()
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        font.setPixelSize(max(1, int(round(pixel_size))))

        font_file = _FONT_FILE_MAP.get(overlay.font_name or "")
        if font_file:
            font_path = os.path.join(self._fonts_dir, font_file)
            if os.path.isfile(font_path):
                family = self._qt_font_family_cache.get(font_path)
                if family is None:
                    font_id = QFontDatabase.addApplicationFont(font_path)
                    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
                    family = families[0] if families else ""
                    self._qt_font_family_cache[font_path] = family
                if family:
                    font.setFamily(family)
                    return font
            # Font configured but file missing/unusable -> graceful fallback
            font.setFamily("Segoe UI")
            return font

        if overlay.font_name:
            font.setFamily(overlay.font_name)
        else:
            font.setFamily("Segoe UI")
        return font

    def _insert_text(
        self,
        page,
        rect,
        text: str,
        color: Tuple[float, float, float],
        font_size: Optional[float] = None,
    ) -> None:
        fitz = _fitz()
        fitz_font = fitz.Font("helv")
        size = font_size or self.compute_font_size(text, None, rect.width, rect.height)
        self._insert_centered_text_line(
            page=page,
            rect=rect,
            text=text,
            color=color,
            fitz_font=fitz_font,
            fontname="helv",
            fontsize=size,
        )

    def _insert_centered_text_line(
        self,
        page,
        rect,
        text: str,
        color: Tuple[float, float, float],
        fitz_font,
        fontname: str,
        fontsize: float,
    ) -> None:
        """Insert one line of text centered in rect using insert_text()."""
        if not text or fontsize <= 0:
            return

        fitz = _fitz()
        asc = fitz_font.ascender
        desc = fitz_font.descender
        line_height = max((asc - desc) * fontsize, fontsize)
        text_width = fitz_font.text_length(text, fontsize=fontsize)

        # Horizontal center; never shift left of the rectangle.
        x = rect.x0 + max((rect.width - text_width) / 2.0, 0.0)

        # Vertical center in box: convert top-aligned line box to baseline y.
        top_y = rect.y0 + max((rect.height - line_height) / 2.0, 0.0)
        baseline_y = top_y + (asc * fontsize)

        page.insert_text(
            fitz.Point(x, baseline_y),
            text,
            fontname=fontname,
            fontsize=fontsize,
            color=color,
        )

    def _insert_image(
        self, page, rect, image_path: str
    ) -> None:
        page.insert_image(rect, filename=image_path, keep_proportion=True, overlay=True)
