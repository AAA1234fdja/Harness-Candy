"""Reintentos con backoff exponencial y jitter determinista (checklist v3 §4.3).

El DAG ya reintenta nodos con feedback de WEV; este modulo anade la politica
de espera entre reintentos (backoff + jitter) reutilizable por cualquier
componente (backends, herramientas, webhooks de alertas).

El jitter usa ``random.Random(seed)`` para que las corridas con la misma
semilla sean 100% reproducibles (requisito de determinismo del diseno).
"""
from __future__ import annotations

import random
import time
from typing import Any, Callable, Iterable, Optional, TypeVar

T = TypeVar("T")


class RetryExhausted(RuntimeError):
    """Se agotaron los intentos; ``last`` guarda la ultima excepcion."""

    def __init__(self, attempts: int, last: BaseException):
        super().__init__(f"reintentos agotados tras {attempts} intentos: {last}")
        self.attempts = attempts
        self.last = last


def backoff_delays(
    attempts: int,
    *,
    base_delay: float = 0.1,
    max_delay: float = 5.0,
    factor: float = 2.0,
    jitter: float = 0.25,
    seed: int = 0,
) -> list[float]:
    """Genera la lista de esperas (segundos) antes de cada reintento.

    espera_i = min(max_delay, base_delay * factor^i) * (1 +- jitter)
    con la aleatoriedad derivada de ``seed`` (determinista).
    """
    rng = random.Random(seed)
    delays: list[float] = []
    for i in range(max(0, attempts - 1)):
        raw = min(max_delay, base_delay * (factor ** i))
        spread = raw * jitter
        delays.append(max(0.0, raw + rng.uniform(-spread, spread)))
    return delays


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 5.0,
    factor: float = 2.0,
    jitter: float = 0.25,
    seed: int = 0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
) -> T:
    """Ejecuta ``fn`` reintentando ante las excepciones de ``retry_on``.

    ``sleep`` es inyectable para que los tests no duerman de verdad.
    ``on_retry(n_intento, exc, espera_s)`` se llama antes de cada espera.
    Lanza ``RetryExhausted`` si todos los intentos fallan.
    """
    if attempts < 1:
        raise ValueError("attempts debe ser >= 1")
    delays = backoff_delays(attempts, base_delay=base_delay, max_delay=max_delay, factor=factor, jitter=jitter, seed=seed)
    last: BaseException | None = None
    for intento in range(1, attempts + 1):
        try:
            return fn()
        except retry_on as exc:  # type: ignore[misc]
            last = exc
            if intento == attempts:
                break
            espera = delays[intento - 1]
            if on_retry is not None:
                on_retry(intento, exc, espera)
            sleep(espera)
    raise RetryExhausted(attempts, last if last is not None else RuntimeError("sin excepcion"))


def retryable(
    attempts: int = 3,
    **kwargs: Any,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorador: ``@retryable(attempts=3)`` sobre una funcion."""
    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args: Any, **kw: Any) -> T:
            return retry_call(lambda: fn(*args, **kw), attempts=attempts, **kwargs)
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return deco
