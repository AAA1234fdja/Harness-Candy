"""Grafos dirigidos (DAG) propios, solo stdlib: orden topologico, niveles,
ruta critica y paralelismo (v3 §4.3 DAGExecutor ya ejecuta; aqui el analisis).

Usos:
  - workflow: validar dependencias entre steps (depends_on) y ordenarlos.
  - reportes: camino critico de una corrida (que tareas dominaron el tiempo).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


class CycleError(ValueError):
    pass


@dataclass
class DiGraph:
    """Grafo dirigido con pesos en aristas (duraciones/costos)."""

    edges: dict[str, dict[str, float]] = field(default_factory=dict)  # origen -> {destino: peso}

    def add_node(self, n: str) -> None:
        self.edges.setdefault(n, {})

    def add_edge(self, a: str, b: str, peso: float = 1.0) -> None:
        self.add_node(a)
        self.add_node(b)
        self.edges[a][b] = float(peso)

    @property
    def nodes(self) -> list[str]:
        return list(self.edges)

    def sucesores(self, n: str) -> dict[str, float]:
        return self.edges.get(n, {})

    def predecesores(self, n: str) -> dict[str, float]:
        out = {}
        for a, destinos in self.edges.items():
            if n in destinos:
                out[a] = destinos[n]
        return out

    def grado_entrada(self, n: str) -> int:
        return len(self.predecesores(n))

    def topo_sort(self) -> list[str]:
        """Kahn; lanza CycleError si hay ciclo."""
        entrada = {n: self.grado_entrada(n) for n in self.edges}
        # FIFO en orden de insercion: respeta el orden declarado salvo dependencias
        cola = [n for n, g in entrada.items() if g == 0]
        orden: list[str] = []
        while cola:
            n = cola.pop(0)
            orden.append(n)
            for m in self.edges[n]:
                entrada[m] -= 1
                if entrada[m] == 0:
                    cola.append(m)
        if len(orden) != len(self.edges):
            raise CycleError(f"ciclo detectado; ordenados {len(orden)}/{len(self.edges)}")
        return orden

    def hay_ciclo(self) -> bool:
        try:
            self.topo_sort()
            return False
        except CycleError:
            return True

    def niveles(self) -> dict[str, int]:
        """Nivel de cada nodo = longitud del camino mas largo desde una raiz."""
        orden = self.topo_sort()
        nivel = {n: 0 for n in self.edges}
        for n in orden:
            for m, _ in self.edges[n].items():
                nivel[m] = max(nivel[m], nivel[n] + 1)
        return nivel

    def ancho_por_nivel(self) -> dict[int, int]:
        niveles = self.niveles()
        ancho: dict[int, int] = {}
        for n, lv in niveles.items():
            ancho[lv] = ancho.get(lv, 0) + 1
        return ancho

    def max_paralelismo(self) -> int:
        """Cantidad maxima de tareas que pueden correr en paralelo (ancho max)."""
        return max(self.ancho_por_nivel().values()) if self.edges else 0

    def critical_path(self) -> tuple[list[str], float]:
        """Camino mas largo (suma de pesos) en el DAG; devuelve (nodos, costo)."""
        orden = self.topo_sort()
        dist = {n: 0.0 for n in self.edges}
        prev: dict[str, Optional[str]] = {n: None for n in self.edges}
        for n in orden:
            for m, peso in self.edges[n].items():
                if dist[n] + peso > dist[m]:
                    dist[m] = dist[n] + peso
                    prev[m] = n
        if not dist:
            return [], 0.0
        fin = max(dist, key=lambda n: dist[n])
        costo = dist[fin]
        camino = []
        while fin is not None:
            camino.append(fin)
            fin = prev[fin]
        return camino[::-1], costo

    def alcanzables(self, origen: str) -> set[str]:
        vistos = {origen}
        pila = [origen]
        while pila:
            n = pila.pop()
            for m in self.edges.get(n, {}):
                if m not in vistos:
                    vistos.add(m)
                    pila.append(m)
        return vistos

    def to_dict(self) -> dict:
        return {"edges": {a: dict(d) for a, d in self.edges.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> "DiGraph":
        g = cls()
        for a, destinos in d["edges"].items():
            for b, peso in destinos.items():
                g.add_edge(a, b, peso)
        return g

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict()), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "DiGraph":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def dependencias_a_grafo(deps: dict[str, Iterable[str]]) -> DiGraph:
    """Convierte {'tarea': ['dep1', 'dep2']} en DiGraph dep -> tarea."""
    g = DiGraph()
    for nodo, dependencias in deps.items():
        g.add_node(nodo)
        for d in dependencias:
            g.add_edge(d, nodo)
    return g
