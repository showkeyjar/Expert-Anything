"""Headless self-test for the Flet UI.

Instantiates ExpertApp with a mock page so we exercise every control
construction path (this is exactly where flet 0.86.5 API mismatches blow up)
without needing a real desktop window.

Also drives a fake teaching session through the core API to ensure the
async handlers don't reference removed symbols.

IMPORTANT: we point EXPERTANYTHING_DATA_DIR at a temp dir *before* importing
any expert_anything module, so the test never writes real assets / learner.json.
"""
import asyncio
import os
import tempfile
from types import SimpleNamespace

# Must be set before config.py reads the environment at import time.
os.environ["EXPERTANYTHING_DATA_DIR"] = tempfile.mkdtemp(prefix="ea_selftest_")

import flet as ft

import expert_anything.core.tutor as tutor_mod
from expert_anything.ui.app import ExpertApp


class MockPage:
    """Minimal stand-in for flet.Page covering only what the UI touches."""

    def __init__(self):
        self.title = ""
        self.window = SimpleNamespace(
            width=0, height=0, min_width=0, min_height=0
        )
        self.padding = 0
        self.spacing = 0
        self.theme_mode = None
        self.overlay = []
        self.services = []
        self.added = []
        self.updated = 0

    def add(self, *controls):
        self.added.extend(controls)

    def update(self):
        self.updated += 1

    def show_dialog(self, control):
        self.shown = control

    def pop_dialog(self):
        self.popped = True


# Stub Tutor so _render_lesson never hits the network (and runs headlessly).
class FakeTutor:
    def __init__(self, asset, llm):
        self.asset = asset
        self.llm = llm

    def teach(self, concept, vary=0, style=None):
        return {
            "concept": concept.name,
            "style": "例子",
            "explanation": "这是一段测试讲解。",
            "example": "这是一个例子。",
            "steps": ["第一步", "第二步", "第三步"],
            "evidence": ["证据一", "证据二"],
        }

    def evaluate(self, concept, answer):
        return {"score": 3, "understood": True, "feedback": "不错。"}


