"""Regression guard for i18n key integrity.

Catches the "key renders as its own name" bug class: a `_t("key")` call whose
key is missing from the table silently shows the raw key to the user in all
three languages.

Scan strategy (static, run on import):
1. literal references  `_t("key")` / `t("key")` / `self._t("key")` across
   expert_anything/ and main.py;
2. tuple-driven references (e.g. `_t(tmpl)` where tmpl comes from a tuple of
   literals) are covered by additionally accepting any key whose quoted name
   appears anywhere in the corpus;
3. dynamically-assembled keys (f-string/concat prefixes like rel_/trend_/
   kind_/teacher_status_) are NOT statically resolvable — they are excluded
   by prefix, and new families must be added to DYNAMIC_PREFIXES.
"""

import ast
import re
import unittest
from pathlib import Path

from expert_anything.core.i18n import LANGS, _STRINGS

ROOT = Path(__file__).resolve().parent.parent
I18N_FILE = ROOT / "expert_anything" / "core" / "i18n.py"
# Code-level corpus: every .py in the repo (tools, verify scripts, tests,
# package-internal _-prefixed modules like ui/widgets/_helpers.py) EXCEPT
# i18n.py itself (definitions), this file (audit lists), the legacy/ archive
# (dead UI generations whose stale keys never ship), and _-prefixed files in
# the REPO ROOT only (scratch scripts whose audit lists would mask dead keys).
# Docs/markdown mentions do NOT count as references.
SRC_FILES = [
    p
    for p in ROOT.rglob("*.py")
    if ".venv" not in str(p) and ".git" not in str(p)
    and "legacy" not in p.parts
    and p.name not in ("i18n.py", "test_i18n_integrity.py")
    and not (p.parent == ROOT and p.name.startswith("_"))
]
CORPUS = "\n".join(p.read_text(encoding="utf-8") for p in SRC_FILES)

DYNAMIC_PREFIXES = (
    "rel_", "style_", "profile_", "channel_", "kind_", "anomaly_",
    "trend_", "sev_", "teacher_status_", "domain_template_reason_",
    "profile_hint_", "baseline_", "guide_step", "glossary_occ_",
)
# error keys are assembled with a *suffix*: f"{kind}_failed", teach_error etc.
DYNAMIC_SUFFIXES = ("_failed",)
# 2026-09-29: the last two PENDING_WIRING keys went live —
# action_path / action_path_focus render the practice-oriented successor
# run in NodeDetailCard (node_detail._append_action_path): weak successors
# (mastery < 0.6) get the focus variant (⚠ + mastery %), mastered runs get
# the plain numbered list, path-end concepts render nothing.
# PENDING_WIRING is now empty — new not-yet-wired keys need a comment here.
PENDING_WIRING = frozenset()
# 2026-09-29 second cleanup pass: the corpus rule was fixed (package-internal
# _-prefixed modules like ui/widgets/_helpers.py were wrongly excluded,
# resurrecting tag_stuck / tag_high_leverage / tag_unblock_n / legend_focus),
# then every remaining baseline key was verified superseded by a live key
# family (rec_reason_*, km_*, nav_*, teach_*, imp_*, ...) and deleted from
# i18n.py. The baseline is now EMPTY by design: a new dead key is a
# regression to fix, never something to grandfather in.
KNOWN_DEAD_BASELINE = frozenset()

LITERAL_CALL = re.compile(
    r"""(?:^|[^\w])(?:_?t)\(\s*["']([^"'\{}]+)["']\s*[),]"""
)


