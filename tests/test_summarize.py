"""Tests del resumen extractivo (summarize.py)."""
import unittest

import _path  # noqa: F401
from harness_candy.summarize import STOPWORDS_ES, Summary, resumen_por_parrafos, summarize

TEXTO = (
    "El harness evalua agentes con criterios ponderados. "
    "Los agentes ejecutan tareas dentro de un sandbox. "
    "La calidad se mide con la metrica q. "
    "El presupuesto limita el costo de adaptacion. "
    "Las claves API jamas van en el codigo. "
    "El sistema es determinista con semilla fija."
)


class TestSummarize(unittest.TestCase):
    def test_devuelve_summary(self):
        s = summarize(TEXTO, k=2)
        self.assertIsInstance(s, Summary)
        self.assertEqual(len(s.oraciones_seleccionadas), 2)
        self.assertTrue(s.texto)
        self.assertGreater(s.proporcion, 0)

    def test_orden_original(self):
        s = summarize(TEXTO, k=3)
        oraciones = [o.strip() for o in TEXTO.split(". ") if o.strip()]
        indices = [oraciones.index(o.rstrip(".")) if o.rstrip(".") in [x.rstrip(".") for x in oraciones] else -1 for o in s.oraciones_seleccionadas]
        # las seleccionadas deben respetar el orden del texto
        pos = [TEXTO.find(o) for o in s.oraciones_seleccionadas]
        self.assertEqual(pos, sorted(pos))

    def test_k_mayor_que_oraciones(self):
        s = summarize("Uno. Dos.", k=10)
        self.assertLessEqual(len(s.oraciones_seleccionadas), 2)

    def test_texto_corto_min_palabras(self):
        s = summarize("Hola.", k=1)
        self.assertEqual(len(s.oraciones_seleccionadas), 1)

    def test_to_dict(self):
        d = summarize(TEXTO, k=1).to_dict()
        self.assertIn("texto", d)
        self.assertIn("oraciones_seleccionadas", d)

    def test_stopwords_no_puntuan(self):
        self.assertIn("el", STOPWORDS_ES)
        self.assertIn("de", STOPWORDS_ES)

    def test_resumen_por_parrafos(self):
        texto = "Primero. Segundo.\n\nTercero. Cuarto."
        out = resumen_por_parrafos(texto, k_por_parrafo=1)
        self.assertIsInstance(out, str)
        self.assertTrue(out)

    def test_determinista(self):
        a = summarize(TEXTO, k=2).texto
        b = summarize(TEXTO, k=2).texto
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
