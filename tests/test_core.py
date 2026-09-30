"""Core engine tests: parsers, extraction, models, learner, tutor, teacher.

These run without GUI and without an LLM key (deterministic paths only).
"""
import io
import sys
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expert_anything.core import learner, storage
from expert_anything.core.extraction import (
    extract_knowledge,
    _assemble,
    _extract_with_llm,
    _fallback,
)
from expert_anything.core.learner import (
    adaptive_path,
    dependency_chain,
    due_for_review,
    mastery_prediction,
    normalize,
    record_evaluation,
    register_asset,
    review_gain,
    set_study_goal,
    study_goal_progress,
    weaknesses,
)
from expert_anything.core.models import Concept, KnowledgeAsset, Relation
from expert_anything.core.parsers import extract_from_bytes
from expert_anything.core.teacher import (
    Anomaly,
    TeacherModel,
    anomaly_concept_ids,
    build_teacher_model,
    incorporate_comparison,
    record_learner_question,
)
from expert_anything.core.tutor import Tutor

SAMPLE = """# 设计 Agent Memory

## 为什么需要 Memory
Agent 在执行多轮任务时会丢失上下文，Memory 让 Agent 跨回合保留关键信息。

## Memory 的类型
有短期记忆（当前会话）和长期记忆（写入外部存储如向量库）。

## 与 Context Engineering 的关系
Memory 是 Context Engineering 的一部分，负责在合适时机把信息塞回上下文。

## 实践建议
先定义要记什么，再选择存储介质，最后做召回与压缩。
"""



def _minimal_pdf(text: bytes) -> bytes:
    """Build a valid single-page PDF with a real xref table (pypdf-readable)."""
    stream = b"BT /F1 12 Tf 72 100 Td (" + text + b") Tj ET\n"
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        (b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R"
         b"/Resources<</Font<</F1 5 0 R>>>>>>"),
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"endstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj".encode() + body + b"endobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref_pos}\n%%EOF".encode()
    return bytes(out)

