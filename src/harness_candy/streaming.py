"""Barrido de eventos (event bus) y formato SSE (checklist v3 §5.7, §6.2).

El runner y el servidor publican eventos de progreso (inicio/fin de nodo,
fin de corrida, alertas) para observabilidad en vivo. El bus es sincrono y
tolerante a fallos: un suscriptor que falla no rompe la corrida (se registra
el error en ``errors``).
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Optional

# Eventos estandar del sistema
EVT_RUN_START = "run_start"
EVT_RUN_END = "run_end"
EVT_NODE_START = "node_start"
EVT_NODE_END = "node_end"
EVT_ALERT = "alert"
EVT_PROBE = "probe"
EVT_TOOL_CALL = "tool_call"

ALL_EVENTS = (EVT_RUN_START, EVT_RUN_END, EVT_NODE_START, EVT_NODE_END, EVT_ALERT, EVT_PROBE, EVT_TOOL_CALL)

Subscriber = Callable[[str, dict], None]


class EventBus:
    """Bus de eventos pub/sub con historial acotado."""

    def __init__(self, *, history_limit: int = 1000):
        self._subs: dict[str, list[Subscriber]] = {}
        self._lock = threading.Lock()
        self._history: list[tuple[float, str, dict]] = []
        self._history_limit = history_limit
        self.errors: list[str] = []

    def subscribe(self, event: str, cb: Subscriber) -> Callable[[], None]:
        """Suscribe ``cb`` a ``event`` (o ``"*"`` para todos). Devuelve unsubscribe."""
        with self._lock:
            self._subs.setdefault(event, []).append(cb)
            self._subs.setdefault("*", [])  # asegurar entrada

        def unsubscribe() -> None:
            with self._lock:
                if event in self._subs and cb in self._subs[event]:
                    self._subs[event].remove(cb)

        return unsubscribe

    def emit(self, event: str, data: dict | None = None) -> dict:
        """Publica un evento; devuelve la entrada creada (con ts)."""
        entry = {"ts": time.time(), "event": event, "data": data or {}}
        with self._lock:
            self._history.append((entry["ts"], event, entry["data"]))
            if len(self._history) > self._history_limit:
                self._history = self._history[-self._history_limit:]
            subs = list(self._subs.get(event, [])) + list(self._subs.get("*", []))
        for cb in subs:
            try:
                cb(event, entry["data"])
            except Exception as exc:  # noqa: BLE001 - tolerante a fallos
                self.errors.append(f"{event}: {type(exc).__name__}: {exc}")
        return entry

    def history(self, event: str | None = None) -> list[dict]:
        with self._lock:
            return [
                {"ts": ts, "event": ev, "data": data}
                for ts, ev, data in self._history
                if event is None or ev == event
            ]

    def clear(self) -> None:
        with self._lock:
            self._history.clear()
            self.errors.clear()


class EventCollector:
    """Suscriptor de pruebas: acumula todos los eventos recibidos."""

    def __init__(self, bus: EventBus):
        self.received: list[tuple[str, dict]] = []
        self._unsub = bus.subscribe("*", lambda ev, data: self.received.append((ev, data)))

    def close(self) -> None:
        self._unsub()

    def events(self, name: str) -> list[dict]:
        return [data for ev, data in self.received if ev == name]


def sse(event: str, data: dict, *, event_id: int | None = None) -> str:
    """Formatea un evento como Server-Sent Events (para el endpoint /events)."""
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    payload = json.dumps(data, ensure_ascii=False, default=str)
    for chunk in payload.splitlines() or [""]:
        lines.append(f"data: {chunk}")
    return "\n".join(lines) + "\n\n"


class SseBroadcaster:
    """Convierte un EventBus en cola de eventos SSE para clientes conectados."""

    def __init__(self, bus: EventBus, *, max_queue: int = 500):
        import queue

        self.bus = bus
        self._queues: list["queue.Queue[str]"] = []
        self._lock = threading.Lock()
        self._max_queue = max_queue
        self._counter = 0
        self._unsub = bus.subscribe("*", self._on_event)

    def _on_event(self, event: str, data: dict) -> None:
        self._counter += 1
        frame = sse(event, data, event_id=self._counter)
        with self._lock:
            for q in list(self._queues):
                try:
                    q.put_nowait(frame)
                except Exception:
                    self._queues.remove(q)

    def connect(self) -> "object":
        import queue

        q: "queue.Queue[str]" = queue.Queue(maxsize=self._max_queue)
        with self._lock:
            self._queues.append(q)
        return q

    def disconnect(self, q) -> None:
        with self._lock:
            if q in self._queues:
                self._queues.remove(q)

    def close(self) -> None:
        self._unsub()
