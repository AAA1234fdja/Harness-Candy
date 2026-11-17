"""Flujo general de trabajo (seccion 8) y run_task (Listado 1).

Pasos: recepcion del objetivo -> plan (ISA) -> contexto (ZEV) ->
distribucion (YEV/DAG) -> ejecucion (XEV, con ciclo Harness^2 por agente) ->
validacion (WEV) -> evaluacion global (ELY) -> consolidacion en memoria.
"""
from __future__ import annotations

import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .agents import Agent, Artifact, Task
from .components import ELY, ISA, WEV, XEV, YEV, ZEV
from .dag import DAGExecutor, NodeResult, TaskDAG, TaskNode
from .harness import Budget, Harness, Harness2Adapter, HarnessStore
from .memory import KnowledgeMemory, VariableMemory
from .metrics import MetricsCollector
from .pool import ModelPool
from .protocols import WevMessage
from .quality import Criterion, TraceLog, new_run_id, score_q


def run_task(
    task: Task,
    agent: Agent,
    pool: ModelPool,
    store: HarnessStore,
    budget: Budget,
    wev: WEV,
    *,
    tracer: TraceLog | None = None,
    run_id: str = "",
    seed: int = 0,
    adapter: Harness2Adapter | None = None,
) -> Artifact:
    """Listado 1 del diseno combinado (adaptador Harness^2 por agente).

    1. Nivel 3: modelo y clave por rol (pool).
    2. Reutiliza un harness validado para (task.kind, model) si existe.
    3. Si no existe y el presupuesto lo permite: Propose -> Probe -> Compose.
    4. Ejecuta la tarea con el harness adoptado (o el por defecto).
    """
    clave, model = pool.select(task.kind)
    agent = agent.with_model(model)
    h = store.lookup(task.kind, model)
    if h is None and budget.allows_probe(c_a=1.0):
        budget.charge(c_a=1.0)
        adapter = adapter or Harness2Adapter(tracer=tracer, run_id=run_id)
        h, evidence = adapter.adapt(agent, task, k=budget.k, m=budget.m, score_fn=wev.score, base_seed=seed)
        store.save(task.kind, model, h, evidence=evidence.to_dict(), q_mean=sum(evidence.reference_scores) / max(1, len(evidence.reference_scores)))
    artifact = agent.run(task, harness=h or agent.default_harness, seed=seed)
    if tracer is not None:
        msg, q = wev.evaluate(artifact, task.criterios)
        tracer.record(
            run_id=run_id, task_id=task.task_id, model=model, seed=seed,
            harness=(h or agent.default_harness).label(), phase="final", q=q, verdict=msg.veredicto,
        )
    return artifact


@dataclass
class RunResult:
    run_id: str
    objetivo: str
    plan: dict
    dag_results: dict
    wev_reports: dict[str, WevMessage]
    qs: dict[str, float]
    ely_audit: dict
    costo_adaptacion: float
    trace_path: str
    duracion: float
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "objetivo": self.objetivo,
            "plan": self.plan,
            "dag_results": {k: v.to_dict() for k, v in self.dag_results.items()},
            "wev_reports": {k: v.to_dict() for k, v in self.wev_reports.items()},
            "qs": self.qs,
            "ely_audit": self.ely_audit,
            "costo_adaptacion": self.costo_adaptacion,
            "trace_path": self.trace_path,
            "duracion": round(self.duracion, 3),
            "metrics": self.metrics,
        }


