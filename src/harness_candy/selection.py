"""Seleccion estadistica del harness adoptado (paper §3 Compose, ec. (2)).

Dado un conjunto de candidatos con sus scores (m corridas cada uno) y la
referencia, elige el adoptado:
  1. calcula delta = media(cand) - media(ref) y el test de Mann-Whitney
     one-sided (cand > ref);
  2. adopta el candidato con mayor delta significativa (p < alpha); si ninguno
     es significativo, se queda la referencia;
  3. reporta intervalo bootstrap (IC 95%) del q medio del ganador.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .quality import compose_delta, mann_whitney_u
from .stats import bootstrap_ci, mean


@dataclass
class CandidateScore:
    label: str
    scores: list[float]

    @property
    def media(self) -> float:
        return mean(self.scores) if self.scores else 0.0


@dataclass
class SelectionResult:
    label_ganador: str
    es_referencia: bool
    delta: float
    p_value: float
    ic95: tuple[float, float]
    n_ref: int
    n_cand: int
    detalle: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "label_ganador": self.label_ganador,
            "es_referencia": self.es_referencia,
            "delta": round(self.delta, 6),
            "p_value": round(self.p_value, 6),
            "ic95": [round(self.ic95[0], 6), round(self.ic95[1], 6)],
            "n_ref": self.n_ref,
            "n_cand": self.n_cand,
            "detalle": self.detalle,
        }


def seleccionar_adoptado(
    referencia: Sequence[float],
    candidatos: Sequence[CandidateScore],
    *,
    alpha: float = 0.05,
    n_boot: int = 2000,
    seed: int = 0,
) -> SelectionResult:
    """Elige el harness adoptado entre referencia y candidatos (estadistica)."""
    ref = list(referencia)
    if not ref:
        raise ValueError("la referencia necesita al menos una corrida")
    ref_media = mean(ref)
    detalle: list[dict] = []
    mejor: CandidateScore | None = None
    mejor_delta = 0.0
    mejor_p = 1.0
    for cand in candidatos:
        if not cand.scores:
            continue
        delta = compose_delta(ref, cand.scores, alpha=alpha)
        u, p_two = mann_whitney_u(cand.scores, ref)
        # one-sided: P(cand > ref) ~= 1 - p_two/2 cuando U favorece a cand
        p_one = min(1.0, p_two / 2.0) if u > (len(cand.scores) * len(ref)) / 2 else min(1.0, 1.0 - p_two / 2.0)
        detalle.append({"label": cand.label, "media": round(cand.media, 6), "delta": round(delta, 6), "p_one_sided": round(p_one, 6)})
        if p_one < alpha and cand.media - ref_media > mejor_delta:
            mejor = cand
            mejor_delta = cand.media - ref_media
            mejor_p = p_one
    if mejor is None:
        ic = bootstrap_ci(ref, mean, n_boot=n_boot, alpha=0.05, seed=seed)
        return SelectionResult(
            label_ganador="reference", es_referencia=True, delta=0.0, p_value=1.0,
            ic95=(ic[0], ic[2]), n_ref=len(ref), n_cand=sum(len(c.scores) for c in candidatos), detalle=detalle,
        )
    ic = bootstrap_ci(mejor.scores, mean, n_boot=n_boot, alpha=0.05, seed=seed)
    return SelectionResult(
        label_ganador=mejor.label, es_referencia=False, delta=mejor_delta, p_value=mejor_p,
        ic95=(ic[0], ic[2]), n_ref=len(ref), n_cand=sum(len(c.scores) for c in candidatos), detalle=detalle,
    )
