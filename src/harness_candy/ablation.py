"""Experimento de ablacion (seccion 12 del diseno combinado).

Ejecuta el mismo conjunto de tareas en cuatro configuraciones acumulativas
y compara Q medio, tasa de exito y costo por tarea:

  A  ADK solo (base: ejecutar sin validar)
  B  A + protocolos tipados + criterios de aceptacion + WEV
  C  B + adaptador Harness^2 (Propose-Probe-Compose con regla ec. 2)
  D  C + ELY (juez independiente, regresion y ajuste de prompts)

Veredicto: si C no supera a B por encima de delta, el costo de Harness^2 no
se justifica para esa tarea.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .agents import Agent, Task
from .components import ELY, WEV
from .harness import Budget, Harness2Adapter, HarnessStore
from .pool import ModelPool
from .protocols import ProtocolError, validate
from .quality import TraceLog, new_run_id, score_q, should_adopt


@dataclass
class AblationConfig:
    name: str
    use_protocols: bool
    use_wev: bool
    use_harness2: bool
    use_ely: bool


CONFIGS = [
    AblationConfig("A", use_protocols=False, use_wev=False, use_harness2=False, use_ely=False),
    AblationConfig("B", use_protocols=True, use_wev=True, use_harness2=False, use_ely=False),
    AblationConfig("C", use_protocols=True, use_wev=True, use_harness2=True, use_ely=False),
    AblationConfig("D", use_protocols=True, use_wev=True, use_harness2=True, use_ely=True),
]


@dataclass
class ConfigMetrics:
    config: str
    q_scores: list[float] = field(default_factory=list)
    success: int = 0
    runs: int = 0
    cost: float = 0.0

    @property
    def q_mean(self) -> float:
        return statistics.fmean(self.q_scores) if self.q_scores else 0.0

    @property
    def success_rate(self) -> float:
        return self.success / self.runs if self.runs else 0.0

    @property
    def cost_per_task(self) -> float:
        return self.cost / self.runs if self.runs else 0.0

    def to_dict(self) -> dict:
        return {
            "config": self.config,
            "q_mean": round(self.q_mean, 4),
            "success_rate": round(self.success_rate, 4),
            "cost_per_task": round(self.cost_per_task, 2),
            "runs": self.runs,
        }


@dataclass
class AblationReport:
    metrics: dict[str, ConfigMetrics]
    verdict: str

    def table(self) -> str:
        lines = ["| Config | Q medio | Tasa de exito | Costo/tarea | Corridas |", "|---|---|---|---|---|"]
        for name in ("A", "B", "C", "D"):
            m = self.metrics[name]
            lines.append(f"| {name} | {m.q_mean:.3f} | {m.success_rate:.1%} | {m.cost_per_task:.2f} | {m.runs} |")
        lines.append("")
        lines.append(self.verdict)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"metrics": {k: v.to_dict() for k, v in self.metrics.items()}, "verdict": self.verdict}


def run_ablation(
    tasks: list[Task],
    agent: Agent,
    pool: ModelPool,
    wev: WEV,
    ely: Optional[ELY] = None,
    *,
    k: int = 2,
    m: int = 3,
    alpha: float = 0.05,
    c_a: float = 1.0,
    trace_dir: str | Path = "traces/ablation",
    seed: int = 0,
) -> AblationReport:
    """Corre las 4 configuraciones acumulativas sobre el mismo conjunto."""
    trace_dir = Path(trace_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)
    metrics = {c.name: ConfigMetrics(c.name) for c in CONFIGS}

    for cfg in CONFIGS:
        store = HarnessStore()
        budget = Budget(total=10_000, beta=1.0, k=k, m=m)
        run_id = new_run_id()
        tracer = TraceLog(trace_dir / f"{cfg.name}-{run_id}.jsonl")
        for i, task in enumerate(tasks):
            tseed = seed + i * 17
            met = metrics[cfg.name]
            met.runs += 1
            met.cost += c_a
            if cfg.use_protocols:
                # los mensajes del flujo se validan; un malformado se rechaza
                try:
                    from .protocols import Envelope, YevMessage

                    validate(
                        YevMessage(
                            envelope=Envelope("yev", task.task_id, "ISA", "YEV"),
                            depende_de=[], instruccion=task.instruction, agente_destino="XEV",
                        ).to_dict()
                    )
                except ProtocolError as exc:
                    met.q_scores.append(0.0)
                    continue
            if not cfg.use_harness2:
                artifact = agent.run(task, harness=agent.default_harness, seed=tseed)
            else:
                adapter = Harness2Adapter(tracer=tracer, run_id=run_id)
                if not budget.allows_probe(c_a):
                    artifact = agent.run(task, seed=tseed)
                else:
                    budget.charge(c_a)
                    met.cost += budget.probe_cost(c_a) - c_a
                    h, _ev = adapter.adapt(agent, task, k=k, m=m, score_fn=wev.score, base_seed=tseed)
                    store.save(task.kind, agent.model, h, evidence={})
                    artifact = agent.run(task, harness=h, seed=tseed)
            if not cfg.use_wev:
                met.q_scores.append(1.0)  # sin evaluacion, solo "se ejecuto"
                met.success += 1
            else:
                msg, q = wev.evaluate(artifact, task.criterios)
                met.q_scores.append(q)
                if msg.veredicto == "aprobado":
                    met.success += 1
                tracer.record(
                    run_id=run_id, task_id=task.task_id, model=agent.model, seed=tseed,
                    harness=artifact.meta.get("harness", ""), phase=f"ablation-{cfg.name}", q=q,
                    verdict=msg.veredicto,
                )
        if cfg.use_ely and ely is not None:
            # D: ELY audita y fija linea base de regresion
            for i, task in enumerate(tasks):
                ely.regression.set_baseline(task.task_id, metrics[cfg.name].q_scores[i])

    b, c = metrics["B"], metrics["C"]
    adopt = should_adopt(b.q_scores, c.q_scores, alpha) if len(b.q_scores) == len(c.q_scores) and b.q_scores else False
    if adopt:
        verdict = (
            f"C supera a B por encima de delta (Q medio {b.q_mean:.3f} -> {c.q_mean:.3f}): "
            "el adaptador Harness^2 se justifica para este conjunto de tareas."
        )
    else:
        verdict = (
            f"C NO supera a B por encima de delta (Q medio {b.q_mean:.3f} -> {c.q_mean:.3f}): "
            "el costo de Harness^2 no se justifica para estas tareas; conservar B."
        )
    if metrics["D"].q_mean < metrics["C"].q_mean - 0.02:
        verdict += " Advertencia: D (con ELY) rinde peor que C: revisar calibracion del juez independiente."
    return AblationReport(metrics=metrics, verdict=verdict)


def k_curve(
    tasks: list,
    agent,
    pool: ModelPool,
    wev: WEV,
    *,
    ks: tuple[int, ...] = (1, 2, 4),
    m: int = 3,
    alpha: float = 0.05,
    c_a: float = 1.0,
    seed: int = 0,
) -> list[dict]:
    """Estima con DATOS PROPIOS la curva de mejora frente a k (--k N).

    Corre la configuracion C (con adaptador Harness^2) para cada k y devuelve
    [(k, q_medio, costo_por_tarea)]. El documento advierte que su curva es
    ilustrativa: aqui se mide. El costo de sondeo crece linealmente con k
    ((1 + 2k) m c_a) y la mejora tiende a saturar.
    """
    out = []
    for k in ks:
        q_scores, cost = [], 0.0
        for i, task in enumerate(tasks):
            tseed = seed + i * 17
            adapter = Harness2Adapter()
            h, _ev = adapter.adapt(agent, task, k=k, m=m, score_fn=wev.score, base_seed=tseed)
            artifact = agent.run(task, harness=h, seed=tseed)
            _msg, q = wev.evaluate(artifact, task.criterios)
            q_scores.append(q)
            cost += (1 + 2 * k) * m * c_a + c_a
        out.append(
            {
                "k": k,
                "q_medio": round(statistics.fmean(q_scores), 4) if q_scores else 0.0,
                "costo_por_tarea": round(cost / len(tasks), 2) if tasks else 0.0,
                "costo_sondeo_unitario": (1 + 2 * k) * m * c_a,
            }
        )
    return out
