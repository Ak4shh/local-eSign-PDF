from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QCoreApplication, QSettings

from app.settings import APP_NAME

RECENT_FILES_MAX = 8
ZOOM_MODE_CUSTOM = "custom"
ZOOM_MODE_FIT = "fit"


def _normalize_pdf_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _is_valid_pdf_path(path: str, require_exists: bool = True) -> bool:
    if not path:
        return False
    normalized = _normalize_pdf_path(path)
    if not normalized.lower().endswith(".pdf"):
        return False
    return os.path.isfile(normalized) if require_exists else True


class AppPersistence:
    def __init__(self) -> None:
        organization = QCoreApplication.organizationName() or APP_NAME
        application = QCoreApplication.applicationName() or APP_NAME
        self._settings = QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            organization,
            application,
        )

    def restore_window_geometry(self, window) -> None:
        geometry = self._settings.value("window/geometry")
        if geometry:
            window.restoreGeometry(geometry)

    def save_window_geometry(self, window) -> None:
        self._settings.setValue("window/geometry", window.saveGeometry())
        self._settings.sync()

    def recent_files(self) -> list[str]:
        raw = self._settings.value("files/recent", [], type=list)
        cleaned: list[str] = []
        seen: set[str] = set()
        for path in raw:
            if not isinstance(path, str) or not _is_valid_pdf_path(path):
                continue
            normalized = _normalize_pdf_path(path)
            if normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(normalized)
            if len(cleaned) >= RECENT_FILES_MAX:
                break
        if cleaned != raw:
            self._settings.setValue("files/recent", cleaned)
            self._settings.sync()
        return cleaned

    def add_recent_file(self, path: str) -> list[str]:
        if not _is_valid_pdf_path(path):
            return self.recent_files()
        normalized = _normalize_pdf_path(path)
        recent = [entry for entry in self.recent_files() if entry != normalized]
        recent.insert(0, normalized)
        recent = recent[:RECENT_FILES_MAX]
        self._settings.setValue("files/recent", recent)
        self._settings.sync()
        return recent

    def remove_recent_file(self, path: str) -> list[str]:
        normalized = _normalize_pdf_path(path)
        recent = [entry for entry in self.recent_files() if entry != normalized]
        self._settings.setValue("files/recent", recent)
        self._settings.sync()
        return recent

    def last_open_dir(self) -> str:
        path = self._settings.value("files/last_open_dir", "", type=str)
        return path if path and os.path.isdir(path) else ""

    def set_last_open_dir(self, path: str) -> None:
        if path and os.path.isdir(path):
            self._settings.setValue("files/last_open_dir", path)
            self._settings.sync()

    def last_save_dir(self) -> str:
        path = self._settings.value("files/last_save_dir", "", type=str)
        return path if path and os.path.isdir(path) else ""

    def set_last_save_dir(self, path: str) -> None:
        if path and os.path.isdir(path):
            self._settings.setValue("files/last_save_dir", path)
            self._settings.sync()

    def zoom_preference(self) -> tuple[str, float]:
        mode = self._settings.value("view/zoom_mode", ZOOM_MODE_FIT, type=str)
        value = self._settings.value("view/zoom_value", 1.0, type=float)
        if mode not in (ZOOM_MODE_CUSTOM, ZOOM_MODE_FIT):
            mode = ZOOM_MODE_FIT
        return mode, float(value)

    def set_zoom_preference(self, mode: str, value: float) -> None:
        if mode not in (ZOOM_MODE_CUSTOM, ZOOM_MODE_FIT):
            mode = ZOOM_MODE_FIT
        self._settings.setValue("view/zoom_mode", mode)
        self._settings.setValue("view/zoom_value", float(value))
        self._settings.sync()

    def tool_inputs(self) -> dict[str, Any]:
        return {
            "signature_text": self._settings.value("inputs/signature_text", "", type=str),
            "name_text": self._settings.value("inputs/name_text", "", type=str),
            "date_text": self._settings.value("inputs/date_text", "", type=str),
            "font_name": self._settings.value("inputs/font_name", "", type=str),
            "color": self._settings.value("inputs/color", "", type=str),
        }

    def save_tool_inputs(
        self,
        *,
        signature_text: str,
        name_text: str,
        date_text: str,
        font_name: str,
        color: str,
    ) -> None:
        self._settings.setValue("inputs/signature_text", signature_text)
        self._settings.setValue("inputs/name_text", name_text)
        self._settings.setValue("inputs/date_text", date_text)
        self._settings.setValue("inputs/font_name", font_name)
        self._settings.setValue("inputs/color", color)
        self._settings.sync()
