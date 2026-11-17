"""Tests de la CLI (harness-candy ...): subcomandos y codigos de salida."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from helpers import make_repo

from harness_candy.cli import build_parser, main


def run_cli(argv):
    """Ejecuta la CLI capturando stdout/stderr; devuelve (exit_code, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class TestBasicos(unittest.TestCase):
    def test_version(self):
        code, out, _ = run_cli(["version"])
        self.assertEqual(code, 0)
        self.assertIn("harness-candy", out)

    def test_schemas_a_archivo(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "task.json"
            code, _, _ = run_cli(["schemas", "--name", "task", "--out", str(p)])
            self.assertEqual(code, 0)
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertIn("$schema_version", data)

    def test_validate_ok_e_invalido(self):
        with tempfile.TemporaryDirectory() as td:
            ok = Path(td) / "ok.json"
            ok.write_text(json.dumps({"task_id": "t", "kind": "k", "instruction": "i"}), encoding="utf-8")
            code, out, _ = run_cli(["validate", "--schema", "task", "--file", str(ok)])
            self.assertEqual(code, 0)
            self.assertIn("OK", out)
            malo = Path(td) / "malo.json"
            malo.write_text(json.dumps({"task_id": "t"}), encoding="utf-8")
            code, _, err = run_cli(["validate", "--schema", "task", "--file", str(malo)])
            self.assertEqual(code, 1)
            self.assertIn("INVALIDO", err)

    def test_validate_data_inline(self):
        code, out, _ = run_cli(["validate", "--schema", "budget", "--data", '{"total": 10}'])
        self.assertEqual(code, 0)

    def test_parser_tiene_todos_los_subcomandos(self):
        parser = build_parser()
        # cada subcomando queda registrado
        texto = parser.format_help()
        for cmd in ("version", "schemas", "validate", "run", "task", "suite", "golden", "report", "bench", "cache", "tools", "serve"):
            self.assertIn(cmd, texto)


class TestRunYReport(unittest.TestCase):
    def test_run_objetivo_generico_y_reporte(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td, with_secret=False)
            out_json = Path(td) / "run.json"
            out_html = Path(td) / "run.html"
            code, _, _ = run_cli([
                "run", "--objetivo", f"tarea demo sobre {root}",
                "--input", f"root={root}", "--seed", "0",
                "--trace-dir", str(Path(td) / "traces"),
                "--out", str(out_json), "--report", str(out_html),
            ])
            self.assertIn(code, (0, 2))  # 0 si todo done, 2 si algo no aprobado
            data = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertTrue(data["run_id"].startswith("run-"))
            self.assertIn("metrics", data)
            html = out_html.read_text(encoding="utf-8")
            self.assertIn(data["run_id"], html)

    def test_report_desde_run_guardado(self):
        with tempfile.TemporaryDirectory() as td:
            run = {"run_id": "run-0123456789ab", "objetivo": "o", "dag_results": {}, "duracion": 0.1, "metrics": {}}
            rp = Path(td) / "r.json"
            rp.write_text(json.dumps(run), encoding="utf-8")
            out = Path(td) / "r.xml"
            code, _, _ = run_cli(["report", "--run", str(rp), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("<testsuite", out.read_text(encoding="utf-8"))


class TestSuiteGoldenCacheTools(unittest.TestCase):
    def test_suite_list(self):
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "s.json"
            sp.write_text(json.dumps({
                "name": "s",
                "tasks": [{"task_id": "a", "kind": "security_scan", "instruction": "i", "deps": []}],
            }), encoding="utf-8")
            code, out, _ = run_cli(["suite", "list", "--file", str(sp)])
            self.assertEqual(code, 0)
            data = json.loads(out)
            self.assertEqual(data["tasks"][0]["task_id"], "a")

    def test_golden_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td, with_secret=False)
            gp = Path(td) / "g.json"
            gp.write_text(json.dumps({
                "name": "g", "min_pass_rate": 1.0,
                "cases": [{
                    "id": "c1",
                    "task": {"task_id": "s1", "kind": "security_scan", "instruction": "i",
                             "inputs": {"root": str(root)},
                             "criterios": [{"id": "informe_json_valido", "peso": 3.0}]},
                    "expect": {"veredicto": "aprobado"},
                }],
            }), encoding="utf-8")
            code, out, _ = run_cli(["golden", "--file", str(gp), "--trace-dir", str(Path(td) / "tr")])
            self.assertEqual(code, 0)  # pasa la puerta
            self.assertIn("golden OK", out)

    def test_cache_stats_y_clear(self):
        with tempfile.TemporaryDirectory() as td:
            cdir = Path(td) / "cache"
            cdir.mkdir()
            (cdir / "x.json").write_text('{"ts": 1, "response": "r"}', encoding="utf-8")
            code, out, _ = run_cli(["cache", "--dir", str(cdir)])
            self.assertEqual(code, 0)
            self.assertIn("entradas", out)
            code, out, _ = run_cli(["cache", "--dir", str(cdir), "--clear"])
            self.assertEqual(code, 0)
            self.assertIn("1 entradas", out)

    def test_tools(self):
        with tempfile.TemporaryDirectory() as td:
            outj = Path(td) / "tools.json"
            code, _, _ = run_cli(["tools", "--root", td, "--out", str(outj)])
            self.assertEqual(code, 0)
            nombres = [t["name"] for t in json.loads(outj.read_text())["tools"]]
            self.assertIn("echo", nombres)
            self.assertIn("read_file", nombres)


if __name__ == "__main__":
    unittest.main()
