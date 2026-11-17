"""Schedule avanzado (v3 §4.3 jobs + sweeps): particiones de tareas, sweep de
hyperparametros con early stop y reanudacion (resume) desde checkpoint JSON.

Diferencia con ``scheduler.py`` (jobs periodicos): aqui se trata de ejecutar
UNA cola grande de tareas en particiones (shards) con puntos de control, y de
barrer un espacio de hyperparametros midiendo una metrica objetivo.
"""
from __future__ import annotations

import itertools
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence


# ---------------------------------------------------------------------------
# Particiones
# ---------------------------------------------------------------------------

def particionar(items: Sequence[Any], n: int, *, clave_tamano: Callable[[Any], float] = lambda x: 1.0) -> list[list[Any]]:
    """Reparte ``items`` en ``n`` shards balanceados por ``clave_tamano`` (LPT greedy)."""
    if n <= 0:
        raise ValueError("n debe ser >= 1")
    shards: list[list[Any]] = [[] for _ in range(n)]
    pesos = [0.0] * n
    for item in sorted(items, key=clave_tamano, reverse=True):
        i = pesos.index(min(pesos))
        shards[i].append(item)
        pesos[i] += clave_tamano(item)
    return [s for s in shards if s] or [[] for _ in range(min(n, 1))]


def shard_de(item_index: int, total_items: int, n: int) -> int:
    """Shard determinista por indice (round-robin): el item i va al shard (i % n)."""
    if n <= 0 or total_items <= 0:
        return 0
    return item_index % n


# ---------------------------------------------------------------------------
# Sweep de hyperparametros
# ---------------------------------------------------------------------------

@dataclass
class SweepPoint:
    params: dict[str, Any]
    indice: int = 0

    def to_dict(self) -> dict:
        return {"params": self.params, "indice": self.indice}


def grid_sweep(espacio: dict[str, Sequence[Any]]) -> list[SweepPoint]:
    """Producto cartesiano del espacio de hyperparametros, en orden estable."""
    if not espacio:
        return [SweepPoint({}, 0)]
    claves = list(espacio)
    puntos = []
    for i, valores in enumerate(itertools.product(*(espacio[k] for k in claves))):
        puntos.append(SweepPoint(dict(zip(claves, valores)), i))
    return puntos


@dataclass
class SweepResult:
    mejor: SweepPoint
    mejor_valor: float
    historial: list[dict] = field(default_factory=list)  # [{params, valor, indice}]
    evaluados: int = 0
    detenido_temprano: bool = False

    def to_dict(self) -> dict:
        return {
            "mejor_params": self.mejor.params,
            "mejor_valor": round(self.mejor_valor, 6),
            "evaluados": self.evaluados,
            "detenido_temprano": self.detenido_temprano,
            "historial": self.historial,
        }


def sweep_con_early_stop(
    evaluar: Callable[[dict[str, Any]], float],
    espacio: dict[str, Sequence[Any]],
    *,
    maximizar: bool = True,
    min_puntos: int = 3,
    ventana: int = 3,
    mejora_minima: float = 0.0,
) -> SweepResult:
    """Barrido del grid con early stop: si tras ``min_puntos`` las ultimas
    ``ventana`` evaluaciones no mejoran ``mejora_minima``, se detiene."""
    puntos = grid_sweep(espacio)
    historial: list[dict] = []
    mejor_valor = float("-inf") if maximizar else float("inf")
    mejor = puntos[0]
    sin_mejora = 0
    for p in puntos:
        valor = float(evaluar(p.params))
        historial.append({"params": p.params, "valor": round(valor, 6), "indice": p.indice})
        es_mejor = valor > mejor_valor if maximizar else valor < mejor_valor
        if es_mejor and (maximizar and valor - mejor_valor >= mejora_minima or not maximizar and mejor_valor - valor >= mejora_minima or mejor is puntos[0]):
            if historial and len(historial) > 1 or mejor is p:
                pass
        if es_mejor:
            if len(historial) > 1 and abs(valor - mejor_valor) < mejora_minima and len(historial) > min_puntos:
                sin_mejora += 1
            else:
                sin_mejora = 0
            mejor_valor = valor if es_mejor else mejor_valor
            mejor = p
        else:
            sin_mejora += 1
        if len(historial) >= min_puntos and sin_mejora >= ventana:
            return SweepResult(mejor=mejor, mejor_valor=mejor_valor, historial=historial, evaluados=len(historial), detenido_temprano=True)
    return SweepResult(mejor=mejor, mejor_valor=mejor_valor, historial=historial, evaluados=len(historial), detenido_temprano=False)


# ---------------------------------------------------------------------------
# Runner con checkpoint / resume
# ---------------------------------------------------------------------------

@dataclass
class ScheduleItem:
    id: str
    datos: dict = field(default_factory=dict)


@dataclass
class ScheduleResult:
    procesados: int
    fallidos: int
    resultados: dict[str, Any] = field(default_factory=dict)
    duracion: float = 0.0
    reanudado: bool = False

    def to_dict(self) -> dict:
        return {"procesados": self.procesados, "fallidos": self.fallidos, "duracion": round(self.duracion, 3),
                "reanudado": self.reanudado, "n_resultados": len(self.resultados)}


class ScheduleRunner:
    """Ejecuta una cola de items en shards con checkpoint JSON (resume)."""

    def __init__(self, ejecutar: Callable[[ScheduleItem], Any], *, n_shards: int = 1, checkpoint: str | Path | None = None, max_reintentos: int = 2):
        self.ejecutar = ejecutar
        self.n_shards = max(1, n_shards)
        self.checkpoint = Path(checkpoint) if checkpoint else None
        self.max_reintentos = max(1, max_reintentos)
        self._estado: dict[str, Any] = {"done": {}, "failed": {}}

    def _cargar_checkpoint(self) -> bool:
        if self.checkpoint and self.checkpoint.exists():
            data = json.loads(self.checkpoint.read_text(encoding="utf-8"))
            self._estado = data
            return bool(data.get("done") or data.get("failed"))
        return False

    def _guardar_checkpoint(self) -> None:
        if self.checkpoint:
            self.checkpoint.parent.mkdir(parents=True, exist_ok=True)
            self.checkpoint.write_text(json.dumps(self._estado, ensure_ascii=False, default=str), encoding="utf-8")

    def run(self, items: Sequence[ScheduleItem]) -> ScheduleResult:
        """Procesa los items; los que ya constan en el checkpoint se saltan (resume)."""
        inicio = time.time()
        reanudado = self._cargar_checkpoint()
        shards = particionar(items, self.n_shards, clave_tamano=lambda it: 1.0)
        resultados = dict(self._estado.get("done", {}))
        fallidos = dict(self._estado.get("failed", {}))
        procesados = 0
        for shard in shards:
            for item in shard:
                if item.id in resultados or item.id in fallidos:
                    continue  # resume: ya hecho
                ok = False
                ultimo_error = ""
                for intento in range(self.max_reintentos):
                    try:
                        res = self.ejecutar(item)
                        resultados[item.id] = res if not isinstance(res, str) else res
                        self._estado["done"] = resultados
                        ok = True
                        break
                    except Exception as e:  # noqa: BLE001
                        ultimo_error = f"{type(e).__name__}: {e}"
                if ok:
                    procesados += 1
                else:
                    fallidos[item.id] = ultimo_error
                    self._estado["failed"] = fallidos
                self._guardar_checkpoint()
        return ScheduleResult(
            procesados=procesados,
            fallidos=len(fallidos),
            resultados=resultados,
            duracion=time.time() - inicio,
            reanudado=reanudado,
        )
