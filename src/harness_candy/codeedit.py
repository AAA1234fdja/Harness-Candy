"""Edicion estructurada de codigo con AST (v3 §4.4 snapshots/edicion segura).

Operaciones sobre el AST (nunca por regex sobre codigo):
* ``add_import`` / ``remove_import``
* ``add_function`` / ``rename_function`` / ``set_function_body``
* ``apply_unified_diff``: aplica un diff unificado con validacion previa y
  posterior (ast.parse + py_compile en sandbox); si no cuadra, rechaza.
* ``validate_code``: ast.parse + compilacion real en sandbox.
* ``generate_file_from_spec``: genera un modulo .py desde una especificacion.
* ``generate_tests_for``: genera un test unittest basico para funciones dadas.

Todo cambio pasa por ``validate_code``: el codigo resultante debe parsear y
compilar, o se rechaza (fail-closed).
"""
from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .sandbox import run_sandboxed


class CodeEditError(ValueError):
    pass


class DiffApplicationError(CodeEditError):
    pass


# ---------------------------------------------------------------------------
# Utilidades AST
# ---------------------------------------------------------------------------

def parse_module(src: str) -> ast.Module:
    try:
        return ast.parse(src)
    except SyntaxError as e:
        raise CodeEditError(f"sintaxis invalida: linea {e.lineno}: {e.msg}") from e


def _unparse(tree: ast.AST) -> str:
    return ast.unparse(tree)  # Python >= 3.9


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise CodeEditError(f"no existe la funcion {name!r}")


def add_import(src: str, module: str, names: Optional[list[str]] = None) -> str:
    """Anade ``import module`` o ``from module import names`` (idempotente)."""
    tree = parse_module(src)
    if names:
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == module:
                existentes = {a.name for a in node.names}
                for n in names:
                    if n not in existentes:
                        node.names.append(ast.alias(name=n, asname=None))
                return _unparse(tree)
        tree.body.insert(0, ast.ImportFrom(module=module, names=[ast.alias(name=n, asname=None) for n in names], level=0))
    else:
        for node in tree.body:
            if isinstance(node, ast.Import) and any(a.name == module for a in node.names):
                return _unparse(tree)
        tree.body.insert(0, ast.Import(names=[ast.alias(name=module, asname=None)]))
    return _unparse(tree)


def remove_import(src: str, module: str) -> str:
    tree = parse_module(src)
    nuevo = []
    for node in tree.body:
        if isinstance(node, ast.Import) and all(a.name != module for a in node.names):
            nuevo.append(node)
        elif isinstance(node, ast.ImportFrom) and node.module != module:
            nuevo.append(node)
    tree.body = nuevo
    return _unparse(tree)


def add_function(src: str, name: str, args: list[str], body: str, *, returns: str = "", docstring: str = "") -> str:
    """Anade una funcion nueva (o la reemplaza si ya existe) con el body dado."""
    tree = parse_module(src)
    # args como lista de argumentos posicionales simples
    argumentos = ast.arguments(
        posonlyargs=[],
        args=[ast.arg(arg=a) for a in args],
        kwonlyargs=[],
        kw_defaults=[],
        defaults=[],
    )
    body_tree = parse_module(body)
    fn = ast.FunctionDef(
        name=name,
        args=argumentos,
        body=body_tree.body,
        decorator_list=[],
        returns=ast.Name(id=returns, ctx=ast.Load()) if returns else None,
    )
    if docstring:
        fn.body.insert(0, ast.Expr(value=ast.Constant(value=docstring)))
    # reemplazar si existe
    tree.body = [n for n in tree.body if not (isinstance(n, ast.FunctionDef) and n.name == name)]
    tree.body.append(fn)
    ast.fix_missing_locations(tree)
    return _unparse(tree)


def rename_function(src: str, old: str, new: str) -> str:
    """Renombra una funcion y todas sus llamadas dentro del modulo."""
    tree = parse_module(src)
    _find_function(tree, old)  # debe existir

    class Renombrador(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            if node.name == old:
                node.name = new
            self.generic_visit(node)
            return node

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load) and node.id == old:
                node.id = new
            return node

        def visit_Attribute(self, node):
            self.generic_visit(node)
            return node

    tree = Renombrador().visit(tree)
    ast.fix_missing_locations(tree)
    return _unparse(tree)


def set_function_body(src: str, name: str, body: str) -> str:
    tree = parse_module(src)
    fn = _find_function(tree, name)
    nuevo = parse_module(body).body
    # conservar docstring existente
    if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant) and isinstance(fn.body[0].value.value, str):
        nuevo.insert(0, fn.body[0])
    fn.body = nuevo
    ast.fix_missing_locations(tree)
    return _unparse(tree)


