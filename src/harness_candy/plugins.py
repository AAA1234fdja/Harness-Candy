"""Registro de plugins y hooks (checklist v3 §4.8, §17.1).

Puntos de extension oficiales del sistema. Un plugin implementa uno o mas
hooks con estos nombres (todos opcionales):

    on_run_start(run_id, objetivo, ctx)
    on_node_start(node_dict, ctx)
    on_node_end(node_dict, result_dict, ctx)
    on_run_end(run_dict, ctx)
    on_alert(alert_dict, ctx)
    on_tool_call(tool, args, result, ctx)

Los hooks se ejecutan siempre dentro de try/except: un plugin roto NO rompe
la corrida (se registra en ``registry.errors`` y se deshabilita).

Descubrimiento: un modulo de terceros expone ``PLUGIN = MiPlugin()`` o una
funcion ``register(registry)``; se carga con ``registry.load_module("mi_paquete.plugins")``.
"""
from __future__ import annotations

import importlib
import threading
from typing import Any, Callable, Optional, Protocol

HOOK_NAMES = (
    "on_run_start",
    "on_node_start",
    "on_node_end",
    "on_run_end",
    "on_alert",
    "on_tool_call",
)


class Plugin(Protocol):
    name: str


class PluginRegistry:
    """Registro de plugins con hooks tolerantes a fallos."""

    def __init__(self):
        self._plugins: dict[str, Any] = {}
        self._enabled: dict[str, bool] = {}
        self._lock = threading.Lock()
        self.errors: list[str] = []

    # -- registro -----------------------------------------------------------
    def register(self, plugin: Any, *, name: str | None = None) -> None:
        pname = name if name is not None else getattr(plugin, "name", None) or type(plugin).__name__
        if not pname:
            raise ValueError("el plugin necesita atributo 'name' o pasar name=")
        with self._lock:
            self._plugins[pname] = plugin
            self._enabled[pname] = True

    def unregister(self, name: str) -> None:
        with self._lock:
            self._plugins.pop(name, None)
            self._enabled.pop(name, None)

    def enable(self, name: str) -> None:
        with self._lock:
            if name in self._enabled:
                self._enabled[name] = True

    def disable(self, name: str) -> None:
        with self._lock:
            if name in self._enabled:
                self._enabled[name] = False

    def names(self) -> list[str]:
        return sorted(self._plugins)

    def is_enabled(self, name: str) -> bool:
        return self._enabled.get(name, False)

    def get(self, name: str) -> Any:
        return self._plugins.get(name)

    # -- descubrimiento -----------------------------------------------------
    def load_module(self, module_name: str) -> list[str]:
        """Importa un modulo y registra su ``PLUGIN`` o llama a su ``register``."""
        mod = importlib.import_module(module_name)
        loaded: list[str] = []
        plugin = getattr(mod, "PLUGIN", None)
        if plugin is not None:
            self.register(plugin)
            loaded.append(getattr(plugin, "name", type(plugin).__name__))
        reg_fn = getattr(mod, "register", None)
        if callable(reg_fn):
            reg_fn(self)
            loaded.append(f"{module_name}.register")
        if not loaded:
            raise ImportError(f"{module_name} no expone PLUGIN ni register(registry)")
        return loaded

    # -- ejecucion de hooks ---------------------------------------------------
    def run_hook(self, hook: str, *args: Any, ctx: dict | None = None) -> list[Any]:
        """Ejecuta ``hook`` en todos los plugins habilitados; devuelve resultados.

        Un plugin que falla queda registrado en ``errors`` y se deshabilita
        (fail-safe: el sistema sigue operando).
        """
        if hook not in HOOK_NAMES:
            raise ValueError(f"hook desconocido: {hook!r}; validos: {HOOK_NAMES}")
        results: list[Any] = []
        with self._lock:
            items = [(n, p) for n, p in self._plugins.items() if self._enabled.get(n, False)]
        for name, plugin in items:
            fn = getattr(plugin, hook, None)
            if fn is None:
                continue
            try:
                results.append(fn(*args, ctx=ctx or {}))
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"{name}.{hook}: {type(exc).__name__}: {exc}")
                with self._lock:
                    self._enabled[name] = False
        return results

    def to_dict(self) -> dict:
        return {
            "plugins": [
                {"name": n, "enabled": self._enabled.get(n, False), "hooks": [h for h in HOOK_NAMES if hasattr(p, h)]}
                for n, p in sorted(self._plugins.items())
            ],
            "errors": list(self.errors),
        }


class CompositePlugin:
    """Plugin compuesto: agrega varios plugins bajo un mismo nombre."""

    def __init__(self, name: str, plugins: list):
        self.name = name
        self._plugins = plugins

    def __getattr__(self, hook: str):
        if hook not in HOOK_NAMES:
            raise AttributeError(hook)

        def call(*args: Any, ctx: dict | None = None) -> list[Any]:
            out = []
            for p in self._plugins:
                fn = getattr(p, hook, None)
                if fn is not None:
                    out.append(fn(*args, ctx=ctx or {}))
            return out

        return call


class LoggingPlugin:
    """Plugin de ejemplo: registra los eventos del ciclo en una lista."""

    name = "logging"

    def __init__(self):
        self.log: list[tuple[str, dict]] = []

    def on_run_start(self, run_id: str, objetivo: str, ctx: dict | None = None) -> None:
        self.log.append(("run_start", {"run_id": run_id, "objetivo": objetivo}))

    def on_node_end(self, node: dict, result: dict, ctx: dict | None = None) -> None:
        self.log.append(("node_end", {"task_id": node.get("task_id"), "status": result.get("status")}))

    def on_run_end(self, run: dict, ctx: dict | None = None) -> None:
        self.log.append(("run_end", {"run_id": run.get("run_id"), "duracion": run.get("duracion")}))
