"""Tests de workflows declarativos (workflow.py)."""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from helpers import make_pool, make_repo
from harness_candy.agents import ScriptedBackend, SecurityScanAgent
from harness_candy.components import WEV
from harness_candy.harness import Budget, Harness, HarnessStore
from harness_candy.security import SecurityGate
from harness_candy.workflow import StepResult, Workflow, WorkflowResult, run_workflow


def _wf_demo(repo, con_when=True):
    steps = [
        {"id": "marcar", "type": "set", "key": "listo", "value": True},
        {
            "id": "escanear", "type": "task",
            "task": {
                "task_id": "wf-scan",
                "kind": "security_scan",
                "instruction": "Escanear el repo demo",
                "inputs": {"root": str(repo)},
                "criterios": [
                    {"id": "informe_json_valido", "peso": 3.0},
                    {"id": "compile_ok", "peso": 2.0},
                    {"id": "sin_secretos_criticos", "peso": 3.0},
                ],
            },
        },
    ]
    if con_when:
        steps[1]["when"] = "ctx['listo'] == True"
        steps.append({"id": "saltar", "type": "set", "key": "x", "value": 1, "when": "ctx['listo'] == False"})
    return {"name": "wf-demo", "steps": steps}


def _entorno(td):
    pool = make_pool()
    store = HarnessStore()
    store.save("security_scan", "modelo-ligero", Harness(), evidence={"q": [1.0]}, q_mean=1.0)  # sin probe
    wev = WEV(SecurityGate())
    agent = SecurityScanAgent("XEV", "modelo-ligero", ScriptedBackend(lambda *a, **k: "ok"))
    return pool, store, wev, agent


class TestWorkflow(unittest.TestCase):
    def test_from_dict_valida(self):
        with self.assertRaises(ValueError):
            Workflow.from_dict({"name": "x"})  # sin steps
        with self.assertRaises(ValueError):
            Workflow.from_dict({"name": "x", "steps": [{"id": "s"}]})  # sin type
        with self.assertRaises(ValueError):
            Workflow.from_dict({"name": "x", "steps": [{"id": "s", "type": "raro"}]})
        wf = Workflow.from_dict(_wf_demo("x"))
        self.assertEqual(wf.name, "wf-demo")
        self.assertEqual(len(wf.steps), 3)

    def test_load_desde_archivo(self):
        import json

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "wf.json"
            p.write_text(json.dumps(_wf_demo("x")), encoding="utf-8")
            self.assertEqual(Workflow.load(p).name, "wf-demo")

    def test_run_workflow_set_when_task(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(td)
            pool, store, wev, agent = _entorno(td)
            wf = Workflow.from_dict(_wf_demo(repo))
            res = run_workflow(wf, agent=agent, pool=pool, store=store, wev=wev, trace_dir=Path(td) / "traces", seed=0)
            self.assertIsInstance(res, WorkflowResult)
            self.assertEqual(res.steps["marcar"].status, "done")
            self.assertEqual(res.steps["saltar"].status, "skipped")
            self.assertEqual(res.steps["escanear"].status, "done")
            self.assertIn("escanear", res.context["qs"])
            self.assertIn("tasa_pruebas", res.metrics)
            d = res.to_dict()
            self.assertIn("run_id", d)
            self.assertTrue(Path(res.trace_path).exists())

    def test_run_workflow_when_falso_salta_task(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(td)
            pool, store, wev, agent = _entorno(td)
            data = _wf_demo(repo)
            data["steps"][1]["when"] = "ctx['listo'] == False"  # falso -> skip
            wf = Workflow.from_dict(data)
            res = run_workflow(wf, agent=agent, pool=pool, store=store, wev=wev, trace_dir=Path(td) / "traces", seed=0)
            self.assertEqual(res.steps["escanear"].status, "skipped")

    def test_when_malicioso_rechazado(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(td)
            pool, store, wev, agent = _entorno(td)
            data = _wf_demo(repo, con_when=False)
            data["steps"][0]["when"] = "__import__('os').system('echo pwned')"
            wf = Workflow.from_dict(data)
            res = run_workflow(wf, agent=agent, pool=pool, store=store, wev=wev, trace_dir=Path(td) / "traces", seed=0)
            self.assertEqual(res.steps["marcar"].status, "failed")

    def test_step_set_con_expr(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(td)
            pool, store, wev, agent = _entorno(td)
            wf = Workflow.from_dict({
                "name": "w-set",
                "steps": [
                    {"id": "a", "type": "set", "key": "base", "value": 10},
                    {"id": "b", "type": "set", "key": "doble", "value": "expr:ctx['base'] * 2"},
                ],
            })
            res = run_workflow(wf, agent=agent, pool=pool, store=store, wev=wev, trace_dir=Path(td) / "traces", seed=0)
            self.assertEqual(res.context["doble"], 20)

    def test_workflow_parallel(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(td)
            pool, store, wev, agent = _entorno(td)
            wf = Workflow.from_dict({
                "name": "w-par",
                "steps": [
                    {"id": "grupo", "type": "parallel", "steps": [
                        {"id": "p1", "type": "set", "key": "a", "value": 1},
                        {"id": "p2", "type": "set", "key": "b", "value": 2},
                    ]},
                ],
            })
            res = run_workflow(wf, agent=agent, pool=pool, store=store, wev=wev, trace_dir=Path(td) / "traces", seed=0)
            self.assertEqual(res.steps["grupo"].status, "done")
            self.assertEqual(res.steps["p1"].status, "done")
            self.assertEqual(res.steps["p2"].status, "done")
            self.assertEqual(res.context["a"], 1)

    def test_step_result_to_dict(self):
        sr = StepResult("s", "done", {"q": 1.0}, 0.5)
        d = sr.to_dict()
        self.assertEqual(d["step_id"], "s")
        self.assertEqual(d["status"], "done")


if __name__ == "__main__":
    unittest.main()
