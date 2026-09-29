"""Phase 4 tests — deterministic terminology table and learner profiling.

Both features are pure functions over the domain template: no LLM, no
network, no writes. These tests pin the two safety properties the feature
promises — the glossary never invents a term, and the profile never guesses
when the evidence is thin (``unknown`` plus a reason instead).
"""
import unittest

from expert_anything.core import i18n, learner, terminology
from expert_anything.core.domain_templates import ELECTRICITY_TRADING_TEMPLATE
from expert_anything.core.models import Concept, KnowledgeAsset
from expert_anything.core.tutor import Tutor

LMP_ID = "et-013"
LMP_NAME = "节点边际电价(LMP)"
UNKNOWN_CONCEPT = "碳配额"        # not registered in the electricity template
UNKNOWN_DOMAIN = "no_such_domain"

SAMPLE_TEXT = "本节讨论现货交易与节点边际电价(LMP)的形成机制，并对比中长期交易。"


def _template_ids():
    ids = []
    for chapter in ELECTRICITY_TRADING_TEMPLATE.chapters:
        for data in chapter.get("concepts", []) or []:
            cid = str(data.get("id", "") or "")
            if cid:
                ids.append(cid)
    return ids


def _template_names():
    names = set()
    for chapter in ELECTRICITY_TRADING_TEMPLATE.chapters:
        for data in chapter.get("concepts", []) or []:
            names.add(str(data.get("name", "")))
    return names


def _template_name(index):
    """Canonical name of the index-th template concept (registration order)."""
    concepts = []
    for chapter in ELECTRICITY_TRADING_TEMPLATE.chapters:
        concepts.extend(chapter.get("concepts", []) or [])
    return str(concepts[index].get("name", ""))


def _state(concepts=(), scores=(), baseline=""):
    state = {"assets": {"a1": {"title": "test"}}, "concepts": {}, "history": []}
    for name, mastery in concepts:
        state["concepts"][learner.normalize(name)] = {"name": name, "mastery": mastery}
    state["history"] = [{"score": score} for score in scores]
    if baseline:
        state["profile"] = {"baseline": baseline}
    return state


class TestTerminologyTable(unittest.TestCase):
    """The glossary is a faithful projection of the domain template."""

    def test_table_covers_every_registered_concept(self):
        rows = [row for group in terminology.glossary().values() for row in group]
        self.assertEqual(sorted(row["id"] for row in rows), sorted(_template_ids()))

    def test_table_never_invents_terms(self):
        for term in terminology.iter_terms():
            self.assertIn(term.id, _template_ids())
            self.assertIn(term.name, _template_names())
            self.assertTrue(term.definition)

    def test_lookup_by_id_canonical_name_and_alias(self):
        for ref in (LMP_ID, LMP_NAME, "节点边际电价", "LMP", "lmp", " ＬＭＰ "):
            term = terminology.get_term(ref)
            self.assertIsNotNone(term, ref)
            self.assertEqual(term.id, LMP_ID, ref)
        self.assertEqual(terminology.terms_for_concept("lmp")[0].id, LMP_ID)

    def test_unknown_reference_returns_nothing(self):
        self.assertIsNone(terminology.get_term(UNKNOWN_CONCEPT))
        self.assertIsNone(terminology.get_term(""))
        self.assertEqual(terminology.terms_for_concept(UNKNOWN_CONCEPT), [])
        self.assertEqual(terminology.resolve_alias(UNKNOWN_CONCEPT), "")
        self.assertEqual(terminology.aliases_of(UNKNOWN_CONCEPT), [])

    def test_alias_table_is_bidirectional(self):
        table = terminology.bidirectional_table()
        self.assertEqual(table["name_to_id"].get(LMP_NAME), LMP_ID)
        self.assertEqual(table["name_to_aliases"].get(LMP_NAME), ["LMP"])
        self.assertEqual(table["alias_to_name"].get("lmp"), LMP_NAME)
        self.assertEqual(terminology.resolve_alias("LMP"), LMP_NAME)
        self.assertEqual(terminology.aliases_of(LMP_NAME), ["LMP"])
        self.assertEqual(terminology.aliases_of(LMP_ID), ["LMP"])
        # every canonical name in the reverse map is a registered concept
        names = _template_names()
        for canonical in table["alias_to_name"].values():
            self.assertIn(canonical, names)

    def test_text_matching_returns_registered_spans(self):
        hits = terminology.match_terms(SAMPLE_TEXT)
        self.assertEqual([hit["id"] for hit in hits], ["et-004", LMP_ID, "et-003"])
        offsets = [hit["start"] for hit in hits]
        self.assertEqual(offsets, sorted(offsets))
        for hit in hits:
            self.assertIn(hit["id"], _template_ids())
            self.assertIn(hit["name"], _template_names())
            self.assertEqual(SAMPLE_TEXT[hit["start"]:hit["end"]], hit["matched"])

    def test_text_matching_longest_variant_and_empty_input(self):
        hits = terminology.match_terms("节点边际电价(LMP)")
        self.assertEqual([hit["id"] for hit in hits], [LMP_ID])
        self.assertEqual(terminology.match_terms(UNKNOWN_CONCEPT + "与公司理财"), [])
        self.assertEqual(terminology.match_terms(""), [])

    def test_stats_track_the_template(self):
        info = terminology.stats()
        terms = terminology.iter_terms()
        self.assertEqual(info["domain_id"], "electricity_trading")
        self.assertEqual(info["template_name"], ELECTRICITY_TRADING_TEMPLATE.name)
        self.assertEqual(info["term_count"], len(_template_ids()))
        self.assertEqual(info["chapter_count"],
                         len(ELECTRICITY_TRADING_TEMPLATE.chapters))
        self.assertEqual(info["alias_count"], sum(len(t.aliases) for t in terms))
        self.assertEqual(info["terms_with_aliases"],
                         sum(1 for t in terms if t.aliases))

    def test_missing_domain_yields_empty_results(self):
        self.assertEqual(terminology.glossary(UNKNOWN_DOMAIN), {})
        self.assertEqual(terminology.match_terms(SAMPLE_TEXT, UNKNOWN_DOMAIN), [])
        self.assertEqual(list(terminology.iter_terms(UNKNOWN_DOMAIN)), [])
        self.assertIsNone(terminology.get_term(LMP_ID, UNKNOWN_DOMAIN))
        self.assertEqual(terminology.stats(UNKNOWN_DOMAIN)["term_count"], 0)


