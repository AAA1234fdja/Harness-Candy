"""Tests de alertas de presupuesto (umbrales 50/80/100%) y sumideros."""
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import _path  # noqa: F401
from harness_candy.alerts import Alert, BudgetMonitor, LogSink, MultiSink, WebhookSink, quality_alert
from harness_candy.harness import Budget
from harness_candy.streaming import EventBus


class Capturador:
    def __init__(self):
        self.alertas = []

    def emit(self, alert):
        self.alertas.append(alert)


class TestBudgetMonitor(unittest.TestCase):
    def test_umbrales_se_emiten_una_vez(self):
        cap = Capturador()
        budget = Budget(total=1000, beta=1.0)
        mon = BudgetMonitor(budget, cap)
        # 40%: nada
        self.assertEqual(mon.notify_spent(400), [])
        # 55%: cruza el 50%
        a = mon.notify_spent(550)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0].data["threshold"], 0.5)
        self.assertEqual(a[0].level, "info")
        # 60% otra vez: no re-emite el 50%
        self.assertEqual(mon.notify_spent(600), [])
        # 85%: cruza el 80%
        a = mon.notify_spent(850)
        self.assertEqual([x.level for x in a], ["warning"])
        # 100%: critico
        a = mon.notify_spent(1000)
        self.assertEqual([x.level for x in a], ["critical"])
        self.assertEqual(len(cap.alertas), 3)
        # 120%: ya todos cruzados, nada nuevo
        self.assertEqual(mon.notify_spent(1200), [])

    def test_extra_spent(self):
        cap = Capturador()
        mon = BudgetMonitor(Budget(total=100, beta=1.0), cap)
        a = mon.notify_spent(30, extra_spent=25)  # 55%
        self.assertEqual(len(a), 1)

    def test_usa_spent_adapt_del_budget_si_no_se_pasa_spent(self):
        cap = Capturador()
        budget = Budget(total=100, beta=1.0)
        budget.spent_adapt = 60.0
        mon = BudgetMonitor(budget, cap)
        a = mon.notify_spent()
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0].data["threshold"], 0.5)

    def test_emite_en_event_bus(self):
        bus = EventBus()
        mon = BudgetMonitor(Budget(total=10, beta=1.0), Capturador(), event_bus=bus)
        mon.notify_spent(10)
        eventos = bus.history("alert")
        self.assertEqual(len(eventos), 3)  # 50, 80, 100
        self.assertEqual(eventos[0]["data"]["kind"], "budget")

    def test_reset(self):
        cap = Capturador()
        mon = BudgetMonitor(Budget(total=100, beta=1.0), cap)
        mon.notify_spent(100)
        mon.reset()
        self.assertEqual(len(mon.notify_spent(60)), 1)


class TestSinks(unittest.TestCase):
    def test_log_sink_a_stream(self):
        buf = io.StringIO()
        sink = LogSink(stream=buf)
        sink.emit(Alert(ts=1.0, level="warning", kind="budget", message="msg", data={"x": 1}))
        texto = buf.getvalue()
        self.assertIn("[WARNING]", texto)
        self.assertIn("msg", texto)
        self.assertIn('"x": 1', texto)

    def test_webhook_sink_recibe_post(self):
        recibidos = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                recibidos.append(json.loads(self.rfile.read(n).decode("utf-8")))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            sink = WebhookSink(f"http://127.0.0.1:{srv.server_port}/hook")
            sink.emit(Alert(ts=1.0, level="critical", kind="budget", message="100%", data={"spent": 10}))
            self.assertEqual(sink.enviadas, 1)
            self.assertEqual(recibidos[0]["message"], "100%")
            # el webhook nunca envia claves: solo el dict de la alerta
            self.assertNotIn("Authorization", json.dumps(recibidos))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_webhook_caido_no_rompe(self):
        sink = WebhookSink("http://127.0.0.1:1/cerrado", timeout=0.5)
        sink.emit(Alert(ts=1.0, level="info", kind="budget", message="x"))  # no lanza
        self.assertEqual(sink.enviadas, 0)
        self.assertEqual(len(sink.errores), 1)

    def test_multi_sink_tolerante(self):
        class Roto:
            def emit(self, alert):
                raise RuntimeError("boom")

        cap = Capturador()
        multi = MultiSink([Roto(), cap])
        multi.emit(Alert(ts=1, level="info", kind="quality", message="ok"))
        self.assertEqual(len(cap.alertas), 1)

    def test_quality_alert(self):
        cap = Capturador()
        bus = EventBus()
        a = quality_alert("warning", "regresion detectada", {"task": "t"}, cap, event_bus=bus)
        self.assertEqual(a.kind, "quality")
        self.assertEqual(len(cap.alertas), 1)
        self.assertEqual(len(bus.history("alert")), 1)


if __name__ == "__main__":
    unittest.main()
