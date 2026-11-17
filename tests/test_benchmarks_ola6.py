"""Tests del evaluador multi-benchmark local (benchmarks.py, ola 6)."""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.benchmarks import (
    BenchmarkCase,
    BenchmarkSuite,
    benchmark_card,
    comparar_modelos,
    construir_prompt,
    evaluation_card,
    export_olmes,
    load_benchmark,
    puntuar_caso,
    reporte_benchmark_md,
    run_benchmark,
    suites_desde_directorio,
)


def suite_mini():
    return BenchmarkSuite("mini", min_pass_rate=0.5, casos=[
        BenchmarkCase("q1", "mcq", "2+2?", opciones=["3", "4"], esperada=1, dominio="mates",
                      few_shot=[{"prompt": "1+1?", "respuesta": "B"}]),
        BenchmarkCase("q2", "mcq", "Capital?", opciones=["Madrid", "Paris"], esperada="B", dominio="geo"),
        BenchmarkCase("q3", "abierto", "nombra un lenguaje", patron=r"python|rust", dominio="codigo"),
    ])


class TestCasos(unittest.TestCase):
    def test_prompt_few_shot_y_opciones(self):
        c = suite_mini().casos[0]
        p = construir_prompt(c, 1)
        self.assertIn("1+1?", p)
        self.assertIn("A) 3", p)
        self.assertIn("B) 4", p)
        self.assertIn("Responde SOLO con la letra", p)

    def test_tipo_invalido(self):
        with self.assertRaises(ValueError):
            BenchmarkCase.from_dict({"id": "x", "tipo": "raro"})

    def test_puntuar_mcq_letra_e_indice(self):
        c = suite_mini().casos[0]
        self.assertTrue(puntuar_caso(c, "B")[0])
        self.assertTrue(puntuar_caso(c, "La respuesta es B")[0])
        self.assertFalse(puntuar_caso(c, "A")[0])
        c2 = suite_mini().casos[1]
        self.assertTrue(puntuar_caso(c2, "B")[0])

    def test_puntuar_abierto_patron(self):
        c = suite_mini().casos[2]
        self.assertTrue(puntuar_caso(c, "python es util")[0])
        self.assertFalse(puntuar_caso(c, "java nomas")[0])

    def test_puntuar_codigo_en_sandbox(self):
        c = BenchmarkCase("c", "codigo", "f suma", test_code="assert f(2,3)==5\nprint('ok')", expected_stdout="ok")
        ok, det = puntuar_caso(c, "```python\ndef f(a,b):\n    return a+b\n```")
        self.assertTrue(ok, det)
        ok2, _ = puntuar_caso(c, "```python\ndef f(a,b):\n    return a-b\n```")
        self.assertFalse(ok2)


class TestRunBenchmark(unittest.TestCase):
    def test_seeds_passk_gate_dominios(self):
        def fake(p):
            if "2+2" in p: return "B"
            if "Capital" in p: return "B"
            return "python"
        rep = run_benchmark(suite_mini(), fake, modelo="fake", seeds=(0, 1), k=2)
        self.assertEqual(rep.total, 6)
        self.assertEqual(rep.passed, 6)
        self.assertEqual(rep.pass_rate, 1.0)
        self.assertTrue(rep.gate_ok)
        self.assertEqual(set(rep.por_seed), {0, 1})
        self.assertEqual(set(rep.por_dominio), {"mates", "geo", "codigo"})
        self.assertGreaterEqual(rep.pass_at_k, rep.pass_at_1)
        json.dumps(rep.to_dict())

    def test_gate_falla_con_modelo_malo(self):
        rep = run_benchmark(suite_mini(), lambda p: "X", seeds=(0,))
        self.assertEqual(rep.passed, 0)
        self.assertFalse(rep.gate_ok)

    def test_ejecutar_no_callable(self):
        with self.assertRaises(TypeError):
            run_benchmark(suite_mini(), "no-callable")

    def test_caso_que_explota_no_tumba(self):
        def boom(p):
            if "Capital" in p: raise RuntimeError("explotó")
            return "B"
        rep = run_benchmark(suite_mini(), boom, seeds=(0,))
        self.assertEqual(rep.total, 3)
        self.assertEqual(rep.passed, 1)  # solo q1 pasa; q2 explota y q3 no matchea patron


class TestCardsInterop(unittest.TestCase):
    def test_benchmark_card_y_evaluation_card(self):
        rep = run_benchmark(suite_mini(), lambda p: "B" if "2+2" in p or "Capital" in p else "python", modelo="m1", seeds=(0,))
        card = benchmark_card(suite_mini(), rep, git_commit="abc")
        self.assertEqual(card["schema"], "harness-candy/benchmark-card")
        self.assertEqual(card["metric"]["name"], "pass_rate")
        self.assertEqual(card["git_commit"], "abc")
        ec = evaluation_card(rep)
        self.assertEqual(len(ec["casos"]), rep.total)
        ol = export_olmes(rep, modelo="m1")
        self.assertIn("pass@1", ol["metricas"])
        for d in (card, ec, ol):
            json.dumps(d)

    def test_comparar_modelos(self):
        comp = comparar_modelos({"bueno": lambda p: "B" if "2+2" in p or "Capital" in p else "python",
                                  "malo": lambda p: "A"}, suite_mini(), seeds=(0,))
        self.assertEqual(comp["referencia"], "bueno")
        self.assertIn("malo", comp["comparacion_vs_referencia"])
        self.assertLess(comp["comparacion_vs_referencia"]["malo"]["delta_pass_rate"], 0)
        json.dumps(comp)

    def test_reporte_md(self):
        rep = run_benchmark(suite_mini(), lambda p: "B", seeds=(0,))
        md = reporte_benchmark_md(rep)
        self.assertIn("# Benchmark: mini", md)
        self.assertIn("| mates |", md)


class TestPersistencia(unittest.TestCase):
    def test_guardar_cargar_y_directorio(self):
        with tempfile.TemporaryDirectory() as td:
            suite_mini().guardar(Path(td) / "a.json")
            BenchmarkSuite("otra", casos=[]).guardar(Path(td) / "b.json")
            s2 = load_benchmark(Path(td) / "a.json")
            self.assertEqual(s2.name, "mini")
            self.assertEqual(len(s2.casos), 3)
            ss = suites_desde_directorio(td)
            self.assertEqual(set(ss), {"mini", "otra"})

    def test_suites_ejemplo_del_repo(self):
        ss = suites_desde_directorio(Path(__file__).resolve().parents[1] / "benchmarks")
        self.assertIn("mini-mmlu-es", ss)
        self.assertIn("swe-mini", ss)
        self.assertEqual(len(ss["mini-mmlu-es"].casos), 10)


if __name__ == "__main__":
    unittest.main()