def main():
    page = MockPage()
    app = ExpertApp(page)
    print("[ok] ExpertApp.__init__ constructed all sidebar/knowledge/teach controls")

    # Exercise the import view (render method) — constructs TextField/Container/etc.
    app.show_import()
    print("[ok] show_import() built import view controls")

    # Exercise knowledge + learner views against a current asset if present,
    # and the teaching session render path with a deterministic fallback LLM.
    # (We don't have an asset here, but the code guards on self.current.)
    app.show_knowledge()
    app.show_learner()
    print("[ok] show_knowledge()/show_learner() ran (no current asset path)")

    # Drive the teaching render path so list comprehensions like the
    # `steps`/`evidence` columns actually execute (catches NameErrors etc.).
    # Patch Tutor on the ui module and on the core module both, just in case.
    import expert_anything.ui.app as ui_app
    ui_app.Tutor = FakeTutor
    tutor_mod.Tutor = FakeTutor

    from expert_anything.core.teacher import TeacherModel, ConceptNote, Anomaly

    # Build a minimal fake asset + concept so _render_lesson can find them.
    concept = SimpleNamespace(
        id="c1", name="测试概念", definition="定义", normalized_name="测试概念"
    )
    asset = SimpleNamespace(
        asset_id="a1", title="测试资产",
        concepts=[concept],
        relations=[],
        learning_path=[],
        concept_by_id=lambda cid: concept if cid == "c1" else None,
    )
    app.current = asset

    # Fake Teacher Model so show_teacher + the lesson's "doubt" section run.
    note = ConceptNote(
        concept_id="c1", name="测试概念", significance="很重要",
        prerequisites=["基础A"], misconceptions=["误以为X"],
        connections=["连接Y"], external_notes=["外部：背景Z"], note="综合理解。",
    )
    anomaly = Anomaly(
        id="an1", kind="contradiction",
        description="测试概念在材料里自相矛盾", location="第二段",
        severity="high", status="open", source="internal",
    )
    app.teacher = TeacherModel(
        asset_id="a1", status="done", method="fake",
        concept_notes=[note], anomalies=[anomaly],
    )

    # Exercise the cognitive-nav view (concept notes + anomaly list render).
    app.show_teacher()
    print("[ok] show_teacher() rendered cognitive-nav view (notes + anomalies)")

    async def run_teach():
        await app._render_lesson("c1")

    asyncio.run(run_teach())
    print("[ok] _render_lesson() executed lesson render (steps/evidence/doubt ran)")

    # Drive the submit/closed-loop path: simulate a learner answer, run the
    # evaluation + incorporate_learner_signal handler end-to-end (headlessly).
    async def run_submit():
        # Rebuild the lesson so the `submit` closure is bound to the current asset.
        await app._render_lesson("c1")

        def walk(ctrl, out):
            if ctrl is None:
                return
            out.append(ctrl)
            children = getattr(ctrl, "controls", None) or []
            for ch in children:
                walk(ch, out)
            content = getattr(ctrl, "content", None)
            if content is not None:
                walk(content, out)

        all_controls = []
        for c in app.content.controls:
            walk(c, all_controls)
        submit_handler = next(
            (getattr(c, "on_click", None) for c in all_controls
             if getattr(c, "on_click", None) and getattr(c.on_click, "__name__", "") == "submit"),
            None,
        )
        assert submit_handler is not None, "could not locate submit handler"
        await submit_handler(None)
        return app.teacher

    teacher_after = asyncio.run(run_submit())
    assert teacher_after is not None, "teacher not updated after submit"
    lg = [an for an in teacher_after.anomalies if an.kind == "learner_gap"]
    assert lg, "closed-loop did not record a learner_gap anomaly"
    print("[ok] submit() closed-loop ran: learner_gap anomaly recorded (%d)" % len(lg))

    # --- style responsiveness: 图示 must actually render a diagram ----------
    def walk(ctrl, out):
        if ctrl is None:
            return
        out.append(ctrl)
        for ch in (getattr(ctrl, "controls", None) or []):
            walk(ch, out)
        content = getattr(ctrl, "content", None)
        if content is not None:
            walk(content, out)

    def has_canvas():
        """True if the lesson view contains an interactive graph (Canvas)."""
        allc = []
        for c in app.content.controls:
            walk(c, allc)
        return any(type(c).__name__ == "Canvas" for c in allc)

    # Per requirement 3, each concept now carries its own focused interactive graph
    # for every style (not only 图示), so 例子 style DOES render a concept-map now.
    assert has_canvas(), "例子 style should now render the per-concept graph (Canvas)"
    print("[ok] 例子 style: per-concept interactive graph rendered (Canvas present)")

    # switch to diagram style -> still renders the interactive graph
    app.learner["profile"] = {"goal": "g", "baseline": "novice", "style": "diagram"}
    asyncio.run(app._render_lesson("c1"))
    assert has_canvas(), "diagram style must still render the concept-map graph (Canvas)"
    print("[ok] diagram style: concept-map interactive graph rendered (Canvas present)")

    # _change_style must re-render and update the stored style
    class FakeEv:
        control = SimpleNamespace(value="steps")
    asyncio.run(app._change_style(FakeEv()))
    assert app.learner["profile"]["style"] == "steps", "change style did not persist"
    print("[ok] _change_style() persisted new style and re-rendered")

    # Sanity: no stray ft.padding. / ft.alignment. symbols compiled in
    import inspect
    src = inspect.getsource(ExpertApp)
    assert "ft.padding." not in src, "leftover ft.padding.* usage!"
    assert "ft.alignment." not in src, "leftover ft.alignment.* usage!"
    print("[ok] no leftover ft.padding.* / ft.alignment.* references")

    # FilePicker is a Service in flet 0.86.5 — must be mounted via page.services,
    # NOT page.overlay (otherwise its method listener never registers and
    # pick_files times out with "Timeout waiting for invoke method listener").
    assert app.file_picker in page.services, "FilePicker must be in page.services!"
    assert app.file_picker not in page.overlay, "FilePicker must NOT be in page.overlay!"
    print("[ok] FilePicker mounted via page.services (not overlay)")

    # --- asset deletion: files + learner traces removed cleanly --------------
    from expert_anything.core import storage as storage_mod, config as cfg_mod
    from expert_anything.core.extraction import extract_knowledge
    from expert_anything.core.learner import register_asset, record_evaluation, save as save_learner

    # create + persist one real asset, register into learner, add a history row
    del_asset = extract_knowledge(
        "# 概念A\n这是概念A的定义。\n# 概念B\n这是概念B。\n", "del_test.md", None
    )
    storage_mod.save_asset(del_asset)
    register_asset(app.learner, del_asset)
    record_evaluation(app.learner, "概念A", del_asset.asset_id, 0.3, "我的回答", "再想想")
    save_learner(app.learner)
    app.refresh_assets()
    aid = del_asset.asset_id
    assert any(a.asset_id == aid for a in app.assets), "asset should appear in list"
    assert aid in app.learner.get("history", [{}])[0].get("asset_id", ""), "history should hold asset"
    # the delete button (IconButton) must exist in the rendered list
    del_row = next(
        (c for c in app.asset_list.controls if isinstance(c, ft.Row) and c.controls), None
    )
    assert del_row is not None and any(
        getattr(c, "icon", None) == ft.Icons.DELETE_OUTLINE for c in del_row.controls
    ), "delete button missing from asset list row"
    print("[ok] asset list renders a delete button per asset")

    # perform deletion
    app.delete_asset_by_id(aid)
    assert not (cfg_mod.ASSETS_DIR / f"{aid}.json").exists(), "asset file must be deleted"
    assert not (cfg_mod.ASSETS_DIR / f"teacher_{aid}.json").exists(), "teacher file must be deleted"
    assert aid not in app.learner.get("assets", {}), "asset entry must be removed from learner"
    assert all(
        aid not in (c.get("sources") or []) for c in app.learner.get("concepts", {}).values()
    ), "concept sources not cleaned"
    assert all(
        h.get("asset_id") != aid for h in app.learner.get("history", [])
    ), "history not cleaned"
    print("[ok] delete_asset_by_id() removed asset+teacher files and all learner traces")

    # confirm-dialog wiring: opening it calls page.open
    storage_mod.save_asset(del_asset)
    register_asset(app.learner, del_asset)
    save_learner(app.learner)
    app.refresh_assets()
    app._confirm_delete(aid, "测试资产")
    assert page.shown is not None, "confirm dialog should be shown via page.show_dialog"
    print("[ok] _confirm_delete() opens a confirmation dialog via page.show_dialog")

    # --- import progress flow: a progress view is shown + thread-safe plumbing ---
    # Force the deterministic (no-LLM) path so the test stays fast and offline.
    app.llm = None
    app._pending_bytes = None
    app._paste.value = "# 概念A\n这是概念A的定义。\n# 概念B\n这是概念B的内容。\n"
    app._fname.value = "progress_test.md"
    seen_progress_view = {"called": False}
    orig_render_progress = app._render_progress_view

    def spy_render(message):
        seen_progress_view["called"] = True
        return orig_render_progress(message)

    app._render_progress_view = spy_render

    async def run_import():
        await app._do_import(None)

    asyncio.run(run_import())
    assert seen_progress_view["called"], "import must show a progress view"
    assert app._busy is False, "busy flag must be reset after import finishes"
    assert app.current is not None, "current asset must be set after import"
    assert app._progress_text.value.startswith("完成"), "progress should end with 完成"
    assert page.updated > 0, "page.update() must be called during the progress run"
    print("[ok] _do_import() showed progress view, ran to completion, reset busy flag")

    # re-entrancy guard: a second import while busy is ignored (no double work)
    app._busy = True
    cur = app.current
    asyncio.run(run_import())
    assert app.current is cur, "re-entrant import must be ignored (no duplicate runs)"
    app._busy = False
    print("[ok] _do_import() re-entrancy guard prevents duplicate runs")

    # --- 阅读原文 view: renders original text + jumps to a concept's evidence ---
    app.current = del_asset

    def collect_text(ctrl, out):
        if ctrl is None:
            return
        if isinstance(ctrl, ft.Text):
            out.append(ctrl.value or "")
        for ch in (getattr(ctrl, "controls", None) or []):
            collect_text(ch, out)
        content = getattr(ctrl, "content", None)
        if content is not None:
            collect_text(content, out)

    def find_by_key(ctrl, key, out):
        if ctrl is None:
            return
        if getattr(ctrl, "key", None) == key:
            out.append(ctrl)
        for ch in (getattr(ctrl, "controls", None) or []):
            find_by_key(ch, key, out)
        content = getattr(ctrl, "content", None)
        if content is not None:
            find_by_key(content, key, out)

    # top-level reading view (no highlight) must render the source as a
    # STRUCTURED document (one block per paragraph), not a single giant blob.
    app.show_source()
    t1 = []
    collect_text(app.content, t1)
    for para in ["# 概念A", "这是概念A的定义。", "# 概念B", "这是概念B。"]:
        assert any(t == para for t in t1), \
            f"source paragraph not rendered as its own block: {para!r}"
    print("[ok] show_source() renders a structured document (one block per paragraph)")

    # jumping from a concept highlights its first evidence snippet (key=src-hl)
    first_c = del_asset.concepts[0]
    hl = first_c.evidence[0] if first_c.evidence else None
    app._open_source_for_concept(first_c.id)
    found = []
    if hl:
        find_by_key(app.content, "src-hl", found)
        assert found, "jump-to-evidence should highlight the snippet (key=src-hl)"
        hltext = []
        collect_text(found[0], hltext)
        assert any(hl[:15] in t for t in hltext), \
            "highlighted text should be the concept's evidence snippet"
    print("[ok] _open_source_for_concept() highlighted concept evidence (key=src-hl)")

    # --- back navigation: reader must offer a way back to the knowledge model --
    def collect_btns(ctrl, out):
        if ctrl is None:
            return
        if isinstance(ctrl, (ft.TextButton, ft.ElevatedButton)):
            out.append(ctrl)
        for ch in (getattr(ctrl, "controls", None) or []):
            collect_btns(ch, out)
        content = getattr(ctrl, "content", None)
        if content is not None:
            collect_btns(content, out)

    from expert_anything.core.i18n import t as _t, set_lang as _set_lang

    def collect_images(ctrl, out):
        if ctrl is None:
            return
        if isinstance(ctrl, ft.Image):
            out.append(ctrl)
        for ch in (getattr(ctrl, "controls", None) or []):
            collect_images(ch, out)
        content = getattr(ctrl, "content", None)
        if content is not None and not isinstance(content, str):
            collect_images(content, out)

    def collect_type(ctrl, type_name, out):
        """Recursively collect controls whose Python type name matches."""
        if ctrl is None:
            return
        if type(ctrl).__name__ == type_name:
            out.append(ctrl)
        for ch in (getattr(ctrl, "controls", None) or []):
            collect_type(ch, type_name, out)
        content = getattr(ctrl, "content", None)
        if content is not None and not isinstance(content, str):
            collect_type(content, type_name, out)

    # full-text mode
    app.show_source()
    btns = []
    collect_btns(app.content, btns)
    assert any(b.content == _t("back_to_km") for b in btns), \
        "full-text reader must show a 'back to knowledge model' button"
    # focused mode (from a concept) must also show it
    app._open_source_for_concept(first_c.id)
    btns2 = []
    collect_btns(app.content, btns2)
    assert any(b.content == _t("back_to_km") for b in btns2), \
        "focused reader must show a 'back to knowledge model' button"
    print("[ok] reader offers 'back to knowledge model' in both full and focused modes")

    # --- i18n: switching language changes rendered strings --------------------
    _set_lang("en")
    app.show_import()
    t_en = []
    collect_text(app.content, t_en)
    assert any("Import Knowledge" in s for s in t_en), "English UI: import title not translated"
    _set_lang("zh-CN")
    app.show_import()
    t_zh = []
    collect_text(app.content, t_zh)
    assert any("导入知识资产" in s for s in t_zh), "Chinese UI: import title not restored"
    print("[ok] language switch re-renders UI strings (zh-CN <-> en)")

    # --- sidebar menu must localize on language change (issue: it stayed zh) --
    def collect_labels(ctrl, out):
        if ctrl is None:
            return
        if isinstance(ctrl, ft.TextButton) and isinstance(getattr(ctrl, "label", None), str):
            out.append(ctrl.label)
        if isinstance(ctrl, ft.TextButton) and isinstance(getattr(ctrl, "content", None), str):
            out.append(ctrl.content)
        if isinstance(ctrl, ft.Dropdown) and isinstance(getattr(ctrl, "label", None), str):
            out.append(ctrl.label)
        if isinstance(ctrl, ft.Text) and isinstance(getattr(ctrl, "value", None), str):
            out.append(ctrl.value)
        for ch in (getattr(ctrl, "controls", None) or []):
            collect_labels(ch, out)
        content = getattr(ctrl, "content", None)
        if content is not None and not isinstance(content, str):
            collect_labels(content, out)

    _set_lang("zh-CN")
    app._rebuild_sidebar()
    sb = []
    collect_labels(app._sidebar, sb)
    assert any("知识模型" in s for s in sb), "sidebar should show 知识模型 in zh-CN"
    _set_lang("en")
    app._rebuild_sidebar()
    sb_en = []
    collect_labels(app._sidebar, sb_en)
    assert any("Knowledge Model" in s for s in sb_en), "sidebar must switch to English on language change"
    _set_lang("zh-CN")
    app._rebuild_sidebar()
    print("[ok] sidebar menu localizes on language switch (zh-CN <-> en)")

    # --- knowledge model is a hierarchy/network, not a flat grid (issue 1) ----
    from expert_anything.core.models import KnowledgeAsset as _KA, Concept as _C, Relation as _R
    TXT = ("机器学习是人工智能的一个分支。\n"
           "共享片段XYZ 是机器学习的重要应用之一。\n"
           "监督学习利用带标签的样本来训练模型。\n"
           "过拟合指模型在训练集表现好但泛化差。")
    ca = _C(id="c1", name="机器学习", definition="人工智能的分支",
            evidence=["机器学习是人工智能的一个分支。", "共享片段XYZ"])
    cb = _C(id="c2", name="监督学习", definition="用标签训练",
            evidence=["共享片段XYZ", "监督学习利用带标签的样本来训练模型。"])
    cc = _C(id="c3", name="过拟合", definition="泛化差",
            evidence=["过拟合指模型在训练集表现好但泛化差。"])
    r1 = _R(id="r1", source="c1", target="c2", label="包含", type="contains")
    r2 = _R(id="r2", source="c2", target="c3", label="相关", type="related")
    hier = _KA(asset_id="aX", type="md", title="测试层级", source_name="t.md",
               created_at="2020", source_text=TXT, concepts=[ca, cb, cc],
               relations=[r1, r2], learning_path=["c1", "c2", "c3"],
               method="llm_extraction_v1")
    app.current = hier
    app.show_knowledge()
    kt = []
    collect_text(app.content, kt)
    assert any("机器学习" in s for s in kt), "knowledge view must show 机器学习"
    assert any("监督学习" in s for s in kt), "knowledge view must show child 监督学习 (hierarchy)"
    assert any("过拟合" in s for s in kt), "knowledge view must show 过拟合"
    assert any("概念结构" in s or "Concept structure" in s for s in kt), \
        "must render a concept-structure (hierarchy) section"
    print("[ok] knowledge model renders as a hierarchy/network, not a flat grid")

    # --- one-to-many: a concept maps to several source passages (issue 2) -----
    app._open_source_for_concept("c1")  # c1 has 2 evidence snippets
    ev0, ev1 = [], []
    find_by_key(app.content, "evsec-0", ev0)
    find_by_key(app.content, "evsec-1", ev1)
    assert ev0 and ev1, "concept reader should list multiple evidence sections (one-to-many)"
    print("[ok] concept reader shows one-to-many evidence passages (evsec-0 / evsec-1)")

    # --- many-to-one: a shared passage is annotated with all its concepts ----
    app.show_source()  # full mode -> annotate paragraphs referenced by concepts
    many = []
    find_by_key(app.content, "many2one", many)
    assert many, "full reader must annotate shared passages with many-to-one anchor chips"
    print("[ok] full reader shows many-to-one anchor chips on shared passages")

    # --- issue 2: every concept offers a '讲解' (learn) button in the tree ----
    app.current = hier
    app.show_knowledge()
    kb = []
    collect_btns(app.content, kb)
    assert any(getattr(b, "content", None) == _t("learn_concept") for b in kb), \
        "knowledge tree must offer a per-concept '讲解' (learn) button"
    print("[ok] knowledge tree: per-concept '讲解' button present")

    # --- issue 3: per-concept focused interactive knowledge graph view -------
    app.show_concept_map(concept_id="c1")
    ccanv = []
    collect_type(app.content, "Canvas", ccanv)
    assert ccanv, "concept map view must render an interactive graph (Canvas)"
    cviewers = []
    collect_type(app.content, "InteractiveViewer", cviewers)
    assert cviewers, "concept map must be pan/zoomable (InteractiveViewer)"
    cb = []
    collect_btns(app.content, cb)
    assert any(getattr(b, "content", None) == _t("back_to_km_from_graph") for b in cb), \
        "concept map view must offer a back-to-knowledge-model button"
    print("[ok] concept map view: interactive graph + pan/zoom + back navigation")

    # --- issue 2: clicking a concept opens that concept's lesson --------------
    app.learner["profile"] = {"goal": "g", "baseline": "novice", "style": "example"}
    asyncio.run(app.show_teach(None, concept_id="c2"))
    assert app.teach_state.get("concept_id") == "c2", "learn must open the requested concept"
    c2t = []
    collect_text(app.content, c2t)
    assert any("监督学习" in s for s in c2t), "lesson for c2 should show its own name 监督学习"
    print("[ok] per-concept learn: opens the requested concept's lesson")

    # --- issue 5: learner model shows mastery map + recommended next ----------
    register_asset(app.learner, hier)
    record_evaluation(app.learner, "机器学习", hier.asset_id, 0.2, "我答了", "再想想")
    save_learner(app.learner)
    app.show_learner()
    lcanv = []
    collect_type(app.content, "Canvas", lcanv)
    assert lcanv, "learner model must render an interactive graph (Canvas)"
    ltxt = []
    collect_text(app.content, ltxt)
    assert any(_t("recommend_next") in s for s in ltxt), "learner model must show 推荐下一步"
    # adaptive path must be a *ranked queue* (>=2 ranked cards), not a single pick.
    # rank badges render as standalone short digit strings.
    rank_badges = [s for s in ltxt if s.strip().isdigit() and len(s.strip()) <= 2]
    assert len(rank_badges) >= 2, f"adaptive path should rank >=2 concepts, got {rank_badges!r}"
    print("[ok] learner model: mastery map + adaptive ranked queue rendered", rank_badges)

    # --- issue 5: cognitive nav hub graph + learn/explore buttons -------------
    # Give the current asset (hier) a proper self-learning Teacher Model so the
    # concept notes and anomaly links resolve against hier's concept ids.
    note_x = ConceptNote(concept_id="c1", name="机器学习", significance="很重要")
    app.teacher = TeacherModel(
        asset_id="aX", status="done", method="fake",
        concept_notes=[note_x], anomalies=[],
    )
    app.teacher.anomalies.append(Anomaly(
        id="an-h", kind="logical_gap",
        description="机器学习与监督学习的关系在文中未充分说明",
        location="机器学习", severity="medium", status="open", source="internal",
    ))
    app.show_teacher()
    tcanv = []
    collect_type(app.content, "Canvas", tcanv)
    assert tcanv, "cognitive nav must render an interactive hub graph (Canvas)"
    tbtns = []
    collect_btns(app.content, tbtns)
    assert any(getattr(b, "content", None) == _t("learn_concept") for b in tbtns), \
        "cognitive nav concept notes must offer a '讲解' button"
    assert any(getattr(b, "content", None) == _t("explore_anomaly") for b in tbtns), \
        "cognitive nav must offer '前往探索' for anomaly-linked concepts"
    print("[ok] cognitive nav: hub graph + learn/explore buttons rendered")


if __name__ == "__main__":
    main()
    print("\nSELFTEST PASSED")
