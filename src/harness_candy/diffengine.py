"""Diff semantico de codigo (AST): que cambio entre dos versiones (v3 §5.8 review).

``ast_diff(src_a, src_b)`` compara dos fuentes Python y devuelve:
  - funciones anadidas / eliminadas / modificadas (cambio de firma o de body)
  - clases anadidas/eliminadas
  - imports anadidos/eliminados

Util para WEV/review de PRs: el review se fija en la SEMANTICA del cambio,
no en el texto del diff.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field


def _firmas(tree: ast.Module) -> dict[str, str]:
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.posonlyargs + node.args.args]
            if node.args.vararg:
                args.append("*" + node.args.vararg.arg)
            args += [a.arg for a in node.args.kwonlyargs]
            if node.args.kwarg:
                args.append("**" + node.args.kwarg.arg)
            ret = ast.unparse(node.returns) if node.returns else ""
            out[node.name] = f"({', '.join(args)}) -> {ret}"
    return out


def _firmas_clases(tree: ast.Module) -> dict[str, list[str]]:
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            out[node.name] = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return out


def _imports(tree: ast.Module) -> set[str]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name + (f" as {a.asname}" if a.asname else "") for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.add(f"from {node.module} import " + ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in node.names))
    return out


def _body_hash(tree: ast.Module, fname: str) -> str:
    import hashlib

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fname:
            return hashlib.sha256(ast.unparse(node).encode()).hexdigest()[:16]
    return ""


@dataclass
class CodeDiff:
    funciones_anadidas: list[str] = field(default_factory=list)
    funciones_eliminadas: list[str] = field(default_factory=list)
    funciones_modificadas: list[dict] = field(default_factory=list)  # {name, firma_antes, firma_despues, cambio_body}
    clases_anadidas: list[str] = field(default_factory=list)
    clases_eliminadas: list[str] = field(default_factory=list)
    imports_anadidos: list[str] = field(default_factory=list)
    imports_eliminados: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "funciones_anadidas": self.funciones_anadidas,
            "funciones_eliminadas": self.funciones_eliminadas,
            "funciones_modificadas": self.funciones_modificadas,
            "clases_anadidas": self.clases_anadidas,
            "clases_eliminadas": self.clases_eliminadas,
            "imports_anadidos": self.imports_anadidos,
            "imports_eliminados": self.imports_eliminados,
        }

    @property
    def hay_cambios(self) -> bool:
        d = self.to_dict()
        return any(v for v in d.values())

    @property
    def n_cambios(self) -> int:
        d = self.to_dict()
        return sum(len(v) if isinstance(v, list) else 0 for v in d.values())


def ast_diff(src_a: str, src_b: str) -> CodeDiff:
    """Compara dos fuentes Python semanticamente (por AST)."""
    ta = ast.parse(src_a)
    tb = ast.parse(src_b)
    fa, fb = _firmas(ta), _firmas(tb)
    ca, cb = _firmas_clases(ta), _firmas_clases(tb)
    ia, ib = _imports(ta), _imports(tb)
    diff = CodeDiff()
    diff.funciones_anadidas = sorted(set(fb) - set(fa))
    diff.funciones_eliminadas = sorted(set(fa) - set(fb))
    for nombre in sorted(set(fa) & set(fb)):
        firma_cambio = fa[nombre] != fb[nombre]
        body_cambio = _body_hash(ta, nombre) != _body_hash(tb, nombre)
        if firma_cambio or body_cambio:
            diff.funciones_modificadas.append(
                {
                    "name": nombre,
                    "firma_antes": fa[nombre],
                    "firma_despues": fb[nombre],
                    "cambio_firma": firma_cambio,
                    "cambio_body": body_cambio,
                }
            )
    diff.clases_anadidas = sorted(set(cb) - set(ca))
    diff.clases_eliminadas = sorted(set(ca) - set(cb))
    diff.imports_anadidos = sorted(ib - ia)
    diff.imports_eliminados = sorted(ia - ib)
    return diff


# ---------------------------------------------------------------------------
# Complejidad ciclomática y diff entre árboles de archivos
# ---------------------------------------------------------------------------

_DECISION_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.Assert)


def complejidad_ciclomatica(src: str) -> dict[str, int]:
    """Complejidad ciclomática por funcion (McCabe): 1 + decisiones + booleanos."""
    tree = ast.parse(src)
    out: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decisiones = 1
            for sub in ast.walk(node):
                if isinstance(sub, _DECISION_NODES):
                    decisiones += 1
                elif isinstance(sub, ast.BoolOp):
                    decisiones += len(sub.values) - 1
            out[node.name] = decisiones
    return out


def ast_diff_detallado(src_a: str, src_b: str) -> dict:
    """ast_diff + complejidad ciclomática antes/despues por funcion cambiada."""
    d = ast_diff(src_a, src_b).to_dict()
    ca = complejidad_ciclomatica(src_a)
    cb = complejidad_ciclomatica(src_b)
    for mod in d["funciones_modificadas"]:
        mod["cc_antes"] = ca.get(mod["name"], 0)
        mod["cc_despues"] = cb.get(mod["name"], 0)
        mod["cc_delta"] = mod["cc_despues"] - mod["cc_antes"]
    d["complejidad_total_antes"] = sum(ca.values())
    d["complejidad_total_despues"] = sum(cb.values())
    return d


def diff_arboles(dir_a: str, dir_b: str, *, globs=("**/*.py",)) -> dict[str, dict]:
    """Compara dos directorios archivo por archivo (por ruta relativa)."""
    from pathlib import Path

    ra, rb = Path(dir_a), Path(dir_b)
    archivos_a = {str(p.relative_to(ra)): p for g in globs for p in ra.glob(g) if p.is_file()}
    archivos_b = {str(p.relative_to(rb)): p for g in globs for p in rb.glob(g) if p.is_file()}
    out: dict[str, dict] = {}
    for rel in sorted(set(archivos_a) | set(archivos_b)):
        if rel not in archivos_a:
            out[rel] = {"estado": "anadido"}
        elif rel not in archivos_b:
            out[rel] = {"estado": "eliminado"}
        else:
            d = ast_diff(archivos_a[rel].read_text(encoding="utf-8"), archivos_b[rel].read_text(encoding="utf-8"))
            out[rel] = {"estado": "cambiado" if d.hay_cambios else "igual", "diff": d.to_dict()}
    return out
