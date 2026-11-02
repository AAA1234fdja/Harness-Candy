"""Experimentos con grid de params: ejecucion paralela local + estadistica.

- ``grid``: dict param -> lista de valores; se expande con itertools.product.
- ``ejecutar(params) -> float``: corre UNA configuracion y devuelve su score
  (cuanto mayor, mejor). Es inyectable: en tests se usa una funcion pura.
- Paralelo local con ThreadPoolExecutor (los experimentos de harness son
  mayormente I/O de LLM; el GIL no limita el paralelismo de red).
- Estadistica propia (stdlib-only): media, desviacion e IC95 por bootstrap
  de la media, para decir "el mejor punto es mejor con significancia".
- Reporte en Markdown y JSON para el informe del lab.
"""
from __future__ import annotations

import itertools
import json
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


# ---------------------------------------------------------------- estadistica
def media(xs: list[float]) -> float:
    if not xs:
        raise ValueError("media de lista vacia")
    return sum(xs) / len(xs)


def desviacion(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    return statistics.stdev(xs)


def ic95_bootstrap(xs: list[float], n_boot: int = 1000, seed: int = 0) -> tuple[float, float]:
    """IC95 de la media por bootstrap (percentil 2.5 / 97.5)."""
    if not xs:
        raise ValueError("IC de lista vacia")
    if len(xs) == 1:
        return (xs[0], xs[0])
    rng = random.Random(seed)
    n = len(xs)
    medias = []
    for _ in range(max(1, n_boot)):
        medias.append(sum(xs[rng.randrange(n)] for _ in range(n)) / n)
    medias.sort()
    lo = medias[int(0.025 * len(medias))]
    hi = medias[min(len(medias) - 1, int(0.975 * len(medias)))]
    return (lo, hi)


# ------------------------------------------------------------------ experimento
@dataclass
class PuntoGrid:
    """Una configuracion del grid ya evaluada."""

    params: dict
    score: float
    duracion: float = 0.0

    def to_dict(self) -> dict:
        return {"params": self.params, "score": round(self.score, 6), "duracion": round(self.duracion, 3)}


@dataclass
class ResultadoLab:
    nombre: str
    puntos: list[PuntoGrid] = field(default_factory=list)
    mejor: Optional[PuntoGrid] = None
    media_global: float = 0.0
    ic95_global: tuple[float, float] = (0.0, 0.0)
    n_boot: int = 1000
    duracion: float = 0.0

    @property
    def mejor_params(self) -> dict:
        return dict(self.mejor.params) if self.mejor else {}

    @property
    def mejor_score(self) -> float:
        return self.mejor.score if self.mejor else 0.0

    @property
    def ic95(self) -> tuple[float, float]:
        """IC95 del score del MEJOR punto (bootstrap sobre sus repeticiones)."""
        if not self.mejor:
            return (0.0, 0.0)
        repeticiones = [p.score for p in self.puntos if p.params == self.mejor.params]
        if len(repeticiones) < 2:
            return (self.mejor.score, self.mejor.score)
        return ic95_bootstrap(repeticiones, n_boot=self.n_boot)

    def to_dict(self) -> dict:
        return {
            "nombre": self.nombre,
            "n_puntos": len(self.puntos),
            "mejor_params": self.mejor_params,
            "mejor_score": round(self.mejor_score, 6),
            "ic95_mejor": [round(self.ic95[0], 6), round(self.ic95[1], 6)],
            "media_global": round(self.media_global, 6),
            "ic95_global": [round(self.ic95_global[0], 6), round(self.ic95_global[1], 6)],
            "duracion": round(self.duracion, 3),
            "puntos": [p.to_dict() for p in self.puntos],
        }

    def guardar_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def reporte_md(self) -> str:
        lineas = [
            f"# Experimento: {self.nombre}",
            "",
            f"- Puntos evaluados: {len(self.puntos)}",
            f"- Mejor configuracion: `{json.dumps(self.mejor_params, ensure_ascii=False)}`",
            f"- Mejor score: **{self.mejor_score:.4f}**  IC95={tuple(round(x, 4) for x in self.ic95)}",
            f"- Media global: {self.media_global:.4f}  IC95={tuple(round(x, 4) for x in self.ic95_global)}",
            f"- Duracion: {self.duracion:.2f}s",
            "",
            "| params | score | duracion (s) |",
            "|---|---|---|",
        ]
        for p in sorted(self.puntos, key=lambda p: p.score, reverse=True):
            lineas.append(f"| {json.dumps(p.params, ensure_ascii=False)} | {p.score:.4f} | {p.duracion:.3f} |")
        return "\n".join(lineas) + "\n"


class Experimento:
    """Un experimento: nombre + grid + funcion de evaluacion.

    ``ejecutar(params)`` puede devolver un float (score) o un dict con clave
    ``score``. ``repeticiones`` permite repetir cada punto para tener IC.
    """

    def __init__(
        self,
        nombre: str,
        *,
        grid: dict[str, list],
        ejecutar: Callable[[dict], Any],
        repeticiones: int = 1,
        max_workers: int = 4,
        n_boot: int = 1000,
        seed: int = 0,
    ) -> None:
        if not grid:
            raise ValueError("el grid no puede ser vacio")
        if not all(isinstance(v, (list, tuple)) and len(v) > 0 for v in grid.values()):
            raise ValueError("cada param del grid debe tener al menos un valor")
        if not callable(ejecutar):
            raise TypeError("ejecutar debe ser callable")
        self.nombre = nombre
        self.grid = {k: list(v) for k, v in grid.items()}
        self.ejecutar = ejecutar
        self.repeticiones = max(1, int(repeticiones))
        self.max_workers = max(1, int(max_workers))
        self.n_boot = n_boot
        self.seed = seed

    def puntos_grid(self) -> list[dict]:
        claves = list(self.grid)
        return [dict(zip(claves, vals)) for vals in itertools.product(*(self.grid[k] for k in claves))]

    def _score_de(self, salida: Any) -> float:
        if isinstance(salida, dict):
            return float(salida["score"])
        return float(salida)

    def correr(self) -> ResultadoLab:
        inicio = time.time()
        configuraciones = self.puntos_grid()
        trabajos: list[tuple[dict, int]] = [(cfg, r) for cfg in configuraciones for r in range(self.repeticiones)]

        def _uno(trab: tuple[dict, int]) -> PuntoGrid:
            cfg, _rep = trab
            t0 = time.time()
            salida = self.ejecutar(dict(cfg))
            return PuntoGrid(params=cfg, score=self._score_de(salida), duracion=time.time() - t0)

        if self.max_workers == 1 or len(trabajos) == 1:
            puntos = [_uno(t) for t in trabajos]
        else:
            with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                puntos = list(ex.map(_uno, trabajos))
        puntos.sort(key=lambda p: p.score, reverse=True)
        mejor = puntos[0] if puntos else None
        scores = [p.score for p in puntos]
        res = ResultadoLab(
            nombre=self.nombre,
            puntos=puntos,
            mejor=mejor,
            media_global=media(scores) if scores else 0.0,
            ic95_global=ic95_bootstrap(scores, n_boot=self.n_boot, seed=self.seed) if scores else (0.0, 0.0),
            n_boot=self.n_boot,
            duracion=time.time() - inicio,
        )
        return res
