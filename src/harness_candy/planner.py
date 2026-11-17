"""Planificador HTN-lite (v3 §5.2, ISA planifica): descomposicion de objetivos
en operadores con precondiciones y efectos.

Un ``Operator`` declara:
  - ``preconditions``: hechos que deben cumplirse antes (sobre el estado)
  - ``effects``: hechos que quedan verdaderos tras ejecutarlo
  - ``subtasks``: otros goals/operadores que lo componen (descomposicion HTN)

``Planner.plan(goal, estado_inicial)`` hace busqueda en profundidad limitada
(mutando el estado con los efectos) y devuelve un ``Plan`` (lista ordenada de
operadores aplicables). Si el goal ya esta en el estado, plan vacio.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class PlanningError(RuntimeError):
    pass


@dataclass
class Operator:
    name: str
    preconditions: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    subtasks: tuple[str, ...] = ()  # nombres de goals/operadores hijos
    cost: float = 1.0

    def applicable(self, estado: set[str]) -> bool:
        return all(p in estado for p in self.preconditions)

    def apply(self, estado: set[str]) -> set[str]:
        nuevo = set(estado)
        for e in self.effects:
            nuevo.add(e)
        return nuevo


@dataclass
class Plan:
    goal: str
    pasos: list[str] = field(default_factory=list)  # nombres de operadores en orden
    costo: float = 0.0

    def to_dict(self) -> dict:
        return {"goal": self.goal, "pasos": self.pasos, "costo": self.costo}


class Planner:
    """Planificador sobre un registro de operadores/goals."""

    def __init__(self, operators: Optional[list[Operator]] = None, *, max_depth: int = 8, max_nodos: int = 2000):
        self.operators: dict[str, Operator] = {op.name: op for op in (operators or [])}
        self.max_depth = max_depth
        self.max_nodos = max_nodos

    def register(self, op: Operator) -> None:
        self.operators[op.name] = op

    def plan(self, goal: str, estado_inicial: set[str] | frozenset | None = None) -> Plan:
        estado = set(estado_inicial or set())
        if goal in estado:
            return Plan(goal=goal, pasos=[], costo=0.0)
        if goal not in self.operators:
            raise PlanningError(f"goal desconocido: {goal!r}; registrados: {sorted(self.operators)}")
        resultado = self._buscar(goal, estado, 0, frozenset(), [0])
        if resultado is None:
            raise PlanningError(f"sin plan para {goal!r} desde estado inicial (profundidad max {self.max_depth})")
        costo = sum(self.operators[p].cost for p in resultado if p in self.operators)
        return Plan(goal=goal, pasos=resultado, costo=costo)


    def verificar_plan(self, plan: Plan, estado_inicial: set[str] | frozenset | None = None) -> tuple[bool, set[str]]:
        """Simula el plan desde el estado inicial; devuelve (valido, estado_final).

        Cada paso debe ser aplicable cuando le toca (fail-closed).
        """
        estado = set(estado_inicial or set())
        for paso in plan.pasos:
            op = self.operators.get(paso)
            if op is None:
                return False, estado
            if not op.applicable(estado):
                return False, estado
            estado.update(op.effects)
        objetivo = self.operators.get(plan.goal)
        if objetivo is None:
            return plan.goal in estado, estado
        # goal compuesto: valido si quedo satisfecho o sus precondiciones se cumplieron
        return (plan.goal in estado) or all(p in estado for p in objetivo.preconditions), estado

    def niveles(self, goal: str, estado_inicial: set[str] | frozenset | None = None) -> list[list[str]]:
        """Agrupa los pasos del plan en niveles ejecutables en paralelo.

        Un paso puede ir en el nivel k si todas sus precondiciones quedaron
        cubiertas por efectos de niveles anteriores.
        """
        plan = self.plan(goal, estado_inicial)
        estado = set(estado_inicial or set())
        niveles: list[list[str]] = []
        pendientes = list(plan.pasos)
        while pendientes:
            nivel = [p for p in pendientes if self.operators[p].applicable(estado)]
            if not nivel:
                raise PlanningError(f"plan no paralelizable: {pendientes}")
            niveles.append(nivel)
            for p in nivel:
                estado.update(self.operators[p].effects)
            pendientes = [p for p in pendientes if p not in nivel]
        return niveles

    def estimate_cost(self, goal: str, estado_inicial: set[str] | frozenset | None = None) -> float:
        """Costo estimado del plan (suma de costos de operadores)."""
        return self.plan(goal, estado_inicial).costo

    def _buscar(
        self,
        goal: str,
        estado: set[str],
        profundidad: int,
        en_camino: frozenset[str],
        contador: list[int],
    ) -> Optional[list[str]]:
        """Busca un plan para ``goal`` mutando ``estado`` con los efectos.

        Devuelve la lista de operadores en orden, o None si no hay plan.
        """
        contador[0] += 1
        if contador[0] > self.max_nodos:
            raise PlanningError("busqueda excedida (max_nodos)")
        if profundidad > self.max_depth:
            return None
        if goal in estado:
            return []
        if goal in en_camino:
            return None  # ciclo en la descomposicion
        op = self.operators.get(goal)
        if op is None:
            return None
        en_camino = en_camino | {goal}
        if op.subtasks:
            # HTN: descomponer en subtasks en orden; cada subplan actualiza el estado
            pasos: list[str] = []
            for sub in op.subtasks:
                subpasos = self._buscar(sub, estado, profundidad + 1, en_camino, contador)
                if subpasos is None:
                    return None
                for p in subpasos:
                    o = self.operators.get(p)
                    if o is not None:
                        estado.update(o.effects)
                pasos += subpasos
            # tras los subtasks, el goal compuesto se da por logrado si sus
            # precondiciones quedaron satisfechas (o no tiene)
            if all(p in estado for p in op.preconditions):
                estado.update(op.effects)
                return pasos
            return None
        # operador primitivo: aplicar si es aplicable
        if op.applicable(estado):
            estado.update(op.effects)
            return [op.name]
        return None


def plan_simple(objetivo: str = "informe_de_seguridad") -> Plan:
    """Planificador de ejemplo para objetivos de seguridad (demo determinista)."""
    ops = [
        Operator("recolectar", effects=("datos",)),
        Operator("analizar", preconditions=("datos",), effects=("hallazgos",)),
        Operator("redactar", preconditions=("hallazgos",), effects=("informe",)),
        Operator("validar", preconditions=("informe",), effects=("informe_validado",)),
        Operator(
            "informe_de_seguridad",
            subtasks=("recolectar", "analizar", "redactar", "validar"),
            preconditions=("informe_validado",),
            effects=("informe_validado",),
        ),
    ]
    pl = Planner(ops)
    if objetivo in pl.operators:
        return pl.plan(objetivo, set())
    return pl.plan("informe_de_seguridad", set())
