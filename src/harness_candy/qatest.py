"""QA de codigo generado: mutation testing + PBT/fuzz + mantenibilidad.

Capitulo 03 del documento exhaustivo, stdlib-only:

- ``mutar_fuente``: operadores de mutacion sobre el AST de una funcion
  (AOR aritmetico, ROR comparacion, inversion de condiciones, reemplazo de
  return, eliminacion de llamada). Cada mutante se compila y se corre contra
  los tests dados; ``mutation_score`` = muertos / total.
- ``fuzz_funcion``: property-based testing con generador de inputs con seed
  (reproducible) y corpus persistente; un crash se convierte automaticamente
  en test de regresion serializado.
- ``metricas_mantenibilidad``: LOC, complejidad ciclomática media (reusa
  diffengine), duplicacion (reusa summarize) y deuda tecnica estimada.
"""
from __future__ import annotations

import ast
import json
import random
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .diffengine import complejidad_ciclomatica
from .summarize import detectar_duplicados

OPERADORES = ("aor", "ror", "invertir_cond", "return_none", "quitar_llamada", "constante")


# ------------------------------------------------------------- mutation AST
class MutationError(RuntimeError):
    pass


def _operar_binop(op: ast.operator, operador: str) -> ast.operator | None:
    mapa_aor = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult}
    mapa_ror = {ast.Lt: ast.Gt, ast.Gt: ast.Lt, ast.LtE: ast.GtE, ast.GtE: ast.LtE, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
    if operador == "aor" and type(op) in mapa_aor:
        return mapa_aor[type(op)]()
    if operador == "ror" and type(op) in mapa_ror:
        return mapa_ror[type(op)]()
    return None


def mutar_fuente(src: str, nombre_fn: str, operador: str, *, rng: Optional[random.Random] = None) -> tuple[str, str]:
    """Aplica UN operador de mutacion a la funcion ``nombre_fn``.

    Devuelve (codigo_mutado, descripcion). Lanza MutationError si no hay
    nada que mutar con ese operador.
    """
    if operador not in OPERADORES:
        raise ValueError(f"operador desconocido {operador!r}; use {OPERADORES}")
    rng = rng or random.Random(0)
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nombre_fn), None)
    if fn is None:
        raise MutationError(f"no existe la funcion {nombre_fn!r}")
    desc = ""
    aplicado = False
    if operador in ("aor", "ror"):
        candidatas = [n for n in ast.walk(fn) if isinstance(n, ast.BinOp)]
        if candidatas:
            blanco = rng.choice(candidatas)
            nuevo = _operar_binop(blanco.op, operador)
            if nuevo is not None:
                blanco.op = nuevo
                desc = f"{operador}: {type(blanco.op).__name__} en linea {blanco.lineno}"
                aplicado = True
    elif operador == "invertir_cond":
        conds = [n for n in ast.walk(fn) if isinstance(n, (ast.If, ast.While))]
        if conds:
            blanco = rng.choice(conds)
            blanco.test = ast.UnaryOp(op=ast.Not(), operand=blanco.test)
            desc = f"invertir condicion en linea {blanco.lineno}"
            aplicado = True
    elif operador == "return_none":
        rets = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
        if rets:
            blanco = rng.choice(rets)
            blanco.value = None
            desc = f"return None en linea {blanco.lineno}"
            aplicado = True
    elif operador == "quitar_llamada":
        llamadas = [n for n in ast.walk(fn) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
        if llamadas:
            blanco = rng.choice(llamadas)
            # reemplaza la llamada por pass
            idx = fn.body.index(blanco)
            fn.body[idx] = ast.Pass()
            desc = f"eliminar llamada en linea {blanco.lineno}"
            aplicado = True
    elif operador == "constante":
        consts = [n for n in ast.walk(fn) if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and n.value != 0]
        if consts:
            blanco = rng.choice(consts)
            blanco.value = blanco.value + 1
            desc = f"constante {blanco.value - 1} -> {blanco.value} en linea {blanco.lineno}"
            aplicado = True
    if not aplicado:
        raise MutationError(f"el operador {operador!r} no encontro objetivo en {nombre_fn!r}")
    ast.fix_missing_locations(tree)
    return ast.unparse(tree), desc


@dataclass
class Mutante:
    operador: str
    descripcion: str
    codigo: str
    muerto: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return {"operador": self.operador, "descripcion": self.descripcion, "muerto": self.muerto, "error": self.error[:200]}


@dataclass
class MutationReport:
    archivo: str
    funcion: str
    mutantes: list[Mutante] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.mutantes)

    @property
    def muertos(self) -> int:
        return sum(1 for m in self.mutantes if m.muerto)

    @property
    def score(self) -> float:
        return self.muertos / self.total if self.total else 0.0

    def to_dict(self) -> dict:
        return {"archivo": self.archivo, "funcion": self.funcion, "total": self.total,
                "muertos": self.muertos, "mutation_score": round(self.score, 4),
                "mutantes": [m.to_dict() for m in self.mutantes]}