class TestTeachingChainEnrichment(unittest.TestCase):
    """The lesson payload carries the Phase 4 blocks, without breaking."""

    def _lesson(self, concept_name):
        asset = KnowledgeAsset(
            asset_id="phase4-test",
            type="book",
            title="电力市场入门",
            source_name="phase4.txt",
            created_at="2026-09-23T00:00:00Z",
            concepts=[
                Concept(
                    id="c1",
                    name=concept_name,
                    definition="测试用概念定义。",
                    evidence=["测试用原文依据。"],
                )
            ],
        )
        asset.learning_path = ["c1"]
        tutor = Tutor(asset, llm=None)
        return tutor.teach(asset.concepts[0])

    def test_lesson_carries_registered_term_and_profile(self):
        lesson = self._lesson(LMP_NAME)
        self.assertEqual(lesson["terminology"]["self"]["id"], LMP_ID)
        self.assertEqual(lesson["terminology"]["self"]["name"], LMP_NAME)
        self.assertEqual(lesson["terminology"]["self"]["aliases"], ["LMP"])
        self.assertEqual(lesson["profile"]["level"], "unknown")
        self.assertFalse(lesson["profile"]["known"])
        self.assertEqual(lesson["difficulty_hint"], "unknown")

    def test_lesson_without_registered_term_stays_honest(self):
        lesson = self._lesson(UNKNOWN_CONCEPT)
        self.assertIsNone(lesson["terminology"]["self"])
        self.assertEqual(lesson["terminology"]["related"], [])
        self.assertEqual(lesson["profile"]["level"], "unknown")


