"""Juez LLM calibrado para comparacion (capitulo 16 del documento exhaustivo).

Modos de evaluacion del juez (estandar 2025-2026):
- ``pairwise``: A vs B con orden aleatorio por sesgo de posicion (reusa
  swap_test de judge.py para la medicion de sesgo).
- ``single``: puntua un artefacto en escala 0..5 contra criterios.
- ``reference_guided``: puntua comparando contra una respuesta de referencia.

Calibracion contra anotaciones humanas: MAE, sesgo medio, MAE por dominio y
correlacion (Pearson de stats.py). Consenso multi-juez: k jueces votan, mayoria
+ entropia normalizada como medida de acuerdo (cuanto mas cerca de 0, mas
consenso; MT-Bench/Arena usan varianza entre jueces como proxy de calidad).

Todo stdlib; el backend es inyectable (ScriptedBackend en tests).
"""
from __future__ import annotations

import json
import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from .agents import Artifact, LLMBackend
from .judge import LLMJudge, swap_test
from .llm import structured_output
from .stats import pearson

ESCALA = 5  # 0..5 como MT-Bench / JudgeLM


@dataclass
class JudgeVote:
    juez: str
    score: float  # 0..5
    raw: str = ""

    def to_dict(self) -> dict:
        return {"juez": self.juez, "score": round(self.score, 4), "raw": self.raw[:200]}


@dataclass
class PairwiseResult:
    ganador: str  # "A" | "B" | "empate"
    score_a: float
    score_b: float
    sesgo_posicion: float  # 1.0 = consistente en ambos ordenes
    detalle: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"ganador": self.ganador, "score_A": round(self.score_a, 4), "score_B": round(self.score_b, 4),
                "sesgo_posicion": self.sesgo_posicion, "detalle": self.detalle}


class CalibratedJudge:
    """Juez con los tres modos y salida estructurada validada (fail-closed a 0)."""

    def __init__(self, backend: LLMBackend, *, model: str = "", nombre: str = "juez", max_retries: int = 2):
        self.backend = backend
        self.model = model
        self.nombre = nombre
        self.max_retries = max_retries
        self._llm = LLMJudge(backend, model or "default")

    def _pedir(self, prompt: str, schema: dict, *, seed: int = 0) -> dict:
        try:
            data, _ = structured_output(self.backend, prompt, schema, model=self.model, max_retries=self.max_retries, schema_name=self.nombre)
            return data
        except Exception:
            return {"score": 0.0, "razon": "salida no parseable (fail-closed)"}

    # ------------------------------------------------------------- single
    def single(self, instruccion: str, artifact: Artifact, criterios: Sequence, *, dominio: str = "general") -> JudgeVote:
        crit = "\n".join(f"- {c.id}: {c.descripcion}" for c in criterios) or "- calidad general"
        prompt = (
            f"TAREA: {instruccion}\nCRITERIOS:\n{crit}\nARTEFACTO:\n{artifact.to_text()[:4000]}\n\n"
            f"Puntua 0..{ESCALA} (0 pesimo, {ESCALA} excelente). Devuelve SOLO JSON: "
            '{"score": 0..5, "razon": "..."}'
        )
        schema = {"type": "object", "required": ["score"], "additionalProperties": False,
                  "properties": {"score": {"type": "number", "minimum": 0, "maximum": ESCALA}, "razon": {"type": "string"}}}
        data = self._pedir(prompt, schema)
        score = max(0.0, min(float(ESCALA), float(data.get("score", 0.0))))
        return JudgeVote(self.nombre, score, json.dumps(data, ensure_ascii=False))

    # ----------------------------------------------------------- pairwise
    def pairwise(self, instruccion: str, a: Artifact, b: Artifact, criterios: Sequence, *, seed: int = 0) -> PairwiseResult:
        """A vs B: puntua ambos; el orden de presentacion se invierte con el seed
        para medir sesgo de posicion (usa swap_test)."""
        crit = "\n".join(f"- {c.id}: {c.descripcion}" for c in criterios) or "- calidad general"
        prompt = (
            f"TAREA: {instruccion}\nCRITERIOS:\n{crit}\nARTEFACTO A:\n{a.to_text()[:2000]}\n\n"
            f"ARTEFACTO B:\n{b.to_text()[:2000]}\n\n"
            f"Puntua cada uno 0..{ESCALA}. Devuelve SOLO JSON: "
            '{"score_A": 0..5, "score_B": 0..5, "razon": "..."}'
        )
        schema = {"type": "object", "required": ["score_A", "score_B"], "additionalProperties": False,
                  "properties": {"score_A": {"type": "number", "minimum": 0, "maximum": ESCALA},
                                 "score_B": {"type": "number", "minimum": 0, "maximum": ESCALA},
                                 "razon": {"type": "string"}}}
        data = self._pedir(prompt, schema, seed=seed)
        sa = max(0.0, min(float(ESCALA), float(data.get("score_A", 0.0))))
        sb = max(0.0, min(float(ESCALA), float(data.get("score_B", 0.0))))
        ganador = "A" if sa > sb + 1e-9 else ("B" if sb > sa + 1e-9 else "empate")
        sw = swap_test(self._llm, instruccion, a, b, criterios)
        return PairwiseResult(ganador=ganador, score_a=sa, score_b=sb,
                              sesgo_posicion=float(sw["tasa_acuerdo"]), detalle=sw)

    # --------------------------------------------------- reference-guided
    def reference_guided(self, instruccion: str, artifact: Artifact, referencia: str, criterios: Sequence) -> JudgeVote:
        crit = "\n".join(f"- {c.id}: {c.descripcion}" for c in criterios) or "- calidad general"
        prompt = (
            f"TAREA: {instruccion}\nCRITERIOS:\n{crit}\nRESPUESTA DE REFERENCIA (gold):\n{referencia[:2000]}\n\n"
            f"ARTEFACTO A EVALUAR:\n{artifact.to_text()[:2000]}\n\n"
            f"Puntua 0..{ESCALA} comparando contra la referencia (la referencia no es perfecta; puntua fidelidad al gold). "
            'Devuelve SOLO JSON: {"score": 0..5, "razon": "..."}'
        )
        schema = {"type": "object", "required": ["score"], "additionalProperties": False,
                  "properties": {"score": {"type": "number", "minimum": 0, "maximum": ESCALA}, "razon": {"type": "string"}}}
        data = self._pedir(prompt, schema)
        score = max(0.0, min(float(ESCALA), float(data.get("score", 0.0))))
        return JudgeVote(self.nombre, score, json.dumps(data, ensure_ascii=False))


