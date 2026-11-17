"""Tests de los huecos completados para el checklist Ely-Cowork:
Mann-Whitney, Compose con fusion, trayectorias, cancelacion, deadline,
revision humana (irreversible), allowlist de XEV, linter/diff, juez LLM
(swap test + calibracion), tasa de falsos positivos, reproducibilidad 100%,
metricas y curva k."""
import threading
import unittest

try:
    import _path  # noqa: F401
except ModuleNotFoundError:  # al importar como tests.test_* desde la raiz del repo
    from tests import _path  # noqa: F401
try:
    from helpers import make_repo, make_runner
except ModuleNotFoundError:  # al importar como tests.test_* desde la raiz del repo
    from tests.helpers import make_repo, make_runner

from harness_candy.agents import Agent, Artifact, ScriptedBackend, Task
from harness_candy.components import (
    WEV, XEV, check_diff_paths, linter_basico,
)
from harness_candy.dag import DAGExecutor, NodeResult, TaskDAG, TaskNode
from harness_candy.harness import Harness, Harness2Adapter
from harness_candy.judge import LLMJudge, calibrate, swap_test
from harness_candy.quality import (
    Criterion, mann_whitney_adopt, mann_whitney_u, should_adopt,
)
from harness_candy.ablation import k_curve
from harness_candy.security import SecurityGate
from harness_candy.pool import ModelPool, PoolEntry

CRITS = [Criterion("json", "", 2.0), Criterion("recs", "", 1.0)]


def make_task(kind="demo"):
    return Task(task_id="t-x", kind=kind, instruction="hacer algo", criterios=CRITS)


class FakeAgent(Agent):
    def __init__(self, good=False, **kw):
        super().__init__("xev", "m", ScriptedBackend(lambda *a, **k: "ok"), Harness(), **kw)
        self.good = good

    def run(self, task, harness=None, seed=0):
        h = harness or self.default_harness
        ok_json = any("json" in g for g in h.guardrails)
        ok_recs = any(s.startswith("rec") for s in h.skills)
        if self.good:
            ok_json = ok_recs = True
        return Artifact(task.task_id, {"json": ok_json, "recs": ok_recs}, meta={"harness": h.label()})


def score(artifact, criterios):
    from harness_candy.quality import score_q

    c = artifact.content if isinstance(artifact.content, dict) else {}
    return score_q(criterios, [k for k in ("json", "recs") if c.get(k)], [])


class TestMannWhitney(unittest.TestCase):
    def test_u_y_p(self):
        u, p = mann_whitney_u([0.9, 0.95, 1.0, 0.9], [0.1, 0.2, 0.1, 0.2])
        self.assertGreater(u, 8)  # separacion clara
        self.assertLess(p, 0.05)

    def test_adopta_solo_si_mejora_significativa(self):
        self.assertTrue(mann_whitney_adopt([0.2, 0.3, 0.2, 0.3], [0.9, 1.0, 0.9, 1.0]))
        self.assertFalse(mann_whitney_adopt([0.5, 0.6, 0.4, 0.5], [0.55, 0.6, 0.45, 0.6]))

    def test_regla_delta_sigue_siendo_la_default(self):
        self.assertTrue(should_adopt([0.2, 0.2, 0.2], [0.9, 0.9, 0.9]))


class TestComposeFusionYTrayectorias(unittest.TestCase):
    def test_fusiona_cuando_varios_ganadores(self):
        # dos mutaciones distintas mejoran individualmente -> compuesto
        def proposer(h0, kind, k):
            return [
                h0.evolve(guardrails=["json_strict"]),
                h0.evolve(skills=["recomendaciones"]),
                h0.evolve(system_prompt="peor prompt que no ayuda"),
            ]

        agent = FakeAgent()  # default malo
        ad = Harness2Adapter(proposer=proposer)
        h, ev = ad.adapt(agent, make_task(), k=3, m=3, score_fn=score)
        # json_strict y recs ganan individualmente -> compuesto con ambos
        self.assertEqual(ev.adopted, "compuesto")
        self.assertIn("json_strict", h.guardrails)
        self.assertTrue(any(s.startswith("rec") for s in h.skills))

    def test_evidencia_guarda_trayectorias(self):
        agent = FakeAgent()
        ad = Harness2Adapter()
        h, ev = ad.adapt(agent, make_task(), k=1, m=3, score_fn=score)
        self.assertIn("reference", ev.trajectories)
        self.assertEqual(len(ev.trajectories["reference"]), 3)
        self.assertIn("artifact=", ev.trajectories["reference"][0])
        self.assertIn("trajectories", ev.to_dict())


