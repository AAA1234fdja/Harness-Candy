"""Autenticacion y rate limit del servidor HTTP (checklist v3 §10.2, §5.8).

``TokenAuth``: si la variable de entorno ``HARNESS_API_TOKEN`` esta definida,
toda peticion (salvo ``/health``) debe llevar ``Authorization: Bearer <token>``;
la comparacion es en tiempo constante (``hmac.compare_digest``). El token vive
solo en el entorno, nunca en el repo ni en logs.

``IpRateLimiter``: limite de peticiones por IP/cliente en ventana deslizante
(por defecto 120/min) para evitar abuso del endpoint local.
"""
from __future__ import annotations

import hmac
import os
import threading
import time
from typing import Optional

DEFAULT_TOKEN_ENV = "HARNESS_API_TOKEN"


class TokenAuth:
    def __init__(self, token: str | None = None, *, env: str = DEFAULT_TOKEN_ENV):
        self.token = token if token is not None else os.environ.get(env, "")
        self.env = env

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def check_header(self, authorization: str | None) -> bool:
        """True si el header Authorization trae el token correcto (o auth off)."""
        if not self.enabled:
            return True
        if not authorization:
            return False
        parts = authorization.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return False
        return hmac.compare_digest(parts[1].strip().encode(), self.token.encode())


class IpRateLimiter:
    """Limite de tasa por clave (p. ej. IP del cliente) en ventana deslizante."""

    def __init__(self, *, limit: int = 120, window_s: float = 60.0):
        self.limit = limit
        self.window_s = window_s
        self._stamps: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, *, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        with self._lock:
            stamps = [s for s in self._stamps.get(key, []) if now - s < self.window_s]
            if len(stamps) >= self.limit:
                self._stamps[key] = stamps
                return False
            stamps.append(now)
            self._stamps[key] = stamps
            return True

    def remaining(self, key: str, *, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        with self._lock:
            stamps = [s for s in self._stamps.get(key, []) if now - s < self.window_s]
            return max(0, self.limit - len(stamps))

    def stats(self) -> dict:
        with self._lock:
            return {"clientes": len(self._stamps), "limit": self.limit, "window_s": self.window_s}
