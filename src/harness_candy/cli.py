"""CLI de Harness-Candy (checklist v3 §4.2): run, suite, golden, report, validate, serve...

Solo librería estándar (argparse). Punto de entrada: ``harness-candy ...``
(definido en pyproject) o ``python -m harness_candy ...``.

Ejemplos:
    harness-candy version
    harness-candy run --objetivo "informe de seguridad del repo" --input root=. --out run.json
    harness-candy suite --file examples/suites/demo.json --report out.html
    harness-candy golden --file examples/golden/security_scan.json
    harness-candy report --run run.json --format html --out run.html
    harness-candy validate --schema task --file tarea.json
    harness-candy schemas --name run_result
    harness-candy serve --port 8000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__
from .agents import SecurityScanAgent, Task
from .components import WEV
from .evalkit import run_golden
from .factory import build_runner, make_backend, make_pool
from .harness import Budget, HarnessStore
from .quality import Criterion
from .report import write_report
from .runner import run_task
from .schemas import SCHEMAS, SchemaError, schema_json, validate_named
from .security import SecurityGate
from .storage import open_store
from .suite import load_suite, run_suite
from .tools import default_registry


def _parse_inputs(pairs: list[str]) -> dict:
    out: dict[str, Any] = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"--input invalido (esperaba clave=valor): {p!r}")
        k, v = p.split("=", 1)
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def _load_json_file(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _save_json(obj: Any, path: str | None) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")
        print(f"guardado en {path}", file=sys.stderr)
    else:
        print(text)


def cmd_version(args) -> int:
    print(f"harness-candy {__version__}")
    return 0


def cmd_schemas(args) -> int:
    text = schema_json(args.name)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"esquema guardado en {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


def cmd_validate(args) -> int:
    if args.file:
        data = _load_json_file(args.file)
    else:
        data = json.loads(args.data)
    try:
        validate_named(args.schema, data)
    except SchemaError as e:
        print(f"INVALIDO [{args.schema}]: {e}", file=sys.stderr)
        return 1
    print(f"OK [{args.schema}]")
    return 0


def cmd_run(args) -> int:
    runner = build_runner(args.trace_dir, backend_kind=args.backend)
    run = runner.run(args.objetivo, inputs=_parse_inputs(args.input), seed=args.seed)
    data = run.to_dict()
    if args.store:
        open_store(args.store).save(data)
    _save_json(data, args.out)
    if args.report:
        write_report(data, args.report)
        print(f"reporte en {args.report}", file=sys.stderr)
    return 0 if all(r.get("status") == "done" for r in data["dag_results"].values()) else 2


def cmd_task(args) -> int:
    t = _load_json_file(args.file)
    validate_named("task", t)
    pool = make_pool()
    backend = make_backend(args.backend)
    agent = SecurityScanAgent("XEV", "modelo-ligero", backend)
    task = Task(
        task_id=t["task_id"], kind=t["kind"], instruction=t.get("instruction", ""),
        inputs=t.get("inputs", {}),
        criterios=[Criterion(c["id"], c.get("descripcion", ""), float(c.get("peso", 1.0))) for c in t.get("criterios", [])],
        max_reintentos=int(t.get("max_reintentos", 2)),
    )
    budget = Budget(**(t.get("budget") or {"total": 10_000, "beta": 0.5, "k": 2, "m": 3}))
    wev = WEV(SecurityGate())
    artifact = run_task(task, agent, pool, HarnessStore(), budget, wev, seed=args.seed)
    msg, q = wev.evaluate(artifact, task.criterios)
    _save_json({"artifact": artifact.to_text(), "wev": msg.to_dict(), "q": q}, args.out)
    return 0 if msg.veredicto == "aprobado" else 2


def cmd_suite(args) -> int:
    suite = load_suite(args.file)
    if args.command == "list":
        _save_json({"suite": suite.name, "tasks": suite.task_list()}, args.out)
        return 0
    pool = make_pool()
    backend = make_backend(args.backend)
    agent = SecurityScanAgent("XEV", "modelo-ligero", backend)
    budget = Budget(**(suite.budget or {"total": 10_000, "beta": 0.5, "k": 2, "m": 3}))
    wev = WEV(SecurityGate())
    result = run_suite(suite, agent=agent, pool=pool, store=HarnessStore(), budget=budget, wev=wev, trace_dir=args.trace_dir)
    data = result.to_dict()
    if args.store:
        open_store(args.store).save(data)
    _save_json(data, args.out)
    if args.report:
        write_report(data, args.report)
    return 0 if all(r.get("status") == "done" for r in data["dag_results"].values()) else 2


def cmd_golden(args) -> int:
    pool = make_pool()
    backend = make_backend(args.backend)
    agent = SecurityScanAgent("XEV", "modelo-ligero", backend)
    report = run_golden(
        args.file, agent=agent, pool=pool, store=HarnessStore(), wev=WEV(SecurityGate()),
        trace_dir=args.trace_dir, seed=args.seed, max_cases=args.max_cases,
    )
    _save_json(report.to_dict(), args.out)
    try:
        report.assert_gate(args.min_pass_rate)
    except AssertionError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"golden OK: pass_rate={report.pass_rate:.3f} ({report.passed}/{report.total})")
    return 0


def cmd_report(args) -> int:
    run = _load_json_file(args.run)
    path = write_report(run, args.out, fmt=args.format)
    print(f"reporte {args.format} en {path}", file=sys.stderr)
    return 0


def cmd_bench(args) -> int:
    import runpy

    root = Path(__file__).resolve().parents[2]
    sys.argv = ["bench_escalabilidad.py", str(args.n)]
    runpy.run_path(str(root / "examples" / "bench_escalabilidad.py"), run_name="__main__")
    return 0


def cmd_cache(args) -> int:
    from .cache import ResponseCache

    cache = ResponseCache(args.dir, ttl_s=args.ttl)
    if args.clear:
        n = cache.clear()
        print(f"cache limpiado: {n} entradas borradas de {args.dir}")
    else:
        print(json.dumps(cache.stats(), ensure_ascii=False, indent=2))
    return 0


def cmd_tools(args) -> int:
    reg = default_registry(args.root)
    _save_json({"tools": reg.catalog()}, args.out)
    return 0


def cmd_serve(args) -> int:
    from .server import main as serve_main

    return serve_main(["--host", args.host, "--port", str(args.port), "--store", args.store, "--trace-dir", args.trace_dir, "--backend", args.backend])



def cmd_config(args) -> int:
    from .config import Config

    cfg = Config.load(args.file)
    data = cfg.to_safe_dict() if not args.full else cfg.to_dict()
    _save_json(data, args.out)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_summarize(args) -> int:
    from .summarize import summarize

    texto = Path(args.file).read_text(encoding="utf-8") if args.file else (args.text or "")
    if not texto.strip():
        print("texto vacio", file=sys.stderr)
        return 2
    s = summarize(texto, k=args.k)
    _save_json(s.to_dict(), args.out)
    print(s.texto)
    return 0


def cmd_rag(args) -> int:
    from .rag import RAGPipeline

    if args.command == "index":
        pipe = RAGPipeline(chunk_size=args.chunk, chunk_overlap=args.overlap)
        d = Path(args.dir)
        n = pipe.add_dir(d) if d.is_dir() else pipe.add_file(d)
        pipe.save(args.out)
        print(f"indexados {n} chunks -> {args.out} ({pipe.stats()})")
        return 0
    pipe = RAGPipeline.load(args.index or args.out)
    r = pipe.query(args.query or "", k=args.k)
    _save_json(r, args.out if args.command == "query" and args.query_out else None)
    for f in r["fragmentos"]:
        print(f"[{f['score']:.3f}] {f['procedencia']}#{f['indice']}: {f['contenido'][:140]}")
    return 0


def cmd_plan(args) -> int:
    from .planner import plan_simple

    p = plan_simple(args.objetivo)
    _save_json(p.to_dict(), args.out)
    print(" -> ".join(p.pasos) if p.pasos else "(objetivo ya satisfecho)")
    return 0


def cmd_review(args) -> int:
    from .review import ReviewAgent

    diff = Path(args.file).read_text(encoding="utf-8")
    msg = ReviewAgent().review_diff(diff)
    _save_json(msg.to_dict(), args.out)
    print(msg.veredicto)
    return 0 if msg.veredicto == "aprobado" else 2


def cmd_workflow(args) -> int:
    from .workflow import Workflow, run_workflow

    wf = Workflow.load(args.file)
    runner = build_runner(args.trace_dir, backend_kind=args.backend)
    agent = runner.xev.agents["XEV"]
    res = run_workflow(
        wf, agent=agent, pool=runner.pool, store=runner.store, budget=runner.budget,
        wev=runner.wev, trace_dir=args.trace_dir, seed=args.seed,
    )
    _save_json(res.to_dict(), args.out)
    for sid, st in res.steps.items():
        print(f"{sid}: {st.status}")
    return 0 if all(st.status != "failed" for st in res.steps.values()) else 2


def cmd_campaign(args) -> int:
    from .orchestrator import Campaign, run_campaign

    camp = Campaign.load(args.file)
    runner = build_runner(args.trace_dir, backend_kind=args.backend)
    res = run_campaign(camp, runner=runner, trace_dir=args.trace_dir)
    _save_json(res.to_dict(), args.out)
    print(res.resumen_ejecutivo())
    return 0


def cmd_codegen(args) -> int:
    from .codegen import scaffold_project

    files = scaffold_project(args.dir, args.name, author=args.author)
    for rel in sorted(files):
        print(rel)
    return 0


def cmd_evalsuite(args) -> int:
    from .evalsuite import html_eval_report, run_eval_suite

    pool = make_pool()
    backend = make_backend(args.backend)
    agent = SecurityScanAgent("XEV", "modelo-ligero", backend)
    seeds = tuple(int(x) for x in args.seeds.split(",") if x.strip())
    ev = run_eval_suite(
        args.file, agent=agent, pool=pool, store=HarnessStore(), wev=WEV(SecurityGate()),
        seeds=seeds, trace_dir=args.trace_dir,
    )
    _save_json(ev.to_dict(), args.out)
    if args.html:
        Path(args.html).write_text(html_eval_report(ev), encoding="utf-8")
        print(f"reporte HTML en {args.html}", file=sys.stderr)
    print(f"pass_rate={ev.pass_rate_global:.3f} ({ev.n_casos} casos) bootstrap={ev.bootstrap}")
    return 0


def cmd_watch(args) -> int:
    from .watch import WatchRunner

    eventos: list = []
    w = WatchRunner(args.dir, eventos.append, interval_s=args.interval)
    if args.once:
        ev = w.poll_once()
        _save_json(ev.to_dict() if ev else {"cambios": {}}, args.out)
        print("sin cambios" if ev is None else json.dumps(ev.to_dict(), ensure_ascii=False))
        return 0
    w.start()
    print(f"vigilando {args.dir} cada {args.interval}s (Ctrl+C para parar)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        w.stop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness-candy", description="Ely-Cowork ADK+Harness^2: orquestacion multiagente con calidad medible")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="muestra la version").set_defaults(fn=cmd_version)

    ps = sub.add_parser("schemas", help="imprime los esquemas JSON Schema publicados")
    ps.add_argument("--name", choices=sorted(SCHEMAS), default=None)
    ps.add_argument("--out", default=None)
    ps.set_defaults(fn=cmd_schemas)

    pv = sub.add_parser("validate", help="valida un JSON contra un esquema publicado")
    pv.add_argument("--schema", required=True, choices=sorted(SCHEMAS))
    pv.add_argument("--file", default=None)
    pv.add_argument("--data", default=None, help="JSON inline (si no se usa --file)")
    pv.set_defaults(fn=cmd_validate)

    pr = sub.add_parser("run", help="ejecuta un objetivo completo (ISA->...->ELY)")
    pr.add_argument("--objetivo", required=True)
    pr.add_argument("--input", action="append", default=[], help="clave=valor (repetible)")
    pr.add_argument("--seed", type=int, default=0)
    pr.add_argument("--backend", default="scripted", choices=["scripted", "xkiro"])
    pr.add_argument("--trace-dir", default="traces")
    pr.add_argument("--store", default=None, help="json://dir | sqlite://path.db")
    pr.add_argument("--out", default=None, help="guarda el RunResult JSON aqui")
    pr.add_argument("--report", default=None, help="p.ej. run.html (xml|html|md|json)")
    pr.set_defaults(fn=cmd_run)

    pt = sub.add_parser("task", help="ejecuta una sola tarea (JSON con esquema 'task')")
    pt.add_argument("--file", required=True)
    pt.add_argument("--seed", type=int, default=0)
    pt.add_argument("--backend", default="scripted", choices=["scripted", "xkiro"])
    pt.add_argument("--out", default=None)
    pt.set_defaults(fn=cmd_task)

    psu = sub.add_parser("suite", help="ejecuta (o lista con 'list') una suite JSON de tareas")
    psu.add_argument("command", nargs="?", default="run", choices=["run", "list"])
    psu.add_argument("--file", required=True)
    psu.add_argument("--backend", default="scripted", choices=["scripted", "xkiro"])
    psu.add_argument("--trace-dir", default="traces")
    psu.add_argument("--store", default=None)
    psu.add_argument("--out", default=None)
    psu.add_argument("--report", default=None)
    psu.set_defaults(fn=cmd_suite)

    pg = sub.add_parser("golden", help="corre un golden set y aplica el umbral min_pass_rate (exit 2 si falla)")
    pg.add_argument("--file", required=True)
    pg.add_argument("--backend", default="scripted", choices=["scripted", "xkiro"])
    pg.add_argument("--trace-dir", default="traces")
    pg.add_argument("--seed", type=int, default=0)
    pg.add_argument("--max-cases", type=int, default=None)
    pg.add_argument("--min-pass-rate", type=float, default=None)
    pg.add_argument("--out", default=None)
    pg.set_defaults(fn=cmd_golden)

    prep = sub.add_parser("report", help="genera un reporte (xml|html|md|json) de una corrida guardada")
    prep.add_argument("--run", required=True, help="archivo JSON del RunResult")
    prep.add_argument("--format", default=None, help="xml|html|md|json (default: extension de --out)")
    prep.add_argument("--out", required=True)
    prep.set_defaults(fn=cmd_report)

    pb = sub.add_parser("bench", help="bench de escalabilidad del DAG")
    pb.add_argument("n", nargs="?", type=int, default=24)
    pb.set_defaults(fn=cmd_bench)

    pc = sub.add_parser("cache", help="estadisticas o limpieza del cache de respuestas LLM")
    pc.add_argument("--dir", default=".harness_cache")
    pc.add_argument("--ttl", type=float, default=7 * 86400.0)
    pc.add_argument("--clear", action="store_true")
    pc.set_defaults(fn=cmd_cache)

    pto = sub.add_parser("tools", help="catalogo de herramientas registradas por defecto")
    pto.add_argument("--root", default=".")
    pto.add_argument("--out", default=None)
    pto.set_defaults(fn=cmd_tools)

    pse = sub.add_parser("serve", help="servidor HTTP local (API REST + SSE)")
    pse.add_argument("--host", default="0.0.0.0")
    pse.add_argument("--port", type=int, default=8000)
    pse.add_argument("--store", default="json://runs")
    pse.add_argument("--trace-dir", default="traces")
    pse.add_argument("--backend", default="scripted", choices=["scripted", "xkiro"])
    pse.set_defaults(fn=cmd_serve)

    pcf = sub.add_parser("config", help="muestra la configuracion efectiva (secretos enmascarados)")
    pcf.add_argument("--file", default=None, help="config.json o .env-lite opcional")
    pcf.add_argument("--full", action="store_true", help="sin enmascarar (cuidado)")
    pcf.add_argument("--out", default=None)
    pcf.set_defaults(fn=cmd_config)

    psm = sub.add_parser("summarize", help="resumen extractivo (TextRank-lite) de un texto")
    psm.add_argument("--file", default=None)
    psm.add_argument("--text", default=None)
    psm.add_argument("-k", type=int, default=3)
    psm.add_argument("--out", default=None)
    psm.set_defaults(fn=cmd_summarize)

    prag = sub.add_parser("rag", help="RAG propio: indexa documentos y responde con citas")
    prag.add_argument("command", choices=["index", "query"])
    prag.add_argument("--dir", default=None, help="directorio o archivo a indexar")
    prag.add_argument("--index", default=None, help="indice JSON existente (para query)")
    prag.add_argument("--out", default="rag_index.json", help="donde guardar indice/resultado")
    prag.add_argument("--query", default=None)
    prag.add_argument("--query-out", default=None)
    prag.add_argument("-k", type=int, default=4)
    prag.add_argument("--chunk", type=int, default=800)
    prag.add_argument("--overlap", type=int, default=120)
    prag.set_defaults(fn=cmd_rag)

    ppl = sub.add_parser("plan", help="plan HTN-lite de ejemplo (informe de seguridad)")
    ppl.add_argument("--objetivo", default="informe_de_seguridad")
    ppl.add_argument("--out", default=None)
    ppl.set_defaults(fn=cmd_plan)

    prev = sub.add_parser("review", help="revisa un diff unificado (WEV review de PR)")
    prev.add_argument("--file", required=True)
    prev.add_argument("--out", default=None)
    prev.set_defaults(fn=cmd_review)

    pwf = sub.add_parser("workflow", help="ejecuta un workflow declarativo JSON (steps task/set/parallel)")
    pwf.add_argument("--file", required=True)
    pwf.add_argument("--backend", default="scripted", choices=["scripted", "xkiro"])
    pwf.add_argument("--trace-dir", default="traces")
    pwf.add_argument("--seed", type=int, default=0)
    pwf.add_argument("--out", default=None)
    pwf.set_defaults(fn=cmd_workflow)

    pcam = sub.add_parser("campaign", help="campana de objetivos con presupuesto global (FinOps)")
    pcam.add_argument("--file", required=True)
    pcam.add_argument("--backend", default="scripted", choices=["scripted", "xkiro"])
    pcam.add_argument("--trace-dir", default="traces")
    pcam.add_argument("--out", default=None)
    pcam.set_defaults(fn=cmd_campaign)

    pcg = sub.add_parser("codegen", help="genera el esqueleto de un proyecto Python nuevo")
    pcg.add_argument("dir")
    pcg.add_argument("--name", required=True)
    pcg.add_argument("--author", default="AAA1234fdja")
    pcg.set_defaults(fn=cmd_codegen)

    pev = sub.add_parser("evalsuite", help="golden set x N semillas con intervalo bootstrap e informe HTML")
    pev.add_argument("--file", required=True)
    pev.add_argument("--seeds", default="0,1,2")
    pev.add_argument("--backend", default="scripted", choices=["scripted", "xkiro"])
    pev.add_argument("--trace-dir", default="traces")
    pev.add_argument("--out", default=None)
    pev.add_argument("--html", default=None)
    pev.set_defaults(fn=cmd_evalsuite)

    pwa = sub.add_parser("watch", help="vigila un directorio y reporta cambios (snapshots sha256)")
    pwa.add_argument("dir")
    pwa.add_argument("--once", action="store_true", help="una sola pasada de polling")
    pwa.add_argument("--interval", type=float, default=1.0)
    pwa.add_argument("--out", default=None)
    pwa.set_defaults(fn=cmd_watch)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
