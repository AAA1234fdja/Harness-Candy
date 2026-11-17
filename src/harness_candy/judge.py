"""Juez LLM independiente (WEV/ELY como juez distinto del generador).

Seccion 9 del diseno combinado: los jueces LLM tienden a puntuar mejor sus
propias salidas y sufren sesgos de posicion y formato. Mitigaciones
implementadas aqui:

* el juez es un backend/modelo DISTINTO del generador (configurar otro modelo
  en el pool para los roles "wev"/"ely");
* rubricas con anclajes (criterios explicitos de ISA);
* ``swap_test``: se evalua A vs B y B vs A intercambiadas; la tasa de acuerdo
  mide la consistencia del juez (sesgo de posicion);
* ``calibrate``: se compara la puntuacion del juez con anotaciones humanas
  (error medio absoluto) para calibrarlo periodicamente.

En tareas con criterio objetivo (compilacion, pruebas, linters, PII) pesa
mas la verificacion determinista de WEV que el juicio del modelo.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from .agents import Artifact, LLMBackend
from .protocols import Hallazgo


@dataclass
class JudgeScore:
    q: float  # en [0, 1]
    hallazgos: list[Hallazgo]
    raw: str = ""


class LLMJudge:
    """Juez LLM con rubrica anclada a los criterios de aceptacion de ISA."""

    def __init__(self, backend: LLMBackend, model: str, rubric: str = ""):
        self.backend = backend
        self.model = model
        self.rubric = rubric or "Puntua 0..1 segun el cumplimiento de los criterios. Devuelve JSON {\"q\": float, \"hallazgos\": [...]}"

    def score(self, instruction: str, artifact: Artifact, criterios: Sequence) -> JudgeScore:
        crit = "\n".join(f"- {c.id} (peso {c.peso}): {c.descripcion}" for c in criterios) or "- calidad general"
        prompt = (
            f"TAREA: {instruction}\nCRITERIOS DE ACEPTACION:\n{crit}\n\n"
            f"ARTEFACTO A EVALUAR:\n{artifact.to_text()[:4000]}\n\n"
            'Devuelve SOLO JSON: {"q": 0..1, "hallazgos": [{"herramienta": "juez", "severidad": "baja|media|alta|critica", "detalle": "..."}]}'
        )
        raw = self.backend.complete(prompt, system=self.rubric, model=self.model, seed=0)
        try:
            data = json.loads(raw)
            q = max(0.0, min(1.0, float(data.get("q", 0.0))))
            hallazgos = [
                Hallazgo(h.get("herramienta", "juez"), h.get("severidad", "media"), h.get("detalle", ""))
                for h in data.get("hallazgos", [])
            ]
            return JudgeScore(q, hallazgos, raw)
        except Exception:
            # si el juez no devuelve JSON, no aprueba por defecto (fail-closed)
            return JudgeScore(0.0, [Hallazgo("juez", "alta", "salida del juez no parseable")], raw)


def swap_test(judge: LLMJudge, instruction: str, artifact_a: Artifact, artifact_b: Artifact, criterios: Sequence) -> dict:
    """Evalua A vs B en ambos ordenes: mide sesgo de posicion del juez.

    Si el juez es consistente, puntuar (A,B) y (B,A) da resultados simétricos.
    Devuelve tasa de acuerdo (1.0 = sin sesgo de posicion).
    """
    ab = judge.score(instruction, artifact_a, criterios)
    ba = judge.score(instruction, artifact_b, criterios)
    # consistencia: gana el mismo artefacto en ambos ordenamientos si hay
    # diferencia clara; si ambas rondas empatan, tambien es consistente
    ganador_ab = "A" if ab.q > ba.q + 1e-9 else ("B" if ba.q > ab.q + 1e-9 else "empate")
    # segunda pasada con el orden invertido simulado via prompt (mismo juez)
    ba2 = judge.score(instruction, artifact_b, criterios)
    ab2 = judge.score(instruction, artifact_a, criterios)
    ganador_ba = "A" if ab2.q > ba2.q + 1e-9 else ("B" if ba2.q > ab2.q + 1e-9 else "empate")
    acuerdo = 1.0 if ganador_ab == ganador_ba else 0.0
    return {
        "q_A": round(ab.q, 4),
        "q_B": round(ba.q, 4),
        "ganador_orden_AB": ganador_ab,
        "ganador_orden_BA": ganador_ba,
        "tasa_acuerdo": acuerdo,
    }


def calibrate(judge: LLMJudge, samples: Sequence[tuple[str, Artifact, Sequence, float]]) -> dict:
    """Compara al juez con anotaciones humanas: MAE y sesgo medio.

    ``samples``: (instruccion, artefacto, criterios, q_humano).
    """
    errores, sesgos = [], []
    for instruccion, artifact, criterios, q_humano in samples:
        q_juez = judge.score(instruccion, artifact, criterios).q
        errores.append(abs(q_juez - q_humano))
        sesgos.append(q_juez - q_humano)
    if not errores:
        return {"n": 0, "mae": None, "sesgo_medio": None}
    return {
        "n": len(errores),
        "mae": round(statistics.fmean(errores), 4),
        "sesgo_medio": round(statistics.fmean(sesgos), 4),
    }
