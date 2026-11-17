"""Suite de evaluacion agregada: golden set x varias semillas + estadistica (v3 §5.9, §19, §21).

``run_eval_suite(golden, seeds=(0,1,2), ...)`` corre el golden set con cada
semilla y agrega:
  - pass_rate por semilla y global,
  - matriz de confusion de veredictos (esperado vs. obtenido),
  - intervalo bootstrap (percentil) del pass_rate global,
  - ``significancia_vs(otra)``: bootstrap de la diferencia de pass_rate
    (p-valor one-sided de que B > A).

``html_eval_report`` genera un reporte HTML autocontenido.
"""
from __future__ import annotations

import html
import json
import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .agents import Agent
from .components import WEV
from .evalkit import GoldenSet, run_golden
from .harness import Budget, HarnessStore
from .pool import ModelPool


@dataclass
class EvalSuiteResult:
    golden: str
    seeds: list[int]
    pass_rate_por_seed: dict[int, float]
    pass_rate_global: float
    matriz_confusion: dict[str, dict[str, int]]
    bootstrap: dict[str, float]  # p2.5, p50, p97.5 del pass_rate
    n_casos: int

    def to_dict(self) -> dict:
        return {
            "golden": self.golden,
            "seeds": self.seeds,
            "pass_rate_por_seed": {str(s): round(v, 4) for s, v in self.pass_rate_por_seed.items()},
            "pass_rate_global": round(self.pass_rate_global, 4),
            "matriz_confusion": self.matriz_confusion,
            "bootstrap": {k: round(v, 4) for k, v in self.bootstrap.items()},
            "n_casos": self.n_casos,
        }


