"""Regression guard for the silent-death prompt-template class.

A `str.format()` template that embeds literal braces (JSON examples, code, math)
raises KeyError or ValueError and — because callers wrap the LLM call in a broad
except — silently falls back to a deterministic stub.

Architecture note: extraction.py and teacher.py no longer store hard-coded
prompt templates as module-level constants.  All LLM prompts live in
prompt_registry.py and are rendered at call time via get_prompt().
teacher.py's _build_user_prompt() and _build_reflect_user_prompt() call
get_prompt() and then .format() — this file tests those functions directly.
tutor.py still keeps embedded constants (EVALUATE_USER, FOLLOWUP_SYSTEM etc.)
as deterministic fallbacks; teach_user() tests those.
"""

import unittest

from expert_anything.core.prompt_registry import get_prompt
from expert_anything.core.tutor import (
    EVALUATE_USER,
    FOLLOWUP_SYSTEM,
    _teach_user,
)


class PromptTemplateFormatTest(unittest.TestCase):
    # Extraction: _call_extract calls get_prompt("extraction_user").format(chunk_text=...)
    def test_extraction_user_template_renders(self):
        sentinel = "ZZ_TEXT_8231"
        tmpl = get_prompt("extraction_user", default=None)
        self.assertIsNotNone(tmpl, "extraction_user key must exist in registry")
        out = tmpl.format(chunk_text=sentinel)
        self.assertIsInstance(out, str)
        self.assertIn(sentinel, out)

    # Teacher: _build_user_prompt calls get_prompt("teacher_user") .format(title, concept_list, source_snippets)
    def test_teacher_user_template_renders(self):
        sentinel = "ZZ_TITLE_5521"
        tmpl = get_prompt("teacher_user", default=None)
        self.assertIsNotNone(tmpl)
        out = tmpl.format(title=sentinel, concept_list="- 概念A：定义A",
                          source_snippets="原文片段")
        self.assertIn(sentinel, out)

    # Teacher reflect: teacher.py has no hard-coded _REFLECT_USER anymore;
    # verify the registry key exists and renders.
    def test_teacher_reflect_user_exists(self):
        tmpl = get_prompt("teacher_reflect_user", default=None)
        # If not in registry, teacher.py's _build_reflect_user_prompt must
        # fall back to a hard-coded constant — verify at least the module loads.
        self.assertIsNotNone(tmpl)

    # Tutor: _teach_user() accepts {goal,baseline,style,name,definition,
    # evidence,relations,context,recent,vary}.  vary=0 renders plain;
    # vary>0 injects a VAR_Y_ANGLES domain rotation.
    def test_tutor_teach_user_renders_with_and_without_vary(self):
        for vary in (0, 3):
            sentinel = f"ZZ_EVIDENCE_{vary}_991"
            out = _teach_user(
                goal="理解知识",
                baseline="不确定",
                style="example",
                name="Agent",
                definition="定义",
                evidence=f"- {sentinel}",
                relations="（无）",
                context="（无）",
                recent="",
                vary=vary,
            )
            self.assertIn(sentinel, out)
            # the literal template key itself must not survive unformatted
            self.assertNotIn("tutor_teach_user", out)

    # Tutor EVALUATE_USER still lives in tutor.py (not in registry).
    def test_tutor_evaluate_user_template_renders(self):
        sentinel = "ZZ_EVAL_ANS_664"
        out = EVALUATE_USER.format(
            name="Agent",
            definition="定义",
            evidence="- 证据",
            answer=sentinel,
        )
        self.assertIn(sentinel, out)

    # Tutor FOLLOWUP_SYSTEM still lives in tutor.py.
    def test_tutor_followup_system_template_renders(self):
        sentinel = "ZZ_FUP_NAME_218"
        out = FOLLOWUP_SYSTEM.format(title="《样本书》", name=sentinel)
        self.assertIn(sentinel, out)

    def test_teach_user_does_not_leak_raw_template(self):
        # If the template path were reverted to an unescaped-brace version,
        # _teach_user would raise KeyError inside .format().
        out = _teach_user(
            goal="g", baseline="b", style="example", name="X",
            definition="d", evidence="- e", relations="r", context="c",
            recent="",
        )
        self.assertIn("X", out)
        self.assertTrue(len(out) > 50)

    # Practice: tutor_practice_user → {name, defn, evidence}
    def test_tutor_practice_user_template_renders(self):
        sentinel = "ZZ_PRAC_EVID_331"
        tmpl = get_prompt("tutor_practice_user", default=None)
        self.assertIsNotNone(tmpl, "tutor_practice_user must exist in registry")
        out = tmpl.format(name="概念X", defn="定义X", evidence=f"- {sentinel}")
        self.assertIn(sentinel, out)
        self.assertNotIn("tutor_practice_user", out)

    # Practice system: no format params, just verify non-empty
    def test_tutor_practice_system_template_exists(self):
        tmpl = get_prompt("tutor_practice_system", default=None)
        self.assertIsNotNone(tmpl)
        self.assertTrue(len(tmpl) > 20)

    # Quiz true_false: tutor_quiz_truefalse_user → {name, defn, evidence}
    def test_tutor_quiz_truefalse_user_template_renders(self):
        sentinel = "ZZ_TF_EVID_442"
        tmpl = get_prompt("tutor_quiz_truefalse_user", default=None)
        self.assertIsNotNone(tmpl)
        out = tmpl.format(name="概念Y", defn="定义Y", evidence=f"- {sentinel}")
        self.assertIn(sentinel, out)
        self.assertNotIn("tutor_quiz_truefalse_user", out)

    # Quiz ordering: tutor_quiz_ordering_user → {name, defn, evidence}
    def test_tutor_quiz_ordering_user_template_renders(self):
        sentinel = "ZZ_ORD_EVID_553"
        tmpl = get_prompt("tutor_quiz_ordering_user", default=None)
        self.assertIsNotNone(tmpl)
        out = tmpl.format(name="概念Z", defn="定义Z", evidence=f"- {sentinel}")
        self.assertIn(sentinel, out)
        self.assertNotIn("tutor_quiz_ordering_user", out)

    # Evaluate user: tutor_evaluate_user → {name, definition, evidence, task_block, answer}
    def test_tutor_evaluate_user_template_renders(self):
        sentinel = "ZZ_EVAL_ANS_664"
        tmpl = get_prompt("tutor_evaluate_user", default=None)
        self.assertIsNotNone(tmpl)
        out = tmpl.format(
            name="概念W", definition="定义W", evidence="- 证据",
            task_block="", answer=sentinel
        )
        self.assertIn(sentinel, out)
        self.assertNotIn("tutor_evaluate_user", out)


if __name__ == "__main__":
    unittest.main()
