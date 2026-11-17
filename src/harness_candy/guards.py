"""Guardrails de salida componibles (checklist v3 §5.8, guardrails E/S).

Un ``Guard`` inspecciona un artefacto y devuelve hallazgos (con severidad).
``GuardPipeline`` los compone: todos se ejecutan y se agregan los hallazgos.

Guardas incluidas:
- ``NoSecretsGuard``: bloquea secretos/PII en la salida (usa security.py).
- ``MaxLengthGuard``: rechaza salidas excesivamente largas.
- ``JsonSchemaGuard``: exige que el artefacto cumpla un esquema publicado.
- ``RequiredKeysGuard``: exige claves minimas en un artefacto JSON.
- ``ForbiddenPatternsGuard``: patrones regex prohibidos en la salida.
"""
from __future__ import annotations

import re
from typing import Any, Optional, Protocol, Sequence

from .protocols import Hallazgo
from .schemas import SchemaError, validate_schema
from .security import scan_pii


class Guard(Protocol):
    name: str

    def check(self, artifact_text: str, artifact: Any = None) -> list[Hallazgo]: ...


class GuardPipeline:
    def __init__(self, guards: Sequence[Guard]):
        self.guards = list(guards)

    def add(self, guard: Guard) -> None:
        self.guards.append(guard)

    def check(self, artifact_text: str, artifact: Any = None) -> list[Hallazgo]:
        hallazgos: list[Hallazgo] = []
        for g in self.guards:
            try:
                hallazgos.extend(g.check(artifact_text, artifact))
            except Exception as exc:  # noqa: BLE001 - un guard roto no tumba la corrida
                hallazgos.append(Hallazgo(g.name, "media", f"guard roto: {type(exc).__name__}: {exc}"))
        return hallazgos

    def names(self) -> list[str]:
        return [g.name for g in self.guards]


class NoSecretsGuard:
    """Bloquea secretos y PII en la salida (severidad critica)."""

    name = "no_secretos"

    def __init__(self, extra_patterns: Optional[list[str]] = None):
        self.extra = [re.compile(p) for p in (extra_patterns or [])]

    def check(self, artifact_text: str, artifact: Any = None) -> list[Hallazgo]:
        out: list[Hallazgo] = []
        hits = scan_pii(artifact_text)
        for h in hits:
            out.append(Hallazgo(self.name, "critica", h))
        for pat in self.extra:
            for m in pat.finditer(artifact_text):
                out.append(Hallazgo(self.name, "critica", f"patron prohibido: {m.group(0)[:40]}..."))
        return out


class MaxLengthGuard:
    name = "longitud_max"

    def __init__(self, max_chars: int = 100_000):
        self.max_chars = max_chars

    def check(self, artifact_text: str, artifact: Any = None) -> list[Hallazgo]:
        if len(artifact_text) > self.max_chars:
            return [Hallazgo(self.name, "alta", f"salida de {len(artifact_text)} caracteres > max {self.max_chars}")]
        return []


class JsonSchemaGuard:
    """El artefacto debe cumplir un esquema (p. ej. un esquema de informe)."""

    def __init__(self, schema: dict, name: str = "json_schema"):
        self.schema = schema
        self.name = name

    def check(self, artifact_text: str, artifact: Any = None) -> list[Hallazgo]:
        import json as _json

        data = artifact if artifact is not None else None
        if data is None:
            try:
                data = _json.loads(artifact_text)
            except Exception:
                return [Hallazgo(self.name, "alta", "la salida no es JSON valido")]
        try:
            validate_schema(data, self.schema, path=f"{self.name}.$")
        except SchemaError as e:
            return [Hallazgo(self.name, "alta", str(e))]
        return []


class RequiredKeysGuard:
    name = "claves_requeridas"

    def __init__(self, keys: Sequence[str]):
        self.keys = list(keys)

    def check(self, artifact_text: str, artifact: Any = None) -> list[Hallazgo]:
        if not isinstance(artifact, dict):
            return [Hallazgo(self.name, "media", "el artefacto no es un objeto JSON")]
        faltan = [k for k in self.keys if k not in artifact]
        if faltan:
            return [Hallazgo(self.name, "media", f"faltan claves: {faltan}")]
        return []


class ForbiddenPatternsGuard:
    name = "patrones_prohibidos"

    def __init__(self, patterns: Sequence[str], severidad: str = "alta"):
        self.patterns = [re.compile(p) for p in patterns]
        self.severidad = severidad

    def check(self, artifact_text: str, artifact: Any = None) -> list[Hallazgo]:
        out = []
        for pat in self.patterns:
            for m in pat.finditer(artifact_text):
                out.append(Hallazgo(self.name, self.severidad, f"patron prohibido: {m.group(0)[:60]}"))
        return out


def default_pipeline() -> GuardPipeline:
    """Pipeline por defecto: no secretos/PII + longitud razonable."""
    return GuardPipeline([NoSecretsGuard(), MaxLengthGuard()])
