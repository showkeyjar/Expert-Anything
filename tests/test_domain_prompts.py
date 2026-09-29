"""Tests for domain-specific prompts (docs/电力交易领域学习方案.md, Phase 3).

Covers four things:
1. the domain prompt keys exist and are complete in zh-CN / en / ja;
2. prompt selection: a detected domain picks the domain variant, and *no*
   domain keeps the generic prompt byte-identical (no behaviour change);
3. the domain templates really inject the template's concept skeleton;
4. the source-grounding hard rules still hold on the domain path: verbatim
   evidence only, hallucinated concepts dropped.

Everything here is offline (scripted LLM fake).  Real-LLM end-to-end coverage
for the electricity domain lives in tests/test_llm.py, which is skipped when
EXPERTANYTHING_LLM_API_KEY is not configured.
"""
import concurrent.futures
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expert_anything.core import prompt_registry as pr
from expert_anything.core.domain_templates import (
    domain_concept_names,
    domain_concept_skeleton,
    detect_domain_from_title,
)
from expert_anything.core.extraction import extract_knowledge
from expert_anything.core.models import Concept, KnowledgeAsset
from expert_anything.core.teacher import _build_user_prompt, build_teacher_model

LANGS = ("zh-CN", "en", "ja")

DOMAIN_KEYS = (
    "extraction_system_electricity",
    "extraction_user_electricity",
    "teacher_system_electricity",
    "teacher_user_electricity",
)

GENERIC_KEYS = ("extraction_system", "extraction_user", "teacher_system", "teacher_user")

USER_KEY_PLACEHOLDERS = {
    "extraction_user_electricity": ("{chunk_text}", "{concept_skeleton}"),
    "teacher_user_electricity": (
        "{title}", "{concept_list}", "{relations}", "{source_snippets}", "{concept_skeleton}"
    ),
}

DOMAIN_TEXT = (
    "电力市场交易体系\n\n"
    "两级市场架构：中国电力市场实行省级市场与区域市场两级运作。\n\n"
    "省级电力交易中心：负责省内交易组织的日常运营。\n\n"
    "现货交易：包括日前市场、日内市场和实时平衡市场。\n"
)
DOMAIN_FILE = "电力市场交易体系.md"

PLAIN_TEXT = (
    "Python basics\n\n"
    "A variable stores a value. A function groups statements together.\n"
)
PLAIN_FILE = "python-notes.md"

DOMAIN_LLM_JSON = json.dumps(
    {
        "concepts": [
            {
                "name": "两级市场架构",
                "definition": "中国电力市场实行省级市场与区域市场两级运作",
                "evidence": ["中国电力市场实行省级市场与区域市场两级运作"],
            },
            {
                # Not in the source at all: must be dropped even on the
                # domain path (the skeleton is guidance, not a fact source).
                "name": "幽灵概念",
                "definition": "原文中不存在",
                "evidence": ["原文中根本不存在的证据句子"],
            },
        ],
        "relations": [],
        "learning_path": ["两级市场架构"],
    },
    ensure_ascii=False,
)

# Minimal well-formed reply for the single self-learning call.
TEACHER_JSON = json.dumps({"concept_notes": [], "anomalies": []}, ensure_ascii=False)

PLAIN_LLM_JSON = json.dumps(
    {
        "concepts": [
            {
                "name": "variable",
                "definition": "A variable stores a value",
                "evidence": ["A variable stores a value"],
            }
        ],
        "relations": [],
        "learning_path": ["variable"],
    },
    ensure_ascii=False,
)


# Long enough to fan out into overlapping chunks (CHUNK=9000, OVERLAP=600).
CHUNKED_TEXT = "现货交易" * 3000
CHUNKED_JSON = json.dumps(
    {
        "concepts": [
            {"name": "现货交易", "definition": "现货交易", "evidence": ["现货交易"]}
        ],
        "relations": [],
        "learning_path": ["现货交易"],
    },
    ensure_ascii=False,
)


