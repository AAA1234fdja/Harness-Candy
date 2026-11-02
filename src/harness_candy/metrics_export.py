"""Exportacion de metricas: formato Prometheus y spans OTLP/JSON (v3 §11.1).

``prometheus_text``: expone las metricas de una corrida en el formato de
texto de Prometheus (para un /metrics raspado por un Prometheus real).

``otlp_spans``: convierte entradas de TraceLog en spans OTLP/JSON (HTTP),
listos para un collector OTLP (``OtlpExporter`` los envia por POST; por
defecto desactivado: el collector es responsabilidad del despliegue).
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Iterable, Optional


def _sanitize_name(name: str) -> str:
    out = []
    for ch in name:
        out.append(ch if (ch.isalnum() or ch == "_") else "_")
    s = "".join(out)
    return s if s and not s[0].isdigit() else "m_" + s


def prometheus_text(metrics: dict[str, Any], *, labels: dict[str, str] | None = None, prefix: str = "harness_candy") -> str:
    """Renderiza un dict de metricas como texto exposition de Prometheus.

    Solo valores numericos; los dict/list/None se ignoran (o cuentan como info).
    """
    labels = labels or {}
    label_str = ""
    if labels:
        label_str = "{" + ",".join(f'{k}="{str(v).replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}"' for k, v in sorted(labels.items())) + "}"
    lines: list[str] = []
    for key, value in sorted(metrics.items()):
        name = _sanitize_name(f"{prefix}_{key}")
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            lines.append(f"{name}{label_str} {value}")
        elif isinstance(value, dict):
            for sub, subv in sorted(value.items()):
                if isinstance(subv, (int, float)) and not isinstance(subv, bool):
                    sub_labels = dict(labels)
                    sub_labels[key] = str(sub)
                    ls = "{" + ",".join(f'{k}="{v}"' for k, v in sorted(sub_labels.items())) + "}"
                    lines.append(f"{name}{ls} {subv}")
        # str/None/list: no son metricas numericas
    return "\n".join(lines) + ("\n" if lines else "")


def otlp_spans(trace_entries: Iterable[dict], *, service_name: str = "harness-candy") -> dict:
    """Convierte entradas TraceLog (JSONL) en un payload OTLP/JSON de traces."""
    spans = []
    for e in trace_entries:
        attrs = {
            "run_id": str(e.get("run_id", "")),
            "task_id": str(e.get("task_id", "")),
            "model": str(e.get("model", "")),
            "seed": int(e.get("seed", 0) or 0),
            "harness": str(e.get("harness", "")),
            "phase": str(e.get("phase", "")),
            "q": float(e.get("q", 0.0) or 0.0),
            "verdict": str(e.get("verdict", "")),
        }
        ts = e.get("ts", time.time())
        spans.append(
            {
                "traceId": _hexid(str(e.get("run_id", "")), 32),
                "spanId": _hexid(str(e.get("msg_id", e.get("task_id", "")) + str(ts)), 16),
                "name": f"harness.{e.get('phase', 'run')}",
                "kind": "SPAN_KIND_INTERNAL",
                "startTimeUnixNano": int(float(ts) * 1e9),
                "endTimeUnixNano": int(float(ts) * 1e9),
                "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in attrs.items() if v != ""],
            }
        )
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service_name}}]},
                "scopeSpans": [{"scope": {"name": "harness-candy"}, "spans": spans}],
            }
        ]
    }


def _hexid(text: str, size: int) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:size]


class OtlpExporter:
    """Exporta spans OTLP/JSON a un collector por HTTP POST (mejor esfuerzo)."""

    def __init__(self, endpoint: str, *, timeout: float = 5.0, enabled: bool = True):
        self.endpoint = endpoint
        self.timeout = timeout
        self.enabled = enabled
        self.enviados = 0
        self.errores: list[str] = []

    def export(self, trace_entries: Iterable[dict], *, service_name: str = "harness-candy") -> bool:
        if not self.enabled:
            return False
        payload = json.dumps(otlp_spans(trace_entries, service_name=service_name), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint, data=payload, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
            self.enviados += 1
            return True
        except Exception as exc:  # noqa: BLE001 - exportar no debe romper la corrida
            self.errores.append(f"{type(exc).__name__}: {exc}")
            return False
