"""Tests for the offline HTML report generator (no LLM / no GUI needed)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expert_anything.core.i18n import set_lang, get_lang
from expert_anything.core.report_html import build_html_report, localize_method


ASSETS = {
    "a1": {
        "title": "Sample Book",
        "method": "llm_extraction_chunked_v1",
        "concepts": [
            {"id": "c1", "name": "Memory", "definition": "跨轮次保留信息",
             "evidence": ["Memory keeps key info across turns."]},
            {"id": "c2", "name": "Context Engineering", "definition": "决定存什么取什么",
             "evidence": ["It decides what to store and retrieve."]},
        ],
        "relations": [
            {"source": "c1", "target": "c2", "label": "属于"},
        ],
    }
}
LEARNER = {
    "concepts": {
        "memory": {"name": "Memory", "mastery": 0.8, "sources": ["a1"]},
        "context engineering": {"name": "Context Engineering", "mastery": 0.2, "sources": ["a1"]},
    },
    "history": [
        {"at": "2026-08-17T10:00:00", "concept": "Memory", "score": 0.9,
         "feedback": "很好，抓住了跨轮次的关键。"},
    ],
}

# Learner state with a full learning trace (meta on history rows).
LEARNER_TRACE = {
    "concepts": {
        "memory": {"name": "Memory", "mastery": 0.2, "sources": ["a1"]},
    },
    "history": [
        {"at": "2026-08-18T09:00:00", "concept": "Memory", "key": "memory",
         "score": 0.2, "answer": "a", "feedback": "f",
         "meta": {"channel": "answer", "style": "例子", "rotated_style": True,
                  "judges": 2}},
        {"at": "2026-08-18T09:10:00", "concept": "Memory", "key": "memory",
         "score": 0.1, "answer": "a", "feedback": "f",
         "meta": {"channel": "quiz", "judges": 1}},
        {"at": "2026-08-18T09:20:00", "concept": "Memory", "key": "memory",
         "score": 0.1, "answer": "a", "feedback": "f",
         "meta": {"channel": "practice", "judges": 1}},
    ],
}

# An asset whose concepts carry explicit source locations (SourceLocation feature).
ASSETS_LOC = {
    "a1": {
        "title": "Sample Book",
        "method": "llm_extraction_chunked_v1",
        "concepts": [
            {
                "id": "c1", "name": "Memory", "definition": "跨轮次保留信息",
                "evidence": ["Memory keeps key info across turns."],
                "locations": [{
                    "char_start": 0, "char_end": 10, "chapter": "第1章 基础",
                    "snippet": "Memory keeps key info across turns.", "line": 7,
                }],
            },
        ],
        "relations": [],
    }
}


class TestReportHTML(unittest.TestCase):
    def setUp(self):
        self._prev_lang = get_lang()

    def tearDown(self):
        # restore global language so other test modules aren't polluted
        set_lang(self._prev_lang)

    def test_localize_method(self):
        set_lang("zh-CN")
        self.assertEqual(localize_method("llm_extraction_chunked_v1"), "智能分析")
        self.assertEqual(localize_method("llm_failed_fallback_v1"), "基础模式（未深度加工）")
        self.assertEqual(localize_method("deterministic_v1"), "基础模式（未深度加工）")
        self.assertEqual(localize_method("something_unknown"), "未知方法")

    def test_build_html_basic(self):
        set_lang("zh-CN")
        html = build_html_report(ASSETS, LEARNER, lang="zh-CN", current_asset_id="a1")
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("<svg", html)
        self.assertIn("</svg>", html)
        self.assertIn("bar-fill", html)               # mastery bars
        self.assertIn("Memory", html)                 # concept name present
        self.assertIn("Context Engineering", html)
        self.assertIn("跨轮次保留信息", html)            # definition rendered
        self.assertIn("学习报告", html)                   # localized title rendered

    def test_build_html_empty(self):
        set_lang("en")
        html = build_html_report({}, {"concepts": {}, "history": []}, lang="en")
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("No concept data", html)

    def test_build_html_three_langs(self):
        for lang in ("zh-CN", "en", "ja"):
            set_lang(lang)
            html = build_html_report(ASSETS, LEARNER, lang=lang, current_asset_id="a1")
            self.assertIn("<svg", html)
            self.assertIn("Memory", html)

    def test_report_shows_source_locations(self):
        set_lang("zh-CN")
        html = build_html_report(
            ASSETS_LOC, {"concepts": {}, "history": []},
            lang="zh-CN", current_asset_id="a1")
        self.assertIn("原文第 7 行", html)          # primary locator line
        self.assertIn("第1章 基础", html)            # chapter attribution
        # per-evidence line-number suffix reuses the same key
        self.assertIn("原文第 7 行", html)

        set_lang("en")
        html_en = build_html_report(
            ASSETS_LOC, {"concepts": {}, "history": []},
            lang="en", current_asset_id="a1")
        self.assertIn("source line 7", html_en)
        self.assertIn("Chapter: 第1章 基础", html_en)

    def test_trace_audit_renders_from_history_meta(self):
        set_lang("zh-CN")
        html = build_html_report(
            ASSETS, LEARNER_TRACE, lang="zh-CN", current_asset_id="a1")
        # audit section exists and reads the trace (record = source of truth)
        self.assertIn("学习轨迹明细", html)
        self.assertIn("作答次数", html)
        self.assertEqual(html.count("Memory") >= 2, True)
        self.assertIn("策略轮换 1 次", html)          # rotated_style counted
        self.assertIn("双裁判复核 1 次", html)         # judges >= 2 counted
        self.assertIn("答题", html)
        self.assertIn("自测", html)
        self.assertIn("实践", html)
        # 3 consecutive sub-threshold attempts -> stuck concept surfaced
        self.assertIn("卡壳概念（1 个）", html)
        self.assertIn("Memory (0.13)", html)          # avg of 0.2/0.1/0.1

    def test_trace_audit_empty_state(self):
        set_lang("zh-CN")
        html = build_html_report(
            ASSETS, {"concepts": {}, "history": []}, lang="zh-CN",
            current_asset_id="a1")
        self.assertIn("暂无学习轨迹记录", html)
        self.assertIn("学习轨迹明细", html)

    def test_trace_audit_three_langs(self):
        for lang in ("zh-CN", "en", "ja"):
            set_lang(lang)
            html = build_html_report(
                ASSETS, LEARNER_TRACE, lang=lang, current_asset_id="a1")
            self.assertIn("Learning trace details" if lang == "en"
                          else ("学習軌跡の明細" if lang == "ja" else "学习轨迹明细"), html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
