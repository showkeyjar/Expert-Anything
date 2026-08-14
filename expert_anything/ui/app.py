"""ExpertAnything desktop UI (Flet).

Vertical slice: import -> knowledge model -> teaching session -> learner model.
LLM-bound work runs in a thread (via asyncio.to_thread) so the window stays
responsive. Missing LLM key degrades gracefully (deterministic fallback).

All user-facing strings go through core.i18n.t() so the UI is localizable.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path

import flet as ft

from expert_anything.core import config, storage
from expert_anything.core.extraction import extract_knowledge
from expert_anything.ui.graph_widget import build_knowledge_graph
from expert_anything.ui.concept_cards import adaptive_queue_view
from expert_anything.core.i18n import (
    LANGS,
    get_lang,
    init_lang,
    save_lang,
    set_lang,
    t,
    translate_option,
)
from expert_anything.core.learner import (
    adaptive_path,
    load as load_learner,
    mark_completed,
    next_concept_id,
    normalize,
    record_evaluation,
    register_asset,
    save as save_learner,
    set_profile,
    unregister_asset,
    weaknesses,
)
from expert_anything.core.llm import LLMClient
from expert_anything.core.models import KnowledgeAsset
from expert_anything.core.parsers import extract_from_bytes
from expert_anything.core.teacher import (
    anomaly_concept_ids,
    anomaly_prioritized_path,
    build_teacher_model,
    incorporate_learner_signal,
    kind_label,
)
from expert_anything.core.tutor import Tutor


class ExpertApp:
    def __init__(self, page: ft.Page) -> None:
        init_lang()
        self.page = page
        self.assets: list[KnowledgeAsset] = []
        self.current: KnowledgeAsset | None = None
        self.learner = load_learner()
        self.llm = self._build_llm()
        self.teach_state: dict = {}
        self.teacher = None  # TeacherModel of the current asset (self-learning layer)
        self._current_view = "import"      # which top-level view is shown (for re-render on lang change)
        self._source_state: dict = {}      # args to re-render the reader on lang change
        self._concept_map_state: dict = {} # args to re-render the per-concept graph view
        self._pending_teach_cid: str | None = None  # concept the user asked to learn before aligning

        page.title = "ExpertAnything · " + t("app_tagline")
        page.window.width = 1100
        page.window.height = 760
        page.window.min_width = 880
        page.window.min_height = 600
        page.padding = 0
        page.spacing = 0
        page.theme_mode = ft.ThemeMode.LIGHT

        self.content = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=0)
        self.asset_list = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO)
        self.status = ft.Text("", size=12, color=ft.Colors.GREY)
        # Progress UI for long import/analysis runs so the window never looks frozen.
        self._progress_bar = ft.ProgressBar(
            value=0.0, width=460, height=14,
            color=ft.Colors.CYAN_400, bgcolor=ft.Colors.BLUE_50,
        )
        self._progress_text = ft.Text("", size=12, color=ft.Colors.GREY_800)
        self._busy = False      # a long-running op is in progress
        self._det = False       # progress is in determinate (numeric) mode
        self._loop = None       # running event loop (set when an async op starts)
        self._start = 0.0       # wall-clock start of the current op (for ETA)
        self._stage_msg = ""    # current stage label, shown with elapsed time
        self.file_picker = ft.FilePicker()
        page.services.append(self.file_picker)

        self._lang_dd = self._build_lang_dd()
        self._sidebar = ft.Container(
            width=240,
            bgcolor=ft.Colors.BLUE_GREY_900,
            padding=ft.Padding.all(14),
            content=self._build_sidebar_content(),
        )

        page.add(
            ft.Row(
                [self._sidebar, ft.VerticalDivider(width=1), self.content],
                expand=True,
                spacing=0,
            )
        )
        self.refresh_assets()
        self.show_import()

    # ------------------------------------------------------------------ utils
    def _build_llm(self) -> LLMClient | None:
        if not config.has_llm():
            return None
        try:
            return LLMClient.from_config(
                config.LLM_API_KEY, config.LLM_BASE_URL, config.LLM_MODEL,
                max_concurrency=2,
            )
        except Exception:
            return None

    def _build_lang_dd(self) -> ft.Control:
        """Language selector rendered as a *light* card so its label, selected
        value and the dropdown option list are clearly readable inside the dark
        sidebar (a plain Dropdown on BLUE_GREY_900 was effectively invisible)."""
        dd = ft.Dropdown(
            label=t("lang_label"),
            width=212,
            value=get_lang(),
            options=[ft.dropdown.Option(key=code, text=name) for code, name in LANGS.items()],
            on_select=self._on_lang_change,
            bgcolor=ft.Colors.WHITE,
            border_color=ft.Colors.BLUE_200,
            filled=True,
            label_style=ft.TextStyle(color=ft.Colors.GREY_700, size=12),
            text_style=ft.TextStyle(color=ft.Colors.BLACK, size=13, weight=ft.FontWeight.W_500),
        )
        return ft.Container(
            bgcolor=ft.Colors.WHITE,
            border_radius=10,
            padding=ft.Padding.all(8),
            content=ft.Column([dd], spacing=0),
        )

    def _build_sidebar_content(self) -> ft.Control:
        """Build the sidebar's inner column. Called on every render so it
        always reflects the active language (the menu itself must localize too)."""
        self._lang_dd = self._build_lang_dd()
        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Container(
                            width=30, height=30, border_radius=8,
                            bgcolor=ft.Colors.CYAN_400,
                            content=ft.Text("EA", color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                            alignment=ft.Alignment.CENTER,
                        ),
                        ft.Text("ExpertAnything", color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                    ]
                ),
                ft.Container(height=6),
                self._lang_dd,
                ft.Container(height=6),
                self._nav_button(t("import_asset"), self.show_import, icon=ft.Icons.ADD),
                self._nav_button(t("knowledge_model"), self.show_knowledge, icon=ft.Icons.ACCOUNT_TREE),
                self._nav_button(t("teach_session"), self.show_teach, icon=ft.Icons.SCHOOL),
                self._nav_button(t("learner_model"), self.show_learner, icon=ft.Icons.PSYCHOLOGY),
                self._nav_button(t("cognitive_nav"), self.show_teacher, icon=ft.Icons.AUTO_AWESOME),
                self._nav_button(t("read_source"), self.show_source, icon=ft.Icons.ARTICLE),
                ft.Divider(color=ft.Colors.BLUE_GREY_700),
                ft.Text(t("assets_label"), color=ft.Colors.BLUE_GREY_200, size=12),
                self.asset_list,
                ft.Container(expand=True),
                self.status,
            ]
        )

    def _rebuild_sidebar(self) -> None:
        """Rebuild the sidebar (e.g. after a language switch)."""
        self._sidebar.content = self._build_sidebar_content()
        self.page.update()

    async def _on_lang_change(self, e) -> None:
        set_lang(e.control.value)
        save_lang()
        view = self._current_view
        if view == "import":
            self.show_import()
        elif view == "knowledge":
            self.show_knowledge()
        elif view == "learner":
            self.show_learner()
        elif view == "teacher":
            self.show_teacher()
        elif view == "source":
            self.show_source(**self._source_state)
        elif view == "concept_map":
            self.show_concept_map(**self._concept_map_state)
        elif view == "teach":
            await self.show_teach()
        # The sidebar (menu labels + language dropdown) must localize too.
        self._rebuild_sidebar()

    def _nav_button(self, label: str, handler, icon=None) -> ft.Control:
        return ft.TextButton(
            label, icon=icon, on_click=handler,
            style=ft.ButtonStyle(color=ft.Colors.WHITE),
        )

    # --------------------------------------------------- per-concept navigation
    def _learn_handler(self, cid: str):
        """Async wrapper so a concept's '讲解' button jumps straight into that
        concept's teaching session (instead of only '进入教学会话')."""
        async def _h(e):
            self._pending_teach_cid = cid
            await self.show_teach(None, concept_id=cid)
        return _h

    def _graph_handler(self, cid: str):
        def _h(e):
            self.show_concept_map(concept_id=cid)
        return _h

    def _asset_mastery_map(self, a) -> dict:
        """{concept_id: mastery} for the current asset, drawn from the learner
        model (keyed by normalized concept name)."""
        by_norm = {
            key: float(rec.get("mastery", 0.0))
            for key, rec in self.learner.get("concepts", {}).items()
        }
        m = {}
        if not a:
            return m
        for c in a.concepts:
            nk = normalize(c.name)
            if nk in by_norm:
                m[c.id] = by_norm[nk]
        return m

    def _build_dashboard_stats(self, a) -> ft.Control:
        """Dashboard-style stat cards inspired by DeepTutor's Space dashboard.
        Shows concept count, mastery overview, and anomaly status at a glance."""
        master = self._asset_mastery_map(a)
        anom = self._anomaly_ids(a)
        total = len(a.concepts)
        mastered = sum(1 for m in master.values() if m >= 0.6)
        partial = sum(1 for m in master.values() if 0.3 <= m < 0.6)
        weak = sum(1 for m in master.values() if 0 < m < 0.3)
        unstudied = total - mastered - partial - weak
        n_anom = len(anom)

        def _stat_card(icon, label, value, color):
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=16, vertical=12),
                border_radius=10,
                bgcolor=ft.Colors.WHITE,
                shadow=ft.BoxShadow(blur_radius=2, color=(0,0,0,0.06), offset=ft.Offset(0,1)),
                content=ft.Column([
                    ft.Row([
                        ft.Icon(icon, size=20, color=color),
                        ft.Container(width=8),
                        ft.Text(label, size=12, color=ft.Colors.GREY_700),
                    ], wrap=False),
                    ft.Container(height=4),
                    ft.Text(str(value), size=22, weight=ft.FontWeight.BOLD, color=color),
                ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.START),
            )

        cards = [
            _stat_card(ft.Icons.FOLDER_OUTLINED, t("total_concepts", n=total), total, ft.Colors.BLUE_700),
            _stat_card(ft.Icons.CHECK_CIRCLE_OUTLINED, t("mastered"), mastered, ft.Colors.GREEN_700),
            _stat_card(ft.Icons.TRENDING_UP, t("partial"), partial + weak, ft.Colors.AMBER_700),
            _stat_card(ft.Icons.PSYCHOLOGY, t("unstudied"), unstudied, ft.Colors.GREY_700),
            _stat_card(ft.Icons.WARNING_AMBER, t("anomalies"), n_anom, ft.Colors.ORANGE_700 if n_anom else ft.Colors.GREY_400),
        ]
        return ft.Row(cards, spacing=12, alignment=ft.MainAxisAlignment.START)

    def _anomaly_ids(self, a) -> set:
        if self.teacher is not None:
            return anomaly_concept_ids(a, self.teacher)
        if a is not None:
            tm = storage.load_teacher(a.asset_id)
            return anomaly_concept_ids(a, tm)
        return set()

    def _find_cid(self, name: str) -> str | None:
        if not self.current:
            return None
        n = normalize(name)
        for c in self.current.concepts:
            if normalize(c.name) == n:
                return c.id
        return None

    def _adaptive_path(self, a):
        """Ranked, adaptive study queue for the current asset, blending mastery
        deficit, anomaly links, foundational leverage and declared-path order."""
        if not a:
            return []
        return adaptive_path(
            a, self.learner, self._anomaly_ids(a),
            path=list(a.learning_path) or None,
        )

    def _recommend_next(self, a):
        """Single best next concept for the learner model's '推荐下一步' header CTA.
        Now derived from the adaptive queue so it stays consistent with the list."""
        items = self._adaptive_path(a)
        if not items:
            return None, ""
        top = items[0]
        if "anom" in top["tags"]:
            reason = "recommend_reason_anom"
        elif "weak" in top["tags"]:
            reason = "recommend_reason_weak"
        else:
            reason = "recommend_reason_path"
        return top["cid"], reason

    def _reason_texts(self, tags):
        """Map adaptive-path reason tags to translated, human-readable strings."""
        out = []
        for tag in tags:
            if tag == "anom":
                out.append(t("recommend_reason_anom"))
            elif tag == "weak":
                out.append(t("recommend_reason_weak"))
            elif tag == "foundation":
                out.append(t("recommend_reason_foundation"))
            elif tag.startswith("unblock:"):
                n = tag.split(":", 1)[1]
                out.append(t("recommend_reason_unblock", n=n))
            elif tag == "ready":
                out.append(t("recommend_reason_ready"))
            elif tag == "blocked":
                out.append(t("recommend_reason_blocked"))
            elif tag == "path":
                out.append(t("recommend_reason_path"))
        return out

    def set_status(self, msg: str) -> None:
        self.status.value = msg
        self.page.update()

    def refresh_assets(self) -> None:
        self.assets = storage.load_assets()
        self.asset_list.controls = []
        for a in self.assets:
            row = ft.Row(
                [
                    ft.TextButton(
                        t("asset_item", title=a.title, count=len(a.concepts)),
                        on_click=lambda e, aid=a.asset_id: self.select_asset(aid),
                        style=ft.ButtonStyle(color=ft.Colors.BLUE_GREY_100),
                        tooltip=a.source_name,
                        expand=True,
                    ),
                    ft.IconButton(
                        ft.Icons.DELETE_OUTLINE,
                        icon_size=15,
                        tooltip=t("delete_tip"),
                        on_click=lambda e, aid=a.asset_id, ti=a.title: self._confirm_delete(aid, ti),
                    ),
                ]
            )
            self.asset_list.controls.append(row)
        self.page.update()

    def select_asset(self, asset_id: str) -> None:
        self.current = next((a for a in self.assets if a.asset_id == asset_id), None)
        if self.current:
            self.teacher = storage.load_teacher(asset_id)
            register_asset(self.learner, self.current)
            save_learner(self.learner)
            self.show_knowledge()

    # ----------------------------------------------------------- delete asset
    def _show_dialog(self, dlg: ft.Control) -> None:
        """Show a dialog, compatible across flet versions."""
        if hasattr(self.page, "show_dialog"):
            self.page.show_dialog(dlg)
        elif hasattr(self.page, "open"):
            self.page.open(dlg)
        else:
            self.page.overlay.append(dlg)
            dlg.open = True
            self.page.update()

    def _dismiss_dialog(self, dlg: ft.Control) -> None:
        """Dismiss a previously shown dialog."""
        if hasattr(self.page, "pop_dialog"):
            self.page.pop_dialog()
        elif hasattr(self.page, "close"):
            self.page.close(dlg)
        else:
            dlg.open = False
            self.page.update()

    def delete_asset_by_id(self, asset_id: str) -> None:
        """Permanently remove an asset and all of its traces (files + learner model)."""
        storage.delete_asset(asset_id)
        unregister_asset(self.learner, asset_id)
        save_learner(self.learner)
        was_current = self.current is not None and self.current.asset_id == asset_id
        if was_current:
            self.current = None
            self.teacher = None
        self.refresh_assets()
        if was_current or not self.current:
            self.show_import()

    def _confirm_delete(self, asset_id: str, title: str) -> None:
        def do_delete(e):
            self._dismiss_dialog(dlg)
            self.delete_asset_by_id(asset_id)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(t("confirm_delete_title")),
            content=ft.Text(t("confirm_delete_body", title=title)),
            actions=[
                ft.TextButton(t("cancel"), on_click=lambda e: self._dismiss_dialog(dlg)),
                ft.TextButton(
                    t("delete"),
                    on_click=do_delete,
                    style=ft.ButtonStyle(color=ft.Colors.RED),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self._show_dialog(dlg)

    def _clear(self) -> None:
        self.content.controls = []

    def _render(self, *controls: ft.Control) -> None:
        self._clear()
        self.content.controls.extend(controls)
        self.page.update()

    # ---------------------------------------------------------- progress (import/analysis)
    def _elapsed(self) -> float:
        return time.perf_counter() - self._start if self._start else 0.0

    def _set_msg(self, msg: str) -> None:
        """Set the current stage label and refresh the progress text with elapsed s."""
        self._stage_msg = msg
        self._progress_text.value = f"{msg}（已用 {self._elapsed():.0f}s）"

    def _render_progress_view(self, message: str) -> None:
        """Replace the content area with an animated progress panel.

        This also removes the import button from the screen, so the user cannot
        click '生成知识包' again while a long extraction/self-learn is running.
        """
        self._clear()
        self.content.controls.append(
            ft.Container(
                padding=ft.Padding.all(22),
                content=ft.Column([
                    self._header(t("processing"), t("processing_hint")),
                    ft.Container(height=16),
                    self._progress_bar,
                    ft.Container(height=10),
                    self._progress_text,
                    ft.Container(height=10),
                    ft.Text(
                        t("progress_note"),
                        size=11, color=ft.Colors.GREY,
                    ),
                ]),
            )
        )
        self.page.update()

    def _begin_progress(self, message: str) -> None:
        self._loop = asyncio.get_running_loop()
        self._busy = True
        self._det = False
        self._start = time.perf_counter()
        self._progress_bar.value = 0.08
        self._set_msg(message)
        self._render_progress_view(message)
        self._loop.create_task(self._pulse())

    def _stage(self, message: str) -> None:
        """Switch to a new labelled stage; keep the bar in indeterminate mode."""
        self._det = False
        self._set_msg(message)
        self.page.update()

    def _end_progress(self, message: str) -> None:
        self._busy = False
        self._det = False
        self._progress_bar.value = 1.0
        self._set_msg(message)
        self.page.update()

    def _make_progress_cb(self):
        """Build a thread-safe progress callback for the worker thread.

        The extraction/teacher model run inside asyncio.to_thread, so their
        on_progress fires on a worker thread. We marshal it back onto the main
        event loop with call_soon_threadsafe before touching any flet control.
        """
        loop = self._loop
        app = self

        def cb(stage, current, total, message):
            loop.call_soon_threadsafe(
                lambda: loop.create_task(app._apply_progress(stage, current, total, message))
            )

        return cb

    async def _apply_progress(self, stage, current, total, message) -> None:
        self._set_msg(message)
        if total and total > 0:
            self._det = True
            self._progress_bar.value = max(0.0, min(1.0, current / total))
        self.page.update()

    async def _pulse(self) -> None:
        """Indeterminate animation while we wait on a single LLM call."""
        while self._busy:
            if not self._det:
                v = self._progress_bar.value or 0.0
                v = v + 0.07
                if v >= 0.92:
                    v = 0.12
                self._progress_bar.value = v
                self._progress_text.value = (
                    f"{self._stage_msg}（已用 {self._elapsed():.0f}s）"
                )
                self.page.update()
            await asyncio.sleep(0.12)

    # ------------------------------------------------------------------ import
    def show_import(self, e=None) -> None:
        self._current_view = "import"
        self._paste = ft.TextField(
            label=t("paste_label"),
            multiline=True, min_lines=8, max_lines=16, expand=True,
        )
        self._fname = ft.TextField(label=t("asset_name"), value="learning-note.md", width=240)
        note = "" if self.llm else t("no_llm_note")
        self._render(
            self._header(t("import_title"), t("import_subtitle")),
            ft.Container(
                padding=ft.Padding.all(18),
                content=ft.Column(
                    [
                        ft.ElevatedButton(t("choose_file"), icon=ft.Icons.UPLOAD_FILE,
                                          on_click=self._pick_file),
                        ft.Text(note, color=ft.Colors.ORANGE, size=12, visible=bool(note)),
                        self._paste,
                        ft.Row([self._fname,
                                ft.ElevatedButton(t("generate"), icon=ft.Icons.AUTO_AWESOME,
                                                  on_click=self._do_import)]),
                    ], spacing=12,
                ),
            ),
        )

    async def _pick_file(self, e) -> None:
        files = await self.file_picker.pick_files(
            allowed_extensions=["md", "markdown", "txt", "epub", "pdf", "html", "htm"]
        )
        if not files:
            return
        f = files[0]
        try:
            data = Path(f.path).read_bytes()
        except Exception as exc:
            self.set_status(t("process_error", exc=exc))
            return
        self._pending_bytes = data
        self._fname.value = os.path.basename(f.path)
        self._paste.value = extract_from_bytes(data, self._fname.value)[:4000]
        self.page.update()

    async def _do_import(self, e) -> None:
        if self._busy:
            return
        fname = self._fname.value or "learning-note.md"
        if getattr(self, "_pending_bytes", None):
            text = extract_from_bytes(self._pending_bytes, fname)
        else:
            text = self._paste.value or ""
        if not text.strip():
            self.set_status(t("no_content"))
            return
        self._loop = asyncio.get_running_loop()
        self._begin_progress(t("extracting"))
        try:
            cb = self._make_progress_cb()
            asset = await asyncio.to_thread(extract_knowledge, text, fname, self.llm, on_progress=cb)
            storage.save_asset(asset)
            self._stage(t("self_learning"))
            teacher = await asyncio.to_thread(build_teacher_model, asset, self.llm, on_progress=cb)
            storage.save_teacher(asset.asset_id, teacher)
            self.teacher = teacher
            register_asset(self.learner, asset)
            save_learner(self.learner)
            self.refresh_assets()
            self.current = asset
            self._end_progress(
                t("import_done",
                  title=asset.title, n_concepts=len(asset.concepts),
                  method=asset.method, status=teacher.status, n_anom=len(teacher.anomalies))
            )
        except Exception as exc:
            self._end_progress(t("process_error", exc=exc))
            self.set_status(t("import_failed", exc=exc))
            self.show_import()
            return
        self.show_knowledge()

    # ---------------------------------------------------------------- knowledge
    def _build_concept_tree(self, a: KnowledgeAsset):
        """Derive a forest from relations.

        A concept that is a `target` of at least one relation is a child; the
        rest are roots. This turns the previously flat card grid into an actual
        hierarchy (with a network map alongside for the cross-links). A visited
        guard prevents infinite recursion on relation cycles.
        """
        children = {c.id: [] for c in a.concepts}
        has_parent = {c.id: False for c in a.concepts}
        for r in a.relations:
            if r.source in children and r.target in children and r.source != r.target:
                children[r.source].append((r.target, r.label or ""))
                has_parent[r.target] = True
        roots = [c.id for c in a.concepts if not has_parent[c.id]] or [c.id for c in a.concepts]
        lp = {cid: i for i, cid in enumerate(a.learning_path)}
        roots.sort(key=lambda cid: lp.get(cid, 999))
        for cid in children:
            children[cid].sort(key=lambda pair: lp.get(pair[0], 999))
        return roots, children

    def _depth_color(self, depth: int) -> str:
        palette = [ft.Colors.BLUE_700, ft.Colors.TEAL_600, ft.Colors.GREEN_600,
                   ft.Colors.ORANGE_600, ft.Colors.PURPLE_500, ft.Colors.PINK_400]
        return palette[depth % len(palette)]

    def _render_concept_tree(self, a: KnowledgeAsset) -> ft.Control:
        roots, children = self._build_concept_tree(a)

        def node(cid: str, depth: int, visited: frozenset) -> ft.Control | None:
            if cid in visited:
                return None
            c = a.concept_by_id(cid)
            if c is None:
                return None
            ev = getattr(c, "evidence", []) or []
            child_ctls = []
            for (child, _label) in children.get(cid, []):
                ch = node(child, depth + 1, visited | {cid})
                if ch is not None:
                    child_ctls.append(ch)
            has_children = bool(child_ctls)
            header_row = ft.Row([
                ft.Container(
                    width=4, height=26, border_radius=2,
                    bgcolor=self._depth_color(depth),
                ),
                ft.Text(c.name, weight=ft.FontWeight.BOLD, size=13,
                        color=ft.Colors.BLUE_900),
                ft.Container(
                    content=ft.Text(f"{len(ev)} 处原文", size=10, color=ft.Colors.GREY_600),
                    padding=ft.Padding.only(left=6),
                ) if ev else ft.Container(),
            ], spacing=6)
            col = ft.Column([
                header_row,
                ft.Text(c.definition or c.summary or t("no_definition"),
                        size=11, color=ft.Colors.GREY_700),
                ft.Row([
                    ft.TextButton(
                        t("learn_concept"),
                        on_click=self._learn_handler(cid),
                        style=ft.ButtonStyle(color=ft.Colors.BLUE_700),
                    ),
                    ft.TextButton(
                        t("concept_graph_btn"),
                        on_click=self._graph_handler(cid),
                        style=ft.ButtonStyle(color=ft.Colors.TEAL_700),
                    ),
                    ft.TextButton(
                        t("read_source_link"),
                        on_click=lambda e, cid=cid: self._open_source_for_concept(cid),
                        style=ft.ButtonStyle(color=ft.Colors.BLUE_700),
                    ),
                ], spacing=2),
            ], spacing=2)
            if has_children:
                col.controls.append(
                    ft.Container(
                        padding=ft.Padding.only(left=14, top=2, bottom=2),
                        content=ft.Column(child_ctls, spacing=4),
                    )
                )
            return ft.Container(
                padding=ft.Padding.only(left=depth * 18, top=4, bottom=4, right=8),
                content=col,
            )

        nodes = [node(r, 0, frozenset()) for r in roots]
        nodes = [n for n in nodes if n is not None]
        if not nodes:
            return ft.Text(t("none"), size=12)
        return ft.Column(nodes, spacing=4)

    def show_knowledge(self, e=None) -> None:
        self._current_view = "knowledge"
        if not self.current:
            self._render(self._header(t("knowledge_model_header"), t("no_asset")))
            return
        a = self.current

        # Dashboard stats bar (DeepTutor-inspired)
        dashboard = self._build_dashboard_stats(a)

        # Build smart concept cards with adaptive ranking
        path_items = self._adaptive_path(a)
        concept_cards_ctrl = adaptive_queue_view(
            path_items,
            on_concept_click=lambda cid: self.show_teach(None, concept_id=cid),
        )

        rel_rows = [
            ft.Text(
                f"{a.concept_by_id(r.source).name if a.concept_by_id(r.source) else r.source} "
                f"—[{r.label or r.type}]→ "
                f"{a.concept_by_id(r.target).name if a.concept_by_id(r.target) else r.target}",
                size=12,
            )
            for r in a.relations
        ]
        path_names = " → ".join(
            (a.concept_by_id(cid).name if a.concept_by_id(cid) else cid) for cid in a.learning_path
        )
        tree = self._render_concept_tree(a)
        has_hierarchy = bool(a.relations)
        tree_note = ft.Text(
            t("tree_tip") if has_hierarchy else t("no_hierarchy"),
            size=11, color=ft.Colors.GREY_600,
        )
        # Interactive network graph — pan/zoom, clickable nodes, mastery-coloured.
        net = ft.Container(
            padding=ft.Padding.all(8), border_radius=8, bgcolor=ft.Colors.BLUE_50,
            content=build_knowledge_graph(
                a,
                mastery_map=self._asset_mastery_map(a),
                anomaly_ids=self._anomaly_ids(a),
                on_select=lambda cid: self.show_concept_map(concept_id=cid),
            ),
        )
        net_note = ft.Text(t("net_tip"), size=11, color=ft.Colors.GREY_600)

        is_fallback = (a.method or "").startswith(("deterministic", "fallback", "llm_failed", "lazy"))

        # Build render list with proper spacing
        render_items = [
            self._header(t("knowledge_model_header") + f" · {a.title}",
                         t("knowledge_subtitle", name=a.source_name, method=a.method)),
            dashboard,
        ]

        # Only add warning if it's a fallback asset
        if is_fallback:
            render_items.append(ft.Container(
                padding=ft.Padding.all(10), border_radius=8, bgcolor=ft.Colors.ORANGE_50,
                content=ft.Text(
                    t("fallback_warn", method=a.method),
                    size=12, color=ft.Colors.ORANGE_900,
                ),
            ))

        # Concept cards section
        render_items.append(ft.Container(
            padding=ft.Padding.symmetric(horizontal=20, vertical=10),
            content=ft.Column([
                ft.Text(t("recommend_next"), size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
                ft.Container(content=concept_cards_ctrl),
            ], spacing=6),
        ))

        # Concept tree section
        render_items.append(ft.Container(
            padding=ft.Padding.symmetric(horizontal=20, vertical=10),
            content=ft.Column([
                ft.Text(t("concept_structure"), size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
                ft.Text(tree_note, size=11, color=ft.Colors.GREY_600),
                ft.Container(content=tree),
            ], spacing=6),
        ))

        # Knowledge graph section
        render_items.append(ft.Container(
            padding=ft.Padding.symmetric(horizontal=20, vertical=10),
            content=ft.Column([
                ft.Text(t("concept_map_net"), size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
                ft.Text(net_note, size=11, color=ft.Colors.GREY_600),
                ft.Container(
                    content=net,
                    height=450,
                    border_radius=8,
                ),
            ], spacing=6),
        ))

        # Relations section
        if rel_rows:
            render_items.append(ft.Container(
                padding=ft.Padding.symmetric(horizontal=20, vertical=10),
                content=ft.Column([
                    ft.Text(t("relations"), size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
                    ft.Column(rel_rows, spacing=2),
                ], spacing=6),
            ))

        # Action buttons
        render_items.append(ft.Container(
            padding=ft.Padding.symmetric(horizontal=20, vertical=16),
            content=ft.Row([
                ft.ElevatedButton(t("read_source"), icon=ft.Icons.ARTICLE, on_click=self.show_source),
                ft.Container(width=10),
                ft.ElevatedButton(t("enter_teach"), icon=ft.Icons.SCHOOL, on_click=self.show_teach),
            ], spacing=10),
        ))

        self._render(*render_items)

    # --------------------------------------------------------- concept map view
    def show_concept_map(self, e=None, concept_id=None) -> None:
        """A focused, per-concept knowledge graph: the ego-network around one
        concept (it + its neighbours + the relations between them), plus the
        system's deep note and clickable neighbours so the learner can cross-check
        and branch into any related concept."""
        self._current_view = "concept_map"
        self._concept_map_state = {"concept_id": concept_id}
        if not self.current:
            self._render(self._header(t("concept_graph_view"), t("no_asset")))
            return
        a = self.current
        c = a.concept_by_id(concept_id) if concept_id else None
        if c is None:
            self._render(self._header(t("concept_graph_view"), t("none")))
            return

        master = self._asset_mastery_map(a)
        anom = self._anomaly_ids(a)
        graph = ft.Container(
            padding=ft.Padding.all(8), border_radius=8, bgcolor=ft.Colors.BLUE_50,
            content=build_knowledge_graph(
                a, focus_id=c.id, mastery_map=master, anomaly_ids=anom,
                on_select=lambda cid: self.show_concept_map(concept_id=cid),
            ),
        )

        note = self.teacher.concept_note_by_id(c.id) if self.teacher else None
        note_lines = []
        if note:
            if note.significance:
                note_lines.append(ft.Text(t("why_important") + note.significance, size=12))
            if note.note:
                note_lines.append(ft.Text(note.note, size=12, color=ft.Colors.GREY_800))
            if note.misconceptions:
                note_lines.append(ft.Text(t("misconceptions") + "；".join(note.misconceptions),
                                          size=12, color=ft.Colors.ORANGE_900))

        neigh = []
        for r in a.relations:
            if r.source == c.id:
                other = a.concept_by_id(r.target)
                if other:
                    neigh.append((t("rel_to", label=r.label or t("rel_default"), name=other.name), other.id))
            elif r.target == c.id:
                other = a.concept_by_id(r.source)
                if other:
                    neigh.append((t("rel_from", label=r.label or t("rel_default"), name=other.name), other.id))
        if neigh:
            chips = [
                ft.OutlinedButton(
                    content=label, height=28, on_click=self._learn_handler(cid),
                    style=ft.ButtonStyle(
                        color=ft.Colors.BLUE_700, side=ft.BorderSide(1, ft.Colors.BLUE_300),
                        shape=ft.RoundedRectangleBorder(radius=12),
                        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                    ),
                )
                for label, cid in neigh
            ]
            neigh_ctrl = ft.Row(chips, wrap=True, spacing=6, run_spacing=6)
        else:
            neigh_ctrl = ft.Text(t("no_neighbors"), size=11, color=ft.Colors.GREY_600)

        actions = ft.Row([
            ft.ElevatedButton(t("learn_concept_full"), icon=ft.Icons.SCHOOL, on_click=self._learn_handler(c.id)),
            ft.OutlinedButton(t("read_source_link"), on_click=lambda e, cid=c.id: self._open_source_for_concept(cid)),
            ft.TextButton(t("back_to_km_from_graph"), on_click=self.show_knowledge,
                          style=ft.ButtonStyle(color=ft.Colors.BLUE_700)),
        ], spacing=10)

        self._render(
            self._header(t("concept_graph_view") + f" · {c.name}", t("graph_focus_tip", name=c.name)),
            ft.Container(content=graph, padding=ft.Padding.all(10)),
            self._section(t("definition_lbl"), ft.Text(c.definition or c.summary or t("no_definition"), size=13)),
            *([self._section(t("concept_notes"), ft.Column(note_lines, spacing=4))] if note_lines else []),
            self._section(t("neighbor_relations"), neigh_ctrl),
            ft.Container(content=actions, padding=ft.Padding.only(top=8)),
        )

    # ------------------------------------------------------------------- teach
    def _open_source_for_concept(self, concept_id: str) -> None:
        """Jump to the reading view for a concept, listing all of its evidence
        passages (one-to-many) rather than just the first snippet."""
        self.show_source(concept_id=concept_id, evidence_idx=0)

    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:
        """Break the raw source into readable paragraphs.

        Prefers blank-line separation (markdown-style); falls back to single
        newlines, then to the whole text as one block. This is what turns the
        previous single megablob Text into a proper document.
        """
        raw = re.split(r"\n\s*\n", text.strip())
        paras = [p.strip() for p in raw if p.strip()]
        if len(paras) <= 1:
            paras = [p.strip() for p in text.split("\n") if p.strip()]
        if not paras:
            paras = [text.strip() or t("selected_fragment")]
        return paras

    def _concept_index_strip(self, active_cid: str | None = None) -> ft.Control:
        """A clickable strip of concepts that have a source anchor.

        Clicking a chip jumps the reader to that concept's first evidence in the
        original text. This is the 'table of contents' that makes the view about
        the extracted knowledge rather than a raw text dump.
        """
        a = self.current
        chips = []
        for c in a.concepts:
            if not c.evidence:
                continue
            if not any(ev and ev in (a.source_text or "") for ev in c.evidence):
                continue
            cid = c.id
            is_active = (cid == active_cid)
            chips.append(
                ft.OutlinedButton(
                    content=c.name,
                    on_click=lambda e, cid=cid: self.show_source(concept_id=cid, evidence_idx=0),
                    style=ft.ButtonStyle(
                        color=ft.Colors.AMBER_900 if is_active else ft.Colors.BLUE_700,
                        side=ft.BorderSide(1.5, ft.Colors.AMBER if is_active else ft.Colors.BLUE_300),
                        shape=ft.RoundedRectangleBorder(radius=14),
                        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                    ),
                    height=30,
                )
            )
        if not chips:
            return ft.Text(t("no_anchor_concepts"), size=11, color=ft.Colors.GREY_600)
        return ft.Row(chips, wrap=True, spacing=6, run_spacing=6)

    def _source_paragraph(self, para: str, hl: str | None = None) -> ft.Control:
        """Render one paragraph; if hl is given and sits in this paragraph,
        split it and wrap the match in a highlighted, scroll-anchored container."""
        if hl and hl in para:
            idx = para.index(hl)
            before = para[:idx]
            match = para[idx:idx + len(hl)]
            after = para[idx + len(hl):]
            return ft.Column([
                ft.Text(before, size=13, color=ft.Colors.GREY_900, selectable=True) if before else ft.Container(),
                ft.Container(
                    key="src-hl",
                    padding=ft.Padding.all(6), border_radius=6,
                    bgcolor=ft.Colors.YELLOW_100,
                    border=ft.Border(
                        left=ft.BorderSide(1.5, ft.Colors.AMBER),
                        right=ft.BorderSide(1.5, ft.Colors.AMBER),
                        top=ft.BorderSide(1.5, ft.Colors.AMBER),
                        bottom=ft.BorderSide(1.5, ft.Colors.AMBER),
                    ),
                    content=ft.Text(match, size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_900, selectable=True),
                ),
                ft.Text(after, size=13, color=ft.Colors.GREY_900, selectable=True) if after else ft.Container(),
            ], spacing=0)
        return ft.Text(para, size=13, color=ft.Colors.GREY_900, selectable=True)

    def _concept_para_map(self, a: KnowledgeAsset, paras: list[str]) -> dict:
        """para index -> concept ids whose evidence appears in that paragraph.

        This is the many-to-one index: one passage can be referenced by several
        concepts at once. Used to annotate each paragraph with the concepts that
        ground in it.
        """
        m: dict = {}
        for c in a.concepts:
            for ev in getattr(c, "evidence", []) or []:
                if not ev:
                    continue
                pi = next((i for i, p in enumerate(paras) if ev in p), None)
                if pi is not None:
                    m.setdefault(pi, []).append(c.id)
        return m

    def _anchor_chips(self, a: KnowledgeAsset, concept_ids, active_cid, key=None) -> ft.Control:
        """Chips for the *other* concepts that reference the same passage."""
        chips = []
        for cid in concept_ids:
            if cid == active_cid:
                continue
            c = a.concept_by_id(cid)
            if not c:
                continue
            chips.append(
                ft.OutlinedButton(
                    content=c.name, height=26,
                    on_click=lambda e, cid=cid: self.show_source(concept_id=cid, evidence_idx=0),
                    style=ft.ButtonStyle(
                        color=ft.Colors.BLUE_700,
                        side=ft.BorderSide(1, ft.Colors.BLUE_300),
                        shape=ft.RoundedRectangleBorder(radius=12),
                        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                    ),
                )
            )
        if not chips:
            return ft.Container()
        return ft.Container(
            key=key,
            padding=ft.Padding.only(left=10, bottom=6, top=2),
            content=ft.Row(
                [ft.Text(t("also_referenced") + "：", size=11, color=ft.Colors.GREY_600), *chips],
                spacing=4, wrap=True, run_spacing=4,
            ),
        )

    def show_source(self, e=None, highlight: str | None = None,
                    concept_id: str | None = None, evidence_idx: int = 0) -> None:
        """A focused reader for the original, unmodified source text.

        - No anchor: a structured document (one block per paragraph) with a
          concept index strip on top — a reader, not a raw dump.
        - With an anchor (clicked from a concept card or a chip): a narrowed view
          showing only the paragraph containing the evidence plus its immediate
          neighbours, with the snippet highlighted and auto-scrolled into view.
        """
        self._current_view = "source"
        self._source_state = {"concept_id": concept_id, "evidence_idx": evidence_idx}
        if not self.current:
            self._render(self._header(t("read_source"), t("no_asset")))
            return
        a = self.current
        text = a.source_text or ""
        if not text.strip():
            self._render(
                self._header(t("read_source") + f" · {a.title}", t("reader_subtitle", name=a.source_name)),
                self._section("", ft.Text(
                    t("no_source"),
                    size=13, color=ft.Colors.GREY_700,
                )),
            )
            return

        paras = self._split_paragraphs(text)
        total = len(paras)
        para_map = self._concept_para_map(a, paras)

        # Resolve the anchor: an explicit highlight wins; otherwise derive it
        # from the concept's evidence at the requested index.
        hl = highlight
        active_cid = concept_id
        if concept_id and not hl:
            c = a.concept_by_id(concept_id)
            if c and c.evidence:
                hl = c.evidence[min(evidence_idx, len(c.evidence) - 1)]

        focused = bool(hl) and hl in text
        index_strip = self._concept_index_strip(active_cid=active_cid)

        if focused:
            # ONE-TO-MANY: a concept can map to several source passages. List every
            # evidence of the active concept, each in its paragraph context with the
            # selected one highlighted, plus many-to-one chips for concepts sharing it.
            c = a.concept_by_id(active_cid) if active_cid else None
            evidences = (getattr(c, "evidence", []) or []) if c else ([hl] if hl else [])
            if not evidences:
                evidences = [hl] if hl else []
            sections = []
            for i, ev in enumerate(evidences):
                is_sel = (i == evidence_idx)
                pi = next((j for j, p in enumerate(paras) if ev in p), None)
                if pi is None:
                    # Evidence spans a paragraph break: show a windowed snippet.
                    start = text.index(ev)
                    lo, hi = max(0, start - 200), min(len(text), start + len(ev) + 200)
                    window = text[lo:hi]
                    block = ft.Column([
                        ft.Text(("…" if lo > 0 else "") + window[:start - lo], size=13, color=ft.Colors.GREY_900, selectable=True) if (start - lo) > 0 else ft.Container(),
                        ft.Container(
                            key="src-hl" if is_sel else None,
                            padding=ft.Padding.all(6), border_radius=6, bgcolor=ft.Colors.YELLOW_100,
                            border=ft.Border(left=ft.BorderSide(1.5, ft.Colors.AMBER), right=ft.BorderSide(1.5, ft.Colors.AMBER), top=ft.BorderSide(1.5, ft.Colors.AMBER), bottom=ft.BorderSide(1.5, ft.Colors.AMBER)),
                            content=ft.Text(ev, size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_900, selectable=True),
                        ),
                        ft.Text(window[start - lo + len(ev):] + ("…" if hi < len(text) else ""), size=13, color=ft.Colors.GREY_900, selectable=True) if (start - lo + len(ev)) < len(window) else ft.Container(),
                    ], spacing=0)
                else:
                    lo_i, hi_i = max(0, pi - 1), min(total - 1, pi + 1)
                    block = ft.Column(
                        [self._source_paragraph(p, ev if (j == pi and is_sel) else None)
                         for j, p in enumerate(paras[lo_i:hi_i + 1])],
                        spacing=10,
                    )
                    ref = [cid for cid in para_map.get(pi, []) if cid != active_cid]
                    if ref:
                        block.controls.append(self._anchor_chips(a, ref, active_cid))
                sections.append(
                    ft.Container(key=f"evsec-{i}", padding=ft.Padding.only(bottom=12), content=block)
                )
            cname = (c.name if c else t("selected_fragment"))
            subtitle = f"{t('read_source')} · {t('loc_concept', name=cname)} · {t('evidence_locations', n=len(evidences))}"
            actions = [
                ft.TextButton(content=t("back_to_km"), on_click=self.show_knowledge,
                              style=ft.ButtonStyle(color=ft.Colors.BLUE_700)),
            ]
            if active_cid:
                actions.append(
                    ft.ElevatedButton(content=t("learn_concept_full"), icon=ft.Icons.SCHOOL,
                                      on_click=self._learn_handler(active_cid))
                )
            if len(evidences) > 1:
                nxt = (evidence_idx + 1) % len(evidences)
                actions.append(ft.TextButton(content=t("next_evidence"), icon=ft.Icons.ARROW_FORWARD,
                                             on_click=lambda e, n=nxt: self.show_source(concept_id=active_cid, evidence_idx=n),
                                             style=ft.ButtonStyle(color=ft.Colors.BLUE_700)))
            actions.append(ft.TextButton(content=t("back_to_full"), icon=ft.Icons.MENU_BOOK,
                                         on_click=lambda e: self.show_source(),
                                         style=ft.ButtonStyle(color=ft.Colors.BLUE_700)))
            body_col = ft.Column([ft.Row(actions, spacing=4), *sections], spacing=8)
        else:
            subtitle = t("reader_full", n=total)
            # Full mode: many-to-one — annotate each referenced paragraph with the
            # concepts that ground in it, so the document reads as a network too.
            top_bar = ft.Row([
                ft.TextButton(content=t("back_to_km"), on_click=self.show_knowledge,
                              style=ft.ButtonStyle(color=ft.Colors.BLUE_700)),
            ], spacing=4)
            blocks = []
            for i, p in enumerate(paras):
                col = [self._source_paragraph(p)]
                ref = para_map.get(i, [])
                if ref:
                    col.append(self._anchor_chips(a, ref, active_cid, key="many2one"))
                blocks.append(ft.Column(col, spacing=2))
            body_col = ft.Column([top_bar, *blocks], spacing=10, scroll=ft.ScrollMode.AUTO)

        self._render(
            self._header(t("read_source") + f" · {a.title}", subtitle),
            ft.Container(content=index_strip, padding=ft.Padding.symmetric(horizontal=16, vertical=6)),
            ft.Container(content=body_col, expand=True, padding=ft.Padding.all(16)),
        )
        if focused:
            # scroll_to is a coroutine in flet 0.86.5 — schedule on the loop.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                loop.create_task(self.content.scroll_to(scroll_key="src-hl", duration=300))

    async def show_teach(self, e=None, concept_id=None) -> None:
        self._current_view = "teach"
        if not self.current:
            self._render(self._header(t("teach_title"), t("no_asset")))
            return
        a = self.current
        self.teach_state = {"concept_id": None}
        profile = self.learner.get("profile", {})
        if not profile.get("goal"):
            await self._render_align()
            return
        # A specific concept was requested (clicked "讲解"), or was pending after
        # the alignment step. Honour it directly instead of resuming the path.
        if concept_id and a.concept_by_id(concept_id):
            self.teach_state["concept_id"] = concept_id
            await self._render_lesson(concept_id)
            return
        if self._pending_teach_cid and a.concept_by_id(self._pending_teach_cid):
            cid = self._pending_teach_cid
            self._pending_teach_cid = None
            self.teach_state["concept_id"] = cid
            await self._render_lesson(cid)
            return
        path = anomaly_prioritized_path(a, self.teacher, a.learning_path)
        cid = next_concept_id(self.learner, a, path) or (a.learning_path[0] if a.learning_path else None)
        if cid is None:
            self._render(self._header(t("teach_title"), t("no_teach_concept")))
            return
        self.teach_state["concept_id"] = cid
        await self._render_lesson(cid)

    async def _render_align(self) -> None:
        a = self.current
        goal = ft.TextField(label=t("goal_label"), width=420)
        baseline = ft.Dropdown(label=t("baseline_label"), width=200, value="novice",
                               options=[ft.dropdown.Option(key=k, text=t("baseline_" + k)) for k in ("novice", "some", "practiced")])
        style = ft.Dropdown(label=t("style_label"), width=200, value="example",
                            options=[ft.dropdown.Option(key=k, text=t("style_" + k)) for k in ("example", "diagram", "steps")])

        async def start(e):
            set_profile(self.learner, goal.value or t("default_goal"), baseline.value or "novice", style.value or "example")
            save_learner(self.learner)
            self.set_status(t("start_teach"))
            await self.show_teach(None, concept_id=self._pending_teach_cid)

        self._render(
            self._header(t("teach_title") + f" · {a.title}", t("align_subtitle")),
            ft.Container(padding=ft.Padding.all(18), content=ft.Column([goal, ft.Row([baseline, style]), ft.ElevatedButton(t("start_teach"), icon=ft.Icons.SCHOOL, on_click=start)], spacing=12)),
        )

    async def _render_lesson(self, concept_id: str, vary: int = 0) -> None:
        a = self.current
        c = a.concept_by_id(concept_id)
        if not c:
            return
        front_ids = anomaly_concept_ids(a, self.teacher)
        priority_hint = t("priority_hint") if concept_id in front_ids else ""
        self.teach_state["concept_id"] = concept_id
        self.teach_state["vary"] = vary
        profile = self.learner.get("profile", {})
        style = profile.get("style", "example")
        self.set_status(t("preparing"))
        lesson = await asyncio.to_thread(Tutor(a, self.llm).teach, c, vary, style)

        # Compute progress for this concept
        entry = self.learner.get("assets", {}).get(a.asset_id, {})
        completed_count = len(entry.get("completed", []))
        total_count = len(a.concepts)
        progress_text = t("progress_done", done=completed_count, total=total_count)

        steps = (
            ft.Column([ft.Text(f"{i+1}. {s}", size=12) for i, s in enumerate(lesson.get("steps", []))])
            if lesson.get("steps")
            else ft.Text("")
        )
        evidence = ft.Column([ft.Text(f"· {ev}", size=11, color=ft.Colors.GREY_700) for ev in lesson.get("evidence", [])]) if lesson.get("evidence") else ft.Text(t("no_relations"))

        # Live style selector — this is the control that was previously inert.
        # Changing it re-renders the lesson in the chosen shape, proving the
        # "例子 / 图示 / 拆解步骤" choice actually does something.
        style_dd = ft.Dropdown(
            label=t("style_dd_label"), width=240, value=style,
            options=[ft.dropdown.Option(key=k, text=t("style_" + k)) for k in ("example", "diagram", "steps")],
            on_select=self._change_style,
        )

        # Interactive concept graph: pan/zoom, clickable, focused on THIS
        # concept. Clicking a neighbour switches to teaching that concept.
        async def _graph_select(cid):
            await self.show_teach(None, concept_id=cid)

        diagram_ctrl = ft.Container(
            padding=ft.Padding.all(8), border_radius=8, bgcolor=ft.Colors.BLUE_50,
            content=build_knowledge_graph(
                a, focus_id=c.id,
                mastery_map=self._asset_mastery_map(a),
                anomaly_ids=self._anomaly_ids(a),
                on_select=_graph_select,
            ),
        )

        # Surface the system's open anomalies for this concept — teaching walks
        # *ahead* of the student by making "things still in doubt" explicit.
        doubt_section = ft.Text("")
        if self.teacher:
            matched = [
                an for an in self.teacher.anomalies
                if an.status in ("open", "investigating")
                and (c.name in an.description or c.name in (an.location or ""))
            ]
            open_total = len(self.teacher.open_anomalies())
            if matched:
                doubt_section = ft.Column([
                    ft.Text(t("doubt_matched", kind=kind_label(an.kind), desc=an.description),
                            size=12, color=ft.Colors.ORANGE_900)
                    for an in matched
                ])
            elif open_total:
                doubt_section = ft.Text(
                    t("doubt_none", n=open_total),
                    size=11, color=ft.Colors.GREY_700, italic=True,
                )

        answer = ft.TextField(label=t("answer_label"), multiline=True, min_lines=3, max_lines=6, expand=True)

        # "换一个例子" — proves the example is generated live, not static text.
        extra_btn = ft.Container()

        async def _vary_example(e):
            await self._render_lesson(concept_id, vary + 1)

        if style == "example" and self.llm is not None:
            extra_btn = ft.TextButton(t("vary_example"), on_click=_vary_example)

        async def submit(e):
            self.set_status(t("evaluating"))
            result = await asyncio.to_thread(Tutor(a, self.llm).evaluate, c, answer.value or "")
            score = record_evaluation(self.learner, c.name, a.asset_id, result["score"], answer.value or "", result["feedback"])
            mark_completed(self.learner, a.asset_id, c.id)
            save_learner(self.learner)
            # Closed loop: feed the learner's answer back into the Teacher Model
            # so the system keeps converging on what students actually struggle with.
            teacher = self.teacher or storage.load_teacher(a.asset_id)
            if teacher is None:
                from expert_anything.core.teacher import TeacherModel, ConceptNote
                teacher = TeacherModel(
                    asset_id=a.asset_id, status="fallback", method="lazy_init",
                    concept_notes=[ConceptNote(concept_id=cc.id, name=cc.name) for cc in a.concepts],
                )
            updated = await asyncio.to_thread(
                incorporate_learner_signal, a, teacher, c.id,
                answer.value or "", result["score"], result["feedback"], self.llm,
            )
            storage.save_teacher(a.asset_id, updated)
            self.teacher = updated
            fb = ft.Container(
                padding=ft.Padding.all(10), border_radius=8,
                bgcolor=ft.Colors.GREEN_50 if result["understood"] else ft.Colors.ORANGE_50,
                content=ft.Column([
                    ft.Text(t("eval_score", score=result["score"], m=score), weight=ft.FontWeight.BOLD, size=12),
                    ft.Text(result["feedback"], size=12),
                    ft.ElevatedButton(t("next_step"), icon=ft.Icons.ARROW_FORWARD, on_click=self._next_lesson),
                ]),
            )
            self.content.controls.append(fb)
            self.page.update()

        # Order the sections by the chosen style so the difference is obvious.
        graph_section = self._section(t("concept_graph"), diagram_ctrl)
        blocks = [
            self._header(t("teach_title") + f" · {c.name}", t("lesson_subtitle") + priority_hint),
            ft.Row([
                ft.Text(progress_text, size=11, color=ft.Colors.GREY_600),
                ft.TextButton(
                    t("concept_graph_view"), icon=ft.Icons.MAP,
                    style=ft.ButtonStyle(icon_size=14, padding=ft.Padding.symmetric(horizontal=8, vertical=2)),
                    on_click=lambda e, cid=concept_id: self.show_concept_map(concept_id=cid)),
            ], spacing=8, alignment=ft.MainAxisAlignment.END),
        ]
        blocks.append(ft.Container(padding=ft.Padding.only(bottom=6), content=style_dd))
        # Surface THIS concept's own definition up front so each lesson is visibly
        # about a different concept, not a generic template.
        blocks.append(self._section(
            t("definition_lbl"),
            ft.Text(c.definition or c.summary or t("no_definition"),
                    size=13, color=ft.Colors.GREY_800),
        ))
        blocks.append(graph_section)
        if style == "diagram":
            blocks.append(self._section(t("explain_position"), ft.Text(lesson.get("explanation", ""), size=13)))
            blocks.append(self._section(t("example_goal"), ft.Text(lesson.get("example", ""), size=13, color=ft.Colors.BLUE_900)))
            blocks.append(self._section(t("action_path"), steps))
        elif style == "steps":
            blocks.append(self._section(t("action_path_focus"), steps))
            blocks.append(self._section(t("explanation"), ft.Text(lesson.get("explanation", ""), size=13)))
            blocks.append(self._section(t("example_goal"), ft.Text(lesson.get("example", ""), size=13, color=ft.Colors.BLUE_900)))
        else:  # example
            blocks.append(self._section(t("example_goal_focus"), ft.Text(lesson.get("example", ""), size=13, color=ft.Colors.BLUE_900)))
            blocks.append(self._section(t("explanation"), ft.Text(lesson.get("explanation", ""), size=13)))
            blocks.append(self._section(t("action_path"), steps))
            blocks.append(extra_btn)
        blocks.append(self._section(t("evidence"), evidence))
        blocks.append(self._section(t("doubt_section"), doubt_section))
        blocks.append(self._section(t("practice"), ft.Text(lesson.get("practice", ""), size=13, weight=ft.FontWeight.BOLD)))
        blocks.append(ft.Container(padding=ft.Padding.all(10), content=ft.Column([answer, ft.ElevatedButton(t("submit_eval"), icon=ft.Icons.CHECK, on_click=submit)], spacing=10)))
        self._render(*blocks)

    async def _change_style(self, e) -> None:
        profile = self.learner.get("profile", {})
        set_profile(self.learner, profile.get("goal", t("default_goal")),
                    profile.get("baseline", "novice"), e.control.value or "example")
        save_learner(self.learner)
        cid = self.teach_state.get("concept_id")
        if cid:
            await self._render_lesson(cid, self.teach_state.get("vary", 0))

    async def _next_lesson(self, e) -> None:
        a = self.current
        path = anomaly_prioritized_path(a, self.teacher, a.learning_path)
        cid = next_concept_id(self.learner, a, path)
        if cid is None:
            self._render(self._header(t("teach_title"), f"《{a.title}》" + t("no_teach_concept")))
            return
        self.teach_state["concept_id"] = cid
        await self._render_lesson(cid)

    # ----------------------------------------------------------------- learner
    def show_learner(self, e=None) -> None:
        self._current_view = "learner"
        self.learner = load_learner()
        a = self.current
        profile = self.learner.get("profile", {})
        prof_text = t("profile_text",
                      goal=profile.get("goal", t("default_goal")),
                      baseline=translate_option("baseline", profile.get("baseline", "novice")),
                      style=translate_option("style", profile.get("style", "example")))
        mmap = self._asset_mastery_map(a) if a else {}
        anom = self._anomaly_ids(a) if a else set()

        # ---- overview stats ---------------------------------------------------
        if a and a.concepts:
            total = len(a.concepts)
            studied = len(mmap)
            vals = list(mmap.values())
            avg = sum(vals) / len(vals) if vals else 0.0
            done = sum(1 for v in vals if v >= config.WEAKNESS_THRESHOLD)
            overview = f"{t('progress_done', done=studied, total=total)} ｜ {t('avg_mastery')} {avg:.0%}"
            overview_ctrl = ft.Text(overview, size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900)
        else:
            overview_ctrl = ft.Text(t("no_asset"), size=13, color=ft.Colors.GREY_700)

        # ---- mastery map (interactive, mastery-coloured, clickable) ---------
        if a and a.concepts:
            async def _lm_select(cid):
                await self.show_teach(None, concept_id=cid)
            map_ctrl = ft.Container(
                padding=ft.Padding.all(8), border_radius=8, bgcolor=ft.Colors.BLUE_50,
                content=build_knowledge_graph(
                    a, mastery_map=mmap, anomaly_ids=anom,
                    on_select=_lm_select,
                ),
            )
            legend = ft.Container()  # legend built into the widget
        else:
            map_ctrl = ft.Text(t("no_mastery_yet"), size=12, color=ft.Colors.GREY_700)
            legend = ft.Container()

        # ---- recommended next step --------------------------------------------
        # ---- adaptive learning path (smart cards) -----------------------------
        path_items = self._adaptive_path(a) if a else []
        rec_ctrl = adaptive_queue_view(
            path_items,
            on_concept_click=lambda cid: self.show_teach(None, concept_id=cid),
        )

        # ---- per-concept mastery, each clickable to learn ---------------------
        concept_rows = []
        if a:
            order = list(a.learning_path) or [c.id for c in a.concepts]
            for cid in order:
                c = a.concept_by_id(cid)
                if not c:
                    continue
                m = mmap.get(cid, 0.0)
                concept_rows.append(
                    ft.Row([
                        ft.TextButton(
                            c.name, on_click=self._learn_handler(cid),
                            style=ft.ButtonStyle(color=ft.Colors.BLUE_800),
                        ),
                        ft.ProgressBar(value=m, width=180,
                                       color=ft.Colors.GREEN if m >= config.WEAKNESS_THRESHOLD else ft.Colors.ORANGE),
                        ft.Text(f"{m:.0%}", size=12, width=44),
                    ], spacing=8)
                )
        concept_mastery_ctrl = ft.Column(concept_rows) if concept_rows else ft.Text(t("no_records"), size=12)

        # ---- weaknesses, clickable --------------------------------------------
        weak = weaknesses(self.learner)
        if weak:
            chips = []
            for w in weak:
                cid = self._find_cid(w["name"])
                if cid:
                    chips.append(ft.OutlinedButton(
                        content=f"{w['name']}（{w['mastery']:.0%}）", height=28,
                        on_click=self._learn_handler(cid),
                        style=ft.ButtonStyle(color=ft.Colors.RED_700,
                                             side=ft.BorderSide(1, ft.Colors.RED_300),
                                             shape=ft.RoundedRectangleBorder(radius=12)),
                    ))
            weak_ctrl = ft.Column([
                ft.Row(chips, wrap=True, spacing=6, run_spacing=6),
                ft.Text(t("weak_click_hint"), size=11, color=ft.Colors.GREY_600),
            ], spacing=4)
        else:
            weak_ctrl = ft.Text(t("no_weakness"), size=13, color=ft.Colors.GREEN_800)

        # ---- recent responses -------------------------------------------------
        history = self.learner.get("history", [])[:10]
        hist_rows = [
            ft.Text(t("history_row", concept=h.get("concept", ""), score=h.get("score", 0), feedback=h.get("feedback", "")[:40]),
                     size=11, color=ft.Colors.GREY_700)
            for h in history
        ]

        self._render(
            self._header(t("learner_title"), t("learner_subtitle")),
            self._section(t("profile"), ft.Text(prof_text, size=13)),
            self._section(t("learner_overview"), overview_ctrl),
            self._section(t("mastery_map"), ft.Column([map_ctrl, legend], spacing=4) if a and a.concepts else map_ctrl),
            self._section(t("recommend_next"), rec_ctrl),
            self._section(t("mastery"), concept_mastery_ctrl),
            self._section(t("weaknesses"), weak_ctrl),
            self._section(t("recent"), ft.Column(hist_rows) if hist_rows else ft.Text(t("none"))),
        )

    # ---------------------------------------------------------- cognitive nav
    def show_teacher(self, e=None) -> None:
        self._current_view = "teacher"
        if not self.current:
            self._render(self._header(t("nav_title"), t("nav_no_asset")))
            return
        a = self.current
        tm = self.teacher or storage.load_teacher(a.asset_id)
        self.teacher = tm
        if tm is None:
            self._render(self._header(t("nav_title"), t("nav_no_self")),
                         self._section("", ft.ElevatedButton(t("gen_self"), icon=ft.Icons.AUTO_AWESOME, on_click=self._rerun_self_learn)))
            return

        mmap = self._asset_mastery_map(a)
        anom_ids = self._anomaly_ids(a)

        # ---- cognitive-nav hub: interactive mastery-coloured graph --------
        async def _nav_select(cid):
            await self.show_teach(None, concept_id=cid)
        hub = ft.Container(
            padding=ft.Padding.all(8), border_radius=8, bgcolor=ft.Colors.BLUE_50,
            content=build_knowledge_graph(
                a, mastery_map=mmap, anomaly_ids=anom_ids,
                on_select=_nav_select,
            ),
        )
        hub_legend = ft.Container()  # legend built into the widget
        concept_chips = [
            ft.OutlinedButton(
                content=c.name, height=30, on_click=self._learn_handler(c.id),
                style=ft.ButtonStyle(
                    color=ft.Colors.TEAL_800 if c.id in anom_ids else ft.Colors.BLUE_700,
                    side=ft.BorderSide(1.5, ft.Colors.TEAL_300 if c.id in anom_ids else ft.Colors.BLUE_300),
                    shape=ft.RoundedRectangleBorder(radius=14),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                ),
            )
            for c in a.concepts
        ]
        nav_chips = ft.Row(concept_chips, wrap=True, spacing=6, run_spacing=6)

        # ---- concepts tied to open anomalies (walk ahead of the student) -------
        anom_concepts = [a.concept_by_id(cid) for cid in anom_ids if a.concept_by_id(cid)]
        if anom_concepts:
            anom_rows_explore = [
                ft.Row([
                    ft.Text(c.name, size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.TEAL_900, expand=True),
                    ft.ElevatedButton(t("explore_anomaly"), icon=ft.Icons.EXPLORE,
                                      on_click=self._learn_handler(c.id)),
                ], spacing=8)
                for c in anom_concepts
            ]
            anom_explore_ctrl = ft.Column(anom_rows_explore, spacing=4)
        else:
            anom_explore_ctrl = ft.Text(t("no_anomaly"), size=12, color=ft.Colors.GREY_700)

        # concept notes cards (each with a "讲解" button)
        note_cards = []
        for c in a.concepts:
            n = tm.concept_note_by_id(c.id)
            if n is None:
                continue
            body = []
            if n.significance:
                body.append(ft.Text(t("why_important") + n.significance, size=12))
            if n.prerequisites:
                body.append(ft.Text(t("prereq") + "、".join(n.prerequisites), size=12))
            if n.connections:
                body.append(ft.Text(t("connections") + "、".join(n.connections), size=12))
            if n.misconceptions:
                body.append(ft.Text(t("misconceptions") + "；".join(n.misconceptions), size=12, color=ft.Colors.ORANGE_900))
            if n.note:
                body.append(ft.Text(n.note, size=12, color=ft.Colors.GREY_800))
            if n.external_notes:
                body.append(ft.Text(t("external_notes") + "；".join(n.external_notes), size=11, italic=True, color=ft.Colors.BLUE_900))
            if n.learner_signals:
                body.append(ft.Text(t("learner_signals") + " ｜ ".join(n.learner_signals[-3:]), size=11, color=ft.Colors.PURPLE_900))
            if not body:
                body = [ft.Text(t("not_deep"), size=12, color=ft.Colors.GREY_700)]
            note_cards.append(
                ft.Card(content=ft.Container(padding=ft.Padding.all(12), width=360, content=ft.Column([
                    ft.Row([
                        ft.Text(n.name, weight=ft.FontWeight.BOLD, size=14),
                        ft.Container(expand=True),
                        ft.TextButton(t("learn_concept"), on_click=self._learn_handler(c.id),
                                      style=ft.ButtonStyle(color=ft.Colors.BLUE_700)),
                    ], spacing=6),
                    *body,
                ], spacing=4)))
            )

        # anomaly list
        sev_color = {"high": ft.Colors.RED, "medium": ft.Colors.ORANGE, "low": ft.Colors.BLUE_GREY, "info": ft.Colors.GREY}
        anom_rows = []
        for an in tm.anomalies:
            anom_rows.append(
                ft.Card(content=ft.Container(padding=ft.Padding.all(10), content=ft.Column([
                    ft.Row([
                        ft.Text(kind_label(an.kind), weight=ft.FontWeight.BOLD, size=12, color=sev_color.get(an.severity, ft.Colors.GREY)),
                        ft.Text(f"[{an.severity}] · {an.status}", size=11, color=ft.Colors.GREY_700),
                    ], spacing=8),
                    ft.Text(an.description, size=12),
                    ft.Text(t("reader_subtitle", name=(an.location or t("none"))) + (f" ｜ {an.resolution}" if an.resolution else ""), size=11, color=ft.Colors.GREY_700),
                ], spacing=4)))
            )
        anom_section = ft.Column(anom_rows) if anom_rows else ft.Text(t("no_anomaly"))

        self._render(
            self._header(t("nav_title") + f" · {a.title}", t("nav_title") + f"：{tm.status} ｜ {tm.method}"),
            self._section(t("nav_hub"), ft.Column([hub, hub_legend, nav_chips], spacing=4)),
            self._section(t("open_anomaly_concepts"), anom_explore_ctrl),
            self._section(t("concept_notes"), ft.Row(wrap=True, spacing=10, run_spacing=10, controls=note_cards) if note_cards else ft.Text(t("none"))),
            self._section(t("anomaly_section", n=len(tm.anomalies)), anom_section),
            ft.Container(padding=ft.Padding.all(10), content=ft.ElevatedButton(t("recheck"), icon=ft.Icons.AUTO_AWESOME, on_click=self._rerun_self_learn)),
        )

    async def _rerun_self_learn(self, e) -> None:
        if not self.current:
            return
        if self._busy:
            return
        a = self.current
        self._loop = asyncio.get_running_loop()
        self._begin_progress(t("self_learning"))
        try:
            cb = self._make_progress_cb()
            tm = await asyncio.to_thread(build_teacher_model, a, self.llm, on_progress=cb)
            storage.save_teacher(a.asset_id, tm)
            self.teacher = tm
            self._end_progress(t("recheck") + f"：{tm.status}，{len(tm.anomalies)} " + t("anomaly_section", n=len(tm.anomalies)).split("（")[0])
        except Exception as exc:
            self._end_progress(t("process_error", exc=exc))
        self.show_teacher()

    # ------------------------------------------------------------------- shared
    def _header(self, title: str, subtitle: str = "") -> ft.Container:
        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=20, vertical=16),
            bgcolor=ft.Colors.BLUE_50,
            content=ft.Column([
                ft.Text(title, size=20, weight=ft.FontWeight.BOLD),
                ft.Text(subtitle, size=12, color=ft.Colors.GREY_700) if subtitle else ft.Container(),
            ]),
        )

    def _section(self, title: str, body: ft.Control) -> ft.Container:
        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=20, vertical=8),
            content=ft.Column([
                ft.Text(title, size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900),
                body,
            ], spacing=6),
        )


def main(page: ft.Page) -> None:
    ExpertApp(page)


if __name__ == "__main__":
    # Allow EXPERTANYTHING_LLM_API_KEY etc. to be exported in the same shell.
    import flet as _ft

    _ft.run(main)
