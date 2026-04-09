from __future__ import annotations

import os
import sys

from PySide6.QtCore import QCoreApplication, QStandardPaths


def app_root() -> str:
    """Return app root path for both source runs and PyInstaller bundles."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return str(sys._MEIPASS)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    return os.path.join(app_root(), *parts)


def user_app_data_path(*parts: str) -> str:
    base_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    if not base_dir:
        app_name = QCoreApplication.applicationName() or "PDF eSign"
        local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        base_dir = os.path.join(local_app_data, app_name)
    return os.path.join(base_dir, *parts)
