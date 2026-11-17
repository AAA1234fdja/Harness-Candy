"""Proposer con refinamiento LLM de los prompts del harness (v3 §5.2, paper §3 Propose).

A diferencia de ``RuleBasedProposer`` (mutaciones fijas), ``LLMProposer`` usa un
backend LLM para *editar* el harness (system_prompt, tool_guidance, guardrails)
a partir de la evidencia de corridas previas (hallazgos WEV, q, trayectorias).

Seguridad (fail-closed):
  - la respuesta del LLM debe ser JSON validada contra el esquema ``harness``
    (usa ``llm.structured_output`` con reintentos);
  - si el LLM falla o propone algo invalido, se cae a ``RuleBasedProposer``;
  - jamas se ejecuta nada del texto del LLM: solo se copian campos de texto
    plano a un ``Harness`` nuevo (``evolve``), que luego WEV evalua.
"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Optional

from .agents import LLMBackend, Task
from .harness import Harness, RuleBasedProposer
from .llm import PromptTemplate, structured_output
from .schemas import validate_named

CANDIDATO_SCHEMA = {
    "type": "object",
    "required": ["cambios", "razonamiento"],
    "additionalProperties": False,
    "properties": {
        "cambios": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "system_prompt": {"type": "string", "minLength": 1},
                "tool_guidance": {"type": "string"},
                "guardrails": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "skills": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "scripts": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            },
        },
        "razonamiento": {"type": "string"},
    },
}

PROMPT_PROPOSE = """Eres el componente PROPOSE del adaptador Harness^2.

Tarea (kind={kind}): {instruction}
Criterios de aceptacion: {criterios}

Harness actual (h0):
{system_prompt}

Evidencia de corridas previas:
- q medio de referencia: {q_ref}
- hallazgos: {hallazgos}
- trayectorias: {trayectorias}

Propone {k} variantes de h0 como objetos JSON con esta forma (una linea por variante):
"cambios": { "system_prompt": "...", "tool_guidance": "...", "guardrails": [...], "skills": [...] }, "razonamiento": "..."

Reglas: conserva lo que funciono; corrige SOLO lo que la evidencia muestra
que falla; no inventes herramientas; maximo {k} propuestas. Devuelve SOLO
un objeto JSON con la clave "propuestas" que sea una lista de esas variantes.
"""


class LLMProposer:
    """Propone candidatos de harness refinando prompts con un LLM (fail-closed)."""

    def __init__(self, backend: LLMBackend, *, model: str = "", fallback: Optional[RuleBasedProposer] = None, max_retries: int = 2):
        self.backend = backend
        self.model = model
        self.fallback = fallback or RuleBasedProposer()
        self.max_retries = max_retries
        self.ultimo_razonamiento = ""

    def __call__(self, h0: Harness, task_kind: str, k: int, *, task: Optional[Task] = None, evidencia: Optional[dict] = None) -> list[Harness]:
        evidencia = evidencia or {}
        try:
            return self._proponer_llm(h0, task_kind, k, task, evidencia)
        except Exception:
            # fail-closed: sin LLM valido, usamos las mutaciones deterministas
            return self.fallback(h0, task_kind, k)

    def _proponer_llm(self, h0: Harness, task_kind: str, k: int, task: Optional[Task], evidencia: dict) -> list[Harness]:
        prompt = PromptTemplate(PROMPT_PROPOSE).render(
            kind=task_kind,
            instruction=(task.instruction if task else task_kind),
            criterios=", ".join(c.id for c in task.criterios) if task else "(genericos)",
            system_prompt=h0.system_prompt or "(vacio)",
            q_ref=round(evidencia.get("q_ref", 0.0), 4),
            hallazgos=json.dumps(evidencia.get("hallazgos", []), ensure_ascii=False)[:800],
            trayectorias=json.dumps(evidencia.get("trayectorias", []), ensure_ascii=False)[:800],
            k=k,
        )
        schema = {
            "type": "object",
            "required": ["propuestas"],
            "additionalProperties": False,
            "properties": {"propuestas": {"type": "array", "minItems": 1, "maxItems": max(1, k * 2), "items": CANDIDATO_SCHEMA}},
        }
        data, _ = structured_output(
            self.backend, prompt, schema, model=self.model, max_retries=self.max_retries, schema_name="propuestas",
        )
        candidatos: list[Harness] = []
        for prop in data["propuestas"][: 2 * k]:
            cambios = prop["cambios"]
            # validar cada campo contra el esquema de harness parcial
            parcial = {kk: vv for kk, vv in cambios.items() if vv not in (None, "", [])}
            if parcial:
                validate_named("harness", {**{f: getattr(h0, f) for f in ("version",)}, **parcial} if False else parcial)
            cand = h0.evolve(**cambios) if cambios else h0
            # conserva lo que funciono: el system_prompt nuevo se ANADE al de h0
            if "system_prompt" in cambios and h0.system_prompt:
                cand = replace(cand, system_prompt=h0.system_prompt + "\n" + cambios["system_prompt"])
            candidatos.append(cand)
        if not candidatos:
            raise ValueError("el LLM no propuso candidatos validos")
        self.ultimo_razonamiento = " | ".join(p.get("razonamiento", "") for p in data["propuestas"])
        return candidatos


def proposer_desde_config(backend: LLMBackend | None, **kw) -> object:
    """Devuelve LLMProposer si hay backend; si no, RuleBasedProposer."""
    if backend is None:
        return RuleBasedProposer()
    return LLMProposer(backend, **kw)
