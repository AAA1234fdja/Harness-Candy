"""Catalogo de agentes desde un archivo (checklist v3 §5.2, "agentes.yaml").

Formato JSON (esquema ``agents_catalog``)::

    {"agents": [
      {"name": "XEV", "model": "modelo-ligero", "roles": ["xev"],
       "system_prompt": "...", "skills": ["secrets_v2"], "guardrails": ["json_strict"],
       "tools": ["read_file", "py_compile"]}
    ]}

``build_agents(catalog, backend)`` construye los ``Agent`` reales listos para
enchufar en ``XEV({...})``; el harness inicial de cada agente se deriva de sus
campos (skills/guardrails/system_prompt).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agents import Agent, LLMBackend
from .harness import Harness
from .schemas import SCHEMAS, SchemaError, validate_schema

AGENTS_CATALOG_SCHEMA = {
    "type": "object",
    "required": ["agents"],
    "additionalProperties": True,
    "properties": {
        "agents": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["name", "model"],
                "additionalProperties": True,
                "properties": {
                    "name": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_]{0,31}$"},
                    "model": {"type": "string", "minLength": 1},
                    "roles": {"type": "array", "items": {"type": "string"}},
                    "system_prompt": {"type": "string"},
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "guardrails": {"type": "array", "items": {"type": "string"}},
                    "tools": {"type": "array", "items": {"type": "string"}},
                    "tool_guidance": {"type": "string"},
                },
            },
        }
    },
}
# se publica junto a los demas esquemas
SCHEMAS["agents_catalog"] = AGENTS_CATALOG_SCHEMA


class AgentSpec:
    def __init__(self, d: dict):
        self.name = d["name"]
        self.model = d["model"]
        self.roles = list(d.get("roles", []))
        self.system_prompt = d.get("system_prompt", "")
        self.skills = list(d.get("skills", []))
        self.guardrails = list(d.get("guardrails", []))
        self.tools = list(d.get("tools", []))
        self.tool_guidance = d.get("tool_guidance", "")
        self.agent_class = d.get("class", "Agent")

    def to_harness(self) -> Harness:
        return Harness(
            system_prompt=self.system_prompt,
            skills=list(self.skills),
            guardrails=list(self.guardrails),
            tool_guidance=self.tool_guidance,
        )


class AgentCatalog:
    def __init__(self, agents: list[AgentSpec], raw: dict):
        self.agents = agents
        self.raw = raw

    @staticmethod
    def from_dict(data: dict) -> "AgentCatalog":
        try:
            validate_schema(data, AGENTS_CATALOG_SCHEMA, path="agents_catalog.$")
        except SchemaError:
            raise
        return AgentCatalog([AgentSpec(a) for a in data["agents"]], data)

    @staticmethod
    def load(path: str | Path) -> "AgentCatalog":
        return AgentCatalog.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def names(self) -> list[str]:
        return [a.name for a in self.agents]

    def get(self, name: str) -> AgentSpec:
        for a in self.agents:
            if a.name == name:
                return a
        raise KeyError(f"agente desconocido: {name!r}; hay: {self.names()}")

    def by_role(self, role: str) -> list[AgentSpec]:
        return [a for a in self.agents if role in a.roles or not a.roles]

    def build_agents(self, backend: LLMBackend) -> dict[str, Agent]:
        """Instancia los agentes del catalogo con el backend dado.

        ``class: "SecurityScanAgent"`` instancia el agente de escaneo real;
        por defecto se crea un ``Agent`` generico.
        """
        from .agents import SecurityScanAgent

        out: dict[str, Agent] = {}
        for spec in self.agents:
            cls = SecurityScanAgent if spec.agent_class == "SecurityScanAgent" else Agent
            out[spec.name] = cls(
                name=spec.name,
                model=spec.model,
                backend=backend,
                default_harness=spec.to_harness(),
            )
        return out


def load_catalog(path: str | Path) -> AgentCatalog:
    return AgentCatalog.load(path)
