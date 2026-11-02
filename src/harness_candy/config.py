"""Configuracion del sistema con esquema, entornos y precedencia (v3 §4.1).

Fuentes, de menor a mayor precedencia:
  1. archivo (JSON o .env-lite ``K=V``)
  2. variables de entorno con prefijo ``HARNESS_``
  3. overrides por codigo (kwargs)

Formato JSON esperado (esquema ``config``)::

    {"backend": {"kind": "scripted|xkiro", "base_url": "...", "model": "..."},
     "budget": {"total": 10000, "beta": 0.5, "k": 2, "m": 3},
     "server": {"host": "0.0.0.0", "port": 8000, "rate_limit": 120},
     "cache": {"dir": ".harness_cache", "ttl_s": 604800},
     "store": "json://runs",
     "trace_dir": "traces"}

Las claves de API NUNCA van en el archivo: solo referencian variables de
entorno (p. ej. ``"api_key_env": "XKIRO_API_KEY"``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .schemas import SCHEMAS, SchemaError, validate_schema

CONFIG_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "backend": {
            "type": "object",
            "properties": {
                "kind": {"enum": ["scripted", "xkiro"]},
                "base_url": {"type": "string"},
                "model": {"type": "string"},
                "api_key_env": {"type": "string", "pattern": "^[A-Z_][A-Z0-9_]*$"},
                "timeout": {"type": "number", "exclusiveMinimum": 0},
            },
        },
        "budget": {"$ref": "#budget"},
        "server": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                "rate_limit": {"type": "integer", "minimum": 1},
                "rate_window_s": {"type": "number", "exclusiveMinimum": 0},
                "auth": {"type": "boolean"},
            },
        },
        "cache": {
            "type": "object",
            "properties": {
                "dir": {"type": "string"},
                "ttl_s": {"type": "number", "exclusiveMinimum": 0},
                "max_entries": {"type": "integer", "minimum": 1},
                "enabled": {"type": "boolean"},
            },
        },
        "store": {"type": "string"},
        "trace_dir": {"type": "string"},
        "runs_dir": {"type": "string"},
    },
}
SCHEMAS["config"] = CONFIG_SCHEMA

DEFAULTS: dict[str, Any] = {
    "backend": {"kind": "scripted", "api_key_env": "XKIRO_API_KEY", "timeout": 60.0},
    "budget": {"total": 10_000, "beta": 0.5, "k": 2, "m": 3},
    "server": {"host": "0.0.0.0", "port": 8000, "rate_limit": 120, "rate_window_s": 60.0, "auth": False},
    "cache": {"dir": ".harness_cache", "ttl_s": 604800, "max_entries": 5000, "enabled": True},
    "store": "json://runs",
    "trace_dir": "traces",
    "runs_dir": "runs",
}

ENV_PREFIX = "HARNESS_"
# HARNESS_SERVER_PORT -> server.port ; HARNESS_BUDGET_TOTAL -> budget.total
_ENV_MAP = {
    "HARNESS_BACKEND_KIND": ("backend", "kind"),
    "HARNESS_BACKEND_MODEL": ("backend", "model"),
    "HARNESS_BACKEND_BASE_URL": ("backend", "base_url"),
    "HARNESS_BUDGET_TOTAL": ("budget", "total"),
    "HARNESS_BUDGET_BETA": ("budget", "beta"),
    "HARNESS_BUDGET_K": ("budget", "k"),
    "HARNESS_BUDGET_M": ("budget", "m"),
    "HARNESS_SERVER_HOST": ("server", "host"),
    "HARNESS_SERVER_PORT": ("server", "port"),
    "HARNESS_SERVER_RATE_LIMIT": ("server", "rate_limit"),
    "HARNESS_CACHE_DIR": ("cache", "dir"),
    "HARNESS_CACHE_TTL": ("cache", "ttl_s"),
    "HARNESS_STORE": ("store", None),
    "HARNESS_TRACE_DIR": ("trace_dir", None),
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _parse_env_file(path: str | Path) -> dict:
    """Formato .env-lite: lineas K=V, comentarios con #, comillas opcionales."""
    data: dict[str, Any] = {}
    for linea in Path(path).read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        v = v.strip().strip('"').strip("'")
        data[k.strip()] = v
    return data


