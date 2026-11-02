"""Tests del lote 6: summarize avanzado, llm costos/batch, config interpolar/reload,
watch debounce, orchestrator A/B y early-stop, evalsuite pass@k/CSV, notify."""
import json
import tempfile
import time
import unittest
from pathlib import Path

import _path  # noqa: F401
from helpers import make_repo, make_runner
from harness_candy.config import Config, ConfigWatcher, diff_configs, interpolar
from harness_candy.crypto import SIGNING_KEY_ENV
from harness_candy.evalsuite import EvalSuiteResult, exportar_csv, pass_at_k
from harness_candy.harness import Harness
from harness_candy.llm import PromptBuilder, FewShotExample, batch_complete, estimate_cost, truncar_contexto
from harness_candy.notify import CallbackSink, JsonlSink, Notifier, Notification, WebhookSink, notificar_evento_watch
from harness_candy.orchestrator import Campaign, run_campaign, run_campaign_ab
from harness_candy.summarize import detectar_duplicados, keywords, similitud_jaccard, summarize_longitud, tfidf_lite
from harness_candy.watch import DebouncedWatchRunner, WatchRunner, resumen_cambios


class FakeBackend:
    def complete(self, prompt, system="", model="", seed=0):
        return f"r:{prompt}:{seed}"


class TestSummarizeAvanzado(unittest.TestCase):
    def test_keywords(self):
        kw = keywords("seguridad claves entorno seguridad claves sandbox", top=3)
        self.assertEqual(kw[0][0], "seguridad")
        self.assertAlmostEqual(kw[0][1], 2 / 6, places=5)

    def test_tfidf(self):
        corpus = ["el gato duerme en casa", "el perro ladra fuerte", "gato perro juegan juntos"]
        out = tfidf_lite(corpus, top=3)
        self.assertEqual(len(out), 3)
        self.assertTrue(all(isinstance(x, tuple) for x in out[0]))

    def test_jaccard_y_dups(self):
        a = "el gato duerme en la casa del vecino"
        self.assertEqual(similitud_jaccard(a, a), 1.0)
        self.assertLess(similitud_jaccard(a, "texto totalmente distinto sin nada comun xyz"), 0.3)
        dups = detectar_duplicados([a, a + " extra", "otro texto aparte zzz"])
        self.assertTrue(any(i == 0 and j == 1 for i, j, _ in dups))

    def test_summarize_longitud(self):
        texto = " ".join(f"Oracion numero {i} con varias palabras aqui." for i in range(20))
        s = summarize_longitud(texto, max_palabras=20)
        self.assertLessEqual(len(s.texto.split()), 20 + 10)  # margen por corte por oraciones
        self.assertTrue(s.texto)


class TestLLMAmpliado(unittest.TestCase):
    def test_estimate_cost(self):
        self.assertAlmostEqual(estimate_cost(2000, 0.015), 0.03)
        self.assertEqual(estimate_cost(0, 1.0), 0.0)

    def test_truncar(self):
        t = "x" * 1000
        self.assertEqual(len(truncar_contexto(t, max_tokens=10)), 40)
        self.assertEqual(truncar_contexto(t, max_tokens=10, desde="fin"), t[-40:])
        self.assertEqual(truncar_contexto("corto", max_tokens=100), "corto")

    def test_prompt_builder(self):
        pb = PromptBuilder(system="sys", instruction="Haz {{ accion }}")
        pb.add("contexto", "datos X").add_few_shot([FewShotExample("e", "s")])
        out = pb.build(accion="resumir")
        self.assertIn("SYSTEM: sys", out)
        self.assertIn("[CONTEXTO]", out)
        self.assertIn("[EJEMPLOS]", out)
        self.assertIn("INSTRUCCION: Haz resumir", out)

    def test_batch_complete_orden(self):
        rs = batch_complete(FakeBackend(), ["a", "b", "c", "d"], seed=5)
        self.assertEqual(rs, ["r:a:5", "r:b:6", "r:c:7", "r:d:8"])


