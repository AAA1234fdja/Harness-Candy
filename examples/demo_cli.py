#!/usr/bin/env python3
"""Demo: usar la CLI empaquetada (harness-candy ...) desde Python.

Equivalente a:
    harness-candy run --objetivo "informe de seguridad de src/" --input root=src --out /tmp/run.json
    harness-candy validate --schema task --file tarea.json
    harness-candy schemas --name suite
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness_candy.cli import main


def main_demo() -> int:
    root_repo = Path(__file__).resolve().parents[1]
    out = Path("/tmp/harness_candy_demo_run.json")
    print("== harness-candy version ==")
    main(["version"])
    print("== harness-candy run (backend scripted, sin red) ==")
    code = main([
        "run",
        "--objetivo", "generar informe de seguridad del paquete src/",
        "--input", "root=src",
        "--seed", "0",
        "--trace-dir", str(root_repo / "traces"),
        "--out", str(out),
        "--report", str(out.with_suffix(".html")),
    ])
    print(f"(exit={code}; 0 = todas las tareas done, 2 = alguna no aprobada)")
    print("== harness-candy validate ==")
    main(["validate", "--schema", "task", "--data", '{"task_id": "t", "kind": "k", "instruction": "i"}'])
    main(["validate", "--schema", "task", "--data", '{"task_id": "t"}'])  # invalido -> exit 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main_demo())
