"""Tests de configuracion con precedencia y enmascarado (config.py)."""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.config import CONFIG_SCHEMA, DEFAULTS, Config, default_config, load_config
from harness_candy.schemas import SCHEMAS, SchemaError, schema_names


class TestConfig(unittest.TestCase):
    def test_esquema_registrado(self):
        self.assertIn("config", SCHEMAS)
        self.assertIn("config", schema_names())
        self.assertIs(SCHEMAS["config"], CONFIG_SCHEMA)

    def test_defaults(self):
        c = default_config()
        self.assertEqual(c.get("server", "port"), 8000)
        self.assertEqual(c.get("backend", "kind"), "scripted")
        self.assertEqual(c.get("budget", "total"), 10_000)

    def test_precedencia_archivo_env_kwargs(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.json"
            p.write_text(json.dumps({"server": {"port": 9999}}), encoding="utf-8")
            self.assertEqual(Config.load(p).get("server", "port"), 9999)
            self.assertEqual(Config.load(p, environ={"HARNESS_SERVER_PORT": "7777"}).get("server", "port"), 7777)
            self.assertEqual(Config.load(p, environ={"HARNESS_SERVER_PORT": "7777"}, server={"port": 6666}).get("server", "port"), 6666)

    def test_env_file_lite(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".env"
            p.write_text("# comentario\nHARNESS_STORE=sqlite:///tmp/x.db\nHARNESS_SERVER_PORT=9000\n", encoding="utf-8")
            # el parser .env-lite lee claves HARNESS_*? no: lee K=V generica; usamos load con archivo plano
            c = Config.load(p)
            self.assertEqual(c.get("HARNESS_STORE"), "sqlite:///tmp/x.db")

    def test_env_map_coercion_tipos(self):
        c = Config.load(None, environ={"HARNESS_BUDGET_TOTAL": "5000", "HARNESS_BUDGET_BETA": "0.3", "HARNESS_SERVER_PORT": "8080"})
        self.assertEqual(c.get("budget", "total"), 5000)
        self.assertAlmostEqual(c.get("budget", "beta"), 0.3)
        self.assertEqual(c.get("server", "port"), 8080)

    def test_kwargs_override(self):
        c = Config.load(None, trace_dir="xyz")
        self.assertEqual(c.get("trace_dir"), "xyz")

    def test_to_safe_dict_enmascara_secretos(self):
        c = Config({"backend": {"kind": "scripted", "api_key_env": "XKIRO_API_KEY"}, "custom": {"api_key": "sk-abcdef123456", "token": "abc"}})
        sd = c.to_safe_dict()
        self.assertEqual(sd["backend"]["api_key_env"], "***")
        self.assertEqual(sd["custom"]["api_key"], "***")
        self.assertEqual(sd["custom"]["token"], "***")

    def test_to_safe_dict_detecta_valores_sk(self):
        c = Config({"nota": "la clave es sk-abcdefghijklmnop123"})
        self.assertEqual(c.to_safe_dict()["nota"], "***")

    def test_valida_esquema(self):
        with self.assertRaises(SchemaError):
            Config({"server": {"port": "no-es-int"}})

    def test_budget_valida_contra_esquema_budget(self):
        with self.assertRaises(SchemaError):
            Config.load(None, budget={"total": -5})

    def test_load_config_alias(self):
        self.assertIsInstance(load_config(None), Config)

    def test_no_hay_api_key_en_defaults(self):
        texto = json.dumps(DEFAULTS)
        self.assertNotIn("sk-", texto)
        self.assertNotIn("AKIA", texto)


if __name__ == "__main__":
    unittest.main()
