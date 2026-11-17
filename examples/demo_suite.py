#!/usr/bin/env python3
"""Demo: ejecutar una SUITE JSON de tareas como DAG (checklist v3 §4.4).

Uso:
    python examples/demo_suite.py [ruta_suite.json] [reporte_salida.html]

Por defecto usa examples/suites/demo.json (escaneo de seguridad de src/).
Sin red ni claves (backend scripted). El reporte HTML queda junto a la suite.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness_candy.agents import SecurityScanAgent, ScriptedBackend
from harness_candy.components import WEV
from harness_candy.factory import make_backend, make_pool
from harness_candy.harness import Budget, HarnessStore
from harness_candy.report import write_report
from harness_candy.security import SecurityGate
from harness_candy.suite import load_suite, run_suite


def main() -> int:
    import os

    root_repo = Path(__file__).resolve().parents[1]
    os.chdir(root_repo)  # las rutas relativas de la suite son desde la raiz del repo
    suite_path = Path(sys.argv[1]) if len(sys.argv) > 1 else root_repo / "examples" / "suites" / "demo.json"
    out_report = Path(sys.argv[2]) if len(sys.argv) > 2 else suite_path.with_suffix(".html")

    suite = load_suite(suite_path)
    # las rutas relativas se hacen absolutas (el sandbox corre con cwd efimero)
    for t in suite.tasks:
        if "root" in t.get("inputs", {}):
            t["inputs"]["root"] = str((root_repo / t["inputs"]["root"]).resolve())
    print(f"suite: {suite.name} ({len(suite.tasks)} tareas, seed={suite.seed})")
    for t in suite.task_list():
        print(f"  - {t['task_id']} [{t['kind']}] deps={t['deps']}")

    agent = SecurityScanAgent("XEV", "modelo-ligero", make_backend("scripted"))
    result = run_suite(
        suite,
        agent=agent,
        pool=make_pool(),
        store=HarnessStore(),
        budget=Budget(**(suite.budget or {"total": 10_000, "beta": 0.5, "k": 2, "m": 3})),
        wev=WEV(SecurityGate()),
        trace_dir=root_repo / "traces",
    )
    data = result.to_dict()
    for tid, r in data["dag_results"].items():
        print(f"  {tid}: {r['status']} (intentos={r['attempts']}, q={data['qs'].get(tid, '-')})")
    print(f"duracion: {data['duracion']}s | costo_adapt: {data['metrics'].get('costo_adaptacion')}")
    print(f"metricas: {json.dumps(data['metrics'], ensure_ascii=False)[:300]}...")
    write_report(data, out_report)
    print(f"reporte HTML: {out_report}")
    print(f"traza JSONL: {result.trace_path}")
    ok = all(r["status"] == "done" for r in data["dag_results"].values())
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
