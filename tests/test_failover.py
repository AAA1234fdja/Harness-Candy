"""Tests de failover automatico entre backends (riesgo R11)."""
import unittest

import _path  # noqa: F401
from harness_candy.backends import BackendError
from harness_candy.failover import AllBackendsFailed, FailoverBackend


class BackendFalla:
    def __init__(self, veces=10**9):
        self.n = 0
        self.veces = veces

    def complete(self, prompt, *, system="", model="", seed=0):
        self.n += 1
        if self.n <= self.veces:
            raise BackendError("servicio caido")
        return "recuperado"


class BackendOK:
    def __init__(self, respuesta="ok"):
        self.respuesta = respuesta
        self.last_usage = {"total_tokens": 5}

    def complete(self, prompt, *, system="", model="", seed=0):
        return self.respuesta


class TestFailover(unittest.TestCase):
    def test_primero_falla_usa_el_segundo(self):
        fb = FailoverBackend([BackendFalla(), BackendOK("secundario")], names=["primario", "secundario"])
        out = fb.complete("hola", model="m")
        self.assertEqual(out, "secundario")
        self.assertEqual(fb.attempts[0]["ok"], False)
        self.assertEqual(fb.attempts[1]["ok"], True)
        self.assertEqual(fb.last_usage["failover_backend"], "secundario")

    def test_primero_sano_no_se_prueba_el_segundo(self):
        fb = FailoverBackend([BackendOK("primario"), BackendOK("secundario")])
        self.assertEqual(fb.complete("hola"), "primario")
        self.assertEqual(len(fb.attempts), 1)

    def test_todos_fallan_lanza_agregado(self):
        fb = FailoverBackend([BackendFalla(), BackendFalla()], names=["a", "b"])
        with self.assertRaises(AllBackendsFailed) as ctx:
            fb.complete("hola")
        self.assertEqual(len(ctx.exception.attempts), 2)
        self.assertIn("a:", str(ctx.exception))
        self.assertIn("b:", str(ctx.exception))

    def test_recuperacion_tras_fallo_transitorio(self):
        fb = FailoverBackend([BackendFalla(veces=1), BackendOK("backup")], names=["flaky", "backup"])
        self.assertEqual(fb.complete("hola"), "backup")
        self.assertEqual(fb.attempts[0]["ok"], False)
        self.assertEqual(fb.attempts[1]["ok"], True)

    def test_requiere_al_menos_un_backend(self):
        with self.assertRaises(ValueError):
            FailoverBackend([])

    def test_healthy_filtra_sin_api_key(self):
        class ConKey:
            def _api_key(self):
                raise BackendError("falta XKIRO_API_KEY")

            def complete(self, prompt, *, system="", model="", seed=0):
                return "x"

        fb = FailoverBackend([ConKey(), BackendOK()], names=["con-key-rota", "scripted"])
        self.assertEqual(fb.healthy(), ["scripted"])

    def test_stats(self):
        fb = FailoverBackend([BackendFalla(), BackendOK()], names=["a", "b"])
        fb.complete("hola")
        s = fb.stats()
        self.assertEqual(s["backends"], ["a", "b"])
        self.assertEqual(s["sanos"], ["a", "b"])  # BackendFalla no tiene _api_key -> se considera sano
        self.assertEqual(len(s["intentos"]), 2)

    def test_timeout_total(self):
        import time

        class Lento:
            def complete(self, prompt, *, system="", model="", seed=0):
                time.sleep(0.2)
                raise BackendError("lento")

        fb = FailoverBackend([Lento(), Lento()], timeout_total=0.05)
        with self.assertRaises(AllBackendsFailed) as ctx:
            fb.complete("hola")
        self.assertIn("timeout total", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
