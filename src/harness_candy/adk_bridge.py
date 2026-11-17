"""Puente YEV -> ADK: cada nodo del DAG se traduce en un agente de flujo.

Regla de acoplamiento del diseno combinado (seccion 3): YEV es el puente con
ADK; cada nodo del DAG se traduce en SequentialAgent, ParallelAgent o
LoopAgent, y las ramas independientes corren en paralelo.

Aqui ``build_flow_spec`` produce la especificacion determinista (util para
docs/tests). ``build_adk_flow`` construye los agentes reales de
``google.adk`` si el paquete esta instalado (extra ``adk``); si no, falla con
un mensaje claro. La logica de adaptacion Harness^2 vive en el adaptador y
ADK no necesita conocerla.
"""
from __future__ import annotations

from typing import Any, Callable

from .dag import TaskDAG


def build_flow_spec(dag: TaskDAG) -> dict:
    """Especificacion del flujo: capas topologicas -> sequential de parallel.

    Cada capa con un solo nodo es un paso secuencial; con varios, un
    ParallelAgent (fan-out / gather sobre session.state).
    """
    layers = dag.layers()
    steps = []
    for layer in layers:
        if len(layer) == 1:
            steps.append({"type": "sequential", "children": [{"type": "task", "task_id": layer[0]}]})
        else:
            steps.append(
                {
                    "type": "parallel",
                    "children": [{"type": "task", "task_id": tid} for tid in layer],
                }
            )
    return {"type": "sequential", "children": steps, "state": "session.state"}


def build_adk_flow(dag: TaskDAG, agent_factory: Callable[[str], Any]):
    """Construye agentes de flujo de google.adk para el DAG dado.

    Requiere ``pip install -e .[adk]``. Devuelve el agente raiz.
    """
    try:
        from google.adk.agents import LoopAgent, ParallelAgent, SequentialAgent
    except ImportError as exc:
        raise RuntimeError(
            "google-adk no esta instalado: instala el extra 'adk' "
            "(pip install -e .[adk]) o usa build_flow_spec() para la version "
            "sin dependencias."
        ) from exc

    def make(node_id: str):
        return agent_factory(node_id)

    children = []
    for layer in dag.layers():
        if len(layer) == 1:
            children.append(make(layer[0]))
        else:
            children.append(ParallelAgent(name=f"parallel-{'-'.join(layer)}", sub_agents=[make(t) for t in layer]))
    return SequentialAgent(name="ely_cowork_root", sub_agents=children)
