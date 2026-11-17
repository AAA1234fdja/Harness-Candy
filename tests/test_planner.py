"""Tests del planificador HTN-lite (planner.py)."""
import unittest

import _path  # noqa: F401
from harness_candy.planner import Operator, Plan, Planner, PlanningError, plan_simple


def _ops_demo():
    return [
        Operator("recolectar", effects=("datos",)),
        Operator("analizar", preconditions=("datos",), effects=("hallazgos",)),
        Operator("informe", subtasks=("recolectar", "analizar"), preconditions=("datos", "hallazgos"), effects=("informe_listo",)),
    ]


class TestPlanner(unittest.TestCase):
    def test_plan_compuesto(self):
        p = Planner(_ops_demo()).plan("informe", set())
        self.assertEqual(p.pasos, ["recolectar", "analizar"])
        self.assertGreater(p.costo, 0)

    def test_goal_ya_satisfecho(self):
        p = Planner(_ops_demo()).plan("datos", {"datos"})
        self.assertEqual(p.pasos, [])
        self.assertEqual(p.costo, 0.0)

    def test_goal_desconocido(self):
        with self.assertRaises(PlanningError):
            Planner(_ops_demo()).plan("no_existe", set())

    def test_sin_plan_posible(self):
        ops = [Operator("necesita", preconditions=("imposible",), effects=("x",))]
        with self.assertRaises(PlanningError):
            Planner(ops).plan("necesita", set())

    def test_ciclo_no_cuelga(self):
        ops = [
            Operator("a", subtasks=("b",), preconditions=(), effects=("ea",)),
            Operator("b", subtasks=("a",), preconditions=(), effects=("eb",)),
        ]
        with self.assertRaises(PlanningError):
            Planner(ops, max_depth=4, max_nodos=500).plan("a", set())

    def test_register(self):
        pl = Planner()
        pl.register(Operator("x", effects=("ok",)))
        self.assertEqual(pl.plan("x", set()).pasos, ["x"])

    def test_operator_apply_y_applicable(self):
        op = Operator("o", preconditions=("p",), effects=("e",))
        self.assertFalse(op.applicable(set()))
        self.assertTrue(op.applicable({"p"}))
        self.assertEqual(op.apply({"p"}), {"p", "e"})

    def test_plan_to_dict(self):
        d = Planner(_ops_demo()).plan("informe", set()).to_dict()
        self.assertEqual(d["goal"], "informe")
        self.assertEqual(d["pasos"], ["recolectar", "analizar"])

    def test_plan_simple(self):
        p = plan_simple()
        self.assertEqual(p.pasos, ["recolectar", "analizar", "redactar", "validar"])
        self.assertIsInstance(p, Plan)

    def test_max_nodos(self):
        ops = [Operator(f"n{i}", subtasks=(f"n{i+1}",) if i < 50 else (), effects=(f"e{i}",)) for i in range(60)]
        with self.assertRaises(PlanningError):
            Planner(ops, max_nodos=10).plan("n0", set())


if __name__ == "__main__":
    unittest.main()
