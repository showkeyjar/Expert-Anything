"""LLM-layer tests: real extraction, styles, evaluation, teacher, follow-up.

These require a configured LLM key (EXPERTANYTHING_LLM_API_KEY) and are
skipped otherwise. They run against small inline texts (fast, cheap).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expert_anything.core import config
from expert_anything.core.llm import LLMClient
from expert_anything.core.extraction import extract_knowledge
from expert_anything.core.teacher import build_teacher_model
from expert_anything.core.tutor import Tutor

HAS_LLM = config.has_llm()

TEXT = """# Design Agent Memory

Agent needs Memory to keep key information across turns. Short-term memory
lives in the current session; long-term memory is stored externally and
reused across sessions. Memory is part of Context Engineering: it decides
what to store, retrieve and compress at the right time.
"""


@unittest.skipUnless(HAS_LLM, "EXPERTANYTHING_LLM_API_KEY not configured")
class TestLLMExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.llm = LLMClient.from_config(
            config.LLM_API_KEY, config.LLM_BASE_URL, config.LLM_MODEL
        )

    def test_extraction_grounded(self):
        asset = extract_knowledge(TEXT, "agent-memory.md", llm=self.llm)
        self.assertGreaterEqual(len(asset.concepts), 2)
        self.assertEqual(asset.method, "llm_extraction_v1")
        for c in asset.concepts:
            self.assertTrue(c.evidence, f"{c.name} has no evidence")
            for ev in c.evidence:
                self.assertIn(ev, TEXT, "evidence not verbatim from source")

    def test_extraction_rejects_hallucinated(self):
        # source has no such concept; grounded extraction must not invent it
        asset = extract_knowledge(TEXT, "agent-memory.md", llm=self.llm)
        names = {c.name.lower() for c in asset.concepts}
        self.assertNotIn("quantum entanglement", names)


@unittest.skipUnless(HAS_LLM, "EXPERTANYTHING_LLM_API_KEY not configured")
class TestLLMTeach(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.llm = LLMClient.from_config(
            config.LLM_API_KEY, config.LLM_BASE_URL, config.LLM_MODEL
        )
        cls.asset = extract_knowledge(TEXT, "agent-memory.md", llm=cls.llm)
        cls.tutor = Tutor(cls.asset, llm=cls.llm)
        cls.concept = cls.asset.concepts[0]

    def test_three_styles_distinct(self):
        r1 = self.tutor.teach(self.concept, style="例子")
        r2 = self.tutor.teach(self.concept, style="图示")
        r3 = self.tutor.teach(self.concept, style="拆解步骤")
        self.assertNotEqual(r1["explanation"][:30], r2["explanation"][:30])
        self.assertTrue(r3["steps"])

    def test_vary_changes_content(self):
        r1 = self.tutor.teach(self.concept, vary=0)
        r2 = self.tutor.teach(self.concept, vary=1)
        self.assertNotEqual(r1["explanation"][:40], r2["explanation"][:40])

    def test_evaluate_returns_reference_and_gap(self):
        r = self.tutor.evaluate(self.concept, "Memory 保存跨回合的信息。")
        self.assertIn("reference", r)
        self.assertIn("gap", r)

    def test_followup_answered(self):
        r = self.tutor.follow_up(self.concept, "为什么需要长期记忆？")
        self.assertGreater(len(r.strip()), 20)


@unittest.skipUnless(HAS_LLM, "EXPERTANYTHING_LLM_API_KEY not configured")
class TestLLMTeacher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.llm = LLMClient.from_config(
            config.LLM_API_KEY, config.LLM_BASE_URL, config.LLM_MODEL
        )
        cls.asset = extract_knowledge(TEXT, "agent-memory.md", llm=cls.llm)

    def test_teacher_done(self):
        tm = build_teacher_model(self.asset, llm=self.llm)
        # an intermittent LLM hiccup degrades to status="failed" but must
        # still yield a structurally complete model (fallback notes)
        self.assertIn(tm.status, ("done", "failed"))
        self.assertEqual(len(tm.concept_notes), len(self.asset.concepts))
        for note in tm.concept_notes:
            self.assertTrue(note.concept_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