def run_mutation(
    src: str,
    nombre_fn: str,
    tests: Callable[[Callable[..., Any]], bool],
    *,
    operadores: Sequence[str] = OPERADORES,
    max_mutantes: int = 20,
    seed: int = 0,
) -> MutationReport:
    """Genera mutantes de ``nombre_fn`` y corre ``tests`` contra cada uno.

    ``tests(fn)`` debe devolver True si todos los tests pasan con esa version
    de la funcion. Un mutante "muerto" es aquel cuyos tests fallan.
    """
    rng = random.Random(seed)
    # compila la version original para saber su namespace base
    ns_original: dict[str, Any] = {}
    exec(compile(src, "<orig>", "exec"), ns_original)
    fn_original = ns_original[nombre_fn]
    if not tests(fn_original):
        raise MutationError("los tests ya fallan sobre el codigo original")
    rep = MutationReport(archivo="<src>", funcion=nombre_fn)
    for op in operadores:
        for _ in range(max(1, max_mutantes // len(operadores))):
            try:
                codigo, desc = mutar_fuente(src, nombre_fn, op, rng=rng)
            except MutationError:
                continue
            try:
                ast.parse(codigo)  # sanity: el mutante compila
            except SyntaxError as e:
                rep.mutantes.append(Mutante(op, desc, codigo, False, f"mutante no compila: {e}"))
                continue
            ns: dict[str, Any] = {}
            try:
                exec(compile(codigo, "<mut>", "exec"), ns)
                pasa = tests(ns[nombre_fn])
                rep.mutantes.append(Mutante(op, desc, codigo, not pasa, "" if pasa else "tests fallaron"))
            except Exception as e:  # noqa: BLE001 - un mutante que rompe es mutante muerto
                rep.mutantes.append(Mutante(op, desc, codigo, True, f"{type(e).__name__}: {e}"))
            if len(rep.mutantes) >= max_mutantes:
                return rep
    return rep


# ------------------------------------------------------------- PBT / fuzz
@dataclass
class FuzzFinding:
    input: Any
    error: str
    seed: int

    def to_dict(self) -> dict:
        return {"input": json.dumps(self.input, ensure_ascii=False, default=str), "error": self.error[:300], "seed": self.seed}


@dataclass
class FuzzReport:
    funcion: str
    n_ejecuciones: int = 0
    hallazgos: list[FuzzFinding] = field(default_factory=list)
    corpus_path: Optional[str] = None

    @property
    def crash_rate(self) -> float:
        return len(self.hallazgos) / self.n_ejecuciones if self.n_ejecuciones else 0.0

    def to_dict(self) -> dict:
        return {"funcion": self.funcion, "n": self.n_ejecuciones, "hallazgos": [h.to_dict() for h in self.hallazgos],
                "crash_rate": round(self.crash_rate, 6), "corpus": self.corpus_path}

    def guardar_corpus(self, path: str | Path) -> None:
        """Persiste los inputs problematicos como tests de regresion (corpus)."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        datos = [{"input": h.input, "error": h.error, "seed": h.seed} for h in self.hallazgos]
        p.write_text(json.dumps({"funcion": self.funcion, "regresiones": datos}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self.corpus_path = str(p)


def fuzz_funcion(
    fn: Callable[..., Any],
    generador: Callable[[random.Random], Any],
    propiedad: Callable[[Any, Any], bool],
    *,
    n: int = 200,
    seed: int = 0,
    nombre: str = "",
    guardar_en: Optional[str | Path] = None,
) -> FuzzReport:
    """PBT/fuzz con seed reproducible: genera inputs, corre fn, verifica la propiedad.

    ``propiedad(input, salida)`` -> True si se cumple. Cualquier excepcion de
    ``fn`` o propiedad falsa con error se registra como hallazgo; al final,
    si se pidio ``guardar_en``, los hallazgos se persisten como corpus de
    regresion.
    """
    if not callable(fn) or not callable(generador) or not callable(propiedad):
        raise TypeError("fn, generador y propiedad deben ser callables")
    rng = random.Random(seed)
    rep = FuzzReport(funcion=nombre or getattr(fn, "__name__", "fn"))
    for i in range(max(1, n)):
        inp = generador(rng)
        rep.n_ejecuciones += 1
        try:
            salida = fn(inp)
            if not propiedad(inp, salida):
                rep.hallazgos.append(FuzzFinding(inp, f"propiedad falsa en iter {i}: salida={salida!r}", seed))
        except Exception as e:  # noqa: BLE001 - el fuzz captura todo
            rep.hallazgos.append(FuzzFinding(inp, f"{type(e).__name__}: {e}", seed))
    if guardar_en:
        rep.guardar_corpus(guardar_en)
    return rep


# ------------------------------------------------------------- mantenibilidad
@dataclass
class Mantenibilidad:
    archivo: str
    loc: int
    funciones: int
    complejidad_media: float
    complejidad_max: int
    duplicados: int
    deuda_tecnica_estimada: float  # minutos: suma de (complejidad-5)+ * loc/funcion

    def to_dict(self) -> dict:
        return {"archivo": self.archivo, "loc": self.loc, "funciones": self.funciones,
                "complejidad_media": round(self.complejidad_media, 2), "complejidad_max": self.complejidad_max,
                "duplicados": self.duplicados, "deuda_min_estimada": round(self.deuda_tecnica_estimada, 1)}


def metricas_mantenibilidad(path: str | Path, *, umbral_duplicado: int = 80) -> Mantenibilidad:
    """Metricas de mantenibilidad de un archivo .py (capitulo 03 §mantenibilidad)."""
    p = Path(path)
    src = p.read_text(encoding="utf-8")
    lineas = src.splitlines()
    tree = ast.parse(src)
    fns = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    cx = complejidad_ciclomatica(src)
    vals = list(cx.values()) or [1]
    bloques = [l for l in lineas if len(l.strip()) > 20]
    dups = len(detectar_duplicados(bloques, umbral=umbral_duplicado)) if bloques else 0
    deuda = sum(max(0, c - 5) * (len(lineas) / max(1, len(fns))) for c in vals)
    return Mantenibilidad(
        archivo=str(p), loc=len(lineas), funciones=len(fns),
        complejidad_media=sum(vals) / len(vals), complejidad_max=max(vals),
        duplicados=dups, deuda_tecnica_estimada=deuda,
    )


def metricas_proyecto(dir_path: str | Path, *, patron: str = "*.py") -> dict:
    """Mantenibilidad agregada de un directorio: totals + archivos problematicos."""
    base = Path(dir_path)
    mats = [metricas_mantenibilidad(p) for p in sorted(base.rglob(patron)) if "__pycache__" not in str(p)]
    if not mats:
        return {"archivos": 0, "loc_total": 0, "deuda_min_total": 0.0, "problematicos": []}
    problematicos = [m.to_dict() for m in mats if m.complejidad_max > 10 or m.duplicados > 3]
    return {
        "archivos": len(mats),
        "loc_total": sum(m.loc for m in mats),
        "complejidad_media_global": round(sum(m.complejidad_media for m in mats) / len(mats), 2),
        "deuda_min_total": round(sum(m.deuda_tecnica_estimada for m in mats), 1),
        "problematicos": problematicos,
    }


# ------------------------------------------------------- mutation sobre diffs
def funciones_cambiadas(src_antes: str, src_despues: str) -> list[str]:
    """Nombres de funciones que cambiaron entre dos versiones (via ast_diff)."""
    from .diffengine import ast_diff

    diff = ast_diff(src_antes, src_despues)
    cambiadas: set[str] = set(diff.funciones_anadidas) | set(diff.funciones_eliminadas)
    cambiadas |= {m["name"] for m in diff.funciones_modificadas}
    # fallback por AST: funciones cuyo body cambio (hash del body)
    if not cambiadas:
        import ast as _ast
        def _firmas(src: str) -> dict[str, str]:
            tree = _ast.parse(src)
            out = {}
            for n in _ast.walk(tree):
                if isinstance(n, _ast.FunctionDef):
                    out[n.name] = ",".join(_ast.dump(st) for st in n.body)
            return out
        fa, fb = _firmas(src_antes), _firmas(src_despues)
        cambiadas = {k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k)}
    return sorted(cambiadas)


def run_mutation_diff(
    src_antes: str,
    src_despues: str,
    tests: Callable[[Callable[..., Any]], bool],
    *,
    operadores: Sequence[str] = OPERADORES,
    max_mutantes: int = 10,
    seed: int = 0,
) -> list[MutationReport]:
    """Mutation testing dirigido al diff: solo se mutan funciones cambiadas.

    Es la propuesta del documento (capitulo 03): en CI se mutan las lineas
    tocadas por el PR, no todo el archivo.
    """
    nombres = funciones_cambiadas(src_antes, src_despues)
    if not nombres:
        return []
    return [run_mutation(src_despues, nombre, tests, operadores=operadores, max_mutantes=max_mutantes, seed=seed + i)
            for i, nombre in enumerate(nombres)]
