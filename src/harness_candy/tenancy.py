"""Multi-tenancy base: namespaces por proyecto/tenant (checklist v3 §1.2 ADR-006).

Cada tenant opera sobre su propio subdirectorio de corridas y trazas:
``runs/<tenant>/`` y ``traces/<tenant>/``. El nombre de tenant se valida con un
patron estricto (evita path traversal: solo [a-z0-9-]).

Uso:
    tm = TenantManager(Path("data"))
    store = tm.store("proyecto-a")     # JsonRunStore independiente
    trace_dir = tm.trace_dir("proyecto-a")
"""
from __future__ import annotations

import re
from pathlib import Path

from .storage import JsonRunStore, SqliteRunStore

TENANT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


class InvalidTenant(ValueError):
    pass


def validate_tenant(name: str) -> str:
    if not isinstance(name, str) or not TENANT_PATTERN.fullmatch(name):
        raise InvalidTenant(f"nombre de tenant invalido: {name!r} (use [a-z0-9-], max 32)")
    return name


class TenantManager:
    """Crea stores y trace_dirs aislados por tenant bajo un directorio base."""

    def __init__(self, base_dir: str | Path):
        self.base = Path(base_dir)

    def _dir(self, tenant: str, kind: str) -> Path:
        validate_tenant(tenant)
        # defensa en profundidad: jamas concatenar sin validar
        d = (self.base / kind / tenant).resolve()
        if self.base.resolve() not in d.parents:
            raise InvalidTenant(f"ruta fuera de la base: {d}")
        return d

    def store(self, tenant: str, *, backend: str = "json"):
        d = self._dir(tenant, "runs")
        if backend == "sqlite":
            return SqliteRunStore(d / "runs.db")
        return JsonRunStore(d)

    def trace_dir(self, tenant: str) -> Path:
        d = self._dir(tenant, "traces")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def tenants(self) -> list[str]:
        runs = self.base / "runs"
        if not runs.exists():
            return []
        return sorted(p.name for p in runs.iterdir() if p.is_dir() and TENANT_PATTERN.fullmatch(p.name))
