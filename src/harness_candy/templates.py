"""Motor de plantillas minimo (tipo Jinja reducido), solo stdlib.

Soporta:
  {{ expr }}            interpolacion con filtros: upper, lower, trim, length,
                        tojson, join(sep), default(x), int, float
  {% for x in xs %}...{% endfor %}     (xs puede ser lista; itera en orden)
  {% if expr %}...{% else %}...{% endif %}
  {% set x = expr %}
  {# comentario #}

Las plantillas se COMPILAN a codigo Python plano y se ejecutan con exec en un
namespace propio con __builtins__ vacio en las expresiones (eval controlado).
Usalas solo con plantillas del propio proyecto, igual que cualquier motor de
plantillas server-side.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, Callable

_TOKEN_RE = re.compile(r"({{.*?}}|{%.*?%}|{#.*?#})", re.DOTALL)


class TemplateError(ValueError):
    pass


_FILTERS: dict[str, Callable] = {
    "upper": lambda v: str(v).upper(),
    "lower": lambda v: str(v).lower(),
    "trim": lambda v: str(v).strip(),
    "length": lambda v: len(v),
    "tojson": lambda v: json.dumps(v, ensure_ascii=False, default=str),
    "join": lambda v, sep=", ": sep.join(str(x) for x in v),
    "default": lambda v, d="": d if v in (None, "", []) else v,
    "int": lambda v: int(v),
    "float": lambda v: float(v),
}


def _split_top(s: str, sep: str) -> list[str]:
    """Parte por ``sep`` respetando parentesis y strings."""
    out, depth, cur, in_str, q = [], 0, "", False, ""
    for ch in s:
        if in_str:
            cur += ch
            if ch == q:
                in_str = False
            continue
        if ch in ("'", '"'):
            in_str, q = True, ch
            cur += ch
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _compile_expr(expr: str) -> str:
    """'x | upper' -> "_FILTERS['upper'](_v('x'))"."""
    parts = [p.strip() for p in _split_top(expr, "|")]
    base, filters = parts[0], parts[1:]
    if not base:
        raise TemplateError(f"expresion vacia en {expr!r}")
    code = f"_v({base!r})"
    for f in filters:
        m = re.fullmatch(r"([a-z_]+)(?:\((.*)\))?", f, re.DOTALL)
        if not m or m.group(1) not in _FILTERS:
            raise TemplateError(f"filtro desconocido en {f!r}")
        args = m.group(2)
        code = f"_FILTERS[{m.group(1)!r}]({code}{', ' + args if args else ''})"
    return code


def _v(expr: str) -> Any:
    """Evalua ``expr`` en el namespace de la plantilla (frame llamador)."""
    frame = sys._getframe(1)
    return eval(expr, {"__builtins__": {}}, frame.f_globals)


def compile_template(src: str) -> Callable[..., str]:
    """Compila la plantilla a una funcion ``f(**ctx) -> str``."""
    tokens = _TOKEN_RE.split(src)
    lines = ["__out = []", "_append = __out.append"]
    indent = 0
    for tok in tokens:
        if not tok:
            continue
        pad = "    " * indent
        if tok.startswith("{#"):
            continue
        if tok.startswith("{{"):
            expr = tok[2:-2].strip()
            lines.append(pad + f"_append(str({_compile_expr(expr)}))")
        elif tok.startswith("{%"):
            stmt = tok[2:-2].strip()
            if stmt.startswith("for "):
                m = re.fullmatch(r"for (\w+) in (.+)", stmt, re.DOTALL)
                if not m:
                    raise TemplateError(f"for malformado: {stmt!r}")
                lines.append(pad + f"for {m.group(1)} in _v({m.group(2).strip()!r}):")
                indent += 1
            elif stmt == "endfor":
                indent -= 1
            elif stmt.startswith("if "):
                lines.append(pad + f"if _v({stmt[3:].strip()!r}):")
                indent += 1
            elif stmt == "else":
                indent -= 1
                lines.append("    " * indent + "else:")
                indent += 1
            elif stmt == "endif":
                indent -= 1
            elif stmt.startswith("set "):
                m = re.fullmatch(r"set (\w+) = (.+)", stmt, re.DOTALL)
                if not m:
                    raise TemplateError(f"set malformado: {stmt!r}")
                lines.append(pad + f"{m.group(1)} = _v({m.group(2).strip()!r})")
            else:
                raise TemplateError(f"sentencia desconocida: {stmt!r}")
        else:
            lines.append(pad + f"_append({tok!r})")
    if indent != 0:
        raise TemplateError("bloque sin cerrar (for/if)")
    lines.append("__result = ''.join(__out)")
    code = "\n".join(lines)
    compile(code, "<template>", "exec")  # valida sintaxis en compilacion

    def render(**ctx) -> str:
        ns: dict[str, Any] = {"_FILTERS": _FILTERS, "_v": _v}
        ns.update(ctx)
        exec(compile(code, "<template>", "exec"), ns)
        return ns["__result"]

    return render



# ---------------------------------------------------------------------------
# Herencia (extends/block) e includes
# ---------------------------------------------------------------------------

_EXTENDS_RE = re.compile(r"{%\s*extends\s+[\"']([^\"']+)[\"']\s*%}")
_BLOCK_RE = re.compile(r"{%\s*block\s+(\w+)\s*%}(.*?){%\s*endblock\s*%}", re.DOTALL)
_INCLUDE_RE = re.compile(r"{%\s*include\s+[\"']([^\"']+)[\"']\s*%}")


def _leer_plantilla(base_dir, nombre: str, vistos: frozenset) -> str:
    from pathlib import Path

    if nombre in vistos:
        raise TemplateError(f"include/extends ciclico: {nombre!r}")
    p = (Path(base_dir) / nombre).resolve()
    if base_dir is not None and not str(p).startswith(str(Path(base_dir).resolve())):
        raise TemplateError(f"plantilla fuera del directorio base: {nombre!r}")
    return p.read_text(encoding="utf-8")


def _expand(src: str, base_dir, vistos: frozenset = frozenset()) -> str:
    """Expande includes inline y herencia extends/block."""
    if base_dir is None:
        return src

    def _inc(m):
        return _expand(_leer_plantilla(base_dir, m.group(1), vistos), base_dir, vistos | {m.group(1)})

    src = _INCLUDE_RE.sub(_inc, src)
    m = _EXTENDS_RE.search(src)
    if m:
        nombre_base = m.group(1)
        base = _expand(_leer_plantilla(base_dir, nombre_base, vistos), base_dir, vistos | {nombre_base})
        bloques_hijo = {b.group(1): b.group(2) for b in _BLOCK_RE.finditer(src)}

        def _reemp(bm):
            return bloques_hijo.get(bm.group(1), bm.group(2))

        return _BLOCK_RE.sub(_reemp, base)
    return src


def render_string(src: str, base_dir=None, **ctx) -> str:
    return compile_template(_expand(src, base_dir))(**ctx)


def render_file(path, **ctx) -> str:
    from pathlib import Path

    p = Path(path)
    return render_string(p.read_text(encoding="utf-8"), base_dir=p.parent, **ctx)
