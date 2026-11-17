"""Tests de QA de codigo (qatest.py, ola 6): mutation AST, mutation sobre diff, fuzz/PBT, mantenibilidad."""
import ast
import json
import random
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.qatest import (
    OPERADORES,
    MutationError,
    funciones_cambiadas,
    fuzz_funcion,
    metricas_mantenibilidad,
    metricas_proyecto,
    mutar_fuente,
    run_mutation,
    run_mutation_diff,
)

SRC = "def suma(a, b):\n    if a > 0:\n        return a + b\n    return b - 1\n"


class TestMutacion(unittest.TestCase):
    def test_cada_operador_genera_mutante_compilable(self):
        vistos = set()
        for op in OPERADORES:
            try:
                codigo, desc = mutar_fuente(SRC, "suma", op, rng=random.Random(1))
                ast.parse(codigo)
                vistos.add(op)
            except MutationError:
                pass
        self.assertGreaterEqual(len(vistos), 4)

    def test_errores(self):
        with self.assertRaises(MutationError):
            mutar_fuente(SRC, "no_existe", "aor")
        with self.assertRaises(ValueError):
            mutar_fuente(SRC, "suma", "operador-raro")

    def test_run_mutation_score(self):
        def tests(fn):
            return fn(2, 3) == 5 and fn(-1, 3) == 2
        rep = run_mutation(SRC, "suma", tests, seed=1, max_mutantes=12)
        self.assertGreaterEqual(rep.total, 4)
        self.assertGreater(rep.muertos, 0)
        self.assertLessEqual(rep.score, 1.0)
        d = rep.to_dict()
        json.dumps(d)
        self.assertEqual(d["total"], rep.total)

    def test_tests_fallidos_en_original(self):
        with self.assertRaises(MutationError):
            run_mutation(SRC, "suma", lambda fn: False)

    def test_mutation_sobre_diff(self):
        antes = "def f(x):\n    return x + 1\n\ndef g(x):\n    return x\n"
        despues = "def f(x):\n    return x + 2\n\ndef g(x):\n    return x\n"
        self.assertEqual(funciones_cambiadas(antes, despues), ["f"])
        self.assertEqual(funciones_cambiadas(antes, antes), [])
        reps = run_mutation_diff(antes, despues, lambda fn: fn(1) == 3, max_mutantes=4, seed=0)
        self.assertEqual(len(reps), 1)
        self.assertEqual(reps[0].funcion, "f")
        self.assertGreaterEqual(reps[0].total, 1)


class TestFuzz(unittest.TestCase):
    def test_hallazgo_y_reproducibilidad(self):
        def doble(x):
            if x == 7:
                raise ValueError("bug en 7")
            return x * 2
        def gen(rng):
            return rng.randint(0, 20)
        prop = lambda i, o: o == i + i
        r1 = fuzz_funcion(doble, gen, prop, n=100, seed=3, nombre="doble")
        r2 = fuzz_funcion(doble, gen, prop, n=100, seed=3)
        self.assertEqual([h.input for h in r1.hallazgos], [h.input for h in r2.hallazgos])
        self.assertIn(7, [h.input for h in r1.hallazgos])
        self.assertEqual(r1.n_ejecuciones, 100)
        json.dumps(r1.to_dict())

    def test_corpus_regresion(self):
        def doble(x):
            if x == 7:
                raise ValueError("bug")
            return x * 2
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "corpus.json"
            rep = fuzz_funcion(doble, lambda rng: rng.randint(0, 20), lambda i, o: o == i + i,
                               n=50, seed=3, guardar_en=p)
            datos = json.loads(p.read_text())
            self.assertEqual(datos["funcion"], "doble")
            self.assertGreaterEqual(len(datos["regresiones"]), 1)
            self.assertEqual(rep.corpus_path, str(p))

    def test_validacion_callables(self):
        with self.assertRaises(TypeError):
            fuzz_funcion("no", lambda r: 1, lambda i, o: True)


class TestMantenibilidad(unittest.TestCase):
    def test_metricas_archivo(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "mod.py"
            f.write_text(SRC + "\ndef otra(x):\n    if x:\n        if x > 1:\n            return x\n    return 0\n")
            m = metricas_mantenibilidad(f)
            self.assertEqual(m.loc, len(f.read_text().splitlines()))
            self.assertEqual(m.funciones, 2)
            self.assertGreaterEqual(m.complejidad_max, 1)
            json.dumps(m.to_dict())

    def test_metricas_proyecto(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.py").write_text(SRC)
            (Path(td) / "b.py").write_text("def h(x):\n    return x\n")
            proj = metricas_proyecto(td)
            self.assertEqual(proj["archivos"], 2)
            self.assertGreater(proj["loc_total"], 0)
            self.assertIn("problematicos", proj)


if __name__ == "__main__":
    unittest.main()
