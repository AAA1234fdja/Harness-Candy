"""Scheduler de suites: ejecucion periodica de suites dentro del servidor (v3 §4.3 scheduling).

Un ``Job`` referencia una suite (por ruta dentro del base_dir) y un intervalo.
``Scheduler.tick(now)`` ejecuta los jobs debidos (en un thread por job) y
guarda historial. Es deliberadamente simple (sin cron complejo): intervalo
fijo + jitter opcional. Los jobs nunca se solapan entre si (lock por job).
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class Job:
    job_id: str
    name: str
    suite_path: str  # dentro del base_dir
    interval_s: float
    enabled: bool = True
    jitter_s: float = 0.0
    next_run: float = 0.0
    last_run: float = 0.0
    last_status: str = ""
    runs: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "suite_path": self.suite_path,
            "interval_s": self.interval_s,
            "enabled": self.enabled,
            "next_run": self.next_run,
            "last_run": self.last_run,
            "last_status": self.last_status,
            "runs": self.runs,
        }


class Scheduler:
    """Ejecuta jobs por intervalo. ``run_fn(job) -> status str`` es inyectable."""

    def __init__(self, run_fn: Callable[[Job], str], *, base_dir: str | Path = "."):
        self.run_fn = run_fn
        self.base_dir = Path(base_dir).resolve()
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.history: list[dict] = []

    def add(self, *, name: str, suite_path: str, interval_s: float, enabled: bool = True, jitter_s: float = 0.0, now: float | None = None) -> Job:
        if interval_s <= 0:
            raise ValueError("interval_s debe ser > 0")
        p = (self.base_dir / suite_path).resolve()
        if not str(p).startswith(str(self.base_dir)):
            raise ValueError(f"suite_path fuera del base_dir: {suite_path!r}")
        now = now if now is not None else time.time()
        job = Job(
            job_id="job-" + uuid.uuid4().hex[:10],
            name=name,
            suite_path=suite_path,
            interval_s=interval_s,
            enabled=enabled,
            jitter_s=jitter_s,
            next_run=now + interval_s,
        )
        with self._lock:
            self.jobs[job.job_id] = job
        return job

    def remove(self, job_id: str) -> bool:
        with self._lock:
            return self.jobs.pop(job_id, None) is not None

    def get(self, job_id: str) -> Job:
        return self.jobs[job_id]

    def list(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in self.jobs.values()]

    def set_enabled(self, job_id: str, enabled: bool) -> None:
        self.jobs[job_id].enabled = enabled

    def tick(self, *, now: float | None = None) -> list[dict]:
        """Ejecuta los jobs debidos (en threads); devuelve los lanzados."""
        now = now if now is not None else time.time()
        lanzados: list[dict] = []
        with self._lock:
            debidos = [j for j in self.jobs.values() if j.enabled and now >= j.next_run]
        for job in debidos:
            if not job._lock.acquire(blocking=False):
                continue  # ya se esta ejecutando: no se solapan
            import random

            jitter = random.uniform(0, job.jitter_s) if job.jitter_s else 0.0
            job.next_run = now + job.interval_s + jitter

            def _run(j: Job = job):
                try:
                    status = self.run_fn(j)
                    j.last_status = status
                except Exception as exc:  # noqa: BLE001
                    j.last_status = f"error: {type(exc).__name__}: {exc}"
                finally:
                    j.last_run = time.time()
                    j.runs += 1
                    self.history.append({"ts": time.time(), "job_id": j.job_id, "status": j.last_status})
                    j._lock.release()

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            lanzados.append(job.to_dict())
        return lanzados

    def tick_blocking(self, *, now: float | None = None) -> list[dict]:
        """Variante sincrona (para tests): ejecuta los debidos en el hilo actual."""
        now = now if now is not None else time.time()
        ejecutados: list[dict] = []
        with self._lock:
            debidos = [j for j in self.jobs.values() if j.enabled and now >= j.next_run]
        for job in debidos:
            if not job._lock.acquire(blocking=False):
                continue
            job.next_run = now + job.interval_s
            try:
                job.last_status = self.run_fn(job)
            except Exception as exc:  # noqa: BLE001
                job.last_status = f"error: {type(exc).__name__}: {exc}"
            finally:
                job.last_run = now
                job.runs += 1
                self.history.append({"ts": now, "job_id": job.job_id, "status": job.last_status})
                job._lock.release()
            ejecutados.append(job.to_dict())
        return ejecutados