class _ScriptedLLM:
    """Fake client: records the messages it was called with, replays scripted JSON."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, temperature=0.3, json_mode=False, max_tokens=None):
        self.calls.append(list(messages))
        # The last scripted response is reused, so a case that fans out over
        # several chunks can be covered with a single canned reply.
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return response


class _InlinePool:
    """ThreadPoolExecutor stand-in that runs the submitted callable eagerly."""

    def __init__(self, max_workers):
        self.max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, fn, llm, chunk):
        future = concurrent.futures.Future()
        try:
            future.set_result(fn(llm, chunk))
        except Exception as exc:  # pragma: no cover - surfaced via result()
            future.set_exception(exc)
        return future


def _asset(title: str, text: str) -> KnowledgeAsset:
    """One grounded concept whose evidence is verbatim from ``text``."""
    evidence = "中国电力市场实行省级市场与区域市场两级运作"
    return KnowledgeAsset(
        asset_id="a-test",
        type="md",
        title=title,
        source_name="test.md",
        created_at="2026-01-01T00:00:00Z",
        source_text=text,
        concepts=[Concept(id="c1", name="两级市场架构", definition=evidence, evidence=[evidence])],
        relations=[],
        learning_path=["c1"],
    )


class TestDomainPromptKeys(unittest.TestCase):
    """The domain keys must exist, be non-empty and carry their placeholders."""

    def test_domain_keys_exist_in_all_languages(self):
        for lang in LANGS:
            table = pr._REGISTRY[lang]
            for key in DOMAIN_KEYS:
                self.assertIn(key, table, f"{key} missing for {lang}")
                self.assertTrue(str(table[key]).strip(), f"{key} empty for {lang}")

    def test_user_templates_keep_their_placeholders(self):
        for lang in LANGS:
            for key, placeholders in USER_KEY_PLACEHOLDERS.items():
                tmpl = pr._REGISTRY[lang][key]
                for placeholder in placeholders:
                    self.assertIn(
                        placeholder, tmpl, f"{key} ({lang}) lost {placeholder}"
                    )

    def test_generic_templates_have_no_skeleton_placeholder(self):
        # The generic path never receives a skeleton, so it must not reference
        # one (this is what keeps the non-domain rendering unchanged).
        for lang in LANGS:
            for key in GENERIC_KEYS:
                self.assertNotIn(
                    "{concept_skeleton}", pr._REGISTRY[lang][key], f"{key} ({lang})"
                )

    def test_domain_suffix_map_matches_registered_template(self):
        self.assertEqual(pr.DOMAIN_PROMPT_SUFFIXES["electricity_trading"], "electricity")
        self.assertEqual(
            detect_domain_from_title("电力市场交易体系"), "electricity_trading"
        )


class TestDomainPromptSelection(unittest.TestCase):
    """Detected domain → variant; everything else → generic, verbatim."""

    def test_detected_domain_selects_variant(self):
        for lang in LANGS:
            for base, variant in (
                ("extraction_system", "extraction_system_electricity"),
                ("extraction_user", "extraction_user_electricity"),
                ("teacher_system", "teacher_system_electricity"),
                ("teacher_user", "teacher_user_electricity"),
            ):
                chosen = pr.get_domain_prompt(base, "electricity_trading", lang=lang)
                self.assertEqual(chosen, pr.get_prompt(variant, lang=lang))
                self.assertNotEqual(chosen, pr.get_prompt(base, lang=lang))

    def test_no_domain_keeps_generic_verbatim(self):
        for lang in LANGS:
            for base in GENERIC_KEYS:
                self.assertEqual(
                    pr.get_domain_prompt(base, None, lang=lang),
                    pr.get_prompt(base, lang=lang),
                )
                self.assertEqual(
                    pr.get_domain_prompt(base, "", lang=lang),
                    pr.get_prompt(base, lang=lang),
                )

    def test_unregistered_domain_keeps_generic_verbatim(self):
        # ``carbon_trading`` is registered now (second domain), so the
        # "unregistered" case must use a domain that really has no variant.
        self.assertNotIn("fusion_energy", pr.DOMAIN_PROMPT_SUFFIXES)
        for base in GENERIC_KEYS:
            self.assertEqual(
                pr.get_domain_prompt(base, "fusion_energy", lang="zh-CN"),
                pr.get_prompt(base, lang="zh-CN"),
            )

    def test_registered_carbon_domain_selects_its_variant(self):
        for lang in LANGS:
            for base, variant in (
                ("extraction_system", "extraction_system_carbon"),
                ("extraction_user", "extraction_user_carbon"),
                ("teacher_system", "teacher_system_carbon"),
                ("teacher_user", "teacher_user_carbon"),
            ):
                chosen = pr.get_domain_prompt(base, "carbon_trading", lang=lang)
                self.assertEqual(chosen, pr.get_prompt(variant, lang=lang))
                self.assertNotEqual(chosen, pr.get_prompt(base, lang=lang))
                # A domain variant must never fall back to another domain.
                self.assertNotIn("_electricity", variant)

    def test_unknown_key_falls_back_to_default(self):
        self.assertEqual(
            pr.get_domain_prompt("no_such_key", "electricity_trading", default="fallback"),
            "fallback",
        )
        self.assertEqual(pr.domain_prompt_key("no_such_key", "electricity_trading"), None)

    def test_language_fallback_to_zh_cn(self):
        self.assertEqual(
            pr.get_domain_prompt("extraction_system", "electricity_trading", lang="de"),
            pr.get_prompt("extraction_system_electricity", lang="zh-CN"),
        )

    def test_domain_prompt_key_helper(self):
        self.assertEqual(
            pr.domain_prompt_key("teacher_user", "electricity_trading"),
            "teacher_user_electricity",
        )
        self.assertIsNone(pr.domain_prompt_key("teacher_user", None))


class TestConceptSkeleton(unittest.TestCase):
    """The skeleton is the template's chapter/concept structure, nothing else."""

    def test_skeleton_lists_chapters_and_template_concepts(self):
        skeleton = domain_concept_skeleton("electricity_trading")
        names = domain_concept_names("electricity_trading")
        self.assertGreaterEqual(len(names), 19)
        for name in names:
            self.assertIn(name, skeleton, f"{name} missing from skeleton")
        self.assertIn("et-001", skeleton)
        self.assertIn("市场架构", skeleton)

    def test_skeleton_is_empty_for_unknown_domain(self):
        self.assertEqual(domain_concept_skeleton(None), "")
        self.assertEqual(domain_concept_skeleton(""), "")
        # Registered second domain → non-empty; a truly unknown one → empty.
        self.assertNotEqual(domain_concept_skeleton("carbon_trading"), "")
        self.assertEqual(domain_concept_skeleton("fusion_energy"), "")


