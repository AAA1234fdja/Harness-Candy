"""Tests del servidor HTTP local: API REST (health, runs, suite, golden, schemas, tools)."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import _path  # noqa: F401
from helpers import make_repo

from harness_candy import __version__
from harness_candy.server import make_server


def request(base, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read().decode("utf-8")


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        td = Path(cls.td.name)
        cls.root = make_repo(str(td), with_secret=False)
        cls.base = td
        cls.server = make_server("127.0.0.1", 0, store=f"json://{td}/runs", trace_dir=td / "traces", base_dir=td)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.td.cleanup()

    def test_health(self):
        status, ct, body = request(self.base_url, "GET", "/health")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["version"], __version__)

    def test_run_completo_via_api(self):
        status, _, body = request(self.base_url, "POST", "/runs", {
            "objetivo": f"tarea demo sobre {self.root}",
            "inputs": {"root": str(self.root)},
            "seed": 0,
        })
        self.assertEqual(status, 201)
        run = json.loads(body)
        self.assertTrue(run["run_id"].startswith("run-"))
        self.assertIn("dag_results", run)
        self.run_id = run["run_id"]

        status, _, body = request(self.base_url, "GET", "/runs")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(json.loads(body)["count"], 1)

        status, _, body = request(self.base_url, "GET", f"/runs/{self.run_id}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["run_id"], self.run_id)

    def test_reportes_de_run(self):
        if not hasattr(self, "run_id"):
            status, _, body = request(self.base_url, "POST", "/runs", {"objetivo": "demo", "inputs": {"root": str(self.root)}})
            self.run_id = json.loads(body)["run_id"]
        status, ct, body = request(self.base_url, "GET", f"/runs/{self.run_id}/report.html")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ct)
        self.assertIn(self.run_id, body)
        status, ct, body = request(self.base_url, "GET", f"/runs/{self.run_id}/report.xml")
        self.assertEqual(status, 200)
        self.assertIn("<testsuite", body)
        status, _, body = request(self.base_url, "GET", f"/runs/{self.run_id}/report.md")
        self.assertIn("# Corrida", body)

    def test_schemas_y_tools(self):
        status, _, body = request(self.base_url, "GET", "/schemas")
        self.assertEqual(status, 200)
        self.assertIn('"task"', body)
        status, _, body = request(self.base_url, "GET", "/schemas/task")
        self.assertEqual(status, 200)
        self.assertIn("$schema_version", body)
        status, _, body = request(self.base_url, "GET", "/schemas/nope")
        self.assertEqual(status, 404)
        status, _, body = request(self.base_url, "GET", "/tools")
        self.assertEqual(status, 200)
        nombres = [t["name"] for t in json.loads(body)["tools"]]
        self.assertIn("echo", nombres)

    def test_suite_via_api(self):
        status, _, body = request(self.base_url, "POST", "/suite", {
            "name": "api-suite",
            "tasks": [{
                "task_id": "scan", "kind": "security_scan", "instruction": "escanear",
                "inputs": {"root": str(self.root)}, "deps": [],
                "criterios": [{"id": "informe_json_valido", "peso": 3.0}],
            }],
        })
        self.assertEqual(status, 201)
        data = json.loads(body)
        self.assertEqual(data["suite"], "api-suite")
        self.assertIn("scan", data["dag_results"])

    def test_golden_via_api(self):
        g = {
            "name": "g-api", "min_pass_rate": 1.0,
            "cases": [{
                "id": "c1",
                "task": {"task_id": "s1", "kind": "security_scan", "instruction": "i",
                         "inputs": {"root": str(self.root)},
                         "criterios": [{"id": "informe_json_valido", "peso": 3.0}]},
                "expect": {"veredicto": "aprobado"},
            }],
        }
        gp = self.base / "golden_api.json"
        gp.write_text(json.dumps(g), encoding="utf-8")
        status, _, body = request(self.base_url, "POST", "/golden", {"path": "golden_api.json"})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["gate_ok"])

    def test_golden_path_fuera_de_base_rechazado(self):
        status, _, _ = request(self.base_url, "POST", "/golden", {"path": "../fuera.json"})
        self.assertEqual(status, 400)

    def test_errores(self):
        status, _, body = request(self.base_url, "GET", "/runs/run-000000000000")
        self.assertEqual(status, 404)
        status, _, _ = request(self.base_url, "POST", "/runs", {"inputs": {}})
        self.assertEqual(status, 400)  # falta objetivo
        status, _, _ = request(self.base_url, "GET", "/ruta-rara")
        self.assertEqual(status, 404)

    def test_delete_run(self):
        status, _, body = request(self.base_url, "POST", "/runs", {"objetivo": "demo borrable", "inputs": {"root": str(self.root)}})
        rid = json.loads(body)["run_id"]
        status, _, _ = request(self.base_url, "DELETE", f"/runs/{rid}")
        self.assertEqual(status, 200)
        status, _, _ = request(self.base_url, "GET", f"/runs/{rid}")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