# ------------------------------------------------------------- calibracion
@dataclass
class CalibrationReport:
    juez: str
    n: int
    mae: float
    sesgo_medio: float
    correlacion: float
    por_dominio: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "juez": self.juez, "n": self.n, "mae": round(self.mae, 4),
            "sesgo_medio": round(self.sesgo_medio, 4), "correlacion_pearson": round(self.correlacion, 4),
            "por_dominio": self.por_dominio,
        }


def calibrar_juez(
    judge: CalibratedJudge,
    samples: Sequence[tuple[str, Artifact, Sequence, float, str]],
) -> CalibrationReport:
    """MAE/sesgo/correlacion contra anotaciones humanas.

    ``samples``: (instruccion, artefacto, criterios, score_humano 0..5, dominio).
    """
    errores: list[float] = []
    sesgos: list[float] = []
    humanos: list[float] = []
    puntajes_juez: list[float] = []
    por_dominio: dict[str, list[tuple[float, float]]] = {}
    for instruccion, artifact, criterios, q_humano, dominio in samples:
        v = judge.single(instruccion, artifact, criterios, dominio=dominio)
        errores.append(abs(v.score - q_humano))
        sesgos.append(v.score - q_humano)
        humanos.append(q_humano)
        puntajes_juez.append(v.score)
        por_dominio.setdefault(dominio, []).append((q_humano, v.score))
    if not errores:
        return CalibrationReport(judge.nombre, 0, 0.0, 0.0, 0.0)
    dom: dict[str, dict] = {}
    for d, pares in por_dominio.items():
        mae_d = statistics.fmean(abs(a - b) for a, b in pares)
        dom[d] = {"n": len(pares), "mae": round(mae_d, 4)}
    return CalibrationReport(
        juez=judge.nombre,
        n=len(errores),
        mae=statistics.fmean(errores),
        sesgo_medio=statistics.fmean(sesgos),
        correlacion=pearson(humanos, puntajes_juez) if len(humanos) > 1 and len(set(humanos)) > 1 else 0.0,
        por_dominio=dom,
    )


# ------------------------------------------------------------- consenso
def consenso(votos: Sequence[JudgeVote], *, pesos: Optional[Sequence[float]] = None) -> dict:
    """Consenso entre k jueces: media ponderada + entropia normalizada.

    acuerdo = 1 - H/Hmax (1.0 = todos votaron igual; 0 = maxima dispersion).
    """
    if not votos:
        return {"media": 0.0, "moda": None, "n": 0, "desviacion": 0.0, "acuerdo": 0.0, "votos": []}
    scores = [v.score for v in votos]
    w = list(pesos) if pesos and len(pesos) == len(scores) else [1.0] * len(scores)
    media = sum(s * wi for s, wi in zip(scores, w)) / sum(w)
    desv = statistics.stdev(scores) if len(scores) > 1 else 0.0
    # entropia sobre bins de 1 punto en 0..5
    bins = [0] * (ESCALA + 1)
    for s in scores:
        bins[min(ESCALA, int(round(s)))] += 1
    n = len(scores)
    h = -sum((c / n) * math.log(c / n) for c in bins if c > 0)
    hmax = math.log(ESCALA + 1)
    acuerdo = 1.0 - (h / hmax) if hmax > 0 else 1.0
    moda = max(set(scores), key=scores.count)
    return {
        "media": round(media, 4), "moda": moda, "n": n,
        "desviacion": round(desv, 4), "acuerdo": round(acuerdo, 4),
        "votos": [v.to_dict() for v in votos],
    }


