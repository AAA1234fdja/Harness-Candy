"""Capa de calidad transversal (seccion 5 y 9 del diseno combinado).

Da a Harness^2 la senal de evaluacion que le falta y evita que el sistema
se califique a si mismo:

* criterios de aceptacion medibles (ISA los fija, WEV los aplica),
* score Q(a) (ecuacion 1),
* decision estadistica candidato vs. referencia (ecuacion 2),
* trazabilidad JSONL (run_id, modelo, semilla, version del harness),
* regresion / deteccion de deriva (ELY).

Nota: la ecuacion (2) del PDF imprime el denominador como ``m``; aqui se
implementa la forma estadistica estandar del error estandar de la
diferencia de medias, ``sqrt(m)`` (ver docs/DISENO_COMBINADO.md).
"""
from __future__ import annotations

import json
import math
import statistics
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .protocols import Hallazgo


# ---------------------------------------------------------------------------
# Criterios de aceptacion medibles (ISA -> WEV)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Criterion:
    """Criterio de aceptacion medible: id + peso w_i (ecuacion 1)."""

    id: str
    descripcion: str = ""
    peso: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Ecuacion (1): Q(a) = max(0, sum(w_i c_i)/sum(w_i) - sum_j rho_sj) en [0, 1]
# ---------------------------------------------------------------------------

def score_q(
    criterios: Sequence[Criterion],
    cumplidos: Iterable[str],
    hallazgos: Sequence[Hallazgo] = (),
) -> float:
    """Puntuacion de calidad de un artefacto ``a`` segun la ecuacion (1).

    ``c_i`` vale 1 si el criterio ``i`` se cumple. ``rho_sj`` penaliza cada
    hallazgo ``j`` segun su severidad. El resultado se acota a [0, 1].
    """
    cumplidos = set(cumplidos)
    total_w = sum(c.peso for c in criterios)
    if total_w <= 0:
        ratio = 0.0
    else:
        ratio = sum(c.peso for c in criterios if c.id in cumplidos) / total_w
    penalizacion = sum(h.penalty() for h in hallazgos)
    q = ratio - penalizacion
    return max(0.0, min(1.0, q))


# ---------------------------------------------------------------------------
# Ecuacion (2): decision estadistica candidato vs. referencia
# ---------------------------------------------------------------------------

def compose_delta(scores_ref: Sequence[float], scores_cand: Sequence[float], alpha: float = 0.05) -> float:
    """Umbral delta de la ecuacion (2).

    delta = z_{1-alpha} * sqrt(s0^2 + s'^2) / sqrt(m)

    con m corridas por configuracion y varianzas muestrales s0^2, s'^2.
    (El PDF imprime ``/m``; se usa la forma estandar ``/sqrt(m)`` del error
    estandar de la diferencia de medias.)
    """
    m = len(scores_ref)
    if m == 0 or len(scores_cand) != m:
        raise ValueError("se requieren m corridas por configuracion (m >= 1)")
    s0 = statistics.variance(scores_ref) if m > 1 else 0.0
    s1 = statistics.variance(scores_cand) if m > 1 else 0.0
    z = statistics.NormalDist().inv_cdf(1.0 - alpha)
    return z * math.sqrt(s0 + s1) / math.sqrt(m)


def should_adopt(
    scores_ref: Sequence[float],
    scores_cand: Sequence[float],
    alpha: float = 0.05,
) -> bool:
    """Compose adopta h' solo si la mejora supera el ruido (ec. 2).

    ``mean(Q(h')) - mean(Q(h0)) > delta``; si no se cumple, se conserva h0.
    """
    m = len(scores_ref)
    if m == 0 or len(scores_cand) != m:
        raise ValueError("misma cantidad de corridas en referencia y candidato")
    delta = compose_delta(scores_ref, scores_cand, alpha)
    return (statistics.fmean(scores_cand) - statistics.fmean(scores_ref)) > delta


# ---------------------------------------------------------------------------
# Trazabilidad: registro JSONL reproducible (run_id, modelo, semilla, harness)
# ---------------------------------------------------------------------------

class TraceLog:
    """Registro de cada corrida en formato JSONL para auditar y reproducir."""

    REQUIRED_FIELDS = ("run_id", "task_id", "model", "seed", "harness", "phase", "q")

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        run_id: str,
        task_id: str,
        model: str,
        seed: int,
        harness: str,
        phase: str,
        q: float,
        verdict: str = "",
        extra: dict[str, Any] | None = None,
        ts: float | None = None,
    ) -> dict:
        entry = {
            "ts": ts if ts is not None else time.time(),
            "run_id": run_id,
            "task_id": task_id,
            "model": model,
            "seed": seed,
            "harness": harness,
            "phase": phase,
            "q": round(float(q), 6),
            "verdict": verdict,
        }
        if extra:
            entry["extra"] = extra
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return entry

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out


def new_run_id() -> str:
    return "run-" + uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Regresion y deteccion de deriva (ELY)
# ---------------------------------------------------------------------------

@dataclass
class RegressionAlert:
    task_id: str
    baseline_q: float
    q_actual: float
    caida_pp: float  # en puntos porcentuales
    mensaje: str


class RegressionGuard:
    """Conjunto de tareas de referencia de ELY.

    * Alerta si la metrica cae mas de ``drop_pp`` puntos porcentuales.
    * Considera exito si q >= referencia - ``success_band`` (banda del 3%).
    """

    def __init__(self, drop_pp: float = 2.0, success_band: float = 0.03):
        self.drop_pp = drop_pp
        self.success_band = success_band
        self.baseline: dict[str, float] = {}

    def set_baseline(self, task_id: str, q: float) -> None:
        self.baseline[task_id] = float(q)

    def update_baseline(self, task_id: str, q: float) -> None:
        """Actualiza la referencia solo si no empeora (anti-deriva)."""
        if task_id not in self.baseline or q >= self.baseline[task_id]:
            self.baseline[task_id] = float(q)

    def check(self, task_id: str, q: float) -> RegressionAlert | None:
        if task_id not in self.baseline:
            return None
        base = self.baseline[task_id]
        caida_pp = (base - q) * 100.0
        if caida_pp > self.drop_pp:
            return RegressionAlert(
                task_id=task_id,
                baseline_q=base,
                q_actual=float(q),
                caida_pp=caida_pp,
                mensaje=(
                    f"deriva detectada en {task_id}: Q bajo de {base:.3f} a {q:.3f} "
                    f"(-{caida_pp:.1f} pp > {self.drop_pp} pp)"
                ),
            )
        return None

    def is_success(self, task_id: str, q: float) -> bool:
        if task_id not in self.baseline:
            return True
        return q >= self.baseline[task_id] - self.success_band

    def to_dict(self) -> dict:
        return {"drop_pp": self.drop_pp, "success_band": self.success_band, "baseline": dict(self.baseline)}
