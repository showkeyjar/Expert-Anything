"""Shared helper functions for UI widgets.

Extracted from pyside_widgets.py so that widget submodules can import
these utilities without pulling in the entire monolith.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from expert_anything.core.i18n import t as _t
from expert_anything.ui import theme

# QtSvg is an optional component; when it is missing the scene previews simply
# do not render (callers skip).  Keep the import guarded so the rest of the
# helpers stay usable in minimal environments.
try:
    from PySide6.QtCore import QByteArray, QSize
    from PySide6.QtSvgWidgets import QSvgWidget

    _HAS_SVG = True
except Exception:  # pragma: no cover - headless/minimal installs
    QSvgWidget = None  # type: ignore[assignment]
    _HAS_SVG = False

# --------------------------------------------------------------------------- #
# colour palette (consistent with pyside_graph / core.graph_viz)
# --------------------------------------------------------------------------- #
MASTERY_COLORS = {
    "mastered": "#4CAF50",
    "partial": "#FF9800",
    "weak": "#F44336",
    "unstudied": "#9E9E9E",
}


def _tag_label(tag: str) -> str:
    """Translated tag label -- looked up at render time so language switches
    take effect immediately (module-level _t() would freeze the first lang)."""
    # Dynamic tags with numeric suffix
    if tag.startswith("unblock:"):
        try:
            n = int(tag.split(":", 1)[1])
            return _t("tag_unblock_n", n=n)
        except (ValueError, IndexError):
            pass
    return {
        "weak": _t("legend_weak"),
        "anom": _t("legend_anomaly"),
        "foundation": _t("legend_unstudied"),
        "ready": _t("legend_mastered"),
        "blocked": _t("legend_learning"),
        "path": _t("legend_focus"),
        "stuck": _t("tag_stuck"),
        "high_leverage": _t("tag_high_leverage"),
        "prereq_shaky": _t("legend_weak"),
        "unblock_stuck": _t("tag_stuck"),
    }.get(tag, tag)


def mastery_level(m: float) -> str:
    if m >= 0.6:
        return "mastered"
    if m >= 0.3:
        return "partial"
    if m > 0:
        return "weak"
    return "unstudied"


def mastery_color(m: float) -> str:
    return MASTERY_COLORS[mastery_level(m)]


def tag_chip(text: str, color: str = theme.ACCENT) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"background-color: {theme.rgba(color)}; color: {color};"
        "padding: 2px 8px; border-radius: 6px; font-size: 11.5px;"
    )
    return lbl


def _sec_title(text: str, color: str = theme.TEXT) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-size: 14px; font-weight: 600; color: {color}; margin-top: 6px;"
    )
    return lbl


class CollapsibleSection(QWidget):
    """A 「更多」 disclosure section: toggle button + hidden body.

    First screens keep 2-3 core blocks; secondary content lives behind this
    fold (hidden, never removed — every capability stays one click away).
    Mirrors the learner view's analysis fold (AGENTS.md §49), generalised so
    every view can ship a quiet first screen.
    """

    def __init__(self, title: str, hint: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._title = str(title)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._toggle = QPushButton()
        self._toggle.setCheckable(True)
        self._toggle.setChecked(False)
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.setStyleSheet(
            f"QPushButton {{ background-color: transparent;"
            f" color: {theme.TEXT_MUTED}; border: none; text-align: left;"
            " padding: 6px 2px; font-size: 12.5px; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {theme.ACCENT}; }}"
        )
        if hint:
            self._toggle.setToolTip(str(hint))
        self._toggle.toggled.connect(self._on_toggled)
        lay.addWidget(self._toggle)
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(10)
        self._body.setVisible(False)
        lay.addWidget(self._body)
        self._refresh_label()

    def body_layout(self) -> QVBoxLayout:
        return self._body_lay

    def add(self, widget: QWidget) -> None:
        self._body_lay.addWidget(widget)

    def set_expanded(self, on: bool) -> None:
        self._toggle.setChecked(bool(on))

    def is_expanded(self) -> bool:
        return self._toggle.isChecked()

    def _on_toggled(self, on: bool) -> None:
        self._body.setVisible(on)
        self._refresh_label()

    def _refresh_label(self) -> None:
        arrow = "▾" if self._toggle.isChecked() else "▸"
        self._toggle.setText(f"{arrow} {self._title}")


# --------------------------------------------------------------------------- #
# Decoder scene previews (aspect-safe + click-to-zoom)
# --------------------------------------------------------------------------- #
if _HAS_SVG:

    class SvgZoomDialog(QDialog):
        """Full-size view of a decoder scene — the click target of previews.

        Renders at (or above) the scene's native viewBox resolution so labels
        keep their designed font size; the scene scrolls when it exceeds the
        window instead of being shrunk back into illegibility.
        """

        def __init__(self, svg_data: str, title: str = "", parent: QWidget | None = None):
            super().__init__(parent)
            self.setObjectName("svg_zoom_dialog")
            self.setWindowTitle(title or _t("svg_zoom_title"))
            lay = QVBoxLayout(self)
            lay.setContentsMargins(10, 10, 10, 10)
            lay.setSpacing(8)
            scroll = QScrollArea()
            scroll.setWidgetResizable(False)  # native size; scrollbars when larger
            wgt = QSvgWidget()
            wgt.load(QByteArray(svg_data.encode("utf-8")))
            wgt.renderer().setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            vb = wgt.renderer().viewBox()
            vw, vh = vb.width(), vb.height()
            # native viewBox scale, with a floor so narrow scenes stay readable
            w = max(int(vw), 520)
            h = int(w * vh / vw) if vw > 0 else 360
            wgt.setFixedSize(w, h)
            scroll.setWidget(wgt)
            lay.addWidget(scroll, 1)
            box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            box.rejected.connect(self.reject)
            lay.addWidget(box)
            self.resize(min(w + 32, 1080), min(h + 92, 740))

    class SvgScenePreview(QSvgWidget):
        """Decoder-scene preview that cannot squash its text.

        Three guarantees over a bare ``QSvgWidget``:
        1. aspect ratio preserved — ``QSvgRenderer`` defaults to
           ``IgnoreAspectRatio``, which is what flattened every label when the
           layout forced the scene into a fixed-height box;
        2. height follows width (``heightForWidth``) — the layout can never
           squeeze the scene vertically again;
        3. click opens :class:`SvgZoomDialog` at native resolution, the
           actually-readable view (effective minimum font = the scene's own
           designed sizes, never scaled below 1.0).
        """

        def __init__(self, parent: QWidget | None = None):
            super().__init__(parent)
            self._svg_text = ""
            self._aspect = 0.0
            self._zoom_title = ""
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip(_t("svg_zoom_tip"))
            sp = self.sizePolicy()
            sp.setHeightForWidth(True)
            sp.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
            sp.setVerticalPolicy(QSizePolicy.Policy.Minimum)
            self.setSizePolicy(sp)

        def load_svg(self, svg_text: str, zoom_title: str = "") -> bool:
            """Load SVG markup; returns False when the markup is invalid."""
            self._svg_text = svg_text or ""
            self._zoom_title = zoom_title
            self.load(QByteArray(self._svg_text.encode("utf-8")))
            r = self.renderer()
            r.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            vb = r.viewBox()
            self._aspect = (vb.width() / vb.height()) if vb.height() > 0 else 0.0
            self.updateGeometry()
            return r.isValid()

        def hasHeightForWidth(self) -> bool:
            return self._aspect > 0

        def heightForWidth(self, w: int) -> int:
            if self._aspect <= 0:
                return 160
            # floor: never collapse into a degenerate strip
            return max(120, int(w / self._aspect))

        def sizeHint(self) -> QSize:
            if self._aspect > 0:
                w = 480
                return QSize(w, int(w / self._aspect))
            return super().sizeHint()

        def mouseReleaseEvent(self, event) -> None:
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._svg_text
            ):
                SvgZoomDialog(self._svg_text, self._zoom_title, self).exec()
                event.accept()
                return
            super().mouseReleaseEvent(event)

else:  # pragma: no cover - QtSvg unavailable
    SvgZoomDialog = None  # type: ignore[assignment]
    SvgScenePreview = None  # type: ignore[assignment]


def open_note_editor(parent, learner_state: dict, concept_name: str) -> str | None:
    """Modal own-words note editor at any learning site.

    Writing an explanation in your own words is the cheapest strong
    comprehension check (generation effect), so the editor is reachable from
    the lesson page and the reader — not only from the map card.
    Returns the saved note text, or None when the learner cancelled.
    """
    from expert_anything.core.learner import get_note, set_note, save as save_learner

    dlg = QDialog(parent)
    dlg.setWindowTitle(_t("note_dialog_title", name=concept_name))
    dlg.setMinimumWidth(420)
    lay = QVBoxLayout(dlg)
    hint = QLabel(_t("note_hint"))
    hint.setWordWrap(True)
    hint.setStyleSheet("font-size: 13px; color: #6B7A90;")
    lay.addWidget(hint)
    editor = QPlainTextEdit(get_note(learner_state, concept_name))
    editor.setObjectName("note_editor")
    editor.setMinimumHeight(160)
    editor.setStyleSheet("font-size: 14px;")
    lay.addWidget(editor)
    btns = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save
        | QDialogButtonBox.StandardButton.Cancel
    )
    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)
    lay.addWidget(btns)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    set_note(learner_state, concept_name, editor.toPlainText())
    save_learner(learner_state)
    return get_note(learner_state, concept_name)


def open_feynman_check(parent, learner_state, asset, concept) -> None:
    """Modal own-words recall check on the concept (deterministic coverage).

    Active recall ("explain it back") is the strongest comprehension check, so
    it lives at the learning sites (lesson page, reader) next to the note.  The
    comparison is entirely deterministic (``core.feynman.coverage``): no LLM,
    nothing invented.  No-ops when the asset/concept is unavailable.
    """
    if asset is None or concept is None:
        return

    from expert_anything.ui.widgets.feynman import FeynmanDialog

    dlg = FeynmanDialog(asset, concept, learner_state, parent)
    dlg.exec()
