"""Construccion del contexto del executor (ZEV -> XEV): empaqueta instruccion,
inputs, fragmentos recuperados (RAG), historial y limites de tokens en un
``ContextBundle`` con prompt listo (via llm.PromptBuilder) (v3 §5.5 ZEV).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .agents import Task
from .llm import PromptBuilder, estimate_tokens, truncar_contexto


@dataclass
class Fragmento:
    contenido: str
    procedencia: str
    score: float = 0.0

    def to_dict(self) -> dict:
        return {"contenido": self.contenido, "procedencia": self.procedencia, "score": self.score}


@dataclass
class ContextBundle:
    """Contexto del executor: todo lo que XEV necesita para ejecutar la tarea."""

    task: Task
    fragmentos: list[Fragmento] = field(default_factory=list)
    historial: list[str] = field(default_factory=list)
    max_tokens: int = 4000
    sobrante_tokens: int = 0

    @property
    def tokens_estimados(self) -> int:
        total = estimate_tokens(self.task.instruction) + sum(estimate_tokens(str(v)) for v in self.task.inputs.values())
        total += sum(estimate_tokens(f.contenido) for f in self.fragmentos)
        total += sum(estimate_tokens(h) for h in self.historial)
        return total

    def to_prompt(self) -> str:
        """Prompt final para el modelo ejecutor (secciones nombradas)."""
        pb = PromptBuilder(system="Ejecuta la tarea con las herramientas aprobadas. Cita la procedencia del contexto.", instruction=self.task.instruction)
        if self.fragmentos:
            texto = "\n\n".join(f"[{f.procedencia} | score={f.score:.3f}]\n{f.contenido}" for f in self.fragmentos)
            pb.add("contexto_recuperado", texto)
        if self.task.inputs:
            import json

            pb.add("entradas", json.dumps(self.task.inputs, ensure_ascii=False, default=str))
        if self.historial:
            pb.add("historial", "\n".join(self.historial[-10:]))
        if self.task.criterios:
            pb.add("criterios", "\n".join(f"- {c.id} (peso {c.peso}): {c.descripcion}" for c in self.task.criterios))
        return pb.build()

    def to_dict(self) -> dict:
        return {
            "task_id": self.task.task_id,
            "kind": self.task.kind,
            "instruction": self.task.instruction,
            "inputs": self.task.inputs,
            "fragmentos": [f.to_dict() for f in self.fragmentos],
            "historial": list(self.historial),
            "tokens_estimados": self.tokens_estimados,
            "max_tokens": self.max_tokens,
        }


def construir_contexto(
    task: Task,
    *,
    fragmentos: Optional[Sequence] = None,
    historial: Optional[Sequence[str]] = None,
    max_tokens: int = 4000,
) -> ContextBundle:
    """Empaqueta el contexto y recorta fragmentos por score hasta el presupuesto.

    ``fragmentos`` puede ser una lista de dicts {'contenido','procedencia','score'}
    (p.ej. salida de ``rag.RAGPipeline.query``) o de ``Fragmento``.
    """
    frags: list[Fragmento] = []
    for f in fragmentos or []:
        if isinstance(f, Fragmento):
            frags.append(f)
        elif isinstance(f, dict):
            frags.append(Fragmento(str(f.get("contenido", "")), str(f.get("procedencia", "")), float(f.get("score", 0.0))))
    # ordenar por score desc y recortar hasta max_tokens (4 chars/token)
    frags.sort(key=lambda f: f.score, reverse=True)
    presupuesto = max_tokens * 4
    base = estimate_tokens(task.instruction) + sum(estimate_tokens(str(v)) for v in task.inputs.values())
    usados = base * 4
    seleccion: list[Fragmento] = []
    for f in frags:
        costo = len(f.contenido)
        if usados + costo > presupuesto and seleccion:
            break
        seleccion.append(f)
        usados += costo
    hist = [truncar_contexto(h, max_tokens=max(50, max_tokens // 10)) for h in (historial or [])]
    bundle = ContextBundle(task=task, fragmentos=seleccion, historial=hist, max_tokens=max_tokens)
    bundle.sobrante_tokens = max(0, max_tokens - bundle.tokens_estimados)
    return bundle
