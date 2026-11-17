"""Tests de generacion de esqueletos (codegen.py)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.codegen import scaffold_agent, scaffold_project


class TestCodegen(unittest.TestCase):
    def test_scaffold_project(self):
        with tempfile.TemporaryDirectory() as td:
            files = scaffold_project(td, "mi-proy")
            esperadas = {"pyproject.toml", "README.md", "LICENSE", "agents.json", ".gitignore",
                         "src/mi_proy/__init__.py", "src/mi_proy/cli.py", "src/mi_proy/__main__.py",
                         "tests/test_smoke.py", ".github/workflows/ci.yml"}
            self.assertTrue(esperadas.issubset(set(files)))
            for rel, p in files.items():
                self.assertTrue(p.exists(), rel)
            pyproject = (Path(td) / "pyproject.toml").read_text(encoding="utf-8")
            self.assertIn('name = "mi-proy"', pyproject)
            agentes = json.loads((Path(td) / "agents.json").read_text(encoding="utf-8"))
            self.assertEqual(agentes["agents"][0]["name"], "XEV")

    def test_scaffold_nombre_invalido(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                scaffold_project(td, "Nombre_Mal!")
            with self.assertRaises(ValueError):
                scaffold_project(td, "1empieza-mal")

    def test_scaffold_proyecto_compila_y_pasa_smoke(self):
        with tempfile.TemporaryDirectory() as td:
            scaffold_project(td, "demo-proy")
            # compilar todos los .py generados
            for p in Path(td).rglob("*.py"):
                compile(p.read_text(encoding="utf-8"), str(p), "exec")
            # correr el test smoke con PYTHONPATH=src
            env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(td) / "src")}
            r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                               cwd=td, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-500:])

    def test_scaffold_cli_version(self):
        with tempfile.TemporaryDirectory() as td:
            scaffold_project(td, "demo-cli")
            env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(td) / "src")}
            r = subprocess.run([sys.executable, "-m", "demo_cli", "--version"], cwd=td, env=env,
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-300:])
            self.assertIn("0.1.0", r.stdout)

    def test_scaffold_agent(self):
        with tempfile.TemporaryDirectory() as td:
            scaffold_project(td, "pp")
            ag = scaffold_agent(td, "AG2", model="m2", roles=["zev"])
            self.assertEqual(ag["name"], "AG2")
            data = json.loads((Path(td) / "agents.json").read_text(encoding="utf-8"))
            self.assertEqual(len(data["agents"]), 2)
            with self.assertRaises(ValueError):
                scaffold_agent(td, "AG2")

    def test_scaffold_agent_sin_archivo_previo(self):
        with tempfile.TemporaryDirectory() as td:
            ag = scaffold_agent(td, "AG1")
            self.assertEqual(ag["name"], "AG1")
            self.assertTrue((Path(td) / "agents.json").exists())


if __name__ == "__main__":
    unittest.main()
