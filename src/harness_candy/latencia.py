"""Bench de latencia: percentiles p50/p90/p95/p99 de corridas (v3 §8.1).

``bench_latencia(fn, n)`` ejecuta ``fn`` n veces (con warmup) y devuelve
media, percentiles, min/max y total. Sirve para fijar objetivos numéricos de
latencia por tarea (los objetivos en sí son de la org 🏢) y para comparar
antes/después de migrar un componente a Rust (docs/INDEPENDENCIA.md).
"""
from __future__ import annotations

import statistics
import time
from typing import Any, Callable


def percentiles(valores: list[float], ps: tuple[float, ...] = (0.5, 0.9, 0.95, 0.99)) -> dict[str, float]:
    """Percentiles con interpolacion lineal (statistics.quantiles, method inclusive)."""
    if not valores:
        raise ValueError("sin valores")
    ordenados = sorted(valores)
    n = len(ordenados)
    out: dict[str, float] = {}
    for p in ps:
        if n == 1:
            out[f"p{int(p*100)}"] = ordenados[0]
            continue
        # cuantiles inclusivos: equivalents a numpy 'linear'
        qs = statistics.quantiles(ordenados, n=100, method="inclusive") if False else None
        # calculo directo: posicion = p * (n - 1)
        pos = p * (n - 1)
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        out[f"p{int(p*100)}"] = ordenados[lo] * (1 - frac) + ordenados[hi] * frac
    return out


def bench_latencia(fn: Callable[[], Any], *, n: int = 20, warmup: int = 2) -> dict[str, Any]:
    """Ejecuta fn n veces tras ``warmup`` y mide duraciones (segundos)."""
    if n < 1:
        raise ValueError("n >= 1")
    for _ in range(max(0, warmup)):
        fn()
    duraciones: list[float] = []
    resultado = None
    for _ in range(n):
        t0 = time.perf_counter()
        resultado = fn()
        duraciones.append(time.perf_counter() - t0)
    p = percentiles(duraciones)
    return {
        "n": n,
        "warmup": warmup,
        "media_s": round(statistics.fmean(duraciones), 6),
        "min_s": round(min(duraciones), 6),
        "max_s": round(max(duraciones), 6),
        "desv_s": round(statistics.stdev(duraciones) if n > 1 else 0.0, 6),
        "total_s": round(sum(duraciones), 4),
        **{k: round(v, 6) for k, v in p.items()},
        "resultado_ejemplo": str(resultado)[:120],
    }


def comparar_latencias(antes: dict, despues: dict) -> dict[str, Any]:
    """Delta porcentual de medias entre dos benches (negativo = mejora)."""
    delta = (despues["media_s"] - antes["media_s"]) / antes["media_s"] * 100.0 if antes["media_s"] else 0.0
    return {
        "media_antes_s": antes["media_s"],
        "media_despues_s": despues["media_s"],
        "delta_media_pct": round(delta, 2),
        "mejora": delta < 0,
        "p95_antes_s": antes.get("p95"),
        "p95_despues_s": despues.get("p95"),
    }
