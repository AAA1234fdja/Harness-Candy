"""Alertas de presupuesto y de calidad (checklist v3 §13.2, §11).

``BudgetMonitor`` vigila el gasto acumulado frente al presupuesto total y
emite alertas al cruzar los umbrales 50% / 80% / 100% (una vez cada uno).
Los sumideros (sinks) son enchufables: log local, webhook HTTP (opcional,
nunca envia claves) o cualquiera que implemente ``emit(alert)``.

Las alertas tambien alimentan el bus de eventos (``streaming.EventBus``) si
se le pasa uno.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from .harness import Budget


class AlertSink(Protocol):
    def emit(self, alert: "Alert") -> None: ...


@dataclass
class Alert:
    ts: float
    level: str  # "info" | "warning" | "critical"
    kind: str  # "budget" | "quality" | "security" | "regression"
    message: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"ts": self.ts, "level": self.level, "kind": self.kind, "message": self.message, "data": self.data}


class LogSink:
    """Sumidero por defecto: imprime la alerta en stderr."""

    def __init__(self, stream=None):
        import sys

        self.stream = stream or sys.stderr

    def emit(self, alert: Alert) -> None:
        print(f"[{alert.level.upper()}] {alert.kind}: {alert.message} {json.dumps(alert.data, ensure_ascii=False, default=str)}", file=self.stream)


class WebhookSink:
    """Sumidero webhook (POST JSON). NUNCA envia claves ni secretos: solo el dict de la alerta."""

    def __init__(self, url: str, *, timeout: float = 5.0, headers: dict | None = None):
        self.url = url
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.enviadas = 0
        self.errores: list[str] = []

    def emit(self, alert: Alert) -> None:
        body = json.dumps(alert.to_dict(), ensure_ascii=False, default=str).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, method="POST", headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
            self.enviadas += 1
        except Exception as exc:  # noqa: BLE001 - el webhook no debe romper la corrida
            self.errores.append(f"{type(exc).__name__}: {exc}")


class MultiSink:
    def __init__(self, sinks: list[AlertSink]):
        self.sinks = list(sinks)

    def emit(self, alert: Alert) -> None:
        for s in self.sinks:
            try:
                s.emit(alert)
            except Exception:  # noqa: BLE001
                pass


class BudgetMonitor:
    """Vigila ``budget.spent_adapt`` (y gasto adicional) contra ``budget.total``."""

    DEFAULT_THRESHOLDS = (0.5, 0.8, 1.0)

    def __init__(
        self,
        budget: Budget,
        sink: AlertSink,
        *,
        thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
        event_bus=None,
    ):
        self.budget = budget
        self.sink = sink
        self.thresholds = tuple(sorted(thresholds))
        self._crossed: set[float] = set()
        self.bus = event_bus
        self.alerts: list[Alert] = []

    def notify_spent(self, spent: float | None = None, *, extra_spent: float = 0.0, now: float | None = None) -> list[Alert]:
        """Evalua el gasto actual y emite alertas por cada umbral cruzado."""
        spent = (self.budget.spent_adapt if spent is None else spent) + extra_spent
        total = self.budget.total
        ratio = spent / total if total > 0 else 1.0
        now = now if now is not None else time.time()
        nuevas: list[Alert] = []
        for th in self.thresholds:
            if ratio >= th and th not in self._crossed:
                self._crossed.add(th)
                level = "info" if th < 0.8 else ("warning" if th < 1.0 else "critical")
                alert = Alert(
                    ts=now,
                    level=level,
                    kind="budget",
                    message=f"presupuesto al {int(th * 100)}%: gastado {round(spent, 3)} de {total}",
                    data={"spent": round(spent, 4), "total": total, "ratio": round(ratio, 4), "threshold": th},
                )
                self.alerts.append(alert)
                self.sink.emit(alert)
                if self.bus is not None:
                    self.bus.emit("alert", alert.to_dict())
                nuevas.append(alert)
        return nuevas

    def reset(self) -> None:
        self._crossed.clear()
        self.alerts.clear()


def quality_alert(level: str, message: str, data: dict, sink: AlertSink, *, event_bus=None, now: float | None = None) -> Alert:
    alert = Alert(ts=now if now is not None else time.time(), level=level, kind="quality", message=message, data=data)
    sink.emit(alert)
    if event_bus is not None:
        event_bus.emit("alert", alert.to_dict())
    return alert
