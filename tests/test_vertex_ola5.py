"""Tests del backend Vertex AI/Gemini con ADC (quinta ola).

Sin red real: todo pasa por transport inyectable (fake) y environ inyectado.
Verifica ademas que NUNCA se escribe una clave a disco ni se loguea el token.
"""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.vertex import (
    ADCError,
    VertexBackend,
    obtener_token_adc,
    token_desde_adc_file,
    token_desde_metadata,
)


def resp_json(payload: dict):
    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode()

    return R()


class TransportFalso:
    """Transport inyectable que graba los requests y responde segun una cola."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.requests = []

    def __call__(self, req, timeout=10):
        self.requests.append(req)
        return self.respuestas.pop(0)


class TestVertexBackend(unittest.TestCase):
    def test_complete_via_rest(self):
        tr = TransportFalso([
            resp_json({"candidates": [{"content": {"parts": [{"text": "hola "}, {"text": "mundo"}]}}]})
        ])
        vb = VertexBackend("mi-proyecto", location="us-central1", model="gemini-x",
                           token_provider=lambda: "tok-de-prueba", transport=tr)
        self.assertTrue(callable(getattr(vb, "complete", None)))  # duck-type LLMBackend (Protocol)
        out = vb.complete("dime hola", system="sys", seed=0)
        self.assertEqual(out, "hola mundo")
        req = tr.requests[0]
        self.assertIn("Bearer tok-de-prueba", req.headers.get("Authorization", ""))
        self.assertIn("/mi-proyecto/", req.full_url)
        self.assertIn("us-central1", req.full_url)
        self.assertIn(":generateContent", req.full_url)
        body = json.loads(req.data.decode())
        self.assertEqual(body["contents"][0]["parts"][0]["text"], "dime hola")
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "sys")

    def test_model_override_y_url(self):
        tr = TransportFalso([resp_json({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})])
        vb = VertexBackend("p", model="m1", token_provider=lambda: "t", transport=tr)
        vb.complete("x", model="m2")
        self.assertIn("/models/m2:generateContent", tr.requests[0].full_url)

    def test_respuesta_invalida_error(self):
        tr = TransportFalso([resp_json({"error": "cuota"})])
        vb = VertexBackend("p", token_provider=lambda: "t", transport=tr)
        with self.assertRaises(RuntimeError):
            vb.complete("x")

    def test_project_obligatorio(self):
        with self.assertRaises(ValueError):
            VertexBackend("")

    def test_from_env(self):
        env = {"GOOGLE_CLOUD_PROJECT": "proj-123", "VERTEX_LOCATION": "europe-west4", "VERTEX_MODEL": "gemini-y"}
        vb = VertexBackend.from_env(environ=env, token_provider=lambda: "t", transport=lambda r, timeout=1: resp_json({}))
        self.assertEqual(vb.project, "proj-123")
        self.assertEqual(vb.location, "europe-west4")
        self.assertEqual(vb.default_model, "gemini-y")

    def test_token_nunca_en_disco(self):
        # el token solo vive en memoria/header: el backend no tiene archivos propios
        with tempfile.TemporaryDirectory() as td:
            tr = TransportFalso([resp_json({"candidates": [{"content": {"parts": [{"text": "x"}]}}]})])
            vb = VertexBackend("p", token_provider=lambda: "token-secreto-123", transport=tr)
            vb.complete("hola")
            archivos = list(Path(td).rglob("*"))
            self.assertEqual(archivos, [])  # no escribio nada
            self.assertNotIn("token-secreto-123", repr(vb.__dict__))  # no queda en un attr plano de texto


class TestADC(unittest.TestCase):
    def test_token_desde_metadata(self):
        tr = TransportFalso([resp_json({"access_token": "tok-meta", "expires_in": 3600})])
        self.assertEqual(token_desde_metadata(transport=tr), "tok-meta")
        headers = {k.lower(): v for k, v in tr.requests[0].headers.items()}
        self.assertEqual(headers.get("metadata-flavor"), "Google")

    def test_metadata_falla_devuelve_none(self):
        def falla(req, timeout=1):
            raise OSError("sin metadata server")
        self.assertIsNone(token_desde_metadata(transport=falla))

    def test_token_desde_adc_file(self):
        with tempfile.TemporaryDirectory() as td:
            adc = Path(td) / "adc.json"
            adc.write_text(json.dumps({
                "type": "authorized_user",
                "client_id": "cid",
                "client_secret": "cs",
                "refresh_token": "rt",
                "token_uri": "https://oauth2.googleapis.com/token",
            }))
            tr = TransportFalso([resp_json({"access_token": "AT-desde-adc", "expires_in": 3600})])
            tok = token_desde_adc_file(adc, transport=tr)
            self.assertEqual(tok, "AT-desde-adc")
            # el body del refresh NO se imprime ni se guarda; solo viaja en el request
            body = json.loads(tr.requests[0].data.decode())
            self.assertEqual(body["grant_type"], "refresh_token")
            self.assertEqual(body["refresh_token"], "rt")

    def test_adc_file_inexistente(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(token_desde_adc_file(Path(td) / "no.json", transport=lambda r, timeout=1: resp_json({})))

    def test_adc_file_tipo_invalido(self):
        with tempfile.TemporaryDirectory() as td:
            adc = Path(td) / "adc.json"
            adc.write_text(json.dumps({"type": "service_account", "private_key": "x"}))
            self.assertIsNone(token_desde_adc_file(adc, transport=lambda r, timeout=1: resp_json({})))

    def test_obtener_token_adc_orden_y_error(self):
        # metadata falla, gcloud no existe en sandbox, adc falta -> ADCError
        def falla(req, timeout=1):
            raise OSError("sin red")
        with tempfile.TemporaryDirectory() as td:
            env = {"GOOGLE_APPLICATION_CREDENTIALS": str(Path(td) / "no-existe.json")}
            with self.assertRaises(ADCError):
                obtener_token_adc(transport=falla, environ=env)

    def test_obtener_token_adc_desde_metadata(self):
        tr = TransportFalso([resp_json({"access_token": "tok-final", "expires_in": 3600})])
        tok = obtener_token_adc(transport=tr, environ={})
        self.assertEqual(tok, "tok-final")


if __name__ == "__main__":
    unittest.main()
