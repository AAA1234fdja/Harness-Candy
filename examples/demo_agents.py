#!/usr/bin/env python3
"""Demo: cargar el catalogo de agentes (examples/agents.json) y ejecutar una tarea.

Muestra el flujo §5.2 del checklist v3: agentes declarativos (nombre, modelo,
roles, harness inicial, herramientas) -> build_agents(backend) -> run_task.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness_candy.agents import Task
from harness_candy.agents_catalog import load_catalog
from harness_candy.components import WEV
from harness_candy.factory import make_backend, make_pool
from harness_candy.harness import Budget, HarnessStore
from harness_candy.quality import Criterion
from harness_candy.runner import run_task
from harness_candy.security import SecurityGate


def main() -> int:
    root_repo = Path(__file__).resolve().parents[1]
    catalog = load_catalog(root_repo / "examples" / "agents.json")
    print("catalogo:", catalog.names())
    for name in catalog.names():
        spec = catalog.get(name)
        print(f"  {name}: model={spec.model} roles={spec.roles} skills={spec.skills} tools={spec.tools}")

    backend = make_backend("scripted")
    agentes = catalog.build_agents(backend)
    xev = agentes["XEV"]
    print("harness inicial de XEV:", xev.default_harness.label())

    task = Task(
        task_id="t-catalog",
        kind="security_scan",
        instruction="Escanear el paquete demo",
        inputs={"root": str(root_repo / "examples" / "golden" / "limpio")},
        criterios=[Criterion("informe_json_valido", "JSON", 3.0), Criterion("compile_ok", "compila", 2.0)],
    )
    artifact = run_task(
        task, xev, make_pool(), HarnessStore(),
        Budget(total=10_000, beta=0.5, k=2, m=3), WEV(SecurityGate()),
        seed=0,
    )
    msg, q = WEV(SecurityGate()).evaluate(artifact, task.criterios)
    print(f"resultado: veredicto={msg.veredicto} q={q:.3f} checks={msg.checks}")
    return 0 if msg.veredicto == "aprobado" else 2


if __name__ == "__main__":
    raise SystemExit(main())
