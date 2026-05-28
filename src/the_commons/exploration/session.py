"""ExploreSession — profile 로드 + 컨트롤러 라이프사이클 + state·attribution 영속.

MCP 도구(`tc_explore_*`)가 매 호출마다 stateless로 동작하려면 컨트롤러를 세션 단위로
재구성해야 한다(이전 호출의 archive 복원). 이 모듈은 그 라이프사이클을 캡슐화한다.

state는 `~/.cq/state/explore/<profile>.json`(env `TC_EXPLORE_STATE_DIR` override),
attribution은 `~/.cq/state/explore/<profile>.attribution.jsonl` (V12, round별 1줄 append).
"""

from __future__ import annotations

import importlib
import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .map_elites import Action, Cell, ControllerConfig, Genotype, MapElitesController

_DEFAULT_STATE_DIR = Path.home() / ".cq" / "state" / "explore"


def _state_dir() -> Path:
    d = Path(os.environ.get("TC_EXPLORE_STATE_DIR", str(_DEFAULT_STATE_DIR)))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(profile: str) -> Path:
    return _state_dir() / f"{profile}.json"


def _attribution_path(profile: str) -> Path:
    return _state_dir() / f"{profile}.attribution.jsonl"


def load_profile(profile_name: str):
    """`experiments/<profile>/profile.py` 모듈을 동적 import.

    bottle_loop는 dir 이름이 'bottle_loop'이지만 도메인은 mvtec.
    profile_name = experiments/ 하위 디렉토리 이름과 일치.
    """
    return importlib.import_module(f"experiments.{profile_name}.profile")


def _geno_to_dict(g: Genotype | None) -> dict | None:
    if g is None:
        return None
    return {"recipe": g.recipe, "config": [list(kv) for kv in g.config]}


def _geno_from_dict(d: dict | None) -> Genotype | None:
    if d is None:
        return None
    return Genotype(d["recipe"], tuple(tuple(kv) for kv in d["config"]))


def action_to_dict(action: Action) -> dict:
    """Action(컨트롤러 추천) → MCP 응답 dict. 에이전트가 이걸 보고 모드 분기."""
    return {
        "mode": action.kind,                  # exploit_within | explore_tier1 | reeval | stop | cold start
        "task": action.task,
        "genotype": _geno_to_dict(action.genotype),
        "descriptor": list(action.descriptor),
        "seed": action.seed,
        "target": action.target,
        "reason": action.reason,
    }


def action_from_dict(d: dict) -> Action:
    return Action(
        kind=d["mode"], task=d.get("task", ""),
        genotype=_geno_from_dict(d.get("genotype")),
        descriptor=tuple(d.get("descriptor", (-1, -1))),
        seed=int(d.get("seed", 0)),
        target=d.get("target", "elite"),
        reason=d.get("reason", ""),
    )


class ExploreSession:
    """profile 한 개에 묶인 컨트롤러 세션. MCP 호출마다 load→step/report→save."""

    def __init__(self, profile_name: str, *, epsilon: float = 0.4, budget: int = 30,
                 seed_base: int | None = None, tasks: list[str] | None = None) -> None:
        self.profile_name = profile_name
        self.profile = load_profile(profile_name)
        # cold start config (state 없을 때만 사용)
        self._cfg = ControllerConfig(
            epsilon=epsilon, budget=budget,
            seed_base=seed_base if seed_base is not None else 20260528,
        )
        self._tasks = tasks if tasks is not None else getattr(self.profile, "DEFAULT_TASKS", ["default"])
        self.controller: MapElitesController = self._build_or_restore()

    def _build_or_restore(self) -> MapElitesController:
        sp = _state_path(self.profile_name)
        pool = self.profile.build_pool(self._tasks, self.profile.RECIPE_CATALOG)
        ctrl = MapElitesController(self._cfg, self.profile.bin_rule, self._tasks, pool,
                                   mutate_fn=self.profile.mutate)
        if sp.exists():
            state = json.loads(sp.read_text(encoding="utf-8"))
            _restore(ctrl, state)
        return ctrl

    def save(self) -> None:
        sp = _state_path(self.profile_name)
        state = _dump(self.controller, self.profile_name, self._tasks)
        sp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def log_attribution(self, record: dict[str, Any]) -> None:
        """V12: round별 (mode, parent, prompt, output, result, ...) JSONL append."""
        ap = _attribution_path(self.profile_name)
        with ap.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def archive_snapshot(self) -> dict:
        return _dump(self.controller, self.profile_name, self._tasks)


def _dump(ctrl: MapElitesController, profile: str, tasks: list[str]) -> dict:
    arch = {}
    for (t, c0, c1), cell in ctrl.archive.items():
        arch[f"{t}|{c0}|{c1}"] = {
            "descriptor": [c0, c1],
            "elite": _geno_to_dict(cell.elite),
            "samples": cell.samples,
            "challenger": _geno_to_dict(cell.challenger),
            "challenger_samples": cell.challenger_samples,
        }
    return {
        "profile": profile, "tasks": list(tasks), "round": ctrl.round,
        "epsilon": ctrl.cfg.epsilon, "budget": ctrl.cfg.budget,
        "seed_base": ctrl.cfg.seed_base,
        "archive": arch, "universals": ctrl.universals,
        "tried": [[t, g.recipe, [list(kv) for kv in g.config]] for t, g in ctrl.tried],
        "n_cells": len(ctrl.archive),
    }


def _restore(ctrl: MapElitesController, state: dict) -> None:
    for key, c in state.get("archive", {}).items():
        t, c0, c1 = key.split("|")
        cell = Cell(descriptor=(int(c0), int(c1)))
        cell.elite = _geno_from_dict(c.get("elite"))
        cell.samples = list(c.get("samples", []))
        cell.challenger = _geno_from_dict(c.get("challenger"))
        cell.challenger_samples = list(c.get("challenger_samples", []))
        ctrl.archive[(t, int(c0), int(c1))] = cell
    ctrl.round = int(state.get("round", 0))
    ctrl.universals = list(state.get("universals", []))
    for t, recipe, cfg in state.get("tried", []):
        ctrl.tried.add((t, Genotype(recipe, tuple(tuple(kv) for kv in cfg))))
    # rng advance — round만큼 굴려 분기 재현 (RE9 잔존)
    for _ in range(ctrl.round):
        ctrl.rng.random()


__all__ = ["ExploreSession", "load_profile", "action_to_dict", "action_from_dict"]
