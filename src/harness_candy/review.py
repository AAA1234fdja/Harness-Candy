"""Review automatico de PRs (WEV sobre un diff): alcance + sintaxis + hallazgos (v3 §5.8).

``ReviewAgent.review_diff`` analiza el diff de un pull request:
- ``check_diff_paths``: el diff solo toca rutas permitidas (allowlist);
- sintaxis: los archivos .py añadidos parsean con ``ast`` (sin ejecutarlos);
- secretos/PII en el diff: se bloquean (capa de seguridad de salida).

Devuelve un ``WevMessage`` (aprobado/rechazado) con checks medibles, para
enchufar en CI como puerta de revisión (quien produce no acepta su trabajo).
"""
from __future__ import annotations

import ast
import re
from typing import Optional, Sequence

from .components import check_diff_paths
from .protocols import Envelope, Hallazgo, WevMessage
from .security import scan_pii

DEFAULT_ALLOWED_PREFIXES = ("src/", "tests/", "docs/", "examples/", "benchmarks/")

_ADDED_FILE_RE = re.compile(r"^\+\+\+ b/(?P<path>\S+)$", re.MULTILINE)
_ADDED_LINE_RE = re.compile(r"^\+(?!\+\+)(?P<line>.*)$", re.MULTILINE)


class ReviewAgent:
    """Agente WEV especializado en revisar diffs de PR."""

    def __init__(self, *, allowed_prefixes: Sequence[str] = DEFAULT_ALLOWED_PREFIXES, security=None):
        self.allowed_prefixes = list(allowed_prefixes)
        self.security = security

    def _added_py_blocks(self, diff_text: str) -> dict[str, str]:
        """Reconstruye el contenido anadido de cada .py del diff (lineas '+')."""
        bloques: dict[str, list[str]] = {}
        actual: Optional[str] = None
        for linea in diff_text.splitlines():
            m = _ADDED_FILE_RE.match(linea)
            if m:
                actual = m.group("path")
                if actual.endswith(".py"):
                    bloques.setdefault(actual, [])
                continue
            if linea.startswith("+++") or linea.startswith("---"):
                continue
            if linea.startswith("+") and actual and actual.endswith(".py"):
                bloques[actual].append(linea[1:])
            elif linea.startswith((" ", "-")) and not linea.startswith("---"):
                # contexto o borrado: no cambia el archivo actual salvo que sea otro header
                if not linea.startswith("@@") and linea.startswith("diff "):
                    actual = None
        return {p: "\n".join(ls) for p, ls in bloques.items() if ls}

    def review_diff(self, diff_text: str, *, task_id: str = "pr-review", origen: str = "PR", destino: str = "WEV") -> WevMessage:
        hallazgos: list[Hallazgo] = []
        en_alcance, hallazgos_alcance = check_diff_paths(diff_text, self.allowed_prefixes)
        hallazgos.extend(hallazgos_alcance)

        # secretos/PII en el diff (lineas anadidas)
        for m in _ADDED_LINE_RE.finditer(diff_text):
            for h in scan_pii(m.group("line")):
                hallazgos.append(Hallazgo("review_diff", "critica", f"secreto/PII anadido: {h}"))

        # sintaxis de los .py anadidos (parseo local, sin ejecutar nada)
        sintaxis_ok = True
        for path, contenido in self._added_py_blocks(diff_text).items():
            try:
                ast.parse(contenido)
            except SyntaxError as e:
                sintaxis_ok = False
                hallazgos.append(Hallazgo("review_sintaxis", "alta", f"{path}: SyntaxError linea {e.lineno}: {e.msg}"))

        checks = {
            "diff_en_alcance": en_alcance,
            "sintaxis_ok": sintaxis_ok,
            "sin_secretos_en_diff": not any(h.severidad == "critica" for h in hallazgos),
        }
        criticos = [h for h in hallazgos if h.severidad in ("alta", "critica")]
        veredicto = "aprobado" if all(checks.values()) and not criticos else "rechazado"
        env = Envelope(protocol="wev", task_id=task_id, origen=origen, destino=destino)
        return WevMessage(
            envelope=env,
            artefacto_id=task_id,
            checks=checks,
            veredicto=veredicto,
            hallazgos=hallazgos,
            accion="rechazar PR" if veredicto == "rechazado" else "aprobar PR",
        )