def _bootstrap_pass_rate(valores: list[bool], n_boot: int = 2000, seed: int = 0) -> dict[str, float]:
    """Intervalo percentil bootstrap del pass rate."""
    if not valores:
        return {"p2_5": 0.0, "p50": 0.0, "p97_5": 0.0}
    rng = random.Random(seed)
    medias = []
    n = len(valores)
    for _ in range(n_boot):
        muestra = [rng.choice(valores) for _ in range(n)]
        medias.append(sum(muestra) / n)
    medias.sort()
    return {
        "p2_5": medias[int(0.025 * len(medias))],
        "p50": medias[len(medias) // 2],
        "p97_5": medias[min(len(medias) - 1, int(0.975 * len(medias)))],
    }


def run_eval_suite(
    golden: GoldenSet | str,
    *,
    agent: Agent,
    pool: ModelPool,
    store: HarnessStore,
    wev: WEV,
    seeds: tuple[int, ...] = (0, 1, 2),
    trace_dir: str = "traces",
    budget: Budget | None = None,
    n_boot: int = 2000,
    boot_seed: int = 0,
) -> EvalSuiteResult:
    """Corre el golden set con varias semillas y agrega estadistica."""
    if not isinstance(golden, GoldenSet):
        from .evalkit import load_golden

        golden = load_golden(golden)
    por_seed: dict[int, float] = {}
    todos_ok: list[bool] = []
    confusion: dict[str, dict[str, int]] = {"aprobado": {"aprobado": 0, "rechazado": 0}, "rechazado": {"aprobado": 0, "rechazado": 0}}
    for s in seeds:
        report = run_golden(
            golden, agent=agent, pool=pool, store=store,
            budget=budget or Budget(total=100_000, beta=0.5, k=2, m=3),
            wev=wev, trace_dir=Path(trace_dir) / f"seed{s}", seed=s,
        )
        por_seed[s] = report.pass_rate
        for r in report.results:
            esperado = "aprobado" if r.passed else "rechazado"
            obtenido = "aprobado" if r.veredicto == "aprobado" else "rechazado"
            confusion[esperado][obtenido] += 1
            todos_ok.append(r.passed)
    global_rate = sum(todos_ok) / len(todos_ok) if todos_ok else 0.0
    boot = _bootstrap_pass_rate(todos_ok, n_boot=n_boot, seed=boot_seed)
    return EvalSuiteResult(
        golden=golden.name,
        seeds=list(seeds),
        pass_rate_por_seed=por_seed,
        pass_rate_global=global_rate,
        matriz_confusion=confusion,
        bootstrap=boot,
        n_casos=len(todos_ok),
    )


def significancia_vs(a: EvalSuiteResult, b: EvalSuiteResult, *, n_boot: int = 2000, seed: int = 1) -> dict[str, Any]:
    """Bootstrap de la diferencia pass_rate_b - pass_rate_a (one-sided: B mejor)."""
    # aproximamos con las tasas por semilla de cada suite
    rng = random.Random(seed)
    va = [a.pass_rate_por_seed[s] for s in a.seeds]
    vb = [b.pass_rate_por_seed[s] for s in b.seeds]
    diffs = []
    for _ in range(n_boot):
        da = sum(rng.choice(va) for _ in va) / len(va)
        db = sum(rng.choice(vb) for _ in vb) / len(vb)
        diffs.append(db - da)
    diffs.sort()
    p_b_mejor = sum(1 for d in diffs if d > 0) / len(diffs)
    return {
        "delta_medio": round(statistics.fmean(diffs), 4),
        "p_b_mejor_que_a": round(p_b_mejor, 4),
        "significativo_95": p_b_mejor >= 0.95,
        "ic95_delta": [round(diffs[int(0.025 * len(diffs))], 4), round(diffs[int(0.975 * len(diffs))], 4)],
    }


def html_eval_report(result: EvalSuiteResult, *, extra: Optional[dict] = None) -> str:
    def e(x):
        return html.escape(str(x))

    filas_seed = "".join(f"<tr><td>{s}</td><td>{v:.3f}</td></tr>" for s, v in result.pass_rate_por_seed.items())
    mc = result.matriz_confusion
    tabla_mc = (
        "<table><tr><th>esperado \\ obtenido</th><th>aprobado</th><th>rechazado</th></tr>"
        f"<tr><td>aprobado</td><td>{mc['aprobado']['aprobado']}</td><td>{mc['aprobado']['rechazado']}</td></tr>"
        f"<tr><td>rechazado</td><td>{mc['rechazado']['aprobado']}</td><td>{mc['rechazado']['rechazado']}</td></tr></table>"
    )
    extra_html = ""
    if extra:
        extra_html = "<h2>Comparacion</h2><pre>" + e(json.dumps(extra, ensure_ascii=False, indent=2, default=str)) + "</pre>"
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Eval {e(result.golden)}</title>
<style>body{{font-family:system-ui;margin:2rem}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:.3rem .6rem}}</style>
</head><body>
<h1>Evaluacion: {e(result.golden)}</h1>
<p>pass_rate global: <b>{result.pass_rate_global:.3f}</b> ({result.n_casos} casos x {len(result.seeds)} semillas) ·
bootstrap IC95: [{result.bootstrap['p2_5']:.3f}, {result.bootstrap['p97_5']:.3f}]</p>
<h2>Por semilla</h2><table><tr><th>seed</th><th>pass_rate</th></tr>{filas_seed}</table>
<h2>Matriz de confusion (esperado vs obtenido)</h2>{tabla_mc}
{extra_html}
</body></html>"""


def pass_at_k(resultados: list[bool], k: int) -> float:
    """pass@k: fraccion de casos donde al menos uno de los primeros k intentos paso.

    Aqui cada caso ya es agregado por semilla; para listas planas de bool:
    pass@k sobre ventanas de k (estandar en eval de LLMs con n muestras).
    """
    if not resultados or k <= 0:
        return 0.0
    if k == 1:
        return sum(resultados) / len(resultados)
    # ventana deslizante de k: un caso cuenta si algun intento en la ventana paso
    n = len(resultados)
    exitos = 0
    for i in range(0, n, k):
        ventana = resultados[i:i + k]
        if any(ventana):
            exitos += 1
    return exitos / (n / k)


def exportar_csv(result: EvalSuiteResult, path: str | Path) -> Path:
    """Exporta el resumen de la suite a CSV (una fila por semilla)."""
    import csv

    p = Path(path)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["golden", "seed", "pass_rate"])
        for seed, pr in result.pass_rate_por_seed.items():
            w.writerow([result.golden, seed, f"{pr:.4f}"])
        w.writerow([result.golden, "global", f"{result.pass_rate_global:.4f}"])
    return p


def curva_pass_k(resultados: list[bool], ks: list[int] | None = None) -> dict[int, float]:
    """Curva pass@k para k = 1..len(resultados) (o los ks dados)."""
    if not resultados:
        return {}
    ks = ks or list(range(1, len(resultados) + 1))
    return {k: round(pass_at_k(resultados, k), 4) for k in ks if 1 <= k <= len(resultados)}


def markdown_eval_report(result: EvalSuiteResult, *, extra: Optional[dict] = None) -> str:
    """Reporte de evaluacion en Markdown (para PRs y docs)."""
    lineas = [
        f"# Evaluacion: {result.golden}",
        "",
        f"- pass_rate global: **{result.pass_rate_global:.3f}** ({result.n_casos} casos x {len(result.seeds)} semillas)",
        f"- bootstrap IC95: [{result.bootstrap['p2_5']:.3f}, {result.bootstrap['p97_5']:.3f}]",
        "",
        "## Por semilla",
        "",
        "| seed | pass_rate |",
        "|---|---|",
    ]
    for seed, pr in result.pass_rate_por_seed.items():
        lineas.append(f"| {seed} | {pr:.3f} |")
    mc = result.matriz_confusion
    lineas += [
        "",
        "## Matriz de confusion (esperado vs obtenido)",
        "",
        "| esperado \\ obtenido | aprobado | rechazado |",
        "|---|---|---|",
        f"| aprobado | {mc['aprobado']['aprobado']} | {mc['aprobado']['rechazado']} |",
        f"| rechazado | {mc['rechazado']['aprobado']} | {mc['rechazado']['rechazado']} |",
    ]
    if extra:
        lineas += ["", "## Comparacion", "", "```json", json.dumps(extra, ensure_ascii=False, indent=2, default=str), "```"]
    return "\n".join(lineas) + "\n"
