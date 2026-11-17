"""Notificaciones de eventos del sistema (workflow, campaign, watch), stdlib.

Sinks:
  - ``CallbackSink``: llama a una funcion Python.
  - ``JsonlSink``: escribe eventos JSONL en un archivo (auditoria).
  - ``WebhookSink``: POST JSON a una URL (urllib, timeout corto; sin red no falla
    el sistema: captura el error y lo registra como evento de entrega fallida).

``Notifier`` hace fanout a varios sinks con manejo de errores por sink
(un sink caido no tumba a los demas). Los secretos en las URLs se enmascaran
en los logs (crypto.mask_secret).
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .crypto import mask_secret


@dataclass
class Notification:
    evento: str
    severidad: str = "info"  # info | warning | critica
    datos: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"ts": round(self.ts, 3), "evento": self.evento, "severidad": self.severidad, "datos": self.datos}


class CallbackSink:
    def __init__(self, fn: Callable[[Notification], None]):
        self.fn = fn

    def enviar(self, n: Notification) -> None:
        self.fn(n)


class JsonlSink:
    """Escribe cada notificacion como una linea JSON en ``path``."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def enviar(self, n: Notification) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(n.to_dict(), ensure_ascii=False, default=str) + "\n")


class WebhookSink:
    """POST JSON a una URL. Falla en silencio (registra el error) si no hay red."""

    def __init__(self, url: str, *, timeout: float = 5.0, headers: dict | None = None):
        self.url = url
        self.timeout = timeout
        self.headers = headers or {}
        self.entregas_ok = 0
        self.entregas_fallo = 0

    def enviar(self, n: Notification) -> None:
        cuerpo = json.dumps(n.to_dict(), ensure_ascii=False, default=str).encode("utf-8")
        req = urllib.request.Request(self.url, data=cuerpo, headers={"Content-Type": "application/json", **self.headers}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if 200 <= resp.status < 300:
                    self.entregas_ok += 1
                else:
                    self.entregas_fallo += 1
        except Exception:
            self.entregas_fallo += 1

    def descripcion_enmascarada(self) -> str:
        # enmascara credenciales en la URL para logs
        return mask_secret(self.url, visibles=12)


class Notifier:
    """Fanout de notificaciones a varios sinks; un sink caido no afecta a los otros."""

    def __init__(self, sinks: Optional[list] = None):
        self.sinks: list = list(sinks or [])
        self.errores: list[dict] = []
        self.enviadas = 0

    def add(self, sink) -> None:
        self.sinks.append(sink)

    def notify(self, evento: str, datos: dict | None = None, *, severidad: str = "info") -> Notification:
        n = Notification(evento=evento, severidad=severidad, datos=datos or {})
        for sink in self.sinks:
            try:
                sink.enviar(n)
            except Exception as e:  # noqa: BLE001 - un sink no tumba la notificacion
                self.errores.append({"sink": type(sink).__name__, "error": f"{type(e).__name__}: {e}"})
        self.enviadas += 1
        return n

    def stats(self) -> dict:
        return {"enviadas": self.enviadas, "sinks": len(self.sinks), "errores": len(self.errores), "detalle_errores": self.errores[-10:]}


def notificar_evento_watch(notifier: Notifier, ev) -> Notification:
    """Traduce un WatchEvent a notificacion (severidad segun haya borrados)."""
    sev = "critica" if ev.changes.get("deleted") else ("warning" if ev.changes.get("modified") else "info")
    return notifier.notify("watch_change", {"cambios": ev.changes}, severidad=sev)
