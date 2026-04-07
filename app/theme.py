from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette


@dataclass(frozen=True)
class ThemeColors:
    app_bg: str
    panel_bg: str
    toolbar_bg: str
    surface_bg: str
    workspace_bg: str
    text: str
    text_muted: str
    border: str
    active_fill: str
    active_border: str
    primary_bg: str
    primary_text: str
    quiet_bg: str
    danger_bg: str
    danger_text: str


@dataclass(frozen=True)
class ThemeSpacing:
    outer: int
    panel_padding: int
    section_gap: int
    field_gap: int
    compact_gap: int


@dataclass(frozen=True)
class ThemeRadii:
    control: int
    surface: int


@dataclass(frozen=True)
class ThemeSizes:
    toolbar_height: int
    control_height: int
    compact_control_height: int
    left_panel_width: int
    right_panel_width: int


@dataclass(frozen=True)
class ThemeTypography:
    family: str
    section_title_px: int
    body_px: int
    helper_px: int


@dataclass(frozen=True)
class ThemeTokens:
    colors: ThemeColors
    spacing: ThemeSpacing
    radii: ThemeRadii
    sizes: ThemeSizes
    typography: ThemeTypography


def build_palette(tokens: ThemeTokens) -> QPalette:
    colors = tokens.colors
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(colors.app_bg))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors.text))
    palette.setColor(QPalette.ColorRole.Base, QColor(colors.surface_bg))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors.panel_bg))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors.surface_bg))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colors.text))
    palette.setColor(QPalette.ColorRole.Text, QColor(colors.text))
    palette.setColor(QPalette.ColorRole.Button, QColor(colors.surface_bg))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors.text))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(colors.primary_text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(colors.active_fill))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(colors.text))
    return palette


def build_stylesheet(tokens: ThemeTokens) -> str:
    c = tokens.colors
    s = tokens.spacing
    r = tokens.radii
    z = tokens.sizes
    t = tokens.typography

    return f"""
QWidget {{
    color: {c.text};
    font-family: "{t.family}";
    font-size: {t.body_px}px;
    font-weight: 600;
}}

QMainWindow#mainWindow {{
    background: {c.app_bg};
}}

QWidget#centralShell {{
    background: {c.app_bg};
}}

QToolBar#mainToolbar {{
    background: {c.toolbar_bg};
    border: none;
    border-bottom: 1px solid {c.border};
    spacing: {s.compact_gap}px;
    padding: {s.compact_gap}px {s.outer}px;
    min-height: {z.toolbar_height}px;
}}

QToolBar#mainToolbar QToolButton {{
    background: {c.surface_bg};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {r.control}px;
    padding: 4px 10px;
    min-height: {z.compact_control_height}px;
    font-family: "{t.family}";
    font-size: {t.body_px}px;
}}

QToolBar#mainToolbar QToolButton:hover {{
    background: {c.active_fill};
    border-color: {c.active_border};
}}

QToolBar#mainToolbar QToolButton:pressed {{
    background: {c.panel_bg};
}}

QLabel#toolbarPageLabel, QLabel#toolbarZoomLabel {{
    color: {c.text};
    font-family: "{t.family}";
    font-size: {t.body_px}px;
    font-weight: 600;
    padding: 0 4px;
}}

QWidget#leftPanel, QWidget#rightPanel {{
    background: {c.panel_bg};
}}

QWidget#leftPanel {{
    border-right: 1px solid {c.border};
}}

QWidget#rightPanel {{
    border-left: 1px solid {c.border};
}}

QFrame#panelCard, QFrame#contextCard, QFrame#actionCard {{
    background: {c.surface_bg};
    border: 1px solid {c.border};
    border-radius: {r.surface}px;
}}

QLabel[role="sectionTitle"] {{
    color: {c.text};
    font-family: "{t.family}";
    font-size: {t.section_title_px}px;
    font-weight: 600;
}}

QLabel[role="subTitle"], QLabel[role="fieldLabel"] {{
    color: {c.text};
    font-family: "{t.family}";
    font-size: {t.body_px}px;
    font-weight: 500;
}}

QLabel[role="helper"] {{
    color: {c.text_muted};
    font-family: "{t.family}";
    font-size: {t.helper_px}px;
}}

QLineEdit, QComboBox {{
    background: {c.surface_bg};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {r.control}px;
    padding: 3px 8px;
    min-height: {z.control_height}px;
    font-family: "{t.family}";
    font-size: {t.body_px}px;
}}

QLineEdit:focus, QComboBox:focus {{
    border-color: {c.active_border};
    background: #FFFFFF;
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background: {c.surface_bg};
    color: {c.text};
    border: 1px solid {c.border};
    selection-background-color: {c.active_fill};
    selection-color: {c.text};
}}

QPushButton {{
    background: {c.quiet_bg};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {r.control}px;
    padding: 4px 10px;
    min-height: {z.control_height}px;
    font-family: "{t.family}";
    font-size: {t.body_px}px;
}}

QPushButton:hover {{
    background: {c.active_fill};
    border-color: {c.active_border};
}}

QPushButton:pressed {{
    background: {c.panel_bg};
}}

QPushButton:disabled {{
    color: {c.text_muted};
    background: {c.panel_bg};
    border-color: {c.border};
}}

QPushButton[role="tool"] {{
    text-align: left;
    background: {c.surface_bg};
    font-weight: 600;
}}

QPushButton[role="tool"]:checked {{
    background: {c.active_fill};
    border-color: {c.active_border};
}}

QPushButton[role="primary"] {{
    background: {c.primary_bg};
    color: {c.primary_text};
    border-color: {c.primary_bg};
    font-weight: 600;
}}

QPushButton[role="primary"]:hover {{
    background: #645F59;
    border-color: #645F59;
}}

QPushButton[role="danger"] {{
    background: {c.danger_bg};
    color: {c.danger_text};
    border-color: {c.border};
}}

QPushButton[role="danger"]:hover {{
    background: {c.active_fill};
    border-color: {c.active_border};
}}

QPushButton[role="danger"]:pressed {{
    background: {c.panel_bg};
    border-color: {c.active_border};
}}

QListWidget#pageList {{
    background: {c.surface_bg};
    border: 1px solid {c.border};
    border-radius: {r.surface}px;
    font-family: "{t.family}";
    font-size: {t.helper_px}px;
    color: {c.text};
    padding: {s.compact_gap}px;
}}

QListWidget#pageList::item {{
    border: 1px solid transparent;
    border-radius: {r.control}px;
    padding: 4px;
    margin: 2px 0;
}}

QListWidget#pageList::item:selected {{
    background: {c.active_fill};
    border-color: {c.active_border};
    color: {c.text};
}}

QGraphicsView#pdfViewer {{
    background: {c.workspace_bg};
    border: 1px solid {c.border};
    border-radius: {r.surface}px;
}}

QStatusBar {{
    background: {c.toolbar_bg};
    color: {c.text_muted};
    border-top: 1px solid {c.border};
    font-family: "{t.family}";
    font-size: {t.helper_px}px;
}}

QStatusBar::item {{
    border: none;
}}

QDialog#editOverlayDialog {{
    background: {c.surface_bg};
}}

QDialog#editOverlayDialog QLabel {{
    color: {c.text};
    font-family: "{t.family}";
    font-size: {t.body_px}px;
}}
"""
