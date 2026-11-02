"""Internacionalizacion minima (ES/EN) para mensajes del sistema (v3 §15 docs ES).

  - ``t(lang, clave, **ctx)``: traduce e interpola; fallback a 'es'.
  - ``detectar_idioma(texto)``: heuristica por stopwords (es/en/otro).
  - ``agregar_mensajes(lang, dict)``: ampliar el catalogo en runtime.
"""
from __future__ import annotations

import re
from typing import Any

MESSAGES: dict[str, dict[str, str]] = {
    "es": {
        "ok": "correcto",
        "error": "error",
        "run_ok": "corrida {run_id} completada en {duracion}s con q={q}",
        "run_fail": "corrida {run_id} fallo: {error}",
        "aprobado": "aprobado",
        "rechazado": "rechazado",
        "presupuesto_agotado": "presupuesto agotado: gastado {spent} de {total}",
        "secreto_detectado": "posible secreto detectado en {ruta} linea {linea}",
        "golden_ok": "golden '{name}' OK: pass_rate={pass_rate} ({passed}/{total})",
        "workflow_step": "step {step}: {status}",
        "sin_resultados": "sin resultados",
        "cache_hit": "cache hit ({ratio:.0%} de ahorro)",
    },
    "en": {
        "ok": "ok",
        "error": "error",
        "run_ok": "run {run_id} completed in {duracion}s with q={q}",
        "run_fail": "run {run_id} failed: {error}",
        "aprobado": "approved",
        "rechazado": "rejected",
        "presupuesto_agotado": "budget exhausted: spent {spent} of {total}",
        "secreto_detectado": "possible secret detected at {ruta} line {linea}",
        "golden_ok": "golden '{name}' OK: pass_rate={pass_rate} ({passed}/{total})",
        "workflow_step": "step {step}: {status}",
        "sin_resultados": "no results",
        "cache_hit": "cache hit ({ratio:.0%} saved)",
    },
}

_WORD_RE = re.compile(r"[a-záéíóúñ]+", re.IGNORECASE)

_STOP_ES = {"el", "la", "de", "que", "en", "un", "una", "los", "las", "con", "por", "para", "se", "su", "es"}
_STOP_EN = {"the", "of", "and", "to", "in", "a", "an", "is", "for", "on", "with", "that", "this", "are"}


def idiomas() -> list[str]:
    return sorted(MESSAGES)


def t(lang: str, clave: str, **ctx: Any) -> str:
    """Traduce ``clave`` al idioma ``lang`` (fallback 'es') e interpola ctx."""
    catalogo = MESSAGES.get(lang) or MESSAGES["es"]
    plantilla = catalogo.get(clave)
    if plantilla is None:
        plantilla = MESSAGES["es"].get(clave, clave)
    try:
        return plantilla.format(**ctx)
    except (KeyError, IndexError):
        return plantilla


def detectar_idioma(texto: str) -> str:
    """Heuristica: cuenta stopwords de es/en en el texto."""
    palabras = [w.lower() for w in _WORD_RE.findall(texto)]
    if not palabras:
        return "otro"
    es = sum(1 for w in palabras if w in _STOP_ES)
    en = sum(1 for w in palabras if w in _STOP_EN)
    if es == 0 and en == 0:
        return "otro"
    return "es" if es >= en else "en"


def agregar_mensajes(lang: str, mensajes: dict[str, str]) -> None:
    """Anade/actualiza mensajes de un idioma en runtime."""
    MESSAGES.setdefault(lang, {}).update(mensajes)


def traducir_veredicto(veredicto: str, lang: str = "es") -> str:
    return t(lang, veredicto.lower(), **{}) if veredicto.lower() in MESSAGES.get(lang, {}) else veredicto
