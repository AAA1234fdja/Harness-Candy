#!/usr/bin/env python3
"""Benchmarks del proyecto (checklist v3 §8.2).

Ejecuta el bench de escalabilidad (N módulos, N+1 tareas en paralelo) y reporta
métricas + tiempos. Uso:

    python benchmarks/bench_escalabilidad.py [N]     # N default 24

Los resultados alimentan la decisión de migración a Rust (docs/INDEPENDENCIA.md):
se comparan tiempos/tarea antes y después de migrar un componente.
"""
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))

if __name__ == "__main__":
    sys.argv = [sys.argv[0]] + sys.argv[1:]
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples" / "bench_escalabilidad.py"), run_name="__main__")
