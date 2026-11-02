"""Multi-backend real: Anthropic + Ollama (local) + selector costo/latencia/calidad.

Capitulo 01/20 del documento exhaustivo: un harness productivo opera sobre
varios proveedores. Aqui:

- ``AnthropicBackend``: API de Anthropic (/v1/messages, header x-api-key +
  anthropic-version). La clave SOLO sale de ``ANTHROPIC_API_KEY`` (env).
- ``OllamaBackend``: Ollama local (POST /api/generate, sin clave; base_url via
  ``OLLAMA_BASE_URL`` o localhost:11434). Modo local-first.
- ``SelectorModelos``: elige modelo por rol segun politica
  (``costo`` | ``latencia`` | ``calidad``) usando metricas registradas
  (costo/1k, p95 de latencia, q medio). Integra bench_latencia.
- ``FailoverPorModelo``: lista de (modelo, backend) y reintenta en orden con
  reintentos (retry.retry_call); seleccion automatica previa por el selector.

Todo stdlib; ``transport`` inyectable en cada backend para tests sin red.
Las claves NUNCA se escriben a disco ni a logs.
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from .backends import BackendError
from .retry import retry_call

Transport = Callable[[urllib.request.Request, float], Any]


def _post_json(url: str, body: dict, headers: dict, timeout: float, transport: Optional[Transport]) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 method="POST", headers={"Content-Type": "application/json", **headers})
    opener = transport or urllib.request.urlopen
    try:
        with opener(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", "replace")[:300]
        raise BackendError(f"{url} respondio HTTP {e.code}: {detalle}") from e
    except urllib.error.URLError as e:
        raise BackendError(f"no se pudo contactar {url}: {e.reason}") from e
    except OSError as e:
        raise BackendError(f"no se pudo contactar {url}: {e}") from e


class AnthropicBackend:
    """Backend contra la API de Anthropic (Messages). Clave solo en env."""

    def __init__(
        self,
        *,
        api_key_env: str = "ANTHROPIC_API_KEY",
        base_url: str = "https://api.anthropic.com",
        default_model: str = "",
        model_env: str = "ANTHROPIC_MODEL",
        max_tokens: int = 1024,
        timeout: float = 60.0,
        transport: Optional[Transport] = None,
        environ: Optional[dict] = None,
    ) -> None:
        self.api_key_env = api_key_env
        self.base_url = base_url.rstrip("/")
        self._environ = environ if environ is not None else dict(os.environ)
        self.default_model = default_model or self._environ.get(model_env, "claude-sonnet-4-5")
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.transport = transport
        self.last_usage: dict = {}

    def _api_key(self) -> str:
        key = self._environ.get(self.api_key_env, "").strip()
        if not key:
            raise BackendError(f"falta {self.api_key_env} en el entorno (nunca en el repo)")
        return key

    def complete(self, prompt: str, *, system: str = "", model: str = "", seed: int = 0) -> str:
        model = model or self.default_model
        body = {
            "model": model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        headers = {
            "x-api-key": self._api_key(),
            "anthropic-version": "2023-06-01",
        }
        data = _post_json(f"{self.base_url}/v1/messages", body, headers, self.timeout, self.transport)
        try:
            self.last_usage = data.get("usage", {}) or {}
            contenido = data["content"]
            return "".join(b.get("text", "") for b in contenido if b.get("type") == "text")
        except (KeyError, IndexError, TypeError) as e:
            raise BackendError(f"respuesta inesperada de Anthropic: {str(data)[:300]}") from e


class OllamaBackend:
    """Backend contra Ollama local (sin clave). Modo local-first/offline."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        default_model: str = "",
        model_env: str = "OLLAMA_MODEL",
        timeout: float = 120.0,
        transport: Optional[Transport] = None,
        environ: Optional[dict] = None,
    ) -> None:
        self._environ = environ if environ is not None else dict(os.environ)
        self.base_url = (base_url or self._environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        self.default_model = default_model or self._environ.get(model_env, "llama3.1")
        self.timeout = timeout
        self.transport = transport

    def disponible(self, *, timeout: float = 3.0) -> bool:
        req = urllib.request.Request(f"{self.base_url}/api/tags")
        opener = self.transport or urllib.request.urlopen
        try:
            with opener(req, timeout=timeout) as resp:
                return 200 <= getattr(resp, "status", 200) < 300
        except Exception:  # noqa: BLE001 - offline es un estado valido
            return False

    def complete(self, prompt: str, *, system: str = "", model: str = "", seed: int = 0) -> str:
        model = model or self.default_model
        body: dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
        if system:
            body["system"] = system
        if seed:
            body["options"] = {"seed": seed, "temperature": 0.0}
        data = _post_json(f"{self.base_url}/api/generate", body, {}, self.timeout, self.transport)
        try:
            return data["response"]
        except (KeyError, TypeError) as e:
            raise BackendError(f"respuesta inesperada de Ollama: {str(data)[:300]}") from e


# ------------------------------------------------------------- selector
@dataclass
class MetricasModelo:
    alias: str
    costo_per_1k: float = 0.0
    p95_s: float = 0.0
    q_media: float = 0.0


class SelectorModelos:
    """Elige el modelo por rol segun politica: costo | latencia | calidad.

    Las metricas se registran con ``registrar`` (p.ej. desde bench_latencia +
    costo del pool + q de corridas previas). Sin metricas, cae al primero.
    """

    POLITICAS = ("costo", "latencia", "calidad")

    def __init__(self, politica: str = "calidad") -> None:
        if politica not in self.POLITICAS:
            raise ValueError(f"politica desconocida {politica!r}; use {self.POLITICAS}")
        self.politica = politica
        self._metricas: dict[str, MetricasModelo] = {}

    def registrar(self, alias: str, *, costo_per_1k: float = 0.0, p95_s: float = 0.0, q_media: float = 0.0) -> None:
        self._metricas[alias] = MetricasModelo(alias, costo_per_1k, p95_s, q_media)

    def actualizar_desde_bench(self, alias: str, bench: dict, *, costo_per_1k: float = 0.0, q_media: float = 0.0) -> None:
        self.registrar(alias, costo_per_1k=costo_per_1k, p95_s=float(bench.get("p95", 0.0)), q_media=q_media)

    def elegir(self, candidatos: Sequence[str]) -> str:
        """Devuelve el alias ganador segun la politica (menor costo/latencia, mayor q)."""
        if not candidatos:
            raise ValueError("sin candidatos")
        con_metricas = [a for a in candidatos if a in self._metricas]
        if not con_metricas:
            return candidatos[0]
        if self.politica == "costo":
            return min(con_metricas, key=lambda a: self._metricas[a].costo_per_1k)
        if self.politica == "latencia":
            return min(con_metricas, key=lambda a: self._metricas[a].p95_s)
        return max(con_metricas, key=lambda a: self._metricas[a].q_media)


# ------------------------------------------------------------- failover por modelo
class FailoverPorModelo:
    """Intenta (modelo, backend) en orden hasta que uno responda.

    ``opciones``: lista de dicts {"modelo": str, "backend": LLMBackend-like}.
    Usa retry_call por opcion (reintentos con backoff) y registra el ganador.
    """

    def __init__(self, opciones: Sequence[dict], *, max_reintentos: int = 2, backoff_base: float = 0.5) -> None:
        if not opciones:
            raise ValueError("se necesita al menos una opcion (modelo, backend)")
        self.opciones = list(opciones)
        self.max_reintentos = max(1, max_reintentos)
        self.backoff_base = backoff_base
        self.intentos: list[str] = []
        self.ganador: Optional[str] = None

    def complete(self, prompt: str, *, system: str = "", model: str = "", seed: int = 0) -> str:
        errores: list[str] = []
        for op in self.opciones:
            modelo = model or op.get("modelo", "")
            backend = op["backend"]
            try:
                out = retry_call(
                    lambda: backend.complete(prompt, system=system, model=modelo, seed=seed),
                    attempts=self.max_reintentos,
                    base_delay=self.backoff_base,
                    retry_on=(BackendError, OSError),
                )
                self.ganador = f"{modelo}"
                self.intentos.append(f"ok:{modelo}")
                return out
            except Exception as e:  # noqa: BLE001 - pasa a la siguiente opcion
                errores.append(f"{modelo}: {type(e).__name__}: {e}")
                self.intentos.append(f"fallo:{modelo}")
        raise BackendError("todas las opciones fallaron: " + " | ".join(errores))

    def resumen(self) -> dict:
        return {"ganador": self.ganador, "intentos": self.intentos}


def backends_disponibles(*, environ: Optional[dict] = None) -> dict[str, Any]:
    """Detecta backends reales disponibles segun el entorno (sin tocar red).

    Devuelve {"anthropic": AnthropicBackend|None, "ollama": OllamaBackend,
    "vertex": VertexBackend|None} con los que tengan credencial/config.
    """
    from .vertex import VertexBackend

    env = dict(os.environ) if environ is None else dict(environ)
    out: dict[str, Any] = {"anthropic": None, "ollama": OllamaBackend(environ=env), "vertex": None}
    if env.get("ANTHROPIC_API_KEY"):
        out["anthropic"] = AnthropicBackend(environ=env)
    if env.get("GOOGLE_CLOUD_PROJECT"):
        try:
            out["vertex"] = VertexBackend.from_env(environ=env)
        except Exception:  # noqa: BLE001 - sin ADC no hay vertex
            out["vertex"] = None
    return out


def failover_desde_env(
    modelos: Optional[Sequence[str]] = None,
    *,
    environ: Optional[dict] = None,
    max_reintentos: int = 2,
) -> FailoverPorModelo:
    """Construye un FailoverPorModelo con los proveedores disponibles en env.

    Orden: anthropic -> vertex -> ollama (local-first al final como fallback
    offline). ``modelos`` permite fijar el modelo por proveedor.
    """
    disp = backends_disponibles(environ=environ)
    opciones: list[dict] = []
    modelos = list(modelos or [])
    for i, nombre in enumerate(("anthropic", "vertex", "ollama")):
        backend = disp.get(nombre)
        if backend is None:
            continue
        modelo = modelos[i] if i < len(modelos) else ""
        opciones.append({"modelo": modelo, "backend": backend})
    if not opciones:
        raise BackendError("no hay ningun proveedor disponible: define ANTHROPIC_API_KEY, GOOGLE_CLOUD_PROJECT+ADC, u OLLAMA_BASE_URL")
    return FailoverPorModelo(opciones, max_reintentos=max_reintentos)


# ------------------------------------------------------------- presupuesto de tokens
class TokenBudget:
    """Presupuesto de tokens/energia por dominio (green AI, cap. 09).

    Asigna un tope de tokens por dominio; ``registrar_gasto`` acumula y
    alerta al 80% (warning) y bloquea al 100% (critical) salvo que se
    permita excedente. Stdlib-only.
    """

    def __init__(self, topes: dict[str, int], *, permitir_excedente: bool = False) -> None:
        if not topes or any(v <= 0 for v in topes.values()):
            raise ValueError("topes deben ser positivos por dominio")
        self.topes = dict(topes)
        self.gastado: dict[str, int] = {d: 0 for d in topes}
        self.permitir_excedente = permitir_excedente
        self.alertas: list[dict] = []

    def registrar_gasto(self, dominio: str, tokens: int) -> dict:
        if dominio not in self.topes:
            raise KeyError(f"dominio sin presupuesto: {dominio!r}")
        if tokens < 0:
            raise ValueError("tokens negativos")
        self.gastado[dominio] += tokens
        uso = self.gastado[dominio] / self.topes[dominio]
        estado = "ok"
        if uso >= 1.0:
            estado = "agotado"
            self.alertas.append({"dominio": dominio, "nivel": "critical", "uso": round(uso, 4)})
        elif uso >= 0.8:
            estado = "warning"
            self.alertas.append({"dominio": dominio, "nivel": "warning", "uso": round(uso, 4)})
        return {"dominio": dominio, "gastado": self.gastado[dominio], "tope": self.topes[dominio],
                "uso": round(uso, 4), "estado": estado,
                "permitido": estado != "agotado" or self.permitir_excedente}

    def resumen(self) -> dict:
        return {d: {"gastado": g, "tope": self.topes[d], "uso": round(g / self.topes[d], 4)} for d, g in self.gastado.items()}
