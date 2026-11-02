"""DAG de tareas de YEV y su ejecucion (secciones 3 y 6.3).

YEV descompone el plan de ISA en un DAG de dependencias: las ramas
independientes corren en paralelo (work parallelism, nivel 1 / ADK) y las
dependientes esperan sus requisitos. Cada nodo tiene presupuesto, criterios
de aceptacion y reintentos maximos; si WEV rechaza y quedan reintentos, el
nodo se reintenta con la retroalimentacion del informe wev; si se agotan, la
tarea se escala (a ISA o a una persona).

Ademas se respetan los limites de la delegacion en subagentes: concurrencia
maxima y profundidad maxima.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .protocols import WevMessage
from .quality import Criterion


@dataclass
class TaskNode:
    task_id: str
    kind: str
    instruction: str
    deps: list[str] = field(default_factory=list)
    agent: str = "XEV"
    model: Optional[str] = None
    clave: Optional[str] = None
    presupuesto: dict = field(default_factory=dict)
    criterios: list[Criterion] = field(default_factory=list)
    max_reintentos: int = 2
    permite_subagentes: bool = False
    profundidad_max: int = 1
    inputs: dict = field(default_factory=dict)
    herramienta: str = ""  # p.ej. "shell", "security_scan"; XEV valida contra su allowlist
    deadline: Optional[float] = None  # plazo en segundos desde el inicio del nodo
    irreversible: bool = False  # si True, NO se ejecuta: pasa a revision humana


@dataclass
class NodeResult:
    task_id: str
    status: str  # pending | running | done | failed | escalated | cancelled | human_review
    artifact: Any = None
    wev: Optional[WevMessage] = None
    attempts: int = 0
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "attempts": self.attempts,
            "error": self.error,
            "wev": self.wev.to_dict() if self.wev else None,
            "duracion": round(self.finished_at - self.started_at, 3) if self.finished_at else 0.0,
        }


class TaskDAG:
    def __init__(self):
        self.nodes: dict[str, TaskNode] = {}

    def add(self, node: TaskNode) -> None:
        if node.task_id in self.nodes:
            raise ValueError(f"task_id duplicado: {node.task_id}")
        self.nodes[node.task_id] = node

    def validate(self) -> None:
        for n in self.nodes.values():
            for d in n.deps:
                if d not in self.nodes:
                    raise ValueError(f"{n.task_id} depende de {d!r} que no existe")
        # deteccion de ciclos (DFS)
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in self.nodes}

        def dfs(tid: str, stack: list[str]) -> None:
            color[tid] = GRAY
            stack.append(tid)
            for d in self.nodes[tid].deps:
                if color[d] == GRAY:
                    raise ValueError(f"ciclo detectado: {' -> '.join(stack + [d])}")
                if color[d] == WHITE:
                    dfs(d, stack)
            stack.pop()
            color[tid] = BLACK

        for tid in self.nodes:
            if color[tid] == WHITE:
                dfs(tid, [])

    def layers(self) -> list[list[str]]:
        """Agrupa los nodos en capas topologicas (Kahn por niveles)."""
        self.validate()
        remaining = dict(self.nodes)
        indeg = {tid: len(n.deps) for tid, n in self.nodes.items()}
        layers: list[list[str]] = []
        done: set[str] = set()
        while remaining:
            layer = [tid for tid, n in remaining.items() if all(d in done for d in n.deps)]
            if not layer:
                raise ValueError("grafo con ciclo no detectado en validate()")
            layers.append(sorted(layer))
            for tid in layer:
                done.add(tid)
                del remaining[tid]
        return layers

    def dependents(self) -> dict[str, list[str]]:
        deps_of: dict[str, list[str]] = {tid: [] for tid in self.nodes}
        for tid, n in self.nodes.items():
            for d in n.deps:
                deps_of[d].append(tid)
        return deps_of


# handler: (node, context) -> NodeResult (con wev opcional para reintentos)
Handler = Callable[[TaskNode, dict], NodeResult]


class DAGExecutor:
    """Ejecuta el DAG capa por capa; dentro de cada capa, en paralelo.

    Respeta ``max_concurrency`` (limite de concurrencia de la administracion)
    y ``max_depth`` (profundidad maxima de delegacion en subagentes).
    """

    def __init__(
        self,
        handler: Handler,
        *,
        max_concurrency: int = 4,
        max_depth: int = 2,
        on_event: Optional[Callable[[str, dict], None]] = None,
    ):
        self.handler = handler
        self.max_concurrency = max_concurrency
        self.max_depth = max_depth
        self.on_event = on_event or (lambda evt, data: None)

    def execute(self, dag: TaskDAG, context: dict | None = None) -> dict[str, NodeResult]:
        context = dict(context or {})
        context.setdefault("depth", 0)
        cancel_event = context.get("cancel_event")  # threading.Event opcional: cancela la ejecucion
        results: dict[str, NodeResult] = {}
        for layer in dag.layers():
            if cancel_event is not None and cancel_event.is_set():
                for tid in layer:
                    if tid not in results:
                        results[tid] = NodeResult(task_id=tid, status="cancelled", finished_at=time.time())
                        self.on_event("cancelled", {"task_id": tid})
                continue
            pending = {tid: dag.nodes[tid] for tid in layer}
            # reintentos con retroalimentacion wev mientras queden intentos
            while pending:
                with ThreadPoolExecutor(max_workers=self.max_concurrency) as pool:
                    futures = {
                        tid: pool.submit(self._run_one, node, context, results)
                        for tid, node in pending.items()
                    }
                    for tid, fut in futures.items():
                        results[tid] = fut.result()
                retry: dict[str, TaskNode] = {}
                for tid, node in pending.items():
                    res = results[tid]
                    if res.status == "rejected" and res.attempts <= node.max_reintentos:
                        # retroalimentacion: el informe wev viaja al reintento
                        context.setdefault("feedback", {})[tid] = res.wev.to_dict() if res.wev else {}
                        res.status = "running"
                        retry[tid] = node
                    elif res.status == "rejected":
                        res.status = "escalated"  # agoto reintentos -> escalar a ISA/persona
                        self.on_event("escalated", {"task_id": tid, "wev": res.wev.to_dict() if res.wev else None})
                pending = retry
        return results

    def _run_one(self, node: TaskNode, context: dict, results: dict[str, NodeResult]) -> NodeResult:
        res = results.get(node.task_id)
        attempts = (res.attempts if res else 0) + 1
        res = NodeResult(task_id=node.task_id, status="running", attempts=attempts, started_at=time.time())
        self.on_event("start", {"task_id": node.task_id, "attempt": attempts})
        # Revision humana: las operaciones irreversibles NO se ejecutan solos
        if node.irreversible:
            out = NodeResult(
                task_id=node.task_id, status="human_review", attempts=attempts,
                error="operacion irreversible: requiere aprobacion humana (ISA la marco)",
                started_at=res.started_at,
            )
            out.finished_at = time.time()
            self.on_event("human_review", {"task_id": node.task_id})
            return out
        # Plazo (deadline) por nodo
        started = context.get("node_started_at", {})
        if node.deadline is not None and node.task_id in started:
            if time.time() - started[node.task_id] > node.deadline:
                out = NodeResult(
                    task_id=node.task_id, status="failed", attempts=attempts,
                    error=f"deadline excedido ({node.deadline}s)", started_at=res.started_at,
                )
                out.finished_at = time.time()
                return out
        context.setdefault("node_started_at", {})[node.task_id] = time.time()
        try:
            out = self.handler(node, context)
            out.task_id = node.task_id
            out.attempts = attempts
            if out.status not in ("done", "failed", "rejected", "escalated"):
                out.status = "done" if out.wev is None or out.wev.veredicto == "aprobado" else "rejected"
            out.started_at = res.started_at
        except Exception as exc:  # manejo robusto de errores (seccion 4.3)
            out = NodeResult(
                task_id=node.task_id, status="failed", attempts=attempts,
                error=f"{type(exc).__name__}: {exc}", started_at=res.started_at,
            )
            self.on_event("error", {"task_id": node.task_id, "error": out.error})
        out.finished_at = time.time()
        self.on_event("end", {"task_id": node.task_id, "status": out.status})
        return out
