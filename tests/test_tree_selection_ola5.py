"""Tests del arbol de candidatos y la seleccion estadistica (quinta ola)."""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.selection import CandidateScore, SelectionResult, seleccionar_adoptado
from harness_candy.tree import HarnessTree, TreeNode


class TestHarnessTree(unittest.TestCase):
    def _arbol(self):
        t = HarnessTree("h0", 0.5)
        c1 = t.add_candidate("cand-1", 0.8)
        t.add_candidate("sub-1", 0.9, parent_id=c1.id)
        t.add_candidate("cand-2", 0.7)
        return t, c1

    def test_estructura(self):
        t, c1 = self._arbol()
        self.assertEqual(t.ancho, 4)
        self.assertEqual(t.profundidad, 2)
        self.assertEqual(t.root, "root")
        self.assertEqual(t.best(1)[0].harness_label, "sub-1")
        self.assertEqual(t.best(2)[1].harness_label, "cand-1")

    def test_path_to(self):
        t, c1 = self._arbol()
        camino = t.path_to(t.best(1)[0].id)
        self.assertEqual([n.harness_label for n in camino], ["h0", "cand-1", "sub-1"])
        with self.assertRaises(KeyError):
            t.path_to("no-existe")

    def test_padre_desconocido(self):
        t = HarnessTree()
        with self.assertRaises(KeyError):
            t.add_candidate("x", 0.1, parent_id="fantasma")

    def test_podar(self):
        t, _ = self._arbol()
        n = t.podar(0.75)
        self.assertGreaterEqual(n, 1)
        self.assertTrue(all(node.score >= 0.75 or node.id == "root" for node in t.nodes.values()))

    def test_ascii(self):
        t, _ = self._arbol()
        s = t.ascii()
        self.assertIn("h0", s)
        self.assertIn("sub-1", s)

    def test_save_load(self):
        t, _ = self._arbol()
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "tree.json"
            t.save(p)
            json.loads(p.read_text(encoding="utf-8"))  # JSON valido
            t2 = HarnessTree.load(p)
            self.assertEqual(t2.ancho, 4)
            self.assertEqual(t2.root, "root")
            self.assertEqual(t2.best(1)[0].score, 0.9)
            self.assertEqual(t2.profundidad, 2)

    def test_update_score(self):
        t, c1 = self._arbol()
        t.update_score(c1.id, 0.99)
        self.assertEqual(t.best(1)[0].id, c1.id)


class TestSeleccionarAdoptado(unittest.TestCase):
    def test_elige_candidato_mejor(self):
        sel = seleccionar_adoptado(
            [0.5, 0.5, 0.5],
            [CandidateScore("c1", [0.9, 0.95, 0.85]), CandidateScore("c2", [0.5, 0.51, 0.49])],
            n_boot=300,
        )
        self.assertIsInstance(sel, SelectionResult)
        self.assertEqual(sel.label_ganador, "c1")
        self.assertFalse(sel.es_referencia)
        self.assertGreater(sel.delta, 0)
        self.assertLessEqual(sel.ic95[0], sel.ic95[1])
        json.dumps(sel.to_dict())

    def test_empate_vuelve_a_referencia(self):
        sel = seleccionar_adoptado([0.5, 0.5, 0.5], [CandidateScore("c2", [0.5, 0.51, 0.49])], n_boot=300)
        self.assertTrue(sel.es_referencia)

    def test_referencia_vacia_error(self):
        with self.assertRaises(ValueError):
            seleccionar_adoptado([], [CandidateScore("c1", [0.9])])

    def test_detalle_por_candidato(self):
        sel = seleccionar_adoptado([0.5, 0.5], [CandidateScore("a", [0.7, 0.7]), CandidateScore("b", [0.6, 0.6])], n_boot=100)
        labels = {d["label"] for d in sel.detalle}
        self.assertEqual(labels, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
