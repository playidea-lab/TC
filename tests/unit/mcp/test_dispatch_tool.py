"""tc_dispatch MCP 도구 core impl 단위 테스트 (LocalWorker 모킹)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from the_commons.mcp.dispatch import _dispatch_impl


class Test_dispatch_impl_BuildsJobSpecAndReturnsResultDict(unittest.TestCase):
    @patch("the_commons.mcp.dispatch._build_worker")
    def test_success_path_returns_fitness_and_metrics(self, mock_build):
        # mock worker: submit→jid, poll→success+metrics, download→describe.json with best_value
        w = MagicMock()
        w.submit.return_value = "jid-abc"
        w.poll.return_value = (True, {"score": -0.5}, "status: SUCCEEDED")
        w.download.return_value = '{"best_value": -0.42, "primary_metric": "score"}'
        w.tail_stderr.return_value = ""
        mock_build.return_value = w

        out = _dispatch_impl(
            "autoresearch", project_id="proj", worker_id="wk",
            name="r-test", code="print('hi')", command="echo run", monitor="score",
        )
        self.assertTrue(out["success"])
        self.assertEqual(out["fitness"], -0.42)            # describe 우선
        self.assertEqual(out["describe"]["primary_metric"], "score")
        self.assertEqual(out["stderr_tail"], "")
        w.close.assert_called_once()                       # 리소스 정리

    @patch("the_commons.mcp.dispatch._build_worker")
    def test_failure_returns_stderr_tail_for_self_correct(self, mock_build):
        w = MagicMock()
        w.submit.return_value = "jid"
        w.poll.return_value = (False, {"failed": True}, "status: FAILED")
        w.download.return_value = None                      # describe 없음
        w.tail_stderr.return_value = "Traceback: OOM\n RuntimeError: cuda out of memory"
        mock_build.return_value = w

        out = _dispatch_impl(
            "autoresearch", project_id="p", worker_id="w",
            name="r", code="x", command="cmd", monitor="score",
        )
        self.assertFalse(out["success"])
        self.assertIn("OOM", out["stderr_tail"])           # 에이전트 자기수정 입력
        self.assertIsNone(out["fitness"])
        self.assertTrue(out["error"])

    @patch("the_commons.mcp.dispatch._build_worker")
    def test_aux_files_and_config_passed_through(self, mock_build):
        w = MagicMock()
        w.submit.return_value = "jid"
        w.poll.return_value = (True, {"score": -0.9}, "ok")
        w.download.return_value = '{"best_value": -0.9}'
        w.tail_stderr.return_value = ""
        mock_build.return_value = w

        _dispatch_impl(
            "autoresearch", project_id="p", worker_id="w",
            name="r", code="train_code", command="cmd", monitor="score",
            aux_files={"prepare.py": "VOCAB=8192"},
            config={"mode": "max"},
            metric_keys=["score", "loss"],
            requirements=["torch"],
            timeout=600,
        )
        # JobSpec이 모든 필드와 함께 worker.submit에 전달됐는지
        spec = w.submit.call_args[0][0]
        self.assertEqual(spec.name, "r")
        self.assertEqual(spec.code, "train_code")
        self.assertEqual(spec.aux_files["prepare.py"], "VOCAB=8192")
        self.assertEqual(spec.config["mode"], "max")
        self.assertEqual(spec.metric_keys, ["score", "loss"])
        self.assertEqual(spec.requirements, ["torch"])
        self.assertEqual(spec.timeout, 600)


if __name__ == "__main__":
    unittest.main(verbosity=2)
