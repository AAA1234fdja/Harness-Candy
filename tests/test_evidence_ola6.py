"""Tests de evidence packs, OTLP e2e, alertas avanzadas y rollback (evidence.py, ola 6)."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import _path  # noqa: F401
from harness_candy.evidence import (
    ReglaAlerta,
    evaluar_alertas,
    evidence_pack,
    export_otlp_end_to_end,
    exportar_pack_zip,
    guardar_pack,
    cargar_pack,
    marcar_rollback_en_store,
    pack_desde_store,
    rollback_si_regresion,
    verificar_pack,
)
from harness_candy.storage import JsonRunStore

KEY = "clave-de-prueba-32-bytes-minimo-ok!!"


def transport_ok(req, timeout=10):
    class R:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"
    return R()


class TestEvidencePack(unittest.TestCase):
    def test_firma_y_verificacion(self):
        run = {"run_id": "r1", "qs": {"t1": 0.9}}
        pack = evidence_pack(run, cards=[{"schema": "x"}], runmark={"git_commit": "abc"}, key=KEY)
        v = verificar_pack(pack, key=KEY)
        self.assertTrue(v["ok"])

    def test_pack_alterado_falla(self):
        pack = evidence_pack({"run_id": "r1"}, key=KEY)
        pack2 = json.loads(json.dumps(pack))
        pack2["run"]["run_id"] = "alterado"
        self.assertFalse(verificar_pack(pack2, key=KEY)["ok"])

    def test_firma_incorrecta_falla(self):
        pack = evidence_pack({"run_id": "r1"}, key=KEY)
        self.assertFalse(verificar_pack(pack, key="otra-clave-distinta-32-bytes!!")["ok"])

    def test_guardar_cargar_y_zip(self):
        pack = evidence_pack({"run_id": "r1", "dag_results": {"t": {"status": "done"}}}, key=KEY)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "pack.json"
            guardar_pack(pack, p)
            self.assertEqual(cargar_pack(p)["run"]["run_id"], "r1")
            z = exportar_pack_zip(pack, Path(td) / "pack.zip")
            with zipfile.ZipFile(z) as zz:
                nombres = zz.namelist()
                self.assertIn("pack.json", nombres)
                self.assertIn("run.json", nombres)
                self.assertIn("VERIFICACION.txt", nombres)

    def test_pack_desde_store(self):
        with tempfile.TemporaryDirectory() as td:
            store = JsonRunStore(Path(td) / "runs")
            store.save({"run_id": "r9", "qs": {"t": 0.8}})
            pack = pack_desde_store(store, "r9", root=Path(__file__).resolve().parents[1], key=KEY)
            self.assertEqual(pack["run"]["run_id"], "r9")
            self.assertNotEqual(pack["runmark"]["git_commit"], "unknown")
            self.assertTrue(verificar_pack(pack, key=KEY)["ok"])
            with self.assertRaises(KeyError):
                pack_desde_store(store, "no-existe", key=KEY)


class TestOtlpE2E(unittest.TestCase):
    def test_export_ok(self):
        res = export_otlp_end_to_end([{"name": "p1", "duracion": 0.1}, {"name": "p2", "duracion": 0.2}], transport=transport_ok)
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], 200)
        self.assertGreaterEqual(res["n_spans"], 1)

    def test_export_caido_reporta_error(self):
        def caido(req, timeout=1):
            raise OSError("collector caido")
        res = export_otlp_end_to_end([], transport=caido)
        self.assertFalse(res["ok"])
        self.assertIn("collector caido", res["error"])


class TestAlertas(unittest.TestCase):
    def test_tendencia_toxicity_y_jsr(self):
        hist = {"toxicity_rate": [0.0] * 5 + [0.1, 0.1], "jsr": [0.0] * 5 + [0.3]}
        al = evaluar_alertas(hist)
        msgs = " ".join(a.message for a in al)
        self.assertIn("toxicity_rate", msgs)
        self.assertIn("jsr", msgs)
        self.assertTrue(all(a.level in ("info", "warning", "critical") for a in al))
        self.assertTrue(all(a.kind in ("security", "quality", "budget", "regression") for a in al))

    def test_caida_q_y_agreement(self):
        hist = {"q_media": [0.9] * 10 + [0.7] * 5, "judge_agreement": [0.9] * 10 + [0.5] * 5}
        al = evaluar_alertas(hist)
        msgs = " ".join(a.message for a in al)
        self.assertIn("q_media", msgs)
        self.assertIn("judge_agreement", msgs)

    def test_sin_datos_no_alerta(self):
        self.assertEqual(evaluar_alertas({"toxicity_rate": [0.0]}), [])
        self.assertEqual(evaluar_alertas({}), [])

    def test_regla_custom(self):
        reglas = [ReglaAlerta("metrica_x", "tendencia", ventana=2, umbral=0.4, severidad="critica")]
        al = evaluar_alertas({"metrica_x": [0.1, 0.9]}, reglas)
        self.assertEqual(len(al), 1)
        self.assertEqual(al[0].level, "critical")


class TestRollback(unittest.TestCase):
    def test_rollback_cuando_cae_mas_de_la_banda(self):
        dec = rollback_si_regresion([0.5, 0.55], {"tarea-0": 0.9, "tarea-1": 0.9}, banda=0.03, drop_pp=2.0)
        self.assertTrue(dec["rollback"])
        self.assertTrue(dec["alertas"])
        self.assertIn("volver", dec["accion"])
        json.dumps(dec)

    def test_sin_rollback_en_banda(self):
        dec = rollback_si_regresion([0.9, 0.91], {"tarea-0": 0.9, "tarea-1": 0.9}, banda=0.03)
        self.assertFalse(dec["rollback"])
        self.assertIn("mantener", dec["accion"])

    def test_marcar_rollback_en_store(self):
        with tempfile.TemporaryDirectory() as td:
            store = JsonRunStore(Path(td) / "runs")
            dec = rollback_si_regresion([0.4], {"tarea-0": 0.9}, banda=0.03)
            run = marcar_rollback_en_store({"run_id": "r2", "status": "done"}, dec, store)
            self.assertEqual(run["status"], "rollback")
            self.assertTrue(store.get("r2")["rollback"]["rollback"])


if __name__ == "__main__":
    unittest.main()
