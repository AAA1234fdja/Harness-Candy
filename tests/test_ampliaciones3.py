"""Tests del lote 7: planner verificar/niveles, diffengine complejidad/arboles, viz charts, crypto PBKDF2."""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.crypto import clave_desde_env, derive_key
from harness_candy.diffengine import ast_diff_detallado, complejidad_ciclomatica, diff_arboles
from harness_candy.planner import Operator, Plan, Planner, PlanningError
from harness_candy.viz import heatmap, line_chart


def _ops():
    return [
        Operator("a", effects=("x",)),
        Operator("b", preconditions=("x",), effects=("y",)),
        Operator("c", preconditions=("x",), effects=("z",)),
        Operator("top", subtasks=("a", "b", "c"), preconditions=("y", "z"), effects=("fin",)),
    ]


class TestPlannerAmpliado(unittest.TestCase):
    def test_verificar_plan_ok(self):
        pl = Planner(_ops())
        p = pl.plan("top", set())
        ok, estado = pl.verificar_plan(p, set())
        self.assertTrue(ok)
        self.assertIn("y", estado)

    def test_verificar_plan_invalido(self):
        pl = Planner([Operator("necesita", preconditions=("falta",), effects=("e",))])
        ok, _ = pl.verificar_plan(Plan(goal="necesita", pasos=["necesita"]), set())
        self.assertFalse(ok)

    def test_verificar_paso_desconocido(self):
        pl = Planner(_ops())
        ok, _ = pl.verificar_plan(Plan(goal="top", pasos=["nope"]), set())
        self.assertFalse(ok)

    def test_niveles(self):
        pl = Planner(_ops())
        niv = pl.niveles("top", set())
        self.assertEqual(niv[0], ["a"])
        self.assertEqual(sorted(niv[1]), ["b", "c"])

    def test_niveles_no_paralelizable(self):
        ops = [Operator("a", preconditions=("x",), effects=("y",)), Operator("top", subtasks=("a",), preconditions=("y",), effects=("f",))]
        with self.assertRaises(PlanningError):
            Planner(ops).niveles("top", set())

    def test_estimate_cost(self):
        self.assertEqual(Planner(_ops()).estimate_cost("top", set()), 3.0)


class TestDiffEngineAmpliado(unittest.TestCase):
    def test_complejidad(self):
        cc = complejidad_ciclomatica("def f(x):\n    if x:\n        return 1\n    for i in range(3):\n        print(i)\n    return 0\n")
        self.assertGreaterEqual(cc["f"], 3)

    def test_ast_diff_detallado(self):
        d = ast_diff_detallado("def f(x):\n    if x: return 1\n", "def f(x):\n    if x: return 1\n    while x: x -= 1\n")
        mod = d["funciones_modificadas"][0]
        self.assertEqual(mod["cc_delta"], 1)
        self.assertEqual(d["complejidad_total_despues"] - d["complejidad_total_antes"], 1)

    def test_diff_arboles(self):
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            (Path(t1) / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            (Path(t1) / "igual.py").write_text("X = 1\n", encoding="utf-8")
            (Path(t2) / "m.py").write_text("def f():\n    return 2\n", encoding="utf-8")
            (Path(t2) / "igual.py").write_text("X = 1\n", encoding="utf-8")
            (Path(t2) / "nuevo.py").write_text("def g():\n    return 0\n", encoding="utf-8")
            (Path(t1) / "viejo.py").write_text("Y = 2\n", encoding="utf-8")
            out = diff_arboles(t1, t2)
            self.assertEqual(out["m.py"]["estado"], "cambiado")
            self.assertEqual(out["igual.py"]["estado"], "igual")
            self.assertEqual(out["nuevo.py"]["estado"], "anadido")
            self.assertEqual(out["viejo.py"]["estado"], "eliminado")


class TestVizAmpliado(unittest.TestCase):
    def test_line_chart(self):
        out = line_chart([1, 3, 2, 5, 4], ancho=20, alto=6)
        self.assertIn("•", out)
        self.assertIn("min=1 max=5 n=5", out)
        self.assertEqual(line_chart([]), "")

    def test_heatmap(self):
        out = heatmap([[0, 1], [2, 3]])
        filas = out.splitlines()
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0][0], " ")
        self.assertEqual(filas[1][-1], "@")
        self.assertEqual(heatmap([]), "")


class TestCryptoAmpliado(unittest.TestCase):
    def test_derive_key(self):
        k1, s1 = derive_key("pw")
        k2, s2 = derive_key("pw")
        self.assertNotEqual(s1, s2)  # salt aleatorio
        self.assertEqual(derive_key("pw", salt=s1)[0], k1)  # determinista con salt fija
        self.assertEqual(len(k1), 32)

    def test_clave_desde_env(self):
        k = clave_desde_env("MI_CLAVE_TEST", environ={"MI_CLAVE_TEST": "secreto"})
        self.assertEqual(len(k), 32)
        with self.assertRaises(RuntimeError):
            clave_desde_env("NO_EXISTE_TEST_XYZ", environ={})


if __name__ == "__main__":
    unittest.main()
