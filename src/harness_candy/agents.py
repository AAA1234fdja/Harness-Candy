"""Agentes model-agnostic (Nivel 2) e interfaz de backend LLM.

El diseno combinado es deliberadamente independiente del proveedor: ADK es
model-agnostic (p.ej. via LiteLLM) y cada agente puede usar otro modelo y
otra clave API. Aqui la abstraccion es minima y sin dependencias:

* ``LLMBackend``: interfaz del modelo (con ``ScriptedBackend`` para pruebas
  deterministas sin claves; con ADK/LiteLLM se implementa el mismo protocolo).
* ``Agent``: modelo + instrucciones + herramientas; ``run(task, harness)``.
* ``SecurityScanAgent``: agente XEV de demostracion (caso de uso del
  documento: "generar un informe de seguridad para un repositorio"),
  cuya calidad depende mediblemente del harness (skills/guardrails).
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from .harness import Harness
from .quality import Criterion
from .sandbox import run_sandboxed


class LLMBackend(Protocol):
    """Interfaz minima de un modelo de lenguaje (pesos fijos, sin reentrenar)."""

    def complete(self, prompt: str, *, system: str = "", model: str = "", seed: int = 0) -> str: ...


class ScriptedBackend:
    """Backend determinista para tests/demos: fn(prompt, system, model, seed)."""

    def __init__(self, fn: Callable[..., str]):
        self.fn = fn

    def complete(self, prompt: str, *, system: str = "", model: str = "", seed: int = 0) -> str:
        return self.fn(prompt, system=system, model=model, seed=seed)


@dataclass
class Task:
    task_id: str
    kind: str
    instruction: str
    inputs: dict = field(default_factory=dict)
    criterios: list[Criterion] = field(default_factory=list)
    max_reintentos: int = 2
    meta: dict = field(default_factory=dict)


@dataclass
class Artifact:
    task_id: str
    content: Any
    meta: dict = field(default_factory=dict)

    def to_text(self) -> str:
        if isinstance(self.content, str):
            return self.content
        return json.dumps(self.content, ensure_ascii=False, default=str, indent=2)


class Agent:
    """Un agente: modelo con instrucciones y herramientas (ADK code-first)."""

    def __init__(
        self,
        name: str,
        model: str,
        backend: LLMBackend,
        default_harness: Harness | None = None,
        tools: dict[str, Callable] | None = None,
    ):
        self.name = name
        self.model = model
        self.backend = backend
        self.default_harness = default_harness or Harness()
        self.tools = tools or {}

    def with_model(self, model: str) -> "Agent":
        """Mismo agente (misma clase) con otro modelo (seleccion Nivel 3/pool)."""
        import copy

        new = copy.copy(self)
        new.model = model
        return new

    def build_prompt(self, task: Task, harness: Harness) -> str:
        parts = [f"TAREA {task.task_id} ({task.kind}): {task.instruction}"]
        if task.inputs:
            parts.append("ENTRADAS: " + json.dumps(task.inputs, ensure_ascii=False, default=str))
        if harness.tool_guidance:
            parts.append("GUIA DE HERRAMIENTAS: " + harness.tool_guidance)
        if harness.skills:
            parts.append("SKILLS: " + ", ".join(harness.skills))
        if harness.guardrails:
            parts.append("GUARDRAILS: " + ", ".join(harness.guardrails))
        return "\n".join(parts)

    def run(self, task: Task, harness: Harness | None = None, seed: int = 0) -> Artifact:
        h = harness or self.default_harness
        prompt = self.build_prompt(task, h)
        raw = self.backend.complete(prompt, system=h.system_prompt, model=self.model, seed=seed)
        meta = {"harness": h.label(), "model": self.model, "seed": seed}
        usage = getattr(self.backend, "last_usage", None) or {}
        if usage.get("total_tokens"):
            meta["tokens"] = usage["total_tokens"]  # costo real por tarea
        return Artifact(task.task_id, content=raw, meta=meta)


# ---------------------------------------------------------------------------
# Agente de demostracion: escaneo de seguridad de un repositorio (XEV)
# ---------------------------------------------------------------------------

SECRET_PATTERNS_V1 = [
    r"(?i)api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}",
    r"(?i)secret\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}",
    r"(?i)passwd\s*[:=]\s*['\"]?[^\s'\"]{6,}",
]
SECRET_PATTERNS_V2 = SECRET_PATTERNS_V1 + [
    r"AKIA[0-9A-Z]{16}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"ghp_[A-Za-z0-9]{20,}",
]


class SecurityScanAgent(Agent):
    """XEV especializado: informe de seguridad de un repo (caso del doc).

    La calidad del artefacto depende del harness de forma medible:
    ``json_strict`` evita informes malformados; ``secrets_v2`` detecta mas
    patrones; ``recomendaciones`` anade la seccion de mitigacion.
    """

    def run(self, task: Task, harness: Harness | None = None, seed: int = 0) -> Artifact:
        h = harness or self.default_harness
        # root absoluto: el sandbox ejecuta py_compile con cwd efimero, asi que
        # una ruta relativa no existiria dentro del sandbox
        root = Path(task.inputs.get("root", ".")).resolve()
        exts = {".py", ".js", ".ts", ".txt", ".md", ".env", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
        files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in exts and ".git" not in p.parts)

        compile_errors = []
        for p in files:
            if p.suffix == ".py":
                r = run_sandboxed([sys.executable, "-m", "py_compile", str(p)], timeout=15)
                if not r.ok:
                    compile_errors.append({"file": str(p), "error": r.stderr.strip()[-500:]})

        patterns = SECRET_PATTERNS_V2 if "secrets_v2" in h.skills else SECRET_PATTERNS_V1
        secrets = []
        for p in files:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pat in patterns:
                for m in re.finditer(pat, text):
                    secrets.append({"file": str(p), "patron": pat[:24], "fragmento": m.group(0)[:40] + "..."})

        recommendations = []
        if "recomendaciones" in h.skills:
            recommendations = [
                "Rotar inmediatamente cualquier credencial detectada.",
                "Mover secretos a variables de entorno o un gestor de secretos.",
                "Anadir pre-commit hooks que bloqueen secretos en el repo.",
            ]

        informe = {
            "repo": str(root),
            "files_scanned": len(files),
            "compile_errors": compile_errors,
            "secrets": secrets,
            "recommendations": recommendations,
        }
        # Ruido determinista: sin el guardrail json_strict, 1 de cada 4 semillas
        # produce un informe malformado (texto plano en vez de JSON estructurado).
        if "json_strict" not in h.guardrails and seed % 4 == 3:
            return Artifact(
                task.task_id,
                content=f"INFORME SIN ESTRUCTURA (seed={seed}): ver consola interna",
                meta={"raw": True, "harness": h.label(), "model": self.model, "seed": seed},
            )
        return Artifact(
            task.task_id,
            content=informe,
            meta={"harness": h.label(), "model": self.model, "seed": seed},
        )
