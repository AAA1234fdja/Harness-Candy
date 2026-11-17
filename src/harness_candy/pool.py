"""Nivel 3: pool de claves API y seleccion de modelo por rol (seccion 6).

La seleccion no es estatica: se decide segun el trabajo, las cuotas, los
costos y las capacidades. Modelos ligeros para ZEV/XEV, mas potentes para
ISA/ELY (figura 2 del diseno combinado). Las claves nunca se almacenan en
claro: cada entrada referencia una variable de entorno con el secreto.
"""
from __future__ import annotations

import itertools
import os
import threading
from dataclasses import dataclass, field

# kind de tarea -> roles preferidos (ordenados por preferencia)
ROLE_PREFERENCES = {
    "plan": ("isa",),
    "audit": ("ely",),
    "dispatch": ("yev",),
    "research": ("zev",),
    "execute": ("xev",),
    "validate": ("wev",),
    # tipos concretos usados en la demo
    "security_scan": ("xev",),
    "write_report": ("xev",),
}

# modelo ligero vs potente (heuristica del documento: ligeros para ZEV/XEV)
LIGHT_TAG = "light"
POWER_TAG = "power"


@dataclass
class PoolEntry:
    alias: str  # nombre logico de la clave, p.ej. "flash-1"
    model: str  # modelo al que apunta, p.ej. "gemini-2.5-flash"
    secret_env: str  # nombre de la variable de entorno con la API key
    cost_per_1k: float = 0.0  # costo estimado por 1k tokens
    speed: float = 1.0  # velocidad relativa
    capabilities: set[str] = field(default_factory=set)
    roles: set[str] = field(default_factory=set)
    quota_remaining: float = float("inf")
    tag: str = LIGHT_TAG

    def has_secret(self) -> bool:
        return bool(os.environ.get(self.secret_env))


class ModelPool:
    """Pool de claves/modelos con seleccion por rol, cuotas y rotacion."""

    def __init__(self):
        self._entries: list[PoolEntry] = []
        self._lock = threading.Lock()
        self._rotators: dict[str, itertools.cycle] = {}

    def add(self, entry: PoolEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def entries(self) -> list[PoolEntry]:
        return list(self._entries)

    def _eligible(self, task_kind: str) -> list[PoolEntry]:
        roles = set()
        for kind, pref in ROLE_PREFERENCES.items():
            if kind in task_kind:
                roles.update(pref)
        if not roles:
            roles = {"xev"}  # por defecto, rol ejecutor
        eligible = [e for e in self._entries if (not e.roles or e.roles & roles) and e.quota_remaining > 0]
        if not eligible:
            eligible = [e for e in self._entries if e.quota_remaining > 0] or list(self._entries)
        # primero los del tag adecuado: ligeros para zev/xev, potentes para isa/ely
        want_power = bool(roles & {"isa", "ely"})
        eligible.sort(key=lambda e: 0 if (e.tag == POWER_TAG) == want_power else 1)
        return eligible

    def select(self, task_kind: str) -> tuple[str, str]:
        """Devuelve (alias_de_clave, modelo) para el tipo de tarea dado.

        Aplica rotacion round-robin dentro de lo elegible (distribucion
        distribuida entre varias claves API) y descuenta cuota al asignar.
        """
        with self._lock:
            eligible = self._eligible(task_kind)
            if not eligible:
                raise RuntimeError("pool vacio: agrega entradas con ModelPool.add()")
            key = task_kind
            if key not in self._rotators:
                self._rotators[key] = itertools.cycle(range(len(eligible)))
            idx = next(self._rotators[key]) % len(eligible)
            entry = eligible[idx]
            entry.quota_remaining -= 1
            return entry.alias, entry.model

    def charge(self, alias: str, tokens: int) -> float:
        """Descuenta costo por tokens usados; devuelve el costo incurrido."""
        with self._lock:
            for e in self._entries:
                if e.alias == alias:
                    return tokens / 1000.0 * e.cost_per_1k
        return 0.0
