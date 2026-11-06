"""Demo-data integrity tests: assets/teacher/learner stay consistent.

These run against the real data/_demo folder (read-only checks).
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEMO = Path(__file__).resolve().parents[1] / "data" / "_demo"
HAS_DEMO = (DEMO / "assets").exists() and (DEMO / "learner.json").exists()


@unittest.skipUnless(HAS_DEMO, "data/_demo missing (run regen_all.py)")
class TestDemoData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.learner = json.loads((DEMO / "learner.json").read_text(encoding="utf-8"))
        cls.assets = {}
        for f in (DEMO / "assets").glob("*.json"):
            if not f.name.startswith("teacher_"):
                cls.assets[f.stem] = json.loads(f.read_text(encoding="utf-8"))

    def test_two_assets(self):
        self.assertGreaterEqual(len(self.assets), 2)

    def test_asset_concepts_have_evidence(self):
        for aid, data in self.assets.items():
            for c in data.get("concepts", []):
                self.assertTrue(
                    c.get("evidence") or c.get("definition"),
                    f"{aid}: concept {c.get('name')} has neither evidence nor definition",
                )

    def test_relations_reference_real_concepts(self):
        for aid, data in self.assets.items():
            ids = {c["id"] for c in data.get("concepts", [])}
            for r in data.get("relations", []):
                self.assertIn(r["source"], ids, f"{aid}: dangling relation source")
                self.assertIn(r["target"], ids, f"{aid}: dangling relation target")

    def test_relation_evidence_is_a_verbatim_whole_source_line(self):
        """No template notes, no paraphrases: evidence must be sliceable back."""
        for aid, data in self.assets.items():
            text = data.get("source_text", "")
            lines = set(text.splitlines())
            for r in data.get("relations", []):
                ev = r.get("evidence", "")
                self.assertTrue(ev, f"{aid}: relation {r['id']} has no evidence")
                self.assertIn(ev, lines, f"{aid}: evidence is not a whole source line")
                self.assertEqual(
                    text.count(ev), 1,
                    f"{aid}: evidence occurs more than once; the anchor is ambiguous",
                )
                for forbidden in ("模板", "演示数据", "确定性生成"):
                    self.assertNotIn(
                        forbidden, ev,
                        f"{aid}: evidence still contains a generator note",
                    )

    def test_relation_evidence_is_located_by_offset_and_line(self):
        """Every relation carries a truthful anchor for the jump-to-source UI."""
        for aid, data in self.assets.items():
            text = data.get("source_text", "")
            for r in data.get("relations", []):
                loc = r.get("location")
                self.assertIsNotNone(
                    loc, f"{aid}: relation {r['id']} has no source location"
                )
                start, end = loc["char_start"], loc["char_end"]
                self.assertGreaterEqual(start, 0, f"{aid}: negative char_start")
                self.assertLessEqual(end, len(text), f"{aid}: char_end past source")
                self.assertEqual(
                    text[start:end], r["evidence"],
                    f"{aid}: location does not slice back to the evidence",
                )
                self.assertEqual(
                    loc["line"], text.count("\n", 0, start) + 1,
                    f"{aid}: recorded line disagrees with char offset",
                )

    def test_relation_semantics_cover_prereq_plus_two(self):
        """Keep the prereq main line but require two more of the six semantics."""
        from expert_anything.core.decoder import classify_relation

        for aid, data in self.assets.items():
            rels = data.get("relations", [])
            types = {r.get("type", "") for r in rels}
            self.assertIn("prereq", types, f"{aid}: missing prereq main line")
            self.assertGreaterEqual(
                len(types), 3,
                f"{aid}: only {sorted(types)}; need prereq + two more semantics",
            )
            for r in rels:
                # The label must express the declared type on its own, so a
                # drifted label cannot silently hide behind a correct type field.
                self.assertEqual(
                    classify_relation(r.get("label", ""), ""), r["type"],
                    f"{aid}: label {r.get('label')!r} does not read as {r['type']}",
                )

    def test_relation_endpoint_pairs_are_unique(self):
        """One line per node pair keeps the main map readable."""
        for aid, data in self.assets.items():
            pairs = [
                frozenset((r["source"], r["target"]))
                for r in data.get("relations", [])
            ]
            self.assertEqual(
                len(pairs), len(set(pairs)),
                f"{aid}: duplicate endpoint pair(s) would draw overlapping edges",
            )

    def test_learning_path_references_real_concepts(self):
        for aid, data in self.assets.items():
            ids = {c["id"] for c in data.get("concepts", [])}
            for cid in data.get("learning_path", []):
                self.assertIn(cid, ids, f"{aid}: path references unknown concept")

    def test_teacher_models_exist(self):
        for aid in self.assets:
            tp = DEMO / "assets" / f"teacher_{aid}.json"
            self.assertTrue(tp.exists(), f"teacher_{aid}.json missing")

    def test_learner_concepts_match_assets(self):
        asset_names = set()
        for data in self.assets.values():
            for c in data.get("concepts", []):
                asset_names.add(c["name"].lower())
        for key, rec in self.learner.get("concepts", {}).items():
            name = rec.get("name", key).lower()
            if not rec.get("sources"):
                continue
            # concept should exist in at least one asset
            self.assertIn(
                name, asset_names,
                f"learner concept '{rec.get('name')}' not found in any asset",
            )

    def test_learner_asset_entries(self):
        for aid in self.learner.get("assets", {}):
            self.assertIn(aid, self.assets, f"learner references missing asset {aid}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
