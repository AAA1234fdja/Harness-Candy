"""Watch mode: detectar archivos cambiados y re-ejecutar lo afectado (v3 §4.3 watch, changed-only).

``snapshot(dir, globs)`` toma una foto (ruta -> hash sha256 + mtime).
``diff_snapshots(antes, despues)`` devuelve {'added': [...], 'modified': [...],
'deleted': [...]}.
``WatchRunner`` hace poll cada intervalo y llama a ``on_change(changes)``.

Uso tipico: vigilar ``src/`` y ``tests/`` y re-correr el golden set cuando
cambie codigo; o vigilar un directorio de datos para reindexar el RAG.
"""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

DEFAULT_GLOBS = ("**/*.py", "**/*.json", "**/*.md", "**/*.toml", "**/*.yml")


def _hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for bloque in iter(lambda: f.read(65536), b""):
            h.update(bloque)
    return h.hexdigest()


def snapshot(directory: str | Path, globs: Iterable[str] = DEFAULT_GLOBS, *, exclude: Iterable[str] = (".git", "__pycache__", ".venv", "node_modules", ".harness_cache", "traces", "runs")) -> dict[str, dict]:
    """Foto del directorio: {ruta_rel: {'sha256':..., 'mtime':..., 'size':...}}."""
    root = Path(directory)
    out: dict[str, dict] = {}
    for g in globs:
        for p in root.glob(g):
            if not p.is_file():
                continue
            rel = str(p.relative_to(root))
            if any(seg in exclude for seg in p.parts):
                continue
            st = p.stat()
            out[rel] = {"sha256": _hash_file(p), "mtime": st.st_mtime, "size": st.st_size}
    return out


def diff_snapshots(antes: dict[str, dict], despues: dict[str, dict]) -> dict[str, list[str]]:
    """Compara dos fotos y devuelve los cambios por categoria."""
    a, d = set(antes), set(despues)
    return {
        "added": sorted(d - a),
        "deleted": sorted(a - d),
        "modified": sorted(p for p in (a & d) if antes[p]["sha256"] != despues[p]["sha256"]),
    }


def changed_since(antes: dict[str, dict], directory: str | Path, globs: Iterable[str] = DEFAULT_GLOBS) -> dict[str, list[str]]:
    """Atajo: compara una foto anterior con el estado actual del directorio."""
    return diff_snapshots(antes, snapshot(directory, globs))


@dataclass
class WatchEvent:
    ts: float
    changes: dict[str, list[str]]

    def to_dict(self) -> dict:
        return {"ts": self.ts, "changes": self.changes, "total": sum(len(v) for v in self.changes.values())}

    @property
    def hay_cambios(self) -> bool:
        return any(self.changes.values())


class WatchRunner:
    """Bucle de polling que llama a ``on_change`` cuando hay cambios."""

    def __init__(
        self,
        directory: str | Path,
        on_change: Callable[[WatchEvent], None],
        *,
        globs: Iterable[str] = DEFAULT_GLOBS,
        interval_s: float = 1.0,
    ):
        self.directory = Path(directory)
        self.on_change = on_change
        self.globs = tuple(globs)
        self.interval_s = interval_s
        self._ultima: dict[str, dict] = snapshot(self.directory, self.globs)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.eventos: list[WatchEvent] = []

    def poll_once(self, *, now: float | None = None) -> Optional[WatchEvent]:
        """Una pasada de polling; devuelve el evento si hubo cambios."""
        ahora = snapshot(self.directory, self.globs)
        cambios = diff_snapshots(self._ultima, ahora)
        if any(cambios.values()):
            ev = WatchEvent(ts=now if now is not None else time.time(), changes=cambios)
            self.eventos.append(ev)
            self._ultima = ahora
            self.on_change(ev)
            return ev
        self._ultima = ahora
        return None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()

        def _loop():
            while not self._stop.is_set():
                try:
                    self.poll_once()
                except Exception:  # noqa: BLE001 - watch nunca tumba el proceso
                    pass
                self._stop.wait(self.interval_s)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


def resumen_cambios(ev: "WatchEvent", *, max_items: int = 10) -> str:
    """Resumen legible (ES) de un evento de cambios."""
    partes = []
    for tipo in ("added", "modified", "deleted"):
        items = ev.changes.get(tipo, [])
        if items:
            partes.append(f"{tipo}: {len(items)} -> {', '.join(items[:max_items])}" + (" ..." if len(items) > max_items else ""))
    return "; ".join(partes) if partes else "sin cambios"


def diff_contenido(antes: dict[str, dict], despues: dict[str, dict], ruta: str, *, max_lineas: int = 10) -> str:
    """Diff linea a linea (textdiff) del contenido de ``ruta`` entre dos snapshots."""
    from .textdiff import resumen_diff

    a = antes.get(ruta, {}).get("contenido", "")
    b = despues.get(ruta, {}).get("contenido", "")
    return resumen_diff(a, b, max_lineas=max_lineas)


class DebouncedWatchRunner(WatchRunner):
    """WatchRunner con debounce: espera ``debounce_s`` en silencio antes de emitir."""

    def __init__(self, directory, on_change, *, debounce_s: float = 0.5, **kw):
        super().__init__(directory, on_change, **kw)
        self.debounce_s = debounce_s
        self._ultimo_cambio = 0.0

    def poll_once(self, *, now: float | None = None) -> Optional[WatchEvent]:
        ev = super().poll_once(now=now)
        if ev is None:
            return None
        ahora = now if now is not None else time.time()
        if ahora - self._ultimo_cambio < self.debounce_s:
            return None  # se emitira en la siguiente pasada tras el silencio
        self._ultimo_cambio = ahora
        return ev
