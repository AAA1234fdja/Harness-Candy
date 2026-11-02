"""Tests de recursion task-level (parallel/sequential) + reflection (quinta ola)."""
import json
import unittest

import _path  # noqa: F401
from harness_candy.agents import ScriptedBackend
from harness_candy.harness import AdaptationEvidence, Harness
from harness_candy.memory import KnowledgeMemory
from harness_candy.recursion import (
    PARALLEL,
    SEQUENTIAL,
    RecursionResult,
    reflection_post_adopcion,
    run_recursion,
)


def evidencia():
    return AdaptationEvidence(
        reference_scores=[0.5, 0.6],
        candidate_scores={"c1": [0.8, 0.9]},
        adopted="candidato",
        adopted_harness="c1",
        delta=0.3,
        k=2,
        m=2,
        cost=10.0,
    )


class TestRunRecursion(unittest.TestCase):
    def test_sequential_acumula_contexto(self):
        res = run_recursion(["a", "b", "c"], lambda o, ctx: (ctx.get("ultimo_resultado") or "") + o, modo=SEQUENTIAL)
        self.assertIsInstance(res, RecursionResult)
        self.assertEqual(res.modo, SEQUENTIAL)
        self.assertEqual([s.detalle for s in res.sub_resultados], ["a", "ab", "abc"])
        self.assertEqual(res.agregado, "abc")
        self.assertTrue(all(s.ok for s in res.sub_resultados))
        self.assertTrue(res.run_id)

    def test_parallel_no_comparte_estado(self):
        res = run_recursion(["x", "y", "z"], lambda o, ctx: ctx["indice"], modo=PARALLEL, max_workers=3)
        self.assertEqual(res.modo, PARALLEL)
        self.assertEqual({s.detalle for s in res.sub_resultados}, {0, 1, 2})
        self.assertEqual(res.agregado["n_ok"], 3)
        self.assertEqual(len(res.agregado["resultados"]), 3)

    def test_modo_invalido(self):
        with self.assertRaises(ValueError):
            run_recursion(["a"], lambda o, c: 1, modo="raro")

    def test_fallo_de_un_subobjetivo_no_tumba(self):
        def ej(o, ctx):
            if o == "malo":
                raise RuntimeError("boom")
            return o
        res = run_recursion(["ok1", "malo", "ok2"], ej, modo=SEQUENTIAL)
        oks = [s for s in res.sub_resultados if s.ok]
        malos = [s for s in res.sub_resultados if not s.ok]
        self.assertEqual(len(oks), 2)
        self.assertEqual(len(malos), 1)
        self.assertIn("boom", malos[0].detalle)

    def test_to_dict_jsonable(self):
        res = run_recursion(["a"], lambda o, c: {"x": 1}, modo=SEQUENTIAL)
        json.dumps(res.to_dict())  # no debe lanzar


class TestReflection(unittest.TestCase):
    def test_reflection_guarda_en_memoria(self):
        backend = ScriptedBackend(
            lambda p, system="", model="", seed=0: json.dumps(
                {"reflexion": "el candidato c1 mejoro en seguridad", "recomendacion": "subir k", "nivel_confianza": 0.8}
            )
        )
        mem = KnowledgeMemory()
        out = reflection_post_adopcion(backend, run_id="r1", evidence=evidencia(), harness_adoptado=Harness(), memory=mem)
        self.assertEqual(out["reflexion"], "el candidato c1 mejoro en seguridad")
        self.assertEqual(len(mem._entries), 1)
        self.assertIn("r1", mem._entries[0].content)

    def test_reflection_fail_closed_sin_llm(self):
        backend = ScriptedBackend(lambda *a, **k: "no es json")
        mem = KnowledgeMemory()
        out = reflection_post_adopcion(backend, run_id="r2", evidence=evidencia(), harness_adoptado=Harness(), memory=mem)
        self.assertIn("determinista", out["reflexion"])
        self.assertEqual(len(mem._entries), 1)  # igual guarda algo trazable

    def test_reflection_sin_memoria_no_falla(self):
        backend = ScriptedBackend(lambda *a, **k: json.dumps({"reflexion": "x", "recomendacion": "y"}))
        out = reflection_post_adopcion(backend, run_id="r3", evidence=evidencia(), harness_adoptado=Harness())
        self.assertEqual(out["reflexion"], "x")


if __name__ == "__main__":
    unittest.main()
