"""Backend Vertex AI / Gemini con credenciales por defecto de la aplicacion (ADC).

Solo stdlib (urllib). Las credenciales NUNCA se escriben ni se loguean:
se obtienen en runtime por uno de estos mecanismos, en orden:
  1. metadata de GCE (cuenta de servicio de la VM): header Metadata-Flavor;
  2. CLI ``gcloud auth application-default print-access-token``;
  3. archivo ADC ``~/.config/gcloud/application_default_credentials.json``
     (flujo de refresh token contra oauth2.googleapis.com).

El token va solo en el header Authorization de la llamada a la API de Vertex.
``transport`` es inyectable para tests (no se hace red en los tests).
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

DEFAULT_LOCATION = "us-central1"
ADC_FILE_ENV = "GOOGLE_APPLICATION_CREDENTIALS"
DEFAULT_ADC_PATH = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GCE_METADATA_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"


class ADCError(RuntimeError):
    pass


def _http_json(url: str, *, method: str = "GET", body: dict | None = None, headers: dict | None = None, timeout: float = 10.0, transport: Optional[Callable] = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    opener = transport or urllib.request.urlopen
    with opener(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def token_desde_metadata(*, timeout: float = 3.0, transport: Optional[Callable] = None) -> Optional[str]:
    """Token desde el metadata server de GCE (solo existe dentro de GCE/GKE)."""
    try:
        req = urllib.request.Request(GCE_METADATA_URL, headers={"Metadata-Flavor": "Google"})
        opener = transport or urllib.request.urlopen
        with opener(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))["access_token"]
    except Exception:
        return None


def token_desde_gcloud(*, timeout: float = 10.0) -> Optional[str]:
    try:
        r = subprocess.run(
            ["gcloud", "auth", "application-default", "print-access-token"],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def token_desde_adc_file(path: str | Path | None = None, *, timeout: float = 10.0, transport: Optional[Callable] = None, environ: dict | None = None) -> Optional[str]:
    """Refresh-token flow del archivo ADC (no requiere gcloud instalado)."""
    env = os.environ if environ is None else environ
    p = Path(path) if path else Path(env.get(ADC_FILE_ENV, DEFAULT_ADC_PATH))
    if not p.exists():
        return None
    try:
        cred = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if cred.get("type") != "authorized_user" or not cred.get("refresh_token"):
        return None
    body = {
        "client_id": cred["client_id"],
        "client_secret": cred["client_secret"],
        "refresh_token": cred["refresh_token"],
        "grant_type": "refresh_token",
    }
    try:
        resp = _http_json(OAUTH_TOKEN_URL, method="POST", body=body, timeout=timeout, transport=transport)
        return resp.get("access_token")
    except Exception:
        return None


def obtener_token_adc(*, timeout: float = 10.0, transport: Optional[Callable] = None, environ: dict | None = None) -> str:
    """Obtiene un access token por ADC (metadata GCE -> gcloud -> archivo ADC)."""
    tok = token_desde_metadata(timeout=min(timeout, 3.0), transport=transport)
    if tok:
        return tok
    tok = token_desde_gcloud(timeout=timeout)
    if tok:
        return tok
    tok = token_desde_adc_file(timeout=timeout, transport=transport, environ=environ)
    if tok:
        return tok
    raise ADCError("no hay credenciales ADC: ni metadata GCE, ni gcloud, ni archivo ADC (GOOGLE_APPLICATION_CREDENTIALS)")


class VertexBackend:
    """Backend LLM contra la API generativa de Vertex AI (Gemini) via REST.

    Implements ``LLMBackend``: ``complete(prompt, *, system, model, seed)``.
    """

    def __init__(
        self,
        project: str,
        *,
        location: str = DEFAULT_LOCATION,
        model: str = "gemini-2.0-flash",
        token_provider: Callable[[], str] = obtener_token_adc,
        transport: Optional[Callable] = None,
        timeout: float = 60.0,
        endpoint: str | None = None,
    ):
        if not project:
            raise ValueError("project es obligatorio (o pasa GOOGLE_CLOUD_PROJECT en env)")
        self.project = project
        self.location = location
        self.default_model = model
        self.token_provider = token_provider
        self.transport = transport
        self.timeout = timeout
        self.endpoint = endpoint or (
            f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}"
            f"/publishers/google/models/{model}:generateContent"
        )

    @classmethod
    def from_env(cls, *, environ: dict | None = None, **kw) -> "VertexBackend":
        env = os.environ if environ is None else environ
        project = env.get("GOOGLE_CLOUD_PROJECT") or env.get("GCLOUD_PROJECT") or ""
        return cls(
            project,
            location=env.get("VERTEX_LOCATION", DEFAULT_LOCATION),
            model=env.get("VERTEX_MODEL", "gemini-2.0-flash"),
            **kw,
        )

    def _url(self, model: str) -> str:
        if ":generateContent" in self.endpoint:
            base = self.endpoint.split(":generateContent")[0]
            return f"{base.split('/models/')[0]}/models/{model}:generateContent"
        return self.endpoint

    def complete(self, prompt: str, *, system: str = "", model: str = "", seed: int = 0) -> str:
        model = model or self.default_model
        token = self.token_provider()
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"candidateCount": 1, "temperature": 0.0 if seed == 0 else 0.7},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        resp = _http_json(
            self._url(model),
            method="POST",
            body=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.timeout,
            transport=self.transport,
        )
        try:
            parts = resp["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"respuesta de Vertex invalida: {str(e)}; claves={list(resp)[:8]}") from e

    def __repr__(self) -> str:
        return f"VertexBackend(project={self.project!r}, location={self.location!r}, model={self.default_model!r})"