class TestUserProfileDetection(unittest.TestCase):
    """Deterministic profiling: three levels plus an explicit unknown."""

    def test_unknown_without_learning_data(self):
        profile = learner.detect_user_profile(
            {"assets": {}, "concepts": {}, "history": []}
        )
        self.assertEqual(profile["level"], "unknown")
        self.assertFalse(profile["known"])
        self.assertEqual(profile["difficulty_hint"], "unknown")
        self.assertEqual([r["code"] for r in profile["reasons"]],
                         ["profile_reason_no_data"])

    def test_unknown_without_domain_template(self):
        profile = learner.detect_user_profile(_state([(LMP_NAME, 0.8)]),
                                              UNKNOWN_DOMAIN)
        self.assertEqual(profile["level"], "unknown")
        self.assertEqual([r["code"] for r in profile["reasons"]],
                         ["profile_reason_no_template"])
        self.assertEqual(profile["reasons"][0]["params"]["domain"], UNKNOWN_DOMAIN)

    def test_unknown_without_matching_concept(self):
        profile = learner.detect_user_profile(_state([(UNKNOWN_CONCEPT, 0.9)]))
        self.assertEqual(profile["level"], "unknown")
        self.assertEqual([r["code"] for r in profile["reasons"]],
                         ["profile_reason_no_match"])
        self.assertEqual(profile["signals"]["matched"], 0)

    def test_novice_from_thin_coverage(self):
        profile = learner.detect_user_profile(_state([(LMP_NAME, 0.0)]))
        self.assertEqual(profile["level"], "novice")
        self.assertTrue(profile["known"])
        self.assertEqual(profile["difficulty_hint"], "foundation")
        self.assertEqual([r["code"] for r in profile["reasons"]],
                         ["profile_reason_coverage"])
        self.assertEqual(profile["signals"]["matched"], 1)

    def test_some_from_partial_coverage(self):
        names = [_template_name(i) for i in range(5)]
        profile = learner.detect_user_profile(_state([(n, 0.0) for n in names]))
        self.assertEqual(profile["level"], "some")
        self.assertEqual(profile["difficulty_hint"], "standard")
        self.assertEqual(profile["signals"]["matched"], 5)

    def test_practiced_from_score_history(self):
        profile = learner.detect_user_profile(
            _state(
                [(LMP_NAME, 0.8), (_template_name(1), 0.7), (_template_name(2), 0.75)],
                scores=[0.9, 0.8, 0.85],
            )
        )
        self.assertEqual(profile["level"], "practiced")
        self.assertEqual(profile["difficulty_hint"], "advanced")
        codes = [r["code"] for r in profile["reasons"]]
        self.assertEqual(codes, ["profile_reason_scores", "profile_reason_coverage"])
        self.assertEqual(profile["signals"]["avg_score"], 0.85)

    def test_novice_from_low_scores(self):
        profile = learner.detect_user_profile(
            _state([(LMP_NAME, 0.1)], scores=[0.2, 0.3, 0.1])
        )
        self.assertEqual(profile["level"], "novice")
        self.assertEqual(profile["difficulty_hint"], "foundation")

    def test_declared_baseline_is_respected_verbatim(self):
        profile = learner.detect_user_profile(
            _state([(LMP_NAME, 0.0)], baseline="some")
        )
        self.assertEqual(profile["level"], "some")
        codes = [r["code"] for r in profile["reasons"]]
        self.assertEqual(codes, ["profile_reason_declared", "profile_reason_coverage"])
        self.assertEqual(profile["reasons"][0]["params"]["baseline"], "some")

    def test_scores_outrank_declared_baseline(self):
        profile = learner.detect_user_profile(
            _state([(LMP_NAME, 0.9)], scores=[0.9, 0.9, 0.9], baseline="novice")
        )
        self.assertEqual(profile["level"], "practiced")

    def test_reasons_render_in_every_language(self):
        samples = [
            {"assets": {}, "concepts": {}, "history": []},
            _state([(LMP_NAME, 0.0)]),
            _state([(LMP_NAME, 0.8), (_template_name(1), 0.7)], scores=[0.9, 0.8, 0.85]),
        ]
        original = i18n.get_lang()
        try:
            for lang in i18n.LANGS:
                i18n.set_lang(lang)
                for state in samples:
                    profile = learner.detect_user_profile(state)
                    for reason in profile["reasons"]:
                        text = i18n.t(reason["code"], **reason["params"])
                        self.assertNotEqual(text, reason["code"], (lang, reason["code"]))
                        self.assertNotIn("{", text, (lang, reason["code"]))
                    rendered = learner.profile_reason_text(profile, i18n.t)
                    self.assertTrue(rendered)
                    self.assertNotIn("profile_reason", rendered, lang)
        finally:
            i18n.set_lang(original)

    def test_reason_text_survives_unknown_code(self):
        """A missing translation renders as nothing; a crude translator that
        raises still leaves the raw code visible instead of crashing."""
        def translate(key, **kwargs):
            if key == "boom":
                raise RuntimeError("translator failure")
            return ""

        broken = {"reasons": [{"code": "no_such_code", "params": {}},
                              {"code": "", "params": {}},
                              {"code": "boom", "params": {}}]}
        self.assertEqual(learner.profile_reason_text(broken, translate), "boom")

    def test_ui_keys_exist_in_all_languages(self):
        """Every string the Phase 4 UI touches is translated in all 3 langs."""
        keys = [
            "profile_level_novice", "profile_level_some", "profile_level_practiced",
            "profile_level_unknown", "profile_domain_item",
            "profile_domain_item_short", "profile_hint_foundation",
            "profile_hint_standard", "profile_hint_advanced", "profile_hint_unknown",
            "terminology", "terminology_self", "terminology_alias",
            "terminology_definition", "terminology_key_points", "terminology_related",
            "terminology_matched", "terminology_none", "terminology_source_note",
            "terminology_count",
        ]
        original = i18n.get_lang()
        try:
            for lang in i18n.LANGS:
                i18n.set_lang(lang)
                for key in keys:
                    self.assertNotEqual(i18n.t(key), key, (lang, key))
        finally:
            i18n.set_lang(original)


if __name__ == "__main__":
    unittest.main()
