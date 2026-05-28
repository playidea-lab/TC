"""V10 운영 cap 단위 테스트 — tc_explore_recommend_action이 cap 위반 시 stop emit.

3가지 cap: max_wallclock_seconds, max_explosion_rounds, max_total_rounds.
None = 무제한 (back-compat). 위반 시 mode='stop' + reason 사유.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest

from the_commons.exploration.session import ExploreSession
from the_commons.mcp.exploration import (
    _recommend_action_impl, _report_result_impl,
)


class _StateDirIsolation(unittest.TestCase):
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


class Test_recommendAction_NoneCapsAreInfinite(_StateDirIsolation):
    def test_no_caps_returns_normal_action(self):
        rec = _recommend_action_impl("autoresearch", budget=5,
                                     seed_base=42, tasks=["nanochat"])
        self.assertNotEqual(rec["mode"], "stop")


class Test_maxTotalRounds_Cap(_StateDirIsolation):
    def test_cap_at_zero_immediately_stops(self):
        rec = _recommend_action_impl("autoresearch", budget=10, seed_base=1,
                                     tasks=["nanochat"], max_total_rounds=0)
        self.assertEqual(rec["mode"], "stop")
        self.assertIn("max_total_rounds", rec["reason"])

    def test_cap_at_2_stops_after_2_rounds(self):
        # 2 라운드 굴리고 3번째 호출 시 cap에 걸려야
        for _ in range(2):
            rec = _recommend_action_impl("autoresearch", budget=10, seed_base=1,
                                         tasks=["nanochat"], max_total_rounds=10)
            self.assertNotEqual(rec["mode"], "stop")
            _report_result_impl("autoresearch", rec, fitness=-0.9)
        # 3번째: max_total_rounds=2면 round=2 >= 2 → stop
        rec3 = _recommend_action_impl("autoresearch", budget=10, seed_base=1,
                                      tasks=["nanochat"], max_total_rounds=2)
        self.assertEqual(rec3["mode"], "stop")


class Test_maxWallclockSeconds_Cap(_StateDirIsolation):
    def test_zero_seconds_cap_stops_immediately(self):
        # cap=0 → 이미 elapsed >= 0이라 즉시 stop
        rec = _recommend_action_impl("autoresearch", budget=5, seed_base=1,
                                     tasks=["nanochat"], max_wallclock_seconds=0)
        self.assertEqual(rec["mode"], "stop")
        self.assertIn("max_wallclock_seconds", rec["reason"])

    def test_large_cap_does_not_stop(self):
        rec = _recommend_action_impl("autoresearch", budget=5, seed_base=1,
                                     tasks=["nanochat"], max_wallclock_seconds=3600)
        self.assertNotEqual(rec["mode"], "stop")


class Test_maxExplosionRounds_Cap(_StateDirIsolation):
    def test_explosion_count_persists_across_calls(self):
        # 가짜 explosion action을 report로 보내 카운터 누적
        s = ExploreSession("autoresearch", budget=5, seed_base=1, tasks=["nanochat"])
        rec_normal = _recommend_action_impl("autoresearch", budget=5, seed_base=1,
                                            tasks=["nanochat"])
        # action 자체를 explosion으로 위조해 report — 카운터 증가 시뮬
        fake_explosion = dict(rec_normal); fake_explosion["mode"] = "explosion"
        _report_result_impl("autoresearch", fake_explosion, fitness=-0.5)
        # 다음 recommend에 max_explosion_rounds=1 cap → stop
        rec2 = _recommend_action_impl("autoresearch", budget=5, seed_base=1,
                                      tasks=["nanochat"], max_explosion_rounds=1)
        self.assertEqual(rec2["mode"], "stop")
        self.assertIn("max_explosion_rounds", rec2["reason"])


class Test_capState_PersistsAcrossSessions(_StateDirIsolation):
    def test_started_at_preserved_on_reload(self):
        s1 = ExploreSession("autoresearch", budget=5, tasks=["nanochat"])
        original_started = s1.started_at
        s1.save()
        time.sleep(0.05)
        s2 = ExploreSession("autoresearch", budget=5, tasks=["nanochat"])
        self.assertEqual(s2.started_at, original_started)         # 재로드시 보존

    def test_explosion_rounds_preserved_on_reload(self):
        s1 = ExploreSession("autoresearch", budget=5, tasks=["nanochat"])
        s1.increment_explosion_rounds()
        s1.increment_explosion_rounds()
        s1.save()
        s2 = ExploreSession("autoresearch", budget=5, tasks=["nanochat"])
        self.assertEqual(s2.explosion_rounds, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
