"""Single source of truth for the desktop visual language.

Before this module every widget carried its own hex codes: a deep-navy
sidebar, Material-blue underlines on every page header, three different
greys for borders.  The result read as a 2016 desktop tool rather than a
calm reading surface.  Tokens live here so the shell, headers and dialogs
share one palette instead of drifting apart again.

Usage
-----
``apply_theme(app)`` is called once from ``MainWindow.setup_ui`` (idempotent)
and sets the Fusion style, palette, app font and base control QSS.  Widgets
that need specialised styling import the tokens directly.

Rules
-----
- No colour literals in shell/header code; import from here.
- Semantic names only (``TEXT`` not ``GREY_1``) so dark mode stays possible.
- Qt stylesheet strings are built with ``.format``-free f-strings on purpose:
  QSS uses ``{}`` blocks, so tokens are interpolated as plain names.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette

# --------------------------------------------------------------------------- #
# tokens
# --------------------------------------------------------------------------- #

# Surfaces ---------------------------------------------------------------- #
BG = "#F6F7F9"            # app canvas behind cards
SURFACE = "#FFFFFF"       # cards, sidebar, topbar
SURFACE_MUTED = "#FAFBFC"
SURFACE_HOVER = "#F3F4F6"

# Lines ------------------------------------------------------------------- #
BORDER = "#E5E7EB"
BORDER_STRONG = "#D8DDE4"
DIVIDER = "#EEF0F3"

# Ink --------------------------------------------------------------------- #
TEXT = "#111827"
TEXT_MUTED = "#6B7280"
TEXT_FAINT = "#9CA3AF"
TEXT_ON_ACCENT = "#FFFFFF"

# Accent ------------------------------------------------------------------ #
ACCENT = "#2563EB"
ACCENT_HOVER = "#1D4ED8"
ACCENT_TINT = "#EFF6FF"
ACCENT_TINT_STRONG = "#DBEAFE"
ACCENT_SOFT = "#BFDBFE"

# Semantics --------------------------------------------------------------- #
SUCCESS = "#16A34A"
SUCCESS_TINT = "#F0FDF4"
WARNING = "#D97706"
WARNING_TINT = "#FFFBEB"
DANGER = "#DC2626"
DANGER_TINT = "#FEF2F2"

# Geometry ---------------------------------------------------------------- #
RADIUS_SM = 6
RADIUS_MD = 8
RADIUS_LG = 12
SIDEBAR_WIDTH = 244
TOPBAR_HEIGHT = 56

# Type -------------------------------------------------------------------- #
FONT_FAMILIES = [
    "Segoe UI",
    "Microsoft YaHei UI",
    "PingFang SC",
    "Noto Sans CJK SC",
]
FONT_POINT_SIZE = 10.5

_APPLIED = False


def rgba(hex_color: str, alpha: float = 0.12) -> str:
    """QSS-safe tint for a token colour.

    Qt reads ``#RRGGBBAA`` as ``#AARRGGBB``; the old ``{color}20`` idiom
    therefore painted a random green.  Use explicit rgba() instead.
    """
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return hex_color
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


# --------------------------------------------------------------------------- #
# app-wide setup
# --------------------------------------------------------------------------- #


def _palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(BG))
    p.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_MUTED))
    p.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Button, QColor(SURFACE))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(TEXT))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#FFFFFF"))
    p.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT_ON_ACCENT))
    p.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_FAINT))
    return p


def app_stylesheet() -> str:
    """Base control styling.  Widget-level stylesheets still win, which keeps
    the redesign incremental instead of a flag day."""
    return f"""
    QToolTip {{
        background-color: {TEXT};
        color: #FFFFFF;
        border: none;
        padding: 5px 8px;
        border-radius: 6px;
        font-size: 12.5px;
    }}
    QComboBox {{
        background-color: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_MD}px;
        padding: 4px 10px;
        min-height: 22px;
    }}
    QComboBox:hover {{ border-color: {BORDER_STRONG}; }}
    QComboBox:focus {{ border-color: {ACCENT}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background-color: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_SM}px;
        selection-background-color: {ACCENT_TINT};
        selection-color: {ACCENT_HOVER};
        outline: 0;
    }}
    QLineEdit, QPlainTextEdit, QTextEdit {{
        background-color: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: {RADIUS_MD}px;
        padding: 5px 10px;
        selection-background-color: {ACCENT_TINT_STRONG};
        selection-color: {TEXT};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border-color: {ACCENT};
    }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER_STRONG}; border-radius: 4px; min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {TEXT_FAINT}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent; height: 10px; margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {BORDER_STRONG}; border-radius: 4px; min-width: 28px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {TEXT_FAINT}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
    QSplitter::handle {{ background: {DIVIDER}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{
        background: transparent; color: {TEXT_MUTED}; border: none;
        padding: 7px 14px;
    }}
    QTabBar::tab:selected {{ color: {TEXT}; font-weight: 600; }}
    QTabBar::tab:hover {{ color: {TEXT}; }}
    """


def apply_theme(app) -> None:
    """Apply the shared visual language to the QApplication (idempotent)."""
    global _APPLIED
    if app is None:
        return
    from PySide6.QtWidgets import QStyleFactory

    style = QStyleFactory.create("Fusion")
    if style is not None:
        app.setStyle(style)
    app.setPalette(_palette())

    font = QFont()
    font.setFamilies(FONT_FAMILIES)
    font.setPointSizeF(FONT_POINT_SIZE)
    app.setFont(font)

    if not _APPLIED:
        app.setStyleSheet(app_stylesheet())
        _APPLIED = True


# --------------------------------------------------------------------------- #
# small style builders used by the shell and shared widgets
# --------------------------------------------------------------------------- #


def page_header_style() -> str:
    return (
        f"QFrame#page_header {{ background-color: {SURFACE};"
        f" border: none; border-bottom: 1px solid {DIVIDER}; }}"
    )


def primary_button_style(compact: bool = False) -> str:
    pad = "6px 14px" if compact else "8px 18px"
    return (
        f"QPushButton {{ background-color: {ACCENT}; color: {TEXT_ON_ACCENT};"
        f" border: none; border-radius: {RADIUS_MD}px; padding: {pad};"
        " font-size: 13.5px; font-weight: 600; }}"
        f"QPushButton:hover {{ background-color: {ACCENT_HOVER}; }}"
        f"QPushButton:disabled {{ background-color: {ACCENT_SOFT};"
        f" color: {SURFACE}; }}"
    )


def secondary_button_style() -> str:
    return (
        f"QPushButton {{ background-color: {SURFACE}; color: {TEXT};"
        f" border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px;"
        " padding: 7px 14px; font-size: 13.5px; }}"
        f"QPushButton:hover {{ background-color: {SURFACE_HOVER};"
        f" border-color: {BORDER_STRONG}; }}"
    )
