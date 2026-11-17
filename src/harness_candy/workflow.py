"""Workflows declarativos en JSON (v3 §4.4 DSL de casos, flujos compuestos).

Formato::

    {"name": "wf", "context": {"k": "v"},
     "steps": [
       {"id": "scan", "type": "task", "task": {"task_id": "...", "kind": "...", ...}},
       {"id": "par", "type": "parallel", "steps": ["a", "b"]},     # ids de steps previos? no: define grupo inline
       {"id": "cond", "type": "task", "task": {...}, "when": "ctx['ok'] == True", "retry": 2}
     ]}

Tipos de step:
  - ``task``: ejecuta una Task con run_task (Harness^2 + WEV). Guarda el
    resultado en ``context["results"][step_id]`` y ``context["qs"][step_id]``.
  - ``set``: ``context[key] = value`` (value puede ser expr sobre ctx).
  - ``parallel``: ejecuta sus ``steps`` (definidos inline) en paralelo con
    ThreadPoolExecutor; heredan el contexto.
  - ``when``: condicion sobre ``ctx`` (expresion Python restringida: sin
    builtins, solo el dict ctx). Si es falsa, el step se salta.
  - ``retry``: reintenta el step ante fallo (usa retry_call).

El resultado es ``WorkflowResult`` con contexto final, resultados por step,
metricas y duracion.
"""
from __future__ import annotations

import ast
import json
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .agents import Agent, Task
from .graph import CycleError, dependencias_a_grafo
from .components import WEV
from .harness import Budget, HarnessStore
from .metrics import MetricsCollector
from .pool import ModelPool
from .quality import Criterion, TraceLog, new_run_id
from .retry import RetryExhausted, retry_call
from .runner import run_task
from .schemas import validate_named

WORKFLOW_SCHEMA_KEY = "workflow"


def _expr_segura(expr: str, ctx: dict) -> Any:
    """Evalua una expresion sobre ctx con builtins desactivados (when/set)."""
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id not in ("len", "str", "int", "float", "bool", "abs", "min", "max", "sum", "sorted", "list", "dict"):
            raise ValueError(f"llamada no permitida en expresion: {node.func.id}")
        if isinstance(node, ast.Name) and node.id not in ("ctx", "len", "str", "int", "float", "bool", "abs", "min", "max", "sum", "sorted", "list", "dict", "True", "False", "None"):
            raise ValueError(f"nombre no permitido en expresion: {node.id}")
    return eval(compile(tree, "<when>", "eval"), {"__builtins__": {}}, {"ctx": ctx})


@dataclass
class StepResult:
    step_id: str
    status: str  # done | skipped | failed
    detalle: dict = field(default_factory=dict)
    duracion: float = 0.0

    def to_dict(self) -> dict:
        return {"step_id": self.step_id, "status": self.status, "detalle": self.detalle, "duracion": round(self.duracion, 3)}


@dataclass
class WorkflowResult:
    run_id: str
    workflow: str
    context: dict
    steps: dict[str, StepResult]
    duracion: float
    trace_path: str
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "workflow": self.workflow,
            "context": {k: v for k, v in self.context.items() if k not in ("results",)} | {"n_resultados": len(self.context.get("results", {}))},
            "steps": {k: v.to_dict() for k, v in self.steps.items()},
            "duracion": round(self.duracion, 3),
            "trace_path": self.trace_path,
            "metrics": self.metrics,
        }


class Workflow:
    def __init__(self, name: str, steps: list[dict], context: dict | None = None):
        self.name = name
        self.steps = steps
        self.context = dict(context or {})

    @staticmethod
    def from_dict(data: dict) -> "Workflow":
        if "name" not in data or "steps" not in data:
            raise ValueError("workflow requiere 'name' y 'steps'")
        for s in data["steps"]:
            if "id" not in s or "type" not in s:
                raise ValueError(f"step malformado: {s!r}")
            if s["type"] not in ("task", "set", "parallel", "foreach"):
                raise ValueError(f"tipo de step desconocido: {s['type']!r}")
            if s["type"] == "foreach" and ("steps" not in s or "items" not in s):
                raise ValueError("un step 'foreach' requiere 'items' y 'steps'")
        return Workflow(data["name"], data["steps"], data.get("context", {}))

    @staticmethod
    def load(path: str | Path) -> "Workflow":
        return Workflow.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _task_from_dict(d: dict) -> Task:
    validate_named("task", d)
    return Task(
        task_id=d["task_id"],
        kind=d["kind"],
        instruction=d.get("instruction", ""),
        inputs=dict(d.get("inputs", {})),
        criterios=[Criterion(c["id"], c.get("descripcion", ""), float(c.get("peso", 1.0))) for c in d.get("criterios", [])],
        max_reintentos=int(d.get("max_reintentos", 2)),
    )


