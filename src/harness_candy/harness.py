"""Harness y Adaptador Harness^2 (Propose -> Probe -> Compose).

Implementa las secciones 2.2, 5 y 12 (paso 3) del diseno combinado:

* ``Harness``: los ocho componentes editables de Harness^2 (system prompt,
  guardrails, memoria, guia de herramientas, subagentes, skills, scripts,
  plugins). Los pesos del modelo quedan fijos.
* ``HarnessStore``: biblioteca de harness de mejora (lecciones respaldadas
  por evidencia) para reutilizar por (tipo de tarea, modelo).
* ``Budget``: presupuestos por tarea y costo de adaptation (ecuacion 3).
* ``Harness2Adapter``: sustituye la comparacion informal por una decision
  medible: ejecuta la referencia h0 y 2k candidatos m veces cada uno, puntua
  con WEV (Q, ec. 1) y solo adopta el candidato si supera el umbral
  estadistico delta (ec. 2).
"""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, Sequence

from .quality import TraceLog, should_adopt

HARNESS_COMPONENTS = (
    "system_prompt",
    "guardrails",
    "memory",
    "tool_guidance",
    "subagents",
    "skills",
    "scripts",
    "plugins",
)


@dataclass
class Harness:
    """Conjunto (harness) de un agente: los 8 componentes editables."""

    version: str = "0.1.0"
    system_prompt: str = ""
    guardrails: list[str] = field(default_factory=list)
    memory: dict = field(default_factory=dict)
    tool_guidance: str = ""
    subagents: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)

    def fingerprint(self) -> str:
        """Huella estable del harness (para trazabilidad y versionado)."""
        payload = json.dumps(
            {k: getattr(self, k) for k in HARNESS_COMPONENTS} | {"version": self.version},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def label(self) -> str:
        return f"{self.version}#{self.fingerprint()}"

    def evolve(self, **changes: Any) -> "Harness":
        """Devuelve una copia con los componentes indicados modificados.

        Para campos de lista, los valores nuevos se agregan (union) a los
        existentes: Compose "fusiona lo que funciono".
        """
        kwargs = {k: getattr(self, k) for k in HARNESS_COMPONENTS}
        kwargs["version"] = self.version
        for key, value in changes.items():
            if key not in kwargs:
                raise KeyError(f"componente de harness desconocido: {key!r}")
            current = kwargs[key]
            if isinstance(current, list) and isinstance(value, (list, tuple, set)):
                merged = list(current)
                for item in value:
                    if item not in merged:
                        merged.append(item)
                kwargs[key] = merged
            elif isinstance(current, dict) and isinstance(value, dict):
                merged = dict(current)
                merged.update(value)
                kwargs[key] = merged
            else:
                kwargs[key] = value
        new = Harness(**kwargs)
        return new


# ---------------------------------------------------------------------------
# Biblioteca de harness (reutilizacion por tipo de tarea + modelo)
# ---------------------------------------------------------------------------

@dataclass
class HarnessEntry:
    harness: Harness
    q_mean: float
    evidence: dict
    created_at: float = field(default_factory=time.time)
    hits: int = 0


class HarnessStore:
    """Almacen de harness validados, con evidencia, reutilizable.

    ``lookup(task.kind, model)`` devuelve None si no hay harness validado:
    en ese caso el adaptador sondea (Probe) antes de ejecutar.
    """

    def __init__(self, path: str | Path | None = None):
        self._entries: dict[tuple[str, str], HarnessEntry] = {}
        self._lookups = 0
        self.path = Path(path) if path else None

    def lookup(self, task_kind: str, model: str) -> Harness | None:
        self._lookups += 1
        entry = self._entries.get((task_kind, model))
        if entry is None:
            return None
        entry.hits += 1
        return entry.harness

    def save(self, task_kind: str, model: str, harness: Harness, *, evidence: dict, q_mean: float = 0.0) -> None:
        self._entries[(task_kind, model)] = HarnessEntry(harness, q_mean, evidence)
        self._persist()

    def reuse_rate(self) -> float:
        """Tasa r de reutilizacion (ecuacion 3)."""
        if self._lookups == 0:
            return 0.0
        hits = sum(e.hits for e in self._entries.values())
        return hits / self._lookups

    def _persist(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            f"{kind}|{model}": {
                "harness": {k: getattr(e.harness, k) for k in HARNESS_COMPONENTS} | {"version": e.harness.version},
                "q_mean": e.q_mean,
                "hits": e.hits,
                "created_at": e.created_at,
                "evidence_keys": sorted(e.evidence.keys()),
            }
            for (kind, model), e in self._entries.items()
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Presupuesto por tarea (ecuacion 3)
# ---------------------------------------------------------------------------

@dataclass
class Budget:
    """Presupuesto total B y limites para el sondeo del adaptador.

    Ecuacion (3):  C_adapt = (1 - r) * sum_a (1 + 2 k_a) * m * c_a <= beta * B
    con r la tasa de reutilizacion de harness ya validados, c_a el costo de
    una corrida del agente a, k las configuraciones exploradas y m las
    corridas por configuracion.
    """

    total: float  # B: presupuesto total (unidades de costo)
    beta: float = 0.25  # fraccion aceptada para adaptar
    k: int = 2  # --k N: N generales + N de dominio ademas de la referencia
    m: int = 3  # m >= 3 corridas por configuracion
    spent_adapt: float = 0.0

    def probe_cost(self, c_a: float = 1.0) -> float:
        """Costo de sondear un agente: referencia + 2k candidatos, m veces."""
        return (1 + 2 * self.k) * self.m * c_a

    def allows_probe(self, c_a: float = 1.0) -> bool:
        return self.spent_adapt + self.probe_cost(c_a) <= self.beta * self.total

    def charge(self, c_a: float = 1.0) -> None:
        self.spent_adapt += self.probe_cost(c_a)

    def estimate_adapt_cost(self, n_agents: int, reuse_rate: float, c_a: float = 1.0) -> float:
        """Cota de la ecuacion (3) para n agentes con tasa de reutilizacion r."""
        return (1.0 - reuse_rate) * n_agents * self.probe_cost(c_a)

    def justifies_probe(self, expected_delta_q: float, value_per_q: float, c_a: float = 1.0) -> bool:
        """Heuristica: sondear solo si E[dQ] * V_a > 2 k m c_a."""
        return expected_delta_q * value_per_q > 2 * self.k * self.m * c_a


# ---------------------------------------------------------------------------
# Adaptador Harness^2: Propose -> Probe -> Compose
# ---------------------------------------------------------------------------

class Proposer(Protocol):
    """Un editor propone cambios: k generales (invariantes) + k de dominio."""

    def __call__(self, h0: Harness, task_kind: str, k: int) -> list[Harness]: ...


class RuleBasedProposer:
    """Proposiciones deterministas por defecto (sirve sin LLM externo).

    Las mutaciones generales aplican a cualquier tarea; las de dominio son
    especificas del ``task.kind``. Con un LLM real se sustituye por un
    proposer que edite el harness via prompt (ver docs).
    """

    GENERAL_MUTATIONS: list[dict] = [
        {"guardrails": ["json_strict"], "skills": ["recomendaciones"]},
        {"guardrails": ["json_strict"]},
        {"system_prompt": "Se riguroso, estructurado y conciso. Cita evidencia."},
        {"skills": ["recomendaciones"]},
        {"tool_guidance": "Usa solo herramientas aprobadas y con entradas validadas."},
        {"guardrails": ["sin_salida_plana"]},
        {"scripts": ["lint_basico"]},
    ]

    DOMAIN_MUTATIONS: dict[str, list[dict]] = {
        "security_scan": [
            {"skills": ["secrets_v2"]},
            {"guardrails": ["bloquear_secretos_en_salida"]},
            {"skills": ["recomendaciones"]},
            {"scripts": ["scan_secretos", "py_compile"]},
        ],
        "write_report": [
            {"guardrails": ["json_strict"]},
            {"skills": ["estructura_ejecutiva"]},
        ],
    }

    def __call__(self, h0: Harness, task_kind: str, k: int) -> list[Harness]:
        general = self.GENERAL_MUTATIONS[:k]
        # --k N explora N generales + N de dominio; si el kind no tiene
        # mutaciones de dominio definidas, se rotan las generales con offset
        # para que los 2k candidatos sean siempre distintos.
        if task_kind in self.DOMAIN_MUTATIONS:
            domain = self.DOMAIN_MUTATIONS[task_kind][:k]
        else:
            n = len(self.GENERAL_MUTATIONS)
            domain = [self.GENERAL_MUTATIONS[(k + i) % n] for i in range(k)]
        candidates = []
        for mutation in general + domain:
            base_prompt = h0.system_prompt
            cand = h0.evolve(**mutation)
            if "system_prompt" in mutation and base_prompt:
                cand = replace(cand, system_prompt=base_prompt + "\n" + mutation["system_prompt"])
            candidates.append(cand)
        return candidates


# Funcion de score inyectada: WEV (ecuacion 1). Firma: (artifact, criterios) -> float
ScoreFn = Callable[[Any, Sequence], float]


@dataclass
@dataclass
class AdaptationEvidence:
    """Evidencia respaldada de la adaptacion (para la biblioteca de harness)."""

    reference_scores: list[float]
    candidate_scores: dict[str, list[float]]
    adopted: str  # "candidato" | "compuesto" | "referencia"
    adopted_harness: str
    delta: float
    k: int
    m: int
    cost: float
    trajectories: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "reference_scores": self.reference_scores,
            "candidate_scores": self.candidate_scores,
            "adopted": self.adopted,
            "adopted_harness": self.adopted_harness,
            "delta": self.delta,
            "k": self.k,
            "m": self.m,
            "cost": self.cost,
            "trajectories": self.trajectories,
        }


def merge_harnesses(h0: Harness, winners: list[Harness]) -> Harness:
    """Compose: fusiona lo que funciono (union de listas/dicts; el prompt del
    primer ganador prevalece). Descarta lo que choca."""
    if not winners:
        return h0
    merged = h0
    for w in winners:
        merged = merged.evolve(
            guardrails=list(w.guardrails),
            skills=list(w.skills),
            scripts=list(w.scripts),
            plugins=list(w.plugins),
            subagents=list(w.subagents),
            memory=dict(w.memory),
        )
    merged = replace(merged, system_prompt=winners[0].system_prompt or h0.system_prompt,
                     tool_guidance=winners[0].tool_guidance or h0.tool_guidance)
    return merged


class Harness2Adapter:
    """Ciclo Propose -> Probe -> Compose sobre un agente, sin tocar los pesos.

    Nivel 1 (tarea): un cambio se juzga por sus consecuencias en el
    comportamiento. Nivel 2 (harnessing): al terminar se guarda el harness
    adoptado y las lecciones respaldadas por evidencia (via HarnessStore).
    """

    def __init__(
        self,
        proposer: Optional[Proposer] = None,
        alpha: float = 0.05,
        tracer: TraceLog | None = None,
        run_id: str = "",
    ):
        self.proposer = proposer or RuleBasedProposer()
        self.alpha = alpha
        self.tracer = tracer
        self.run_id = run_id

    def _probe(
        self,
        agent,
        task,
        harness: Harness,
        m: int,
        score_fn: ScoreFn,
        phase: str,
        base_seed: int,
    ) -> tuple[list[float], list[str]]:
        """Ejecuta m corridas y guarda la trayectoria de cada una."""
        scores: list[float] = []
        trajectories: list[str] = []
        for i in range(m):
            seed = base_seed + i
            artifact = agent.run(task, harness=harness, seed=seed)
            q = float(score_fn(artifact, task.criterios))
            scores.append(q)
            trajectories.append(
                f"seed={seed} q={q:.3f} harness={harness.label()} "
                f"artifact={str(artifact.content)[:200]}"
            )
            if self.tracer is not None:
                self.tracer.record(
                    run_id=self.run_id,
                    task_id=task.task_id,
                    model=agent.model,
                    seed=seed,
                    harness=harness.label(),
                    phase=phase,
                    q=q,
                    extra={"artifact": str(artifact.content)[:200]},
                )
        return scores, trajectories

    def adapt(
        self,
        agent,
        task,
        *,
        k: int,
        m: int,
        score_fn: ScoreFn,
        base_seed: int = 0,
        h0: Harness | None = None,
    ) -> tuple[Harness, AdaptationEvidence]:
        """Ejecuta Propose -> Probe -> Compose y devuelve (harness, evidencia).

        Compose: adopta el mejor candidato si supera delta (ec. 2); si no,
        pero al menos dos candidatos mejoraron individualmente, fusiona los
        ganadores (union de sus componentes); si no, conserva h0.
        """
        h0 = h0 or agent.default_harness
        ref_scores, ref_traj = self._probe(agent, task, h0, m, score_fn, "reference", base_seed)

        candidates = self.proposer(h0, task.kind, k)
        best: Harness | None = None
        best_scores: list[float] = []
        cand_scores: dict[str, list[float]] = {}
        trajectories: dict[str, list[str]] = {"reference": ref_traj}
        scored: list[tuple[Harness, list[float]]] = []
        for cand in candidates:
            s, traj = self._probe(agent, task, cand, m, score_fn, "probe", base_seed)
            cand_scores[cand.label()] = s
            trajectories[cand.label()] = traj
            scored.append((cand, s))
            if best is None or statistics.fmean(s) > statistics.fmean(best_scores):
                best, best_scores = cand, s

        cost = (1 + 2 * k) * m  # en unidades de corrida c_a = 1
        winners = [c for c, s in scored if should_adopt(ref_scores, s, self.alpha)]
        if len(winners) >= 2:
            # Compose fusiona lo que funciono (>=2 candidatos superaron a h0
            # por encima del ruido) y descarta lo que choca.
            adopted = merge_harnesses(h0, winners)
            adopted_kind = "compuesto"
        elif len(winners) == 1:
            adopted = winners[0]
            adopted_kind = "candidato"
        else:
            adopted = h0
            adopted_kind = "referencia"
        from .quality import compose_delta

        evidence = AdaptationEvidence(
            reference_scores=ref_scores,
            candidate_scores=cand_scores,
            adopted=adopted_kind,
            adopted_harness=adopted.label(),
            delta=compose_delta(ref_scores, best_scores, self.alpha) if best_scores else 0.0,
            k=k,
            m=m,
            cost=cost,
            trajectories=trajectories,
        )
        return adopted, evidence


def harness2_adapter(
    agent,
    task,
    *,
    k: int,
    m: int,
    score: ScoreFn,
    rule: Callable = should_adopt,
    proposer: Optional[Proposer] = None,
    tracer: TraceLog | None = None,
    run_id: str = "",
    base_seed: int = 0,
) -> tuple[Harness, AdaptationEvidence]:
    """Atajo equivalente al pseudocodigo del Listado 1 del diseno combinado."""
    adapter = Harness2Adapter(proposer=proposer, tracer=tracer, run_id=run_id)
    return adapter.adapt(agent, task, k=k, m=m, score_fn=score, base_seed=base_seed)