# --------------------------------------------------------------------------- #
# parsers
# --------------------------------------------------------------------------- #
class TestParsers(unittest.TestCase):
    def test_txt_extraction(self):
        text = extract_from_bytes("hello 中文".encode("utf-8"), "a.txt")
        self.assertIn("hello", text)

    def test_md_extraction(self):
        text = extract_from_bytes(b"# Title\n\nbody text here", "a.md")
        self.assertIn("body text", text)

    def test_docx_extraction(self):
        buf = io.BytesIO()
        xml = (
            '<?xml version="1.0"?><w:document><w:body>'
            "<w:p><w:r><w:t>第一个段落</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>第二个段落</w:t></w:r></w:p>"
            "</w:body></w:document>"
        )
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", xml)
        text = extract_from_bytes(buf.getvalue(), "a.docx")
        self.assertIn("第一个段落", text)
        self.assertIn("第二个段落", text)

    def test_epub_extraction(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("OEBPS/ch1.xhtml", "<html><body><p>epub 正文内容</p></body></html>")
        text = extract_from_bytes(buf.getvalue(), "a.epub")
        self.assertIn("epub 正文内容", text)

    def test_epub_uses_spine_order_and_preserves_blocks(self):
        buf = io.BytesIO()
        container = (
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OPS/package.opf"/></rootfiles></container>'
        )
        opf = (
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '<manifest><item id="late" href="late.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            '<item id="first" href="first.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="first"/><itemref idref="late"/><itemref idref="nav"/></spine>'
            '</package>'
        )
        with zipfile.ZipFile(buf, "w") as z:
            # Deliberately write in the wrong order: archive order is not book order.
            z.writestr("OPS/late.xhtml", "<html><body><h1>第二章</h1><p>后面的段落。</p></body></html>")
            z.writestr("META-INF/container.xml", container)
            z.writestr("OPS/nav.xhtml", "<html><body><nav>目录 噪声</nav></body></html>")
            z.writestr("OPS/package.opf", opf)
            z.writestr("OPS/first.xhtml", "<html><head><title>隐藏标题</title></head><body><h1>第一章</h1><p>第一段。</p><p>第二段。</p></body></html>")
        text = extract_from_bytes(buf.getvalue(), "book.epub")
        self.assertLess(text.index("第一章"), text.index("第二章"))
        self.assertIn("第一段。\n第二段。", text)
        self.assertNotIn("目录 噪声", text)

    def test_epub_headings_are_preserved_for_structural_fallback(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(
                "book.xhtml",
                "<html><body><h1>第 1 章 总览</h1><p>章节正文。</p>"
                "<h2>1.1 核心概念</h2><p>核心概念正文。</p>"
                "<p>1.2 这是一段正文，不是标题。</p></body></html>",
            )
        text = extract_from_bytes(buf.getvalue(), "book.epub")
        asset = extract_knowledge(text, "book.epub", llm=None)
        self.assertEqual(asset.concepts[0].name, "总览")
        self.assertIn("核心概念", [c.name for c in asset.concepts])
        self.assertNotIn("这是一段正文，不是标题", [c.name for c in asset.concepts])

    def test_html_extraction(self):
        text = extract_from_bytes(b"<html><body><p>html text</p></body></html>", "a.html")
        self.assertIn("html text", text)

    def test_pdf_extraction(self):
        pdf = _minimal_pdf(b"PDF text content 123")
        text = extract_from_bytes(pdf, "a.pdf")
        self.assertIn("PDF text content", text)

    def test_unknown_suffix_falls_back_to_text(self):
        text = extract_from_bytes("plain".encode("utf-8"), "a.xyz")
        self.assertEqual(text, "plain")


# --------------------------------------------------------------------------- #
# extraction (deterministic fallback)
# --------------------------------------------------------------------------- #
class TestExtraction(unittest.TestCase):
    def test_fallback_generates_grounded_concepts(self):
        asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)
        self.assertTrue(asset.concepts)
        self.assertEqual(asset.method, "deterministic_fallback_v1")
        # concept names must appear in the source
        for c in asset.concepts:
            self.assertIn(c.name.lower(), SAMPLE.lower(), f"concept {c.name} not in source")

    def test_fallback_path_covers_all_concepts(self):
        asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)
        self.assertEqual(set(asset.learning_path), {c.id for c in asset.concepts})

    def test_empty_text_raises(self):
        with self.assertRaises(ValueError):
            extract_knowledge("   ", "a.txt", llm=None)

    def test_evidence_is_real_source_text(self):
        asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)
        for c in asset.concepts:
            for ev in c.evidence:
                self.assertIn(ev, SAMPLE, "evidence not literally in source")

    def test_fallback_stamps_source_locations(self):
        asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)
        located = 0
        for c in asset.concepts:
            if not c.evidence:
                continue
            self.assertTrue(c.locations, f"concept {c.name!r} evidence has no location")
            for loc in c.locations:
                self.assertGreaterEqual(loc.char_start, 0)
                self.assertGreater(loc.char_end, loc.char_start)
                self.assertGreaterEqual(loc.line, 1)
                self.assertIsInstance(loc.chapter, str)
                # the recorded span must map back to one of the concept's evidence
                self.assertIn(
                    SAMPLE[loc.char_start:loc.char_end],
                    c.evidence,
                    "recorded span must be one of the concept's evidence",
                )
            located += 1
        self.assertGreater(located, 0, "no grounded concept was located")

    def test_assemble_stamps_locations_from_llm_dict(self):
        text = "Alpha 是第一个概念。Beta 依赖 Alpha 才能运行。"
        data = {
            "concepts": [
                {"name": "Alpha", "definition": "第一个概念", "evidence": ["Alpha 是第一个概念。"]},
                {"name": "Beta", "definition": "第二个概念", "evidence": ["Beta 依赖 Alpha 才能运行。"]},
            ],
            "relations": [{"source": "Alpha", "target": "Beta", "label": "依赖", "evidence": "Beta 依赖 Alpha"}],
            "learning_path": ["Alpha", "Beta"],
        }
        asset = _assemble(data, text, "x.md", "test")
        self.assertEqual(len(asset.relations), 1)
        self.assertIn(asset.relations[0].evidence, text)
        by_name = {c.name: c for c in asset.concepts}
        alpha = by_name["Alpha"]
        self.assertTrue(alpha.locations, "Alpha should have a source location")
        loc = alpha.locations[0]
        self.assertEqual(text[loc.char_start:loc.char_end], "Alpha 是第一个概念。")
        self.assertEqual(loc.line, 1)
        # HTML/JSON round-trip preserves locations
        alpha2 = Concept.from_dict(alpha.to_dict())
        self.assertEqual(len(alpha2.locations), len(alpha.locations))
        self.assertEqual(alpha2.locations[0].char_start, loc.char_start)

    def test_assemble_rejects_concept_without_grounded_evidence(self):
        text = "正文只讨论其他内容，没有提供目标术语的解释。"
        data = {
            "concepts": [
                {
                    "name": "Alpha",
                    "definition": "LLM 编造的定义。",
                    "evidence": ["这段证据并不存在。"],
                },
            ],
        }
        asset = _assemble(data, text, "x.md", "test")
        self.assertEqual(asset.concepts, [])
        self.assertEqual(asset.learning_path, [])

    def test_assemble_replaces_ungrounded_definition_with_evidence(self):
        text = "Alpha 是基础概念。"
        data = {
            "concepts": [
                {
                    "name": "Alpha",
                    "definition": "Alpha 是宇宙中最强大的机制。",
                    "evidence": [text],
                },
            ],
        }
        asset = _assemble(data, text, "x.md", "test")
        self.assertEqual(asset.concepts[0].definition, text)
        self.assertIn(asset.concepts[0].definition, text)

    def test_assemble_rejects_relation_without_grounded_evidence(self):
        text = "Alpha 是基础概念。Beta 是另一个概念。"
        data = {
            "concepts": [
                {"name": "Alpha", "evidence": ["Alpha 是基础概念。"]},
                {"name": "Beta", "evidence": ["Beta 是另一个概念。"]},
            ],
            "relations": [
                {
                    "source": "Alpha",
                    "target": "Beta",
                    "label": "依赖",
                    "evidence": "Beta 必须先依赖 Alpha 才能工作。",
                },
            ],
        }
        asset = _assemble(data, text, "x.md", "test")
        self.assertEqual(asset.relations, [])

    def test_chunked_extraction_merges_in_source_order_not_completion_order(self):
        from unittest import mock

        text = "A" * 9000 + "\n" + "B" * 2000
        chunks = ["chunk-0", "chunk-1"]
        results = [
            {
                "concepts": [{"name": "Alpha", "definition": "Alpha", "evidence": ["A" * 80]}],
                "relations": [],
                "learning_path": ["Alpha"],
            },
            {
                "concepts": [{"name": "Beta", "definition": "Beta", "evidence": ["B" * 80]}],
                "relations": [],
                "learning_path": ["Beta"],
            },
        ]

        class _Future:
            def __init__(self, index):
                self.index = index

            def exception(self):
                return None

            def result(self):
                return results[self.index]

        class _Pool:
            def __init__(self, max_workers):
                self.max_workers = max_workers

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def submit(self, fn, llm, chunk):
                return _Future(chunks.index(chunk))

        with mock.patch("expert_anything.core.extraction._split_text", return_value=chunks), \
             mock.patch("expert_anything.core.extraction.concurrent.futures.ThreadPoolExecutor", _Pool), \
             mock.patch(
                 "expert_anything.core.extraction.concurrent.futures.as_completed",
                 side_effect=lambda futures: list(reversed(futures)),
             ):
            asset = _extract_with_llm(text, "long.txt", object())

        self.assertEqual([c.name for c in asset.concepts], ["Alpha", "Beta"])
        self.assertEqual(
            [asset.concept_by_id(cid).name for cid in asset.learning_path],
            ["Alpha", "Beta"],
        )

    def test_concept_from_dict_tolerates_missing_locations(self):
        c = Concept.from_dict({"name": "X"})
        self.assertEqual(c.locations, [])
        self.assertIn("locations", c.to_dict())


# --------------------------------------------------------------------------- #
# models round-trip
# --------------------------------------------------------------------------- #
class TestModels(unittest.TestCase):
    def test_asset_round_trip(self):
        asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)
        d = asset.to_dict()
        asset2 = KnowledgeAsset.from_dict(d)
        self.assertEqual(asset2.asset_id, asset.asset_id)
        self.assertEqual(len(asset2.concepts), len(asset.concepts))
        self.assertEqual(asset2.concepts[0].name, asset.concepts[0].name)
        self.assertEqual(asset2.concepts[0].evidence, asset.concepts[0].evidence)

    def test_public_dict_hides_source(self):
        asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)
        self.assertNotIn("source_text", asset.public_dict())

    def test_concept_lookup(self):
        asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)
        c = asset.concepts[0]
        self.assertEqual(asset.concept_by_id(c.id).id, c.id)
        self.assertEqual(asset.concept_by_name(c.name).id, c.id)


# --------------------------------------------------------------------------- #
# learner model
# --------------------------------------------------------------------------- #
def _asset_with_relations():
    return KnowledgeAsset(
        asset_id="t1",
        type="text",
        title="T",
        source_name="t.md",
        created_at="",
        source_text=SAMPLE,
        concepts=[
            Concept(id="c1", name="A", definition="d", evidence=["A 是基础"]),
            Concept(id="c2", name="B", definition="d", evidence=["B 依赖 A"]),
            Concept(id="c3", name="C", definition="d", evidence=["C 依赖 B"]),
        ],
        relations=[
            Relation(id="r1", source="c1", target="c2", label="依赖"),
            Relation(id="r2", source="c2", target="c3", label="依赖"),
        ],
        learning_path=["c1", "c2", "c3"],
    )


