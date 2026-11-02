"""Tests del orquestador de campanas (orchestrator.py)."""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from helpers import make_repo, make_runner
from harness_candy.harness import Harness
from harness_candy.orchestrator import CAMPAIGN_SCHEMA, Campaign, CampaignResult, run_campaign
from harness_candy.schemas import SchemaError, validate_schema


class TestOrchestrator(unittest.TestCase):
    def test_schema_local_valida(self):
        validate_schema({"name": "c", "objetivos": [{"objetivo": "o"}]}, CAMPAIGN_SCHEMA, path="campaign.$")
        with self.assertRaises(SchemaError):
            validate_schema({"name": "c", "objetivos": []}, CAMPAIGN_SCHEMA, path="campaign.$")
        with self.assertRaises(SchemaError):
            validate_schema({"objetivos": [{"objetivo": "o"}]}, CAMPAIGN_SCHEMA, path="campaign.$")

    def test_campaign_from_dict(self):
        c = Campaign.from_dict({"name": "c", "objetivos": [{"objetivo": "o", "inputs": {"a": 1}, "seed": 3}], "budget_total": 500})
        self.assertEqual(c.name, "c")
        self.assertEqual(c.budget_total, 500)
        self.assertEqual(c.objetivos[0]["seed"], 3)

    def test_campaign_load(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "camp.json"
            p.write_text(json.dumps({"name": "c", "objetivos": [{"objetivo": "o"}]}), encoding="utf-8")
            self.assertEqual(Campaign.load(p).name, "c")

    def test_run_campaign(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(td)
            runner = make_runner(Path(td) / "traces")
            runner.store.save("security_scan", "modelo-ligero", Harness(), evidence={"q": [1.0]}, q_mean=1.0)
            camp = Campaign.from_dict({
                "name": "camp-test",
                "budget_total": 100_000,
                "objetivos": [
                    {"objetivo": "auditar seguridad del repo", "inputs": {"root": str(repo)}, "seed": 0},
                    {"objetivo": "auditar seguridad del repo otra vez", "inputs": {"root": str(repo)}, "seed": 1},
                ],
            })
            res = run_campaign(camp, runner=runner, trace_dir=Path(td) / "traces")
            self.assertIsInstance(res, CampaignResult)
            self.assertEqual(len(res.runs), 2)
            self.assertEqual(res.saltados, [])
            self.assertGreaterEqual(res.q_medio, 0.0)
            self.assertLessEqual(res.q_medio, 1.0)
            self.assertGreater(res.costo_total, 0)
            d = res.to_dict()
            self.assertIn("resumen", d)
            self.assertIn("camp-test", res.resumen_ejecutivo())

    def test_run_campaign_salta_sin_presupuesto(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(td)
            runner = make_runner(Path(td) / "traces")
            runner.store.save("security_scan", "modelo-ligero", Harness(), evidence={"q": [1.0]}, q_mean=1.0)
            camp = Campaign.from_dict({
                "name": "camp-pobre",
                "budget_total": 1,  # beta*total = 0.5 -> no cabe ni un probe; como hay harness cacheado, igual corre
                "objetivos": [{"objetivo": "auditar seguridad del repo", "inputs": {"root": str(repo)}}] * 3,
            })
            res = run_campaign(camp, runner=runner, trace_dir=Path(td) / "traces")
            self.assertEqual(len(res.runs) + len(res.saltados), 3)

    def test_run_campaign_objetivo_falla_no_tumba(self):
        with tempfile.TemporaryDirectory() as td:
            runner = make_runner(Path(td) / "traces")

            class RunnerRoto:
                def __init__(self, r):
                    self.r = r

                def run(self, *a, **k):
                    raise RuntimeError("boom")

            camp = Campaign.from_dict({"name": "c", "objetivos": [{"objetivo": "x"}, {"objetivo": "y"}]})
            res = run_campaign(camp, runner=RunnerRoto(runner), trace_dir=Path(td) / "traces")
            self.assertEqual(len(res.runs), 2)
            self.assertTrue(all("error" in r for r in res.runs))
            self.assertEqual(res.q_medio, 0.0)


if __name__ == "__main__":
    unittest.main()
