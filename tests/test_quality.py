import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.protocols import Hallazgo
from harness_candy.quality import (
    Criterion,
    RegressionGuard,
    TraceLog,
    compose_delta,
    score_q,
    should_adopt,
)

CRITS = [Criterion("a", "", 1.0), Criterion("b", "", 3.0)]


class TestScoreQ(unittest.TestCase):
    def test_todos_cumplidos_q1(self):
        self.assertEqual(score_q(CRITS, ["a", "b"], []), 1.0)

    def test_ninguno_cumplido_q0(self):
        self.assertEqual(score_q(CRITS, [], []), 0.0)

    def test_pesos(self):
        # cumple solo el de peso 1 sobre total 4 -> 0.25
        self.assertAlmostEqual(score_q(CRITS, ["a"], []), 0.25)

    def test_penalizacion_severidad(self):
        q = score_q(CRITS, ["a", "b"], [Hallazgo("linter", "media", "x")])
        self.assertAlmostEqual(q, 0.80)

    def test_clamp_a_cero(self):
        q = score_q(CRITS, ["a", "b"], [Hallazgo("w", "critica", "x"), Hallazgo("w", "alta", "y")])
        self.assertEqual(q, 0.0)

    def test_en_rango_01(self):
        q = score_q(CRITS, ["a"], [Hallazgo("w", "baja", "x")])
        self.assertTrue(0.0 <= q <= 1.0)
        self.assertAlmostEqual(q, 0.25 - 0.05)


class TestReglaEstadistica(unittest.TestCase):
    def test_mejora_grande_se_adopta(self):
        ref = [0.5, 0.5, 0.5, 0.5, 0.5]
        cand = [0.9, 0.9, 0.9, 0.9, 0.9]
        self.assertTrue(should_adopt(ref, cand))

    def test_ruido_no_se_adopta(self):
        ref = [0.50, 0.52, 0.48, 0.51, 0.49]
        cand = [0.51, 0.53, 0.49, 0.52, 0.50]
        self.assertFalse(should_adopt(ref, cand))

    def test_m_minimo_3(self):
        # con m >= 3 corridas la regla funciona; m distinto lanza error
        with self.assertRaises(ValueError):
            should_adopt([0.5, 0.5], [0.6, 0.6, 0.6])

    def test_delta_crece_con_ruido(self):
        quieto_ref = [0.5, 0.5, 0.5]
        ruidoso_ref = [0.3, 0.7, 0.5]
        d1 = compose_delta(quieto_ref, [0.6, 0.6, 0.6])
        d2 = compose_delta(ruidoso_ref, [0.6, 0.6, 0.6])
        self.assertGreater(d2, d1)


class TestTraceLog(unittest.TestCase):
    def test_jsonl_campos_requeridos(self):
        with tempfile.TemporaryDirectory() as td:
            tl = TraceLog(Path(td) / "run.jsonl")
            tl.record(run_id="r1", task_id="t1", model="m", seed=3, harness="0.1#abc", phase="probe", q=0.7)
            entries = tl.entries()
            self.assertEqual(len(entries), 1)
            for f in TraceLog.REQUIRED_FIELDS:
                self.assertIn(f, entries[0])
            # linea valida JSON
            line = (Path(td) / "run.jsonl").read_text().strip().splitlines()[0]
            self.assertEqual(json.loads(line)["run_id"], "r1")


class TestRegresion(unittest.TestCase):
    def test_alerta_caida_mayor_2pp(self):
        g = RegressionGuard()
        g.set_baseline("t1", 0.90)
        alert = g.check("t1", 0.85)  # -5 pp
        self.assertIsNotNone(alert)
        self.assertGreater(alert.caida_pp, 2.0)

    def test_sin_alerta_dentro_de_banda(self):
        g = RegressionGuard()
        g.set_baseline("t1", 0.90)
        self.assertIsNone(g.check("t1", 0.89))  # -1 pp
        self.assertTrue(g.is_success("t1", 0.89))  # dentro de banda 3%
        self.assertFalse(g.is_success("t1", 0.80))

    def test_update_baseline_no_empeora(self):
        g = RegressionGuard()
        g.set_baseline("t1", 0.9)
        g.update_baseline("t1", 0.8)  # no debe bajar la referencia
        self.assertEqual(g.baseline["t1"], 0.9)
        g.update_baseline("t1", 0.95)
        self.assertEqual(g.baseline["t1"], 0.95)


if __name__ == "__main__":
    unittest.main()