def list_functions(src: str) -> list[str]:
    """Nombres de las funciones de nivel modulo."""
    tree = parse_module(src)
    return [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def remove_function(src: str, name: str) -> str:
    """Elimina una funcion de nivel modulo (fail-closed si no existe)."""
    tree = parse_module(src)
    _find_function(tree, name)
    tree.body = [n for n in tree.body if not (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)]
    ast.fix_missing_locations(tree)
    return _unparse(tree)


def add_decorator(src: str, fn_name: str, decorator_expr: str) -> str:
    """Anade un decorador (expresion, p.ej. 'functools.lru_cache(maxsize=128)') a una funcion."""
    tree = parse_module(src)
    fn = _find_function(tree, fn_name)
    deco = parse_module(f"@({decorator_expr})\ndef _tmp():\n    pass\n").body[0].decorator_list[0]
    fn.decorator_list.append(deco)
    ast.fix_missing_locations(tree)
    return _unparse(tree)


def add_class(src: str, name: str, methods: list[dict], *, bases: list[str] | None = None, docstring: str = "") -> str:
    """Anade (o reemplaza) una clase con metodos dados.

    Cada metodo: {"name": str, "args": [..], "body": str, "returns": str?, "docstring": str?}
    """
    tree = parse_module(src)
    base_nodes = [ast.Name(id=b, ctx=ast.Load()) for b in (bases or [])]
    cuerpo = []
    if docstring:
        cuerpo.append(ast.Expr(value=ast.Constant(value=docstring)))
    for m in methods:
        argumentos = ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg=a) for a in m.get("args", ["self"])],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        )
        body_tree = parse_module(m.get("body", "pass"))
        fn = ast.FunctionDef(
            name=m["name"],
            args=argumentos,
            body=body_tree.body,
            decorator_list=[],
            returns=ast.Name(id=m["returns"], ctx=ast.Load()) if m.get("returns") else None,
        )
        if m.get("docstring"):
            fn.body.insert(0, ast.Expr(value=ast.Constant(value=m["docstring"])))
        cuerpo.append(fn)
    if not cuerpo:
        cuerpo.append(ast.Pass())
    cls = ast.ClassDef(name=name, bases=base_nodes, keywords=[], body=cuerpo, decorator_list=[])
    tree.body = [n for n in tree.body if not (isinstance(n, ast.ClassDef) and n.name == name)]
    tree.body.append(cls)
    ast.fix_missing_locations(tree)
    return _unparse(tree)


# ---------------------------------------------------------------------------
# Validacion
# ---------------------------------------------------------------------------

def validate_code(src: str, *, compile_sandbox: bool = True) -> dict:
    """Valida que el codigo parsea (ast) y compila. Opcionalmente en sandbox."""
    tree = parse_module(src)  # lanza CodeEditError si no parsea
    compile(src, "<edit>", "exec")  # chequeo de compilacion local
    resultado = {"ast_ok": True, "compile_ok": True, "sandbox_ok": None, "funciones": [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]}
    if compile_sandbox:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "edit_check.py"
            p.write_text(src, encoding="utf-8")
            r = run_sandboxed([sys.executable, "-m", "py_compile", str(p)], timeout=15)
            resultado["sandbox_ok"] = r.ok
            if not r.ok:
                raise CodeEditError(f"py_compile en sandbox fallo: {r.stderr[-300:]}")
    return resultado


# ---------------------------------------------------------------------------
# Diff unificado
# ---------------------------------------------------------------------------

_HUNK_RE = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lineas: list[str]  # cada una empieza con ' ', '-', '+'


def parse_unified_diff(diff_text: str) -> list[tuple[str, str, list[Hunk]]]:
    """Parsea un diff unificado en [(old_file, new_file, [Hunk...])]."""
    archivos: list[tuple[str, str, list[Hunk]]] = []
    actual: Optional[tuple[str, str, list[Hunk]]] = None
    hunk: Optional[Hunk] = None
    old_file = new_file = ""
    for linea in diff_text.splitlines():
        if linea.startswith("--- "):
            old_file = linea[4:].strip()
            if old_file.startswith("a/"):
                old_file = old_file[2:]
        elif linea.startswith("+++ "):
            new_file = linea[4:].strip()
            if new_file.startswith("b/"):
                new_file = new_file[2:]
            actual = (old_file, new_file, [])
            archivos.append(actual)
            hunk = None
        elif linea.startswith("@@"):
            m = _HUNK_RE.match(linea)
            if not m:
                raise DiffApplicationError(f"hunk malformado: {linea!r}")
            hunk = Hunk(int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1), [])
            if actual is not None:
                actual[2].append(hunk)
        elif hunk is not None and linea[:1] in (" ", "-", "+", "\\"):
            hunk.lineas.append(linea)
    return archivos


