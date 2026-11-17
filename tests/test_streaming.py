"""Tests del bus de eventos y del formato SSE."""
import json
import unittest

import _path  # noqa: F401
from harness_candy.streaming import (
    EVT_NODE_END,
    EVT_RUN_END,
    EVT_RUN_START,
    EventBus,
    EventCollector,
    SseBroadcaster,
    sse,
)


class TestEventBus(unittest.TestCase):
    def test_emit_y_suscripcion(self):
        bus = EventBus()
        recibidos = []
        bus.subscribe(EVT_RUN_START, lambda ev, data: recibidos.append((ev, data)))
        bus.emit(EVT_RUN_START, {"run_id": "r1"})
        self.assertEqual(recibidos, [(EVT_RUN_START, {"run_id": "r1"})])

    def test_wildcard_recibe_todo(self):
        bus = EventBus()
        todos = []
        bus.subscribe("*", lambda ev, data: todos.append(ev))
        bus.emit(EVT_RUN_START, {})
        bus.emit(EVT_NODE_END, {})
        self.assertEqual(todos, [EVT_RUN_START, EVT_NODE_END])

    def test_historial_acotado_y_filtrado(self):
        bus = EventBus(history_limit=5)
        for i in range(10):
            bus.emit(EVT_NODE_END, {"i": i})
        self.assertEqual(len(bus.history()), 5)
        self.assertEqual(len(bus.history(EVT_RUN_START)), 0)
        self.assertEqual(len(bus.history(EVT_NODE_END)), 5)

    def test_unsubscribe(self):
        bus = EventBus()
        recibidos = []
        unsub = bus.subscribe(EVT_RUN_START, lambda ev, data: recibidos.append(data))
        bus.emit(EVT_RUN_START, {"a": 1})
        unsub()
        bus.emit(EVT_RUN_START, {"a": 2})
        self.assertEqual(recibidos, [{"a": 1}])

    def test_suscriptor_que_falla_no_rompe_y_se_registra(self):
        bus = EventBus()
        bus.subscribe(EVT_RUN_END, lambda ev, data: 1 / 0)
        ok = []
        bus.subscribe(EVT_RUN_END, lambda ev, data: ok.append(data))
        bus.emit(EVT_RUN_END, {"x": 1})
        self.assertEqual(ok, [{"x": 1}])
        self.assertEqual(len(bus.errors), 1)
        self.assertIn("ZeroDivisionError", bus.errors[0])

    def test_emit_devuelve_entrada_con_ts(self):
        bus = EventBus()
        entry = bus.emit("custom", {"a": 1})
        self.assertEqual(entry["event"], "custom")
        self.assertIn("ts", entry)

    def test_clear(self):
        bus = EventBus()
        bus.emit("x", {})
        bus.errors.append("e")
        bus.clear()
        self.assertEqual(bus.history(), [])
        self.assertEqual(bus.errors, [])


class TestSse(unittest.TestCase):
    def test_formato_sse(self):
        frame = sse("node_end", {"task_id": "t-1"}, event_id=7)
        self.assertIn("id: 7", frame)
        self.assertIn("event: node_end", frame)
        self.assertIn('data: {"task_id": "t-1"}', frame)
        self.assertTrue(frame.endswith("\n\n"))

    def test_sse_json_valido_en_data(self):
        frame = sse("alert", {"msg": "50%"})
        linea = [l for l in frame.splitlines() if l.startswith("data: ")][0][6:]
        self.assertEqual(json.loads(linea), {"msg": "50%"})


class TestCollectorYBroadcaster(unittest.TestCase):
    def test_collector(self):
        bus = EventBus()
        col = EventCollector(bus)
        bus.emit(EVT_RUN_START, {"r": 1})
        bus.emit(EVT_NODE_END, {"t": 2})
        self.assertEqual(len(col.events(EVT_RUN_START)), 1)
        self.assertEqual(col.events(EVT_NODE_END)[0], {"t": 2})
        col.close()
        bus.emit(EVT_RUN_END, {})
        self.assertEqual(len(col.received), 2)

    def test_broadcaster_reparte_frames(self):
        bus = EventBus()
        bc = SseBroadcaster(bus)
        q = bc.connect()
        bus.emit(EVT_RUN_START, {"r": 1})
        frame = q.get(timeout=2)
        self.assertIn("event: run_start", frame)
        bc.disconnect(q)
        bus.emit(EVT_RUN_END, {})
        self.assertTrue(q.empty())
        bc.close()


if __name__ == "__main__":
    unittest.main()
