"""Tests del registro de herramientas tipadas (defineTool propio, v3 §5.3)."""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.tools import (
    RateLimitError,
    ToolError,
    ToolNotFound,
    ToolRegistry,
    ToolSpec,
    ToolValidationError,
    default_registry,
)


class TestToolSpec(unittest.TestCase):
    def test_permiso_invalido(self):
        with self.assertRaises(ToolError):
            ToolSpec(name="x", description="d", parameters={}, permission="admin")

    def test_sin_handler_ni_command(self):
        with self.assertRaises(ToolError):
            ToolSpec(name="x", description="d", parameters={}, permission="read")

    def test_nombre_fuera_de_pattern(self):
        with self.assertRaises(Exception):
            ToolSpec(name="MAL!", description="d", parameters={}, permission="read", handler=lambda a: a)


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
        (self.root / "README.md").write_text("# hola\n", encoding="utf-8")
        self.reg = default_registry(self.root)

    def tearDown(self):
        self.td.cleanup()

    def test_catalogo_y_describe(self):
        nombres = self.reg.names()
        self.assertIn("echo", nombres)
        self.assertIn("read_file", nombres)
        d = self.reg.describe("echo")
        self.assertEqual(d["permission"], "read")
        self.assertEqual(len(self.reg.catalog()), len(nombres))

    def test_echo_ok(self):
        out = self.reg.call("echo", {"text": "hola"})
        self.assertEqual(out, {"echo": "hola"})

    def test_herramienta_desconocida(self):
        with self.assertRaises(ToolNotFound):
            self.reg.call("no_existe", {})

    def test_args_invalidos_rechazados_antes_de_ejecutar(self):
        with self.assertRaises(ToolValidationError):
            self.reg.call("echo", {"otro": 1})  # falta 'text'
        with self.assertRaises(ToolValidationError):
            self.reg.call("echo", {"text": "ok", "extra": 1})  # additionalProperties false

    def test_permiso_denegado(self):
        with self.assertRaises(PermissionError):
            self.reg.call("py_compile", {"path": "src/a.py"}, allowed={"read"})

    def test_rate_limit(self):
        spec = ToolSpec(
            name="lenta",
            description="d",
            parameters={"type": "object"},
            permission="read",
            handler=lambda a: "ok",
            rate_limit=1,
            rate_window_s=3600,
        )
        self.reg.register(spec)
        self.assertEqual(self.reg.call("lenta", {}), "ok")
        with self.assertRaises(RateLimitError):
            self.reg.call("lenta", {})

    def test_read_file_dentro_del_root(self):
        out = self.reg.call("read_file", {"path": "README.md"})
        self.assertIn("hola", out["content"])

    def test_read_file_fuera_del_root_bloqueado(self):
        with self.assertRaises(PermissionError):
            self.reg.call("read_file", {"path": "../secreto.txt"})

    def test_list_files_con_sufijo(self):
        out = self.reg.call("list_files", {"suffix": ".py"})
        self.assertEqual(out["files"], ["src/a.py"])
        out2 = self.reg.call("list_files", {})
        self.assertEqual(sorted(out2["files"]), ["README.md", "src/a.py"])

    def test_py_compile_en_sandbox(self):
        out = self.reg.call("py_compile", {"path": "src/a.py"}, allowed={"read", "write", "exec"})
        self.assertEqual(out["returncode"], 0)
        self.assertIn("network_isolated", out)

    def test_auditoria_registra_ok_y_error(self):
        self.reg.call("echo", {"text": "a"})
        try:
            self.reg.call("echo", {"mal": 1})
        except ToolValidationError:
            pass
        log = self.reg.audit_log()
        self.assertEqual(len(log), 2)
        self.assertTrue(log[0]["ok"])
        self.assertFalse(log[1]["ok"])
        self.assertIn("invalidos", log[1]["error"])
        self.assertEqual(log[0]["tool"], "echo")

    def test_permisos_por_defecto_todos(self):
        # default_permissions = read|write|exec
        out = self.reg.call("py_compile", {"path": "src/a.py"})
        self.assertEqual(out["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
