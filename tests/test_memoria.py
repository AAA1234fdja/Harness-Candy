"""Tests de la memoria administrada en 3 capas (memoria.py + scripts/memoria)."""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.memoria import (
    CAPAS,
    MAX_PALABRAS,
    CapaDesconocidaError,
    EntradaLargaError,
    EntradaMemoria,
    GestorMemoria,
    contar_palabras,
    validar_entrada,
)

REPO = Path(__file__).resolve().parents[1]


class TestValidacion(unittest.TestCase):
    def test_max_300_palabras_fail_closed(self):
        self.assertEqual(validar_entrada("tipo", "idea", "explicacion"), 3)
        with self.assertRaises(EntradaLargaError):
            validar_entrada("t", "i", "palabra " * (MAX_PALABRAS + 1))
        # justo en el limite entra
        texto = " ".join(["w"] * (MAX_PALABRAS - 2))
        self.assertEqual(validar_entrada("t", "i", texto), MAX_PALABRAS)

    def test_tipo_e_idea_obligatorios(self):
        with self.assertRaises(ValueError):
            validar_entrada("", "idea", "x")
        with self.assertRaises(ValueError):
            validar_entrada("tipo", "  ", "x")

    def test_contar_palabras(self):
        self.assertEqual(contar_palabras("hola mundo cruel"), 3)
        self.assertEqual(contar_palabras(""), 0)


