"""Tests del lote 8: llm logger/fit_context, evalsuite curva/markdown, rag evaluate_retrieval."""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.evalsuite import EvalSuiteResult, curva_pass_k, markdown_eval_report
from harness_candy.factory import make_backend
from harness_candy.llm import ChatSession, ConversationLogger, fit_context, resumen_historial
from harness_candy.rag import RAGPipeline, evaluate_retrieval


class TestLLMLote8(unittest.TestCase):
    def test_logger(self):
        b = make_backend("scripted")
        ses = ChatSession(b, system="sys")
        ses.send("hola")
        with tempfile.TemporaryDirectory() as td:
            log = ConversationLogger(Path(td) / "c.jsonl")
            log.log(ses)
            log.log(ses)
            datos = log.leer()
            self.assertEqual(len(datos), 2 * len(ses.history))
            self.assertEqual(datos[0]["role"], "system")

    def test_fit_context(self):
        b = make_backend("scripted")
        ses = ChatSession(b, system="sys")
        for i in range(10):
            ses.send("m" * 500)
        n = fit_context(ses, max_tokens=50)  # 200 chars
        self.assertLessEqual(n, 4)
        self.assertEqual(ses.history[0].role, "system")
        self.assertGreaterEqual(ses.tokens_estimados(), 0)

    def test_resumen_historial(self):
        b = make_backend("scripted")
        ses = ChatSession(b, system="sys")
        ses.send("Los agentes ejecutan tareas en el sandbox. La calidad se mide con q. El costo se limita con presupuesto.")
        r = resumen_historial(ses, k=1)
        self.assertIsInstance(r, str) and r


class TestEvalLote8(unittest.TestCase):
    def test_curva_pass_k(self):
        c = curva_pass_k([True, False, True, False])
        self.assertEqual(c[1], 0.5)
        self.assertEqual(c[2], 1.0)  # ventana [T,F] ya tiene un acierto
        self.assertEqual(c[4], 1.0)
        c2 = curva_pass_k([False, False, True, True])
        self.assertEqual(c2[2], 0.5)  # primera ventana sin aciertos
        self.assertEqual(curva_pass_k([]), {})

    def test_markdown_report(self):
        r = EvalSuiteResult("g", [0, 1], {0: 1.0, 1: 0.5}, 0.75,
                            {"aprobado": {"aprobado": 1, "rechazado": 0}, "rechazado": {"aprobado": 1, "rechazado": 0}},
                            {"p2_5": 0.5, "p50": 0.75, "p97_5": 1.0}, 2)
        md = markdown_eval_report(r, extra={"delta": 0.1})
        self.assertIn("# Evaluacion: g", md)
        self.assertIn("**0.750**", md)
        self.assertIn("| 1 | 0.500 |", md)
        self.assertIn("Matriz de confusion", md)
        self.assertIn("delta", md)


class TestRagLote8(unittest.TestCase):
    def test_evaluate_retrieval(self):
        pipe = RAGPipeline(chunk_size=200, chunk_overlap=40)
        pipe.add_text("a.md", "Las claves API solo viven en variables de entorno. Nunca en el codigo.")
        pipe.add_text("b.md", "El DAG ejecuta tareas en paralelo con concurrencia limitada.")
        ev = evaluate_retrieval(pipe, [("claves API entorno", "a.md"), ("DAG paralelo concurrencia", "b.md")], k=2)
        self.assertEqual(ev["recall_at_k"], 1.0)
        self.assertEqual(ev["mrr"], 1.0)
        self.assertEqual(ev["n_consultas"], 2)
        ev2 = evaluate_retrieval(pipe, [("zzz qqq", "a.md")], k=1)
        self.assertLessEqual(ev2["recall_at_k"], 1.0)


if __name__ == "__main__":
    unittest.main()
