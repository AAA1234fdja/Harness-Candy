"""Tests multi-backend (backends_multi.py, ola 6): Anthropic, Ollama, selector, failover, token budget.

Sin red: transport inyectable en cada backend.
"""
import json
import unittest

import _path  # noqa: F401
from harness_candy.backends import BackendError
from harness_candy.backends_multi import (
    AnthropicBackend,
    FailoverPorModelo,
    OllamaBackend,
    SelectorModelos,
    TokenBudget,
    backends_disponibles,
    failover_desde_env,
)
from harness_candy.latencia import bench_latencia


def transport_falso(respuesta, capturar=None):
    def tr(req, timeout=10):
        if capturar is not None:
            capturar.append(req)
        class R:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(respuesta).encode()
        return R()
    return tr


class TestAnthropic(unittest.TestCase):
    def test_complete_y_headers(self):
        reqs = []
        b = AnthropicBackend(environ={"ANTHROPIC_API_KEY": "sk-ant-prueba"},
                             transport=transport_falso({"content": [{"type": "text", "text": "hola"}], "usage": {"input_tokens": 3}}, reqs))
        self.assertEqual(b.complete("dime hola", system="sys"), "hola")
        req = reqs[0]
        self.assertEqual(req.headers.get("X-api-key"), "sk-ant-prueba")
        self.assertEqual(req.headers.get("Anthropic-version"), "2023-06-01")
        body = json.loads(req.data.decode())
        self.assertEqual(body["system"], "sys")
        self.assertEqual(body["messages"][0]["content"], "dime hola")
        self.assertEqual(b.last_usage["input_tokens"], 3)

    def test_sin_clave_error(self):
        with self.assertRaises(BackendError) as cm:
            AnthropicBackend(environ={}).complete("x")
        self.assertIn("ANTHROPIC_API_KEY", str(cm.exception))

    def test_respuesta_rara(self):
        b = AnthropicBackend(environ={"ANTHROPIC_API_KEY": "k"}, transport=transport_falso({"error": "x"}))
        with self.assertRaises(BackendError):
            b.complete("x")


class TestOllama(unittest.TestCase):
    def test_complete_local(self):
        reqs = []
        b = OllamaBackend(transport=transport_falso({"response": "hola local"}, reqs))
        self.assertTrue(b.disponible())
        self.assertEqual(b.complete("hola", seed=3), "hola local")
        body = json.loads(reqs[-1].data.decode())
        self.assertEqual(body["model"], "llama3.1")
        self.assertEqual(body["options"]["seed"], 3)
        self.assertFalse(body["stream"])

    def test_caido(self):
        def caido(req, timeout=1):
            raise OSError("sin ollama")
        b = OllamaBackend(transport=caido)
        self.assertFalse(b.disponible())
        with self.assertRaises(BackendError):
            b.complete("x")


class TestSelector(unittest.TestCase):
    def _registrar(self, s):
        s.registrar("flash", costo_per_1k=0.0001, p95_s=0.2, q_media=0.7)
        s.registrar("opus", costo_per_1k=0.015, p95_s=1.5, q_media=0.9)

    def test_politicas(self):
        for pol, ganador in (("calidad", "opus"), ("costo", "flash"), ("latencia", "flash")):
            s = SelectorModelos(pol)
            self._registrar(s)
            self.assertEqual(s.elegir(["flash", "opus"]), ganador)

    def test_sin_metricas_primero(self):
        self.assertEqual(SelectorModelos("calidad").elegir(["x", "y"]), "x")

    def test_desde_bench(self):
        s = SelectorModelos("latencia")
        import time
        bench = bench_latencia(lambda: time.sleep(0.002), n=5)
        s.actualizar_desde_bench("nuevo", bench, costo_per_1k=0.001, q_media=0.85)
        self.assertIn("nuevo", s._metricas)
        self.assertGreater(s._metricas["nuevo"].p95_s, 0)

    def test_politica_invalida(self):
        with self.assertRaises(ValueError):
            SelectorModelos("magia")
        with self.assertRaises(ValueError):
            SelectorModelos("calidad").elegir([])


