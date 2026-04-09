from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class OverlayType(Enum):
    typed_signature = "typed_signature"
    signature_image = "signature_image"
    name = "name"
    date = "date"


class SignaturePresetType(Enum):
    typed = "typed"
    image = "image"


@dataclass
class PdfRect:
    x: float
    y: float
    width: float
    height: float

    def to_tuple(self) -> tuple[float, float, float, float]:
        """Return (x0, y0, x1, y1) as used by PyMuPDF."""
        return (self.x, self.y, self.x + self.width, self.y + self.height)


@dataclass
class OverlayItem:
    page_index: int
    type: OverlayType
    rect_pdf: PdfRect
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    text: Optional[str] = None
    font_name: Optional[str] = None   # display name from SIGNATURE_FONTS
    color: Optional[str] = None       # "black" | "blue"
    image_path: Optional[str] = None
    font_size: Optional[float] = None  # PDF points; computed via PyMuPDF, used in both preview and save


@dataclass
class SignaturePreset:
    name: str
    preset_type: SignaturePresetType
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    text: Optional[str] = None
    font_name: Optional[str] = None
    color: Optional[str] = None
    asset_filename: Optional[str] = None
    resolved_image_path: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    is_available: bool = True
    load_error: Optional[str] = None