def _coerce(v: str) -> Any:
    """Convierte strings de env/archivo al tipo que espera DEFAULTS."""
    low = v.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


class Config:
    """Configuracion viva del sistema, ya con precedencia aplicada."""

    def __init__(self, data: dict):
        validate_schema(data, CONFIG_SCHEMA, path="config.$")
        self.data = data

    @classmethod
    def load(cls, path: str | Path | None = None, *, environ: dict | None = None, **overrides: Any) -> "Config":
        data = _deep_merge(DEFAULTS, {})
        if path:
            p = Path(path)
            raw = json.loads(p.read_text(encoding="utf-8")) if p.suffix == ".json" else _parse_env_file(p)
            data = _deep_merge(data, raw)
        env = os.environ if environ is None else environ
        for env_key, (section, key) in _ENV_MAP.items():
            if env_key in env:
                val = _coerce(env[env_key])
                if key is None:
                    data[section] = val
                else:
                    data.setdefault(section, {})[key] = val
        if overrides:
            data = _deep_merge(data, overrides)
        data = interpolar(data, env)
        # validar la seccion budget contra su esquema propio
        validate_schema(data["budget"], SCHEMAS["budget"], path="config.budget.$")
        return cls(data)



    def get(self, section: str, key: str | None = None, default: Any = None) -> Any:
        v = self.data.get(section, default)
        if key is not None and isinstance(v, dict):
            return v.get(key, default)
        return v

    def to_dict(self) -> dict:
        return json.loads(json.dumps(self.data, default=str))

    def to_safe_dict(self) -> dict:
        """Como to_dict pero enmascarando cualquier campo que parezca secreto."""
        d = self.to_dict()
        def mask(x):
            if isinstance(x, dict):
                return {k: ("***" if any(s in k.lower() for s in ("key", "secret", "token", "password")) and v else mask(v)) for k, v in x.items()}
            if isinstance(x, list):
                return [mask(i) for i in x]
            if isinstance(x, str) and any(s in x for s in ("sk-", "AKIA")):
                return "***"
            return x
        return mask(d)


# ---------------------------------------------------------------------------
# Interpolacion ${VAR} desde el entorno y hot-reload por mtime
# ---------------------------------------------------------------------------

_VAR_RE = __import__("re").compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _interpolar(valor, env: dict):
    import re as _re

    if isinstance(valor, str):
        return _VAR_RE.sub(lambda m: str(env.get(m.group(1), m.group(0))), valor)
    if isinstance(valor, dict):
        return {k: _interpolar(v, env) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_interpolar(v, env) for v in valor]
    return valor


def interpolar(data: dict, env: dict | None = None) -> dict:
    """Sustituye ${VAR} en strings por variables de entorno (sin fallar si falta)."""
    return _interpolar(data, os.environ if env is None else env)


class ConfigWatcher:
    """Recarga la config cuando cambia el archivo (mtime)."""

    def __init__(self, path: str | Path, **overrides: Any):
        self.path = Path(path)
        self.overrides = overrides
        self.config = Config.load(self.path, **overrides)
        self._mtime = self.path.stat().st_mtime if self.path.exists() else 0.0

    def reload_if_changed(self) -> Config | None:
        """Si el archivo cambio, recarga y devuelve la nueva Config; si no, None."""
        m = self.path.stat().st_mtime
        if m != self._mtime:
            self._mtime = m
            self.config = Config.load(self.path, **self.overrides)
            return self.config
        return None

    def check(self) -> Config:
        self._mtime = self.path.stat().st_mtime
        return self.config


def diff_configs(a: dict, b: dict, prefix: str = "") -> list[tuple[str, Any, Any]]:
    """Diferencias planas entre dos configs: [(path, valor_a, valor_b)]."""
    out = []
    claves = set(a) | set(b)
    for k in sorted(claves, key=str):
        va, vb = a.get(k, "<ausente>"), b.get(k, "<ausente>")
        ruta = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(va, dict) and isinstance(vb, dict):
            out.extend(diff_configs(va, vb, ruta))
        elif va != vb:
            out.append((ruta, va, vb))
    return out




def load_config(path: str | Path | None = None, **overrides: Any) -> Config:
    return Config.load(path, **overrides)


def default_config() -> Config:
    return Config.load(None)
