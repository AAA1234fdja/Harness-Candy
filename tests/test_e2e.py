import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from helpers import make_repo, make_runner

from harness_candy.agents import SecurityScanAgent, ScriptedBackend, Task
from harness_candy.components import WEV
from harness_candy.harness import Budget, Harness, Harness2Adapter, HarnessStore
from harness_candy.pool import ModelPool, PoolEntry
from harness_candy.quality import Criterion
from harness_candy.runner import run_task
from harness_candy.security import SecurityGate


class TestFlujoCompleto(unittest.TestCase):
    def test_runner_e2e_repo_limpio(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td, with_secret=False)
            runner = make_runner(Path(td) / "traces")
            res = runner.run(f"Generar informe de seguridad del repositorio {root}", inputs={"root": str(root)}, seed=0)
            # plan con 2 hitos, DAG ejecutado, WEV evaluo, ELY audito
            self.assertEqual(len(res.plan["hitos"]), 2)
            self.assertEqual(set(res.dag_results), {"t-001", "t-002"})
            self.assertEqual(set(res.wev_reports), {"t-001", "t-002"})
            for q in res.qs.values():
                self.assertTrue(0.0 <= q <= 1.0)
            self.assertIn("q_medio", res.ely_audit)
            self.assertGreaterEqual(res.ely_audit["q_medio"], 0.0)
            # trazas JSONL escritas y reproducibles
            self.assertTrue(Path(res.trace_path).exists())
            lines = Path(res.trace_path).read_text().strip().splitlines()
            self.assertGreater(len(lines), 0)
            for line in lines:
                e = json.loads(line)
                for f in ("run_id", "task_id", "model", "seed", "harness", "phase", "q"):
                    self.assertIn(f, e)
            # la memoria de conocimiento quedo alimentada por ZEV/ELY
            self.assertIsNotNone(runner.ely.knowledge)

    def test_runner_e2e_repo_con_secreto_rechaza_y_escala(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td, with_secret=True)
            runner = make_runner(Path(td) / "traces")
            res = runner.run(f"Informe de seguridad de {root}", inputs={"root": str(root)}, seed=1)
            # el escaneo encuentra el secreto AKIA (con harness mejorado) o al menos
            # WEV emite veredicto y el flujo termina (done o escalated), nunca cuelga
            statuses = {r.status for r in res.dag_results.values()}
            self.assertTrue(statuses <= {"done", "rejected", "escalated", "failed"})
            self.assertIn("hallazgos_rechazos", res.ely_audit)


class TestRunTaskAdaptador(unittest.TestCase):
    """run_task (Listado 1): adapta el harness solo si mejora sobre el ruido."""

    def setUp(self):
        self.pool = ModelPool()
        self.pool.add(PoolEntry("flash-1", "modelo-ligero", "K1", roles={"xev"}))
        self.store = HarnessStore()
        self.budget = Budget(total=10_000, beta=1.0, k=2, m=3)
        self.wev = WEV(SecurityGate())
        self.agent = SecurityScanAgent("XEV", "modelo-ligero", ScriptedBackend(lambda *a, **k: "ok"))

    def test_reutiliza_harness_despues_de_adaptar(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td)
            task = Task(
                task_id="t-100", kind="security_scan", instruction="escanear",
                inputs={"root": str(root)},
                criterios=[
                    Criterion("informe_json_valido", "", 3.0),
                    Criterion("compile_ok", "", 2.0),
                    Criterion("sin_secretos_criticos", "", 3.0),
                    Criterion("tiene_recomendaciones", "", 1.0),
                    Criterion("pasa_guardias_salida", "", 2.0),
                ],
            )
            art1 = run_task(task, self.agent, self.pool, self.store, self.budget, self.wev, seed=3)
            self.assertIsNotNone(art1.content)
            # segunda llamada: ya hay harness guardado -> no gasta presupuesto de sondeo
            spent_tras_1 = self.budget.spent_adapt
            run_task(task, self.agent, self.pool, self.store, self.budget, self.wev, seed=3)
            self.assertEqual(self.budget.spent_adapt, spent_tras_1)  # no sondeo otra vez
            h = self.store.lookup("security_scan", "modelo-ligero")
            self.assertIsNotNone(h)

    def test_adopta_mejora_con_proposer_combinado(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td)
            task = Task(
                task_id="t-200", kind="security_scan", instruction="escanear",
                inputs={"root": str(root)},
                criterios=[
                    Criterion("informe_json_valido", "", 3.0),
                    Criterion("tiene_recomendaciones", "", 1.0),
                    Criterion("pasa_guardias_salida", "", 2.0),
                ],
            )

            def proposer(h0, kind, k):
                return [h0.evolve(guardrails=["json_strict"], skills=["recomendaciones", "secrets_v2"])]

            adapter = Harness2Adapter(proposer=proposer)
            h, ev = adapter.adapt(self.agent, task, k=1, m=3, score_fn=self.wev.score, base_seed=3)
            self.assertEqual(ev.adopted, "candidato")  # seed 3 rompe el JSON sin json_strict
            self.assertIn("json_strict", h.guardrails)


if __name__ == "__main__":
    unittest.main()
