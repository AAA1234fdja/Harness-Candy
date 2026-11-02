import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import _path  # noqa: F401
from harness_candy.backends import BackendError, OpenAICompatibleBackend

LAST_REQUEST = {}


class FakeAPIHandler(BaseHTTPRequestHandler):
    """Mock de /chat/completions: devuelve eco y registra la peticion."""

    def do_POST(self):
        global LAST_REQUEST
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        LAST_REQUEST.clear()
        LAST_REQUEST.update(
            {
                "path": self.path,
                "auth": self.headers.get("Authorization", ""),
                "body": json.loads(body),
            }
        )
        if self.path.endswith("/chat/completions"):
            if LAST_REQUEST["body"].get("model") == "modelo-error":
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": {"message": "invalid api key"}}).encode())
                return
            payload = {
                "choices": [
                    {"message": {"role": "assistant", "content": "respuesta de prueba"}}
                ]
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # silencio
        pass


class TestOpenAICompatibleBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeAPIHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        os.environ["XKIRO_API_KEY"] = "sk-test-falsa-solo-para-mock"
        os.environ["XKIRO_MODEL"] = "modelo-test"

    def tearDown(self):
        os.environ.pop("XKIRO_API_KEY", None)
        os.environ.pop("XKIRO_MODEL", None)

    def test_complete_contra_mock(self):
        b = OpenAICompatibleBackend(base_url=self.base_url, timeout=10)
        out = b.complete("hola", system="se conciso", model="modelo-test", seed=7)
        self.assertEqual(out, "respuesta de prueba")
        # la peticion llego bien formada y con la key SOLO en el header
        self.assertEqual(LAST_REQUEST["path"], "/v1/chat/completions")
        self.assertEqual(LAST_REQUEST["auth"], "Bearer sk-test-falsa-solo-para-mock")
        body = LAST_REQUEST["body"]
        self.assertEqual(body["model"], "modelo-test")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "se conciso"})
        self.assertEqual(body["messages"][1]["role"], "user")
        self.assertEqual(body["seed"], 7)
        self.assertNotIn("sk-test", json.dumps(body))  # la key no va en el body

    def test_modelo_por_env(self):
        b = OpenAICompatibleBackend(base_url=self.base_url, timeout=10)
        b.complete("hola")  # usa XKIRO_MODEL del entorno
        self.assertEqual(LAST_REQUEST["body"]["model"], "modelo-test")

    def test_falta_api_key(self):
        os.environ.pop("XKIRO_API_KEY", None)
        b = OpenAICompatibleBackend(base_url=self.base_url, timeout=10)
        with self.assertRaises(BackendError) as ctx:
            b.complete("hola", model="m")
        self.assertIn("XKIRO_API_KEY", str(ctx.exception))

    def test_error_http(self):
        b = OpenAICompatibleBackend(base_url=self.base_url, timeout=10)
        with self.assertRaises(BackendError) as ctx:
            b.complete("hola", model="modelo-error")
        self.assertIn("HTTP 401", str(ctx.exception))
        self.assertIn("invalid api key", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
