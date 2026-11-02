"""Constructores por defecto del sistema (usados por CLI, servidor y ejemplos).

Construye un ``CoworkRunner`` completo con backend "scripted" (determinista,
sin red ni claves) o con un backend real (p. ej. ``OpenAICompatibleBackend``
para xkiro, que lee la clave solo de variables de entorno).

Esto evita repetir el cableado en cada ejemplo/CLI y da un punto unico para
cambiar la configuracion por defecto.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .agents import Agent, LLMBackend, ScriptedBackend, SecurityScanAgent
from .components import ELY, ISA, WEV, XEV, YEV, ZEV
from .harness import Budget, HarnessStore
from .memory import KnowledgeMemory
from .pool import LIGHT_TAG, POWER_TAG, ModelPool, PoolEntry
from .quality import RegressionGuard
from .runner import CoworkRunner
from .security import SecurityGate


def make_pool(*, with_real_backend: bool = False) -> ModelPool:
    """Pool por defecto: un modelo ligero (XEV/ZEV/WEV) y uno potente (ISA/ELY).

    Las claves se referencian por variable de entorno (nunca en el repo).
    """
    pool = ModelPool()
    secret_env = "XKIRO_API_KEY" if with_real_backend else "DEMO_KEY_FLASH"
    secret_env_power = "XKIRO_API_KEY" if with_real_backend else "DEMO_KEY_OPUS"
    pool.add(
        PoolEntry("flash-1", "modelo-ligero", secret_env, cost_per_1k=0.0001, roles={"xev", "zev", "wev"}, tag=LIGHT_TAG)
    )
    pool.add(
        PoolEntry("opus-1", "modelo-potente", secret_env_power, cost_per_1k=0.015, roles={"isa", "ely"}, tag=POWER_TAG)
    )
    return pool


def make_backend(kind: str = "scripted") -> LLMBackend:
    """Backend por defecto para demos/CLI sin red: responde JSON estructurado."""
    if kind == "scripted":
        def _fn(prompt: str, *, system: str = "", model: str = "", seed: int = 0) -> str:
            import json

            return json.dumps(
                {
                    "respuesta": "ok (backend scripted)",
                    "modelo": model,
                    "seed": seed,
                    "prompt_len": len(prompt),
                },
                ensure_ascii=False,
            )

        return ScriptedBackend(_fn)
    if kind == "xkiro":
        from .backends import OpenAICompatibleBackend

        return OpenAICompatibleBackend()
    raise ValueError(f"backend desconocido: {kind!r} (usa 'scripted' o 'xkiro')")


def build_runner(
    trace_dir: str | Path = "traces",
    *,
    backend: LLMBackend | None = None,
    backend_kind: str = "scripted",
    store: HarnessStore | None = None,
    budget: Budget | None = None,
    max_concurrency: int = 4,
    use_security_scan_agent: bool = True,
) -> CoworkRunner:
    """Construye el CoworkRunner completo con valores por defecto seguros."""
    backend = backend or make_backend(backend_kind)
    pool = make_pool(with_real_backend=(backend_kind == "xkiro"))
    store = store or HarnessStore()
    budget = budget or Budget(total=10_000, beta=0.5, k=2, m=3)
    knowledge = KnowledgeMemory()
    security = SecurityGate()
    # ISA sin backend LLM usa el planificador determinista (heuristica), que
    # genera DAGs reales para objetivos de seguridad; con LLM real se puede
    # pasar otro ISA (ver docs/DISENO_COMBINADO.md).
    isa = ISA(backend=None, model="modelo-potente")
    yev = YEV(pool)
    zev = ZEV(knowledge)
    if use_security_scan_agent:
        agent: Agent = SecurityScanAgent("XEV", "modelo-ligero", backend)
    else:
        agent = Agent("XEV", "modelo-ligero", backend)
    xev = XEV({"XEV": agent}, security)
    wev = WEV(security)
    ely = ELY(RegressionGuard(), knowledge)
    return CoworkRunner(
        pool=pool,
        store=store,
        budget=budget,
        isa=isa,
        yev=yev,
        zev=zev,
        xev=xev,
        wev=wev,
        ely=ely,
        trace_dir=trace_dir,
        max_concurrency=max_concurrency,
    )
