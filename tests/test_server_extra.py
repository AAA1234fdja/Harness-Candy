"""Tests extra del servidor: dashboard /, /metrics, /jobs y auth bearer."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import _path  # noqa: F401
from helpers import make_repo

from harness_candy.auth import TokenAuth
from harness_candy.server import make_server


def request(base, method, path, body=None, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(base + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read().decode("utf-8")


class TestServerExtra(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        td = Path(cls.td.name)
        cls.root = make_repo(str(td), with_secret=False)
        (td / "s.json").write_text(json.dumps({
            "name": "job-suite",
            "tasks": [{"task_id": "scan", "kind": "security_scan", "instruction": "i",
                       "inputs": {"root": str(cls.root)}, "deps": [],
                       "criterios": [{"id": "informe_json_valido", "peso": 1.0}]}],
        }), encoding="utf-8")
        cls.server = make_server("127.0.0.1", 0, store=f"json://{td}/runs", trace_dir=td / "traces", base_dir=td)
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.td.cleanup()

    def test_dashboard_en_raiz(self):
        status, ct, body = request(self.base, "GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ct)
        self.assertIn("Harness-Candy", body)
        self.assertIn("/events", body)  # SSE en el dashboard
        self.assertIn("/metrics", body)

    def test_metrics_prometheus(self):
        # primero una corrida para tener metricas
        request(self.base, "POST", "/runs", {"objetivo": "demo metricas", "inputs": {"root": str(self.root)}})
        status, ct, body = request(self.base, "GET", "/metrics")
        self.assertEqual(status, 200)
        self.assertIn("text/plain", ct)
        self.assertIn("harness_candy_corridas_total", body)

    def test_jobs_crud(self):
        status, _, body = request(self.base, "POST", "/jobs", {"name": "cada-300", "suite_path": "s.json", "interval_s": 300})
        self.assertEqual(status, 201)
        job = json.loads(body)
        self.assertTrue(job["job_id"].startswith("job-"))
        status, _, body = request(self.base, "GET", "/jobs")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["jobs"]), 1)
        # tick manual del scheduler para ejecutar el job ya
        lanzados = self.server.cfg.scheduler.tick_blocking(now=job["next_run"] + 1)
        self.assertEqual(len(lanzados), 1)
        status, _, body = request(self.base, "DELETE", f"/jobs/{job['job_id']}")
        self.assertEqual(status, 200)
        status, _, body = request(self.base, "GET", "/jobs")
        self.assertEqual(len(json.loads(body)["jobs"]), 0)

    def test_job_suite_fuera_de_base_rechazado(self):
        status, _, _ = request(self.base, "POST", "/jobs", {"suite_path": "../fuera.json", "interval_s": 60})
        self.assertEqual(status, 400)

    def test_compare_dos_runs(self):
        _, _, b1 = request(self.base, "POST", "/runs", {"objetivo": "demo A", "inputs": {"root": str(self.root)}, "seed": 0})
        _, _, b2 = request(self.base, "POST", "/runs", {"objetivo": "demo B", "inputs": {"root": str(self.root)}, "seed": 1})
        a, b = json.loads(b1)["run_id"], json.loads(b2)["run_id"]
        status, _, body = request(self.base, "GET", f"/compare?a={a}&b={b}")
        self.assertEqual(status, 200)
        d = json.loads(body)
        self.assertEqual(d["a"], a)
        self.assertEqual(d["b"], b)
        self.assertIn("q_medio_a", d)
        self.assertIn("metricas", d)
        # run inexistente -> 404
        status, _, _ = request(self.base, "GET", f"/compare?a={a}&b=run-000000000000")
        self.assertEqual(status, 404)


class TestServerAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        td = Path(cls.td.name)
        cls.root = make_repo(str(td), with_secret=False)
        cls.server = make_server(
            "127.0.0.1", 0, store=f"json://{td}/runs", trace_dir=td / "traces", base_dir=td,
            auth=TokenAuth(token="token-de-prueba-123"),
        )
        cls.port = cls.server.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.td.cleanup()

    def test_sin_token_401_salvo_health(self):
        status, _, _ = request(self.base, "GET", "/runs")
        self.assertEqual(status, 401)
        status, _, _ = request(self.base, "GET", "/health")
        self.assertEqual(status, 200)  # health siempre abierto
        status, _, _ = request(self.base, "POST", "/runs", {"objetivo": "x"})
        self.assertEqual(status, 401)

    def test_con_token_entra(self):
        h = {"Authorization": "Bearer token-de-prueba-123"}
        status, _, _ = request(self.base, "GET", "/runs", headers=h)
        self.assertEqual(status, 200)
        status, _, body = request(self.base, "POST", "/runs", {"objetivo": "auth ok", "inputs": {"root": str(self.root)}}, headers=h)
        self.assertEqual(status, 201)
        self.assertIn("run_id", json.loads(body))

    def test_token_malo_401(self):
        status, _, _ = request(self.base, "GET", "/runs", headers={"Authorization": "Bearer malo"})
        self.assertEqual(status, 401)

    def test_rate_limit_429(self):
        # servidor con limite muy bajo
        td2 = tempfile.TemporaryDirectory()
        self.addCleanup(td2.cleanup)
        srv = make_server("127.0.0.1", 0, store=f"json://{td2.name}/runs", trace_dir=Path(td2.name) / "t",
                          base_dir=td2.name, rate_limit=3, rate_window_s=60)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        codigos = [request(base, "GET", "/health")[0] for _ in range(5)]
        self.assertIn(429, codigos)
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    unittest.main()
