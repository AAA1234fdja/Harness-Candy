#!/usr/bin/env python3
"""Prueba el sistema Ely-Cowork con un modelo REAL de xkiro (API OpenAI-compatible).

Requisitos (en TU entorno; la clave nunca se guarda en el repo):

    export XKIRO_API_KEY="sk-..."                       # tu clave de xkiro
    export XKIRO_BASE_URL="https://api.xkiro.ai/v1"     # opcional (ese es el default)
    export XKIRO_MODEL="nombre-del-modelo"              # opcional si la API lo exige

    python examples/demo_xkiro.py

Hace dos cosas:
1. una llamada directa al backend (ping) para verificar clave/endpoint/modelo;
2. una tarea completa con run_task (Listado 1): el adaptador Harness^2 sondea
   variantes del harness con el modelo real y WEV puntua con Q(a).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness_candy.agents import Agent, Task
from harness_candy.backends import BackendError, OpenAICompatibleBackend
from harness_candy.components import WEV
from harness_candy.harness import Budget, Harness, HarnessStore
from harness_candy.pool import LIGHT_TAG, ModelPool, PoolEntry
from harness_candy.quality import Criterion
from harness_candy.runner import run_task
from harness_candy.security import SecurityGate


def main() -> int:
    if not os.environ.get("XKIRO_API_KEY"):
        print("Falta XKIRO_API_KEY. Ejemplo:")
        print('  export XKIRO_API_KEY="sk-..."')
        print('  export XKIRO_MODEL="nombre-del-modelo"   # si la API lo exige')
        print("  python examples/demo_xkiro.py")
        return 2

    backend = OpenAICompatibleBackend()
    print(f"endpoint: {backend.base_url}")
    print(f"modelo por defecto: {backend.default_model or '(pasa model=... o exporta XKIRO_MODEL)'}")

    # 1) ping al modelo real
    try:
        respuesta = backend.complete(
            "Responde en una sola linea: ¿que eres?", system="Eres conciso.", seed=1
        )
    except BackendError as e:
        print(f"ERROR contactando xkiro: {e}")
        print("Revisa XKIRO_API_KEY, XKIRO_BASE_URL y XKIRO_MODEL.")
        return 1
    print(f"\n[ping xkiro] {respuesta}\n")

    # 2) tarea completa con el adaptador Harness^2 sobre el modelo real
    model = backend.default_model or "default"
    pool = ModelPool()
    pool.add(PoolEntry("xkiro-1", model, "XKIRO_API_KEY", cost_per_1k=0.001, roles={"xev"}, tag=LIGHT_TAG))
    agent = Agent("XEV", model, backend, Harness(system_prompt="Eres un analista de seguridad. Devuelve SOLO JSON valido."))
    task = Task(
        task_id="t-xkiro-1",
        kind="write_report",
        instruction="Devuelve un JSON con las claves {\"ok\": true, \"reporte\": \"hola desde xkiro\"}",
        criterios=[
            Criterion("informe_json_valido", "la salida es JSON estructurado", 3.0),
            Criterion("pasa_guardias_salida", "la salida pasa la puerta de seguridad", 2.0),
        ],
    )
    wev = WEV(SecurityGate())
    store = HarnessStore()
    budget = Budget(total=10_000, beta=0.5, k=2, m=3)
    artifact = run_task(task, agent, pool, store, budget, wev, seed=1)
    msg, q = wev.evaluate(artifact, task.criterios)
    print("[run_task con xkiro]")
    print("  salida del modelo:", artifact.to_text()[:300])
    print(f"  checks={msg.checks} veredicto={msg.veredicto} Q={q:.3f}")
    print(f"  costo de adaptacion (sondeos): {budget.spent_adapt:.0f} corridas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
