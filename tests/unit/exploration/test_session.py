"""ExploreSession 단위 테스트 — profile 로드 + state 영속/복원 + attribution log."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from the_commons.exploration.session import (
    ExploreSession, action_from_dict, action_to_dict,
)


class _StateDirIsolation(unittest.TestCase):
    """모든 테스트가 fresh tmp state dir에서 돌도록."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("TC_EXPLORE_STATE_DIR")
        os.environ["TC_EXPLORE_STATE_DIR"] = self.tmp.name

    def tearDown(self):
        if self._old is None:
            del os.environ["TC_EXPLORE_STATE_DIR"]
        else:
            os.environ["TC_EXPLORE_STATE_DIR"] = self._old
        self.tmp.cleanup()


class Test_session_LoadAndColdStart(_StateDirIsolation):
    def test_cold_start_creates_state_file_with_baseline_archive(self):
        s = ExploreSession("autoresearch", epsilon=0.4, budget=5,
                           seed_base=42, tasks=["nanochat"])
        # cold start: archive 비어있어야
        self.assertEqual(len(s.controller.archive), 0)
        self.assertEqual(s.controller.round, 0)
        s.save()
        sp = Path(self.tmp.name) / "autoresearch.json"
        self.assertTrue(sp.exists())
        st = json.loads(sp.read_text())
        self.assertEqual(st["profile"], "autoresearch")
        self.assertEqual(st["tasks"], ["nanochat"])
        self.assertEqual(st["round"], 0)

    def test_step_then_save_then_reload_preserves_round(self):
        s1 = ExploreSession("autoresearch", budget=5, seed_base=42)
        action = s1.controller.step()
        s1.controller.report(action, fitness=-0.99)
        round_after = s1.controller.round
        s1.save()
        # 새 세션으로 load — 같은 round로 복원되어야
        s2 = ExploreSession("autoresearch")
        self.assertEqual(s2.controller.round, round_after)
        self.assertGreater(len(s2.controller.archive), 0)


class Test_session_AttributionLog(_StateDirIsolation):
    def test_log_appends_jsonl(self):
        s = ExploreSession("autoresearch", budget=5)
        s.log_attribution({"round": 1, "mode": "exploit", "note": "test"})
        s.log_attribution({"round": 2, "mode": "explore"})
        ap = Path(self.tmp.name) / "autoresearch.attribution.jsonl"
        self.assertTrue(ap.exists())
        lines = ap.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["round"], 1)
        self.assertEqual(json.loads(lines[1])["mode"], "explore")


class Test_action_RoundTrip(unittest.TestCase):
    def test_action_to_dict_and_back_preserves_fields(self):
        from the_commons.exploration.map_elites import Action, Genotype
        g = Genotype.of("autoresearch-nanochat", {"depth": 8.0, "aspect_ratio": 64.0})
        a = Action(kind="explore_tier1", task="nanochat", genotype=g,
                   descriptor=(2, 1), seed=12345, reason="cold start")
        d = action_to_dict(a)
        a2 = action_from_dict(d)
        self.assertEqual(a2.kind, a.kind)
        self.assertEqual(a2.task, a.task)
        self.assertEqual(a2.genotype, a.genotype)
        self.assertEqual(a2.descriptor, a.descriptor)
        self.assertEqual(a2.seed, a.seed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