class TestLearner(unittest.TestCase):
    def test_register_asset(self):
        state = {}
        register_asset(state, _asset_with_relations())
        self.assertEqual(len(state["concepts"]), 3)
        self.assertIn("t1", state["assets"])

    def test_review_gain_measures_consolidation(self):
        state = {"concepts": {}, "history": []}
        # oldest-first insertion (record_evaluation prepends)
        record_evaluation(state, "A", "t1", 0.4, "a", "f", meta={"review": False})
        record_evaluation(state, "A", "t1", 0.6, "a", "f", meta={"review": False})
        record_evaluation(state, "A", "t1", 0.9, "a", "f", meta={"review": True})
        record_evaluation(state, "A", "t1", 0.8, "a", "f", meta={"review": True})
        g = review_gain(state)
        self.assertEqual(g["measurable"], 1)
        self.assertEqual(g["review_count"], 2)
        row = g["concepts"][0]
        self.assertEqual(row["baseline"], 0.6)  # best first-time
        self.assertEqual(row["review_avg"], 0.85)
        self.assertEqual(row["gain"], 0.25)

    def test_review_gain_skips_concepts_without_baseline(self):
        state = {"concepts": {}, "history": []}
        record_evaluation(state, "B", "t1", 0.9, "a", "f", meta={"review": True})
        g = review_gain(state)
        self.assertEqual(g["measurable"], 0)
        self.assertEqual(g["review_count"], 1)

    def test_review_gain_legacy_records_count_as_first_time(self):
        state = {"concepts": {}, "history": []}
        record_evaluation(state, "A", "t1", 0.5, "a", "f")  # no meta
        record_evaluation(state, "A", "t1", 0.7, "a", "f", meta={"channel": "quiz"})
        record_evaluation(state, "A", "t1", 0.9, "a", "f", meta={"review": True})
        g = review_gain(state)
        self.assertEqual(g["measurable"], 1)
        self.assertEqual(g["concepts"][0]["baseline"], 0.7)

    def test_mastery_prediction_ignores_review_channel(self):
        # teaching trend is rising; a forgetting dip in review must not
        # drag the forecast ("needs review" != "will never learn it")
        # history is newest-first: teach 0.5 (new), teach 0.3 (old),
        # review dip 0.2 skipped -> teaching channel 0.3 -> 0.5 rising
        state = {"concepts": {}, "history": [
            {"concept": "LMP", "score": 0.2,
             "meta": {"channel": "answer", "review": True}},
            {"concept": "LMP", "score": 0.5},
            {"concept": "LMP", "score": 0.3},
        ]}
        pred = mastery_prediction(state, "LMP")
        self.assertEqual(pred["trend"], "rising")

    def test_mastery_prediction_teaching_falling_still_detected(self):
        # newest-first: 0.4 (new) ... 0.8 (old) -> falling
        state = {"concepts": {}, "history": [
            {"concept": "LMP", "score": 0.4},
            {"concept": "LMP", "score": 0.6},
            {"concept": "LMP", "score": 0.8},
        ]}
        pred = mastery_prediction(state, "LMP")
        self.assertEqual(pred["trend"], "falling")

    def test_stuck_concepts_ignores_review_channel(self):
        from expert_anything.core.learner import stuck_concepts

        # first-time learning passed, then reviews failed — that is normal
        # forgetting (gain_weak handles it), NOT a teaching-strategy failure
        state = {"concepts": {}, "history": [
            {"key": "k", "concept": "LMP", "score": 0.85,
             "meta": {"channel": "answer"}},
            {"key": "k", "concept": "LMP", "score": 0.2,
             "meta": {"channel": "quiz", "review": True}},
            {"key": "k", "concept": "LMP", "score": 0.3,
             "meta": {"channel": "answer", "review": True}},
            {"key": "k", "concept": "LMP", "score": 0.25,
             "meta": {"channel": "practice", "review": True}},
        ]}
        self.assertEqual(stuck_concepts(state), [])

    def test_stuck_concepts_fires_on_teaching_channel(self):
        from expert_anything.core.learner import stuck_concepts

        state = {"concepts": {}, "history": [
            {"key": "k", "concept": "LMP", "score": 0.2},
            {"key": "k", "concept": "LMP", "score": 0.3},
            {"key": "k", "concept": "LMP", "score": 0.25},
        ]}
        out = stuck_concepts(state)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "LMP")

    def test_style_effectiveness_separates_review_bucket(self):
        from expert_anything.core.learner import style_effectiveness

        state = {"concepts": {}, "history": [
            {"concept": "A", "score": 0.5, "meta": {"style": "analogy"}},
            # review of the same concept under the same style: high score
            # is retention evidence, must NOT lift the teaching average
            {"concept": "A", "score": 1.0, "meta": {"style": "analogy", "review": True}},
        ]}
        eff = style_effectiveness(state)
        self.assertEqual(eff["analogy"]["avg"], 0.5)
        self.assertEqual(eff["analogy"]["count"], 1)
        self.assertEqual(eff["analogy"]["review"]["avg"], 1.0)
        self.assertEqual(eff["analogy"]["review"]["count"], 1)

    def test_style_effectiveness_review_only_style_kept(self):
        from expert_anything.core.learner import style_effectiveness

        state = {"concepts": {}, "history": [
            {"concept": "B", "score": 0.7, "meta": {"style": "step", "review": True}},
        ]}
        eff = style_effectiveness(state)
        # review-only style stays visible in its own bucket instead of
        # appearing as a (misleading) teaching-style entry
        self.assertIn("step", eff)
        self.assertEqual(eff["step"]["count"], 0)
        self.assertEqual(eff["step"]["review"]["count"], 1)
        self.assertEqual(eff["step"]["review"]["avg"], 0.7)

    def test_due_for_review_positive_gain_stretches_interval(self):
        from datetime import datetime, timedelta, timezone

        state = {"concepts": {}, "history": []}
        record_evaluation(state, "节点电价", "a", 0.5, "a", "f")
        record_evaluation(state, "节点电价", "a", 0.9, "a", "f",
                          meta={"review": True})
        record_evaluation(state, "节点电价", "a", 0.95, "a", "f",
                          meta={"review": True})
        # push updated_at 5 days back: without stretch the concept would be
        # due (weak base interval 1d), with stretch (gain>=0.15, n>=2) it
        # must NOT be due yet
        now = datetime.now(timezone.utc)
        state["concepts"]["节点电价"]["updated_at"] = (
            now - timedelta(days=5)
        ).isoformat()
        due = [d for d in due_for_review(state) if d["name"] == "节点电价"]
        self.assertEqual(due, [])

    def test_due_for_review_negative_gain_shortens_interval(self):
        from datetime import datetime, timedelta, timezone

        state = {"concepts": {}, "history": []}
        record_evaluation(state, "风险对冲", "a", 0.9, "a", "f")
        record_evaluation(state, "风险对冲", "a", 0.4, "a", "f",
                          meta={"review": True})
        now = datetime.now(timezone.utc)
        state["concepts"]["风险对冲"]["updated_at"] = (
            now - timedelta(days=1, seconds=10)
        ).isoformat()
        due = [d for d in due_for_review(state) if d["name"] == "风险对冲"]
        self.assertEqual(len(due), 1)
        self.assertTrue(due[0]["gain_weak"])
        self.assertLessEqual(due[0]["interval"], 1.0)

    def test_due_for_review_negative_gain_sorts_first(self):
        from datetime import datetime, timedelta, timezone

        state = {"concepts": {}, "history": []}
        # normal concept: very urgent (30 days overdue)
        record_evaluation(state, "普通概念", "a", 0.4, "a", "f")
        # review-ineffective concept: just crossed its 1-day interval
        record_evaluation(state, "风险对冲", "a", 0.9, "a", "f")
        record_evaluation(state, "风险对冲", "a", 0.4, "a", "f",
                          meta={"review": True})
        now = datetime.now(timezone.utc)
        state["concepts"]["普通概念"]["updated_at"] = (
            now - timedelta(days=31)
        ).isoformat()
        state["concepts"]["风险对冲"]["updated_at"] = (
            now - timedelta(days=1, seconds=10)
        ).isoformat()
        due = due_for_review(state)
        self.assertEqual(due[0]["name"], "风险对冲")

    def test_incorporate_review_gain_signal_negative(self):
        from expert_anything.core.models import Concept, KnowledgeAsset
        from expert_anything.core.teacher import (
            TeacherModel,
            incorporate_review_gain_signal,
        )

        asset = KnowledgeAsset(
            asset_id="a1",
            type="text",
            title="T",
            source_name="t.md",
            created_at="",
            concepts=[Concept(id="c1", name="节点电价", definition="d", evidence=["e"])],
            relations=[],
        )
        state = {"concepts": {}, "history": []}
        record_evaluation(state, "节点电价", "a1", 0.9, "a", "f")
        record_evaluation(state, "节点电价", "a1", 0.4, "a", "f",
                          meta={"review": True})
        teacher = TeacherModel(asset_id="a1")
        teacher = incorporate_review_gain_signal(asset, teacher, "c1", state)
        gaps = [a for a in teacher.anomalies if a.kind == "learner_gap"]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].location, "节点电价")
        self.assertTrue(any("复习无效" in s
                            for s in teacher.concept_notes[0].learner_signals))
        # idempotent: second call must not duplicate
        teacher = incorporate_review_gain_signal(asset, teacher, "c1", state)
        gaps = [a for a in teacher.anomalies if a.kind == "learner_gap"]
        self.assertEqual(len(gaps), 1)

    def test_incorporate_review_gain_signal_positive_noop(self):
        from expert_anything.core.models import Concept, KnowledgeAsset
        from expert_anything.core.teacher import (
            TeacherModel,
            incorporate_review_gain_signal,
        )

        asset = KnowledgeAsset(
            asset_id="a1",
            type="text",
            title="T",
            source_name="t.md",
            created_at="",
            concepts=[Concept(id="c1", name="节点电价", definition="d", evidence=["e"])],
            relations=[],
        )
        state = {"concepts": {}, "history": []}
        record_evaluation(state, "节点电价", "a1", 0.4, "a", "f")
        record_evaluation(state, "节点电价", "a1", 0.9, "a", "f",
                          meta={"review": True})
        teacher = TeacherModel(asset_id="a1")
        teacher = incorporate_review_gain_signal(asset, teacher, "c1", state)
        self.assertEqual(teacher.anomalies, [])

    def test_incorporate_review_gain_signal_no_baseline_noop(self):
        from expert_anything.core.models import Concept, KnowledgeAsset
        from expert_anything.core.teacher import (
            TeacherModel,
            incorporate_review_gain_signal,
        )

        asset = KnowledgeAsset(
            asset_id="a1",
            type="text",
            title="T",
            source_name="t.md",
            created_at="",
            concepts=[Concept(id="c1", name="节点电价", definition="d", evidence=["e"])],
            relations=[],
        )
        state = {"concepts": {}, "history": []}
        record_evaluation(state, "节点电价", "a1", 0.3, "a", "f",
                          meta={"review": True})
        teacher = TeacherModel(asset_id="a1")
        teacher = incorporate_review_gain_signal(asset, teacher, "c1", state)
        self.assertEqual(teacher.anomalies, [])

    def test_review_gain_empty_history(self):
        g = review_gain({"concepts": {}, "history": []})
        self.assertEqual(g["avg_gain"], 0.0)
        self.assertEqual(g["measurable"], 0)
        self.assertEqual(g["concepts"], [])

    def test_record_evaluation_smoothing(self):
        state = {}
        register_asset(state, _asset_with_relations())
        new = record_evaluation(state, "A", "t1", 0.5, "ans", "fb")
        self.assertGreater(new, 0)
        self.assertLess(new, 0.5)
        self.assertEqual(len(state["history"]), 1)

    def test_mark_completed_and_next(self):
        state = {}
        asset = _asset_with_relations()
        register_asset(state, asset)
        learner.mark_completed(state, "t1", "c1")
        nxt = learner.next_concept_id(state, asset)
        self.assertEqual(nxt, "c2")

    def test_adaptive_path_prereq_order(self):
        state = {}
        asset = _asset_with_relations()
        register_asset(state, asset)
        items = adaptive_path(asset, state)
        names = [i["name"] for i in items]
        self.assertIn("A", names)
        self.assertIn("B", names)
        self.assertIn("C", names)

    def test_weaknesses(self):
        state = {}
        register_asset(state, _asset_with_relations())
        record_evaluation(state, "A", "t1", 0.2, "a", "f")
        w = weaknesses(state)
        self.assertTrue(any(x["name"] == "A" for x in w))

    def test_due_for_review_spacing(self):
        now = datetime.now(timezone.utc)
        state = {"concepts": {
            "weak old": {"name": "Weak Old", "mastery": 0.4,
                         "updated_at": (now - timedelta(days=5)).isoformat()},
            "strong new": {"name": "Strong New", "mastery": 0.85,
                           "updated_at": now.isoformat()},
            "strong old": {"name": "Strong Old", "mastery": 0.8,
                           "updated_at": (now - timedelta(days=7)).isoformat()},
            "never": {"name": "Never", "mastery": 0.0, "updated_at": ""},
        }}
        due = {d["name"] for d in due_for_review(state)}
        self.assertIn("Weak Old", due)
        self.assertIn("Strong Old", due)
        self.assertNotIn("Strong New", due)
        self.assertNotIn("Never", due)

    def test_due_for_review_accepts_legacy_naive_timestamp(self):
        old = datetime.now(timezone.utc) - timedelta(days=2)
        state = {"concepts": {
            "legacy": {
                "name": "Legacy",
                "mastery": 0.4,
                "updated_at": old.replace(tzinfo=None).isoformat(),
            },
        }}
        due = due_for_review(state)
        self.assertEqual([item["name"] for item in due], ["Legacy"])

    def test_due_for_review_scopes_asset_and_resolves_graph_ids(self):
        now = datetime.now(timezone.utc) - timedelta(days=2)
        asset = _asset_with_relations()
        state = {
            "concepts": {
                "a": {"name": "A", "mastery": 0.8,
                      "updated_at": now.isoformat()},
                "b": {"name": "B", "mastery": 0.3,
                      "updated_at": now.isoformat()},
                "outside": {"name": "Outside", "mastery": 0.3,
                            "updated_at": now.isoformat()},
            },
            "history": [],
        }
        due = due_for_review(state, asset=asset)
        self.assertEqual({item["name"] for item in due}, {"A", "B"})
        a = next(item for item in due if item["name"] == "A")
        self.assertEqual(a["id"], "c1")
        self.assertTrue(a["prereq_weak"])

    def test_due_for_review_unanchored_shortens_interval(self):
        """Concepts without a source anchor get a halved review interval —
        the learner cannot re-read the passage to self-reinforce, so the
        review loop carries the full consolidation load."""
        from expert_anything.core.models import SourceLocation

        now = datetime.now(timezone.utc) - timedelta(days=3)
        asset = _asset_with_relations()
        # give A an anchor so it stays comparable; B keeps none (◌)
        asset.concepts[0].locations = [
            SourceLocation(char_start=0, char_end=5, snippet="A 是", line=1)
        ]
        state = {
            "concepts": {
                "a": {"name": "A", "mastery": 0.7,
                      "updated_at": now.isoformat()},
                "b": {"name": "B", "mastery": 0.7,
                      "updated_at": now.isoformat()},
            },
            "history": [],
        }
        due = due_for_review(state, asset=asset)
        # same mastery & freshness: A's interval 3*1.7=5.1d -> not due at 3d;
        # B is unanchored -> 2.55d -> due, and flagged for the UI
        self.assertEqual(
            [item["name"] for item in due], ["B"],
            "unanchored B must be due while anchored A is not",
        )
        b = due[0]
        self.assertTrue(b["unanchored"])
        self.assertAlmostEqual(b["interval"], 5.1 / 2.0, places=1)
        # sanity: without the asset (no anchor info) neither is scheduled
        # at this freshness — proving the halving is what pulled B in
        self.assertEqual(
            [item["name"] for item in due_for_review(state, asset=None)], []
        )

    def test_unregister_asset_cleans(self):
        state = {}
        asset = _asset_with_relations()
        register_asset(state, asset)
        learner.unregister_asset(state, "t1")
        self.assertEqual(state["concepts"], {})
        self.assertEqual(state["assets"], {})

    def test_normalize(self):
        self.assertEqual(normalize("  Agent-Memory / "), "agent memory")

    # -- mastery prediction -------------------------------------------------
    def test_mastery_prediction_no_data(self):
        state = {"concepts": {}, "history": []}
        pred = mastery_prediction(state, "Foo")
        self.assertEqual(pred["trend"], "unknown")
        self.assertFalse(pred["will_achieve"])
        self.assertEqual(pred["sessions_needed"], -1)

    def test_mastery_prediction_rising(self):
        state = {
            "concepts": {"foo": {"name": "Foo", "mastery": 0.4}},
            "history": [
                {"concept": "Foo", "score": 0.7},
                {"concept": "Foo", "score": 0.5},
                {"concept": "Foo", "score": 0.2},
            ],
        }
        pred = mastery_prediction(state, "Foo")
        self.assertEqual(pred["trend"], "rising")
        self.assertTrue(pred["will_achieve"])
        self.assertGreater(pred["predicted_mastery"], 0.4)
        self.assertGreater(pred["sessions_needed"], 0)

    def test_mastery_prediction_already_mastered(self):
        state = {
            "concepts": {"foo": {"name": "Foo", "mastery": 0.8}},
            "history": [{"concept": "Foo", "score": 0.9}],
        }
        pred = mastery_prediction(state, "Foo")
        self.assertEqual(pred["sessions_needed"], 0)

    def test_mastery_prediction_falling(self):
        state = {
            "concepts": {"foo": {"name": "Foo", "mastery": 0.3}},
            "history": [
                {"concept": "Foo", "score": 0.1},
                {"concept": "Foo", "score": 0.4},
                {"concept": "Foo", "score": 0.7},
            ],
        }
        pred = mastery_prediction(state, "Foo")
        self.assertEqual(pred["trend"], "falling")
        self.assertFalse(pred["will_achieve"])

    def test_mastery_prediction_uses_normalized_concept_name(self):
        state = {
            "concepts": {"agent memory": {"name": "Agent-Memory", "mastery": 0.4}},
            "history": [
                {"concept": "Agent-Memory", "score": 0.8},
                {"concept": "agent memory", "score": 0.2},
            ],
        }
        pred = mastery_prediction(state, " Agent / Memory ")
        self.assertEqual(pred["trend"], "rising")

    # -- study goal ----------------------------------------------------------
    def test_study_goal_set_and_progress(self):
        state = {
            "concepts": {
                "a": {"name": "A", "mastery": 0.7},
                "b": {"name": "B", "mastery": 0.2},
            },
        }
        goal = set_study_goal(state, 3, days=7)
        self.assertEqual(goal["target"], 3)
        self.assertEqual(goal["baseline_mastered"], 1)
        prog = study_goal_progress(state)
        self.assertTrue(prog["active"])
        self.assertEqual(prog["baseline"], 1)
        self.assertEqual(prog["current"], 1)
        self.assertEqual(prog["delta"], 0)

    def test_study_goal_progress_no_goal(self):
        state = {}
        prog = study_goal_progress(state)
        self.assertFalse(prog["active"])

    # -- dependency chain ---------------------------------------------------
    def test_dependency_chain_traces_prereqs(self):
        asset = _asset_with_relations()
        chain = dependency_chain(asset, "c3")
        ids = [item["id"] for item in chain]
        self.assertIn("c1", ids)
        self.assertIn("c2", ids)
        self.assertIn("c3", ids)
        # c3 is the target (depth 0); c1 is the root (depth 2)
        c3_item = next(i for i in chain if i["id"] == "c3")
        self.assertEqual(c3_item["depth"], 0)
        c1_item = next(i for i in chain if i["id"] == "c1")
        self.assertEqual(c1_item["depth"], 2)

    def test_dependency_chain_no_prereqs(self):
        asset = _asset_with_relations()
        chain = dependency_chain(asset, "c1")
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["id"], "c1")


