# -*- mode: python ; coding: utf-8 -*-
#
# One-folder release build for PDF eSign.
#
# Strategy
# --------
# • EXE(exclude_binaries=True) + COLLECT() → one-folder layout.
#   The exe is small; all DLLs/assets live beside it.  No extraction at
#   launch — cold-start time drops significantly vs. the old one-file build.
#
# • collect_all("PySide6") is intentionally avoided.  PyInstaller's static
#   analysis finds the Qt DLLs we actually depend on via import tracing.
#   We only add Qt *plugins* explicitly (platforms, imageformats, styles)
#   because those are never reached by import analysis.
#
# • collect_all("pymupdf") / collect_all("fitz") are replaced with
#   collect_data_files() so we get the data resources without dragging in
#   the entire optional-dependency graph (pandas, numpy, lxml …).
#
# • Unused packages are explicitly excluded to shrink the bundle further.

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ── PyMuPDF data files (fonts, ICC profiles, etc.) ──────────────────────────
# collect_data_files does NOT chase package dependencies, so pandas/numpy
# are not pulled in here.
pymupdf_datas = collect_data_files("pymupdf")
fitz_datas    = collect_data_files("fitz")

# ── PySide6 Qt plugins (not auto-detected from imports) ─────────────────────
# Only the plugin subdirs this application actually needs.
pyside6_plugin_datas = collect_data_files(
    "PySide6",
    includes=[
        # Window system integration
        "plugins/platforms/qwindows.dll",
        # Image format plugins used by the viewer and signature rendering
        "plugins/imageformats/qjpeg.dll",
        "plugins/imageformats/qpng.dll",
        "plugins/imageformats/qbmp.dll",
        "plugins/imageformats/qgif.dll",
        "plugins/imageformats/qtiff.dll",
        "plugins/imageformats/qwebp.dll",
        "plugins/imageformats/qsvg.dll",
        "plugins/imageformats/qico.dll",
        # Native-look style (Fusion style is built-in; Vista style is a plugin)
        "plugins/styles/qwindowsvistastyle.dll",
    ],
)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=(
        pymupdf_datas
        + fitz_datas
        + pyside6_plugin_datas
        + [
            ("assets", "assets"),
            ("SVGs", "SVGs"),
        ]
    ),
    hiddenimports=(
        collect_submodules("fitz")
        + collect_submodules("pymupdf")
        + [
            "pymupdf",
            "fitz",
            "html",
            "shiboken6",
            "PySide6.QtCore",
            "PySide6.QtGui",
            "PySide6.QtWidgets",
            "PySide6.QtSvg",
            "PySide6.QtPrintSupport",
        ]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["runtime_hook_startup.py"],
    excludes=[
        # ── Unused Qt modules ────────────────────────────────────────────────
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtBluetooth",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "PySide6.QtLocation",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtNfc",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
        "PySide6.QtPositioning",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtQuickControls2",
        "PySide6.QtQuickWidgets",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSpatialAudio",
        "PySide6.QtTextToSpeech",
        "PySide6.QtUiTools",
        "PySide6.QtVirtualKeyboard",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
        "PySide6.QtXml",
        # ── Data-science / heavy optional stacks ─────────────────────────────
        # PyMuPDF lists these as optional extras; we don't use them.
        "pandas",
        "pandas.core",
        "numpy",
        "numpy.core",
        "numpy.libs",
        "lxml",
        "lxml.etree",
        "PIL",
        "Pillow",
        "pytz",
        "dateutil",
        "charset_normalizer",
        "yaml",
        "setuptools",
        "pkg_resources",
        # ── Unused stdlib extras ──────────────────────────────────────────────
        "tkinter",
        "unittest",
        "xmlrpc",
        "pydoc",
        "doctest",
        "difflib",
        "ftplib",
        "imaplib",
        "poplib",
        "smtplib",
        "telnetlib",
        "test",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ── Single-file EXE ──────────────────────────────────────────────────────────
# All binaries, datas, and the Python runtime DLL are embedded inside the
# .exe and extracted to %TEMP%\_MEIxxxxxx at launch.  The extraction payload
# is kept small by the aggressive excludes above, which cuts extraction time.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,      # ← embed all native DLLs (Qt, mupdfcpp64.dll, python3.dll …)
    a.datas,         # ← embed assets, Qt plugins, fonts, SVGs
    [],
    name="PDF-eSign",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,       # UPX can corrupt Qt/MuPDF DLLs — keep off for reliability
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
