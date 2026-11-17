"""Datasets de evaluacion en JSONL y comparacion A/B (checklist v3 §5.9, §21).

Un dataset es un archivo JSONL, un golden case por linea (mismo formato que
``golden_set.cases``). Permite evaluar en lote y comparar dos corridas (A/B)
sobre el mismo dataset: ``compare_reports`` da el delta de pass_rate y los
casos que cambiaron de estado.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .evalkit import CaseResult, EvalReport, GoldenCase, GoldenSet, run_golden
from .schemas import validate_named


def load_dataset(path: str | Path, *, name: str = "") -> GoldenSet:
    """Carga un JSONL de casos (cada linea: {"id","task","expect"})."""
    p = Path(path)
    cases: list[GoldenCase] = []
    for i, linea in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        linea = linea.strip()
        if not linea:
            continue
        d = json.loads(linea)
        d.setdefault("id", f"caso-{i}")
        # cada caso se valida contra el esquema de golden_set (un caso)
        validate_named("golden_set", {"name": name or p.stem, "cases": [d]})
        cases.append(GoldenCase.from_dict(d))
    if not cases:
        raise ValueError(f"dataset vacio: {path}")
    return GoldenSet(name=name or p.stem, cases=cases, min_pass_rate=0.0)


def run_dataset(path: str | Path, **kwargs: Any) -> EvalReport:
    """Ejecuta un dataset JSONL completo (delega en run_golden)."""
    return run_golden(load_dataset(path), **kwargs)


@dataclass
class Comparison:
    """Resultado de comparar dos reportes A/B sobre el mismo dataset."""

    a: str
    b: str
    pass_rate_a: float
    pass_rate_b: float
    delta_pp: float  # en puntos porcentuales
    solo_en_a: list[str]  # casos que pasan en A y no en B
    solo_en_b: list[str]  # casos que pasan en B y no en A
    iguales: int

    def to_dict(self) -> dict:
        return {
            "a": self.a,
            "b": self.b,
            "pass_rate_a": round(self.pass_rate_a, 4),
            "pass_rate_b": round(self.pass_rate_b, 4),
            "delta_pp": round(self.delta_pp, 2),
            "solo_en_a": self.solo_en_a,
            "solo_en_b": self.solo_en_b,
            "iguales": self.iguales,
            "b_mejor": self.delta_pp > 0,
        }


def compare_reports(a: EvalReport, b: EvalReport) -> Comparison:
    """Compara dos reportes (mismos casos, distintos harness/config)."""
    pa = {r.case_id: r.passed for r in a.results}
    pb = {r.case_id: r.passed for r in b.results}
    ids = sorted(set(pa) | set(pb))
    solo_a = [i for i in ids if pa.get(i) and not pb.get(i)]
    solo_b = [i for i in ids if pb.get(i) and not pa.get(i)]
    iguales = sum(1 for i in ids if pa.get(i) == pb.get(i) and i in pa and i in pb)
    return Comparison(
        a=a.golden,
        b=b.golden,
        pass_rate_a=a.pass_rate,
        pass_rate_b=b.pass_rate,
        delta_pp=(b.pass_rate - a.pass_rate) * 100.0,
        solo_en_a=solo_a,
        solo_en_b=solo_b,
        iguales=iguales,
    )