# --------------------------------------------------------------------------- #
# tutor (deterministic)
# --------------------------------------------------------------------------- #
class TestStudyPlanAnomalyPriority(unittest.TestCase):
    """generate_study_plan must consume the teacher model: without it the
    anomaly-driven priority inside adaptive_path never reaches the plan
    (the whole point of AGENTS.md §12 stuck/learner_gap closed loop)."""

    def _asset(self):
        return KnowledgeAsset(
            asset_id="a1",
            type="text",
            title="T",
            source_name="t.md",
            created_at="",
            concepts=[
                Concept(id="c1", name="alpha", definition="d"),
                Concept(id="c2", name="beta", definition="d"),
            ],
            relations=[],
            learning_path=["c2", "c1"],
        )

    def _teacher_with_gap_on_alpha(self):
        tm = TeacherModel(asset_id="a1")
        tm.anomalies.append(
            Anomaly(
                id="an1",
                kind="learner_gap",
                description="learner gap on alpha",
                status="open",
            )
        )
        return tm

    def test_plan_promotes_anomaly_concepts(self):
        from expert_anything.core.learner import generate_study_plan
        from expert_anything.core.teacher import anomaly_concept_ids

        asset = self._asset()
        state = {"concepts": {}, "history": []}
        self.assertEqual(
            anomaly_concept_ids(asset, self._teacher_with_gap_on_alpha()),
            {"c1"},
        )

        plan = generate_study_plan(
            asset, state, minutes=30, teacher=self._teacher_with_gap_on_alpha()
        )
        names = [p["name"] for p in plan]
        self.assertIn("alpha", names)
        self.assertLess(names.index("alpha"), names.index("beta"))

    def test_plan_without_teacher_keeps_path_order(self):
        from expert_anything.core.learner import generate_study_plan

        asset = self._asset()
        state = {"concepts": {}, "history": []}
        plan = generate_study_plan(asset, state, minutes=30)
        names = [p["name"] for p in plan]
        self.assertEqual(names, ["beta", "alpha"])


