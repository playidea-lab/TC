"""autoresearch-nanochat 프로파일 바인딩 단위 테스트.

GPU/워커 없이 검증 가능한 부분: num_params 미러 정확도, BD 격자 비축퇴, within 섭동,
materialize 상수치환+adapter append+py_compile. 실주행(dispatch)은 P-firstrun(GPU) 몫.
"""

from __future__ import annotations

import py_compile
import tempfile
import types
import unittest
from pathlib import Path

from experiments.autoresearch import profile as P
from the_commons.exploration.map_elites import ControllerConfig, MapElitesController
from the_commons.exploration.map_elites import Genotype

CODE_ROOT = Path(__file__).resolve().parents[4]  # ~/git/TheCommons (cq-ops의 형제)


class Test_numParams_MirrorsTrainPy(unittest.TestCase):
    def test_depth8_ar64_matches_program_md_50M(self):
        # program.md 요약 예시: depth8 → num_params_M 50.3
        self.assertAlmostEqual(P.num_params(8, 64) / 1e6, 50.3, delta=0.5)

    def test_num_params_monotone_increasing_in_depth(self):
        vals = [P.num_params(d, 64) for d in (4, 6, 8, 12, 16)]
        self.assertEqual(vals, sorted(vals))


class Test_binRule_Grid(unittest.TestCase):
    def test_seed_grid_spreads_2d_not_degenerate(self):
        pool = P.build_pool(["nanochat"], P.RECIPE_CATALOG)
        cells = {P.bin_rule(g) for g in pool["nanochat"]}
        sizes = {c[0] for c in cells}
        shapes = {c[1] for c in cells}
        # 두 축 모두 ≥3 bin 사용 = 1D collapse 아님
        self.assertGreaterEqual(len(sizes), 3)
        self.assertGreaterEqual(len(shapes), 3)

    def test_shape_bin_tracks_aspect_ratio(self):
        g32 = Genotype.of("autoresearch-nanochat", {"depth": 8.0, "aspect_ratio": 32.0})
        g128 = Genotype.of("autoresearch-nanochat", {"depth": 8.0, "aspect_ratio": 128.0})
        self.assertLess(P.shape_bin(g32), P.shape_bin(g128))


class Test_mutate_SizeOnly(unittest.TestCase):
    def test_mutate_increases_depth_keeps_aspect_ratio(self):
        g = Genotype.of("autoresearch-nanochat", {"depth": 8.0, "aspect_ratio": 64.0})
        gm = P.mutate(g)
        self.assertGreater(gm.as_dict()["depth"], g.as_dict()["depth"])
        self.assertEqual(gm.as_dict()["aspect_ratio"], 64.0)


class Test_materialize_UnmodifiedTemplate(unittest.TestCase):
    def setUp(self):
        self.args = types.SimpleNamespace(code_root=str(CODE_ROOT))

    def test_substitutes_constants_and_appends_adapter_compiles(self):
        if not (CODE_ROOT / P.TEMPLATE_REL).exists():
            self.skipTest("vendored train.py 없음(P-vendor 미실행)")
        g = Genotype.of("autoresearch-nanochat", {"depth": 10.0, "aspect_ratio": 128.0})
        code = P.materialize(g, self.args)
        self.assertIn("DEPTH = 10", code)
        self.assertIn("ASPECT_RATIO = 128", code)
        self.assertIn("@score=", code)
        self.assertIn("describe.json", code)
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(code)
            tmp = f.name
        py_compile.compile(tmp, doraise=True)  # 치환 후 문법 유효

    def test_original_template_unchanged_after_materialize(self):
        if not (CODE_ROOT / P.TEMPLATE_REL).exists():
            self.skipTest("vendored train.py 없음")
        before = (CODE_ROOT / P.TEMPLATE_REL).read_text(encoding="utf-8")
        P.materialize(Genotype.of("autoresearch-nanochat", {"depth": 16.0, "aspect_ratio": 256.0}), self.args)
        after = (CODE_ROOT / P.TEMPLATE_REL).read_text(encoding="utf-8")
        self.assertEqual(before, after)  # 원본 무수정(읽기만)


class Test_controller_ColdStartsWithProfile(unittest.TestCase):
    def test_cold_start_emits_valid_action(self):
        pool = P.build_pool(["nanochat"], P.RECIPE_CATALOG)
        ctrl = MapElitesController(ControllerConfig(0.4, 12, 20260527),
                                   P.bin_rule, ["nanochat"], pool, mutate_fn=P.mutate)
        action = ctrl.step()
        self.assertNotEqual(action.kind, "stop")
        self.assertEqual(action.genotype.recipe, "autoresearch-nanochat")


if __name__ == "__main__":
    unittest.main(verbosity=2)
