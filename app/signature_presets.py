from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from typing import Optional

from PySide6.QtGui import QImageReader

from app.image_service import validate_image_path
from app.models import OverlayItem, OverlayType, PdfRect, SignaturePreset, SignaturePresetType
from app.paths import user_app_data_path
from app.settings import SUPPORTED_COLORS

_MANIFEST_VERSION = 1
_MAX_PRESET_NAME_LENGTH = 64


def validate_preset_name(
    name: str,
    presets: list[SignaturePreset],
    *,
    exclude_preset_id: Optional[str] = None,
) -> Optional[str]:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        return "Please enter a preset name."
    if len(cleaned) > _MAX_PRESET_NAME_LENGTH:
        return f"Preset names must be {_MAX_PRESET_NAME_LENGTH} characters or fewer."
    lowered = cleaned.casefold()
    for preset in presets:
        if preset.id != exclude_preset_id and preset.name.casefold() == lowered:
            return f'A preset named "{cleaned}" already exists.'
    return None


class SignaturePresetService:
    def __init__(self, storage_dir: Optional[str] = None) -> None:
        self._dir = storage_dir or user_app_data_path("signature_presets")
        self._assets_dir = os.path.join(self._dir, "assets")
        self._manifest = os.path.join(self._dir, "manifest.json")
        self._presets: list[SignaturePreset] = []
        self.load_warnings: list[str] = []
        self._load()

    def presets(self) -> list[SignaturePreset]:
        return list(self._presets)

    def get_preset(self, preset_id: str) -> Optional[SignaturePreset]:
        return next((p for p in self._presets if p.id == preset_id), None)

    def _load(self) -> None:
        self.load_warnings = []
        self._presets = []
        if not os.path.isfile(self._manifest):
            return
        try:
            with open(self._manifest, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            self.load_warnings.append(f"Could not read signature presets: {exc}")
            return
        records = payload.get("presets", []) if isinstance(payload, dict) else []
        if not isinstance(records, list):
            self.load_warnings.append("Signature preset manifest is invalid.")
            return
        for index, record in enumerate(records, start=1):
            preset = self._preset_from_record(record)
            if preset is None:
                self.load_warnings.append(f"Skipped corrupt signature preset entry #{index}.")
                continue
            self._presets.append(preset)

    def save_typed_preset(
        self,
        *,
        name: str,
        text: str,
        font_name: str,
        color: str,
    ) -> SignaturePreset:
        cleaned_name = " ".join(name.split())
        error = validate_preset_name(cleaned_name, self._presets)
        if error:
            raise ValueError(error)
        if not text.strip():
            raise ValueError("Typed signature presets need signature text.")
        if not font_name:
            raise ValueError("Typed signature presets need a signature font.")
        preset = SignaturePreset(
            name=cleaned_name,
            preset_type=SignaturePresetType.typed,
            text=text.strip(),
            font_name=font_name,
            color=color if color in SUPPORTED_COLORS else SUPPORTED_COLORS[0],
        )
        self._presets.append(preset)
        self._write_manifest()
        return preset

    def save_image_preset(
        self,
        *,
        name: str,
        source_image_path: str,
    ) -> SignaturePreset:
        cleaned_name = " ".join(name.split())
        error = validate_preset_name(cleaned_name, self._presets)
        if error:
            raise ValueError(error)
        validation_error = validate_image_path(source_image_path)
        if validation_error:
            raise ValueError(validation_error)
        reader = QImageReader(source_image_path)
        if not reader.canRead():
            raise ValueError(reader.errorString() or "Unsupported or unreadable image.")
        size = reader.size()
        preset_id = str(uuid.uuid4())
        _, ext = os.path.splitext(source_image_path)
        asset_filename = f"{preset_id}{ext.lower()}"
        os.makedirs(self._assets_dir, exist_ok=True)
        managed_path = os.path.join(self._assets_dir, asset_filename)
        shutil.copy2(source_image_path, managed_path)
        preset = SignaturePreset(
            id=preset_id,
            name=cleaned_name,
            preset_type=SignaturePresetType.image,
            asset_filename=asset_filename,
            resolved_image_path=managed_path,
            image_width=size.width() if size.isValid() else None,
            image_height=size.height() if size.isValid() else None,
        )
        self._presets.append(preset)
        self._write_manifest()
        return preset

    def rename_preset(self, preset_id: str, new_name: str) -> SignaturePreset:
        preset = self.get_preset(preset_id)
        if preset is None:
            raise ValueError("Preset not found.")
        cleaned_name = " ".join(new_name.split())
        error = validate_preset_name(cleaned_name, self._presets, exclude_preset_id=preset_id)
        if error:
            raise ValueError(error)
        preset.name = cleaned_name
        self._write_manifest()
        return preset

    def delete_preset(self, preset_id: str) -> None:
        preset = self.get_preset(preset_id)
        if preset is None:
            raise ValueError("Preset not found.")
        self._presets = [p for p in self._presets if p.id != preset_id]
        if preset.asset_filename:
            try:
                os.remove(os.path.join(self._assets_dir, preset.asset_filename))
            except OSError:
                pass
        self._write_manifest()

    def create_overlay(
        self,
        preset: SignaturePreset,
        *,
        page_index: int,
        rect_pdf: PdfRect,
    ) -> OverlayItem:
        if preset.preset_type == SignaturePresetType.typed:
            return OverlayItem(
                page_index=page_index,
                type=OverlayType.typed_signature,
                rect_pdf=rect_pdf,
                text=preset.text,
                font_name=preset.font_name,
                color=preset.color or SUPPORTED_COLORS[0],
            )
        image_path = preset.resolved_image_path
        if not image_path or not os.path.isfile(image_path):
            raise ValueError(preset.load_error or "This preset image is no longer available.")
        return OverlayItem(
            page_index=page_index,
            type=OverlayType.signature_image,
            rect_pdf=rect_pdf,
            image_path=image_path,
        )

    def _write_manifest(self) -> None:
        os.makedirs(self._assets_dir, exist_ok=True)
        payload = {
            "version": _MANIFEST_VERSION,
            "presets": [self._record_for_preset(p) for p in self._presets],
        }
        fd, tmp_path = tempfile.mkstemp(dir=self._dir, prefix="presets_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, self._manifest)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _preset_from_record(self, record: object) -> Optional[SignaturePreset]:
        if not isinstance(record, dict):
            return None
        try:
            preset_id, name = record["id"], record["name"]
            preset_type = SignaturePresetType(record["type"])
        except (KeyError, ValueError):
            return None
        if not isinstance(preset_id, str) or not isinstance(name, str):
            return None

        if preset_type == SignaturePresetType.typed:
            text = record.get("text")
            font_name = record.get("font_name")
            if not isinstance(text, str) or not isinstance(font_name, str):
                return None
            color = record.get("color")
            return SignaturePreset(
                id=preset_id,
                name=name,
                preset_type=preset_type,
                text=text,
                font_name=font_name,
                color=color if isinstance(color, str) else SUPPORTED_COLORS[0],
            )

        asset_filename = record.get("asset_filename")
        if not isinstance(asset_filename, str):
            return None
        image_path = os.path.join(self._assets_dir, asset_filename)
        available = os.path.isfile(image_path)
        return SignaturePreset(
            id=preset_id,
            name=name,
            preset_type=preset_type,
            asset_filename=asset_filename,
            resolved_image_path=image_path,
            image_width=self._safe_int(record.get("image_width")),
            image_height=self._safe_int(record.get("image_height")),
            is_available=available,
            load_error=None if available else "Preset image file is missing.",
        )

    @staticmethod
    def _safe_int(value: object) -> Optional[int]:
        return value if isinstance(value, int) and value > 0 else None

    def _record_for_preset(self, preset: SignaturePreset) -> dict[str, object]:
        record: dict[str, object] = {
            "id": preset.id,
            "name": preset.name,
            "type": preset.preset_type.value,
        }
        if preset.preset_type == SignaturePresetType.typed:
            record["text"] = preset.text or ""
            record["font_name"] = preset.font_name or ""
            record["color"] = preset.color or SUPPORTED_COLORS[0]
        else:
            record["asset_filename"] = preset.asset_filename or ""
            record["image_width"] = preset.image_width
            record["image_height"] = preset.image_height
        return record