class TestExtractionDomainWiring(unittest.TestCase):
    """Extraction picks the domain prompt and injects the skeleton, without
    loosening any source-grounding rule."""

    def test_domain_title_uses_domain_prompt_and_injects_skeleton(self):
        llm = _ScriptedLLM([DOMAIN_LLM_JSON])
        asset = extract_knowledge(DOMAIN_TEXT, DOMAIN_FILE, llm=llm)
        self.assertEqual(asset.method, "llm_extraction_v1")

        system_msg, user_msg = llm.calls[0][0], llm.calls[0][1]
        self.assertEqual(
            system_msg.content, pr.get_prompt("extraction_system_electricity", lang="zh-CN")
        )
        self.assertEqual(
            user_msg.content,
            pr.get_domain_prompt("extraction_user", "electricity_trading", lang="zh-CN").format(
                chunk_text=DOMAIN_TEXT,
                concept_skeleton=domain_concept_skeleton("electricity_trading"),
            ),
        )
        # The injected guidance really carries the template's concept skeleton.
        self.assertIn("et-001", user_msg.content)
        self.assertIn("两级市场架构", user_msg.content)

    def test_non_domain_title_sends_generic_prompt_verbatim(self):
        llm = _ScriptedLLM([PLAIN_LLM_JSON])
        extract_knowledge(PLAIN_TEXT, PLAIN_FILE, llm=llm)

        system_msg, user_msg = llm.calls[0][0], llm.calls[0][1]
        self.assertEqual(system_msg.content, pr.get_prompt("extraction_system", lang="zh-CN"))
        self.assertEqual(
            user_msg.content,
            pr.get_prompt("extraction_user", lang="zh-CN").format(chunk_text=PLAIN_TEXT),
        )
        self.assertNotIn("et-001", user_msg.content)

    def test_empty_domain_id_forces_generic_prompt(self):
        llm = _ScriptedLLM([DOMAIN_LLM_JSON])
        extract_knowledge(DOMAIN_TEXT, DOMAIN_FILE, llm=llm, domain_id="")
        self.assertEqual(
            llm.calls[0][0].content, pr.get_prompt("extraction_system", lang="zh-CN")
        )
        self.assertEqual(
            llm.calls[0][1].content,
            pr.get_prompt("extraction_user", lang="zh-CN").format(chunk_text=DOMAIN_TEXT),
        )

    def test_domain_path_still_enforces_source_grounding(self):
        llm = _ScriptedLLM([DOMAIN_LLM_JSON])
        asset = extract_knowledge(DOMAIN_TEXT, DOMAIN_FILE, llm=llm)

        names = {c.name for c in asset.concepts}
        self.assertIn("两级市场架构", names)
        # Hallucinated concept (absent from the source) must still be dropped,
        # even though the domain prompt asked for template-aligned output.
        self.assertNotIn("幽灵概念", names)

        for concept in asset.concepts:
            self.assertTrue(concept.evidence, f"{concept.name} has no evidence")
            for ev in concept.evidence:
                self.assertIn(ev, DOMAIN_TEXT, "evidence is not verbatim from the source")
            # Definition is source-grounded too: an ungrounded definition is
            # replaced by the validated evidence span.
            self.assertIn(concept.definition, DOMAIN_TEXT)

    def test_chunked_domain_extraction_injects_skeleton(self):
        llm = _ScriptedLLM([CHUNKED_JSON])
        with mock.patch(
            "expert_anything.core.extraction.concurrent.futures.ThreadPoolExecutor",
            _InlinePool,
        ):
            asset = extract_knowledge(CHUNKED_TEXT, DOMAIN_FILE, llm=llm)

        self.assertGreaterEqual(len(llm.calls), 2, "expected a multi-chunk extraction")
        for messages in llm.calls:
            self.assertEqual(
                messages[0].content,
                pr.get_prompt("extraction_system_electricity", lang="zh-CN"),
            )
            self.assertIn("et-001", messages[1].content)
        self.assertEqual([c.name for c in asset.concepts], ["现货交易"])
        for concept in asset.concepts:
            for ev in concept.evidence:
                self.assertIn(ev, CHUNKED_TEXT, "evidence is not verbatim from the source")

    def test_chunked_non_domain_extraction_keeps_generic_prompt(self):
        llm = _ScriptedLLM([CHUNKED_JSON])
        with mock.patch(
            "expert_anything.core.extraction.concurrent.futures.ThreadPoolExecutor",
            _InlinePool,
        ):
            extract_knowledge(CHUNKED_TEXT, PLAIN_FILE, llm=llm)

        for messages in llm.calls:
            self.assertEqual(
                messages[0].content, pr.get_prompt("extraction_system", lang="zh-CN")
            )
            self.assertNotIn("et-001", messages[1].content)


