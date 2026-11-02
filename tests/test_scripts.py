"""Tests de los scripts ejecutables scripts/harness2-* (via subprocess).

- harness2-setup: rc 0 y "SETUP OK".
- harness2-check --sin-tests: rc 0 y "CHECK OK" (compila + escaneo secretos).
- harness2-judge --max-cases 1: rc 0 con gate OK y rc 2 cuando el umbral es
  inalcanzable; guarda el reporte en el store.
- harness2-report: genera HTML y MD desde archivo JSON y desde run_id del store.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def correr(script: str, *args: str, timeout: int = 240) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True, text=True, cwd=REPO, timeout=timeout,
    )


class TestSetup(unittest.TestCase):
    def test_setup_ok(self):
        with tempfile.TemporaryDirectory() as td:
            r = correr("harness2-setup", "--quiet", "--store", str(Path(td) / "runs"), "--traces", str(Path(td) / "traces"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("SETUP OK", r.stdout)
            self.assertTrue((Path(td) / "runs").is_dir())
            self.assertTrue((Path(td) / "traces").is_dir())

    def test_setup_no_imprime_valores_de_env(self):
        import os
        env = dict(os.environ)
        env["XKIRO_API_KEY"] = "sk-test-valor-secreto-123456"
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "harness2-setup"), "--quiet"],
            capture_output=True, text=True, cwd=REPO, env=env, timeout=60,
        )
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("sk-test-valor-secreto-123456", r.stdout + r.stderr)


class TestCheck(unittest.TestCase):
    def test_check_sin_tests(self):
        r = correr("harness2-check", "--sin-tests", timeout=180)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("CHECK OK", r.stdout)
        self.assertIn("LIMPIO", r.stdout)  # escaneo de secretos


class TestJudge(unittest.TestCase):
    def test_judge_gate_ok_y_fallo(self):
        with tempfile.TemporaryDirectory() as td:
            store = f"json://{td}/runs"
            traces = str(Path(td) / "traces")
            r_ok = correr("harness2-judge", "--max-cases", "1", "--store", store, "--traces", traces, timeout=240)
            self.assertEqual(r_ok.returncode, 0, r_ok.stdout + r_ok.stderr)
            self.assertIn("gate_ok=True", r_ok.stdout)
            # el reporte quedo en el store
            archivos = list((Path(td) / "runs").glob("*.json"))
            self.assertTrue(archivos)
            # gate inalcanzable -> exit 2
            r_fail = correr("harness2-judge", "--max-cases", "1", "--min-pass-rate", "2.0", "--store", store, "--traces", traces, timeout=240)
            self.assertEqual(r_fail.returncode, 2)
            self.assertIn("GATE FALLO", r_fail.stderr)


class TestReport(unittest.TestCase):
    def _run_judge_sintetico(self, td: str) -> Path:
        run = {
            "run_id": "judge-test-1",
            "tipo": "judge",
            "golden": "test",
            "reporte": {
                "golden": "test", "total": 2, "passed": 1, "failed": 1,
                "pass_rate": 0.5, "min_pass_rate": 0.9, "gate_ok": False, "umbral_aplicado": 0.9,
                "results": [
                    {"case_id": "c1", "passed": True, "q": 0.9, "veredicto": "aprobado", "reasons": []},
                    {"case_id": "c2", "passed": False, "q": 0.3, "veredicto": "rechazado", "reasons": ["q baja"]},
                ],
            },
        }
        p = Path(td) / "run.json"
        p.write_text(json.dumps(run), encoding="utf-8")
        return p

    def test_report_desde_archivo_html_y_md(self):
        with tempfile.TemporaryDirectory() as td:
            run_path = self._run_judge_sintetico(td)
            out_html = Path(td) / "reporte.html"
            r = correr("harness2-report", "--run", str(run_path), "--out", str(out_html))
            self.assertEqual(r.returncode, 0, r.stderr)
            html = out_html.read_text(encoding="utf-8")
            self.assertIn("Judge: test", html)
            self.assertIn("FALLO", html)
            self.assertIn("c2", html)
            out_md = Path(td) / "reporte.md"
            r2 = correr("harness2-report", "--run", str(run_path), "--out", str(out_md))
            self.assertEqual(r2.returncode, 0)
            md = out_md.read_text(encoding="utf-8")
            self.assertIn("# Judge: test", md)
            self.assertIn("| `c2` |", md)

    def test_report_desde_run_id_del_store(self):
        with tempfile.TemporaryDirectory() as td:
            store_dir = Path(td) / "runs"
            store_dir.mkdir()
            run = {"run_id": "judge-abc-1", "tipo": "judge", "reporte": {
                "golden": "abc", "total": 1, "passed": 1, "failed": 0, "pass_rate": 1.0,
                "min_pass_rate": 0.9, "gate_ok": True, "umbral_aplicado": 0.9,
                "results": [{"case_id": "c1", "passed": True, "q": 1.0, "veredicto": "aprobado", "reasons": []}]}}
            (store_dir / "judge-abc-1.json").write_text(json.dumps(run), encoding="utf-8")
            out = Path(td) / "out.html"
            r = correr("harness2-report", "--run-id", "judge-abc-1", "--store", f"json://{store_dir}", "--out", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("judge-abc-1", out.read_text(encoding="utf-8"))
            # run_id inexistente -> rc 1
            r2 = correr("harness2-report", "--run-id", "no-existe", "--store", f"json://{store_dir}")
            self.assertEqual(r2.returncode, 1)

    def test_report_corrida_normal(self):
        with tempfile.TemporaryDirectory() as td:
            run = {
                "run_id": "run-normal-1",
                "dag_results": {"t1": {"status": "done", "attempts": 1, "duracion": 0.1}},
                "qs": {"t1": 0.9},
                "metrics": {"costo_total": 1.5},
            }
            p = Path(td) / "run.json"
            p.write_text(json.dumps(run), encoding="utf-8")
            out = Path(td) / "r.html"
            r = correr("harness2-report", "--run", str(p), "--out", str(out))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("run-normal-1", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
