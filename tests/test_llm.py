"""Tests de la capa LLM avanzada (llm.py): plantillas, few-shot, chat, structured."""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.factory import make_backend
from harness_candy.llm import (
    ChatMessage,
    ChatSession,
    FewShotExample,
    PromptTemplate,
    StructuredOutputError,
    build_few_shot,
    complete_with_retry,
    estimate_tokens,
    structured_output,
)


class FakeBackend:
    """Backend falso con guion de respuestas."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas: list[dict] = []
        self.default_model = "fake"

    def complete(self, prompt, system="", model="", seed=0):
        self.llamadas.append({"prompt": prompt, "system": system, "model": model, "seed": seed})
        if not self.respuestas:
            raise RuntimeError("sin respuestas")
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class TestLLM(unittest.TestCase):
    def test_estimate_tokens(self):
        self.assertEqual(estimate_tokens(""), 1)
        self.assertGreaterEqual(estimate_tokens("a" * 100), 25)

    def test_prompt_template(self):
        pt = PromptTemplate("Tema: {{ tema | upper }} ({{ n }} veces)")
        self.assertEqual(pt.render(tema="gatos", n=2), "Tema: GATOS (2 veces)")
        self.assertEqual(pt(tema="perros", n=1), "Tema: PERROS (1 veces)")

    def test_build_few_shot(self):
        fs = build_few_shot([FewShotExample("1+1", "2"), FewShotExample("2+2", "4")])
        self.assertIn("1+1", fs)
        self.assertIn("2+2", fs)
        self.assertIn("Ejemplo 1", fs)
        self.assertIn("Ejemplo 2", fs)

    def test_structured_output_ok(self):
        schema = {"type": "object", "required": ["x"], "properties": {"x": {"type": "integer"}}}
        b = FakeBackend(['```json\n{"x": 5}\n```'])
        data, raw = structured_output(b, "dame JSON", schema, max_retries=0)
        self.assertEqual(data, {"x": 5})
        self.assertIn("x", raw)

    def test_structured_output_reintenta_con_feedback(self):
        schema = {"type": "object", "required": ["x"], "properties": {"x": {"type": "integer"}}}
        b = FakeBackend(["no es json", '{"x": "mal tipo"}', '{"x": 7}'])
        data, _ = structured_output(b, "dame JSON", schema, max_retries=3)
        self.assertEqual(data, {"x": 7})
        self.assertEqual(len(b.llamadas), 3)
        # el segundo intento lleva realimentacion del error
        self.assertIn("esquema", b.llamadas[1]["prompt"])

    def test_structured_output_falla_closed(self):
        schema = {"type": "object", "required": ["x"], "properties": {"x": {"type": "integer"}}}
        b = FakeBackend(["nada", "tampoco"])
        with self.assertRaises(StructuredOutputError):
            structured_output(b, "dame JSON", schema, max_retries=1)

    def test_structured_output_reintenta_si_backend_falla(self):
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
        b = FakeBackend([RuntimeError("caido"), '{"x": 1}'])
        data, _ = structured_output(b, "dame JSON", schema, max_retries=2)
        self.assertEqual(data, {"x": 1})

    def test_chat_session_historial(self):
        b = FakeBackend(["resp1", "resp2"])
        ses = ChatSession(b, system="sys", max_messages=10)
        r = ses.send("hola")
        self.assertEqual(r, "resp1")
        self.assertEqual([m.role for m in ses.history], ["system", "user", "assistant"])
        ses.send("y mas")
        self.assertEqual(len(ses.history), 5)
        self.assertGreater(ses.tokens_estimados(), 0)

    def test_chat_session_recorta_historial(self):
        b = FakeBackend([f"r{i}" for i in range(10)])
        ses = ChatSession(b, system="sys", max_messages=4)
        for i in range(8):
            ses.send(f"m{i}")
        self.assertLessEqual(len(ses.history), 4)
        self.assertEqual(ses.history[0].role, "system")  # conserva el system

    def test_chat_session_persiste_y_reanuda(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ses.json"
            b = FakeBackend(["hola!"])
            ses = ChatSession(b, system="sys", path=path)
            ses.send("hey")
            self.assertTrue(path.exists())
            b2 = FakeBackend(["otra"])
            ses2 = ChatSession.load(path, b2)
            self.assertEqual(len(ses2.history), 3)
            self.assertEqual(ses2.system, "sys")
            ses2.send("otra vez")
            self.assertEqual(ses2.history[-1].content, "otra")

    def test_chat_message_dict(self):
        m = ChatMessage("user", "hola")
        self.assertEqual(ChatMessage.from_dict(m.to_dict()).content, "hola")

    def test_complete_with_retry(self):
        b = FakeBackend([RuntimeError("x"), "ok"])
        # retry_call duerme entre intentos; usamos base_delay pequena via retryable? complete_with_retry usa defaults
        out = complete_with_retry(b, "p", attempts=2)
        self.assertEqual(out, "ok")

    def test_scripted_backend_chat(self):
        b = make_backend("scripted")
        ses = ChatSession(b, system="sys")
        self.assertTrue(ses.send("hola"))


if __name__ == "__main__":
    unittest.main()
