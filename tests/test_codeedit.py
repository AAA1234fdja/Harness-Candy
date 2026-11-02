"""Tests de edicion estructurada de codigo (codeedit.py)."""
import ast
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.codeedit import (
    CodeEditError,
    DiffApplicationError,
    FileSpec,
    add_function,
    add_import,
    apply_unified_diff,
    generate_file_from_spec,
    generate_tests_for,
    parse_module,
    parse_unified_diff,
    remove_import,
    rename_function,
    set_function_body,
    validate_code,
)

SRC = "def f():\n    return 1\n"


class TestCodeEdit(unittest.TestCase):
    def test_parse_module_invalido(self):
        with self.assertRaises(CodeEditError):
            parse_module("def rota(:")

    def test_add_import(self):
        out = add_import(SRC, "os")
        self.assertIn("import os", out)
        ast.parse(out)

    def test_add_import_idempotente(self):
        out = add_import(add_import(SRC, "os"), "os")
        self.assertEqual(out.count("import os"), 1)

    def test_add_import_from(self):
        out = add_import(SRC, "pathlib", ["Path"])
        self.assertIn("from pathlib import Path", out)

    def test_remove_import(self):
        out = remove_import(add_import(SRC, "os"), "os")
        self.assertNotIn("import os", out)

    def test_add_function(self):
        out = add_function(SRC, "g", ["x"], "return x * 2", returns="int", docstring="duplica")
        ast.parse(out)
        self.assertIn("def g(x) -> int:", out)
        self.assertIn('"""duplica"""', out)
        tree = ast.parse(out)
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "g"][0]
        self.assertEqual(ast.unparse(fn.body[-1]), "return x * 2")

    def test_add_function_reemplaza(self):
        out = add_function(add_function(SRC, "g", ["x"], "return 1"), "g", ["x"], "return 2")
        self.assertEqual(out.count("def g("), 1)
        self.assertIn("return 2", out)

    def test_rename_function(self):
        src = "def g(x):\n    return x\n\nprint(g(1))\n"
        out = rename_function(src, "g", "h")
        self.assertIn("def h(x):", out)
        self.assertIn("h(1)", out)
        self.assertNotIn("g(1)", out)

    def test_rename_inexistente_lanza(self):
        with self.assertRaises(CodeEditError):
            rename_function(SRC, "nope", "x")

    def test_set_function_body_conserva_docstring(self):
        src = 'def f():\n    """doc"""\n    return 1\n'
        out = set_function_body(src, "f", "return 2")
        self.assertIn('"""doc"""', out)
        self.assertIn("return 2", out)

    def test_validate_code_ok(self):
        v = validate_code("def f():\n    return 1\n", compile_sandbox=False)
        self.assertTrue(v["ast_ok"])
        self.assertTrue(v["compile_ok"])
        self.assertIn("f", v["funciones"])

    def test_validate_code_falla(self):
        with self.assertRaises(CodeEditError):
            validate_code("def rota(:", compile_sandbox=False)

    def test_parse_unified_diff(self):
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,3 @@\n def f():\n-    return 1\n+    return 2\n"
        archivos = parse_unified_diff(diff)
        self.assertEqual(len(archivos), 1)
        old, new, hunks = archivos[0]
        self.assertEqual(old, "x.py")
        self.assertEqual(new, "x.py")
        self.assertEqual(len(hunks), 1)
        self.assertEqual(hunks[0].old_start, 1)

    def test_apply_unified_diff_ok(self):
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 2\n"
        out = apply_unified_diff(SRC, diff)
        self.assertIn("return 2", out)
        ast.parse(out)

    def test_apply_unified_diff_contexto_roto_rechaza(self):
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 99\n+    return 2\n"
        with self.assertRaises(DiffApplicationError):
            apply_unified_diff(SRC, diff)

    def test_apply_unified_diff_vacio_rechaza(self):
        with self.assertRaises(DiffApplicationError):
            apply_unified_diff(SRC, "")

    def test_apply_unified_diff_hunk_malformado(self):
        with self.assertRaises(DiffApplicationError):
            apply_unified_diff(SRC, "--- a/x\n+++ b/x\n@@ roto @@\n")

    def test_generate_file_from_spec(self):
        with tempfile.TemporaryDirectory() as td:
            spec = FileSpec(
                module="m",
                docstring="modulo demo",
                imports=["os"],
                from_imports={"pathlib": ["Path"]},
                functions=[{"name": "f", "args": ["x"], "body": "return x + 1", "returns": "int", "docstring": "suma"}],
            )
            p = generate_file_from_spec(Path(td) / "sub" / "m.py", spec)
            src = p.read_text(encoding="utf-8")
            ast.parse(src)
            self.assertIn("def f(x) -> int:", src)

    def test_generate_file_rechaza_spec_rota(self):
        with tempfile.TemporaryDirectory() as td:
            spec = FileSpec(module="m", functions=[{"name": "f", "args": [], "body": "return ("}])
            with self.assertRaises(CodeEditError):
                generate_file_from_spec(Path(td) / "m.py", spec)

    def test_generate_tests_for(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "mi_mod.py").write_text("def f():\n    return 1\ndef g():\n    return 2\n", encoding="utf-8")
            src = generate_tests_for(Path(td) / "mi_mod.py", ["f", "g"])
            ast.parse(src)
            self.assertIn("from mi_mod import f, g", src)
            self.assertIn("def test_f", src)
            self.assertIn("def test_g", src)


if __name__ == "__main__":
    unittest.main()
