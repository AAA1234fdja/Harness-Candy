import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from helpers import make_repo

from harness_candy.ablation import CONFIGS, run_ablation
from harness_candy.agents import Agent, Artifact, ScriptedBackend, Task
from harness_candy.components import WEV
from harness_candy.quality import Criterion
from harness_candy.security import SecurityGate


class DemoAgent(Agent):
    """Agente determinista: sin guardrail 'json_strict' falla 1 de cada 4 semillas."""

    def run(self, task, harness=None, seed=0):
        h = harness or self.default_harness
        if "json_strict" not in h.guardrails and seed % 4 == 3:
            return Artifact(task.task_id, "salida malformada", meta={"harness": h.label()})
        return Artifact(task.task_id, {"ok": True}, meta={"harness": h.label()})


CRITS = [Criterion("informe_json_valido", "", 3.0), Criterion("pasa_guardias_salida", "", 2.0)]


class TestAblacion(unittest.TestCase):
    def test_cuatro_configuraciones_acumulativas(self):
        names = [c.name for c in CONFIGS]
        self.assertEqual(names, ["A", "B", "C", "D"])
        self.assertFalse(CONFIGS[0].use_wev)
        self.assertTrue(CONFIGS[1].use_wev and not CONFIGS[1].use_harness2)
        self.assertTrue(CONFIGS[2].use_harness2 and not CONFIGS[2].use_ely)
        self.assertTrue(CONFIGS[3].use_ely)

    def test_reporte_y_veredicto(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td)
            tasks = [
                Task(task_id=f"t-{i}", kind="security_scan", instruction="escanear",
                     inputs={"root": str(root)}, criterios=CRITS)
                for i in range(6)
            ]
            agent = DemoAgent("XEV", "modelo-ligero", ScriptedBackend(lambda *a, **k: "ok"))
            from helpers import make_pool

            report = run_ablation(
                tasks, agent, make_pool(), WEV(SecurityGate()),
                k=2, m=3, trace_dir=Path(td) / "traces",
            )
            self.assertEqual(set(report.metrics), {"A", "B", "C", "D"})
            # A no valida: Q=1 artificialmente pero no detecta fallos -> exito inflado
            self.assertEqual(report.metrics["A"].success_rate, 1.0)
            # B detecta el fallo de formato en ~1/4 de las corridas
            self.assertLess(report.metrics["B"].q_mean, 1.0)
            # C gasta mas costo por tarea que B (sondeo Harness^2)
            self.assertGreater(report.metrics["C"].cost_per_task, report.metrics["B"].cost_per_task)
            self.assertIn("Harness", report.verdict)
            tabla = report.table()
            self.assertIn("| A |", tabla)
            self.assertIn("| D |", tabla)


if __name__ == "__main__":
    unittest.main()
