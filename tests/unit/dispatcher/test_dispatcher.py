"""dispatcher_v2 단위 테스트.

원격 cq/GPU 없이 검증 가능한 부분: Worker Protocol 준수, dispatch() 코어 흐름,
LocalWorker 제출/회수 흐름(CqMcpClient 모킹). 실제 cq RPC는 D3 CqRemoteWorker + 실주행(W3).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from the_commons.dispatcher import JobResult, JobSpec, Worker, dispatch
from the_commons.dispatcher.local_worker import LocalWorker


# --- 가짜 Worker (dispatch 코어 흐름 검증용) -------------------------------


class FakeWorker:
    """Worker Protocol을 구조적으로 충족하는 in-memory 구현."""

    def __init__(self, *, succeed: bool = True, describe: dict | None = None,
                 metrics: dict | None = None, stderr_tail: str = "",
                 submit_error: bool = False) -> None:
        self.succeed = succeed
        self._describe = describe
        self._metrics = metrics or {}
        self._stderr = stderr_tail
        self._submit_error = submit_error
        self.submitted: JobSpec | None = None
        self.closed = False

    def submit(self, spec: JobSpec) -> str:
        if self._submit_error:
            raise RuntimeError("submit boom")
        self.submitted = spec
        return "fake-job-id"

    def poll(self, job_id: str, timeout: int) -> tuple[bool, dict, str]:
        return self.succeed, dict(self._metrics), "status: SUCCEEDED" if self.succeed else "status: FAILED"

    def download(self, job_id: str, path: str) -> str | None:
        if path == "describe.json" and self._describe is not None:
            return json.dumps(self._describe)
        return None

    def tail_stderr(self, job_id: str, n_lines: int = 50) -> str:
        return self._stderr

    def close(self) -> None:
        self.closed = True


# --- Worker Protocol 준수 -------------------------------------------------


class Test_workerProtocol_Conformance(unittest.TestCase):
    def test_fake_worker_satisfies_protocol(self):
        self.assertIsInstance(FakeWorker(), Worker)

    def test_local_worker_satisfies_protocol(self):
        # CqMcpClient는 lazy라 instantiation 자체엔 NATS 없어도 됨.
        w = LocalWorker(project_id="p", worker_id="w", workspace_root="/tmp/x")
        self.assertIsInstance(w, Worker)


# --- dispatch() 코어 흐름 -------------------------------------------------


def _spec(**over) -> JobSpec:
    base = dict(name="r", code="print('hi')", command="echo run", monitor="score",
                metric_keys=["score"], timeout=60)
    base.update(over)
    return JobSpec(**base)


class Test_dispatch_SuccessPath(unittest.TestCase):
    def test_describe_best_value_takes_precedence(self):
        w = FakeWorker(describe={"best_value": -0.99, "primary_metric": "score"},
                       metrics={"score": -0.5})            # metrics는 폴백, describe 우선
        r = dispatch(w, _spec())
        self.assertTrue(r.success)
        self.assertEqual(r.fitness, -0.99)                  # describe 우선
        self.assertEqual(r.describe["primary_metric"], "score")
        self.assertEqual(r.stderr_tail, "")                  # 성공 시 stderr 안 회수

    def test_metrics_fallback_when_no_describe(self):
        w = FakeWorker(describe=None, metrics={"score": -0.55})
        r = dispatch(w, _spec())
        self.assertEqual(r.fitness, -0.55)

    def test_no_fitness_when_neither_describe_nor_monitor_metric(self):
        w = FakeWorker(describe=None, metrics={"other": 1.0})
        r = dispatch(w, _spec(monitor="score"))
        self.assertIsNone(r.fitness)


class Test_dispatch_FailurePath(unittest.TestCase):
    def test_failed_run_returns_stderr_tail_for_agent_self_correct(self):
        # ★ V5/V11: 실패해도 stderr_tail 채움 — 에이전트 자기수정 입력
        traceback = "Traceback (most recent call last):\n  ...\nRuntimeError: OOM"
        w = FakeWorker(succeed=False, stderr_tail=traceback)
        r = dispatch(w, _spec())
        self.assertFalse(r.success)
        self.assertIn("OOM", r.stderr_tail)                  # 에이전트가 이거 보고 batch 줄임
        self.assertTrue(r.error)                              # 한 줄 요약 채워짐

    def test_submit_exception_returns_failed_result_not_raise(self):
        # submit 단에서 예외 발생해도 dispatch는 raise하지 않고 JobResult로 회수
        w = FakeWorker(submit_error=True)
        r = dispatch(w, _spec())
        self.assertFalse(r.success)
        self.assertIn("submit failed", r.error)
        self.assertEqual(r.job_id, "")

    def test_malformed_describe_json_falls_back_to_metrics(self):
        # describe.json이 깨져도 metrics로 폴백
        class BadDescWorker(FakeWorker):
            def download(self, job_id, path):
                return "{not json"
        w = BadDescWorker(succeed=True, metrics={"score": -0.7})
        r = dispatch(w, _spec())
        self.assertIsNone(r.describe)
        self.assertEqual(r.fitness, -0.7)


# --- LocalWorker 제출 흐름 (CqMcpClient 모킹) -------------------------------


class Test_localWorker_SubmitWritesFilesAndStartsJob(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws_root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _build_worker_with_mocked_cq(self):
        w = LocalWorker(project_id="proj-1", worker_id="wk-1", workspace_root=self.ws_root)
        cq = MagicMock()
        cq.call.side_effect = [
            "create_job ok 12345678-1234-1234-1234-123456789abc",   # create_job → uuid 파싱
            "ok",                                                     # create_run
            "ok",                                                     # write_file (best-effort)
            "ok",                                                     # control_job start
        ]
        w._cq = cq
        return w, cq

    def test_submit_writes_train_py_aux_and_config_to_workspace(self):
        w, cq = self._build_worker_with_mocked_cq()
        spec = JobSpec(name="autoresearch", code="DEPTH = 10",
                       aux_files={"prepare.py": "VOCAB_SIZE = 8192"},
                       config={"output_dir": ".", "mode": "max"},
                       command="python train.py", monitor="score",
                       metric_keys=["score"], requirements=["torch"], timeout=600)
        jid = w.submit(spec)
        self.assertEqual(jid, "12345678-1234-1234-1234-123456789abc")
        ws = self.ws_root / jid
        self.assertEqual((ws / "train.py").read_text(), "DEPTH = 10")
        self.assertEqual((ws / "prepare.py").read_text(), "VOCAB_SIZE = 8192")
        self.assertEqual(json.loads((ws / "cq_config.json").read_text())["mode"], "max")
        # cq RPC 호출 순서 확인: create_job → create_run → write_file → control_job(start)
        call_names = [c.args[0] for c in cq.call.call_args_list]
        self.assertEqual(call_names, ["create_job", "create_run", "write_file", "control_job"])

    def test_submit_rejects_empty_command(self):
        w, _ = self._build_worker_with_mocked_cq()
        with self.assertRaises(ValueError):
            w.submit(JobSpec(name="r", code="x", command=""))

    def test_download_reads_local_workspace_file(self):
        w, _ = self._build_worker_with_mocked_cq()
        jid = "abc"
        (self.ws_root / jid).mkdir()
        (self.ws_root / jid / "describe.json").write_text('{"best_value": -0.91}')
        self.assertIn("best_value", w.download(jid, "describe.json"))
        self.assertIsNone(w.download(jid, "missing.txt"))

    def test_tail_stderr_returns_last_n_lines(self):
        w, _ = self._build_worker_with_mocked_cq()
        jid = "j"
        (self.ws_root / jid).mkdir()
        (self.ws_root / jid / "train_err.log").write_text("\n".join(f"line {i}" for i in range(100)))
        tail = w.tail_stderr(jid, n_lines=5)
        self.assertEqual(tail.splitlines(), ["line 95", "line 96", "line 97", "line 98", "line 99"])

    def test_local_worker_rejects_empty_ids(self):
        with self.assertRaises(ValueError):
            LocalWorker(project_id="", worker_id="w")


# --- LocalWorker가 dispatch() 코어와 통합 (CqMcpClient + poll 모킹) ----------


class Test_dispatchWithLocalWorker_FullPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws_root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @patch("the_commons.dispatcher.local_worker.parse_metrics", return_value=({"score": -0.88}, True))
    def test_local_worker_dispatch_returns_fitness_from_describe(self, _parse_mock):
        w = LocalWorker(project_id="p", worker_id="wk", workspace_root=self.ws_root)
        cq = MagicMock()
        cq.call.side_effect = [
            "create_job ok 11111111-2222-3333-4444-555555555555", "ok", "ok", "ok"]
        cq.poll.return_value = "status: SUCCEEDED metrics: {}"
        w._cq = cq
        spec = JobSpec(name="r", code="x", command="echo", monitor="score", timeout=10)
        # describe.json 미리 두기 (워커가 학습 끝나고 쓴 것 모사)
        def _write_describe_on_start(*args, **kwargs):
            jid = "11111111-2222-3333-4444-555555555555"
            (self.ws_root / jid).mkdir(parents=True, exist_ok=True)
            (self.ws_root / jid / "describe.json").write_text('{"best_value": -0.91}')
            return "ok"
        cq.call.side_effect = [
            "create_job ok 11111111-2222-3333-4444-555555555555", "ok", "ok",
            _write_describe_on_start("start"),
        ]
        result = dispatch(w, spec)
        self.assertTrue(result.success)
        self.assertEqual(result.fitness, -0.91)


if __name__ == "__main__":
    unittest.main(verbosity=2)
