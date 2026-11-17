"""Backends LLM reales (model-agnostic), solo con la librería estándar.

`OpenAICompatibleBackend` habla con cualquier API compatible con
OpenAI Chat Completions (p. ej. xkiro, LiteLLM gateway, Ollama, vLLM...).

Reglas de seguridad (seccion 9/13 del diseno):
* la API key NUNCA se escribe en el codigo ni en el repo: se lee de una
  variable de entorno (por defecto ``XKIRO_API_KEY``);
* el endpoint es configurable (``XKIRO_BASE_URL``), por defecto
  ``https://api.xkiro.ai/v1``;
* hay timeout estricto y los errores HTTP se reportan sin filtrar la clave.

Uso:
    export XKIRO_API_KEY="sk-..."          # en TU entorno, no en el repo
    export XKIRO_BASE_URL="https://api.xkiro.ai/v1"   # opcional
    export XKIRO_MODEL="nombre-del-modelo"            # opcional

    from harness_candy.backends import OpenAICompatibleBackend
    backend = OpenAICompatibleBackend()
    print(backend.complete("Hola, ¿que puedes hacer?", system="Eres conciso."))
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

DEFAULT_BASE_URL = "https://api.xkiro.ai/v1"


class BackendError(RuntimeError):
    pass


class OpenAICompatibleBackend:
    """Backend LLM contra un endpoint OpenAI-compatible (/chat/completions)."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key_env: str = "XKIRO_API_KEY",
        model_env: str = "XKIRO_MODEL",
        default_model: str = "",
        timeout: float = 60.0,
        temperature: float = 0.2,
    ):
        self.base_url = (
            base_url or os.environ.get("XKIRO_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key_env = api_key_env
        self.default_model = default_model or os.environ.get(model_env, "")
        self.timeout = timeout
        self.temperature = temperature

    def _api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "").strip()
        if not key:
            raise BackendError(
                f"falta la variable de entorno {self.api_key_env}: "
                f"export {self.api_key_env}='sk-...' (nunca la guardes en el repo)"
            )
        return key

    def complete(self, prompt: str, *, system: str = "", model: str = "", seed: int = 0) -> str:
        """Devuelve el contenido de la primera eleccion del chat completion."""
        model = model or self.default_model
        if not model:
            raise BackendError(
                "no hay modelo: pasa model=... o exporta XKIRO_MODEL='nombre-del-modelo'"
            )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if seed:
            payload["seed"] = seed  # reproducibilidad cuando el proveedor lo soporta
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key()}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", "replace")[:300]
            raise BackendError(f"{self.base_url} respondio HTTP {e.code}: {detalle}") from e
        except urllib.error.URLError as e:
            raise BackendError(f"no se pudo contactar {self.base_url}: {e.reason}") from e
        try:
            self.last_usage = data.get("usage", {}) or {}
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise BackendError(f"respuesta inesperada de {self.base_url}: {str(data)[:300]}") from e
