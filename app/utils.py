from __future__ import annotations
from typing import Tuple
from PySide6.QtGui import QColor

from app.models import PdfRect


def normalize_rect(x1: float, y1: float, x2: float, y2: float) -> PdfRect:
    """Return a PdfRect with positive width/height regardless of drag direction."""
    x = min(x1, x2)
    y = min(y1, y2)
    w = abs(x2 - x1)
    h = abs(y2 - y1)
    return PdfRect(x, y, w, h)


def aspect_fit(
    src_w: float, src_h: float, dst_w: float, dst_h: float
) -> Tuple[float, float, float, float]:
    """
    Return (x, y, w, h) inside dst bounding box that preserves src aspect ratio.
    The result is centered within the destination.
    """
    if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
        return (0.0, 0.0, dst_w, dst_h)

    src_ratio = src_w / src_h
    dst_ratio = dst_w / dst_h

    if src_ratio > dst_ratio:
        # wider than tall relative to destination
        w = dst_w
        h = dst_w / src_ratio
    else:
        h = dst_h
        w = dst_h * src_ratio

    x = (dst_w - w) / 2
    y = (dst_h - h) / 2
    return (x, y, w, h)


def color_name_to_qcolor(color_name: str) -> QColor:
    mapping = {
        "black": QColor(0, 0, 0),
        "blue": QColor(0, 0, 180),
    }
    return mapping.get(color_name, QColor(0, 0, 0))


def color_name_to_mupdf(color_name: str) -> Tuple[float, float, float]:
    """Return an RGB tuple in 0-1 range for PyMuPDF."""
    mapping = {
        "black": (0.0, 0.0, 0.0),
        "blue": (0.0, 0.0, 0.706),
    }
    return mapping.get(color_name, (0.0, 0.0, 0.0))


def fit_font_size(
    text: str,
    font_name: str,
    rect_w: float,
    rect_h: float,
    max_size: float = 200.0,
    min_size: float = 4.0,
) -> float:
    """
    Binary-search for the largest font size where the text fits inside rect_w x rect_h.
    Uses a rough character-width heuristic (0.6 * font_size per char).
    A proper implementation would use PyMuPDF's get_text_length; this is used
    for preview sizing in Qt where we don't want a PyMuPDF dependency.
    """
    lo, hi = min_size, max_size
    for _ in range(20):
        mid = (lo + hi) / 2
        char_w = mid * 0.6
        line_w = len(text) * char_w
        if line_w <= rect_w and mid <= rect_h:
            lo = mid
        else:
            hi = mid
    return lo
