"""Tests del schedule avanzado de la quinta ola (harness_candy.schedule)."""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.schedule import (
    ScheduleItem,
    ScheduleRunner,
    grid_sweep,
    particionar,
    shard_de,
    sweep_con_early_stop,
)


class TestParticion(unittest.TestCase):
    def test_lpt_balancea_y_conserva(self):
        shards = particionar(list(range(10)), 3, clave_tamano=lambda x: x)
        self.assertEqual(len(shards), 3)
        self.assertEqual(sorted(x for s in shards for x in s), list(range(10)))
        pesos = [sum(s) for s in shards]
        # LPT: diferencia entre shard mas pesado y mas liviano <= item mas caro
        self.assertLessEqual(max(pesos) - min(pesos), 9)

    def test_lpt_mejor_que_round_robin(self):
        items = [8, 7, 6, 5, 4]
        lpt = [sum(s) for s in particionar(items, 2, clave_tamano=lambda x: x)]
        rr = [sum(items[i::2]) for i in range(2)]
        self.assertLessEqual(max(lpt) - min(lpt), max(rr) - min(rr))

    def test_mas_shards_que_items(self):
        shards = particionar([1, 2], 5, clave_tamano=lambda x: x)
        self.assertEqual(sum(len(s) for s in shards), 2)

    def test_shard_de_round_robin(self):
        self.assertEqual([shard_de(i, 10, 3) for i in range(6)], [0, 1, 2, 0, 1, 2])
        self.assertEqual(shard_de(0, 0, 3), 0)  # casos borde
        self.assertEqual(shard_de(5, 10, 0), 0)


class TestGridSweep(unittest.TestCase):
    def test_grid_producto(self):
        pts = grid_sweep({"k": [1, 2], "m": [3, 5, 7]})
        self.assertEqual(len(pts), 6)
        self.assertEqual(pts[0].params, {"k": 1, "m": 3})
        self.assertEqual(pts[-1].params, {"k": 2, "m": 7})
        self.assertEqual([p.indice for p in pts], list(range(6)))

    def test_early_stop_corta_temprano(self):
        # sube a 0.9 y luego 3 puntos sin mejorar -> corta en 5 de 7
        vals = iter([0.5, 0.9, 0.6, 0.6, 0.6, 0.6, 0.6])
        res = sweep_con_early_stop(lambda p: next(vals), {"x": list(range(7))}, min_puntos=3, ventana=3)
        self.assertEqual(res.evaluados, 5)
        self.assertTrue(res.detenido_temprano)
        self.assertEqual(res.mejor_valor, 0.9)

    def test_early_stop_evaluo_todo_si_no_hay_corte(self):
        vals = iter([float(i) for i in range(5)])  # siempre mejora
        res = sweep_con_early_stop(lambda p: next(vals), {"x": [1, 2, 3, 4, 5]}, min_puntos=2, ventana=3)
        self.assertEqual(res.evaluados, 5)
        self.assertFalse(res.detenido_temprano)
        self.assertEqual(res.mejor_valor, 4.0)

    def test_minimizar(self):
        vals = iter([5.0, 4.0, 1.0, 1.0, 1.0])
        res = sweep_con_early_stop(lambda p: next(vals), {"x": [1, 2, 3, 4, 5]}, maximizar=False, min_puntos=3, ventana=2)
        self.assertEqual(res.mejor_valor, 1.0)


class TestScheduleRunner(unittest.TestCase):
    def test_run_con_fallo_y_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            ck = Path(td) / "ck.json"
            def ej(it):
                if it.id == "b":
                    raise RuntimeError("boom")
                return {"ok": it.id}
            r1 = ScheduleRunner(ej, checkpoint=ck).run([ScheduleItem("a"), ScheduleItem("b"), ScheduleItem("c")])
            self.assertEqual(r1.procesados, 2)
            self.assertEqual(r1.fallidos, 1)
            self.assertFalse(r1.reanudado)
            self.assertTrue(ck.exists())
            self.assertIn("a", r1.resultados)

    def test_resume_no_reejecuta(self):
        with tempfile.TemporaryDirectory() as td:
            ck = Path(td) / "ck.json"
            llamadas = []
            def ej(it):
                llamadas.append(it.id)
                return it.id
            jobs = [ScheduleItem("a"), ScheduleItem("c"), ScheduleItem("d")]
            ScheduleRunner(ej, checkpoint=ck).run(jobs)
            r2 = ScheduleRunner(ej, checkpoint=ck).run(jobs + [ScheduleItem("e")])
            self.assertTrue(r2.reanudado)
            self.assertEqual(r2.procesados, 1)  # solo "e" es nuevo
            self.assertEqual(llamadas.count("a"), 1)
            self.assertEqual(llamadas.count("e"), 1)

    def test_reintentos_hasta_max(self):
        with tempfile.TemporaryDirectory() as td:
            intentos = []
            def ej(it):
                intentos.append(it.id)
                raise RuntimeError("siempre falla")
            r = ScheduleRunner(ej, checkpoint=Path(td) / "ck.json", max_reintentos=3).run([ScheduleItem("x")])
            self.assertEqual(r.fallidos, 1)
            self.assertEqual(len(intentos), 3)

    def test_shards_procesan_todo(self):
        with tempfile.TemporaryDirectory() as td:
            vistos = []
            def ej(it):
                vistos.append(it.id)
                return it.id
            items = [ScheduleItem(f"i{i}") for i in range(10)]
            r = ScheduleRunner(ej, n_shards=3, checkpoint=Path(td) / "ck.json").run(items)
            self.assertEqual(r.procesados, 10)
            self.assertEqual(sorted(vistos), sorted(it.id for it in items))


if __name__ == "__main__":
    unittest.main()