class TestStyleRotationHint(unittest.TestCase):
    """Stuck rotation must respect review retention when the evidence is
    strong enough: a style that teaches well in-session but consolidates
    badly should not be the next stop if a comparable retainer exists."""

    STYLES = ["example", "diagram", "steps"]

    @staticmethod
    def _hist(entries):
        # history is newest-first
        return [
            {
                "concept": c,
                "score": s,
                "meta": {"style": st, "review": rv},
            }
            for (c, s, st, rv) in entries
        ]

    def test_deviate_when_next_retains_worse(self):
        from expert_anything.core.learner import style_rotation_hint

        state = {
            "history": self._hist([
                # current "example": teaches ok, retains 0.8
                ("c1", 0.5, "example", False),
                ("c1", 0.8, "example", True),
                ("c2", 0.8, "example", True),
                # blind-cycle next "diagram": retains 0.3 (clearly worse)
                ("c3", 0.6, "diagram", False),
                ("c3", 0.3, "diagram", True),
                ("c4", 0.3, "diagram", True),
                # alternative "steps": retains 0.9 (>= current)
                ("c5", 0.6, "steps", False),
                ("c5", 0.9, "steps", True),
                ("c6", 0.9, "steps", True),
            ])
        }
        style, reason = style_rotation_hint(
            state, "example", "diagram", self.STYLES
        )
        self.assertEqual(style, "steps")
        self.assertEqual(reason, "retention")

    def test_keep_blind_cycle_when_evidence_thin(self):
        from expert_anything.core.learner import style_rotation_hint

        # no review records at all -> exact old behaviour
        state = {"history": self._hist([("c1", 0.5, "example", False)])}
        style, reason = style_rotation_hint(
            state, "example", "diagram", self.STYLES
        )
        self.assertEqual(style, "diagram")
        self.assertEqual(reason, "")

        # next style has only 1 review sample (below min_samples)
        state = {
            "history": self._hist([
                ("c1", 0.8, "example", True),
                ("c2", 0.8, "example", True),
                ("c3", 0.3, "diagram", True),
            ])
        }
        style, reason = style_rotation_hint(
            state, "example", "diagram", self.STYLES
        )
        self.assertEqual(style, "diagram")
        self.assertEqual(reason, "")

    def test_keep_blind_cycle_when_next_not_worse(self):
        from expert_anything.core.learner import style_rotation_hint

        # next retains within the margin -> no deviation even though an
        # alternative retains higher (avoid churn on noise)
        state = {
            "history": self._hist([
                ("c1", 0.8, "example", True),
                ("c2", 0.8, "example", True),
                ("c3", 0.7, "diagram", True),
                ("c4", 0.7, "diagram", True),
                ("c5", 0.95, "steps", True),
                ("c6", 0.95, "steps", True),
            ])
        }
        style, reason = style_rotation_hint(
            state, "example", "diagram", self.STYLES
        )
        self.assertEqual(style, "diagram")
        self.assertEqual(reason, "")


