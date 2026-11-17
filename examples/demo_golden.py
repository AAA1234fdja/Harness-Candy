#!/usr/bin/env python3
"""Demo: correr un GOLDEN SET y aplicar la puerta (gate) de CI (v3 §5.9).

Uso:
    python examples/demo_golden.py [golden.json]

Exit 0 si pass_rate >= min_pass_rate; exit 2 si no (sirve directo en CI).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness_candy.agents import SecurityScanAgent
from harness_candy.components import WEV
from harness_candy.evalkit import load_golden, run_golden
from harness_candy.factory import make_backend, make_pool
from harness_candy.harness import Budget, HarnessStore
from harness_candy.security import SecurityGate


def main() -> int:
    root_repo = Path(__file__).resolve().parents[1]
    golden_path = Path(sys.argv[1]) if len(sys.argv) > 1 else root_repo / "examples" / "golden" / "security_scan.json"
    # los casos del golden usan rutas relativas al repo
    import os

    os.chdir(root_repo)
    golden = load_golden(golden_path)
    # rutas relativas -> absolutas (el sandbox usa cwd efimero)
    for c in golden.cases:
        if "root" in c.task.get("inputs", {}):
            c.task["inputs"]["root"] = str((root_repo / c.task["inputs"]["root"]).resolve())
    print(f"golden: {golden.name} ({len(golden.cases)} casos, min_pass_rate={golden.min_pass_rate})")
    report = run_golden(
        golden,
        agent=SecurityScanAgent("XEV", "modelo-ligero", make_backend("scripted")),
        pool=make_pool(),
        store=HarnessStore(),
        budget=Budget(total=100_000, beta=0.5, k=2, m=3),
        wev=WEV(SecurityGate()),
        trace_dir=root_repo / "traces",
        seed=0,
    )
    for r in report.results:
        estado = "PASS" if r.passed else "FAIL"
        print(f"  [{estado}] {r.case_id}: q={r.q:.3f} veredicto={r.veredicto} {r.reasons}")
    d = report.to_dict()
    print(f"pass_rate={d['pass_rate']} gate_ok={d['gate_ok']}")
    print(json.dumps({k: v for k, v in d.items() if k != "results"}, ensure_ascii=False, indent=2))
    try:
        report.assert_gate()
        return 0
    except AssertionError as e:
        print(f"GATE FALLO: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
