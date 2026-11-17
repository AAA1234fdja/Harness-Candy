"""Tests del catalogo de agentes (agents JSON) y construccion de agentes."""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.agents import ScriptedBackend
from harness_candy.agents_catalog import AgentCatalog, AgentSpec, load_catalog
from harness_candy.schemas import SCHEMAS, SchemaError


def catalogo_dict():
    return {
        "agents": [
            {"name": "XEV", "model": "modelo-ligero", "roles": ["xev"],
             "system_prompt": "Eres ejecutor.", "skills": ["secrets_v2"],
             "guardrails": ["json_strict"], "tools": ["read_file", "py_compile"]},
            {"name": "WEV", "model": "modelo-ligero", "roles": ["wev"]},
        ]
    }


class TestCatalog(unittest.TestCase):
    def test_esquema_publicado(self):
        self.assertIn("agents_catalog", SCHEMAS)

    def test_from_dict_valida(self):
        c = AgentCatalog.from_dict(catalogo_dict())
        self.assertEqual(c.names(), ["XEV", "WEV"])
        spec = c.get("XEV")
        self.assertEqual(spec.skills, ["secrets_v2"])
        self.assertEqual(spec.tools, ["read_file", "py_compile"])

    def test_esquema_rechaza(self):
        with self.assertRaises(SchemaError):
            AgentCatalog.from_dict({"agents": [{"name": "1MAL", "model": "m"}]})  # nombre invalido
        with self.assertRaises(SchemaError):
            AgentCatalog.from_dict({"agents": []})  # minItems 1
        with self.assertRaises(SchemaError):
            AgentCatalog.from_dict({})  # falta agents

    def test_by_role(self):
        c = AgentCatalog.from_dict(catalogo_dict())
        self.assertEqual([a.name for a in c.by_role("xev")], ["XEV"])
        self.assertEqual([a.name for a in c.by_role("wev")], ["WEV"])
        # sin roles asignados, matchea cualquier rol
        c2 = AgentCatalog.from_dict({"agents": [{"name": "GEN", "model": "m"}]})
        self.assertEqual([a.name for a in c2.by_role("cualquiera")], ["GEN"])

    def test_get_desconocido(self):
        c = AgentCatalog.from_dict(catalogo_dict())
        with self.assertRaises(KeyError):
            c.get("NOPE")

    def test_harness_del_spec(self):
        spec = AgentSpec({"name": "A", "model": "m", "skills": ["s"], "guardrails": ["g"], "system_prompt": "p"})
        h = spec.to_harness()
        self.assertEqual(h.skills, ["s"])
        self.assertEqual(h.guardrails, ["g"])
        self.assertEqual(h.system_prompt, "p")

    def test_build_agents(self):
        c = AgentCatalog.from_dict(catalogo_dict())
        agentes = c.build_agents(ScriptedBackend(lambda *a, **k: "ok"))
        self.assertIn("XEV", agentes)
        self.assertEqual(agentes["XEV"].default_harness.skills, ["secrets_v2"])
        self.assertEqual(agentes["XEV"].model, "modelo-ligero")

    def test_load_desde_archivo(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "agents.json"
            p.write_text(json.dumps(catalogo_dict()), encoding="utf-8")
            c = load_catalog(p)
            self.assertEqual(len(c.agents), 2)


if __name__ == "__main__":
    unittest.main()
