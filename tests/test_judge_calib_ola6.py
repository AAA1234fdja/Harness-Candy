"""Tests del juez calibrado (judge_calib.py, ola 6): pairwise, reference-guided, MAE, consenso, Elo."""
import json
import unittest

import _path  # noqa: F401
from harness_candy.agents import Artifact, ScriptedBackend
from harness_candy.judge_calib import (
    CalibratedJudge,
    TorneoElo,
    calibrar_juez,
    consenso,
    consenso_pares,
    reporte_calibracion_md,
)
from harness_candy.quality import Criterion

CRITS = [Criterion("c1", "claridad", 1.0)]
A_BUENO = Artifact("t", "respuesta buena y clara")
A_MALO = Artifact("t", "respuesta mala")


def backend_fake(prompt, system="", model="", seed=0):
    if "score_A" in prompt:
        return json.dumps({"score_A": 4.0, "score_B": 1.0, "razon": "A mejor"})
    if '"score"' in prompt:
        return json.dumps({"score": 3.0 if "buen" in prompt else 1.0, "razon": "x"})
    return json.dumps({"q": 0.8 if "buen" in prompt else 0.2, "hallazgos": []})


class TestModos(unittest.TestCase):
    def setUp(self):
        self.j = CalibratedJudge(ScriptedBackend(backend_fake), nombre="j1")

    def test_single(self):
        self.assertEqual(self.j.single("t", A_BUENO, CRITS).score, 3.0)
        self.assertEqual(self.j.single("t", A_MALO, CRITS).score, 1.0)

    def test_pairwise(self):
        pw = self.j.pairwise("t", A_BUENO, A_MALO, CRITS)
        self.assertEqual(pw.ganador, "A")
        self.assertEqual((pw.score_a, pw.score_b), (4.0, 1.0))
        self.assertIn(pw.sesgo_posicion, (0.0, 1.0))
        json.dumps(pw.to_dict())

    def test_reference_guided(self):
        v = self.j.reference_guided("t", A_BUENO, "respuesta gold", CRITS)
        self.assertEqual(v.score, 3.0)
        self.assertEqual(v.juez, "j1")

    def test_fail_closed(self):
        j = CalibratedJudge(ScriptedBackend(lambda *a, **k: "no json"), nombre="roto")
        self.assertEqual(j.single("t", A_BUENO, CRITS).score, 0.0)
        pw = j.pairwise("t", A_BUENO, A_MALO, CRITS)
        self.assertEqual(pw.ganador, "empate")


class TestCalibracion(unittest.TestCase):
    def test_mae_sesgo_dominios(self):
        j = CalibratedJudge(ScriptedBackend(backend_fake), nombre="j1")
        samples = [
            ("t", A_BUENO, CRITS, 3.0, "qa"),
            ("t", A_MALO, CRITS, 1.0, "qa"),
            ("t", A_BUENO, CRITS, 5.0, "estilo"),  # el juez da 3, humano 5 -> error 2
        ]
        rep = calibrar_juez(j, samples)
        self.assertEqual(rep.n, 3)
        self.assertAlmostEqual(rep.mae, 2 / 3, places=3)
        self.assertIn("qa", rep.por_dominio)
        self.assertAlmostEqual(rep.por_dominio["qa"]["mae"], 0.0)
        self.assertGreaterEqual(rep.correlacion, 0.0)
        md = reporte_calibracion_md(rep)
        self.assertIn("# Calibracion del juez: j1", md)
        self.assertIn("| qa |", md)
        json.dumps(rep.to_dict())

    def test_sin_muestras(self):
        j = CalibratedJudge(ScriptedBackend(backend_fake), nombre="j")
        rep = calibrar_juez(j, [])
        self.assertEqual(rep.n, 0)


class TestConsenso(unittest.TestCase):
    def test_acuerdo_total(self):
        j = CalibratedJudge(ScriptedBackend(backend_fake), nombre="j1")
        votos = [j.single("t", A_BUENO, CRITS) for _ in range(3)]
        c = consenso(votos)
        self.assertEqual(c["acuerdo"], 1.0)
        self.assertEqual(c["media"], 3.0)

    def test_consenso_vacio(self):
        c = consenso([])
        self.assertEqual(c["n"], 0)

    def test_consenso_pares(self):
        js = []
        for i in range(3):
            def mk(i=i):
                def fn(prompt, system="", model="", seed=0):
                    if "score_A" in prompt:
                        return json.dumps({"score_A": 4.0 if i == 0 else 1.0, "score_B": 1.0 if i == 0 else 4.0, "razon": "x"})
                    return json.dumps({"q": 0.5, "hallazgos": []})
                return fn
            js.append(CalibratedJudge(ScriptedBackend(mk()), nombre=f"j{i}"))
        cp = consenso_pares(js, "t", A_BUENO, A_MALO, CRITS)
        self.assertEqual(sum(cp["conteo"].values()), 3)
        self.assertIn(cp["ganador_consenso"], ("A", "B", "empate"))
        with self.assertRaises(ValueError):
            consenso_pares([], "t", A_BUENO, A_MALO, CRITS)


class TestElo(unittest.TestCase):
    def test_partida_y_tabla(self):
        t = TorneoElo(k=32)
        t.partida("flash", "opus", "A")
        self.assertGreater(t.entradas["flash"].rating, 1000)
        self.assertLess(t.entradas["opus"].rating, 1000)
        t.partida("flash", "opus", "B")
        t.partida("flash", "opus", "empate")
        tabla = t.tabla()
        self.assertEqual(len(tabla), 2)
        self.assertTrue(all("elo" in e and "winrate" in e for e in tabla))
        json.dumps(t.to_dict())
        # el que gano mas va primero
        t2 = TorneoElo()
        for _ in range(5):
            t2.partida("a", "b", "A")
        self.assertEqual(t2.tabla()[0]["nombre"], "a")


if __name__ == "__main__":
    unittest.main()