class CoworkRunner:
    """Orquesta Ely-Cowork completo: ISA -> YEV -> (ZEV, XEV) -> WEV -> ELY."""

    def __init__(
        self,
        *,
        pool: ModelPool,
        store: HarnessStore,
        budget: Budget,
        isa: ISA,
        yev: YEV,
        zev: ZEV,
        xev: XEV,
        wev: WEV,
        ely: ELY,
        trace_dir: str | Path = "traces",
        max_concurrency: int = 4,
    ):
        self.pool = pool
        self.store = store
        self.budget = budget
        self.isa = isa
        self.yev = yev
        self.zev = zev
        self.xev = xev
        self.wev = wev
        self.ely = ely
        self.trace_dir = Path(trace_dir)
        self.max_concurrency = max_concurrency
        self.memory_vars = VariableMemory()
        self.events: list[tuple[str, dict]] = []

    def _execute_node(self, node: TaskNode, context: dict, run_id: str, tracer: TraceLog) -> NodeResult:
        """Ejecuta un nodo del DAG: run_task (con Harness^2) + validacion WEV."""
        task = Task(
            task_id=node.task_id,
            kind=node.kind,
            instruction=node.instruction,
            inputs=node.inputs,
            criterios=node.criterios,
            max_reintentos=node.max_reintentos,
        )
        # hash determinista (crc32) para que las trazas sean reproducibles 100%
        seed = context.get("seed", 0) + zlib.crc32(node.task_id.encode("utf-8")) % 1000
        # contexto recuperado por ZEV viaja como entrada (fragmentos relevantes)
        if context.get("zev_fragmentos"):
            task.inputs = {**task.inputs, "contexto_zev": context["zev_fragmentos"][:5]}
        agent = self.xev.agents.get(node.agent) or self.xev.agents.get("XEV")
        artifact = run_task(
            task, agent, self.pool, self.store, self.budget, self.wev,
            tracer=tracer, run_id=run_id, seed=seed,
        )
        msg, q = self.wev.evaluate(artifact, node.criterios)
        status = "done" if msg.veredicto == "aprobado" else "rejected"
        # el feedback de WEV queda en el estado para el reintento
        self.memory_vars.set(f"wev:{node.task_id}", msg.to_dict(), scope="task", actor="WEV")
        self.memory_vars.set(f"artifact:{node.task_id}", artifact.content, scope="task", actor="XEV")
        return NodeResult(task_id=node.task_id, status=status, artifact=artifact, wev=msg)

    def run(self, objetivo: str, inputs: dict | None = None, seed: int = 0, cancel_event=None) -> RunResult:
        start = time.time()
        run_id = new_run_id()
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        tracer = TraceLog(self.trace_dir / f"{run_id}.jsonl")
        inputs = inputs or {}
        metrics = MetricsCollector()

        # 1-2. recepcion del objetivo y planificacion (ISA)
        plan = self.isa.plan(objetivo, inputs)
        self.memory_vars.set("plan", plan.to_dict(), scope="session", actor="ISA")

        # 3. recuperacion de contexto (ZEV)
        zev_msg = self.zev.retrieve(objetivo, task_id=run_id)
        self.zev.remember(zev_msg)
        context = {
            "seed": seed,
            "zev_fragmentos": [f["contenido"][:400] for f in zev_msg.fragmentos],
            "inputs": inputs,
            "cancel_event": cancel_event,
        }

        # 4. distribucion (YEV): DAG con modelo/clave por nodo
        dag = self.yev.build_dag(plan, run_id=run_id)
        for node in dag.nodes.values():
            node.inputs = {**inputs, **node.inputs}

        # 5-6. ejecucion (XEV) y validacion (WEV) via el DAG
        executor = DAGExecutor(
            handler=lambda n, ctx: self._execute_node(n, ctx, run_id, tracer),
            max_concurrency=self.max_concurrency,
            on_event=lambda evt, data: self.events.append((evt, data)),
        )
        results = executor.execute(dag, context)

        # 7. evaluacion global (ELY)
        ely_informe = self.ely.audit(results, tracer.entries(), run_id=run_id)
        self.ely.remember_lessons(ely_informe, run_id)

        # 8. consolidacion + metricas (seccion 10 del PDF: no se miden lineas de codigo)
        qs, wev_reports = {}, {}
        for tid, res in results.items():
            node = dag.nodes[tid]
            metrics.add_result(res, criterios_total=len(node.criterios))
            if res.wev is not None:
                wev_reports[tid] = res.wev
                checks = res.wev.checks
                criterios = [Criterion(k, "", 1.0) for k in checks]
                qs[tid] = score_q(criterios, [k for k, v in checks.items() if v], res.wev.hallazgos)
                metrics.mark_cumplidos(sum(1 for v in checks.values() if v))
            metrics.costo_corridas += 1.0  # costo por tarea: una corrida = 1 unidad
        aceptados = [tid for tid, r in results.items() if r.status == "done"]
        for tid in aceptados:
            self.memory_vars.set(f"consolidado:{tid}", True, scope="project", actor="YEV")

        return RunResult(
            run_id=run_id,
            objetivo=objetivo,
            plan=plan.to_dict(),
            dag_results=results,
            wev_reports=wev_reports,
            qs=qs,
            ely_audit=ely_informe,
            costo_adaptacion=self.budget.spent_adapt,
            trace_path=str(tracer.path),
            duracion=time.time() - start,
            metrics=metrics.snapshot(duracion=time.time() - start, costo_adapt=self.budget.spent_adapt),
        )
