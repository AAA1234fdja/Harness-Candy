"""Tests de estadistica propia (stats.py)."""
import math
import unittest

import _path  # noqa: F401
from harness_candy.stats import (
    anova_oneway,
    bootstrap_ci,
    chi2_contingencia,
    chi2_sf,
    describe,
    ic_media,
    ic_proporcion_wilson,
    iqr,
    kendall_tau,
    mean,
    median,
    normal_cdf,
    pearson,
    percentil,
    spearman,
    stdev,
    t_sf,
    variance,
)


class TestStats(unittest.TestCase):
    def test_descriptiva(self):
        xs = [1, 2, 3, 4, 5]
        self.assertEqual(mean(xs), 3.0)
        self.assertEqual(median(xs), 3.0)
        self.assertAlmostEqual(variance(xs), 2.5)
        self.assertAlmostEqual(stdev(xs), math.sqrt(2.5))
        self.assertEqual(percentil(0, xs), 1)
        self.assertEqual(percentil(100, xs), 5)
        self.assertEqual(percentil(50, xs), 3)
        self.assertAlmostEqual(iqr(xs), 2.0)
        d = describe(xs)
        self.assertEqual(d["n"], 5)
        self.assertEqual(d["min"], 1)
        self.assertEqual(d["max"], 5)

    def test_errores_vacio(self):
        with self.assertRaises(ValueError):
            mean([])
        with self.assertRaises(ValueError):
            percentil(50, [])
        with self.assertRaises(ValueError):
            variance([1])
        with self.assertRaises(ValueError):
            percentil(101, [1])

    def test_correlaciones(self):
        x = [1, 2, 3, 4, 5]
        y = [2, 4, 6, 8, 10]
        self.assertAlmostEqual(pearson(x, y), 1.0)
        self.assertAlmostEqual(spearman(x, y), 1.0)
        self.assertAlmostEqual(kendall_tau(x, y), 1.0)
        self.assertAlmostEqual(pearson(x, [5, 4, 3, 2, 1]), -1.0)
        with self.assertRaises(ValueError):
            pearson([1], [1])

    def test_normal_cdf(self):
        self.assertAlmostEqual(normal_cdf(0), 0.5)
        self.assertGreater(normal_cdf(1.96), 0.97)
        self.assertLess(normal_cdf(-1.96), 0.03)

    def test_chi2_sf(self):
        # chi2 con 1 gl: P(X > 3.841) ~= 0.05
        self.assertAlmostEqual(chi2_sf(3.841, 1), 0.05, places=3)
        self.assertEqual(chi2_sf(0, 1), 1.0)

    def test_t_sf(self):
        # t con gl grande se acerca a normal: P(T>1.96) ~= 0.025
        self.assertAlmostEqual(t_sf(1.96, 10_000), 0.025, places=3)

    def test_ic_media(self):
        xs = [10, 12, 11, 13, 9, 10, 12, 11]
        lo, hi = ic_media(xs, 0.05)
        self.assertLess(lo, mean(xs))
        self.assertGreater(hi, mean(xs))
        lo1, hi1 = ic_media([5.0], 0.05)
        self.assertEqual(lo1, hi1)

    def test_ic_proporcion_wilson(self):
        lo, hi = ic_proporcion_wilson(8, 10, 0.05)
        self.assertLess(lo, 0.8)
        self.assertGreater(hi, 0.8)
        self.assertGreaterEqual(lo, 0.0)
        self.assertLessEqual(hi, 1.0)
        lo0, hi0 = ic_proporcion_wilson(0, 0)
        self.assertEqual((lo0, hi0), (0.0, 1.0))

    def test_chi2_contingencia(self):
        # tabla independiente -> chi2 ~ 0, p alto
        r = chi2_contingencia([[10, 10], [10, 10]])
        self.assertAlmostEqual(r["chi2"], 0.0)
        self.assertGreater(r["p"], 0.9)
        # tabla dependiente -> chi2 alto, p bajo
        r2 = chi2_contingencia([[50, 5], [5, 50]])
        self.assertGreater(r2["chi2"], 50)
        self.assertLess(r2["p"], 0.001)
        self.assertEqual(r2["gl"], 1)

    def test_anova(self):
        g1 = [1.0, 2.0, 3.0]
        g2 = [10.0, 11.0, 12.0]
        r = anova_oneway([g1, g2])
        self.assertGreater(r["F"], 50)
        self.assertLess(r["p"], 0.01)
        r2 = anova_oneway([[1.0, 2.0], [1.5, 2.5]])
        self.assertGreater(r2["p"], 0.3)
        with self.assertRaises(ValueError):
            anova_oneway([[1.0]])

    def test_bootstrap_ci(self):
        datos = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        lo, med, hi = bootstrap_ci(datos, mean, n_boot=500, alpha=0.05, seed=0)
        self.assertLess(lo, 5.5)
        self.assertGreater(hi, 5.5)
        self.assertAlmostEqual(med, 5.5, delta=1.5)
        with self.assertRaises(ValueError):
            bootstrap_ci([])

    def test_bootstrap_determinista(self):
        a = bootstrap_ci([1, 2, 3, 4], mean, n_boot=100, seed=7)
        b = bootstrap_ci([1, 2, 3, 4], mean, n_boot=100, seed=7)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
