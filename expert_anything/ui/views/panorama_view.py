"""Project panorama — cross-material sensemaking.

A deterministic projection of data the system already holds: the merged
concept graph, each material's teacher-model anomalies, evidence-anchor
coverage, and learner mastery.  Nothing on this page is newly inferred — it
answers "what is this project made of, where does it stall, and what is still
unverified?" by aggregating existing truth sources across materials.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from expert_anything.core.learner import normalize
from expert_anything.core.teacher import kind_label
from expert_anything.ui.widgets._helpers import CollapsibleSection
from expert_anything.ui import theme
from expert_anything.ui.widgets.shared import PageHeader

# Severity order: high > medium > low > info, unknown sorts last.
_SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


class _ScaleChip(QPushButton):
    """A statistic chip that drills down.

    These chips used to be plain frames showing a bare number: the page
    invited a click and then did nothing.  A count the learner cannot act on
    is a dead end, so each chip now carries an action (switch to the graph,
    open the shared-concept list, scroll to a card) and says so in its
    tooltip.
    """

    def __init__(self, value, label, tip, parent=None):
        super().__init__(parent)
        self.setObjectName("scale_chip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(str(tip))
        self.setMinimumWidth(96)
        self.setMinimumHeight(58)
        self.setStyleSheet(
            f"QPushButton#scale_chip {{ background-color: {theme.SURFACE_MUTED};"
            " border: none; border-radius: 8px; text-align: left; }"
            f"QPushButton#scale_chip:hover {{ background-color: {theme.ACCENT_TINT}; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        v = QLabel(str(value))
        v.setStyleSheet(
            f"font-size: 20px; font-weight: 600; color: {theme.TEXT};"
        )
        k = QLabel(str(label))
        k.setStyleSheet(f"font-size: 12px; color: {theme.TEXT_MUTED};")
        lay.addWidget(v)
        lay.addWidget(k)


class PanoramaView(QWidget):
    """View 8 — project-wide panorama across all materials."""

    asset_switch_requested = Signal(str)       # asset_id
    concept_jump_requested = Signal(str, str)  # asset_id, concept_name
    view_switch_requested = Signal(str)        # view name (e.g. "concept_map")

    def __init__(self, main, parent=None):
        super().__init__(parent)
        self._main = main
        self._build()

    def refresh(self):
        self._rebuild()

    def _rebuild(self):
        layout = self.layout()
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._do_build()

    def _build(self):
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)
        self._do_build()

    # -- construction --------------------------------------------------------
    def _do_build(self):
        self._root_layout.addWidget(
            self._header(
                self._main._t("nav_panorama"),
                self._main._t("panorama_subtitle"),
            )
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(20, 16, 20, 20)
        v.setSpacing(12)

        data = self._collect()
        v.addWidget(self._explain())
        v.addWidget(self._scale_card(data))
        self._unknowns_widget = self._unknowns_card(data)
        v.addWidget(self._unknowns_widget)
        # First screen = 项目规模 + 待解存疑; the materials list and the
        # learning-frontier board sit behind the 「更多」 fold so the page
        # leads with three answers, not five boxes.
        self._more_section = CollapsibleSection(self._main._t("more_section"))
        self._materials_widget = self._materials_card(data)
        self._more_section.add(self._materials_widget)
        self._more_section.add(self._frontier_card(data))
        v.addWidget(self._more_section)
        v.addStretch()
        scroll.setWidget(host)
        self._root_layout.addWidget(scroll, 1)
        # Kept so a statistic chip can scroll the page to the card it
        # summarises (a chip that only shows a number is a dead end).
        self._scroll = scroll

    def _header(self, title, subtitle=""):
        return PageHeader(title, subtitle)

    def _explain(self):
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background-color: {theme.SURFACE};"
            f" border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_MD}px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        t = QLabel(self._main._t("panorama_explain_title"))
        t.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {theme.ACCENT_HOVER};"
        )
        lay.addWidget(t)
        b = QLabel(self._main._t("panorama_explain_body"))
        b.setWordWrap(True)
        b.setStyleSheet(f"font-size: 13px; color: {theme.TEXT_MUTED};")
        lay.addWidget(b)
        return frame

    def _card(self, title, color=theme.ACCENT):
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {theme.SURFACE};"
            f" border: 1px solid {theme.BORDER};"
            f" border-radius: {theme.RADIUS_LG}px; }}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        t = QLabel(str(title))
        t.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {color};")
        lay.addWidget(t)
        return card, lay

    def _muted(self, text, color=theme.TEXT_FAINT):
        lbl = QLabel(str(text))
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"font-size: 13px; color: {color};")
        return lbl

    def _subtitle(self, text, color=theme.TEXT_MUTED):
        lbl = QLabel(str(text))
        lbl.setStyleSheet(f"font-size: 13.5px; font-weight: 600; color: {color};")
        return lbl

    def _link_btn(self, text, color=theme.ACCENT):
        btn = QPushButton(str(text))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: transparent; color: {color};"
            " text-align: left; padding: 3px 6px; border: none;"
            " border-radius: 6px; font-size: 13px; }"
            f"QPushButton:hover {{ background-color: {theme.ACCENT_TINT}; }}"
        )
        return btn

    # -- data collection -----------------------------------------------------
    def _collect(self) -> dict:
        m = self._main
        assets = m.assets or {}
        teachers = m.teacher_models or {}
        norm_assets: dict[str, set] = {}
        shared_map: dict[str, dict] = {}
        materials: list[dict] = []
        unanchored: list[dict] = []
        unknowns: list[dict] = []
        relations_total = 0

        for aid, data in assets.items():
            try:
                asset = m._dict_to_asset(aid, data)
            except Exception:
                continue
            title = data.get("title") or data.get("source_name") or aid
            concepts = asset.concepts
            anchored = [c for c in concepts if getattr(c, "locations", None)]
            rate = (len(anchored) / len(concepts)) if concepts else 0.0
            tdict = teachers.get(aid) or {}
            relations_total += len(asset.relations)
            materials.append(
                dict(
                    aid=aid,
                    title=title,
                    count=len(concepts),
                    rate=rate,
                    status=tdict.get("status", ""),
                )
            )
            for c in concepts:
                key = normalize(c.name)
                if key:
                    norm_assets.setdefault(key, set()).add(aid)
                    entry = shared_map.setdefault(key, {"name": c.name, "aids": []})
                    if aid not in entry["aids"]:
                        entry["aids"].append(aid)
                if not getattr(c, "locations", None):
                    unanchored.append(dict(aid=aid, title=title, name=c.name))
            for an in tdict.get("anomalies", []) or []:
                desc = an.get("description", "") or ""
                loc = an.get("location", "") or ""
                name = ""
                for c in concepts:
                    if c.name and (c.name in desc or c.name in loc):
                        name = c.name
                        break
                unknowns.append(
                    dict(
                        aid=aid,
                        title=title,
                        kind=an.get("kind", "?"),
                        sev=an.get("severity", "medium"),
                        desc=desc,
                        name=name,
                    )
                )

        shared = sum(1 for ids in norm_assets.values() if len(ids) > 1)
        # The shared-concept chip drills into a real list, so the count has to
        # come with the names and the materials they bridge.
        aid_titles = {mt["aid"]: mt["title"] for mt in materials}
        shared_list = [
            dict(
                name=e["name"],
                assets=[(a, aid_titles.get(a, a)) for a in e["aids"]],
            )
            for _key, e in shared_map.items()
            if len(e["aids"]) > 1
        ]
        shared_list.sort(key=lambda s: (-len(s["assets"]), s["name"]))
        unknowns.sort(key=lambda a: _SEV_ORDER.get(a["sev"], 9))

        weak: list[dict] = []
        for key, rec in (m.learner.get("concepts", {}) or {}).items():
            try:
                mv = float(rec.get("mastery", 0.0))
            except Exception:
                mv = 0.0
            if 0.0 < mv < 0.6:
                srcs = rec.get("sources") or []
                weak.append(
                    dict(
                        name=rec.get("name", key),
                        pct=mv,
                        aid=(srcs[0] if srcs else ""),
                    )
                )
        weak.sort(key=lambda w: w["pct"])

        return dict(
            n_assets=len(assets),
            union=len(norm_assets),
            relations=relations_total,
            shared=shared,
            shared_list=shared_list,
            unknowns=unknowns,
            materials=materials,
            unanchored=unanchored,
            weak=weak,
        )

    # -- sections ------------------------------------------------------------
    def _scale_card(self, data):
        card, lay = self._card(self._main._t("panorama_scale_title"))
        row = QHBoxLayout()
        row.setSpacing(10)
        chips = [
            (
                self._main._t("stat_assets"),
                data["n_assets"],
                self._main._t("panorama_chip_tip_assets"),
                lambda: self._scroll_to(getattr(self, "_materials_widget", None)),
            ),
            (
                self._main._t("stat_concepts_total"),
                data["union"],
                self._main._t("panorama_chip_tip_graph"),
                lambda: self.view_switch_requested.emit("concept_map"),
            ),
            (
                self._main._t("stat_relations_total"),
                data["relations"],
                self._main._t("panorama_chip_tip_graph"),
                lambda: self.view_switch_requested.emit("concept_map"),
            ),
            (
                self._main._t("stat_shared_concepts"),
                data["shared"],
                self._main._t("panorama_chip_tip_shared"),
                lambda: self._show_shared(data.get("shared_list") or []),
            ),
            (
                self._main._t("stat_unknowns"),
                len(data["unknowns"]),
                self._main._t("panorama_chip_tip_unknowns"),
                lambda: self._scroll_to(getattr(self, "_unknowns_widget", None)),
            ),
        ]
        for label, val, tip, action in chips:
            chip = _ScaleChip(val, label, tip)
            chip.clicked.connect(action)
            row.addWidget(chip)
        row.addStretch()
        lay.addLayout(row)
        return card

    def _scroll_to(self, widget) -> None:
        """Scroll the panorama page to the card a chip summarises.

        Cards behind the 「更多」 fold auto-expand first — a chip must never
        scroll to an invisible target (dead-link zero tolerance).
        """
        scroll = getattr(self, "_scroll", None)
        sec = getattr(self, "_more_section", None)
        if sec is not None and widget is not None and sec.isAncestorOf(widget):
            sec.set_expanded(True)
        if widget is not None and scroll is not None:
            scroll.ensureWidgetVisible(widget)

    def _show_shared(self, items: list[dict]) -> None:
        """Drill into the shared-concept chip: which ideas bridge materials.

        A cross-material concept is a project-level junction — the learner
        needs its name and where it comes from, plus a one-click way in.
        Nothing here is inferred: it is the same normalised-name overlap the
        chip counts.
        """
        dlg = QDialog(self)
        dlg.setObjectName("panorama_shared_dialog")
        dlg.setWindowTitle(self._main._t("panorama_shared_title"))
        dlg.setMinimumWidth(560)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        if items:
            lay.addWidget(
                self._muted(self._main._t("panorama_shared_intro", n=len(items)))
            )
        else:
            lay.addWidget(self._muted(self._main._t("panorama_shared_empty")))

        for it in items[:40]:
            row = QHBoxLayout()
            row.setSpacing(8)
            name = QLabel(str(it["name"]))
            name.setWordWrap(True)
            name.setStyleSheet("font-size: 14px; color: #1F2933;")
            row.addWidget(name, 1)

            titles = "、".join(t for _aid, t in it["assets"])
            where = self._muted(
                self._main._t("panorama_shared_in", titles=titles), "#546E7A"
            )
            where.setWordWrap(True)
            row.addWidget(where, 1)

            aid = it["assets"][0][0] if it["assets"] else ""
            btn = self._link_btn(
                self._main._t("panorama_jump_concept", name=it["name"]), "#1565C0"
            )
            btn.clicked.connect(
                lambda checked=False, a=aid, n=it["name"]: self._jump_and_close(
                    dlg, a, n
                )
            )
            row.addWidget(btn)

            wrap = QWidget()
            wrap.setLayout(row)
            lay.addWidget(wrap)

        lay.addStretch()
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(dlg.reject)
        box.accepted.connect(dlg.reject)
        lay.addWidget(box)
        dlg.exec()

    def _jump_and_close(self, dlg, asset_id: str, concept_name: str) -> None:
        dlg.accept()
        self.concept_jump_requested.emit(asset_id, concept_name)

    def _materials_card(self, data):
        card, lay = self._card(self._main._t("panorama_materials_title"))
        if not data["materials"]:
            lay.addWidget(self._muted(self._main._t("no_asset")))
            return card
        for mt in data["materials"]:
            row = QHBoxLayout()
            row.setSpacing(8)
            name = QLabel(str(mt["title"]))
            name.setWordWrap(True)
            name.setStyleSheet("font-size: 14px; color: #1F2933;")
            row.addWidget(name, 1)

            rate = mt["rate"]
            rate_color = (
                theme.SUCCESS
                if rate >= 0.8
                else theme.WARNING
                if rate >= 0.5
                else theme.DANGER
            )
            rate_lbl = QLabel(
                self._main._t("panorama_anchor_rate", pct=f"{rate:.0%}")
            )
            rate_lbl.setStyleSheet(f"font-size: 12.5px; color: {rate_color};")
            row.addWidget(rate_lbl)

            cnt = QLabel(f"{mt['count']}")
            cnt.setToolTip(self._main._t("stat_concepts_total"))
            cnt.setStyleSheet("font-size: 12.5px; color: #6B7A90;")
            row.addWidget(cnt)

            status = mt["status"]
            if status:
                st = QLabel(
                    self._main._t(
                        "teacher_status_"
                        + {"done": "done", "fallback": "fallback", "failed": "failed"}.get(
                            status, "done"
                        )
                    )
                )
                st.setStyleSheet("font-size: 12.5px; color: #90A4AE;")
                row.addWidget(st)
            else:
                row.addWidget(self._muted(self._main._t("panorama_no_teacher"), "#CFD8DC"))

            btn = self._link_btn(self._main._t("panorama_view_asset"), "#1565C0")
            btn.clicked.connect(
                lambda checked=False, a=mt["aid"]: self.asset_switch_requested.emit(a)
            )
            row.addWidget(btn)

            wrap = QWidget()
            wrap.setLayout(row)
            lay.addWidget(wrap)
        return card

    def _unknowns_card(self, data):
        title = self._main._t("panorama_unknowns_title", n=len(data["unknowns"]))
        card, lay = self._card(title, theme.WARNING)
        if not data["unknowns"]:
            lay.addWidget(self._muted(self._main._t("panorama_unknowns_none")))
            return card

        sev_colors = {
            "high": theme.DANGER,
            "medium": theme.WARNING,
            "low": theme.TEXT_MUTED,
            "info": theme.ACCENT,
        }
        shown = data["unknowns"][:20]
        for an in shown:
            kind_txt = kind_label(an["kind"])
            card_row = QFrame()
            card_row.setStyleSheet(
                f"QFrame {{ background-color: {theme.SURFACE_MUTED};"
                f" border: 1px solid {theme.DIVIDER};"
                f" border-radius: {theme.RADIUS_SM}px; }}"
            )
            rl = QHBoxLayout(card_row)
            rl.setContentsMargins(10, 6, 10, 6)
            rl.setSpacing(8)

            badge = QLabel(f"{kind_txt} · {an['sev']}")
            badge.setStyleSheet(
                "font-size: 12px; font-weight: 600; color: %s;"
                % sev_colors.get(an["sev"], theme.TEXT_MUTED)
            )
            rl.addWidget(badge)

            desc_text = an["desc"]
            if len(desc_text) > 120:
                desc_text = desc_text[:120] + "…"
            desc = QLabel(desc_text)
            desc.setWordWrap(True)
            desc.setStyleSheet(f"font-size: 13px; color: {theme.TEXT_MUTED};")
            rl.addWidget(desc, 1)

            src = self._muted(f"— {an['title']}")
            rl.addWidget(src)

            if an["name"]:
                jump = self._link_btn(
                    self._main._t("panorama_jump_concept", name=an["name"])
                )
                jump.clicked.connect(
                    lambda checked=False, a=an["aid"], n=an["name"]: (
                        self.concept_jump_requested.emit(a, n)
                    )
                )
                rl.addWidget(jump)

            lay.addWidget(card_row)
        if len(data["unknowns"]) > len(shown):
            lay.addWidget(self._muted(f"+{len(data['unknowns']) - len(shown)}"))
        return card

    def _frontier_card(self, data):
        card, lay = self._card(
            self._main._t("panorama_frontier_title"), theme.ACCENT
        )
        unan = data["unanchored"]
        weak = data["weak"]
        if not unan and not weak:
            lay.addWidget(self._muted(self._main._t("panorama_frontier_none")))
            return card

        if unan:
            lay.addWidget(
                self._subtitle(
                    self._main._t("panorama_frontier_unanchored", n=len(unan)),
                    "#E65100",
                )
            )
            for it in unan[:12]:
                btn = self._link_btn(f"◌ {it['name']}  — {it['title']}", "#E65100")
                btn.clicked.connect(
                    lambda checked=False, a=it["aid"], n=it["name"]: (
                        self.concept_jump_requested.emit(a, n)
                    )
                )
                lay.addWidget(btn)
            if len(unan) > 12:
                lay.addWidget(self._muted(f"+{len(unan) - 12}"))

        if weak:
            lay.addWidget(
                self._subtitle(
                    self._main._t("panorama_frontier_weak", n=len(weak)), "#C62828"
                )
            )
            for w in weak[:12]:
                btn = self._link_btn(
                    self._main._t(
                        "panorama_weak_item", name=w["name"], pct=f"{w['pct']:.0%}"
                    ),
                    "#C62828",
                )
                btn.clicked.connect(
                    lambda checked=False, a=w["aid"], n=w["name"]: (
                        self.concept_jump_requested.emit(a, n)
                    )
                )
                lay.addWidget(btn)
            if len(weak) > 12:
                lay.addWidget(self._muted(f"+{len(weak) - 12}"))
        return card
