"""Tests de reportes JUnit XML / HTML / Markdown / JSON."""
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import _path  # noqa: F401
from harness_candy.report import html_report, junit_xml, markdown_report, write_report


def run_de_ejemplo():
    return {
        "run_id": "run-0123456789ab",
        "objetivo": "informe <script>alert(1)</script>",
        "dag_results": {
            "t-1": {"task_id": "t-1", "status": "done", "attempts": 1, "duracion": 0.5, "error": "", "wev": None},
            "t-2": {"task_id": "t-2", "status": "rejected", "attempts": 2, "duracion": 1.0, "error": "fallo WEV",
                    "wev": {"veredicto": "rechazado", "hallazgos": [{"severidad": "alta"}]}},
            "t-3": {"task_id": "t-3", "status": "escalated", "attempts": 1, "duracion": 0.1, "error": "humano", "wev": None},
            "t-4": {"task_id": "t-4", "status": "human_review", "attempts": 0, "duracion": 0.0, "error": "", "wev": None},
        },
        "qs": {"t-1": 1.0, "t-2": 0.2},
        "wev_reports": {},
        "ely_audit": {"q_medio": 0.6},
        "costo_adaptacion": 3.0,
        "trace_path": "traces/x.jsonl",
        "duracion": 1.6,
        "metrics": {"pruebas_superadas": 5, "pruebas_total": 6, "nota": "sin LOC"},
    }


class TestJUnit(unittest.TestCase):
    def test_xml_parseable_y_conteos(self):
        xml = junit_xml(run_de_ejemplo(), suite_name="demo")
        root = ET.fromstring(xml)
        self.assertEqual(root.tag, "testsuite")
        self.assertEqual(root.get("tests"), "4")
        self.assertEqual(root.get("failures"), "1")   # rejected
        self.assertEqual(root.get("errors"), "1")     # escalated
        self.assertEqual(root.get("skipped"), "1")    # human_review
        casos = root.findall("testcase")
        self.assertEqual(len(casos), 4)
        nombres = {c.get("name") for c in casos}
        self.assertEqual(nombres, {"t-1", "t-2", "t-3", "t-4"})
        # t-2 tiene <failure>, t-3 <error>, t-4 <skipped>
        por_nombre = {c.get("name"): c for c in casos}
        self.assertIsNotNone(por_nombre["t-2"].find("failure"))
        self.assertIsNotNone(por_nombre["t-3"].find("error"))
        self.assertIsNotNone(por_nombre["t-4"].find("skipped"))
        self.assertIsNone(por_nombre["t-1"].find("failure"))

    def test_declaracion_xml(self):
        self.assertTrue(junit_xml(run_de_ejemplo()).startswith('<?xml version="1.0"'))


class TestHtml(unittest.TestCase):
    def test_contiene_datos_y_escapa_html(self):
        html = html_report(run_de_ejemplo())
        self.assertIn("run-0123456789ab", html)
        self.assertIn("t-2", html)
        # el objetivo con <script> debe ir escapado
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("pruebas_superadas", html)

    def test_titulo(self):
        self.assertIn("<title>Mi titulo</title>", html_report(run_de_ejemplo(), title="Mi titulo"))


class TestMarkdown(unittest.TestCase):
    def test_tabla(self):
        md = markdown_report(run_de_ejemplo())
        self.assertIn("# Corrida `run-0123456789ab`", md)
        self.assertIn("| `t-1` | done |", md)
        self.assertIn("## Métricas", md)


class TestWriteReport(unittest.TestCase):
    def test_por_extension(self):
        with tempfile.TemporaryDirectory() as td:
            run = run_de_ejemplo()
            for ext, marker in (("xml", "<testsuite"), ("html", "<!doctype html>"), ("md", "# Corrida"), ("json", '"run_id"')):
                p = write_report(run, Path(td) / f"out.{ext}")
                texto = p.read_text(encoding="utf-8")
                self.assertIn(marker, texto, ext)

    def test_fmt_explicito(self):
        with tempfile.TemporaryDirectory() as td:
            p = write_report(run_de_ejemplo(), Path(td) / "salida.txt", fmt="md")
            self.assertIn("# Corrida", p.read_text(encoding="utf-8"))

    def test_formato_desconocido(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                write_report(run_de_ejemplo(), Path(td) / "out.pdf")

    def test_json_es_el_run(self):
        with tempfile.TemporaryDirectory() as td:
            p = write_report(run_de_ejemplo(), Path(td) / "out.json")
            self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["run_id"], "run-0123456789ab")


if __name__ == "__main__":
    unittest.main()
