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
from expert_anything.core.extraction import extract_knowledge
from expert_anything.core.learner import (
    adaptive_path,
    due_for_review,
    normalize,
    record_evaluation,
    register_asset,
    weaknesses,
)
from expert_anything.core.models import Concept, KnowledgeAsset, Relation
from expert_anything.core.parsers import extract_from_bytes
from expert_anything.core.teacher import (
    TeacherModel,
    anomaly_concept_ids,
    build_teacher_model,
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

    def test_unregister_asset_cleans(self):
        state = {}
        asset = _asset_with_relations()
        register_asset(state, asset)
        learner.unregister_asset(state, "t1")
        self.assertEqual(state["concepts"], {})
        self.assertEqual(state["assets"], {})

    def test_normalize(self):
        self.assertEqual(normalize("  Agent-Memory / "), "agent memory")


# --------------------------------------------------------------------------- #
# tutor (deterministic)
# --------------------------------------------------------------------------- #
class TestTutor(unittest.TestCase):
    def setUp(self):
        self.asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)
        self.tutor = Tutor(self.asset, llm=None)
        self.concept = self.asset.concepts[0]

    def test_teach_all_styles_return_complete_structure(self):
        for style in ("例子", "图示", "拆解步骤"):
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
        self.assertEqual(r["reference"], "")

    def test_followup_without_llm_returns_hint(self):
        r = self.tutor.follow_up(self.concept, "为什么？")
        self.assertIn("未接入 LLM", r)


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


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #
class TestStorage(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
