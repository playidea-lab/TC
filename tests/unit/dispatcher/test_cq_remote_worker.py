"""CqRemoteWorker 단위 테스트 — cq MCP write_file/read_file을 모킹해 흐름 검증.

실 GPU smoke는 S1~S3 워커 복구 후. 이 테스트는 인터페이스 정합·시그니처 호출만.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from the_commons.dispatcher import JobSpec, Worker, dispatch
from the_commons.dispatcher.cq_remote_worker import CqRemoteWorker


def _spec(**over) -> JobSpec:
    base = dict(name="r", code="DEPTH=8", command="echo run",
                monitor="score", metric_keys=["score"], timeout=60)
    base.update(over)
    return JobSpec(**base)


def _worker_with_mocked_cq():
    w = CqRemoteWorker(project_id="proj", worker_id="wk")
    cq = MagicMock()
    w._cq = cq
    return w, cq


class Test_workerProtocol_Conformance(unittest.TestCase):
    def test_satisfies_protocol(self):
        w = CqRemoteWorker(project_id="p", worker_id="w")
        self.assertIsInstance(w, Worker)

    def test_rejects_empty_ids(self):
        with self.assertRaises(ValueError):
            CqRemoteWorker(project_id="", worker_id="w")


class Test_submit_ShipsFilesViaWriteFile(unittest.TestCase):
    def test_submit_sends_train_aux_config_to_remote_workspace(self):
        w, cq = _worker_with_mocked_cq()
        cq.call.side_effect = [
            "create_job ok 11111111-2222-3333-4444-555555555555",  # create_job → uuid
            "ok",                                                    # create_run
            "ok",                                                    # write_file train.py
            "ok",                                                    # write_file cq_config.json
            "ok",                                                    # write_file prepare.py (aux)
            "ok",                                                    # control_job start
        ]
        spec = _spec(
            name="autoresearch", code="DEPTH = 10",
            aux_files={"prepare.py": "VOCAB_SIZE = 8192"},
            config={"mode": "max"},
            command="python train.py", monitor="score",
            metric_keys=["score"], requirements=["torch"],
        )
        jid = w.submit(spec)
        self.assertEqual(jid, "11111111-2222-3333-4444-555555555555")

        # write_file 호출이 워크스페이스 격리(job_id)와 워커 id를 정확히 전달
        write_calls = [c for c in cq.call.call_args_list if c.args[0] == "write_file"]
        self.assertEqual(len(write_calls), 3)                        # train + config + 1 aux
        # 첫 write_file = train.py
        first_args = write_calls[0].args[1]
        self.assertEqual(first_args["worker_id"], "wk")
        self.assertEqual(first_args["job_id"], jid)
        self.assertEqual(first_args["path"], "train.py")
        self.assertIn("DEPTH = 10", first_args["content"])
        # 두 번째 = cq_config.json
        self.assertEqual(write_calls[1].args[1]["path"], "cq_config.json")
        self.assertEqual(json.loads(write_calls[1].args[1]["content"])["mode"], "max")
        # 세 번째 = aux prepare.py
        self.assertEqual(write_calls[2].args[1]["path"], "prepare.py")
        # control_job start로 끝남
        call_seq = [c.args[0] for c in cq.call.call_args_list]
        self.assertEqual(call_seq[0], "create_job")
        self.assertEqual(call_seq[-1], "control_job")

    def test_submit_rejects_empty_command(self):
        w, _ = _worker_with_mocked_cq()
        with self.assertRaises(ValueError):
            w.submit(_spec(command=""))


class Test_download_ReadFile(unittest.TestCase):
    def test_download_returns_content_for_existing_file(self):
        w, cq = _worker_with_mocked_cq()
        cq.call.return_value = '{"best_value": -0.91}'
        out = w.download("jid", "describe.json")
        self.assertEqual(json.loads(out)["best_value"], -0.91)
        # read_file에 worker_id + job_id 정확히 전달
        cq.call.assert_called_once_with("read_file", {
            "worker_id": "wk", "job_id": "jid", "path": "describe.json",
        })

    def test_download_returns_none_for_error_response(self):
        w, cq = _worker_with_mocked_cq()
        cq.call.return_value = "Error: no such file or directory"
        self.assertIsNone(w.download("jid", "missing.json"))

    def test_download_returns_none_when_cq_raises(self):
        w, cq = _worker_with_mocked_cq()
        cq.call.side_effect = RuntimeError("NATS timeout")
        self.assertIsNone(w.download("jid", "x"))


class Test_tailStderr_ReadsLogAndTrims(unittest.TestCase):
    def test_returns_last_n_lines_from_train_err_log(self):
        w, cq = _worker_with_mocked_cq()
        cq.call.return_value = "\n".join(f"line {i}" for i in range(100))
        tail = w.tail_stderr("jid", n_lines=5)
        self.assertEqual(tail.splitlines(),
                         ["line 95", "line 96", "line 97", "line 98", "line 99"])

    def test_returns_empty_when_no_log(self):
        w, cq = _worker_with_mocked_cq()
        cq.call.return_value = "Error: not found"
        self.assertEqual(w.tail_stderr("jid"), "")


class Test_dispatchFlow_WithRemoteWorker(unittest.TestCase):
    """dispatch() 코어가 CqRemoteWorker로도 깨끗하게 흐르는지 (LocalWorker와 동일 인터페이스)."""

    def test_remote_worker_dispatch_returns_fitness_from_describe(self):
        w, cq = _worker_with_mocked_cq()
        cq.call.side_effect = [
            "create_job ok abcdef01-1234-5678-9abc-def012345678",
            "ok", "ok", "ok", "ok",                               # create_run + 2 write_file + start
            '{"best_value": -0.87}',                              # download describe.json
        ]
        cq.poll.return_value = "status: SUCCEEDED metrics: {}"

        with patch("the_commons.dispatcher.local_worker.parse_metrics",
                   return_value=({"score": -0.87}, True)), \
             patch("the_commons.dispatcher.cq_remote_worker.parse_metrics",
                   return_value=({"score": -0.87}, True)):
            result = dispatch(w, _spec(monitor="score"))
        self.assertTrue(result.success)
        self.assertEqual(result.fitness, -0.87)
        self.assertEqual(result.stderr_tail, "")                 # 성공 → stderr 회수 안 함


if __name__ == "__main__":
    unittest.main(verbosity=2)
