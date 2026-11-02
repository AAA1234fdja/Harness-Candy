"""Tests del grafo dirigido (graph.py)."""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.graph import CycleError, DiGraph, dependencias_a_grafo


class TestGraph(unittest.TestCase):
    def test_topo_sort(self):
        g = DiGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_edge("a", "c")
        orden = g.topo_sort()
        self.assertEqual(orden, ["a", "b", "c"])

    def test_ciclo(self):
        g = DiGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "a")
        self.assertTrue(g.hay_ciclo())
        with self.assertRaises(CycleError):
            g.topo_sort()

    def test_niveles_y_paralelismo(self):
        g = DiGraph()
        g.add_edge("a", "b")
        g.add_edge("a", "c")
        g.add_edge("b", "d")
        g.add_edge("c", "d")
        niveles = g.niveles()
        self.assertEqual(niveles["a"], 0)
        self.assertEqual(niveles["d"], 2)
        self.assertEqual(g.max_paralelismo(), 2)
        ancho = g.ancho_por_nivel()
        self.assertEqual(ancho[0], 1)
        self.assertEqual(ancho[1], 2)

    def test_critical_path(self):
        g = DiGraph()
        g.add_edge("a", "b", 1.0)
        g.add_edge("b", "d", 5.0)
        g.add_edge("a", "c", 2.0)
        g.add_edge("c", "d", 2.0)
        camino, costo = g.critical_path()
        self.assertEqual(camino, ["a", "b", "d"])
        self.assertEqual(costo, 6.0)

    def test_alcanzables(self):
        g = DiGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        g.add_edge("x", "y")
        self.assertEqual(g.alcanzables("a"), {"a", "b", "c"})

    def test_predecesores_sucesores(self):
        g = DiGraph()
        g.add_edge("a", "b", 2.0)
        self.assertEqual(g.sucesores("a"), {"b": 2.0})
        self.assertEqual(g.predecesores("b"), {"a": 2.0})
        self.assertEqual(g.grado_entrada("b"), 1)

    def test_persistencia(self):
        with tempfile.TemporaryDirectory() as td:
            g = DiGraph()
            g.add_edge("a", "b", 3.0)
            p = Path(td) / "g.json"
            g.save(p)
            g2 = DiGraph.load(p)
            self.assertEqual(g2.sucesores("a"), {"b": 3.0})
            d = json.loads(p.read_text(encoding="utf-8"))
            self.assertIn("edges", d)

    def test_dependencias_a_grafo(self):
        g = dependencias_a_grafo({"t2": ["t1"], "t3": ["t1", "t2"], "t1": []})
        self.assertEqual(g.topo_sort(), ["t1", "t2", "t3"])

    def test_grafo_vacio(self):
        g = DiGraph()
        self.assertEqual(g.topo_sort(), [])
        self.assertEqual(g.critical_path(), ([], 0.0))
        self.assertEqual(g.max_paralelismo(), 0)


if __name__ == "__main__":
    unittest.main()
