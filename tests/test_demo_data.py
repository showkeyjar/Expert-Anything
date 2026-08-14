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
