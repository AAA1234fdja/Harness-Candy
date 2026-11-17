"""Metricas del sistema (seccion 10 del PDF / seccion 7 del checklist).

Lo que se mide de verdad: requisitos completados, pruebas superadas,
defectos encontrados tras la integracion, tiempo total, costo de APIs,
consumo de tokens, trabajo duplicado y mantenibilidad.

NO se miden lineas de codigo generadas (el documento lo desaconseja
explicitamente): eso incentiva volumen, no calidad.
"""
from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricsCollector:
    """Acumula metricas de una ejecucion (o varias) de Ely-Cowork."""

    inicio: float = field(default_factory=time.time)
    requisitos_total: int = 0
    requisitos_cumplidos: int = 0
    pruebas_superadas: int = 0
    pruebas_total: int = 0
    defectos: Counter = field(default_factory=Counter)  # por severidad
    costo_adaptacion: float = 0.0
    costo_corridas: float = 0.0
    tokens: int = 0
    tareas_por_kind: Counter = field(default_factory=Counter)
    escaladas: int = 0
    human_review: int = 0
    canceladas: int = 0
    archivos_analizados: int = 0
    archivos_que_compilan: int = 0
    hallazgos_linter: int = 0

    def add_result(self, res, criterios_total: int = 0) -> None:
        """Incorpora el NodeResult de una tarea (con su informe wev)."""
        self.tareas_por_kind[getattr(res, "kind", res.task_id)] += 1
        if res.status == "escalated":
            self.escaladas += 1
        if res.status == "human_review":
            self.human_review += 1
        if res.status == "cancelled":
            self.canceladas += 1
        if res.wev is not None:
            for ok in res.wev.checks.values():
                self.pruebas_total += 1
                if ok:
                    self.pruebas_superadas += 1
            for h in res.wev.hallazgos:
                self.defectos[h.severidad] += 1
                if h.herramienta == "linter":
                    self.hallazgos_linter += 1
        if res.artifact is not None:
            meta = getattr(res.artifact, "meta", {}) or {}
            self.tokens += int(meta.get("tokens", 0) or 0)
            content = getattr(res.artifact, "content", None)
            if isinstance(content, dict):
                self.archivos_analizados += int(content.get("files_scanned", 0) or 0)
                if not content.get("compile_errors"):
                    self.archivos_que_compilan += int(content.get("files_scanned", 0) or 0)
        self.requisitos_total += criterios_total

    def add_criterios(self, criterios) -> None:
        self.requisitos_total += len(criterios)
        self.requisitos_cumplidos += 0  # se cuenta via wev

    def mark_cumplidos(self, cumplidos: int) -> None:
        self.requisitos_cumplidos += cumplidos

    @property
    def trabajo_duplicado(self) -> int:
        """Tareas repetidas (mismo kind ejecutado mas de una vez)."""
        return sum(c - 1 for c in self.tareas_por_kind.values() if c > 1)

    @property
    def mantenibilidad(self) -> float:
        """Indice simple: proporcion de archivos que compilan + linter limpio."""
        if self.archivos_analizados == 0:
            return 1.0
        base = self.archivos_que_compilan / self.archivos_analizados
        return max(0.0, min(1.0, base - 0.01 * self.hallazgos_linter))

    def snapshot(self, duracion: float | None = None, costo_adapt: float = 0.0) -> dict[str, Any]:
        duracion = duracion if duracion is not None else time.time() - self.inicio
        return {
            "requisitos_cumplidos": self.requisitos_cumplidos,
            "requisitos_total": self.requisitos_total,
            "tasa_requisitos": round(self.requisitos_cumplidos / self.requisitos_total, 4) if self.requisitos_total else None,
            "pruebas_superadas": self.pruebas_superadas,
            "pruebas_total": self.pruebas_total,
            "tasa_pruebas": round(self.pruebas_superadas / self.pruebas_total, 4) if self.pruebas_total else None,
            "defectos_por_severidad": dict(self.defectos),
            "defectos_total": sum(self.defectos.values()),
            "tiempo_total_s": round(duracion, 3),
            "costo_adaptacion": round(self.costo_adaptacion + costo_adapt, 4),
            "costo_corridas": round(self.costo_corridas, 4),
            "tokens": self.tokens,
            "trabajo_duplicado": self.trabajo_duplicado,
            "mantenibilidad": round(self.mantenibilidad, 4),
            "escaladas": self.escaladas,
            "human_review": self.human_review,
            "canceladas": self.canceladas,
            "nota": "lineas de codigo generadas NO se usan como metrica (diseno combinado, sec. 10)",
        }
