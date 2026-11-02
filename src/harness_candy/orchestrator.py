"""Orquestador de campanas: muchos objetivos con un presupuesto global (v3 §13 FinOps).

Una ``Campaign`` es una lista de objetivos con un presupuesto total. El
orquestador ejecuta cada objetivo con el CoworkRunner mientras quede
presupuesto (``Budget.allows_probe`` por objetivo), agrega metricas y
produce un resumen ejecutivo (q medio, tasa de aprobados, costo total).

Útil para evaluar el sistema sobre un conjunto de objetivos (bench propio)
y para limitar el costo total de inferencia (limitacion F del paper
arXiv:2610.14224: la recursion anade coste -> aqui se impone un tope duro).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .factory import build_runner
from .harness import Budget
from .runner import CoworkRunner, RunResult
from .schemas import validate_named

CAMPAIGN_SCHEMA = {
    "type": "object",
    "required": ["name", "objetivos"],
    "additionalProperties": True,
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "budget_total": {"type": "number", "exclusiveMinimum": 0},
        "beta": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "k": {"type": "integer", "minimum": 0},
        "m": {"type": "integer", "minimum": 1},
        "seed": {"type": "integer"},
        "objetivos": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["objetivo"],
                "properties": {
                    "objetivo": {"type": "string", "minLength": 1},
                    "inputs": {"type": "object"},
                    "seed": {"type": "integer"},
                },
            },
        },
    },
}


@dataclass
class CampaignResult:
    name: str
    runs: list[dict]
    saltados: list[str]
    duracion: float
    costo_total: float
    q_medio: float
    tasa_aprobados: float

    def resumen_ejecutivo(self) -> str:
        return (
            f"Campana '{self.name}': {len(self.runs)} corridas, {len(self.saltados)} saltadas por presupuesto, "
            f"q_medio={self.q_medio:.3f}, tasa_aprobados={self.tasa_aprobados:.1%}, "
            f"costo_total={self.costo_total:.2f}, duracion={self.duracion:.1f}s"
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "n_runs": len(self.runs),
            "saltados": self.saltados,
            "duracion": round(self.duracion, 3),
            "costo_total": round(self.costo_total, 4),
            "q_medio": round(self.q_medio, 4),
            "tasa_aprobados": round(self.tasa_aprobados, 4),
            "runs": self.runs,
            "resumen": self.resumen_ejecutivo(),
        }


class Campaign:
    def __init__(self, name: str, objetivos: list[dict], *, budget_total: float = 10_000, beta: float = 0.5, k: int = 2, m: int = 3, seed: int = 0):
        self.name = name
        self.objetivos = objetivos
        self.budget_total = budget_total
        self.beta = beta
        self.k = k
        self.m = m
        self.seed = seed

    @staticmethod
    def from_dict(data: dict) -> "Campaign":
        # validar con el esquema local (sin registrarlo global para no ensuciar)
        from .schemas import validate_schema

        validate_schema(data, CAMPAIGN_SCHEMA, path="campaign.$")
        return Campaign(
            data["name"],
            data["objetivos"],
            budget_total=float(data.get("budget_total", 10_000)),
            beta=float(data.get("beta", 0.5)),
            k=int(data.get("k", 2)),
            m=int(data.get("m", 3)),
            seed=int(data.get("seed", 0)),
        )

    @staticmethod
    def load(path: str | Path) -> "Campaign":
        return Campaign.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))



def run_campaign_ab(
    campaign: Campaign,
    *,
    runner_a: CoworkRunner,
    runner_b: CoworkRunner,
    trace_dir: str | Path = "traces",
) -> dict:
    """Compara dos runners (A/B) sobre la misma campana y decide con Mann-Whitney.

    Devuelve metricas agregadas de cada lado + estadistica (delta q medio y
    p-valor one-sided de que B > A), usando quality.mann_whitney_adopt.
    """
    from .quality import mann_whitney_adopt, mann_whitney_u

    res_a = run_campaign(campaign, runner=runner_a, trace_dir=Path(trace_dir) / "ab-a")
    res_b = run_campaign(campaign, runner=runner_b, trace_dir=Path(trace_dir) / "ab-b")
    qs_a = [q for r in res_a.runs for q in r.get("qs", {}).values()]
    qs_b = [q for r in res_b.runs for q in r.get("qs", {}).values()]
    u, p = mann_whitney_u(qs_b, qs_a)  # estadistico de B vs A
    adopt = mann_whitney_adopt(qs_a, qs_b)  # ¿adoptar B sobre A? (one-sided cand > ref)
    return {
        "campana": campaign.name,
        "a": {"q_medio": round(res_a.q_medio, 4), "tasa_aprobados": round(res_a.tasa_aprobados, 4), "costo": round(res_a.costo_total, 2)},
        "b": {"q_medio": round(res_b.q_medio, 4), "tasa_aprobados": round(res_b.tasa_aprobados, 4), "costo": round(res_b.costo_total, 2)},
        "delta_q_medio": round(res_b.q_medio - res_a.q_medio, 4),
        "mann_whitney": {"U": round(u, 4), "p": round(p, 4), "adopt_b": bool(adopt)},
    }


def run_campaign(
    campaign: Campaign,
    *,
    runner: CoworkRunner | None = None,
    trace_dir: str | Path = "traces",
    backend_kind: str = "scripted",
    stop_on_first_failure: bool = False,
    early_stop_q: float | None = None,
) -> CampaignResult:
    """Ejecuta los objetivos de la campana bajo el presupuesto global."""
    inicio = time.time()
    if runner is None:
        runner = build_runner(trace_dir, backend_kind=backend_kind)
    budget = Budget(total=campaign.budget_total, beta=campaign.beta, k=campaign.k, m=campaign.m)
    runner.budget = budget
    runs: list[dict] = []
    saltados: list[str] = []
    qs: list[float] = []
    aprobados = 0
    for i, obj in enumerate(campaign.objetivos):
        objetivo = obj["objetivo"]
        # tope duro: si ya no cabe ni una corrida de adaptacion minima, saltar
        if budget.spent_adapt >= budget.beta * budget.total:
            saltados.append(objetivo)
            continue
        try:
            res: RunResult = runner.run(objetivo, inputs=obj.get("inputs") or {}, seed=int(obj.get("seed", campaign.seed + i)))
        except Exception as e:  # noqa: BLE001 - una corrida mala no tumba la campana
            runs.append({"objetivo": objetivo, "error": f"{type(e).__name__}: {e}"})
            if stop_on_first_failure:
                break
            continue
        data = res.to_dict()
        runs.append({"objetivo": objetivo, "run_id": data["run_id"], "qs": data["qs"], "metrics": data["metrics"]})
        if data["qs"]:
            qs.append(sum(data["qs"].values()) / len(data["qs"]))
        if all(v.get("status") == "done" for v in data["dag_results"].values()):
            aprobados += 1
        if early_stop_q is not None and qs and (sum(qs) / len(qs)) >= early_stop_q:
            break  # early stop: la campana ya llego al umbral de calidad
        # descontar el costo de adaptacion de esta corrida del presupuesto global
        budget.spent_adapt += res.costo_adaptacion
    duracion = time.time() - inicio
    return CampaignResult(
        name=campaign.name,
        runs=runs,
        saltados=saltados,
        duracion=duracion,
        costo_total=budget.spent_adapt,
        q_medio=(sum(qs) / len(qs)) if qs else 0.0,
        tasa_aprobados=(aprobados / len(campaign.objetivos)) if campaign.objetivos else 0.0,
    )
