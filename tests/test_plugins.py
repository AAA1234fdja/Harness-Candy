"""Tests del registro de plugins y hooks tolerantes a fallos."""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.plugins import HOOK_NAMES, CompositePlugin, LoggingPlugin, PluginRegistry


class PluginDePrueba:
    name = "prueba"

    def __init__(self):
        self.llamadas = []

    def on_run_start(self, run_id, objetivo, ctx=None):
        self.llamadas.append(("start", run_id, objetivo))
        return "inicio"

    def on_run_end(self, run, ctx=None):
        self.llamadas.append(("end", run.get("run_id")))
        return "fin"


class PluginRoto:
    name = "roto"

    def on_run_start(self, run_id, objetivo, ctx=None):
        raise RuntimeError("boom")


class TestRegistro(unittest.TestCase):
    def test_register_get_names(self):
        reg = PluginRegistry()
        p = PluginDePrueba()
        reg.register(p)
        self.assertEqual(reg.names(), ["prueba"])
        self.assertIs(reg.get("prueba"), p)
        self.assertTrue(reg.is_enabled("prueba"))

    def test_nombre_requerido(self):
        reg = PluginRegistry()
        with self.assertRaises(ValueError):
            reg.register(object(), name="")  # nombre vacio explicito
        reg.register(object(), name="con-nombre")
        self.assertIn("con-nombre", reg.names())

    def test_enable_disable(self):
        reg = PluginRegistry()
        p = PluginDePrueba()
        reg.register(p)
        reg.disable("prueba")
        self.assertEqual(reg.run_hook("on_run_start", "r", "o"), [])
        reg.enable("prueba")
        self.assertEqual(reg.run_hook("on_run_start", "r", "o"), ["inicio"])

    def test_unregister(self):
        reg = PluginRegistry()
        reg.register(PluginDePrueba())
        reg.unregister("prueba")
        self.assertEqual(reg.names(), [])

    def test_hook_desconocido(self):
        reg = PluginRegistry()
        with self.assertRaises(ValueError):
            reg.run_hook("on_algo_raro")
        self.assertIn("on_run_start", HOOK_NAMES)

    def test_plugin_roto_se_deshabilita_y_no_rompe(self):
        reg = PluginRegistry()
        reg.register(PluginRoto())
        p = PluginDePrueba()
        reg.register(p)
        resultados = reg.run_hook("on_run_start", "r1", "objetivo")
        self.assertEqual(resultados, ["inicio"])  # el sano si ejecuto
        self.assertFalse(reg.is_enabled("roto"))
        self.assertEqual(len(reg.errors), 1)
        self.assertIn("roto.on_run_start", reg.errors[0])
        # y ya no se ejecuta
        reg.run_hook("on_run_start", "r2", "o")
        self.assertEqual(len(reg.errors), 1)

    def test_load_module_con_PLUGIN(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "mi_plugin.py").write_text(
                textwrap.dedent(
                    """
                    class MiPlugin:
                        name = "mi"
                        def on_run_start(self, run_id, objetivo, ctx=None):
                            return "hola"
                    PLUGIN = MiPlugin()
                    """
                ),
                encoding="utf-8",
            )
            sys.path.insert(0, td)
            try:
                reg = PluginRegistry()
                cargados = reg.load_module("mi_plugin")
                self.assertIn("mi", cargados)
                self.assertEqual(reg.run_hook("on_run_start", "r", "o"), ["hola"])
            finally:
                sys.path.remove(td)
                sys.modules.pop("mi_plugin", None)

    def test_load_module_con_register(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "otro_plugin.py").write_text(
                textwrap.dedent(
                    """
                    def register(registry):
                        class P:
                            name = "via-register"
                        registry.register(P())
                    """
                ),
                encoding="utf-8",
            )
            sys.path.insert(0, td)
            try:
                reg = PluginRegistry()
                reg.load_module("otro_plugin")
                self.assertIn("via-register", reg.names())
            finally:
                sys.path.remove(td)
                sys.modules.pop("otro_plugin", None)

    def test_load_module_sin_plugin_error(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "vacio.py").write_text("X = 1\n", encoding="utf-8")
            sys.path.insert(0, td)
            try:
                with self.assertRaises(ImportError):
                    PluginRegistry().load_module("vacio")
            finally:
                sys.path.remove(td)
                sys.modules.pop("vacio", None)


class TestCompuestosYLogging(unittest.TestCase):
    def test_composite(self):
        c = CompositePlugin("compuesto", [PluginDePrueba(), PluginDePrueba()])
        out = c.on_run_start("r", "o")
        self.assertEqual(len(out), 2)

    def test_logging_plugin(self):
        reg = PluginRegistry()
        log = LoggingPlugin()
        reg.register(log)
        reg.run_hook("on_run_start", "r-1", "objetivo x")
        reg.run_hook("on_node_end", {"task_id": "t"}, {"status": "done"})
        reg.run_hook("on_run_end", {"run_id": "r-1", "duracion": 1.2})
        self.assertEqual(
            log.log,
            [("run_start", {"run_id": "r-1", "objetivo": "objetivo x"}),
             ("node_end", {"task_id": "t", "status": "done"}),
             ("run_end", {"run_id": "r-1", "duracion": 1.2})],
        )

    def test_to_dict(self):
        reg = PluginRegistry()
        reg.register(PluginDePrueba())
        d = reg.to_dict()
        self.assertEqual(d["plugins"][0]["name"], "prueba")
        self.assertTrue(d["plugins"][0]["enabled"])
        self.assertIn("on_run_start", d["plugins"][0]["hooks"])


if __name__ == "__main__":
    unittest.main()
