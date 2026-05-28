"""tc_explore_* MCP 도구 core impl 단위 테스트(FastMCP 의존 없음).

state dir은 tmp로 격리 — 다른 테스트와 archive 충돌 방지.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from the_commons.mcp.exploration import (
    _archive_state_impl, _build_query_impl,
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


class Test_recommendAction_ColdStart(_StateDirIsolation):
    def test_cold_start_returns_explore_tier1_action(self):
        rec = _recommend_action_impl("autoresearch", budget=5, seed_base=42,
                                     tasks=["nanochat"])
        # mode는 explore_tier1(cold start) 또는 explore_tier2 (모두 미시도)
        self.assertIn(rec["mode"], {"explore_tier1", "explore_tier2", "cold_start"})
        self.assertEqual(rec["task"], "nanochat")
        self.assertEqual(rec["genotype"]["recipe"], "autoresearch-nanochat")


class Test_reportResult_PersistsAndLogs(_StateDirIsolation):
    def test_report_increments_round_and_writes_attribution(self):
        rec = _recommend_action_impl("autoresearch", budget=5, seed_base=42,
                                     tasks=["nanochat"])
        out = _report_result_impl("autoresearch", rec, fitness=-0.99,
                                  stderr_tail="OK", attribution={"src": "test"})
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["round"], 1)
        self.assertGreaterEqual(out["n_cells"], 1)
        # attribution log 파일 작성됐는지
        import pathlib
        ap = pathlib.Path(self.tmp.name) / "autoresearch.attribution.jsonl"
        self.assertTrue(ap.exists())
        self.assertIn("OK", ap.read_text())


class Test_archiveState_Summary(_StateDirIsolation):
    def test_archive_state_returns_compressed_view(self):
        # 라운드 1번 돌리고 archive_state 호출
        rec = _recommend_action_impl("autoresearch", budget=5, seed_base=42,
                                     tasks=["nanochat"])
        _report_result_impl("autoresearch", rec, fitness=-0.95)
        snap = _archive_state_impl("autoresearch")
        self.assertEqual(snap["profile"], "autoresearch")
        self.assertGreaterEqual(snap["n_cells"], 1)
        # 셀별 응답에 samples 전체 안 들어가고 mean·n만
        for cell in snap["cells"].values():
            self.assertIn("mean", cell)
            self.assertIn("n_samples", cell)
            self.assertNotIn("samples", cell)


class Test_buildQuery_Placeholder(_StateDirIsolation):
    def test_returns_query_string_with_profile_name(self):
        # archive 없을 때
        out = _build_query_impl("autoresearch")
        self.assertIn("autoresearch", out["query"])
        self.assertIn("note", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
