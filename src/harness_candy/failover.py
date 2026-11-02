"""Failover automatico entre backends/modelos (riesgo R11, checklist v3 §5.6).

``FailoverBackend`` envuelve una lista ordenada de backends (p. ej. un
modelo primario de xkiro y uno secundario local/vLLM). Si un backend falla
(``BackendError`` u otra excepcion configurable), se reintenta con el
siguiente, dentro del presupuesto de tiempo total.

Cada intento queda registrado (``attempts``) para auditoria y metricas:
nunca se propaga la API key en los errores.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from .backends import BackendError


class AllBackendsFailed(BackendError):
    """Todos los backends fallaron; ``attempts`` detalla cada intento."""

    def __init__(self, attempts: list[dict]):
        resumen = "; ".join(f"{a['backend']}: {a['error'][:120]}" for a in attempts)
        super().__init__(f"todos los backends fallaron: {resumen}")
        self.attempts = attempts


class FailoverBackend:
    """Backend compuesto con failover por prioridad."""

    def __init__(
        self,
        backends: list,
        *,
        names: list[str] | None = None,
        timeout_total: float = 120.0,
        retry_on: tuple[type[BaseException], ...] = (BackendError, OSError),
    ):
        if not backends:
            raise ValueError("se necesita al menos un backend")
        self.backends = list(backends)
        self.names = names or [getattr(b, "name", None) or type(b).__name__ + f"[{i}]" for i, b in enumerate(self.backends)]
        self.timeout_total = timeout_total
        self.retry_on = retry_on
        self.attempts: list[dict] = []
        self.last_usage: dict = {}

    def complete(self, prompt: str, *, system: str = "", model: str = "", seed: int = 0) -> str:
        inicio = time.time()
        self.attempts = []
        for name, backend in zip(self.names, self.backends):
            if time.time() - inicio > self.timeout_total:
                raise AllBackendsFailed(self.attempts + [{"backend": name, "error": "timeout total agotado"}])
            try:
                out = backend.complete(prompt, system=system, model=model, seed=seed)
                self.attempts.append({"backend": name, "ok": True, "latencia_s": round(time.time() - inicio, 3)})
                self.last_usage = getattr(backend, "last_usage", {}) or {}
                self.last_usage["failover_backend"] = name
                return out
            except self.retry_on as exc:  # type: ignore[misc]
                self.attempts.append({"backend": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        raise AllBackendsFailed(self.attempts)

    def healthy(self) -> list[str]:
        """Backends que estan configurados (p. ej. con API key presente)."""
        out = []
        for name, backend in zip(self.names, self.backends):
            check = getattr(backend, "_api_key", None)
            if check is None:
                out.append(name)
            else:
                try:
                    check()
                    out.append(name)
                except BackendError:
                    pass
        return out

    def stats(self) -> dict[str, Any]:
        return {
            "backends": self.names,
            "intentos": self.attempts,
            "sanos": self.healthy(),
        }
