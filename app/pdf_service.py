from __future__ import annotations
import os
import shutil
import tempfile
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from PySide6.QtGui import QImage, QPixmap

from app.models import OverlayItem, OverlayType
from app.settings import SIGNATURE_FONTS
from app.utils import color_name_to_mupdf, aspect_fit

# Map display font name -> file name
_FONT_FILE_MAP: Dict[str, str] = {f["name"]: f["file"] for f in SIGNATURE_FONTS}


class PdfService:
    def __init__(self, fonts_dir: str) -> None:
        self._fonts_dir = fonts_dir
        self._doc: Optional[fitz.Document] = None
        self._path: Optional[str] = None
        self._cache: Dict[Tuple[int, float], QPixmap] = {}

    # ------------------------------------------------------------------
    # Open / close
    # ------------------------------------------------------------------

    def open(self, path: str) -> None:
        self.close()
        doc = fitz.open(path)
        if doc.is_encrypted:
            doc.close()
            raise ValueError("Encrypted PDFs are not supported.")
        self._doc = doc
        self._path = path
        self._cache.clear()

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        self._path = None
        self._cache.clear()

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

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_page(self, page_index: int, zoom: float) -> QPixmap:
        key = (page_index, zoom)
        if key in self._cache:
            return self._cache[key]

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
        page: fitz.Page,
        rect: fitz.Rect,
        overlay: OverlayItem,
        color: Tuple[float, float, float],
    ) -> None:
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

    def _insert_text(
        self,
        page: fitz.Page,
        rect: fitz.Rect,
        text: str,
        color: Tuple[float, float, float],
        font_size: Optional[float] = None,
    ) -> None:
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
        page: fitz.Page,
        rect: fitz.Rect,
        text: str,
        color: Tuple[float, float, float],
        fitz_font: fitz.Font,
        fontname: str,
        fontsize: float,
    ) -> None:
        """Insert one line of text centered in rect using insert_text()."""
        if not text or fontsize <= 0:
            return

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
        self, page: fitz.Page, rect: fitz.Rect, image_path: str
    ) -> None:
        page.insert_image(rect, filename=image_path, keep_proportion=True, overlay=True)