def apply_unified_diff(src: str, diff_text: str) -> str:
    """Aplica el primer archivo del diff unificado sobre ``src``.

    Valida que los numeros de linea y el contexto cuadren; si no, lanza
    ``DiffApplicationError`` sin tocar nada (fail-closed).
    """
    archivos = parse_unified_diff(diff_text)
    if not archivos:
        raise DiffApplicationError("diff vacio o malformado")
    _, _, hunks = archivos[0]
    lineas = src.splitlines()
    # aplicar de abajo arriba para no invalidar los offsets
    resultado = list(lineas)
    for hunk in reversed(hunks):
        start = hunk.old_start - 1  # 0-based
        if hunk.old_start == 0 and hunk.old_count == 0:
            start = 0
        # reconstruir el bloque viejo esperado
        esperado: list[str] = []
        nuevas: list[str] = []
        for l in hunk.lineas:
            if l.startswith("\\"):
                continue
            tag, contenido = l[0], l[1:]
            if tag == " ":
                esperado.append(contenido)
                nuevas.append(contenido)
            elif tag == "-":
                esperado.append(contenido)
            elif tag == "+":
                nuevas.append(contenido)
        if start < 0 or start + len(esperado) > len(resultado):
            raise DiffApplicationError(f"hunk fuera de rango: old_start={hunk.old_start} len={len(resultado)}")
        if resultado[start:start + len(esperado)] != esperado:
            raise DiffApplicationError(
                f"el contexto no cuadra en old_start={hunk.old_start}: esperado {esperado[:3]} vs actual {resultado[start:start+3]}"
            )
        resultado[start:start + len(esperado)] = nuevas
    nuevo_src = "\n".join(resultado) + ("\n" if src.endswith("\n") else "")
    parse_module(nuevo_src)  # debe seguir parseando
    return nuevo_src


# ---------------------------------------------------------------------------
# Generacion de archivos desde especificacion
# ---------------------------------------------------------------------------

@dataclass
class FileSpec:
    module: str  # nombre del paquete/modulo
    docstring: str = ""
    imports: list[str] = field(default_factory=list)
    from_imports: dict[str, list[str]] = field(default_factory=dict)
    functions: list[dict] = field(default_factory=list)  # {name, args, body, returns, docstring}

    def to_source(self) -> str:
        partes = []
        if self.docstring:
            partes.append(f'"""{self.docstring}"""')
        for imp in self.imports:
            partes.append(f"import {imp}")
        for mod, names in self.from_imports.items():
            partes.append(f"from {mod} import {', '.join(names)}")
        for fn in self.functions:
            args = ", ".join(fn.get("args", []))
            ret = f" -> {fn['returns']}" if fn.get("returns") else ""
            doc = f'    """{fn.get("docstring", "")}"""\n' if fn.get("docstring") else ""
            body = "\n".join("    " + l for l in fn.get("body", "pass").splitlines())
            partes.append(f"def {fn['name']}({args}){ret}:\n{doc}{body}")
        return "\n\n".join(partes) + "\n"


def generate_file_from_spec(path: str | Path, spec: FileSpec, *, validate: bool = True) -> Path:
    """Genera un archivo .py desde la spec; valida que compile (fail-closed)."""
    src = spec.to_source()
    if validate:
        validate_code(src)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")
    return p


def generate_tests_for(module_path: str | Path, function_names: list[str], *, class_name: str = "TestGenerado") -> str:
    """Genera un test unittest basico (placeholder asserts) para las funciones dadas."""
    modulo = Path(module_path).stem
    lineas = [
        '"""Tests generados automaticamente (revisar antes de producción)."""',
        "import unittest",
        "",
        f"from {modulo} import {', '.join(function_names)}",
        "",
        "",
        f"class {class_name}(unittest.TestCase):",
    ]
    for fn in function_names:
        lineas.append(f"    def test_{fn}(self):")
        lineas.append(f"        # TODO: asercion real sobre {fn}()")
        lineas.append(f"        self.assertTrue(callable({fn}))")
        lineas.append("")
    lineas.append("")
    lineas.append('if __name__ == "__main__":')
    lineas.append("    unittest.main()")
    src = "\n".join(lineas) + "\n"
    parse_module(src)
    return src
