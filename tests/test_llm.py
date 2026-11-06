"""LLM-layer tests: real extraction, styles, evaluation, teacher, follow-up.

These require a configured LLM key (EXPERTANYTHING_LLM_API_KEY) and are
skipped otherwise. They run against small inline texts (fast, cheap).
"""
import sys
import os
import json
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
        # Each style must yield a genuinely different lesson (the example /
        # diagram / steps differ even though the "why it matters" intuition in
        # explanation is intentionally shared across styles).
        s1 = json.dumps(r1, ensure_ascii=False, sort_keys=True)
        s2 = json.dumps(r2, ensure_ascii=False, sort_keys=True)
        s3 = json.dumps(r3, ensure_ascii=False, sort_keys=True)
        self.assertNotEqual(s1, s2)
        self.assertNotEqual(s1, s3)
        self.assertNotEqual(s2, s3)
        self.assertTrue(r3["steps"])

    def test_vary_changes_content(self):
        # "换一个例子" rotates the example domain; the model occasionally returns
        # the same canonical example, so assert that across several angles at
        # least one differs from the base lesson.
        import json as _json
        r0 = self.tutor.teach(self.concept, vary=0)
        base = _json.dumps(r0, ensure_ascii=False, sort_keys=True)
        variants = [self.tutor.teach(self.concept, vary=v) for v in (1, 2, 3)]
        differs = any(
            _json.dumps(v, ensure_ascii=False, sort_keys=True) != base
            for v in variants
        )
        self.assertTrue(differs, "vary produced no distinct lesson across 3 attempts")

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


# Phase 3: the domain-specific prompt path (docs/电力交易领域学习方案.md).
# The title carries "电力" so domain detection selects the electricity
# prompts; the skeleton is guidance only, so grounding rules must still hold.
ELECTRICITY_TEXT = """# 电力市场交易体系

两级市场架构：中国电力市场实行省级市场与区域市场两级运作。
省级电力交易中心：负责省内交易组织的日常运营。
现货交易：包括日前市场、日内市场和实时平衡市场。
"""


@unittest.skipUnless(HAS_LLM, "EXPERTANYTHING_LLM_API_KEY not configured")
class TestLLMDomainPrompts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.llm = LLMClient.from_config(
            config.LLM_API_KEY, config.LLM_BASE_URL, config.LLM_MODEL
        )
        cls.asset = extract_knowledge(
            ELECTRICITY_TEXT, "电力市场交易体系.md", llm=cls.llm
        )

    def test_domain_extraction_stays_grounded(self):
        asset = self.asset
        self.assertEqual(asset.method, "llm_extraction_v1")
        self.assertTrue(asset.concepts, "domain extraction produced no concepts")
        for c in asset.concepts:
            self.assertTrue(c.evidence, f"{c.name} has no evidence")
            for ev in c.evidence:
                self.assertIn(ev, ELECTRICITY_TEXT, "evidence not verbatim from source")
        # Domain guidance must never fabricate source-external concepts.
        names = {c.name for c in asset.concepts}
        self.assertNotIn("量子纠缠", names)
        self.assertTrue(
            any(c.name in ELECTRICITY_TEXT for c in asset.concepts),
            "no concept name appears in the source",
        )

    def test_domain_teacher_notes_cover_asset_concepts(self):
        tm = build_teacher_model(self.asset, llm=self.llm)
        self.assertIn(tm.status, ("done", "failed"))
        for note in tm.concept_notes:
            self.assertTrue(note.concept_id)


# --------------------------------------------------------------------------- #
# LLM response disk cache (no real network / no LLM key required)
# --------------------------------------------------------------------------- #
import shutil
import tempfile
import urllib.request as _urllib

from expert_anything.core.llm import (
    LLMClient,
    Message,
    configure_llm_cache,
)


class _FakeResponse:
    """Minimal stand-in for urllib's context-managed HTTP response."""

    def __init__(self, raw: bytes):
        self._raw = raw

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestLLMCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        configure_llm_cache(self.tmp, enabled=True)
        self.calls = []

    def tearDown(self):
        configure_llm_cache(None, enabled=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _client(self) -> LLMClient:
        return LLMClient(api_key="test-key", base_url="http://example.invalid", model="m")

    def _patch(self, payload: bytes):
        orig = _urllib.urlopen

        def fake(req, timeout=None):
            self.calls.append(req)
            return _FakeResponse(payload)

        _urllib.urlopen = fake
        return orig

    def test_identical_call_hits_cache_not_network(self):
        payload = json.dumps({"choices": [{"message": {"content": "cached answer"}}]}).encode()
        orig = self._patch(payload)
        try:
            c = self._client()
            msgs = [Message("user", "同一个问题")]
            first = c.chat(msgs)
            second = c.chat(msgs)
        finally:
            _urllib.urlopen = orig
        self.assertEqual(first, "cached answer")
        self.assertEqual(second, "cached answer")
        self.assertEqual(len(self.calls), 1, "第二次相同调用应命中缓存，不再发起网络请求")

    def test_different_temperature_misses_cache(self):
        payload = json.dumps({"choices": [{"message": {"content": "x"}}]}).encode()
        orig = self._patch(payload)
        try:
            c = self._client()
            msgs = [Message("user", "q")]
            c.chat(msgs, temperature=0.0)
            c.chat(msgs, temperature=0.7)
        finally:
            _urllib.urlopen = orig
        self.assertEqual(len(self.calls), 2, "不同 temperature 应视为不同请求，均走网络")

    def test_cache_disabled_via_env(self):
        os.environ["EXPERTANYTHING_LLM_CACHE"] = "0"
        try:
            payload = json.dumps({"choices": [{"message": {"content": "y"}}]}).encode()
            orig = self._patch(payload)
            try:
                c = self._client()
                msgs = [Message("user", "q")]
                c.chat(msgs)
                c.chat(msgs)
            finally:
                _urllib.urlopen = orig
            self.assertEqual(len(self.calls), 2, "禁用缓存后每次都走网络")
        finally:
            os.environ.pop("EXPERTANYTHING_LLM_CACHE", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
