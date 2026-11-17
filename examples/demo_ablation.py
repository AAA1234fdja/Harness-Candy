#!/usr/bin/env python3
"""Demo del experimento de ablacion A/B/C/D (seccion 12 del diseno combinado).

Ejecuta el mismo conjunto de tareas en cuatro configuraciones acumulativas:
  A  base (solo ejecutar)
  B  + protocolos tipados + criterios de aceptacion + WEV
  C  + adaptador Harness^2 (Propose-Probe-Compose, ec. 2)
  D  + ELY (juez independiente, regresion, ajustes)
y compara Q medio, tasa de exito y costo por tarea.

Uso:  python examples/demo_ablation.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness_candy.ablation import run_ablation
from harness_candy.agents import Agent, Artifact, ScriptedBackend, Task
from harness_candy.components import ELY, WEV
from harness_candy.quality import Criterion, RegressionGuard
from harness_candy.memory import KnowledgeMemory
from harness_candy.pool import LIGHT_TAG, ModelPool, PoolEntry
from harness_candy.security import SecurityGate


class DemoAgent(Agent):
    """Agente determinista: sin el guardrail 'json_strict' falla 1 de cada 4
    semillas (informe malformado); con 'secrets_v2' detecta mas patrones."""

    def run(self, task, harness=None, seed=0):
        h = harness or self.default_harness
        import re

        root = Path(task.inputs.get("root", "."))
        texto = "\n".join(p.read_text(errors="ignore") for p in root.rglob("*") if p.is_file())
        secretos = re.findall(r"AKIA[0-9A-Z]{16}", texto) if "secrets_v2" in h.skills else []
        if "json_strict" not in h.guardrails and seed % 4 == 3:
            return Artifact(task.task_id, f"INFORME MALFORMADO seed={seed}", meta={"harness": h.label()})
        return Artifact(
            task.task_id,
            {"ok": True, "secrets": secretos, "recommendations": ["rotar claves"] if "recomendaciones" in h.skills else []},
            meta={"harness": h.label()},
        )


CRITS = [
    Criterion("informe_json_valido", "informe JSON estructurado", 3.0),
    Criterion("sin_secretos_criticos", "sin secretos hardcodeados", 3.0),
    Criterion("tiene_recomendaciones", "con recomendaciones", 1.0),
    Criterion("pasa_guardias_salida", "puerta de seguridad de salida", 2.0),
]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ely-ablation-") as td:
        td = Path(td)
        repo = td / "repo"
        repo.mkdir()
        (repo / "config.py").write_text("AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n", encoding="utf-8")
        tasks = [
            Task(task_id=f"t-{i:02d}", kind="security_scan", instruction="escanear repo",
                 inputs={"root": str(repo)}, criterios=CRITS)
            for i in range(8)
        ]
        pool = ModelPool()
        pool.add(PoolEntry("flash-1", "modelo-ligero", "KEY_FLASH_1", 0.0001, roles={"xev"}, tag=LIGHT_TAG))
        agent = DemoAgent("XEV", "modelo-ligero", ScriptedBackend(lambda *a, **k: "ok"))
        ely = ELY(RegressionGuard(), KnowledgeMemory())
        report = run_ablation(tasks, agent, pool, WEV(SecurityGate()), ely, k=2, m=3, trace_dir=td / "traces")
        print("EXPERIMENTO DE ABLACION (mismo conjunto de tareas, 4 configuraciones)")
        print("=" * 78)
        print(report.table())


if __name__ == "__main__":
    main()
