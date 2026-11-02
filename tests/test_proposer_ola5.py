"""Tests del proposer LLM de la quinta ola (harness_candy.proposer)."""
import json
import unittest

import _path  # noqa: F401
from harness_candy.agents import ScriptedBackend, Task
from harness_candy.harness import Harness, RuleBasedProposer
from harness_candy.proposer import CANDIDATO_SCHEMA, LLMProposer, proposer_desde_config
from harness_candy.quality import Criterion


def tarea():
    return Task("t1", "security_scan", "escanear", {}, [Criterion("c1")])


def llm_json(respuestas):
    """Backend scripted que devuelve la siguiente respuesta de la lista."""
    it = iter(respuestas)
    return ScriptedBackend(lambda p, system="", model="", seed=0: next(it))


class TestLLMProposer(unittest.TestCase):
    def test_propuestas_validas_se_aplican(self):
        backend = llm_json([
            json.dumps({"propuestas": [
                {"cambios": {"system_prompt": "Se riguroso.", "guardrails": ["json_strict"]}, "razonamiento": "r1"},
                {"cambios": {"tool_guidance": "solo aprobadas"}, "razonamiento": "r2"},
            ]})
        ])
        h0 = Harness(system_prompt="base")
        cands = LLMProposer(backend)(h0, "security_scan", 2, task=tarea(), evidencia={"q_ref": 0.6})
        self.assertEqual(len(cands), 2)
        # conserva lo que funciono: system_prompt nuevo se anade al de h0
        self.assertEqual(cands[0].system_prompt, "base\nSe riguroso.")
        self.assertIn("json_strict", cands[0].guardrails)
        self.assertEqual(cands[1].tool_guidance, "solo aprobadas")

    def test_fallback_fail_closed_a_rule_based(self):
        backend = llm_json(["esto no es JSON", "tampoco {{esto}}"])
        p = LLMProposer(backend, max_retries=1)
        cands = p(Harness(), "security_scan", 2)
        # cae al RuleBasedProposer: 2 generales + 2 de dominio
        self.assertEqual(len(cands), 4)

    def test_respeta_k(self):
        backend = llm_json([
            json.dumps({"propuestas": [
                {"cambios": {"guardrails": [f"g{i}"]}, "razonamiento": f"r{i}"} for i in range(6)
            ]})
        ])
        cands = LLMProposer(backend)(Harness(), "demo", 2)
        self.assertEqual(len(cands), 4)  # 2*k tope

    def test_schema_candidato(self):
        self.assertIn("cambios", CANDIDATO_SCHEMA["properties"])
        self.assertIn("razonamiento", CANDIDATO_SCHEMA["required"])

    def test_desde_config(self):
        # con backend -> LLMProposer; sin backend -> RuleBasedProposer (fail-closed)
        p = proposer_desde_config(ScriptedBackend(lambda *a, **k: "{}"), model="m")
        self.assertIsInstance(p, LLMProposer)
        self.assertIsInstance(proposer_desde_config(None), RuleBasedProposer)

    def test_prompt_no_roto(self):
        # el template no debe contener {{ }} literales que rompan el motor
        backend = llm_json([json.dumps({"propuestas": [{"cambios": {}, "razonamiento": "x"}]})])
        cands = LLMProposer(backend)(Harness(), "demo", 1, task=tarea())
        self.assertEqual(len(cands), 1)


if __name__ == "__main__":
    unittest.main()
