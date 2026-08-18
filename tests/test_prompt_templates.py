"""Regression guard for the silent-death prompt-template class.

A `str.format()` template that embeds literal braces (JSON examples, code, math)
raises KeyError/ValueError and — because callers wrap the LLM call in a broad
except — silently falls back to a deterministic stub. The previous case:
`TEACH_USER` had an unescaped JSON example; every teaching lesson was silently
the stub (explanation == bare definition) until fixed.

This test renders every LLM prompt template with representative kwargs and
asserts it does not raise and that the supplied fields were actually substituted
(using unique sentinel substrings so escaped literal braces in JSON examples
cannot cause a false positive).
"""

import unittest

from expert_anything.core.extraction import USER_TEMPLATE
from expert_anything.core.teacher import _USER, _REFLECT_USER
from expert_anything.core.tutor import (
    EVALUATE_USER,
    FOLLOWUP_SYSTEM,
    TEACH_USER,
    _teach_user,
)


class PromptTemplateFormatTest(unittest.TestCase):
    def test_extraction_user_template_renders(self):
        sentinel = "ZZ_TEXT_8231"
        out = USER_TEMPLATE.format(text=sentinel)
        self.assertIsInstance(out, str)
        self.assertIn(sentinel, out)

    def test_teacher_user_template_renders(self):
        sentinel = "ZZ_TITLE_5521"
        out = _USER.format(
            title=sentinel,
            concepts="- 概念A：定义A",
            source="原文片段",
        )
        self.assertIn(sentinel, out)

    def test_teacher_reflect_user_template_renders(self):
        sentinel = "ZZ_ANSWER_7733"
        out = _REFLECT_USER.format(
            name="Agent",
            definition="定义",
            miscon="（无）",
            note="（无）",
            answer=sentinel,
            score="0.50",
            feedback="反馈",
        )
        self.assertIn(sentinel, out)

    def test_tutor_teach_user_renders_with_and_without_vary(self):
        # vary=0 renders plain; vary>0 injects a VAR_Y_ANGLES domain rotation.
        for vary in (0, 3):
            sentinel = f"ZZ_EVIDENCE_{vary}_991"
            out = _teach_user(
                goal="理解知识",
                baseline="不确定",
                style="例子",
                name="Agent",
                definition="定义",
                evidence=f"- {sentinel}",
                relations="（无）",
                learned="（无）",
                vary=vary,
            )
            self.assertIn(sentinel, out)
            # the literal template string itself must not survive unformatted
            self.assertNotIn("TEACH_USER", out)

    def test_tutor_evaluate_user_template_renders(self):
        sentinel = "ZZ_EVAL_ANS_664"
        out = EVALUATE_USER.format(
            name="Agent",
            definition="定义",
            evidence="- 证据",
            answer=sentinel,
        )
        self.assertIn(sentinel, out)

    def test_tutor_followup_system_template_renders(self):
        sentinel = "ZZ_FUP_NAME_218"
        out = FOLLOWUP_SYSTEM.format(title="《样本书》", name=sentinel)
        self.assertIn(sentinel, out)

    def test_teach_user_does_not_leak_raw_template(self):
        # If TEACH_USER were reverted to an unescaped-brace version, _teach_user
        # would raise inside .format(); this also guards the function contract.
        out = _teach_user(
            goal="g", baseline="b", style="图示", name="X",
            definition="d", evidence="- e", relations="r", learned="l",
        )
        # A correctly built prompt references the concept by name.
        self.assertIn("X", out)
        self.assertTrue(len(out) > 50)


if __name__ == "__main__":
    unittest.main()
