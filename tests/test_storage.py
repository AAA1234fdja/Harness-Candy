"""Tests de los stores de corridas: JSON en disco y SQLite (stdlib)."""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.storage import JsonRunStore, SqliteRunStore, open_store


def run(i, objetivo="obj", status="done"):
    return {
        "run_id": f"run-{i:012d}",
        "objetivo": objetivo,
        "duracion": 0.1 * i,
        "dag_results": {"t": {"status": status}},
        "metrics": {"i": i},
    }


class BaseStoreTests:
    """Contrato comun que debe cumplir cualquier RunStore."""

    def make_store(self, td):
        raise NotImplementedError

    def test_save_get_count(self):
        with tempfile.TemporaryDirectory() as td:
            s = self.make_store(td)
            s.save(run(1))
            s.save(run(2, objetivo="otro", status="escalated"))
            self.assertEqual(s.count(), 2)
            r = s.get("run-" + f"{1:012d}")
            self.assertEqual(r["objetivo"], "obj")
            self.assertIsNone(s.get("run-999999999999"))

    def test_list_limit_y_filtro_status(self):
        with tempfile.TemporaryDirectory() as td:
            s = self.make_store(td)
            for i in range(1, 6):
                s.save(run(i, status="escalated" if i % 2 else "done"))
            todos = s.list(limit=100)
            self.assertEqual(len(todos), 5)
            self.assertEqual(len(s.list(limit=2)), 2)
            esc = s.list(limit=100, status="escalated")
            self.assertEqual(len(esc), 3)  # i impar: 1, 3, 5

    def test_delete(self):
        with tempfile.TemporaryDirectory() as td:
            s = self.make_store(td)
            s.save(run(1))
            self.assertTrue(s.delete("run-" + f"{1:012d}"))
            self.assertFalse(s.delete("run-" + f"{1:012d}"))
            self.assertEqual(s.count(), 0)

    def test_sobrescribe_mismo_run_id(self):
        with tempfile.TemporaryDirectory() as td:
            s = self.make_store(td)
            s.save(run(1, objetivo="v1"))
            s.save(run(1, objetivo="v2"))
            self.assertEqual(s.count(), 1)
            self.assertEqual(s.get("run-" + f"{1:012d}")["objetivo"], "v2")


class TestJsonStore(BaseStoreTests, unittest.TestCase):
    def make_store(self, td):
        return JsonRunStore(Path(td) / "runs")

    def test_run_id_con_slash_se_sanitiza(self):
        with tempfile.TemporaryDirectory() as td:
            s = JsonRunStore(td)
            s.save({"run_id": "run-malo/../../x", "objetivo": "o", "dag_results": {}})
            self.assertTrue((Path(td) / "run-malo_.._.._x.json").exists())


class TestSqliteStore(BaseStoreTests, unittest.TestCase):
    def make_store(self, td):
        return SqliteRunStore(Path(td) / "runs.db")

    def test_persiste_en_disco(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "runs.db"
            s = SqliteRunStore(db)
            s.save(run(7))
            # reabrir desde el mismo archivo
            s2 = SqliteRunStore(db)
            self.assertEqual(s2.count(), 1)
            self.assertEqual(s2.get("run-" + f"{7:012d}")["metrics"]["i"], 7)


class TestOpenStore(unittest.TestCase):
    def test_urls(self):
        self.assertIsInstance(open_store("json://x"), JsonRunStore)
        self.assertIsInstance(open_store("sqlite://x.db"), SqliteRunStore)
        self.assertIsInstance(open_store("algo.db"), SqliteRunStore)
        self.assertIsInstance(open_store("una/ruta"), JsonRunStore)


if __name__ == "__main__":
    unittest.main()
