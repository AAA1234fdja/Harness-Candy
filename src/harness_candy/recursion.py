"""Recursion task-level del paper Harness^2 (arXiv:2610.14224 §4): modos
``parallel`` y ``sequential`` bien diferenciados + reflection post-adopcion.

- ``sequential``: los sub-objetivos se ejecutan en cadena; cada corrida recibe
  como entrada el resultado acumulado de la anterior (contexto creciente).
- ``parallel``: los sub-objetivos corren en paralelo (ThreadPoolExecutor) con
  semillas distintas y sin compartir estado; se agregan los resultados.
- ``reflection``: tras adoptar un harness, un LLM reflexiona sobre la evidencia
  (que funciono / que no) y la guarda en KnowledgeMemory (memoria de largo plazo).
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from .agents import LLMBackend
from .harness import AdaptationEvidence, Harness
from .llm import PromptTemplate, structured_output
from .memory import KnowledgeMemory
from .quality import new_run_id

PARALLEL = "parallel"
SEQUENTIAL = "sequential"
MODOS = (PARALLEL, SEQUENTIAL)


@dataclass
class SubResult:
    objetivo: str
    ok: bool
    detalle: Any = None
    duracion: float = 0.0

    def to_dict(self) -> dict:
        return {"objetivo": self.objetivo, "ok": self.ok, "duracion": round(self.duracion, 3), "detalle": self.detalle if isinstance(self.detalle, (dict, list, str, int, float, bool)) or self.detalle is None else str(self.detalle)}


@dataclass
class RecursionResult:
    modo: str
    run_id: str
    sub_resultados: list[SubResult] = field(default_factory=list)
    agregado: Any = None
    reflection: str = ""
    duracion: float = 0.0

    def to_dict(self) -> dict:
        return {
            "modo": self.modo,
            "run_id": self.run_id,
            "n_sub": len(self.sub_resultados),
            "n_ok": sum(1 for s in self.sub_resultados if s.ok),
            "sub_resultados": [s.to_dict() for s in self.sub_resultados],
            "agregado": self.agregado if isinstance(self.agregado, (dict, list, str, int, float, bool)) or self.agregado is None else str(self.agregado),
            "reflection": self.reflection,
            "duracion": round(self.duracion, 3),
        }


def run_recursion(
    objetivos: Sequence[str],
    ejecutar: Callable[[str, dict], Any],
    *,
    modo: str = SEQUENTIAL,
    max_workers: int = 4,
    seed: int = 0,
) -> RecursionResult:
    """Ejecuta sub-objetivos en el modo pedido.

    ``ejecutar(objetivo, contexto)`` recibe el contexto acumulado (sequential)
    o un contexto con el indice (parallel).
    """
    if modo not in MODOS:
        raise ValueError(f"modo desconocido: {modo!r}; use {MODOS}")
    inicio = time.time()
    run_id = new_run_id()
    subs: list[SubResult] = []
    if modo == SEQUENTIAL:
        contexto: dict = {"seed": seed}
        for i, obj in enumerate(objetivos):
            t0 = time.time()
            try:
                res = ejecutar(obj, dict(contexto))
                contexto["ultimo_resultado"] = res if isinstance(res, (dict, list, str, int, float, bool)) else str(res)
                contexto["historial"] = contexto.get("historial", []) + [obj]
                subs.append(SubResult(obj, True, contexto["ultimo_resultado"], time.time() - t0))
            except Exception as e:  # noqa: BLE001 - un sub-objetivo malo no tumba la recursion
                subs.append(SubResult(obj, False, f"{type(e).__name__}: {e}", time.time() - t0))
        agregado = contexto.get("ultimo_resultado")
    else:
        def _uno(i_obj):
            i, obj = i_obj
            t0 = time.time()
            try:
                res = ejecutar(obj, {"indice": i, "seed": seed + i})
                return SubResult(obj, True, res if isinstance(res, (dict, list, str, int, float, bool)) else str(res), time.time() - t0)
            except Exception as e:  # noqa: BLE001
                return SubResult(obj, False, f"{type(e).__name__}: {e}", time.time() - t0)

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            subs = list(ex.map(_uno, enumerate(objetivos)))
        agregado = {"resultados": [s.to_dict() for s in subs], "n_ok": sum(1 for s in subs if s.ok)}
    return RecursionResult(modo=modo, run_id=run_id, sub_resultados=subs, agregado=agregado, duracion=time.time() - inicio)


REFLECTION_PROMPT = """Eres el componente de REFLECTION post-adopcion de Harness^2.

Run: {run_id}
Modo de recursion: {modo}
Harness adoptado: {adopted}
Evidencia: delta_q={delta}, k={k}, m={m}
Scores referencia: {ref_scores}
Scores candidatos: {cand_scores}

Escribe una reflexion breve (max 6 lineas) sobre QUE funciono y QUE no, y una
recomendacion concreta para la proxima adaptacion. Devuelve SOLO JSON:
{"reflexion": "...", "recomendacion": "...", "nivel_confianza": 0..1}
"""


def reflection_post_adopcion(
    backend: LLMBackend,
    *,
    run_id: str,
    evidence: AdaptationEvidence,
    harness_adoptado: Harness,
    modo: str = SEQUENTIAL,
    memory: Optional[KnowledgeMemory] = None,
    model: str = "",
) -> dict:
    """Genera la reflexion post-adopcion con el LLM y la guarda en memoria.

    Fail-closed: si el LLM no devuelve JSON valido, se guarda una reflexion
    determinista con los numeros de la evidencia.
    """
    prompt = PromptTemplate(REFLECTION_PROMPT).render(
        run_id=run_id,
        modo=modo,
        adopted=evidence.adopted,
        delta=round(evidence.delta, 4),
        k=evidence.k,
        m=evidence.m,
        ref_scores=[round(x, 4) for x in evidence.reference_scores],
        cand_scores={k: [round(v, 4) for v in vals] for k, vals in evidence.candidate_scores.items()},
    )
    schema = {
        "type": "object",
        "required": ["reflexion", "recomendacion"],
        "additionalProperties": False,
        "properties": {
            "reflexion": {"type": "string", "minLength": 1},
            "recomendacion": {"type": "string", "minLength": 1},
            "nivel_confianza": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
    }
    try:
        data, _ = structured_output(backend, prompt, schema, model=model, max_retries=2, schema_name="reflection")
    except Exception:
        data = {
            "reflexion": f"Run {run_id}: adoptado={evidence.adopted} delta={evidence.delta:.4f} (sin LLM, reflexion determinista).",
            "recomendacion": "Repetir el probe con m mayor si delta es chico; reutilizar el harness adoptado mientras q se mantenga.",
            "nivel_confianza": 0.5,
        }
    if memory is not None:
        memory.remember(
            f"run {run_id}: " + json.dumps(data, ensure_ascii=False),
            fuente="recursion.reflection",
            task_id=run_id,
            autor="Harness2-reflection",
            nivel_confianza=float(data.get("nivel_confianza", 0.5)),
            tags=["reflection", evidence.adopted, modo],
        )
    return data
