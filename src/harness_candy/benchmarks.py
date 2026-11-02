"""Evaluador multi-benchmark local (capitulo 01 del documento exhaustivo).

Suites estandarizadas ejecutables localmente, sin dependencias externas:
- tipos de caso: ``mcq`` (opcion multiple, exact match), ``codigo`` (se ejecuta
  en sandbox y se compara la salida contra la esperada) y ``abierto``
  (contiene patron / juez opcional).
- few-shot por caso, semillas multiples y ``pass@k`` (reusa evalsuite).
- export a formatos interoperables: BenchmarkCard / EvaluationCard (JSON) y
  OLMES-style (campos modelo/tarea/metrica/valor/n/seed) para comparabilidad
  cross-harness (HELM/OLMES/EveryEvalEver consumen JSON de este tipo).

Todo stdlib-only; el "modelo" es cualquier callable ``ejecutar(prompt)->str``
(inyectable: en tests un fake determinista).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .evalsuite import curva_pass_k, pass_at_k
from .sandbox import run_sandboxed

TIPOS = ("mcq", "codigo", "abierto")


@dataclass
class BenchmarkCase:
    """Un caso de benchmark.

    - mcq: ``opciones`` (lista de textos) + ``esperada`` (indice o letra).
    - codigo: ``codigo_prompt`` (enunciado) + ``test_code`` (asserts) +
      ``esperada_stdout`` opcional; el codigo generado se ejecuta en sandbox.
    - abierto: ``patron`` (regex/substr que debe aparecer) o ``juez`` callable.
    """

    id: str
    tipo: str
    prompt: str
    few_shot: list[dict] = field(default_factory=list)  # [{"prompt":..., "respuesta":...}]
    opciones: list[str] = field(default_factory=list)
    esperada: Any = None
    test_code: str = ""
    expected_stdout: str = ""
    patron: str = ""
    dominio: str = "general"
    seed: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "tipo": self.tipo, "prompt": self.prompt,
            "few_shot": self.few_shot, "opciones": self.opciones, "esperada": self.esperada,
            "test_code": self.test_code, "expected_stdout": self.expected_stdout,
            "patron": self.patron, "dominio": self.dominio, "seed": self.seed,
        }

    @staticmethod
    def from_dict(d: dict) -> "BenchmarkCase":
        if d.get("tipo") not in TIPOS:
            raise ValueError(f"tipo de caso desconocido: {d.get('tipo')!r}; use {TIPOS}")
        return BenchmarkCase(
            id=str(d["id"]), tipo=d["tipo"], prompt=str(d.get("prompt", "")),
            few_shot=list(d.get("few_shot", [])), opciones=list(d.get("opciones", [])),
            esperada=d.get("esperada"), test_code=str(d.get("test_code", "")),
            expected_stdout=str(d.get("expected_stdout", "")), patron=str(d.get("patron", "")),
            dominio=str(d.get("dominio", "general")), seed=int(d.get("seed", 0)),
        )


@dataclass
class BenchmarkSuite:
    """Coleccion de casos con umbral de puerta (gate)."""

    name: str
    casos: list[BenchmarkCase]
    min_pass_rate: float = 0.9
    few_shot_global: int = 0
    metadata: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict) -> "BenchmarkSuite":
        return BenchmarkSuite(
            name=str(d.get("name", "suite")),
            casos=[BenchmarkCase.from_dict(c) for c in d.get("cases", [])],
            min_pass_rate=float(d.get("min_pass_rate", 0.9)),
            few_shot_global=int(d.get("few_shot", 0)),
            metadata=dict(d.get("metadata", {})),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name, "min_pass_rate": self.min_pass_rate,
            "few_shot": self.few_shot_global, "metadata": self.metadata,
            "cases": [c.to_dict() for c in self.casos],
        }

    def guardar(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_benchmark(path: str | Path) -> BenchmarkSuite:
    return BenchmarkSuite.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# ------------------------------------------------------------------ scoring
def construir_prompt(caso: BenchmarkCase, few_shot_extra: int = 0) -> str:
    """Monta el prompt con los ejemplos few-shot del caso (y globales de la suite)."""
    partes = []
    shots = list(caso.few_shot)
    for s in shots[: max(0, few_shot_extra) or len(shots)]:
        partes.append(f"P: {s.get('prompt', '')}\nR: {s.get('respuesta', '')}")
    if caso.tipo == "mcq" and caso.opciones:
        letras = [chr(ord("A") + i) for i in range(len(caso.opciones))]
        opts = "\n".join(f"{l}) {o}" for l, o in zip(letras, caso.opciones))
        partes.append(f"{caso.prompt}\n{opts}\nResponde SOLO con la letra.")
    else:
        partes.append(caso.prompt)
    return "\n\n".join(partes)


def puntuar_caso(caso: BenchmarkCase, salida: str, *, ejecutar_codigo: bool = True, juez: Optional[Callable[[str, str], float]] = None) -> tuple[bool, str]:
    """Puntua la salida del modelo para un caso. Devuelve (ok, detalle)."""
    texto = salida.strip()
    if caso.tipo == "mcq":
        m = re.search(r"\b([A-Z])\b", texto)  # primera letra aislada (A/B/C...)
        letra = m.group(1) if m else ""
        idx = ord(letra) - ord("A") if letra else -1
        esperado = caso.esperada
        if isinstance(esperado, str) and len(esperado) == 1 and esperado.isalpha():
            ok = letra == esperado.upper()
        else:
            ok = idx == int(esperado)
        return ok, f"letra={letra!r} esperada={esperado!r}"
    if caso.tipo == "codigo":
        if not ejecutar_codigo:
            return bool(caso.patron and caso.patron in texto), "sin ejecutar"
        # extraer bloque de codigo de la salida (```python ... ``` o todo)
        m = re.search(r"```(?:python)?\s*\n(.*?)```", texto, re.S)
        codigo = m.group(1) if m else texto
        test = caso.test_code or ""
        programa = codigo + "\n" + (test if test else f"print({json.dumps(caso.expected_stdout)})")
        res = run_sandboxed(["python3", "-c", programa], timeout=15.0, allow_network=False)
        if res.timed_out or res.returncode != 0:
            return False, f"fallo ejecucion rc={res.returncode} err={res.stderr[-200:]}"
        if caso.expected_stdout:
            return res.stdout.strip() == caso.expected_stdout.strip(), f"stdout={res.stdout.strip()[:120]!r}"
        return True, "test ok"
    # abierto
    if caso.patron:
        try:
            ok = re.search(caso.patron, texto, re.I) is not None
        except re.error:
            ok = caso.patron.lower() in texto.lower()
        return ok, f"patron {'hallado' if ok else 'no hallado'}"
    if juez is not None:
        return juez(caso.prompt, texto) >= 0.5, "juez"
    return bool(texto), "no vacio"


# ------------------------------------------------------------------ reporte
@dataclass
class BenchmarkReport:
    suite: str
    modelo: str
    total: int
    passed: int
    pass_at_1: float
    pass_at_k: float
    k: int
    por_dominio: dict[str, float]
    por_seed: dict[int, float]
    gate_ok: bool
    min_pass_rate: float
    duracion: float
    detalles: list[dict] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "suite": self.suite, "modelo": self.modelo, "total": self.total,
            "passed": self.passed, "pass_rate": round(self.pass_rate, 4),
            "pass_at_1": round(self.pass_at_1, 4), "pass_at_k": round(self.pass_at_k, 4), "k": self.k,
            "por_dominio": {d: round(v, 4) for d, v in self.por_dominio.items()},
            "por_seed": {str(s): round(v, 4) for s, v in self.por_seed.items()},
            "gate_ok": self.gate_ok, "min_pass_rate": self.min_pass_rate,
            "duracion": round(self.duracion, 3), "detalles": self.detalles,
        }


def run_benchmark(
    suite: BenchmarkSuite | str | Path,
    ejecutar: Callable[[str], str],
    *,
    modelo: str = "modelo-local",
    seeds: Sequence[int] = (0,),
    k: int = 1,
    judge: Optional[Callable[[str, str], float]] = None,
    max_casos: Optional[int] = None,
) -> BenchmarkReport:
    """Corre la suite con el ejecutor dado (callable prompt->texto).

    Cada caso se ejecuta una vez por semilla; ``pass@k`` usa ventanas de k
    sobre los intentos ordenados por (caso, seed).
    """
    if not isinstance(suite, BenchmarkSuite):
        suite = load_benchmark(suite)
    if not callable(ejecutar):
        raise TypeError("ejecutar debe ser callable(prompt)->str")
    inicio = time.time()
    casos = suite.casos[: max_casos] if max_casos else suite.casos
    detalles: list[dict] = []
    resultados_planos: list[bool] = []
    por_dominio: dict[str, list[bool]] = {}
    por_seed: dict[int, list[bool]] = {}
    for caso in casos:
        for seed in seeds:
            prompt = construir_prompt(caso, suite.few_shot_global)
            try:
                salida = ejecutar(prompt)
                ok, detalle = puntuar_caso(caso, salida, juez=judge)
            except Exception as e:  # noqa: BLE001 - un caso que explota no tumba la suite
                ok, detalle = False, f"{type(e).__name__}: {e}"
            detalles.append({"caso": caso.id, "seed": seed, "ok": ok, "detalle": detalle, "dominio": caso.dominio})
            resultados_planos.append(ok)
            por_dominio.setdefault(caso.dominio, []).append(ok)
            por_seed.setdefault(seed, []).append(ok)
    total = len(resultados_planos)
    passed = sum(resultados_planos)
    return BenchmarkReport(
        suite=suite.name, modelo=modelo, total=total, passed=passed,
        pass_at_1=pass_at_k(resultados_planos, 1),
        pass_at_k=pass_at_k(resultados_planos, max(1, k)),
        k=max(1, k),
        por_dominio={d: sum(v) / len(v) for d, v in por_dominio.items()},
        por_seed={s: sum(v) / len(v) for s, v in por_seed.items()},
        gate_ok=(passed / total if total else 0.0) >= suite.min_pass_rate,
        min_pass_rate=suite.min_pass_rate,
        duracion=time.time() - inicio,
        detalles=detalles,
    )


# ------------------------------------------------------- cards e interop
def benchmark_card(suite: BenchmarkSuite | str, report: BenchmarkReport, *, autor: str = "harness-candy", git_commit: str = "") -> dict:
    """BenchmarkCard minimo (interoperable): quien, que, cuanto, con que config."""
    return {
        "schema": "harness-candy/benchmark-card",
        "version": 1,
        "name": report.suite,
        "model_or_harness": report.modelo,
        "metric": {"name": "pass_rate", "value": round(report.pass_rate, 4), "pass_at_k": round(report.pass_at_k, 4), "k": report.k},
        "n_cases": report.total,
        "config": {"seeds": sorted({d["seed"] for d in report.detalles}), "min_pass_rate": suite.min_pass_rate if isinstance(suite, BenchmarkSuite) else report.min_pass_rate, "gate_ok": report.gate_ok},
        "por_dominio": report.por_dominio,
        "autor": autor,
        "git_commit": git_commit,
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def evaluation_card(report: BenchmarkReport) -> dict:
    """EvaluationCard: detalle por caso (para auditoria y EveryEvalEver-style)."""
    return {
        "schema": "harness-candy/evaluation-card",
        "version": 1,
        "suite": report.suite,
        "model_or_harness": report.modelo,
        "resumen": {k: v for k, v in report.to_dict().items() if k != "detalles"},
        "casos": report.detalles,
    }


def export_olmes(report: BenchmarkReport, *, modelo: str = "") -> dict:
    """Export estilo OLMES: {"nombre_tarea": {"metrica": valor, ...}} por corrida."""
    return {
        "modelo": modelo or report.modelo,
        "suite": report.suite,
        "metricas": {
            "exact_match": round(report.pass_at_1, 4),
            f"pass@{report.k}": round(report.pass_at_k, 4),
            "pass_rate": round(report.pass_rate, 4),
        },
        "n": report.total,
        "por_dominio": {d: round(v, 4) for d, v in report.por_dominio.items()},
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


# ------------------------------------------------------- comparativa multi-modelo
def comparar_modelos(
    ejecutores: dict[str, Callable[[str], str]],
    suite: BenchmarkSuite | str | Path,
    *,
    seeds: Sequence[int] = (0,),
    k: int = 1,
) -> dict:
    """Corre la misma suite con varios modelos y compara con estadistica.

    Devuelve por modelo su BenchmarkReport y, tomando el primero como
    referencia, el delta + p-valor Mann-Whitney one-sided de pass@k entre
    modelos (misma semilla = comparacion apareada por caso).
    """
    from .quality import mann_whitney_u

    if not ejecutores:
        raise ValueError("se necesita al menos un ejecutor")
    reportes: dict[str, BenchmarkReport] = {}
    for nombre, ej in ejecutores.items():
        reportes[nombre] = run_benchmark(suite, ej, modelo=nombre, seeds=seeds, k=k)
    base_name = next(iter(reportes))
    base = reportes[base_name]
    base_flags = [d["ok"] for d in base.detalles]
    comparacion: dict[str, dict] = {}
    for nombre, rep in reportes.items():
        if nombre == base_name:
            continue
        flags = [d["ok"] for d in rep.detalles]
        if len(flags) == len(base_flags):
            u, p = mann_whitney_u([float(f) for f in flags], [float(f) for f in base_flags])
            delta = rep.pass_rate - base.pass_rate
            comparacion[nombre] = {
                "delta_pass_rate": round(delta, 4),
                "p_value_mw": round(p, 6),
                "mejor_que_referencia": delta > 0 and p < 0.05,
            }
    return {
        "suite": base.suite,
        "referencia": base_name,
        "modelos": {n: r.to_dict() for n, r in reportes.items()},
        "comparacion_vs_referencia": comparacion,
    }


def reporte_benchmark_md(report: BenchmarkReport) -> str:
    """Reporte Markdown de una corrida de benchmark (para docs/PRs)."""
    lineas = [
        f"# Benchmark: {report.suite} — modelo `{report.modelo}`",
        "",
        f"- casos x semillas: {report.total} (pass_rate {report.pass_rate:.4f}, pass@{report.k} {report.pass_at_k:.4f})",
        f"- gate (>= {report.min_pass_rate}): **{'OK' if report.gate_ok else 'FALLO'}**",
        f"- duracion: {report.duracion:.2f}s",
        "",
        "| dominio | pass_rate |",
        "|---|---|",
    ]
    for d, v in sorted(report.por_dominio.items()):
        lineas.append(f"| {d} | {v:.4f} |")
    lineas += ["", "| caso | seed | ok | detalle |", "|---|---|---|---|"]
    for d in report.detalles:
        lineas.append(f"| {d['caso']} | {d['seed']} | {'✅' if d['ok'] else '❌'} | {d['detalle'][:80]} |")
    return "\n".join(lineas) + "\n"


def suites_desde_directorio(dir_path: str | Path, patron: str = "*.json") -> dict[str, BenchmarkSuite]:
    """Carga todas las suites de un directorio (p.ej. benchmarks/)."""
    base = Path(dir_path)
    out: dict[str, BenchmarkSuite] = {}
    for p in sorted(base.glob(patron)):
        s = load_benchmark(p)
        out[s.name] = s
    return out