class TestTutor(unittest.TestCase):
    def setUp(self):
        self.asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)
        self.tutor = Tutor(self.asset, llm=None)
        self.concept = self.asset.concepts[0]

    def test_teach_all_styles_return_complete_structure(self):
        for style in ("example", "diagram", "steps"):
            r = self.tutor.teach(self.concept, style=style)
            for key in ("concept", "style", "explanation", "example", "steps", "practice", "evidence"):
                self.assertIn(key, r, f"{style} missing {key}")
            self.assertEqual(r["style"], style)

    def test_teach_differs_per_concept(self):
        r1 = self.tutor.teach(self.asset.concepts[0])
        r2 = self.tutor.teach(self.asset.concepts[1])
        self.assertNotEqual(r1["concept"], r2["concept"])

    def test_evaluate_fallback_heuristic(self):
        r = self.tutor.evaluate(self.concept, "这是一段足够长的回答内容用来测试启发式评分逻辑。")
        self.assertIn("score", r)
        self.assertIn("feedback", r)
        self.assertIn("reference", r)
        self.assertIn("gap", r)
        # keyword-matching fallback now provides the definition as reference
        self.assertTrue(len(r["reference"]) > 0 or r["reference"] == "")

    def test_followup_without_llm_returns_structured_answer(self):
        r = self.tutor.follow_up(self.concept, "为什么？")
        self.assertIsInstance(r, str)
        self.assertTrue(len(r) > 10)  # not just a placeholder

    def test_generate_practice_without_llm_returns_fallback(self):
        r = self.tutor.generate_practice(self.concept)
        self.assertIsNotNone(r)
        self.assertIn("task", r)
        self.assertIn("hint", r)
        self.assertIn("reference", r)
        self.assertEqual(r["concept"], self.concept.name)

    def test_evaluate_practice_without_llm_returns_keyword_score(self):
        r = self.tutor.evaluate_practice(self.concept, "task desc", "learner answer")
        self.assertIn("score", r)
        self.assertIn("feedback", r)
        self.assertIn("reference", r)
        self.assertTrue(0.0 <= r["score"] <= 1.0)
        self.assertIn("未接入 LLM", r["feedback"])

    def test_generate_quiz_without_llm_returns_fallback(self):
        r = self.tutor.generate_quiz(self.concept)
        self.assertIsNotNone(r)
        self.assertIn(r["type"], ("true_false", "ordering"))
        self.assertEqual(r["concept"], self.concept.name)


