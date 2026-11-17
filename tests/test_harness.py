import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.agents import Agent, Artifact, ScriptedBackend, Task
from harness_candy.harness import Budget, Harness, Harness2Adapter, HarnessStore, RuleBasedProposer
from harness_candy.quality import Criterion, score_q, TraceLog

CRITS = [Criterion("json", "", 2.0), Criterion("recs", "", 1.0)]


def make_task():
    return Task(task_id="t-1", kind="demo", instruction="hacer algo", criterios=CRITS)


class FakeAgent(Agent):
    """Agente determinista: Q depende de si el harness trae 'recs' y 'json'.

    Con guardrail 'json' y skill 'recs' -> siempre 1.0.
    Sin ellos -> 0.0 (ruido según semilla no aplica; Q estable por config).
    """

    def run(self, task, harness=None, seed=0):
        h = harness or self.default_harness
        ok_json = any("json" in g for g in h.guardrails)
        ok_recs = any(s.startswith("rec") for s in h.skills)
        content = {"json": ok_json, "recs": ok_recs}
        return Artifact(task.task_id, content, meta={"harness": h.label()})


def score(artifact, criterios):
    c = artifact.content if isinstance(artifact.content, dict) else {}
    cumplidos = [k for k in ("json", "recs") if c.get(k)]
    return score_q(criterios, cumplidos, [])


class TestHarness(unittest.TestCase):
    def test_eight_components_editable(self):
        h = Harness()
        for comp in ("system_prompt", "guardrails", "memory", "tool_guidance", "subagents", "skills", "scripts", "plugins"):
            self.assertTrue(hasattr(h, comp))

    def test_evolve_union_listas(self):
        h = Harness(guardrails=["a"])
        h2 = h.evolve(guardrails=["b"])
        self.assertEqual(h2.guardrails, ["a", "b"])
        self.assertEqual(h.guardrails, ["a"])  # inmutable

    def test_fingerprint_estable_y_distinto(self):
        h1 = Harness(system_prompt="x")
        h2 = Harness(system_prompt="y")
        self.assertEqual(h1.fingerprint(), h1.fingerprint())
        self.assertNotEqual(h1.fingerprint(), h2.fingerprint())


class TestStore(unittest.TestCase):
    def test_lookup_save_reutilizacion(self):
        with tempfile.TemporaryDirectory() as td:
            store = HarnessStore(Path(td) / "store.json")
            self.assertIsNone(store.lookup("k", "m"))
            h = Harness(skills=["recs"])
            store.save("k", "m", h, evidence={"q": [1.0]})
            self.assertEqual(store.lookup("k", "m").skills, ["recs"])
            self.assertGreater(store.reuse_rate(), 0.0)
            self.assertTrue((Path(td) / "store.json").exists())


class TestBudget(unittest.TestCase):
    def test_ecuacion3_cota(self):
        b = Budget(total=1000, beta=0.5, k=2, m=3)
        # (1+2k)*m*c = 5*3 = 15 por sondeo
        self.assertEqual(b.probe_cost(1.0), 15.0)
        self.assertTrue(b.allows_probe(1.0))
        # cota acumulada: (1-r) * n * 15 <= beta*B
        self.assertEqual(b.estimate_adapt_cost(10, reuse_rate=0.5, c_a=1.0), 75.0)
        self.assertLessEqual(b.estimate_adapt_cost(10, 0.5, 1.0), b.beta * b.total)

    def test_allows_probe_respeta_beta(self):
        b = Budget(total=100, beta=0.1, k=2, m=3)  # beta*B = 10 < 15
        self.assertFalse(b.allows_probe(1.0))

    def test_heuristica_justifica_sondeo(self):
        b = Budget(total=1000, beta=1.0, k=2, m=3)
        # E[dQ]*V > 2kmc -> 0.2*100=20 > 12
        self.assertTrue(b.justifies_probe(0.2, value_per_q=100, c_a=1.0))
        self.assertFalse(b.justifies_probe(0.01, value_per_q=1, c_a=1.0))


class TestAdaptadorPPC(unittest.TestCase):
    def setUp(self):
        self.agent = FakeAgent("xev", "modelo-x", ScriptedBackend(lambda *a, **k: "ok"), Harness())
        self.task = make_task()

    def test_propone_2k_candidatos(self):
        prop = RuleBasedProposer()
        cands = prop(self.agent.default_harness, "security_scan", k=2)
        self.assertEqual(len(cands), 4)  # 2 generales + 2 de dominio

    def test_adopta_cuando_mejora_sobre_ruido(self):
        # referencia mala (sin skills), candidatos con mejoras -> adopta
        # (candidato si gana uno solo, compuesto si ganan >=2: Compose fusiona)
        adapter = Harness2Adapter()
        h, ev = adapter.adapt(self.agent, self.task, k=2, m=3, score_fn=score, base_seed=0)
        self.assertIn(ev.adopted, ("candidato", "compuesto"))
        self.assertTrue(any("json" in g for g in h.guardrails))  # mejoro de verdad
        self.assertGreater(ev.cost, 0)
        self.assertEqual(ev.m, 3)
        self.assertEqual(ev.k, 2)
        self.assertEqual(len(ev.reference_scores), 3)
        self.assertEqual(len(ev.candidate_scores), 4)

    def test_conserva_referencia_si_no_supera_delta(self):
        # agente que ya puntua 1.0 con el harness por defecto: nada mejora
        class PerfectAgent(FakeAgent):
            def run(self, task, harness=None, seed=0):
                return Artifact(task.task_id, {"json": True, "recs": True}, meta={"harness": (harness or self.default_harness).label()})

        agent = PerfectAgent("xev", "m", ScriptedBackend(lambda *a, **k: "ok"), Harness(guardrails=["json"], skills=["recs"]))
        adapter = Harness2Adapter()
        h, ev = adapter.adapt(agent, self.task, k=2, m=3, score_fn=score)
        self.assertEqual(ev.adopted, "referencia")

    def test_costo_sondeo_es_1_mas_2k_por_m(self):
        # el adaptador ejecuta referencia + 2k candidatos, m veces cada uno
        calls = {"n": 0}

        class Counting(FakeAgent):
            def run(self, task, harness=None, seed=0):
                calls["n"] += 1
                return super().run(task, harness, seed)

        agent = Counting("xev", "m", ScriptedBackend(lambda *a, **k: "ok"), Harness())
        adapter = Harness2Adapter()
        adapter.adapt(agent, self.task, k=2, m=3, score_fn=score)
        self.assertEqual(calls["n"], (1 + 2 * 2) * 3)  # 15 corridas

    def test_trazas_registran_fases(self):
        with tempfile.TemporaryDirectory() as td:
            tl = TraceLog(Path(td) / "t.jsonl")
            adapter = Harness2Adapter(tracer=tl, run_id="r1")
            adapter.adapt(self.agent, self.task, k=1, m=3, score_fn=score)
            phases = {e["phase"] for e in tl.entries()}
            self.assertIn("reference", phases)
            self.assertIn("probe", phases)
            for e in tl.entries():
                self.assertIn("seed", e)
                self.assertIn("harness", e)


if __name__ == "__main__":
    unittest.main()
