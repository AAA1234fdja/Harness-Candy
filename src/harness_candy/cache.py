"""Cache en disco de respuestas del modelo (checklist v3 §8.3, §13.3).

Reduce costo y latencia reutilizando respuestas identicas (mismo modelo,
system, prompt y seed). La clave es un hash SHA-256 del pedido: nunca se
guarda la API key. El cache es por defecto en ``.harness_cache/`` y se puede
desactivar (``enabled=False``) o limpiar (``clear()``, CLI ``cache --clear``).

Las entradas expiran (TTL) y el tamano se puede acotar (LRU simple por
tiempo de modificacion).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional


def cache_key(model: str, system: str, prompt: str, seed: int) -> str:
    payload = json.dumps(
        {"model": model, "system": system, "prompt": prompt, "seed": seed},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResponseCache:
    """Cache clave-valor en disco para respuestas LLM."""

    def __init__(self, directory: str | Path = ".harness_cache", *, ttl_s: float = 7 * 86400.0, max_entries: int = 5000):
        self.dir = Path(directory)
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self.hits = 0
        self.misses = 0

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def get(self, key: str, *, now: float | None = None) -> Optional[str]:
        p = self._path(key)
        if not p.exists():
            self.misses += 1
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.misses += 1
            return None
        now = now if now is not None else time.time()
        if now - float(data.get("ts", 0)) > self.ttl_s:
            self.misses += 1
            try:
                p.unlink()
            except OSError:
                pass
            return None
        self.hits += 1
        return data.get("response")

    def put(self, key: str, response: str, *, now: float | None = None) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        now = now if now is not None else time.time()
        self._path(key).write_text(
            json.dumps({"ts": now, "response": response}, ensure_ascii=False),
            encoding="utf-8",
        )
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        files = sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        while len(files) > self.max_entries:
            victim = files.pop(0)
            try:
                victim.unlink()
            except OSError:
                pass

    def clear(self) -> int:
        """Borra todas las entradas; devuelve cuantas habia."""
        n = 0
        if self.dir.exists():
            for p in self.dir.glob("*.json"):
                try:
                    p.unlink()
                    n += 1
                except OSError:
                    pass
        return n

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 4) if total else None,
            "entradas": len(list(self.dir.glob("*.json"))) if self.dir.exists() else 0,
            "ttl_s": self.ttl_s,
        }


class CachedBackend:
    """Envuelve un LLMBackend con cache: las respuestas identicas no gastan."""

    def __init__(self, backend, cache: ResponseCache | None = None, *, enabled: bool = True):
        self.backend = backend
        self.cache = cache or ResponseCache()
        self.enabled = enabled
        self.last_usage: dict = {}

    def complete(self, prompt: str, *, system: str = "", model: str = "", seed: int = 0) -> str:
        model = model or getattr(self.backend, "default_model", "")
        if not self.enabled:
            return self._call(prompt, system=system, model=model, seed=seed)
        key = cache_key(model, system, prompt, seed)
        cached = self.cache.get(key)
        if cached is not None:
            self.last_usage = {"total_tokens": 0, "cached": True}
            return cached
        response = self._call(prompt, system=system, model=model, seed=seed)
        self.cache.put(key, response)
        return response

    def _call(self, prompt: str, *, system: str, model: str, seed: int) -> str:
        out = self.backend.complete(prompt, system=system, model=model, seed=seed)
        self.last_usage = getattr(self.backend, "last_usage", {}) or {}
        return out

    def stats(self) -> dict[str, Any]:
        return self.cache.stats()