def run_workflow(
    wf: Workflow,
    *,
    agent: Agent,
    pool: ModelPool,
    store: HarnessStore,
    budget: Budget | None = None,
    wev: WEV,
    trace_dir: str | Path = "traces",
    max_workers: int = 4,
    seed: int = 0,
) -> WorkflowResult:
    """Ejecuta el workflow paso a paso (los 'parallel' en paralelo)."""
    inicio = time.time()
    run_id = new_run_id()
    trace_dir = Path(trace_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)
    tracer = TraceLog(trace_dir / f"wf-{run_id}.jsonl")
    budget = budget or Budget(total=100_000, beta=0.5, k=2, m=3)
    ctx = dict(wf.context)
    ctx.setdefault("results", {})
    ctx.setdefault("qs", {})
    steps_out: dict[str, StepResult] = {}
    metrics = MetricsCollector()

    def ejecutar_step(step: dict, _ctx: dict | None = None) -> StepResult:
        c = _ctx if _ctx is not None else ctx
        sid = step["id"]
        t0 = time.time()
        # condicion when
        if "when" in step:
            try:
                ok = bool(_expr_segura(step["when"], c))
            except Exception as e:
                return StepResult(sid, "failed", {"error": f"when fallo: {e}"}, time.time() - t0)
            if not ok:
                return StepResult(sid, "skipped", {"when": step["when"]}, time.time() - t0)
        tipo = step["type"]
        if tipo == "foreach":
            items = _expr_segura(step["items"], c)
            if not isinstance(items, (list, tuple)):
                return StepResult(sid, "failed", {"error": "items no es una lista"}, time.time() - t0)
            nombre_var = step.get("as", "item")
            sub_resultados = []
            for i, item in enumerate(items):
                sub_ctx = dict(c)
                sub_ctx.setdefault("results", {})
                sub_ctx.setdefault("qs", {})
                sub_ctx[nombre_var] = item
                sub_ctx["indice"] = i
                for sub in step["steps"]:
                    sub = dict(sub)
                    sub.setdefault("id", f"{sid}[{i}]:{sub.get('id', '?')}")
                    # los sub-steps ven el ctx con la variable del loop
                    r = ejecutar_step(sub, sub_ctx)
                    sub_resultados.append(r.to_dict())
                    steps_out[r.step_id] = r
                    # propagar resultados y variables al ctx global para pasos posteriores
                    c.setdefault("results", {}).update(sub_ctx.get("results", {}))
                    c.setdefault("qs", {}).update(sub_ctx.get("qs", {}))
                    for k, v in sub_ctx.items():
                        if k not in ("results", "qs"):
                            c[k] = v
            return StepResult(sid, "done", {"iteraciones": len(items), "sub": sub_resultados}, time.time() - t0)
        if tipo == "set":
            key = step["key"]
            val = step.get("value")
            if isinstance(val, str) and val.startswith("expr:"):
                val = _expr_segura(val[5:], c)
            c[key] = val
            return StepResult(sid, "done", {"set": key}, time.time() - t0)
        if tipo == "parallel":
            sub = step.get("steps", [])
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futuros = {ex.submit(ejecutar_step, s): s["id"] for s in sub}
                for fut, s_id in futuros.items():
                    res = fut.result()
                    steps_out[s_id] = res
            return StepResult(sid, "done", {"parallel": [s["id"] for s in sub]}, time.time() - t0)
        # task
        reintentos = int(step.get("retry", 0)) + 1
        try:
            def _run():
                task = _task_from_dict(step["task"])
                s = seed + zlib.crc32(sid.encode()) % 1000
                artifact = run_task(task, agent, pool, store, budget, wev, tracer=tracer, run_id=run_id, seed=s)
                msg, q = wev.evaluate(artifact, task.criterios)
                return artifact, msg, q

            artifact, msg, q = retry_call(_run, attempts=reintentos, seed=seed, retry_on=(Exception,))
        except RetryExhausted as e:
            return StepResult(sid, "failed", {"error": str(e.last)}, time.time() - t0)
        c["results"][sid] = {"veredicto": msg.veredicto, "checks": msg.checks, "hallazgos": [h.to_dict() for h in msg.hallazgos]}
        c["qs"][sid] = q
        metrics.mark_cumplidos(sum(1 for v in msg.checks.values() if v))
        metrics.pruebas_total += len(msg.checks)
        metrics.pruebas_superadas += sum(1 for v in msg.checks.values() if v)
        metrics.costo_corridas += 1.0
        return StepResult(sid, "done" if msg.veredicto == "aprobado" else "rejected", {"q": q, "veredicto": msg.veredicto}, time.time() - t0)

    # orden topologico por depends_on (fail-closed ante ciclos o deps desconocidas)
    ids = {st["id"] for st in wf.steps}
    deps = {}
    for st in wf.steps:
        for d in st.get("depends_on", []):
            if d not in ids:
                raise ValueError(f"step {st['id']!r} depende de {d!r} que no existe")
        deps[st["id"]] = list(st.get("depends_on", []))
    try:
        orden = dependencias_a_grafo(deps).topo_sort()
    except CycleError as e:
        raise ValueError(f"dependencias ciclicas en el workflow: {e}") from e
    por_id = {st["id"]: st for st in wf.steps}
    for sid in orden:
        res = ejecutar_step(por_id[sid])
        steps_out[sid] = res

    duracion = time.time() - inicio
    return WorkflowResult(
        run_id=run_id,
        workflow=wf.name,
        context=ctx,
        steps=steps_out,
        duracion=duracion,
        trace_path=str(tracer.path),
        metrics=metrics.snapshot(duracion=duracion, costo_adapt=budget.spent_adapt),
    )