def consenso_pares(
    jueces: Sequence[CalibratedJudge],
    instruccion: str,
    a: Artifact,
    b: Artifact,
    criterios: Sequence,
) -> dict:
    """Votacion pairwise entre varios jueces: gana el que recibe mas votos."""
    if not jueces:
        raise ValueError("se necesita al menos un juez")
    votos_ab: list[str] = []
    for j in jueces:
        r = j.pairwise(instruccion, a, b, criterios)
        votos_ab.append(r.ganador)
    conteo = {"A": votos_ab.count("A"), "B": votos_ab.count("B"), "empate": votos_ab.count("empate")}
    ganador = max(conteo, key=lambda k: conteo[k]) if conteo else "empate"
    return {"ganador_consenso": ganador, "votos": votos_ab, "conteo": conteo,
            "acuerdo": round(max(conteo.values()) / len(votos_ab), 4) if votos_ab else 0.0}


def reporte_calibracion_md(report: CalibrationReport) -> str:
    """Reporte Markdown de calibracion del juez (MAE, sesgo, correlacion, dominios)."""
    lineas = [
        f"# Calibracion del juez: {report.juez}",
        "",
        f"- n muestras: {report.n}",
        f"- MAE: **{report.mae:.4f}** (0 = juez perfecto)",
        f"- sesgo medio: {report.sesgo_medio:+.4f} (>0 = el juez sobre-puntua)",
        f"- correlacion Pearson con humanos: {report.correlacion:.4f}",
        "",
        "| dominio | n | MAE |",
        "|---|---|---|",
    ]
    for d, info in sorted(report.por_dominio.items()):
        lineas.append(f"| {d} | {info['n']} | {info['mae']:.4f} |")
    return "\n".join(lineas) + "\n"


# ------------------------------------------------------------- Elo / leaderboard
@dataclass
class EloEntry:
    nombre: str
    rating: float = 1000.0
    wins: int = 0
    losses: int = 0
    draws: int = 0

    @property
    def winrate(self) -> float:
        n = self.wins + self.losses + self.draws
        return (self.wins + 0.5 * self.draws) / n if n else 0.0

    def to_dict(self) -> dict:
        return {"nombre": self.nombre, "elo": round(self.rating, 1), "w": self.wins, "l": self.losses, "d": self.draws, "winrate": round(self.winrate, 4)}


class TorneoElo:
    """Leaderboard Elo entre modelos/harnesses a partir de veredictos pairwise.

    K=32 estandar (Chatbot Arena usa K dinamico; aqui fijo). Cada partida es un
    ``consenso_pares``/``pairwise``: ganador suma, perdedor resta segun la
    probabilidad esperada E = 1/(1+10^((Rb-Ra)/400)).
    """

    def __init__(self, k: float = 32.0, inicial: float = 1000.0) -> None:
        self.k = k
        self.inicial = inicial
        self.entradas: dict[str, EloEntry] = {}

    def _entry(self, nombre: str) -> EloEntry:
        if nombre not in self.entradas:
            self.entradas[nombre] = EloEntry(nombre, self.inicial)
        return self.entradas[nombre]

    def partida(self, a: str, b: str, ganador: str) -> dict:
        """Registra una partida: ganador en {"A","B","empate"} (a=A, b=B)."""
        ea, eb = self._entry(a), self._entry(b)
        exp_a = 1.0 / (1.0 + 10 ** ((eb.rating - ea.rating) / 400.0))
        if ganador == "A":
            sa, sb = 1.0, 0.0
            ea.wins += 1; eb.losses += 1
        elif ganador == "B":
            sa, sb = 0.0, 1.0
            eb.wins += 1; ea.losses += 1
        else:
            sa = sb = 0.5
            ea.draws += 1; eb.draws += 1
        ea.rating += self.k * (sa - exp_a)
        eb.rating += self.k * (sb - (1.0 - exp_a))
        return {"A": a, "B": b, "ganador": ganador, "elo_A": round(ea.rating, 1), "elo_B": round(eb.rating, 1)}

    def tabla(self, top: int = 10) -> list[dict]:
        return [e.to_dict() for e in sorted(self.entradas.values(), key=lambda e: e.rating, reverse=True)[:top]]

    def to_dict(self) -> dict:
        return {"k": self.k, "inicial": self.inicial, "tabla": self.tabla(top=len(self.entradas))}