# --------------------------------------------------------------------------- #
# teacher model (deterministic)
# --------------------------------------------------------------------------- #
class TestTeacher(unittest.TestCase):
    def setUp(self):
        self.asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)

    def test_fallback_marks_needs_llm(self):
        tm = build_teacher_model(self.asset, llm=None)
        self.assertEqual(tm.status, "fallback")
        self.assertTrue(any(a.kind == "needs_llm" for a in tm.anomalies))

    def test_unanchored_concepts_become_anomalies(self):
        """Concepts without source anchors enter the teacher model as
        deterministic unanchored_source anomalies (both LLM and fallback
        paths) and ride the existing name-matching rule into the
        anomaly-prioritized teaching path."""
        from expert_anything.core.teacher import (
            _unanchored_anomalies,
            anomaly_concept_ids,
            anomaly_prioritized_path,
        )

        # deterministic extraction stamps every concept -> no anomalies
        tm = build_teacher_model(self.asset, llm=None)
        self.assertFalse(
            [a for a in tm.anomalies if a.kind == "unanchored_source"]
        )

        # strip one concept's anchors (simulating template enrichment)
        target = self.asset.concepts[0]
        target.locations = []
        extras = _unanchored_anomalies(self.asset)
        self.assertEqual(len(extras), 1)
        self.assertIn(target.name, extras[0].description)

        # fallback path carries them; assemble (LLM) path does too
        tm = build_teacher_model(self.asset, llm=None)
        hits = [a for a in tm.anomalies if a.kind == "unanchored_source"]
        self.assertEqual(len(hits), 1)
        self.assertIn(target.id, anomaly_concept_ids(self.asset, tm))
        path = anomaly_prioritized_path(self.asset, tm)
        self.assertEqual(path[0], target.id)

        # re-anchoring clears the anomaly on the next build
        from expert_anything.core.extraction import _stamp_locations

        _stamp_locations(self.asset)
        tm = build_teacher_model(self.asset, llm=None)
        self.assertFalse(
            [a for a in tm.anomalies if a.kind == "unanchored_source"]
        )

    def test_record_learner_question(self):
        tm = build_teacher_model(self.asset, llm=None)
        cid = self.asset.concepts[0].id
        tm = record_learner_question(self.asset, tm, cid, "这个概念为什么重要？")
        note = tm.concept_note_by_id(cid)
        self.assertTrue(note.learner_signals)
        self.assertIn("学习者追问", note.learner_signals[-1])

    def test_anomaly_concept_ids(self):
        from expert_anything.core.teacher import Anomaly
        tm = TeacherModel(asset_id="x")
        name = self.asset.concepts[0].name
        tm.anomalies.append(Anomaly(
            id="a1", kind="logical_gap",
            description=f"关于「{name}」的解释存在断点",
            status="open"))
        ids = anomaly_concept_ids(self.asset, tm)
        self.assertIn(self.asset.concepts[0].id, ids)

    def test_concept_anomalies_matching_and_order(self):
        from expert_anything.core.teacher import Anomaly, concept_anomalies
        name = self.asset.concepts[0].name
        tm = TeacherModel(asset_id="x")
        tm.anomalies.extend([
            Anomaly(id="a-low", kind="logical_gap",
                    description=f"{name} 的次要疑点", severity="low",
                    status="open"),
            Anomaly(id="a-high", kind="contradiction",
                    description=f"{name} 与后文矛盾", severity="high",
                    status="open"),
            Anomaly(id="a-resolved", kind="surprising_claim",
                    description=f"{name} 的反常主张", severity="high",
                    status="resolved"),
            Anomaly(id="a-other", kind="undefined_term",
                    description="别的概念术语未定义", severity="high",
                    status="open"),
            Anomaly(id="a-surfaced", kind="learner_gap",
                    description=f"{name} 相关的学习者差距", severity="medium",
                    status="surfaced_to_student"),
        ])
        hits = concept_anomalies(self.asset.concepts[0], tm)
        got = [a.id for a in hits]
        # severity-first; resolved filtered out; other-concept filtered out;
        # surfaced learner_gap kept (still needs remediation)
        self.assertEqual(got, ["a-high", "a-surfaced", "a-low"])
        self.assertEqual(concept_anomalies(None, tm), [])
        self.assertEqual(concept_anomalies(self.asset.concepts[0], None), [])
        self.assertEqual(
            [a.id for a in concept_anomalies(self.asset.concepts[0], tm, limit=1)],
            ["a-high"],
        )


def _star_asset():
    """hub → A, hub → B: A and B share the hub as a common neighbour."""
    return KnowledgeAsset(
        asset_id="star",
        type="text",
        title="Star",
        source_name="star.md",
        created_at="",
        source_text="",
        concepts=[
            Concept(id="hub", name="H", definition="hub", evidence=["h"]),
            Concept(id="a", name="A", definition="d", evidence=["a"]),
            Concept(id="b", name="B", definition="d", evidence=["b"]),
        ],
        relations=[
            Relation(id="r1", source="hub", target="a", label="连接"),
            Relation(id="r2", source="hub", target="b", label="连接"),
        ],
        learning_path=["a", "hub", "b"],
    )


def _mastery_state(**pairs) -> dict:
    return {"concepts": {f"k{i}": {"name": k, "mastery": v}
                         for i, (k, v) in enumerate(pairs.items())}}


