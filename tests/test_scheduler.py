"""Tests del scheduler de jobs (tick determinista, no solapamiento, historial)."""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.scheduler import Scheduler


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.base = Path(self.td.name)
        (self.base / "s.json").write_text("{}", encoding="utf-8")
        self.ejecutados = []

    def tearDown(self):
        self.td.cleanup()

    def _sched(self):
        return Scheduler(lambda job: self.ejecutados.append(job.job_id) or "done", base_dir=self.base)

    def test_add_valida(self):
        s = self._sched()
        job = s.add(name="j", suite_path="s.json", interval_s=60, now=1000.0)
        self.assertEqual(job.next_run, 1060.0)
        self.assertEqual(len(s.list()), 1)
        with self.assertRaises(ValueError):
            s.add(name="x", suite_path="s.json", interval_s=0)
        with self.assertRaises(ValueError):
            s.add(name="x", suite_path="../fuera.json", interval_s=10)

    def test_tick_ejecuta_los_debidos(self):
        s = self._sched()
        j1 = s.add(name="cada-10", suite_path="s.json", interval_s=10, now=0.0)
        j2 = s.add(name="cada-100", suite_path="s.json", interval_s=100, now=0.0)
        ejecutados = s.tick_blocking(now=50.0)
        self.assertEqual([e["job_id"] for e in ejecutados], [j1.job_id])  # solo j1 debia
        self.assertEqual(self.ejecutados, [j1.job_id])
        self.assertEqual(j1.runs, 1)
        self.assertEqual(j1.last_status, "done")
        # next_run se adelanta
        self.assertEqual(j1.next_run, 60.0)
        # tick de nuevo antes de tiempo: nada
        self.assertEqual(s.tick_blocking(now=55.0), [])
        # a los 100 ejecutan ambos
        ej = s.tick_blocking(now=100.0)
        self.assertEqual(len(ej), 2)
        self.assertEqual(len(s.history), 3)

    def test_deshabilitado_no_ejecuta(self):
        s = self._sched()
        j = s.add(name="j", suite_path="s.json", interval_s=5, now=0.0)
        s.set_enabled(j.job_id, False)
        self.assertEqual(s.tick_blocking(now=100.0), [])
        s.set_enabled(j.job_id, True)
        self.assertEqual(len(s.tick_blocking(now=100.0)), 1)

    def test_error_en_run_fn_se_registra(self):
        s = Scheduler(lambda job: 1 / 0, base_dir=self.base)
        j = s.add(name="falla", suite_path="s.json", interval_s=1, now=0.0)
        s.tick_blocking(now=10.0)
        self.assertIn("error", j.last_status)
        self.assertIn("ZeroDivisionError", j.last_status)
        self.assertEqual(j.runs, 1)

    def test_remove(self):
        s = self._sched()
        j = s.add(name="j", suite_path="s.json", interval_s=5)
        self.assertTrue(s.remove(j.job_id))
        self.assertFalse(s.remove(j.job_id))
        self.assertEqual(s.list(), [])

    def test_no_solapamiento(self):
        # tick (async) con un job cuyo run_fn tarda: el lock evita reentradas
        import threading
        import time

        s = Scheduler(lambda job: (time.sleep(0.2), "done")[1], base_dir=self.base)
        j = s.add(name="lento", suite_path="s.json", interval_s=1, now=0.0)
        lanzados1 = s.tick(now=5.0)
        lanzados2 = s.tick(now=6.0)  # el job sigue corriendo: no se relanza
        self.assertEqual(len(lanzados1), 1)
        self.assertEqual(lanzados2, [])
        time.sleep(0.4)
        self.assertEqual(j.runs, 1)


if __name__ == "__main__":
    unittest.main()