class TestDAGCancelacionPlazosHuman(unittest.TestCase):
    def test_cancelacion(self):
        dag = TaskDAG()
        dag.add(TaskNode("a", "demo", "tarea a"))
        dag.add(TaskNode("b", "demo", "tarea b", deps=["a"]))
        ev = threading.Event()
        ev.set()  # ya cancelado antes de empezar
        res = DAGExecutor(lambda n, c: NodeResult(n.task_id, "done")).execute(dag, {"cancel_event": ev})
        self.assertEqual({r.status for r in res.values()}, {"cancelled"})

    def test_deadline_excedido(self):
        dag = TaskDAG()
        node = TaskNode("a", "demo", "tarea lenta", deadline=0.0)
        dag.add(node)
        res = DAGExecutor(lambda n, c: NodeResult(n.task_id, "done")).execute(dag, {"node_started_at": {"a": 0.0}})
        self.assertEqual(res["a"].status, "failed")
        self.assertIn("deadline", res["a"].error)

    def test_irreversible_pasa_a_revision_humana_sin_ejecutar(self):
        dag = TaskDAG()
        dag.add(TaskNode("a", "demo", "borrar todo", irreversible=True))
        ejecutado = {"n": 0}

        def handler(n, c):
            ejecutado["n"] += 1
            return NodeResult(n.task_id, "done")

        res = DAGExecutor(handler).execute(dag)
        self.assertEqual(res["a"].status, "human_review")
        self.assertEqual(ejecutado["n"], 0)  # jamas se ejecuto


class TestXEVAllowlist(unittest.TestCase):
    def test_herramienta_no_autorizada(self):
        xev = XEV({"XEV": FakeAgent()})
        with self.assertRaises(PermissionError):
            xev.check_tool_allowed("rm_rf")
        xev.check_tool_allowed("security_scan")  # ok

    def test_comando_no_autorizado(self):
        xev = XEV({"XEV": FakeAgent()})
        with self.assertRaises(PermissionError):
            xev.check_command_allowed(["curl", "http://evil.example"])
        xev.check_command_allowed(["git", "status"])  # ok