class TestCompareIncorporate(unittest.TestCase):
    """incorporate_comparison: map comparisons sink into the Teacher Model."""

    def test_shared_neighbours_become_bridging_anchors(self):
        asset = _star_asset()
        tm = TeacherModel(asset_id="star")
        tm = incorporate_comparison(asset, tm, "a", "b")
        na = tm.concept_note_by_id("a")
        nb = tm.concept_note_by_id("b")
        self.assertTrue(any("对比锚点" in c and "H" in c for c in na.connections),
                        "shared hub missing from A's connections")
        self.assertTrue(any("对比锚点" in c and "H" in c for c in nb.connections),
                        "shared hub missing from B's connections")
        # no mastery state -> no gap anomaly
        self.assertFalse([a for a in tm.anomalies if a.kind == "learner_gap"])

    def test_mastery_gap_raises_anomaly_on_weaker_side(self):
        asset = _star_asset()
        tm = TeacherModel(asset_id="star")
        ls = _mastery_state(A=0.3, B=0.8)  # gap 0.5 >= 0.4 -> high
        tm = incorporate_comparison(asset, tm, "a", "b", learner_state=ls)
        na = tm.concept_note_by_id("a")
        self.assertTrue(any("对比发现" in s and "A" in s for s in na.learner_signals),
                        "weaker side A should carry the learner signal")
        gaps = [a for a in tm.anomalies if a.kind == "learner_gap"]
        self.assertEqual(len(gaps), 1)
        self.assertIn("A", gaps[0].location)
        self.assertEqual(gaps[0].severity, "high")
        # medium band: gap in [0.2, 0.4)
        tm2 = TeacherModel(asset_id="star")
        ls2 = _mastery_state(A=0.4, B=0.7)
        tm2 = incorporate_comparison(asset, tm2, "a", "b", learner_state=ls2)
        gap = [a for a in tm2.anomalies if a.kind == "learner_gap"][0]
        self.assertEqual(gap.severity, "medium")

    def test_idempotent_repeat_calls(self):
        asset = _star_asset()
        tm = TeacherModel(asset_id="star")
        ls = _mastery_state(A=0.3, B=0.8)
        tm = incorporate_comparison(asset, tm, "a", "b", learner_state=ls)
        n_an = len(tm.anomalies)
        tm = incorporate_comparison(asset, tm, "a", "b", learner_state=ls)
        self.assertEqual(len(tm.anomalies), n_an)
        self.assertEqual(len(tm.concept_note_by_id("a").learner_signals), 1)
        self.assertEqual(len(tm.concept_note_by_id("a").connections), 1)

    def test_no_gap_no_shared_no_change(self):
        asset = _star_asset()
        tm = TeacherModel(asset_id="star")
        # all three have records -> the A/H gap is a real 0.05, not a
        # "unlearned defaults to 0" artifact
        ls = _mastery_state(A=0.6, B=0.7, H=0.65)
        tm = incorporate_comparison(asset, tm, "a", "hub", learner_state=ls)
        self.assertFalse([a for a in tm.anomalies if a.kind == "learner_gap"])
        self.assertEqual(tm.concept_note_by_id("a").connections, [])
        self.assertEqual(tm.concept_note_by_id("hub").connections, [])

    def test_injected_comparison_skips_recompute(self):
        asset = _star_asset()
        tm = TeacherModel(asset_id="star")
        comp = {"a": {"name": "A", "mastery": 0.2},
                "b": {"name": "B", "mastery": 0.9},
                "shared_neighbors": ["H"]}
        tm = incorporate_comparison(asset, tm, "a", "b", comparison=comp)
        self.assertTrue(any("对比锚点" in c for c in tm.concept_note_by_id("a").connections))
        self.assertTrue(any(a.kind == "learner_gap" for a in tm.anomalies))

    def test_bad_ids_are_ignored(self):
        asset = _star_asset()
        tm = TeacherModel(asset_id="star")
        self.assertIs(incorporate_comparison(asset, tm, "a", "a"), tm)
        self.assertIs(incorporate_comparison(asset, tm, "a", "nope"), tm)
        self.assertEqual(tm.anomalies, [])


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #
class TestStorage(unittest.TestCase):
    def test_load_backfills_missing_locations(self):
        """Assets persisted without source anchors (older regen / pre-stamping
        imports) get locations backfilled on load; existing anchors (with
        page numbers) are never recomputed."""
        import tempfile as _tf
        with _tf.TemporaryDirectory() as td:
            from expert_anything.core import config
            from expert_anything.core.models import SourceLocation
            old = config.DATA_DIR
            config.DATA_DIR = Path(td)
            config.ASSETS_DIR = config.DATA_DIR / "assets"
            try:
                asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)
                # simulate a legacy asset: strip all anchors before persisting
                for c in asset.concepts:
                    c.locations = []
                storage.save_asset(asset)

                loaded = storage.load_assets()
                self.assertEqual(len(loaded), 1)
                anchored = [c for c in loaded[0].concepts if c.locations]
                self.assertTrue(
                    anchored, "legacy asset not backfilled on load"
                )
                loc = anchored[0].locations[0]
                self.assertGreaterEqual(loc.char_start, 0)
                self.assertGreaterEqual(loc.line, 1)
                self.assertEqual(
                    loc.snippet[:40],
                    (anchored[0].evidence or [""])[0][:40],
                )

                # conservative path: an asset that already has anchors keeps
                # them verbatim (page numbers must survive a reload)
                legacy = loaded[0]
                keep = legacy.concepts[0]
                keep.locations = [
                    SourceLocation(
                        char_start=0, char_end=5, chapter="x",
                        snippet="frozen", line=1, page=3,
                    )
                ]
                storage.save_asset(legacy)
                reloaded = storage.load_assets()[0]
                self.assertEqual(reloaded.concepts[0].locations[0].page, 3)
                self.assertEqual(
                    reloaded.concepts[0].locations[0].snippet, "frozen"
                )
            finally:
                config.DATA_DIR = old
                config.ASSETS_DIR = old / "assets"

    def test_save_load_delete(self):
        import tempfile as _tf
        with _tf.TemporaryDirectory() as td:
            from expert_anything.core import config
            old = config.DATA_DIR
            config.DATA_DIR = Path(td)
            config.ASSETS_DIR = config.DATA_DIR / "assets"
            try:
                asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)
                storage.save_asset(asset)
                loaded = storage.load_assets()
                self.assertEqual(len(loaded), 1)
                self.assertEqual(loaded[0].asset_id, asset.asset_id)
                storage.delete_asset(asset.asset_id)
                self.assertEqual(storage.load_assets(), [])
            finally:
                config.DATA_DIR = old
                config.ASSETS_DIR = old / "assets"

    def test_load_asset_reads_single_file(self):
        import tempfile as _tf
        with _tf.TemporaryDirectory() as td:
            from expert_anything.core import config
            old = config.DATA_DIR
            config.DATA_DIR = Path(td)
            config.ASSETS_DIR = config.DATA_DIR / "assets"
            config.ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            try:
                asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)
                storage.save_asset(asset)
                # a corrupt second file must not break single-file loads
                (config.ASSETS_DIR / "broken.json").write_text(
                    "{not json", encoding="utf-8"
                )
                got = storage.load_asset(asset.asset_id)
                self.assertIsNotNone(got)
                self.assertEqual(got.asset_id, asset.asset_id)
                self.assertIsNone(storage.load_asset("missing-id"))
                self.assertIsNone(storage.load_asset("broken"))
                # corrupt files are skipped, not fatal, in the listing
                names = [a.asset_id for a in storage.load_assets()]
                self.assertIn(asset.asset_id, names)
                self.assertNotIn("broken", names)
            finally:
                config.DATA_DIR = old
                config.ASSETS_DIR = old / "assets"

    def test_atomic_write_preserves_previous_file_on_replace_failure(self):
        import tempfile as _tf
        from unittest import mock

        with _tf.TemporaryDirectory() as td:
            path = Path(td) / "learner.json"
            path.write_text('{"version": 1}', encoding="utf-8")
            with mock.patch(
                "expert_anything.core.storage.os.replace",
                side_effect=OSError("simulated replace failure"),
            ):
                with self.assertRaises(OSError):
                    storage._write_json_atomic(path, {"version": 2})

            self.assertEqual(path.read_text(encoding="utf-8"), '{"version": 1}')
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_atomic_write_replaces_with_valid_json(self):
        import json
        import tempfile as _tf

        with _tf.TemporaryDirectory() as td:
            path = Path(td) / "learner.json"
            storage._write_json_atomic(path, {"history": [{"score": 0.8}]})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["history"][0]["score"], 0.8)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
