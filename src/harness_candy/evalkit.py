"""Golden sets: evaluacion con casos dorados y umbral minimo (v3 §5.9, §19).

Un golden set es un JSON (esquema ``golden_set``) con casos de la forma::

    {"id": "scan-limpio", "task": {...}, "expect": {"veredicto": "aprobado", "q_min": 0.9,
     "artifact_contains": ["files_scanned"], "artifact_json_keys": ["secrets", "recommendations"]}}

``run_golden`` ejecuta cada caso con el pipeline real (run_task + WEV) y
compara contra ``expect``. ``EvalReport.assert_gate()`` se usa en CI para
bloquear regresiones (umbral ``min_pass_rate``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .agents import Agent
from .harness import Budget, HarnessStore
from .pool import ModelPool
from .quality import Criterion, TraceLog
from .runner import run_task
from .schemas import validate_named
from .components import WEV


@dataclass
class GoldenCase:
    id: str
    task: dict
    expect: dict

    @staticmethod
    def from_dict(d: dict) -> "GoldenCase":
        return GoldenCase(id=d["id"], task=d["task"], expect=d.get("expect", {}))


@dataclass
class GoldenSet:
    name: str
    cases: list[GoldenCase]
    min_pass_rate: float = 0.9

    @staticmethod
    def from_dict(data: dict) -> "GoldenSet":
        validate_named("golden_set", data)
        return GoldenSet(
            name=data["name"],
            cases=[GoldenCase.from_dict(c) for c in data["cases"]],
            min_pass_rate=float(data.get("min_pass_rate", 0.9)),
        )


def load_golden(path: str | Path) -> GoldenSet:
    return GoldenSet.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    q: float
    veredicto: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"case_id": self.case_id, "passed": self.passed, "q": round(self.q, 4), "veredicto": self.veredicto, "reasons": self.reasons}


@dataclass
class EvalReport:
    golden: str
    total: int
    passed: int
    results: list[CaseResult]
    min_pass_rate: float

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "golden": self.golden,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 4),
            "min_pass_rate": self.min_pass_rate,
            "gate_ok": self.pass_rate >= self.min_pass_rate,
            "results": [r.to_dict() for r in self.results],
        }

    def assert_gate(self, min_pass_rate: float | None = None) -> None:
        """Lanza AssertionError si el pass rate no alcanza el umbral (uso en CI)."""
        umbral = self.min_pass_rate if min_pass_rate is None else min_pass_rate
        if self.pass_rate < umbral:
            fallidos = [r.case_id for r in self.results if not r.passed]
            raise AssertionError(
                f"golden '{self.golden}': pass_rate {self.pass_rate:.3f} < umbral {umbral:.3f}; casos fallidos: {fallidos}"
            )


def _check_expect(case: GoldenCase, *, q: float, veredicto: str, artifact_text: str, artifact_content: Any, reasons: list[str]) -> bool:
    exp = case.expect
    ok = True
    if "q_min" in exp and q < float(exp["q_min"]):
        reasons.append(f"q={q:.3f} < q_min={exp['q_min']}")
        ok = False
    if "veredicto" in exp and veredicto != exp["veredicto"]:
        reasons.append(f"veredicto={veredicto!r} != esperado {exp['veredicto']!r}")
        ok = False
    if "status" in exp:
        status = "done" if veredicto == "aprobado" else "rejected"
        if status != exp["status"]:
            reasons.append(f"status={status!r} != esperado {exp['status']!r}")
            ok = False
    for needle in exp.get("artifact_contains", []):
        if needle not in artifact_text:
            reasons.append(f"artefacto no contiene {needle!r}")
            ok = False
    if "artifact_json_keys" in exp:
        if not isinstance(artifact_content, dict):
            reasons.append("el artefacto no es un objeto JSON")
            ok = False
        else:
            for key in exp["artifact_json_keys"]:
                if key not in artifact_content:
                    reasons.append(f"falta clave {key!r} en el artefacto JSON")
                    ok = False
    return ok


def run_golden(
    golden: GoldenSet | str | Path,
    *,
    agent: Agent,
    pool: ModelPool,
    store: HarnessStore,
    budget: Budget | None = None,
    wev: WEV,
    trace_dir: str | Path = "traces",
    seed: int = 0,
    max_cases: int | None = None,
) -> EvalReport:
    """Ejecuta todos los casos del golden set y devuelve el reporte agregado."""
    if not isinstance(golden, GoldenSet):
        golden = load_golden(golden)
    budget = budget or Budget(total=100_000, beta=0.5, k=2, m=3)
    trace_dir = Path(trace_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)
    tracer = TraceLog(trace_dir / f"golden-{golden.name}.jsonl")
    results: list[CaseResult] = []
    for i, case in enumerate(golden.cases):
        if max_cases is not None and i >= max_cases:
            break
        t = case.task
        from .agents import Task

        task = Task(
            task_id=t.get("task_id", case.id),
            kind=t["kind"],
            instruction=t.get("instruction", ""),
            inputs=dict(t.get("inputs", {})),
            criterios=[Criterion(c["id"], c.get("descripcion", ""), float(c.get("peso", 1.0))) for c in t.get("criterios", [])],
            max_reintentos=int(t.get("max_reintentos", 2)),
        )
        artifact = run_task(task, agent, pool, store, budget, wev, tracer=tracer, run_id=f"golden-{golden.name}", seed=seed + i)
        msg, q = wev.evaluate(artifact, task.criterios)
        reasons: list[str] = []
        passed = _check_expect(
            case,
            q=q,
            veredicto=msg.veredicto,
            artifact_text=artifact.to_text(),
            artifact_content=artifact.content,
            reasons=reasons,
        )
        results.append(CaseResult(case_id=case.id, passed=passed, q=q, veredicto=msg.veredicto, reasons=reasons))
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    return EvalReport(golden=golden.name, total=total, passed=passed, results=results, min_pass_rate=golden.min_pass_rate)
