"""explore-loop → TC corpus best-effort 적재 단위 테스트 (도서관·사서 갭 메우기).

핵심: ① 서버 미가동 시 try_ingest가 None 반환(raise 안 함) ② report_result이 ingest
실패에도 placement는 성공 ③ 서버 도달 시 evidence 조립·POST 호출.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from the_commons.exploration import corpus_ingest
from the_commons.mcp.exploration import _recommend_action_impl, _report_result_impl


class _StateDirIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("TC_EXPLORE_STATE_DIR")
        os.environ["TC_EXPLORE_STATE_DIR"] = self.tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("TC_EXPLORE_STATE_DIR", None)
        else:
            os.environ["TC_EXPLORE_STATE_DIR"] = self._old
        self.tmp.cleanup()


class Test_tryIngest_BestEffort(unittest.TestCase):
    def test_server_down_returns_none_not_raise(self):
        # 도달 불가 URL — 어떤 예외도 새지 않고 None
        with patch.object(corpus_ingest, "_TC_URL", "http://127.0.0.1:59999"):
            out = corpus_ingest.try_ingest(
                recipe_id="lid-patchcore", hyperparams={"memory_size": 1000.0, "img_size": 256.0},
                primary_metric="image_auroc", fitness=0.91,
                diag={"miss_rate": 0.2, "over_rate": 0.05}, modality="vision")
        self.assertIsNone(out)

    def test_jwt_missing_key_returns_none(self):
        # JWT 키 경로 없음 → 조용히 None
        with patch.object(corpus_ingest, "_JWT_PRIV", "/nonexistent/key.pem"):
            out = corpus_ingest.try_ingest(
                recipe_id="lid-ae", hyperparams={"latent_dim": 16.0},
                primary_metric="image_auroc", fitness=0.5, modality="vision")
        self.assertIsNone(out)

    def test_build_describe_shape_for_adapter(self):
        # describe_to_evidence가 먹는 형식 — recipe_id 별도, hyperparams/metrics 포함
        d = corpus_ingest._build_describe(
            "lid-supervised", {"epochs": 19.0, "img_size": 256.0},
            "image_auroc", 0.9798, {"miss_rate": 0.08, "over_rate": 0.052}, "vision")
        self.assertEqual(d["best_value"], 0.9798)
        self.assertEqual(d["reproducibility_evidence"]["config"]["hyperparams"]["epochs"], 19.0)
        self.assertEqual(d["best"]["metrics"]["image_auroc"], 0.9798)
        self.assertEqual(d["best"]["metrics"]["miss_rate"], 0.08)
        self.assertEqual(d["fingerprint"]["modality"], "vision")

    def test_successful_ingest_posts_envelope(self):
        # httpx POST 모킹 — evidence_id 회수
        sent = {}

        class _Resp:
            def raise_for_status(self): pass
            def json(self): return {"evidence_id": "ev-server-assigned"}

        class _Client:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, json=None, headers=None):
                sent["url"] = url
                sent["evidence"] = json["evidence"]
                return _Resp()

        with patch.object(corpus_ingest, "_issue_jwt", return_value="tok"), \
             patch("httpx.AsyncClient", _Client):
            out = corpus_ingest.try_ingest(
                recipe_id="lid-patchcore", hyperparams={"memory_size": 50000.0},
                primary_metric="image_auroc", fitness=0.658,
                diag={"miss_rate": 0.92}, modality="vision")

        self.assertEqual(out, "ev-server-assigned")
        self.assertTrue(sent["url"].endswith("/ingest"))
        pcq = sent["evidence"]["pcq_record"]
        self.assertEqual(pcq["config"]["recipe_id"], "lid-patchcore")
        self.assertEqual(pcq["config"]["memory_size"], 50000.0)
        self.assertEqual(pcq["metrics"]["image_auroc"], 0.658)
        self.assertEqual(sent["evidence"]["tier"], "real")


class Test_reportResult_IngestIntegration(_StateDirIsolation):
    def test_report_succeeds_even_when_corpus_down(self):
        # 서버 없어도 placement 성공 (탐색 archive는 로컬 우선)
        rec = _recommend_action_impl("autoresearch", budget=5, seed_base=42, tasks=["nanochat"])
        with patch.object(corpus_ingest, "_TC_URL", "http://127.0.0.1:59999"):
            out = _report_result_impl("autoresearch", rec, fitness=-0.9,
                                      diag={"x": 1}, ingest=True)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["round"], 1)

    def test_ingest_false_skips_corpus(self):
        rec = _recommend_action_impl("autoresearch", budget=5, seed_base=42, tasks=["nanochat"])
        with patch("the_commons.exploration.corpus_ingest.try_ingest") as mock_ing:
            _report_result_impl("autoresearch", rec, fitness=-0.9, ingest=False)
            mock_ing.assert_not_called()

    def test_ingest_true_calls_try_ingest_with_recipe(self):
        rec = _recommend_action_impl("autoresearch", budget=5, seed_base=42, tasks=["nanochat"])
        with patch("the_commons.exploration.corpus_ingest.try_ingest",
                   return_value="ev-x") as mock_ing:
            _report_result_impl("autoresearch", rec, fitness=-0.9,
                                diag={"miss_rate": 0.1}, ingest=True)
            mock_ing.assert_called_once()
            kw = mock_ing.call_args.kwargs
            self.assertEqual(kw["recipe_id"], rec["genotype"]["recipe"])
            self.assertEqual(kw["fitness"], -0.9)
            self.assertEqual(kw["diag"], {"miss_rate": 0.1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