class TestTeacherDomainWiring(unittest.TestCase):
    """Teacher prompt: domain title → skeleton injected; otherwise generic."""

    def test_domain_title_injects_skeleton(self):
        asset = _asset("电力市场交易体系", DOMAIN_TEXT)
        prompt = _build_user_prompt(asset)
        self.assertIn("et-001", prompt)
        self.assertIn("两级市场架构", prompt)
        self.assertEqual(
            prompt,
            pr.get_prompt("teacher_user_electricity", lang="zh-CN").format(
                title=asset.title,
                concept_list="- 两级市场架构:中国电力市场实行省级市场与区域市场两级运作 | "
                "证据:中国电力市场实行省级市场与区域市场两级运作",
                relations="(无显式关系)",
                source_snippets=DOMAIN_TEXT[:4000],
                concept_skeleton=domain_concept_skeleton("electricity_trading"),
            ),
        )

    def test_no_domain_renders_generic_template(self):
        asset = _asset("Python basics", PLAIN_TEXT)
        prompt = _build_user_prompt(asset)
        self.assertNotIn("et-001", prompt)
        self.assertEqual(
            prompt,
            pr.get_prompt("teacher_user", lang="zh-CN").format(
                title=asset.title,
                concept_list="- 两级市场架构:中国电力市场实行省级市场与区域市场两级运作 | "
                "证据:中国电力市场实行省级市场与区域市场两级运作",
                relations="(无显式关系)",
                source_snippets=PLAIN_TEXT[:4000],
            ),
        )

    def test_explicit_domain_id_forces_variant_regardless_of_title(self):
        asset = _asset("Python basics", PLAIN_TEXT)
        prompt = _build_user_prompt(asset, domain_id="electricity_trading")
        self.assertIn("et-001", prompt)

    def test_main_pass_picks_domain_prompts_for_domain_asset(self):
        llm = _ScriptedLLM([TEACHER_JSON])
        build_teacher_model(_asset("电力市场交易体系", DOMAIN_TEXT), llm=llm)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(
            llm.calls[0][0].content,
            pr.get_prompt("teacher_system_electricity", lang="zh-CN"),
        )
        self.assertIn("et-001", llm.calls[0][1].content)

    def test_main_pass_picks_generic_prompts_without_domain(self):
        llm = _ScriptedLLM([TEACHER_JSON])
        build_teacher_model(_asset("Python basics", PLAIN_TEXT), llm=llm)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(
            llm.calls[0][0].content, pr.get_prompt("teacher_system", lang="zh-CN")
        )
        self.assertNotIn("et-001", llm.calls[0][1].content)


if __name__ == "__main__":
    unittest.main()