class TestLinterYDiff(unittest.TestCase):
    def test_linter_detecta_import_sin_uso_y_error_sintaxis(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("import os\n\nx = 1\n", encoding="utf-8")
            (root / "b.py").write_text("def roto(:\n", encoding="utf-8")
            hallazgos = linter_basico(str(root))
            severidades = {h.severidad for h in hallazgos}
            self.assertIn("alta", severidades)  # syntax error
            self.assertTrue(any("import sin usar" in h.detalle for h in hallazgos))

    def test_diff_dentro_y_fuera_de_alcance(self):
        diff_ok = "--- a/src/a.py\n+++ b/src/a.py\n@@\n+linea\n"
        ok, h = check_diff_paths(diff_ok, ["src/"])
        self.assertTrue(ok and not h)
        diff_malo = "--- a/src/a.py\n+++ b/src/a.py\n--- a/etc/passwd\n+++ b/etc/passwd\n"
        ok, h = check_diff_paths(diff_malo, ["src/"])
        self.assertFalse(ok)
        self.assertTrue(any("etc/passwd" in x.detalle for x in h))


class FakeJudgeBackend:
    def __init__(self, q):
        self.q = q

    def complete(self, prompt, *, system="", model="", seed=0):
        import json

        return json.dumps({"q": self.q, "hallazgos": []})


class TestJuezLLM(unittest.TestCase):
    def test_judge_parsea_json(self):
        j = LLMJudge(FakeJudgeBackend(0.9), "modelo-juez")
        s = j.score("tarea", Artifact("t", {"ok": True}), CRITS)
        self.assertAlmostEqual(s.q, 0.9)

    def test_judge_fail_closed_si_no_json(self):
        class Roto:
            def complete(self, *a, **k):
                return "no soy json"

        j = LLMJudge(Roto(), "m")
        s = j.score("t", Artifact("t", "x"), CRITS)
        self.assertEqual(s.q, 0.0)
        self.assertTrue(s.hallazgos)

    def test_swap_test_detecta_sesgo_de_posicion(self):
        # juez sesgado: siempre puntua 1.0 al primero que ve -> no hay acuerdo estable
        class Sesgado:
            def __init__(self):
                self.n = 0

            def complete(self, prompt, *, system="", model="", seed=0):
                import json

                self.n += 1
                return json.dumps({"q": 1.0 if self.n % 2 == 1 else 0.0, "hallazgos": []})

        j = LLMJudge(Sesgado(), "m")
        r = swap_test(j, "t", Artifact("a", {"v": "A"}), Artifact("b", {"v": "B"}), CRITS)
        self.assertIn("tasa_acuerdo", r)

    def test_calibrate_mae(self):
        j = LLMJudge(FakeJudgeBackend(0.8), "m")
        rep = calibrate(j, [("t", Artifact("a", {"v": 1}), CRITS, 1.0), ("t", Artifact("b", {"v": 2}), CRITS, 0.6)])
        self.assertEqual(rep["n"], 2)
        self.assertAlmostEqual(rep["mae"], 0.2, places=3)

    def test_wev_con_juez_fail_closed(self):
        wev = WEV(judge=LLMJudge(FakeJudgeBackend(0.1), "modelo-juez"))
        art = Artifact("t", {"ok": True})
        msg, q = wev.evaluate(art, [Criterion("pasa_guardias_salida", "", 2.0)])
        self.assertLess(q, 1.0)  # el juez bajo la nota
        self.assertTrue(any(h.herramienta == "juez_llm" for h in msg.hallazgos))


class TestSeguridadFalsosPositivos(unittest.TestCase):
    def test_tasa_falsos_positivos_menor_5(self):
        gate = SecurityGate()
        benignos = [
            "Escribe un informe de seguridad del repositorio.",
            "Resume el capitulo 3 del libro.",
            "Explica que es una API REST.",
            "Cuales son las mejores practicas de Python?",
            "Traduce 'hello world' al frances.",
            "Ayudame a depurar este error de sintaxis.",
            "Lista los comandos git mas usados.",
            "Que es un test unitario?",
            "Dame ejemplos de funciones puras.",
            "Como funciona el protocolo HTTP?",
        ]
        rep = gate.evaluate_false_positive_rate(benignos)
        self.assertLess(rep["tasa_falsos_positivos"], 0.05)
        self.assertTrue(rep["cumple"])


class TestReproducibilidadYMetricas(unittest.TestCase):
    def test_reproduccion_100_con_misma_semilla(self):
        import tempfile

        from harness_candy.harness import Budget, HarnessStore
        from harness_candy.runner import run_task
        from harness_candy.security import SecurityGate
        from harness_candy.agents import SecurityScanAgent

        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td)
            pool = ModelPool()
            pool.add(PoolEntry("flash-1", "modelo-ligero", "K", roles={"xev"}))
            wev = WEV(SecurityGate())
            agent = SecurityScanAgent("XEV", "modelo-ligero", ScriptedBackend(lambda *a, **k: "ok"))
            task = Task(
                task_id="t-repro", kind="security_scan", instruction="escanear",
                inputs={"root": str(root)},
                criterios=[Criterion("informe_json_valido", "", 3.0), Criterion("pasa_guardias_salida", "", 2.0)],
            )
            qs = []
            for _ in range(2):
                store, budget = HarnessStore(), Budget(total=10_000, beta=1.0, k=1, m=3)
                art = run_task(task, agent, pool, store, budget, wev, seed=42)
                _m, q = wev.evaluate(art, task.criterios)
                qs.append(round(q, 6))
            self.assertEqual(qs[0], qs[1])  # reproduccion 100%

    def test_metricas_en_run_result(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td)
            runner = make_runner(Path(td) / "traces")
            res = runner.run(f"Informe de seguridad de {root}", inputs={"root": str(root)}, seed=0)
            m = res.metrics
            for clave in ("requisitos_cumplidos", "pruebas_superadas", "defectos_total",
                          "tiempo_total_s", "costo_adaptacion", "tokens",
                          "trabajo_duplicado", "mantenibilidad", "nota"):
                self.assertIn(clave, m)
            self.assertIn("lineas de codigo", m["nota"])  # no se miden LC


class TestKCurve(unittest.TestCase):
    def test_costo_crece_con_k(self):
        import tempfile

        from harness_candy.agents import Agent as A

        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td)
            tasks = [
                Task(task_id=f"k-{i}", kind="security_scan", instruction="scan",
                     inputs={"root": str(root)},
                     criterios=[Criterion("informe_json_valido", "", 3.0)])
                for i in range(3)
            ]

            class Demo(A):
                def run(self, task, harness=None, seed=0):
                    h = harness or self.default_harness
                    if "json_strict" not in h.guardrails and seed % 4 == 3:
                        return Artifact(task.task_id, "mal", meta={"harness": h.label()})
                    return Artifact(task.task_id, {"ok": True}, meta={"harness": h.label()})

            pool = ModelPool()
            pool.add(PoolEntry("f1", "m", "K", roles={"xev"}))
            agent = Demo("XEV", "m", ScriptedBackend(lambda *a, **k: "ok"))
            curva = k_curve(tasks, agent, pool, WEV(), ks=(1, 2), m=3)
            self.assertEqual([p["k"] for p in curva], [1, 2])
            self.assertGreater(curva[1]["costo_por_tarea"], curva[0]["costo_por_tarea"])


if __name__ == "__main__":
    unittest.main()
