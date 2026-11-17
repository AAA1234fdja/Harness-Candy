#!/usr/bin/env python3
"""Bench de escalabilidad (seccion 10 del PDF / seccion 7 del checklist).

Genera un repositorio sintetico con N modulos (con y sin defectos), crea un
DAG con N tareas de escaneo independientes + 1 de informe, las ejecuta en
paralelo con limites de concurrencia y reporta las metricas del sistema
(requisitos, pruebas, defectos, tiempo, costo, trabajo duplicado,
mantenibilidad) y los tiempos por fase (para justificar con MEDICIONES la
lista priorizada de migracion a Rust; ver docs/INDEPENDENCIA.md).

Uso:  python examples/bench_escalabilidad.py [N]     # N = numero de modulos (default 24)
"""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness_candy.agents import ScriptedBackend, SecurityScanAgent, Task
from harness_candy.components import WEV
from harness_candy.dag import DAGExecutor, NodeResult, TaskDAG, TaskNode
from harness_candy.harness import Harness
from harness_candy.metrics import MetricsCollector
from harness_candy.pool import LIGHT_TAG, ModelPool, PoolEntry
from harness_candy.quality import Criterion
from harness_candy.runner import run_task
from harness_candy.security import SecurityGate

CRITS = [
    Criterion("informe_json_valido", "informe JSON", 3.0),
    Criterion("compile_ok", "compila", 2.0),
    Criterion("sin_secretos_criticos", "sin secretos", 3.0),
    Criterion("tiene_recomendaciones", "recomendaciones", 1.0),
    Criterion("pasa_guardias_salida", "puerta de seguridad", 2.0),
]


def build_repo(root: Path, n: int) -> None:
    for i in range(n):
        mod = root / f"mod_{i:03d}"
        mod.mkdir(parents=True, exist_ok=True)
        (mod / "core.py").write_text(
            f"def f_{i}(a, b):\n    return a + b + {i}\n", encoding="utf-8"
        )
        if i % 5 == 0:  # cada 5 modulos, uno con defecto (secreto + import sin usar)
            (mod / "core.py").write_text(
                f"import os\nAWS = 'AKIAIOSFODNN7EXAMPLE'\ndef f_{i}(a, b):\n    return a + b\n",
                encoding="utf-8",
            )
        if i % 7 == 0:  # y cada 7, uno que no compila
            (mod / "roto.py").write_text("def roto(:\n", encoding="utf-8")


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    with tempfile.TemporaryDirectory(prefix="bench-") as td:
        root = Path(td) / "repo"
        build_repo(root, n)

        pool = ModelPool()
        pool.add(PoolEntry("flash-1", "modelo-ligero-1", "K1", 0.0001, roles={"xev"}, tag=LIGHT_TAG))
        pool.add(PoolEntry("flash-2", "modelo-ligero-2", "K2", 0.0001, roles={"xev"}, tag=LIGHT_TAG))
        wev = WEV(SecurityGate())
        agent = SecurityScanAgent("XEV", "modelo-ligero-1", ScriptedBackend(lambda *a, **k: "ok"),
                                  Harness(guardrails=["json_strict"], skills=["secrets_v2", "recomendaciones"]))

        dag = TaskDAG()
        for i in range(n):
            sub = root / f"mod_{i:03d}"
            dag.add(TaskNode(
                task_id=f"scan-{i:03d}", kind="security_scan",
                instruction=f"escanear {sub}", herramienta="security_scan",
                agent="XEV", criterios=CRITS, inputs={"root": str(sub)},
            ))
        dag.add(TaskNode(task_id="report", kind="write_report", instruction="informe global",
                         deps=[f"scan-{i:03d}" for i in range(n)], criterios=CRITS[:2],
                         herramienta="security_scan", inputs={"root": str(root)}))
        dag.validate()

        metrics = MetricsCollector()
        t0 = time.time()

        def handler(node, ctx):
            task = Task(node.task_id, node.kind, node.instruction, inputs=node.inputs,
                        criterios=node.criterios, max_reintentos=node.max_reintentos)
            art = run_task(task, agent, pool, _store, _budget, wev, seed=ctx.get("seed", 0))
            msg, q = wev.evaluate(art, node.criterios)
            return NodeResult(node.task_id, "done" if msg.veredicto == "aprobado" else "rejected",
                              artifact=art, wev=msg)

        from harness_candy.harness import Budget, HarnessStore

        _store, _budget = HarnessStore(), Budget(total=10**9, beta=1.0, k=0, m=1)  # sin sondeo en el bench
        executor = DAGExecutor(handler, max_concurrency=8)
        results = executor.execute(dag, {"seed": 0})
        duracion = time.time() - t0

        for tid, res in results.items():
            node = dag.nodes[tid]
            metrics.add_result(res, criterios_total=len(node.criterios))
            if res.wev:
                metrics.mark_cumplidos(sum(1 for v in res.wev.checks.values() if v))
            metrics.costo_corridas += 1.0
        snap = metrics.snapshot(duracion=duracion)

        print(f"BENCH DE ESCALABILIDAD: {n} modulos, {n + 1} tareas, concurrencia=8")
        print(json.dumps(snap, ensure_ascii=False, indent=2))
        estados = {}
        for r in results.values():
            estados[r.status] = estados.get(r.status, 0) + 1
        print("estados:", estados)
        print(f"\ntiempo total: {duracion:.2f}s | tiempo/tarea: {duracion / (n + 1) * 1000:.1f}ms")
        print("Estos tiempos alimentan la justificacion de la migracion a Rust (docs/INDEPENDENCIA.md).")


if __name__ == "__main__":
    main()