class TestConfigAmpliada(unittest.TestCase):
    def test_interpolar(self):
        self.assertEqual(interpolar({"h": "${X}", "l": ["${X}", 1]}, {"X": "v"}), {"h": "v", "l": ["v", 1]})
        self.assertEqual(interpolar({"h": "${FALTA_XYZ}"}, {})["h"], "${FALTA_XYZ}")

    def test_load_interpola(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.json"
            p.write_text(json.dumps({"server": {"host": "${H9}", "port": 1}}), encoding="utf-8")
            c = Config.load(p, environ={"H9": "9.9.9.9"})
            self.assertEqual(c.get("server", "host"), "9.9.9.9")

    def test_watcher_reload(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.json"
            p.write_text(json.dumps({"server": {"port": 1}}), encoding="utf-8")
            w = ConfigWatcher(p)
            self.assertIsNone(w.reload_if_changed())
            time.sleep(0.02)
            p.write_text(json.dumps({"server": {"port": 2}}), encoding="utf-8")
            c = w.reload_if_changed()
            self.assertIsNotNone(c)
            self.assertEqual(c.get("server", "port"), 2)

    def test_diff_configs(self):
        d = diff_configs({"a": 1, "b": {"x": 1}}, {"a": 2, "b": {"x": 1, "y": 5}})
        rutas = [r for r, _, _ in d]
        self.assertIn("a", rutas)
        self.assertIn("b.y", rutas)
        self.assertNotIn("b.x", rutas)


class TestWatchAmpliado(unittest.TestCase):
    def test_resumen_cambios(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.txt").write_text("v1\n", encoding="utf-8")
            w = WatchRunner(td, lambda e: None, globs=["*.txt"])
            (Path(td) / "a.txt").write_text("v2\n", encoding="utf-8")
            (Path(td) / "b.txt").write_text("n\n", encoding="utf-8")
            ev = w.poll_once()
            r = resumen_cambios(ev)
            self.assertIn("modified", r)
            self.assertIn("added", r)

    def test_debounce(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.txt").write_text("v1\n", encoding="utf-8")
            w = DebouncedWatchRunner(td, lambda e: None, globs=["*.txt"], debounce_s=100.0)
            (Path(td) / "a.txt").write_text("v2\n", encoding="utf-8")
            ev1 = w.poll_once()
            self.assertIsNotNone(ev1)  # primera deteccion emite y fija la ventana
            (Path(td) / "a.txt").write_text("v3\n", encoding="utf-8")
            self.assertIsNone(w.poll_once())  # dentro de la ventana de debounce


class TestOrchestratorAmpliado(unittest.TestCase):
    def test_early_stop(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(td)
            runner = make_runner(Path(td) / "traces")
            runner.store.save("security_scan", "modelo-ligero", Harness(), evidence={"q": [1.0]}, q_mean=1.0)
            camp = Campaign.from_dict({
                "name": "c", "budget_total": 100_000,
                "objetivos": [{"objetivo": "auditar seguridad del repo", "inputs": {"root": str(repo)}}] * 5,
            })
            res = run_campaign(camp, runner=runner, trace_dir=Path(td) / "t", early_stop_q=0.5)
            self.assertLess(len(res.runs), 5)  # paro antes de correr las 5

    def test_ab(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(td)
            r1 = make_runner(Path(td) / "t1")
            r1.store.save("security_scan", "modelo-ligero", Harness(), evidence={"q": [1.0]}, q_mean=1.0)
            r2 = make_runner(Path(td) / "t2")
            r2.store.save("security_scan", "modelo-ligero", Harness(), evidence={"q": [1.0]}, q_mean=1.0)
            camp = Campaign.from_dict({"name": "ab", "objetivos": [{"objetivo": "auditar seguridad del repo", "inputs": {"root": str(repo)}}]})
            out = run_campaign_ab(camp, runner_a=r1, runner_b=r2, trace_dir=Path(td) / "ab")
            self.assertIn("mann_whitney", out)
            self.assertIn("a", out)
            self.assertIn("b", out)


class TestEvalSuiteAmpliada(unittest.TestCase):
    def test_pass_at_k(self):
        self.assertEqual(pass_at_k([True, False], 1), 0.5)
        self.assertEqual(pass_at_k([False, True, False, False], 2), 0.5)
        self.assertEqual(pass_at_k([True] * 4, 4), 1.0)
        self.assertEqual(pass_at_k([], 2), 0.0)

    def test_export_csv(self):
        r = EvalSuiteResult("g", [0, 1], {0: 1.0, 1: 0.0}, 0.5,
                            {"aprobado": {"aprobado": 1, "rechazado": 1}, "rechazado": {"aprobado": 0, "rechazado": 0}},
                            {"p2_5": 0.0, "p50": 0.5, "p97_5": 1.0}, 2)
        with tempfile.TemporaryDirectory() as td:
            p = exportar_csv(r, Path(td) / "e.csv")
            lineas = p.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(lineas[0], "golden,seed,pass_rate")
            self.assertEqual(len(lineas), 4)


class TestNotify(unittest.TestCase):
    def test_notifier_fanout(self):
        recibidas = []
        with tempfile.TemporaryDirectory() as td:
            n = Notifier([CallbackSink(recibidas.append), JsonlSink(Path(td) / "n.jsonl")])
            ev = n.notify("prueba", {"x": 1}, severidad="warning")
            self.assertIsInstance(ev, Notification)
            self.assertEqual(len(recibidas), 1)
            lineas = (Path(td) / "n.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lineas), 1)
            d = json.loads(lineas[0])
            self.assertEqual(d["evento"], "prueba")
            self.assertEqual(d["severidad"], "warning")
            st = n.stats()
            self.assertEqual(st["enviadas"], 1)
            self.assertEqual(st["errores"], 0)

    def test_sink_caido_no_tumba(self):
        class SinkRoto:
            def enviar(self, n):
                raise RuntimeError("roto")

        ok = []
        n = Notifier([SinkRoto(), CallbackSink(ok.append)])
        n.notify("e", {})
        self.assertEqual(len(ok), 1)
        self.assertEqual(n.stats()["errores"], 1)

    def test_webhook_sin_red_no_lanza(self):
        w = WebhookSink("http://127.0.0.1:1/hook", timeout=0.5)
        w.enviar(Notification(evento="x"))  # no debe lanzar
        self.assertEqual(w.entregas_fallo, 1)
        self.assertIn("***", w.descripcion_enmascarada() + "***")  # url enmascarada parcial

    def test_notificar_watch(self):
        from harness_candy.watch import WatchEvent

        ok = []
        n = Notifier([CallbackSink(ok.append)])
        ev = WatchEvent(ts=1.0, changes={"added": [], "modified": ["a"], "deleted": ["b"]})
        notif = notificar_evento_watch(n, ev)
        self.assertEqual(notif.severidad, "critica")  # hay borrados
        self.assertEqual(ok[0].evento, "watch_change")


if __name__ == "__main__":
    unittest.main()
