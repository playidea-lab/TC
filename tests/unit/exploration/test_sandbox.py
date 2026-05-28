"""V8 sandbox 정적 검사 단위 테스트 — 5종 위반 fixture + 정상 코드 통과."""

from __future__ import annotations

import unittest

from the_commons.exploration.sandbox import (
    ADAPTER_MARKER, check_code, is_blocked, violations_to_dict,
)

_OK_CODE_WITH_ADAPTER = f"""
import torch
from prepare import evaluate_bpb

DEPTH = 8
ASPECT_RATIO = 64

# ... training ...
val_bpb = 0.99

{ADAPTER_MARKER} (auto-appended) ---
import json as _json
print(f"@score={{-val_bpb:.6f}}", flush=True)
with open("describe.json", "w") as _f:
    _json.dump({{"best_value": -val_bpb}}, _f)
"""


class Test_check_OkCodePassesAdapterMarker(unittest.TestCase):
    def test_legitimate_train_with_adapter_passes(self):
        vs = check_code(_OK_CODE_WITH_ADAPTER)
        self.assertFalse(is_blocked(vs), f"unexpected violations: {vs}")

    def test_empty_code_no_violations(self):
        self.assertEqual(check_code(""), [])


class Test_check_BlocksFiveRewardHackingPatterns(unittest.TestCase):
    def test_syntax_error_blocks(self):
        vs = check_code("def broken(:\n    return 1\n")
        self.assertTrue(is_blocked(vs))
        self.assertEqual(vs[0].rule, "syntax_error")

    def test_prepare_monkeypatch_attr_assign_blocks(self):
        code = """
import prepare
prepare.evaluate_bpb = lambda *a, **k: 0.001
"""
        vs = check_code(code)
        self.assertTrue(is_blocked(vs))
        self.assertTrue(any(v.rule == "prepare_monkeypatch" for v in vs))

    def test_prepare_monkeypatch_setattr_blocks(self):
        code = """
import prepare
setattr(prepare, "evaluate_bpb", lambda *a: 0)
"""
        vs = check_code(code)
        self.assertTrue(is_blocked(vs))
        self.assertTrue(any(v.rule == "prepare_monkeypatch" for v in vs))

    def test_evaluate_bpb_function_redefine_blocks(self):
        code = """
def evaluate_bpb(model, tok, bs):
    return 0.001
"""
        vs = check_code(code)
        self.assertTrue(is_blocked(vs))
        self.assertEqual(vs[0].rule, "evaluate_redefine")

    def test_evaluate_bpb_top_level_assign_blocks(self):
        code = """
evaluate_bpb = lambda *a, **k: 0.001
"""
        vs = check_code(code)
        self.assertTrue(is_blocked(vs))
        self.assertEqual(vs[0].rule, "evaluate_redefine")

    def test_score_emit_before_adapter_blocks(self):
        code = f"""
print("@score=-0.001")  # agent forged emit, before adapter
val_bpb = 5.0
{ADAPTER_MARKER}
print(f"@score={{-val_bpb:.6f}}")
"""
        vs = check_code(code)
        self.assertTrue(is_blocked(vs))
        self.assertTrue(any(v.rule == "score_outside_adapter" for v in vs))

    def test_score_emit_only_after_adapter_passes(self):
        # 위 _OK_CODE_WITH_ADAPTER fixture가 이 케이스를 이미 커버 — 회귀 보호용
        vs = check_code(_OK_CODE_WITH_ADAPTER)
        self.assertFalse(any(v.rule == "score_outside_adapter" for v in vs))

    def test_val_shard_path_read_blocks(self):
        code = """
with open("/Users/x/.cache/autoresearch/data/shard_06542.parquet", "rb") as f:
    val_bytes = f.read()
"""
        vs = check_code(code)
        self.assertTrue(is_blocked(vs))
        # shard_06542 + .cache/autoresearch/data 둘 다 잡힘
        self.assertTrue(any(v.rule == "val_data_access" for v in vs))


class Test_violations_DictSerialization(unittest.TestCase):
    def test_dict_has_rule_severity_message_line(self):
        vs = check_code("def evaluate_bpb(): return 0\n")
        out = violations_to_dict(vs)
        self.assertEqual(set(out[0].keys()), {"rule", "severity", "message", "line"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
