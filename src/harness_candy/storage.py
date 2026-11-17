"""Almacenamiento de corridas: interfaz RunStore con backends JSON y SQLite (v3 §12).

``JsonRunStore``: un archivo JSON por corrida en un directorio (simple,
versionable con git si se quiere). ``SqliteRunStore``: base SQLite (stdlib)
con indice por run_id y consulta por objetivo/estado.

``open_store(url)`` acepta: ``json://<dir>``, ``sqlite://<path.db>`` o una
ruta simple (se usa JSON salvo que termine en ``.db``/``.sqlite``).
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional, Protocol


class RunStore(Protocol):
    def save(self, run: dict[str, Any]) -> None: ...
    def get(self, run_id: str) -> Optional[dict[str, Any]]: ...
    def list(self, *, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]: ...
    def delete(self, run_id: str) -> bool: ...
    def count(self) -> int: ...


class JsonRunStore:
    """Persistencia en archivos JSON (un archivo por corrida)."""

    def __init__(self, directory: str | Path = "runs"):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        safe = run_id.replace("/", "_")
        return self.dir / f"{safe}.json"

    def save(self, run: dict[str, Any]) -> None:
        run_id = run.get("run_id") or f"run-{int(time.time()*1000)}"
        self._path(run_id).write_text(json.dumps(run, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def get(self, run_id: str) -> Optional[dict[str, Any]]:
        p = self._path(run_id)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def list(self, *, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        out = []
        for p in sorted(self.dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                run = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if status is None or any(r.get("status") == status for r in run.get("dag_results", {}).values()):
                out.append(run)
            if len(out) >= limit:
                break
        return out

    def delete(self, run_id: str) -> bool:
        p = self._path(run_id)
        if p.exists():
            p.unlink()
            return True
        return False

    def count(self) -> int:
        return len(list(self.dir.glob("*.json")))


class SqliteRunStore:
    """Persistencia en SQLite (stdlib): tabla runs + indice por estado/objetivo."""

    def __init__(self, path: str | Path = "runs.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    ts REAL NOT NULL,
                    objetivo TEXT,
                    duracion REAL,
                    n_tareas INTEGER,
                    result TEXT NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_runs_ts ON runs(ts)")

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path))
        con.row_factory = sqlite3.Row
        return con

    def save(self, run: dict[str, Any]) -> None:
        run_id = run.get("run_id") or f"run-{int(time.time()*1000)}"
        with self._conn() as con:
            con.execute(
                "INSERT OR REPLACE INTO runs (run_id, ts, objetivo, duracion, n_tareas, result) VALUES (?,?,?,?,?,?)",
                (
                    run_id,
                    time.time(),
                    str(run.get("objetivo", ""))[:500],
                    float(run.get("duracion", 0.0) or 0.0),
                    len(run.get("dag_results", {})),
                    json.dumps(run, ensure_ascii=False, default=str),
                ),
            )

    def get(self, run_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as con:
            row = con.execute("SELECT result FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return json.loads(row["result"]) if row else None

    def list(self, *, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as con:
            rows = con.execute("SELECT result FROM runs ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        runs = [json.loads(r["result"]) for r in rows]
        if status is not None:
            runs = [r for r in runs if any(x.get("status") == status for x in r.get("dag_results", {}).values())]
        return runs

    def delete(self, run_id: str) -> bool:
        with self._conn() as con:
            cur = con.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            return cur.rowcount > 0

    def count(self) -> int:
        with self._conn() as con:
            return int(con.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"])


def open_store(url: str | Path) -> RunStore:
    """Abre un store desde una URL simple: json://dir | sqlite://path.db | ruta."""
    s = str(url)
    if s.startswith("sqlite://"):
        return SqliteRunStore(s[len("sqlite://"):])
    if s.startswith("json://"):
        return JsonRunStore(s[len("json://"):])
    if s.endswith((".db", ".sqlite", ".sqlite3")):
        return SqliteRunStore(s)
    return JsonRunStore(s)
