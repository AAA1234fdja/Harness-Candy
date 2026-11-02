"""Sistema de memoria (seccion 7 del diseno combinado).

Dos memorias diferenciadas, como propone el documento:

* ``VariableMemory``: memoria de variables (equiparable a ``session.state``
  de ADK): resultados intermedios, estado de tareas, referencias a archivos,
  con ambitos, versiones, permisos y sincronizacion para evitar conflictos
  entre agentes.
* ``KnowledgeMemory``: memoria de conocimiento (largo plazo, entre sesiones):
  decisiones arquitectonicas, resultados de experimentos, errores anteriores,
  soluciones comprobadas... recuperable sin reconstruir todo el contexto,
  con procedencia de cada dato (quien, cuando, de que tarea).
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

SCOPES = ("session", "task", "project", "user", "app")


@dataclass
class VersionedValue:
    version: int
    value: Any
    actor: str
    ts: float
    scope: str


class VariableMemory:
    """Memoria de variables compartida entre agentes de una ejecucion."""

    def __init__(self, session_id: str = ""):
        self.session_id = session_id or uuid.uuid4().hex[:10]
        self._data: dict[str, list[VersionedValue]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._global = threading.Lock()
        # permisos: prefijo de clave -> roles con permiso de escritura
        self._write_permissions: dict[str, set[str]] = {}
        self.conflicts: list[dict] = []

    def set_write_permission(self, key_prefix: str, roles: Iterable[str]) -> None:
        self._write_permissions[key_prefix] = set(roles)

    def _check_permission(self, key: str, actor: str) -> None:
        for prefix, roles in self._write_permissions.items():
            if key.startswith(prefix) and actor not in roles:
                raise PermissionError(f"{actor!r} no puede escribir {key!r} (roles: {sorted(roles)})")

    def set(self, key: str, value: Any, *, scope: str = "session", actor: str = "system") -> int:
        if scope not in SCOPES:
            raise ValueError(f"ambito desconocido: {scope!r} (validos: {SCOPES})")
        full_key = f"{scope}:{key}" if scope != "session" else key
        with self._global:
            self._check_permission(full_key, actor)
            lock = self._locks.setdefault(full_key, threading.Lock())
        with lock:
            history = self._data.setdefault(full_key, [])
            # Conflicto write-write: otro actor escribio una version distinta desde la ultima lectura
            if history and history[-1].actor != actor and scope in ("project", "app"):
                self.conflicts.append(
                    {
                        "key": full_key,
                        "ultimo_actor": history[-1].actor,
                        "actor": actor,
                        "ts": time.time(),
                    }
                )
            version = (history[-1].version + 1) if history else 1
            history.append(VersionedValue(version, value, actor, time.time(), scope))
            return version

    def get(self, key: str, *, scope: str = "session", default: Any = None) -> Any:
        full_key = f"{scope}:{key}" if scope != "session" else key
        history = self._data.get(full_key)
        if not history:
            return default
        return history[-1].value

    def history(self, key: str, *, scope: str = "session") -> list[VersionedValue]:
        full_key = f"{scope}:{key}" if scope != "session" else key
        return list(self._data.get(full_key, []))

    def keys(self) -> list[str]:
        return sorted(self._data.keys())


@dataclass
class KnowledgeEntry:
    id: str
    content: str
    procedencia: dict  # fuente, task_id, autor, fecha
    nivel_confianza: float = 1.0
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "procedencia": self.procedencia,
            "nivel_confianza": self.nivel_confianza,
            "tags": list(self.tags),
        }


class KnowledgeMemory:
    """Memoria de conocimiento duradero, con procedencia y busqueda.

    La busqueda por defecto es por solapamiento de tokens (sin embeddings);
    se puede inyectar un ``embedder`` para busqueda semantica.
    """

    def __init__(self, path: str | Path | None = None, embedder: Optional[Any] = None):
        self._entries: list[KnowledgeEntry] = []
        self.path = Path(path) if path else None
        self.embedder = embedder
        if self.path and self.path.exists():
            self._load()

    def remember(
        self,
        content: str,
        *,
        fuente: str,
        task_id: str = "",
        autor: str = "sistema",
        nivel_confianza: float = 1.0,
        tags: Iterable[str] = (),
    ) -> KnowledgeEntry:
        entry = KnowledgeEntry(
            id="kn-" + uuid.uuid4().hex[:10],
            content=content,
            procedencia={"fuente": fuente, "task_id": task_id, "autor": autor, "fecha": time.time()},
            nivel_confianza=float(nivel_confianza),
            tags=list(tags),
        )
        self._entries.append(entry)
        self._persist()
        return entry

    def recall(self, query: str, *, top_k: int = 5) -> list[KnowledgeEntry]:
        if not self._entries:
            return []
        if self.embedder is not None:  # busqueda semantica opcional
            return self.embedder.search(query, self._entries, top_k)
        q_tokens = set(self._tokens(query))
        scored = []
        for e in self._entries:
            e_tokens = set(self._tokens(e.content)) | set(e.tags)
            overlap = len(q_tokens & e_tokens)
            if overlap:
                scored.append((overlap * e.nivel_confianza, e))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if len(t) > 2]

    def all(self) -> list[KnowledgeEntry]:
        return list(self._entries)

    def _persist(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([e.to_dict() for e in self._entries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self._entries = [
            KnowledgeEntry(
                id=d["id"],
                content=d["content"],
                procedencia=d["procedencia"],
                nivel_confianza=d.get("nivel_confianza", 1.0),
                tags=d.get("tags", []),
            )
            for d in data
        ]
