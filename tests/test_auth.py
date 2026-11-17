"""Tests de autenticacion bearer (tiempo constante) y rate limit por IP."""
import unittest

import _path  # noqa: F401
from harness_candy.auth import IpRateLimiter, TokenAuth


class TestTokenAuth(unittest.TestCase):
    def test_deshabilitado_acepta_todo(self):
        auth = TokenAuth(token="")
        self.assertFalse(auth.enabled)
        self.assertTrue(auth.check_header(None))
        self.assertTrue(auth.check_header("Bearer cualquier-cosa"))

    def test_token_correcto(self):
        auth = TokenAuth(token="secreto-de-prueba")
        self.assertTrue(auth.enabled)
        self.assertTrue(auth.check_header("Bearer secreto-de-prueba"))
        self.assertTrue(auth.check_header("bearer  secreto-de-prueba "))

    def test_token_incorrecto_o_formato_malo(self):
        auth = TokenAuth(token="secreto-de-prueba")
        self.assertFalse(auth.check_header(None))
        self.assertFalse(auth.check_header("Bearer otro"))
        self.assertFalse(auth.check_header("Basic secreto-de-prueba"))
        self.assertFalse(auth.check_header("secreto-de-prueba"))

    def test_lee_de_env(self):
        import os

        os.environ["HARNESS_API_TOKEN_TEST"] = "desde-env"
        try:
            auth = TokenAuth(env="HARNESS_API_TOKEN_TEST")
            self.assertTrue(auth.enabled)
            self.assertTrue(auth.check_header("Bearer desde-env"))
        finally:
            del os.environ["HARNESS_API_TOKEN_TEST"]


class TestIpRateLimiter(unittest.TestCase):
    def test_permite_hasta_el_limite(self):
        rl = IpRateLimiter(limit=3, window_s=60)
        self.assertTrue(rl.allow("1.2.3.4", now=1000.0))
        self.assertTrue(rl.allow("1.2.3.4", now=1001.0))
        self.assertTrue(rl.allow("1.2.3.4", now=1002.0))
        self.assertFalse(rl.allow("1.2.3.4", now=1003.0))
        # otra IP tiene su propio limite
        self.assertTrue(rl.allow("5.6.7.8", now=1003.0))

    def test_ventana_deslizante_expira(self):
        rl = IpRateLimiter(limit=2, window_s=10)
        rl.allow("x", now=0.0)
        rl.allow("x", now=5.0)
        self.assertFalse(rl.allow("x", now=9.0))
        self.assertTrue(rl.allow("x", now=11.0))  # la de t=0 ya salio de la ventana

    def test_remaining_y_stats(self):
        rl = IpRateLimiter(limit=5, window_s=60)
        rl.allow("x", now=0.0)
        self.assertEqual(rl.remaining("x", now=1.0), 4)
        self.assertEqual(rl.stats()["clientes"], 1)
        self.assertEqual(rl.stats()["limit"], 5)


if __name__ == "__main__":
    unittest.main()
