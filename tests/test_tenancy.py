"""Tests de multi-tenancy: namespaces por tenant con validacion anti-traversal."""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.storage import JsonRunStore, SqliteRunStore
from harness_candy.tenancy import InvalidTenant, TenantManager, validate_tenant


class TestValidateTenant(unittest.TestCase):
    def test_nombres_validos(self):
        for n in ("a", "proyecto-a", "equipo1", "x" * 32):
            self.assertEqual(validate_tenant(n), n)

    def test_nombres_invalidos(self):
        for n in ("", "../etc", "A", "con espacio", "con_slash/", "-empieza-guion", "x" * 33, "../..", "a;b"):
            with self.assertRaises(InvalidTenant):
                validate_tenant(n)


class TestTenantManager(unittest.TestCase):
    def test_stores_aislados(self):
        with tempfile.TemporaryDirectory() as td:
            tm = TenantManager(td)
            sa = tm.store("proyecto-a")
            sb = tm.store("proyecto-b")
            self.assertIsInstance(sa, JsonRunStore)
            sa.save({"run_id": "run-000000000001", "objetivo": "a", "dag_results": {}})
            self.assertEqual(sa.count(), 1)
            self.assertEqual(sb.count(), 0)  # aislado
            self.assertEqual(tm.tenants(), ["proyecto-a", "proyecto-b"])

    def test_sqlite_por_tenant(self):
        with tempfile.TemporaryDirectory() as td:
            tm = TenantManager(td)
            s = tm.store("proyecto-a", backend="sqlite")
            self.assertIsInstance(s, SqliteRunStore)
            s.save({"run_id": "run-000000000002", "objetivo": "x", "dag_results": {}})
            self.assertEqual(s.count(), 1)

    def test_trace_dir_creado(self):
        with tempfile.TemporaryDirectory() as td:
            tm = TenantManager(td)
            d = tm.trace_dir("proyecto-a")
            self.assertTrue(d.is_dir())
            self.assertIn("proyecto-a", str(d))

    def test_traversal_rechazado(self):
        with tempfile.TemporaryDirectory() as td:
            tm = TenantManager(td)
            with self.assertRaises(InvalidTenant):
                tm.store("../escapa")
            with self.assertRaises(InvalidTenant):
                tm.trace_dir("..")


if __name__ == "__main__":
    unittest.main()
