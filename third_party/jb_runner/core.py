"""Nucleo de jb_runner: Job, cola con prioridad (heap), store JSON y runner.

Diseno:
- ``Job``: unidad de trabajo con id unico, prioridad (mayor = antes) y payload.
- ``JobQueue``: heap por (-prioridad, secuencia) -> orden estable FIFO dentro
  de la misma prioridad.
- ``JobStore``: persistencia JSON en disco con dos secciones: ``jobs`` (estado
  e intentos por id) y ``resultados`` (salida de cada job terminado). Permite
  resume: un job ya en estado OK no se re-ejecuta.
- ``JobRunner``: ejecuta los jobs con reintentos (max_intentos), checkpoint
  tras cada job y resumen final. ``ejecutar`` es inyectable (funcion o callable)
  para poder probar sin egress ni procesos externos.
"""
from __future__ import annotations

import heapq
import itertools
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

ESTADO_PENDIENTE = "pendiente"
ESTADO_OK = "ok"
ESTADO_FALLIDO = "fallido"
ESTADOS = (ESTADO_PENDIENTE, ESTADO_OK, ESTADO_FALLIDO)


@dataclass
class Job:
    """Unidad de trabajo de la cola."""

    id: str
    prioridad: int = 0
    payload: dict = field(default_factory=dict)
    max_intentos: int = 3

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prioridad": self.prioridad,
            "payload": self.payload,
            "max_intentos": self.max_intentos,
        }


class JobQueue:
    """Cola de prioridad: sale primero el de mayor prioridad (FIFO en empates)."""

    def __init__(self) -> None:
        self._heap: list[tuple[int, int, Job]] = []
        self._seq = itertools.count()

    def encolar(self, job: Job) -> None:
        heapq.heappush(self._heap, (-job.prioridad, next(self._seq), job))

    def desencolar(self) -> Optional[Job]:
        if not self._heap:
            return None
        return heapq.heappop(self._heap)[2]

    def __len__(self) -> int:
        return len(self._heap)

    @property
    def vacia(self) -> bool:
        return not self._heap


@dataclass
class ResultadoJob:
    job_id: str
    ok: bool
    resultado: Any = None
    error: str = ""
    intentos: int = 0
    duracion: float = 0.0

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "ok": self.ok,
            "resultado": self.resultado,
            "error": self.error,
            "intentos": self.intentos,
            "duracion": round(self.duracion, 3),
        }


@dataclass
class ResumenCorrida:
    procesados: int = 0
    fallidos: int = 0
    reanudado: bool = False
    duracion: float = 0.0
    resultados: list[ResultadoJob] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "procesados": self.procesados,
            "fallidos": self.fallidos,
            "reanudado": self.reanudado,
            "duracion": round(self.duracion, 3),
            "resultados": [r.to_dict() for r in self.resultados],
        }


class JobStore:
    """Store JSON en disco: estados de jobs + resultados (checkpoint/resume)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {"jobs": {}, "resultados": {}}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
                self._data.setdefault("jobs", {})
                self._data.setdefault("resultados", {})
            except (json.JSONDecodeError, OSError):
                # store corrupto: se arranca de cero en vez de tumbar la corrida
                self._data = {"jobs": {}, "resultados": {}}

    def estado(self, job_id: str) -> str:
        return self._data["jobs"].get(job_id, {}).get("estado", ESTADO_PENDIENTE)

    def intentos(self, job_id: str) -> int:
        return int(self._data["jobs"].get(job_id, {}).get("intentos", 0))

    def resultado_previo(self, job_id: str) -> Optional[ResultadoJob]:
        r = self._data["resultados"].get(job_id)
        if r is None:
            return None
        return ResultadoJob(**r)

    def marcar(self, job: Job, estado: str, intentos: int, resultado: Optional[ResultadoJob] = None) -> None:
        if estado not in ESTADOS:
            raise ValueError(f"estado desconocido: {estado!r}")
        self._data["jobs"][job.id] = {"estado": estado, "intentos": intentos, "job": job.to_dict()}
        if resultado is not None:
            self._data["resultados"][job.id] = resultado.to_dict()
        self.guardar()

    def guardar(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)  # escritura atomica: un corte no corrompe el store

    def ids_con_estado(self, estado: str) -> list[str]:
        return [jid for jid, j in self._data["jobs"].items() if j.get("estado") == estado]


class JobRunner:
    """Ejecuta jobs con reintentos, checkpoint por job y resume desde el store.

    ``ejecutar(job)`` debe devolver el resultado (cualquier objeto JSON-able)
    o lanzar excepcion. Si un job agota sus intentos queda en estado
    ``fallido`` y NO se reintenta en corridas futuras (estado final).
    """

    def __init__(
        self,
        store: JobStore,
        ejecutar: Callable[[Job], Any],
        *,
        reintentar_fallidos: bool = False,
    ) -> None:
        if not callable(ejecutar):
            raise TypeError("ejecutar debe ser callable")
        self.store = store
        self.ejecutar = ejecutar
        self.reintentar_fallidos = reintentar_fallidos

    def run(self, jobs: list[Job]) -> ResumenCorrida:
        inicio = time.time()
        cola = JobQueue()
        reanudado = False
        for job in jobs:
            estado = self.store.estado(job.id)
            if estado == ESTADO_OK:
                reanudado = True  # se reutiliza el resultado persistido
                continue
            if estado == ESTADO_FALLIDO and not self.reintentar_fallidos:
                reanudado = True
                continue
            cola.encolar(job)
        resumen = ResumenCorrida(reanudado=reanudado)
        # primero vuelca los resultados previos (resume) al resumen
        for job in jobs:
            if self.store.estado(job.id) in (ESTADO_OK, ESTADO_FALLIDO):
                r = self.store.resultado_previo(job.id)
                if r is not None:
                    resumen.resultados.append(r)
                    if r.ok:
                        resumen.procesados += 1
                    else:
                        resumen.fallidos += 1
        while not cola.vacia:
            job = cola.desencolar()
            assert job is not None
            res = self._ejecutar_con_reintentos(job)
            resumen.resultados.append(res)
            if res.ok:
                resumen.procesados += 1
            else:
                resumen.fallidos += 1
        resumen.duracion = time.time() - inicio
        return resumen

    def _ejecutar_con_reintentos(self, job: Job) -> ResultadoJob:
        intentos_previos = self.store.intentos(job.id)
        t0 = time.time()
        ultimo_error = ""
        for intento in range(1, max(1, job.max_intentos) + 1):
            try:
                resultado = self.ejecutar(job)
                res = ResultadoJob(job.id, True, resultado, "", intento + intentos_previos, time.time() - t0)
                self.store.marcar(job, ESTADO_OK, res.intentos, res)
                return res
            except Exception as e:  # noqa: BLE001 - el runner captura todo para reintentar
                ultimo_error = f"{type(e).__name__}: {e}"
                self.store.marcar(job, ESTADO_PENDIENTE, intento + intentos_previos)
        res = ResultadoJob(job.id, False, None, ultimo_error, job.max_intentos + intentos_previos, time.time() - t0)
        self.store.marcar(job, ESTADO_FALLIDO, res.intentos, res)
        return res