class I18nKeyIntegrityTest(unittest.TestCase):
    def test_every_language_table_has_identical_key_sets(self):
        # _STRINGS maps key -> {lang: text}; completeness per key is asserted
        # by the existing three-language test in test_core; here we assert no
        # key lost a whole language silently.
        langs = set(LANGS)
        for key, table in _STRINGS.items():
            missing = langs - set(table)
            self.assertFalse(
                missing,
                f"key {key!r} missing languages: {sorted(missing)}",
            )

    def test_no_duplicate_key_definitions(self):
        """A key defined twice in the _STRINGS literal is silently shadowed:
        the later definition wins at runtime while the earlier one is dead
        text that misleads translators and reviewers. 2026-11-02 cleanup
        removed 6 shadowed first-definitions (recommend_next, method_llm,
        method_fallback, import_done, evidence_label, learn_next); this
        guard keeps the table single-definition from here on."""
        tree = ast.parse(I18N_FILE.read_text(encoding="utf-8"))
        strings_dict = None
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                if any(
                    isinstance(t, ast.Name) and t.id == "_STRINGS" for t in targets
                ):
                    strings_dict = node.value
                    break
        self.assertIsNotNone(strings_dict, "_STRINGS definition not found")
        self.assertIsInstance(
            strings_dict, ast.Dict, "_STRINGS is no longer a dict literal"
        )
        keys = [
            k.value for k in strings_dict.keys if isinstance(k, ast.Constant)
        ]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        self.assertEqual(
            dupes,
            [],
            f"duplicate key definitions in _STRINGS — the later one silently "
            f"wins and the earlier one is dead text: {dupes}",
        )

    def test_literal_keys_are_defined(self):
        used = set(LITERAL_CALL.findall(CORPUS))
        undefined = sorted(
            k
            for k in used
            if k not in _STRINGS
            and not k.startswith(DYNAMIC_PREFIXES)
            and not k.endswith(DYNAMIC_SUFFIXES)
        )
        self.assertEqual(
            undefined,
            [],
            "keys referenced by literal _t() but not defined — they would "
            "render as raw key names in the UI",
        )

    def test_concat_prefix_families_are_non_empty(self):
        """A `_t("prefix_" + var)` family whose members were never added
        renders raw keys for every member. Assert each referenced prefix
        resolves to at least one defined key."""
        prefixes = set(
            re.findall(
                r"""(?:^|[^\w])_?t\(\s*["']([a-z][a-z0-9]*_[a-z0-9_]*_)["']\s*\+""",
                CORPUS,
            )
        )
        prefixes |= set(
            re.findall(
                r"""_?t\(\s*f["']([a-z][a-z0-9]*_[a-z0-9_]*_)\{""",
                CORPUS,
            )
        )
        self.assertTrue(prefixes, "concat-key scan found nothing — regex drift?")
        for pfx in sorted(prefixes):
            self.assertTrue(
                any(k.startswith(pfx) for k in _STRINGS),
                f"dynamic key family {pfx!r} referenced but has no members in i18n table",
            )

    def test_no_new_dead_keys_accumulate(self):
        """Keys defined but referenced nowhere in live code are dead weight.
        The 2026-09 cleanup removed 67 keys outright. The remaining ones are
        pinned in KNOWN_DEAD_BASELINE: candidates pending feature re-wiring
        (recommend_reason_*, legend_focus, ...) or doc-mentioned keys whose
        UI never shipped. This guard fails the moment dead keys ACCUMULATE
        beyond the pinned set, so drift is caught at PR time while the
        backlog stays explicit instead of silently growing."""
        dead = set(
            k
            for k in _STRINGS
            if f'"{k}"' not in CORPUS
            and f"'{k}'" not in CORPUS
            and not k.startswith(DYNAMIC_PREFIXES)
            and not k.endswith(DYNAMIC_SUFFIXES)
            and k not in PENDING_WIRING
        )
        new_dead = sorted(dead - KNOWN_DEAD_BASELINE)
        self.assertEqual(
            new_dead,
            [],
            f"NEW dead i18n keys appeared (defined, never referenced): "
            f"{new_dead} — either reference them, delete them, or (if the "
            f"feature is pending) pin them in KNOWN_DEAD_BASELINE",
        )
        resurrected = sorted(KNOWN_DEAD_BASELINE - dead - PENDING_WIRING)
        # informational only: keys got re-referenced or removed — shrink the
        # baseline in the same PR. Not an error to keep them pinned.
        if resurrected:
            print(f"[i18n] baseline keys now referenced/removed: {resurrected}")


if __name__ == "__main__":
    unittest.main()
