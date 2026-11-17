"""Suites de tareas en JSON y su ejecucion (checklist v3 §4.4, DSL de casos).

Formato de una suite (valido contra el esquema publicado ``suite``)::

    {
      "name": "seguridad-basica",
      "seed": 0,
      "max_concurrency": 4,
      "budget": {"total": 10000, "beta": 0.5, "k": 2, "m": 3},
      "tasks": [
        {"task_id": "scan", "kind": "security_scan", "instruction": "escanear repo",
         "inputs": {"root": "."}, "deps": [], "agent": "XEV",
         "criterios": [{"id": "json_valido", "peso": 1.0}]}
      ]
    }

``run_suite`` ejecuta las tareas como DAG (respeta ``deps``) con el mismo
pipeline por nodo que el runner (Harness^2 + WEV) y devuelve un SuiteResult
con metricas agregadas.
"""
from __future__ import annotations

import json
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .agents import Agent, Task
from .dag import DAGExecutor, NodeResult, TaskDAG, TaskNode
from .harness import Budget, HarnessStore
from .metrics import MetricsCollector
from .pool import ModelPool
from .protocols import WevMessage
from .quality import Criterion, TraceLog, new_run_id, score_q
from .runner import run_task
from .schemas import validate_named
from .components import WEV


@dataclass
class Suite:
    name: str
    tasks: list[dict]
    seed: int = 0
    max_concurrency: int = 4
    budget: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(data: dict) -> "Suite":
        validate_named("suite", data)
        return Suite(
            name=data["name"],
            tasks=data["tasks"],
            seed=int(data.get("seed", 0)),
            max_concurrency=int(data.get("max_concurrency", 4)),
            budget=dict(data.get("budget", {})),
        )

    def to_dag(self) -> TaskDAG:
        dag = TaskDAG()
        for t in self.tasks:
            dag.add(
                TaskNode(
                    task_id=t["task_id"],
                    kind=t["kind"],
                    instruction=t.get("instruction", ""),
                    deps=list(t.get("deps", [])),
                    agent=t.get("agent", "XEV"),
                    criterios=[Criterion(c["id"], c.get("descripcion", ""), float(c.get("peso", 1.0))) for c in t.get("criterios", [])],
                    max_reintentos=int(t.get("max_reintentos", 2)),
                    inputs=dict(t.get("inputs", {})),
                    herramienta=t.get("herramienta", ""),
                )
            )
        dag.validate()
        return dag

    def task_list(self) -> list[dict]:
        return [{"task_id": t["task_id"], "kind": t["kind"], "deps": t.get("deps", [])} for t in self.tasks]


def load_suite(path: str | Path) -> Suite:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Suite.from_dict(data)


@dataclass
class SuiteResult:
    run_id: str
    suite: str
    results: dict[str, NodeResult]
    qs: dict[str, float]
    wev_reports: dict[str, WevMessage]
    duracion: float
    trace_path: str
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "suite": self.suite,
            "objetivo": f"suite:{self.suite}",
            "dag_results": {k: v.to_dict() for k, v in self.results.items()},
            "qs": self.qs,
            "wev_reports": {k: v.to_dict() for k, v in self.wev_reports.items()},
            "duracion": round(self.duracion, 3),
            "trace_path": self.trace_path,
            "metrics": self.metrics,
        }


def run_suite(
    suite: Suite,
    *,
    agent: Agent,
    pool: ModelPool,
    store: HarnessStore,
    budget: Budget | None = None,
    wev: WEV,
    trace_dir: str | Path = "traces",
    on_event=None,
) -> SuiteResult:
    """Ejecuta una suite completa como DAG y devuelve el resultado agregado."""
    inicio = time.time()
    run_id = new_run_id()
    trace_dir = Path(trace_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)
    tracer = TraceLog(trace_dir / f"{run_id}.jsonl")
    budget = budget or Budget(total=10_000, beta=0.5, k=2, m=3)
    dag = suite.to_dag()

    def handler(node: TaskNode, context: dict) -> NodeResult:
        task = Task(
            task_id=node.task_id,
            kind=node.kind,
            instruction=node.instruction,
            inputs=node.inputs,
            criterios=node.criterios,
            max_reintentos=node.max_reintentos,
        )
        seed = suite.seed + zlib.crc32(node.task_id.encode("utf-8")) % 1000
        artifact = run_task(task, agent, pool, store, budget, wev, tracer=tracer, run_id=run_id, seed=seed)
        msg, q = wev.evaluate(artifact, node.criterios)
        status = "done" if msg.veredicto == "aprobado" else "rejected"
        return NodeResult(task_id=node.task_id, status=status, artifact=artifact, wev=msg)

    executor = DAGExecutor(handler=handler, max_concurrency=suite.max_concurrency, on_event=on_event)
    results = executor.execute(dag, {"seed": suite.seed})

    metrics = MetricsCollector()
    qs: dict[str, float] = {}
    wev_reports: dict[str, WevMessage] = {}
    for tid, res in results.items():
        node = dag.nodes[tid]
        metrics.add_result(res, criterios_total=len(node.criterios))
        if res.wev is not None:
            wev_reports[tid] = res.wev
            checks = res.wev.checks
            criterios = [Criterion(k, "", 1.0) for k in checks]
            qs[tid] = score_q(criterios, [k for k, v in checks.items() if v], res.wev.hallazgos)
            metrics.mark_cumplidos(sum(1 for v in checks.values() if v))
        metrics.costo_corridas += 1.0
    duracion = time.time() - inicio
    return SuiteResult(
        run_id=run_id,
        suite=suite.name,
        results=results,
        qs=qs,
        wev_reports=wev_reports,
        duracion=duracion,
        trace_path=str(tracer.path),
        metrics=metrics.snapshot(duracion=duracion, costo_adapt=budget.spent_adapt),
    )
