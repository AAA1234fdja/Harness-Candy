#!/usr/bin/env python3
"""Demo: levantar el servidor HTTP local y hacerle pedidos reales.

    python examples/demo_server.py

Endpoints: GET /health, POST /runs, GET /runs, GET /runs/{id}/report.html,
POST /suite, POST /golden, GET /schemas, GET /tools, GET /events (SSE).
Para dejarlo corriendo en vivo:  harness-candy serve --port 8000
"""
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness_candy.server import make_server


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=60) as r:
        return r.status, r.read().decode("utf-8")


def post(base, path, body):
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, r.read().decode("utf-8")


def main() -> int:
    root_repo = Path(__file__).resolve().parents[1]
    srv = make_server("127.0.0.1", 0, store=f"json://{root_repo/'runs_demo'}", trace_dir=root_repo / "traces", base_dir=root_repo)
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}"
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        status, body = get(base, "/health")
        print("GET /health ->", status, body)
        status, body = post(base, "/runs", {"objetivo": "informe de seguridad de src/", "inputs": {"root": "src"}, "seed": 0})
        run = json.loads(body)
        print(f"POST /runs -> {status} run_id={run['run_id']} estados={ {k: v['status'] for k, v in run['dag_results'].items()} }")
        status, body = get(base, "/runs?limit=5")
        print("GET /runs ->", status, "count =", json.loads(body)["count"])
        status, body = get(base, f"/runs/{run['run_id']}/report.html")
        print(f"GET /runs/{run['run_id']}/report.html -> {status} ({len(body)} bytes de HTML)")
        status, body = get(base, "/schemas/task")
        print("GET /schemas/task ->", status, json.loads(body)["$schema_version"])
        status, body = get(base, "/tools")
        print("GET /tools ->", status, [t["name"] for t in json.loads(body)["tools"]])
        time.sleep(0.1)
    finally:
        srv.shutdown()
        srv.server_close()
    print("servidor detenido (demo). Para servir en vivo: harness-candy serve --port 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
