"""Tests del motor de plantillas (templates.py)."""
import unittest

import _path  # noqa: F401
from harness_candy.templates import TemplateError, compile_template, render_file, render_string


class TestTemplates(unittest.TestCase):
    def test_interpolacion_basica(self):
        self.assertEqual(render_string("Hola {{ nombre }}!", nombre="Ada"), "Hola Ada!")

    def test_filtros(self):
        self.assertEqual(render_string("{{ x | upper }}", x="abc"), "ABC")
        self.assertEqual(render_string("{{ x | lower }}", x="ABC"), "abc")
        self.assertEqual(render_string("{{ x | trim }}", x="  hola  "), "hola")
        self.assertEqual(render_string("{{ xs | length }}", xs=[1, 2, 3]), "3")
        self.assertEqual(render_string("{{ d | tojson }}", d={"a": 1}), '{"a": 1}')
        self.assertEqual(render_string("{{ xs | join(' - ') }}", xs=["a", "b"]), "a - b")
        self.assertEqual(render_string("{{ x | default('vacio') }}", x=""), "vacio")
        self.assertEqual(render_string("{{ x | int }}", x="42"), "42")
        self.assertEqual(render_string("{{ x | float }}", x="1.5"), "1.5")

    def test_filtros_encadenados(self):
        self.assertEqual(render_string("{{ x | trim | upper }}", x="  ab "), "AB")

    def test_for(self):
        self.assertEqual(render_string("{% for x in xs %}{{ x }},{% endfor %}", xs=[1, 2, 3]), "1,2,3,")
        self.assertEqual(render_string("{% for x in xs %}{{ x }}{% endfor %}", xs=[]), "")

    def test_if_else(self):
        self.assertEqual(render_string("{% if ok %}SI{% else %}NO{% endif %}", ok=True), "SI")
        self.assertEqual(render_string("{% if ok %}SI{% else %}NO{% endif %}", ok=False), "NO")

    def test_set(self):
        self.assertEqual(render_string("{% set y = x + 1 %}{{ y }}", x=4), "5")

    def test_comentario(self):
        self.assertEqual(render_string("a{# esto no sale #}b"), "ab")

    def test_for_if_anidados(self):
        tpl = "{% for x in xs %}{% if x > 1 %}{{ x }}{% endif %}{% endfor %}"
        self.assertEqual(render_string(tpl, xs=[1, 2, 3]), "23")

    def test_expresion_aritmetica(self):
        self.assertEqual(render_string("{{ a * b }}", a=3, b=4), "12")

    def test_filtro_desconocido_lanza(self):
        with self.assertRaises(TemplateError):
            render_string("{{ x | noexiste }}", x=1)

    def test_bloque_sin_cerrar_lanza(self):
        with self.assertRaises(TemplateError):
            compile_template("{% for x in xs %}sin endfor")

    def test_sentencia_desconocida_lanza(self):
        with self.assertRaises(TemplateError):
            compile_template("{% rom hack %}")

    def test_render_es_reutilizable(self):
        f = compile_template("{{ x }}")
        self.assertEqual(f(x=1), "1")
        self.assertEqual(f(x=2), "2")

    def test_render_file(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.txt"
            p.write_text("Valor: {{ v }}", encoding="utf-8")
            self.assertEqual(render_file(p, v=7), "Valor: 7")

    def test_builtins_desactivados_en_expresiones(self):
        with self.assertRaises(Exception):
            render_string("{{ __import__('os') }}", )


if __name__ == "__main__":
    unittest.main()
