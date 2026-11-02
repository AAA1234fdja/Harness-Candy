"""Tests de i18n (i18n.py) y viz (viz.py)."""
import unittest

import _path  # noqa: F401
from harness_candy.i18n import MESSAGES, agregar_mensajes, detectar_idioma, idiomas, t
from harness_candy.viz import bar_chart, histogram, progress_bar, resumen_serie, sparkline, table_html, tarjeta_html


class TestI18n(unittest.TestCase):
    def test_idiomas(self):
        self.assertIn("es", idiomas())
        self.assertIn("en", idiomas())

    def test_t_basico(self):
        self.assertEqual(t("es", "ok"), "correcto")
        self.assertEqual(t("en", "ok"), "ok")

    def test_t_interpola(self):
        self.assertEqual(t("es", "run_ok", run_id="r1", duracion=2, q=1.0), "corrida r1 completada en 2s con q=1.0")
        self.assertEqual(t("en", "run_ok", run_id="r1", duracion=2, q=1.0), "run r1 completed in 2s with q=1.0")

    def test_t_fallback(self):
        self.assertEqual(t("fr", "ok"), "correcto")  # fallback es
        self.assertEqual(t("es", "clave_inexistente"), "clave_inexistente")

    def test_t_ctx_faltante_no_rompe(self):
        out = t("es", "run_ok", run_id="r1")  # faltan duracion/q
        self.assertIsInstance(out, str)

    def test_detectar_idioma(self):
        self.assertEqual(detectar_idioma("the cat and the dog are in the house"), "en")
        self.assertEqual(detectar_idioma("el perro y el gato estan en la casa"), "es")
        self.assertEqual(detectar_idioma(""), "otro")
        self.assertEqual(detectar_idioma("123 456"), "otro")

    def test_agregar_mensajes(self):
        agregar_mensajes("de", {"ok": "okay"})
        self.assertEqual(t("de", "ok"), "okay")
        self.assertIn("de", idiomas())
        # no pisa es/en
        self.assertEqual(t("es", "ok"), "correcto")


class TestViz(unittest.TestCase):
    def test_sparkline(self):
        sp = sparkline([1, 5, 2, 8])
        self.assertEqual(len(sp), 4)
        self.assertEqual(sparkline([]), "")
        self.assertEqual(sparkline([3, 3, 3]), "▄▄▄")

    def test_bar_chart(self):
        out = bar_chart(["a", "bb"], [1, 2], ancho=10)
        lineas = out.splitlines()
        self.assertEqual(len(lineas), 2)
        self.assertIn("█", lineas[1])
        self.assertIn("2", lineas[1])
        with self.assertRaises(ValueError):
            bar_chart(["a"], [1, 2])
        self.assertEqual(bar_chart([], []), "")

    def test_histogram(self):
        out = histogram([0.1, 0.2, 0.9, 1.0, 0.5], bins=2)
        self.assertIn("[", out)
        self.assertIn("█", out)
        self.assertEqual(histogram([], bins=3), "")
        self.assertIn("█", histogram([5, 5, 5], bins=2))

    def test_progress_bar(self):
        self.assertIn("50%", progress_bar(50))
        self.assertIn("100%", progress_bar(100))
        self.assertIn("0%", progress_bar(-5))
        self.assertIn("100%", progress_bar(150))

    def test_table_html(self):
        h = table_html(["a", "b"], [["<x>", 1], ["y", 2]])
        self.assertIn("<table", h)
        self.assertIn("&lt;x&gt;", h)
        self.assertIn("<th>a</th>", h)

    def test_resumen_serie(self):
        r = resumen_serie("q", [0.5, 0.7, 0.9, 1.0])
        self.assertIn("q:", r)
        self.assertIn("media=", r)
        self.assertEqual(resumen_serie("vacia", []), "vacia: sin datos")

    def test_tarjeta_html(self):
        c = tarjeta_html("Titulo", "<p>hola</p>")
        self.assertIn("hc-card", c)
        self.assertIn("Titulo", c)


if __name__ == "__main__":
    unittest.main()