class TestFailover(unittest.TestCase):
    def test_primero_falla_segundo_responde(self):
        class Roto:
            def complete(self, prompt, *, system="", model="", seed=0):
                raise BackendError("caido")
        class Bueno:
            def __init__(self): self.llamadas = 0
            def complete(self, prompt, *, system="", model="", seed=0):
                self.llamadas += 1
                return f"ok desde {model}"
        bueno = Bueno()
        fo = FailoverPorModelo([{"modelo": "m1", "backend": Roto()}, {"modelo": "m2", "backend": bueno}],
                               max_reintentos=2, backoff_base=0.001)
        self.assertEqual(fo.complete("hola"), "ok desde m2")
        self.assertEqual(fo.ganador, "m2")
        res = fo.resumen()
        self.assertTrue(any(i.startswith("fallo:m1") for i in res["intentos"]))

    def test_todos_fallan(self):
        class Roto:
            def complete(self, prompt, *, system="", model="", seed=0):
                raise BackendError("caido")
        fo = FailoverPorModelo([{"modelo": "a", "backend": Roto()}, {"modelo": "b", "backend": Roto()}], backoff_base=0.001)
        with self.assertRaises(BackendError) as cm:
            fo.complete("x")
        self.assertIn("todas las opciones fallaron", str(cm.exception))

    def test_vacio_error(self):
        with self.assertRaises(ValueError):
            FailoverPorModelo([])


class TestDesdeEnv(unittest.TestCase):
    def test_backends_disponibles(self):
        disp = backends_disponibles(environ={"ANTHROPIC_API_KEY": "sk-ant-x"})
        self.assertIsNotNone(disp["anthropic"])
        self.assertIsNotNone(disp["ollama"])  # local-first siempre
        self.assertIsNone(disp["vertex"])     # sin GOOGLE_CLOUD_PROJECT
        disp2 = backends_disponibles(environ={"GOOGLE_CLOUD_PROJECT": "p", "GOOGLE_APPLICATION_CREDENTIALS": "/no/existe.json"})
        self.assertIsNotNone(disp2["vertex"])

    def test_failover_desde_env(self):
        fo = failover_desde_env(environ={"ANTHROPIC_API_KEY": "sk-ant-x"})
        self.assertEqual(len(fo.opciones), 2)  # anthropic + ollama
        self.assertEqual(fo.opciones[0]["backend"].__class__.__name__, "AnthropicBackend")
        fo_local = failover_desde_env(environ={})
        self.assertEqual(len(fo_local.opciones), 1)
        self.assertEqual(fo_local.opciones[0]["backend"].__class__.__name__, "OllamaBackend")


class TestTokenBudget(unittest.TestCase):
    def test_warning_y_agotado(self):
        tb = TokenBudget({"qa": 1000})
        r1 = tb.registrar_gasto("qa", 850)
        self.assertEqual(r1["estado"], "warning")
        self.assertTrue(r1["permitido"])
        r2 = tb.registrar_gasto("qa", 200)
        self.assertEqual(r2["estado"], "agotado")
        self.assertFalse(r2["permitido"])
        self.assertTrue(any(a["nivel"] == "critical" for a in tb.alertas))
        json.dumps(tb.resumen())

    def test_excedente_permitido(self):
        tb = TokenBudget({"qa": 10}, permitir_excedente=True)
        r = tb.registrar_gasto("qa", 20)
        self.assertEqual(r["estado"], "agotado")
        self.assertTrue(r["permitido"])

    def test_errores(self):
        tb = TokenBudget({"qa": 100})
        with self.assertRaises(KeyError):
            tb.registrar_gasto("otro", 1)
        with self.assertRaises(ValueError):
            tb.registrar_gasto("qa", -5)
        with self.assertRaises(ValueError):
            TokenBudget({"x": 0})


if __name__ == "__main__":
    unittest.main()
