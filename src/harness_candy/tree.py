"""Arbol de candidatos de harness (paper §3 Compose / busqueda en arbol).

Cada nodo es un candidato (``Harness``) con padre, score y profundidad.
Sirve para visualizar la exploracion Propose->Probe y elegir el adoptado
(ver ``selection.py``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class TreeNode:
    id: str
    harness_label: str
    parent_id: Optional[str]
    score: float = 0.0
    depth: int = 0
    meta: dict = field(default_factory=dict)
    children: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "harness_label": self.harness_label, "parent_id": self.parent_id,
                "score": round(self.score, 6), "depth": self.depth, "meta": self.meta, "children": list(self.children)}


class HarnessTree:
    """Arbol de candidatos con raiz = harness de referencia (h0)."""

    def __init__(self, root_label: str = "h0", root_score: float = 0.0):
        self.nodes: dict[str, TreeNode] = {}
        self.root = self._add("root", root_label, None, root_score, 0).id

    def _add(self, nid: str, label: str, parent: Optional[str], score: float, depth: int, meta: dict | None = None) -> TreeNode:
        node = TreeNode(id=nid, harness_label=label, parent_id=parent, score=score, depth=depth, meta=meta or {})
        self.nodes[nid] = node
        if parent is not None and parent in self.nodes:
            self.nodes[parent].children.append(nid)
        return node

    def add_candidate(self, label: str, score: float, parent_id: str = "root", meta: dict | None = None) -> TreeNode:
        """Anade un candidato bajo ``parent_id`` (por defecto la raiz)."""
        if parent_id not in self.nodes:
            raise KeyError(f"padre desconocido: {parent_id!r}")
        nid = f"c{len(self.nodes)}"
        return self._add(nid, label, parent_id, score, self.nodes[parent_id].depth + 1, meta)

    def add_branch(self, label: str, score: float, parent_id: str, meta: dict | None = None) -> TreeNode:
        """Anade un nodo intermedio (sub-arbol) bajo otro nodo."""
        return self.add_candidate(label, score, parent_id, meta)

    def update_score(self, nid: str, score: float) -> None:
        self.nodes[nid].score = score

    def best(self, k: int = 1, incluir_raiz: bool = False) -> list[TreeNode]:
        nodos = [n for n in self.nodes.values() if incluir_raiz or n.id != "root"]
        return sorted(nodos, key=lambda n: n.score, reverse=True)[:k]

    def path_to(self, nid: str) -> list[TreeNode]:
        if nid not in self.nodes:
            raise KeyError(nid)
        camino = []
        actual: Optional[str] = nid
        while actual is not None:
            camino.append(self.nodes[actual])
            actual = self.nodes[actual].parent_id
        return camino[::-1]

    def leaves(self) -> list[TreeNode]:
        return [n for n in self.nodes.values() if not n.children]

    def podar(self, umbral: float) -> int:
        """Elimina nodos (y sus hijos) con score < umbral. Devuelve cuantos quito."""
        a_quitar = [nid for nid, n in self.nodes.items() if nid != "root" and n.score < umbral]
        for nid in a_quitar:
            self._quitar_recursivo(nid)
        return len(a_quitar)

    def _quitar_recursivo(self, nid: str) -> None:
        node = self.nodes.get(nid)
        if node is None:
            return
        for hijo in list(node.children):
            self._quitar_recursivo(hijo)
        if node.parent_id and node.parent_id in self.nodes:
            try:
                self.nodes[node.parent_id].children.remove(nid)
            except ValueError:
                pass
        del self.nodes[nid]

    @property
    def profundidad(self) -> int:
        return max((n.depth for n in self.nodes.values()), default=0)

    @property
    def ancho(self) -> int:
        return len(self.nodes)

    def to_dict(self) -> dict:
        return {"root": self.root, "nodes": {k: v.to_dict() for k, v in self.nodes.items()}}

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def from_dict(cls, d: dict) -> "HarnessTree":
        t = cls.__new__(cls)
        t.nodes = {}
        for nid, nd in d["nodes"].items():
            t.nodes[nid] = TreeNode(id=nd["id"], harness_label=nd["harness_label"], parent_id=nd["parent_id"],
                                    score=nd["score"], depth=nd["depth"], meta=nd.get("meta", {}), children=list(nd.get("children", [])))
        t.root = d["root"]
        return t

    @classmethod
    def load(cls, path: str | Path) -> "HarnessTree":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def ascii(self, nid: str = "root", prefijo: str = "") -> str:
        """Dibujo ASCII del (sub)arbol con scores."""
        if nid not in self.nodes:
            return ""
        n = self.nodes[nid]
        linea = f"{prefijo}{n.harness_label} (q={n.score:.3f}, prof={n.depth})"
        hijos = n.children
        out = [linea]
        for i, h in enumerate(hijos):
            ultimo = i == len(hijos) - 1
            out.append(self.ascii(h, prefijo + ("    " if ultimo else "|   ")))
        return "\n".join(out)
