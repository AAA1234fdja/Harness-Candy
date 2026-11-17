"""Tests de crypto minima (crypto.py)."""
import os
import unittest

import _path  # noqa: F401
from harness_candy.crypto import (
    SIGNING_KEY_ENV,
    buscar_secretos,
    constant_time_eq,
    gen_token,
    hmac_sha256,
    mask_secret,
    redact_text,
    sha256_hex,
    sign_run,
    signing_key,
    verify_run,
)


class TestCrypto(unittest.TestCase):
    def test_sha256(self):
        self.assertEqual(sha256_hex("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(sha256_hex(b"abc"), sha256_hex("abc"))

    def test_hmac(self):
        h = hmac_sha256("k", "mensaje")
        self.assertEqual(len(h), 64)
        self.assertEqual(h, hmac_sha256(b"k", b"mensaje"))
        self.assertNotEqual(h, hmac_sha256("k2", "mensaje"))

    def test_constant_time_eq(self):
        self.assertTrue(constant_time_eq("abc", "abc"))
        self.assertFalse(constant_time_eq("abc", "abd"))

    def test_gen_token(self):
        t1 = gen_token()
        t2 = gen_token()
        self.assertNotEqual(t1, t2)
        self.assertGreaterEqual(len(t1), 32)
        self.assertTrue(all(c.isalnum() or c in "-_" for c in t1))

    def test_signing_key_fail_closed(self):
        with self.assertRaises(RuntimeError):
            signing_key({})
        self.assertEqual(signing_key({SIGNING_KEY_ENV: "clave-de-prueba"}), "clave-de-prueba")

    def test_sign_verify_run(self):
        run = {"run_id": "r1", "qs": {"a": 1.0}, "objetivo": "o"}
        firma = sign_run(run, key="k-secreto")
        self.assertTrue(verify_run(run, firma, key="k-secreto"))
        run_mutado = dict(run)
        run_mutado["qs"] = {"a": 0.0}
        self.assertFalse(verify_run(run_mutado, firma, key="k-secreto"))
        self.assertFalse(verify_run(run, firma, key="otra-clave"))
        # determinista: misma entrada -> misma firma
        self.assertEqual(firma, sign_run(run, key="k-secreto"))

    def test_sign_run_desde_env(self):
        env = {SIGNING_KEY_ENV: "k-env"}
        firma = sign_run({"x": 1}, environ=env)
        self.assertTrue(verify_run({"x": 1}, firma, environ=env))

    def test_mask_secret(self):
        self.assertEqual(mask_secret("sk-abcdefghijklmnop"), "sk-a***(len=19)")
        self.assertEqual(mask_secret("corto"), "corto"[:4] + "***(len=5)")
        self.assertEqual(mask_secret("ab"), "***")
        self.assertEqual(mask_secret(""), "")

    def test_redact_text(self):
        texto = "la clave es sk-abcdefghijklmnop123 y AKIAIOSFODNN7EXAMPLE en el codigo"
        out = redact_text(texto)
        self.assertNotIn("sk-abcdefghijklmnop123", out)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", out)
        self.assertIn("***", out)

    def test_buscar_secretos(self):
        h = buscar_secretos("token = 'ghp_abcdefghijklmnopqrstuvwxyz'")
        self.assertTrue(h)
        self.assertIn("fragmento", h[0])
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz", h[0]["fragmento"])
        self.assertEqual(buscar_secretos("texto limpio sin nada"), [])


if __name__ == "__main__":
    unittest.main()
