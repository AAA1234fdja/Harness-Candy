"""Tests del cache en disco de respuestas LLM."""
import tempfile
import unittest

import _path  # noqa: F401
from harness_candy.cache import CachedBackend, ResponseCache, cache_key


class BackendContador:
    def __init__(self, respuesta="salida"):
        self.n = 0
        self.respuesta = respuesta
        self.last_usage = {"total_tokens": 100}

    def complete(self, prompt, *, system="", model="", seed=0):
        self.n += 1
        return f"{self.respuesta}#{self.n}"


class TestCacheKey(unittest.TestCase):
    def test_determinista(self):
        self.assertEqual(cache_key("m", "s", "p", 0), cache_key("m", "s", "p", 0))

    def test_distinta_por_campo(self):
        base = cache_key("m", "s", "p", 0)
        self.assertNotEqual(base, cache_key("m2", "s", "p", 0))
        self.assertNotEqual(base, cache_key("m", "s2", "p", 0))
        self.assertNotEqual(base, cache_key("m", "s", "p2", 0))
        self.assertNotEqual(base, cache_key("m", "s", "p", 1))

    def test_no_incluye_claves(self):
        k = cache_key("m", "s", "prompt con sk-abcdefghijklmnopqrstuvwxyz1234 dentro", 0)
        # la clave es un hash: el patron de secreto no aparece en claro
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz1234", k)


class TestResponseCache(unittest.TestCase):
    def test_put_get(self):
        with tempfile.TemporaryDirectory() as td:
            c = ResponseCache(td)
            c.put("k1", "respuesta")
            self.assertEqual(c.get("k1"), "respuesta")
            self.assertEqual(c.stats()["hits"], 1)

    def test_miss(self):
        with tempfile.TemporaryDirectory() as td:
            c = ResponseCache(td)
            self.assertIsNone(c.get("nope"))
            self.assertEqual(c.stats()["misses"], 1)
            self.assertEqual(c.stats()["hit_rate"], 0.0)  # 0 hits / 1 total

    def test_ttl_expira(self):
        with tempfile.TemporaryDirectory() as td:
            c = ResponseCache(td, ttl_s=10)
            c.put("k", "v", now=1000.0)
            self.assertEqual(c.get("k", now=1005.0), "v")
            self.assertIsNone(c.get("k", now=1011.0))  # expiro y se borro
            self.assertFalse((c.dir / "k.json").exists())

    def test_clear(self):
        with tempfile.TemporaryDirectory() as td:
            c = ResponseCache(td)
            c.put("a", "1")
            c.put("b", "2")
            self.assertEqual(c.clear(), 2)
            self.assertEqual(c.count() if hasattr(c, "count") else c.stats()["entradas"], 0)

    def test_eviction_por_max_entries(self):
        with tempfile.TemporaryDirectory() as td:
            c = ResponseCache(td, max_entries=3)
            for i in range(6):
                c.put(f"k{i}", str(i))
            self.assertEqual(c.stats()["entradas"], 3)

    def test_archivo_corrupto_cuenta_miss(self):
        with tempfile.TemporaryDirectory() as td:
            c = ResponseCache(td)
            (c.dir / "mala.json").parent.mkdir(parents=True, exist_ok=True)
            (c.dir / "mala.json").write_text("{no es json", encoding="utf-8")
            self.assertIsNone(c.get("mala"))
            self.assertEqual(c.stats()["misses"], 1)


class TestCachedBackend(unittest.TestCase):
    def test_segunda_llamada_usa_cache(self):
        with tempfile.TemporaryDirectory() as td:
            backend = BackendContador()
            cb = CachedBackend(backend, ResponseCache(td))
            r1 = cb.complete("hola", model="m", seed=1)
            r2 = cb.complete("hola", model="m", seed=1)
            self.assertEqual(r1, r2)
            self.assertEqual(backend.n, 1)  # solo una llamada real
            self.assertEqual(cb.stats()["hits"], 1)
            self.assertEqual(cb.last_usage, {"total_tokens": 0, "cached": True})

    def test_seed_distinto_no_usa_cache(self):
        with tempfile.TemporaryDirectory() as td:
            backend = BackendContador()
            cb = CachedBackend(backend, ResponseCache(td))
            cb.complete("hola", model="m", seed=1)
            cb.complete("hola", model="m", seed=2)
            self.assertEqual(backend.n, 2)

    def test_deshabilitado_llama_siempre(self):
        with tempfile.TemporaryDirectory() as td:
            backend = BackendContador()
            cb = CachedBackend(backend, ResponseCache(td), enabled=False)
            cb.complete("hola", model="m", seed=1)
            cb.complete("hola", model="m", seed=1)
            self.assertEqual(backend.n, 2)

    def test_ultimo_uso_del_backend_real(self):
        with tempfile.TemporaryDirectory() as td:
            backend = BackendContador()
            cb = CachedBackend(backend, ResponseCache(td))
            cb.complete("hola", model="m", seed=1)
            self.assertEqual(cb.last_usage.get("total_tokens"), 100)


if __name__ == "__main__":
    unittest.main()
