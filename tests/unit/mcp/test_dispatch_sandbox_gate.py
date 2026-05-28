"""tc_dispatch가 sandbox 게이트로 봉인된 코드를 GPU 비용 0으로 거부하는지 검증."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from the_commons.mcp.dispatch import _dispatch_impl


class Test_dispatchGate_RefusesBlockedCodeWithoutWorkerCall(unittest.TestCase):
    @patch("the_commons.mcp.dispatch._build_worker")
    def test_evaluate_bpb_redefine_short_circuits_before_worker(self, mock_build):
        bad_code = """
def evaluate_bpb(*a, **k):
    return 0.001
"""
        out = _dispatch_impl(
            "autoresearch", project_id="p", worker_id="w",
            name="r", code=bad_code, command="cmd", monitor="score",
        )
        self.assertFalse(out["success"])
        self.assertIn("sandbox blocked", out["error"])
        self.assertIn("evaluate_redefine", out["error"])
        self.assertIn("sandbox_violations", out)
        # 워커 0번 호출 — GPU 비용 0
        mock_build.assert_not_called()

    @patch("the_commons.mcp.dispatch._build_worker")
    def test_prepare_monkeypatch_short_circuits(self, mock_build):
        bad_code = """
import prepare
prepare.evaluate_bpb = lambda *a: 0
"""
        out = _dispatch_impl(
            "autoresearch", project_id="p", worker_id="w",
            name="r", code=bad_code, command="cmd", monitor="score",
        )
        self.assertFalse(out["success"])
        self.assertIn("prepare_monkeypatch", out["error"])
        mock_build.assert_not_called()

    @patch("the_commons.mcp.dispatch._build_worker")
    def test_legitimate_code_proceeds_to_worker(self, mock_build):
        w = MagicMock()
        w.submit.return_value = "jid"
        w.poll.return_value = (True, {"score": -0.9}, "ok")
        w.download.return_value = '{"best_value": -0.9}'
        w.tail_stderr.return_value = ""
        mock_build.return_value = w

        ok_code = """
import torch
DEPTH = 8
val_bpb = 0.99
"""
        out = _dispatch_impl(
            "autoresearch", project_id="p", worker_id="w",
            name="r", code=ok_code, command="cmd", monitor="score",
        )
        self.assertTrue(out["success"])
        self.assertNotIn("sandbox_violations", out)
        mock_build.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