class TestGestor(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.g = GestorMemoria(Path(self.td.name) / "memoria")

    def tearDown(self):
        self.td.cleanup()

    def test_carpetas_creadas(self):
        for capa in CAPAS:
            self.assertTrue((Path(self.td.name) / "memoria" / capa).is_dir())

    def test_cache_ttl_y_purga(self):
        e = self.g.guardar_cache("borrador", "estado", "build en curso", ttl=1.0)
        self.assertEqual(e.capa, "cache")
        self.assertGreater(e.expira_en, e.creado_en)
        self.assertEqual(len(self.g.listar("cache")), 1)
        time.sleep(1.05)
        self.assertEqual(self.g.listar("cache"), [])  # expirada no se lista
        self.assertEqual(len(self.g.listar("cache", incluir_expiradas=True)), 1)
        self.assertEqual(self.g.purgar_cache(), 1)
        self.assertEqual(self.g.purgar_cache(), 0)
        self.assertEqual(len(self.g.listar("cache", incluir_expiradas=True)), 0)

    def test_chat_admision_por_relevancia(self):
        alta = self.g.guardar_chat("proj", "decision", "idea relevante", "porque si", relevancia=0.9)
        self.assertIsNotNone(alta)
        baja = self.g.guardar_chat("proj", "ruido", "nota", "poco relevante", relevancia=0.1)
        self.assertIsNone(baja)  # rechazada: no entra
        forzada = self.g.guardar_chat("proj", "ruido", "nota", "poco relevante", relevancia=0.1, forzar=True)
        self.assertIsNotNone(forzada)
        # umbral configurable
        g2 = GestorMemoria(Path(self.td.name) / "m2", umbral_relevancia=0.95)
        self.assertIsNone(g2.guardar_chat("proj", "t", "i", "x", relevancia=0.9))

    def test_chat_requiere_proyecto_y_es_por_proyecto(self):
        with self.assertRaises(ValueError):
            self.g.guardar_chat("", "t", "i")
        self.g.guardar_chat("A", "t1", "en proyecto A", "", relevancia=1.0)
        self.g.guardar_chat("B", "t2", "en proyecto B", "", relevancia=1.0)
        self.assertEqual(len(self.g.listar("chat", proyecto="A")), 1)
        self.assertEqual(self.g.listar("chat", proyecto="A")[0].idea, "en proyecto A")
        self.assertEqual(len(self.g.listar("chat")), 2)  # sin proyecto: todos

    def test_ecosistema_global(self):
        e = self.g.guardar_ecosistema("patron", "300 palabras max", "tipo+idea+explicacion", proyecto="A", tags=["memoria"])
        self.assertEqual(e.capa, "ecosistema")
        self.assertEqual(self.g.listar("ecosistema")[0].proyecto, "A")

    def test_entrada_larga_rechazada_en_todas_las_capas(self):
        largo = "palabra " * 400
        with self.assertRaises(EntradaLargaError):
            self.g.guardar_cache("t", "i", largo)
        with self.assertRaises(EntradaLargaError):
            self.g.guardar_chat("p", "t", "i", largo)
        with self.assertRaises(EntradaLargaError):
            self.g.guardar_ecosistema("t", "i", largo)

    def test_buscar_bm25(self):
        self.g.guardar_chat("proj", "decision", "usamos BM25 local para busqueda", "determinista y sin dependencias", relevancia=1.0, tags=["rag"])
        self.g.guardar_chat("proj", "nota", "la pizza de anoche", "estaba rica", relevancia=1.0)
        hits = self.g.buscar("chat", "busqueda BM25 determinista", proyecto="proj", top_k=2)
        self.assertTrue(hits)
        self.assertIn("BM25", hits[0][1].idea)
        self.assertGreater(hits[0][0], 0)
        # query vacia -> nada
        self.assertEqual(self.g.buscar("chat", "  "), [])

    def test_buscar_ecosistema_es_global(self):
        self.g.guardar_ecosistema("patron", "regla de las 300 palabras", "cada entrada es tipo+idea+explicacion", proyecto="OtroProyecto")
        hits = self.g.buscar("ecosistema", "300 palabras entrada")
        self.assertTrue(hits)
        self.assertEqual(hits[0][1].proyecto, "OtroProyecto")

    def test_leer_borrar(self):
        e = self.g.guardar_ecosistema("t", "idea", "expl")
        self.assertEqual(self.g.leer("ecosistema", e.id).idea, "idea")
        self.assertTrue(self.g.borrar("ecosistema", e.id))
        self.assertIsNone(self.g.leer("ecosistema", e.id))
        self.assertFalse(self.g.borrar("ecosistema", e.id))

    def test_capa_desconocida(self):
        with self.assertRaises(CapaDesconocidaError):
            self.g.listar("inventada")
        with self.assertRaises(CapaDesconocidaError):
            self.g.buscar("inventada", "q")

    def test_stats(self):
        self.g.guardar_cache("b", "estado", "x", ttl=60)
        self.g.guardar_chat("P", "t", "idea", "expl", relevancia=1.0)
        st = self.g.stats()
        self.assertEqual(st["capas"]["cache"]["entradas"], 1)
        self.assertEqual(st["capas"]["chat"]["entradas"], 1)
        self.assertEqual(st["capas"]["chat"]["proyectos"], ["P"])
        self.assertEqual(st["capas"]["cache"]["max_permitido"], MAX_PALABRAS)
        json.dumps(st)

    def test_persistencia_json_por_entrada(self):
        e = self.g.guardar_chat("P", "decision", "idea", "expl", relevancia=1.0)
        p = Path(self.td.name) / "memoria" / "chat" / "p" / f"{e.id}.json"
        self.assertTrue(p.exists())
        d = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(d["idea"], "idea")
        self.assertLessEqual(d["palabras"], MAX_PALABRAS)

    def test_entrada_corrupta_no_tumba_listado(self):
        d = Path(self.td.name) / "memoria" / "ecosistema"
        (d / "rota.json").write_text("{no es json", encoding="utf-8")
        self.g.guardar_ecosistema("t", "idea", "expl")
        self.assertEqual(len(self.g.listar("ecosistema")), 1)


class TestScript(unittest.TestCase):
    def _run(self, *args, root):
        return subprocess.run(
            [sys.executable, str(REPO / "scripts" / "memoria"), "--root", str(root), *args],
            capture_output=True, text=True, timeout=60,
        )

    def test_cli_completa(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "memoria"
            r = self._run("guardar-chat", "Harness-Candy", "decision", "usamos BM25", "sin deps", "--relevancia", "0.9", root=root)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('"capa": "chat"', r.stdout)
            # rechazo por relevancia -> exit 2
            r = self._run("guardar-chat", "Harness-Candy", "ruido", "nota", "x", "--relevancia", "0.1", root=root)
            self.assertEqual(r.returncode, 2)
            # rechazo por 300 palabras -> exit 2
            r = self._run("guardar-eco", "t", "i", "palabra " * 400, root=root)
            self.assertEqual(r.returncode, 2)
            self.assertIn("RECHAZADA", r.stderr)
            # eco + cache
            self.assertEqual(self._run("guardar-eco", "patron", "300 palabras", "tipo+idea+explicacion", "--proyecto-tag", "HC", root=root).returncode, 0)
            self.assertEqual(self._run("guardar-cache", "borrador", "estado", "build", "--ttl", "60", root=root).returncode, 0)
            # buscar
            r = self._run("buscar", "chat", "BM25", "--proyecto", "Harness-Candy", root=root)
            self.assertEqual(r.returncode, 0)
            self.assertIn("usamos BM25", r.stdout)
            r = self._run("buscar", "ecosistema", "palabras", root=root)
            self.assertIn("300 palabras", r.stdout)
            # listar y stats y purgar
            self.assertEqual(self._run("listar", "chat", "--proyecto", "Harness-Candy", root=root).returncode, 0)
            r = self._run("stats", root=root)
            self.assertEqual(r.returncode, 0)
            self.assertIn('"cache"', r.stdout)
            self.assertEqual(self._run("purgar", root=root).returncode, 0)
            # leer por id
            e_id = self._run("listar", "ecosistema", root=root).stdout.splitlines()[0].split()[0]
            r = self._run("leer", "ecosistema", e_id, root=root)
            self.assertEqual(r.returncode, 0)
            self.assertIn("patron", r.stdout)


if __name__ == "__main__":
    unittest.main()
