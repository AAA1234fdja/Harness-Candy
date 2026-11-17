"""Reportes de corridas: JUnit XML, HTML autocontenido y Markdown (v3 §4.5).

Entrada: el ``to_dict()`` de un ``RunResult`` (o ``SuiteResult``). Salida:
archivos .xml (CI), .html (navegador) y .md (PRs). Todo con la stdlib
(``xml.etree.ElementTree`` escapa solo; en HTML se usa ``html.escape``).
"""
from __future__ import annotations

import html
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _fmt(x: Any) -> str:
    return html.escape(str(x))


def junit_xml(run: dict[str, Any], *, suite_name: str = "harness-candy") -> str:
    """Reporte JUnit XML a partir del dict de una corrida."""
    results = run.get("dag_results", {})
    n = len(results)
    failures = sum(1 for r in results.values() if r.get("status") in ("failed", "rejected"))
    errors = sum(1 for r in results.values() if r.get("status") == "escalated")
    skipped = sum(1 for r in results.values() if r.get("status") in ("cancelled", "human_review"))
    ts = ET.Element("testsuite", {
        "name": suite_name,
        "tests": str(n),
        "failures": str(failures),
        "errors": str(errors),
        "skipped": str(skipped),
        "time": str(run.get("duracion", 0.0)),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    for tid, r in results.items():
        case = ET.SubElement(ts, "testcase", {"name": tid, "classname": suite_name, "time": str(r.get("duracion", 0.0))})
        status = r.get("status", "")
        if status in ("failed", "rejected"):
            f = ET.SubElement(case, "failure", {"message": r.get("error") or "veredicto WEV: rechazado"})
            f.text = json.dumps(r.get("wev"), ensure_ascii=False, default=str)[:2000]
        elif status == "escalated":
            e = ET.SubElement(case, "error", {"message": r.get("error") or "escalado a humano"})
            e.text = json.dumps(r.get("wev"), ensure_ascii=False, default=str)[:2000]
        elif status in ("cancelled", "human_review"):
            ET.SubElement(case, "skipped", {"message": status})
    ET.indent(ts)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(ts, encoding="unicode")


_CSS = """
body{font-family:system-ui,sans-serif;margin:2rem;color:#1a1a1a}
h1{font-size:1.4rem} table{border-collapse:collapse;width:100%;margin:1rem 0}
th,td{border:1px solid #ccc;padding:.35rem .6rem;text-align:left;font-size:.9rem}
th{background:#f2f2f2} .ok{color:#0a7d00;font-weight:600} .bad{color:#b00020;font-weight:600}
code{background:#f6f6f6;padding:.1rem .3rem;border-radius:4px}
.metrics{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.5rem}
.card{border:1px solid #ddd;border-radius:8px;padding:.6rem .8rem;background:#fafafa}
"""


def html_report(run: dict[str, Any], *, title: str | None = None) -> str:
    """Reporte HTML autocontenido de una corrida."""
    title = title or f"Corrida {run.get('run_id', '?')}"
    rows = []
    for tid, r in run.get("dag_results", {}).items():
        status = r.get("status", "")
        cls = "ok" if status == "done" else "bad"
        q = run.get("qs", {}).get(tid, "")
        rows.append(
            "<tr>"
            f"<td><code>{_fmt(tid)}</code></td>"
            f"<td class='{cls}'>{_fmt(status)}</td>"
            f"<td>{_fmt(r.get('attempts', ''))}</td>"
            f"<td>{_fmt(r.get('duracion', ''))}</td>"
            f"<td>{_fmt(q)}</td>"
            f"<td><code>{_fmt((r.get('error') or '')[:120])}</code></td>"
            "</tr>"
        )
    metrics = run.get("metrics", {})
    cards = "".join(
        f"<div class='card'><b>{_fmt(k)}</b><br>{_fmt(v)}</div>" for k, v in metrics.items() if k != "nota"
    )
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>{_fmt(title)}</title><style>{_CSS}</style></head><body>
<h1>{_fmt(title)}</h1>
<p>Objetivo: {_fmt(run.get('objetivo', ''))} · duración: {_fmt(run.get('duracion'))}s ·
costo adaptación: {_fmt(run.get('costo_adaptacion'))} · traza: <code>{_fmt(run.get('trace_path', ''))}</code></p>
<h2>Métricas</h2><div class="metrics">{cards}</div>
<p><i>{_fmt(metrics.get('nota', ''))}</i></p>
<h2>Tareas (DAG)</h2>
<table><tr><th>Tarea</th><th>Estado</th><th>Intentos</th><th>Duración s</th><th>Q</th><th>Error</th></tr>
{''.join(rows)}
</table>
<h2>Auditoría ELY</h2><pre>{_fmt(json.dumps(run.get('ely_audit', {}), ensure_ascii=False, indent=2, default=str))}</pre>
</body></html>"""


def markdown_report(run: dict[str, Any]) -> str:
    """Reporte Markdown (para comentar en un PR)."""
    lines = [
        f"# Corrida `{run.get('run_id', '?')}`",
        "",
        f"- **Objetivo**: {run.get('objetivo', '')}",
        f"- **Duración**: {run.get('duracion')} s",
        f"- **Costo adaptación**: {run.get('costo_adaptacion')}",
        f"- **Tareas**: {len(run.get('dag_results', {}))}",
        "",
        "| Tarea | Estado | Intentos | Q | Error |",
        "|---|---|---|---|---|",
    ]
    for tid, r in run.get("dag_results", {}).items():
        q = run.get("qs", {}).get(tid, "")
        lines.append(f"| `{tid}` | {r.get('status')} | {r.get('attempts')} | {q} | {(r.get('error') or '')[:80]} |")
    m = run.get("metrics", {})
    if m:
        lines += ["", "## Métricas", ""]
        for k, v in m.items():
            lines.append(f"- **{k}**: {v}")
    return "\n".join(lines) + "\n"


def write_report(run: dict[str, Any], path: str | Path, *, fmt: str = "") -> Path:
    """Escribe el reporte en ``path``; el formato sale de la extension o de ``fmt``."""
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt == "xml":
        path.write_text(junit_xml(run), encoding="utf-8")
    elif fmt == "html":
        path.write_text(html_report(run), encoding="utf-8")
    elif fmt in ("md", "markdown"):
        path.write_text(markdown_report(run), encoding="utf-8")
    elif fmt == "json":
        path.write_text(json.dumps(run, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    else:
        raise ValueError(f"formato de reporte desconocido: {fmt!r} (xml|html|md|json)")
    return path
