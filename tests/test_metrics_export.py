"""Tests de exportacion de metricas: Prometheus text y spans OTLP/JSON."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import _path  # noqa: F401
from harness_candy.metrics_export import OtlpExporter, otlp_spans, prometheus_text


class TestPrometheusText(unittest.TestCase):
    def test_numericas_se_exportan(self):
        texto = prometheus_text({"pruebas_total": 10, "tasa": 0.9, "nombre": "ignorado", "flag": True, "lista": [1]}, prefix="hc")
        self.assertIn("hc_pruebas_total 10", texto)
        self.assertIn("hc_tasa 0.9", texto)
        self.assertNotIn("nombre", texto)
        self.assertNotIn("flag", texto)
        self.assertTrue(texto.endswith("\n"))

    def test_labels_y_sanitizado(self):
        texto = prometheus_text({"costo total": 1.5}, labels={"run": 'a"b'}, prefix="hc")
        self.assertIn('hc_costo_total{run="a\\"b"} 1.5', texto)

    def test_submetricas_dict(self):
        texto = prometheus_text({"defectos": {"alta": 2, "baja": 1}}, prefix="hc")
        self.assertIn('hc_defectos{defectos="alta"} 2', texto)
        self.assertIn('hc_defectos{defectos="baja"} 1', texto)

    def test_nombres_con_digito_inicial(self):
        from harness_candy.metrics_export import _sanitize_name

        self.assertEqual(_sanitize_name("1cosa"), "m_1cosa")
        self.assertEqual(_sanitize_name("hc_1cosa"), "hc_1cosa")  # digito despues de letra: valido
        texto = prometheus_text({"1cosa": 5}, prefix="hc")
        self.assertIn("hc_1cosa 5", texto)  # el prefijo ya da letra inicial valida


class TestOtlpSpans(unittest.TestCase):
    def test_estructura_otlp(self):
        entries = [
            {"ts": 1700000000.0, "run_id": "run-abc", "task_id": "t-1", "model": "m", "seed": 3,
             "harness": "h#1", "phase": "probe", "q": 0.9, "verdict": "aprobado"},
            {"ts": 1700000001.0, "run_id": "run-abc", "task_id": "t-1", "model": "m", "seed": 4,
             "harness": "h#1", "phase": "final", "q": 1.0, "verdict": "aprobado"},
        ]
        payload = otlp_spans(entries, service_name="prueba")
        rs = payload["resourceSpans"][0]
        self.assertEqual(rs["resource"]["attributes"][0]["value"]["stringValue"], "prueba")
        spans = rs["scopeSpans"][0]["spans"]
        self.assertEqual(len(spans), 2)
        self.assertEqual(spans[0]["name"], "harness.probe")
        self.assertEqual(len(spans[0]["traceId"]), 32)
        attrs = {a["key"]: a["value"]["stringValue"] for a in spans[0]["attributes"]}
        self.assertEqual(attrs["q"], "0.9")
        self.assertEqual(attrs["seed"], "3")
        self.assertEqual(spans[0]["startTimeUnixNano"], 1700000000 * 10**9)
        # JSON serializable
        json.dumps(payload)


class TestOtlpExporter(unittest.TestCase):
    def test_envia_post(self):
        recibidos = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                recibidos.append(self.rfile.read(n).decode())
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            exp = OtlpExporter(f"http://127.0.0.1:{srv.server_port}/v1/traces")
            ok = exp.export([{"ts": 1.0, "run_id": "r", "task_id": "t", "model": "m", "seed": 0, "harness": "h", "phase": "p", "q": 0.5}])
            self.assertTrue(ok)
            self.assertEqual(exp.enviados, 1)
            payload = json.loads(recibidos[0])
            self.assertIn("resourceSpans", payload)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_desactivado_y_errores_no_lanzan(self):
        exp = OtlpExporter("http://127.0.0.1:1/x", enabled=True, timeout=0.5)
        self.assertFalse(exp.export([{"ts": 1.0}]))
        self.assertEqual(len(exp.errores), 1)
        exp2 = OtlpExporter("http://127.0.0.1:1/x", enabled=False)
        self.assertFalse(exp2.export([{"ts": 1.0}]))
        self.assertEqual(exp2.enviados, 0)


if __name__ == "__main__":
    unittest.main()
