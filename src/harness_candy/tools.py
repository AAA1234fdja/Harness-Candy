"""Registro de herramientas tipadas para XEV (checklist v3 §5.3, defineTool).

Cada herramienta declara su esquema JSON Schema de parametros, un nivel de
permiso (``read`` | ``write`` | ``exec``), timeout y rate limit. La llamada
valida los argumentos ANTES de ejecutar, aplica la allowlist de permisos del
agente, el rate limit y (si la herramienta es un comando) el sandbox.

Errores tipados: ``ToolError`` (argumentos invalidos / desconocida),
``PermissionError`` (permiso insuficiente), ``RateLimitError``,
``ToolTimeoutError``.

Herramientas incluidas de ejemplo (seguras, sobre un root acotado):
``echo``, ``list_files``, ``read_file``. Las de ``exec`` corren con
``run_sandboxed`` (red aislada cuando el SO lo permite).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .sandbox import run_sandboxed
from .schemas import SCHEMAS, SchemaError, validate_schema

PERMISSIONS = ("read", "write", "exec")


class ToolError(RuntimeError):
    pass


class ToolNotFound(ToolError):
    pass


class ToolValidationError(ToolError):
    pass


class RateLimitError(ToolError):
    pass


class ToolTimeoutError(ToolError):
    pass


@dataclass
class ToolSpec:
    """Declaracion de una herramienta (equivalente a defineTool de ADK)."""

    name: str
    description: str
    parameters: dict  # JSON Schema de los argumentos
    permission: str = "read"
    handler: Optional[Callable[[dict], Any]] = None  # None => comando shell (campo `command`)
    command: Optional[list[str]] = None
    timeout: float = 10.0
    rate_limit: int = 0  # 0 = sin limite
    rate_window_s: float = 60.0

    def __post_init__(self):
        if self.permission not in PERMISSIONS:
            raise ToolError(f"permiso desconocido: {self.permission!r}")
        if self.handler is None and self.command is None:
            raise ToolError(f"la herramienta {self.name!r} necesita handler o command")
        validate_schema(
            {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
                "permission": self.permission,
            },
            SCHEMAS["tool_spec"],
            path="tool_spec.$",
        )


class _TokenBucket:
    """Rate limit por ventana deslizante simple (token bucket)."""

    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window_s = window_s
        self._stamps: list[float] = []
        self._lock = threading.Lock()

    def allow(self, now: float | None = None) -> bool:
        if self.limit <= 0:
            return True
        now = now if now is not None else time.time()
        with self._lock:
            self._stamps = [s for s in self._stamps if now - s < self.window_s]
            if len(self._stamps) >= self.limit:
                return False
            self._stamps.append(now)
            return True


@dataclass
class ToolCallRecord:
    """Auditoria de cada llamada a herramienta."""

    ts: float
    tool: str
    actor: str
    ok: bool
    error: str = ""
    duracion: float = 0.0


class ToolRegistry:
    """Registro central de herramientas con validacion, permisos y limites."""

    def __init__(self, *, default_permissions: Optional[set[str]] = None):
        self._tools: dict[str, ToolSpec] = {}
        self._buckets: dict[str, _TokenBucket] = {}
        self._lock = threading.Lock()
        self.calls: list[ToolCallRecord] = []
        self.default_permissions = default_permissions or set(PERMISSIONS)

    def register(self, spec: ToolSpec) -> None:
        with self._lock:
            self._tools[spec.name] = spec
            self._buckets[spec.name] = _TokenBucket(spec.rate_limit, spec.rate_window_s)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolNotFound(f"herramienta desconocida: {name!r}; disponibles: {self.names()}")

    def describe(self, name: str) -> dict:
        spec = self.get(name)
        return {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
            "permission": spec.permission,
            "timeout": spec.timeout,
            "rate_limit": spec.rate_limit,
        }

    def catalog(self) -> list[dict]:
        return [self.describe(n) for n in self.names()]

    def call(self, name: str, args: dict, *, actor: str = "XEV", allowed: Optional[set[str]] = None) -> Any:
        """Ejecuta una herramienta con todas las guardas. Devuelve el resultado."""
        inicio = time.time()
        spec = self.get(name)
        allowed = allowed if allowed is not None else self.default_permissions
        try:
            if spec.permission not in allowed:
                raise PermissionError(f"el actor {actor!r} no tiene permiso {spec.permission!r} para {name!r}")
            try:
                validate_schema(args if isinstance(args, dict) else {"value": args}, spec.parameters, path=f"args({name}).$")
            except SchemaError as e:
                raise ToolValidationError(f"argumentos invalidos para {name!r}: {e}") from e
            bucket = self._buckets.get(name)
            if bucket is not None and not bucket.allow():
                raise RateLimitError(f"rate limit de {name!r}: {spec.rate_limit} llamadas / {spec.rate_window_s}s")
            if spec.handler is not None:
                resultado = spec.handler(args)
            else:
                # comando shell: los valores de args se pasan como argumentos
                # posicionales (orden de insercion), p. ej. py_compile <path>
                cmd = list(spec.command) + [str(v) for v in args.values()]
                r = run_sandboxed(cmd, timeout=spec.timeout)
                if not r.ok:
                    raise ToolTimeoutError(f"comando {spec.name!r} fallo (timeout={r.timed_out}): {r.stderr[-300:]}")
                resultado = {"stdout": r.stdout, "returncode": r.returncode, "network_isolated": r.network_isolated}
            self._record(name, actor, True, "", inicio)
            return resultado
        except (ToolError, PermissionError) as exc:
            self._record(name, actor, False, str(exc), inicio)
            raise

    def _record(self, tool: str, actor: str, ok: bool, error: str, inicio: float) -> None:
        with self._lock:
            self.calls.append(
                ToolCallRecord(ts=time.time(), tool=tool, actor=actor, ok=ok, error=error, duracion=round(time.time() - inicio, 4))
            )

    def audit_log(self) -> list[dict]:
        return [c.__dict__ for c in self.calls]


def json_arg(args: dict) -> str:
    import json

    return json.dumps(args, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Herramientas de ejemplo seguras (root acotado)
# ---------------------------------------------------------------------------

def default_registry(root: str | Path = ".") -> ToolRegistry:
    """Registro con herramientas de ejemplo que solo operan dentro de ``root``."""
    root = Path(root).resolve()
    reg = ToolRegistry()

    def _dentro(path_str: str) -> Path:
        p = (root / path_str).resolve()
        if root not in p.parents and p != root:
            raise PermissionError(f"ruta fuera del root permitido: {path_str!r}")
        return p

    reg.register(
        ToolSpec(
            name="echo",
            description="Devuelve el texto recibido (diagnostico).",
            parameters={
                "type": "object",
                "required": ["text"],
                "properties": {"text": {"type": "string"}},
                "additionalProperties": False,
            },
            permission="read",
            handler=lambda a: {"echo": a["text"]},
        )
    )
    reg.register(
        ToolSpec(
            name="list_files",
            description="Lista archivos (no directorios) dentro del root, con sufijo opcional.",
            parameters={
                "type": "object",
                "properties": {
                    "subdir": {"type": "string"},
                    "suffix": {"type": "string"},
                },
                "additionalProperties": False,
            },
            permission="read",
            handler=lambda a: {
                "files": sorted(
                    str(p.relative_to(root))
                    for p in _dentro(a.get("subdir", ".")).rglob("*")
                    if p.is_file() and (not a.get("suffix") or p.suffix == a["suffix"])
                )[:500]
            },
        )
    )
    reg.register(
        ToolSpec(
            name="read_file",
            description="Lee un archivo de texto dentro del root (max 200 KB).",
            parameters={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
            permission="read",
            handler=lambda a: {"content": _dentro(a["path"]).read_text(encoding="utf-8", errors="ignore")[:200_000]},
            rate_limit=60,
        )
    )
    def _py_compile(args: dict) -> dict:
        # la ruta se resuelve dentro del root y se pasa absoluta al sandbox
        # (el sandbox usa un cwd efimero, una ruta relativa no existiria)
        p = _dentro(args["path"])
        r = run_sandboxed(["python3", "-m", "py_compile", str(p)], timeout=15.0)
        if not r.ok:
            raise ToolTimeoutError(f"py_compile fallo (timeout={r.timed_out}): {r.stderr[-300:]}")
        return {"returncode": r.returncode, "network_isolated": r.network_isolated}

    reg.register(
        ToolSpec(
            name="py_compile",
            description="Compila un .py con py_compile en sandbox (exec, red aislada).",
            parameters={
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
            permission="exec",
            handler=_py_compile,
            timeout=15.0,
            rate_limit=30,
        )
    )
    # herramienta de comando puro (sin argumentos): ejecuta command tal cual
    reg.register(
        ToolSpec(
            name="git_version",
            description="Version de git (comando shell en sandbox, exec).",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            permission="exec",
            command=["git", "--version"],
            timeout=10.0,
        )
    )
    return reg
