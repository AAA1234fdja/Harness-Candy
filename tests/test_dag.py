import time
import unittest

import _path  # noqa: F401
from harness_candy.dag import DAGExecutor, NodeResult, TaskDAG, TaskNode
from harness_candy.protocols import Envelope, WevMessage


def node(tid, deps=(), **kw):
    return TaskNode(task_id=tid, kind="demo", instruction=tid, deps=list(deps), **kw)


class TestDAG(unittest.TestCase):
    def test_layers_topologicas(self):
        dag = TaskDAG()
        dag.add(node("a"))
        dag.add(node("b", deps=["a"]))
        dag.add(node("c", deps=["a"]))
        dag.add(node("d", deps=["b", "c"]))
        layers = dag.layers()
        self.assertEqual(layers[0], ["a"])
        self.assertEqual(sorted(layers[1]), ["b", "c"])
        self.assertEqual(layers[2], ["d"])

    def test_dep_faltante(self):
        dag = TaskDAG()
        dag.add(node("a", deps=["no-existe"]))
        with self.assertRaises(ValueError):
            dag.validate()

    def test_ciclo(self):
        dag = TaskDAG()
        dag.add(node("a", deps=["b"]))
        dag.add(node("b", deps=["a"]))
        with self.assertRaises(ValueError):
            dag.validate()

    def test_duplicado(self):
        dag = TaskDAG()
        dag.add(node("a"))
        with self.assertRaises(ValueError):
            dag.add(node("a"))


class TestExecutor(unittest.TestCase):
    def test_paralelo_en_capa(self):
        dag = TaskDAG()
        dag.add(node("a"))
        dag.add(node("b"))
        dag.add(node("c"))

        def handler(n, ctx):
            time.sleep(0.3)
            return NodeResult(task_id=n.task_id, status="done")

        ex = DAGExecutor(handler, max_concurrency=3)
        start = time.time()
        res = ex.execute(dag)
        elapsed = time.time() - start
        self.assertEqual({r.status for r in res.values()}, {"done"})
        self.assertLess(elapsed, 0.9)  # 3 x 0.3s en paralelo, no 0.9s serie

    def test_dependencias_esperan(self):
        dag = TaskDAG()
        dag.add(node("a"))
        dag.add(node("b", deps=["a"]))
        orden = []

        def handler(n, ctx):
            orden.append(n.task_id)
            return NodeResult(task_id=n.task_id, status="done")

        DAGExecutor(handler).execute(dag)
        self.assertEqual(orden, ["a", "b"])

    def test_reintento_con_feedback_wev(self):
        dag = TaskDAG()
        dag.add(node("a", max_reintentos=2))
        intentos = {"n": 0}

        def handler(n, ctx):
            intentos["n"] += 1
            if intentos["n"] < 3:
                msg = WevMessage(Envelope("wev", n.task_id, "WEV", "YEV"), n.task_id, veredicto="rechazado")
                return NodeResult(task_id=n.task_id, status="rejected", wev=msg)
            return NodeResult(task_id=n.task_id, status="done")

        res = DAGExecutor(handler).execute(dag, context={})
        self.assertEqual(res["a"].status, "done")
        self.assertEqual(intentos["n"], 3)

    def test_escala_tras_agotar_reintentos(self):
        dag = TaskDAG()
        dag.add(node("a", max_reintentos=2))
        events = []

        def handler(n, ctx):
            msg = WevMessage(Envelope("wev", n.task_id, "WEV", "YEV"), n.task_id, veredicto="rechazado")
            return NodeResult(task_id=n.task_id, status="rejected", wev=msg)

        res = DAGExecutor(handler, on_event=lambda e, d: events.append(e)).execute(dag)
        self.assertEqual(res["a"].status, "escalated")
        self.assertEqual(res["a"].attempts, 3)  # intento inicial + 2 reintentos
        self.assertIn("escalated", events)

    def test_fallo_excepcion(self):
        dag = TaskDAG()
        dag.add(node("a"))

        def handler(n, ctx):
            raise RuntimeError("boom")

        res = DAGExecutor(handler).execute(dag)
        self.assertEqual(res["a"].status, "failed")
        self.assertIn("boom", res["a"].error)


if __name__ == "__main__":
    unittest.main()
