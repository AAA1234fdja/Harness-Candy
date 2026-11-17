"""Tests del bench de latencia (percentiles)."""
import time
import unittest

import _path  # noqa: F401
from harness_candy.latencia import bench_latencia, comparar_latencias, percentiles


class TestPercentiles(unittest.TestCase):
    def test_valores_conocidos(self):
        vals = list(range(1, 101))  # 1..100
        p = percentiles(vals)
        self.assertAlmostEqual(p["p50"], 50.5)
        self.assertAlmostEqual(p["p90"], 90.1)
        self.assertAlmostEqual(p["p95"], 95.05)
        self.assertAlmostEqual(p["p99"], 99.01)

    def test_un_valor(self):
        p = percentiles([7.0])
        self.assertEqual(p["p50"], 7.0)
        self.assertEqual(p["p99"], 7.0)

    def test_vacio_error(self):
        with self.assertRaises(ValueError):
            percentiles([])


class TestBenchLatencia(unittest.TestCase):
    def test_mide_duraciones(self):
        llamadas = {"n": 0}

        def fn():
            llamadas["n"] += 1
            time.sleep(0.001)
            return "ok"

        r = bench_latencia(fn, n=10, warmup=2)
        self.assertEqual(llamadas["n"], 12)
        self.assertEqual(r["n"], 10)
        self.assertGreaterEqual(r["media_s"], 0.001)
        self.assertLessEqual(r["min_s"], r["media_s"])
        self.assertGreaterEqual(r["max_s"], r["media_s"])
        self.assertIn("p50", r)
        self.assertIn("p95", r)
        self.assertIn("p99", r)
        self.assertEqual(r["resultado_ejemplo"], "ok")

    def test_determinismo_con_fn_pura(self):
        # fn sin efecto secundario: las metricas dependen solo de n
        r = bench_latencia(lambda: sum(range(100)), n=5, warmup=0)
        self.assertEqual(r["n"], 5)
        # total ~= media * n (el redondeo a 4/6 decimales puede morder un poco)
        self.assertAlmostEqual(r["total_s"], r["media_s"] * 5, places=3)

    def test_n_invalido(self):
        with self.assertRaises(ValueError):
            bench_latencia(lambda: None, n=0)


class TestComparar(unittest.TestCase):
    def test_delta(self):
        antes = {"media_s": 1.0, "p95": 2.0}
        despues = {"media_s": 0.5, "p95": 1.0}
        c = comparar_latencias(antes, despues)
        self.assertEqual(c["delta_media_pct"], -50.0)
        self.assertTrue(c["mejora"])
        self.assertEqual(c["p95_despues_s"], 1.0)

    def test_empeora(self):
        c = comparar_latencias({"media_s": 1.0}, {"media_s": 2.0})
        self.assertEqual(c["delta_media_pct"], 100.0)
        self.assertFalse(c["mejora"])

    def test_media_cero(self):
        c = comparar_latencias({"media_s": 0.0}, {"media_s": 1.0})
        self.assertEqual(c["delta_media_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
