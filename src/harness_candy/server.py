"""Servidor HTTP local: API REST + SSE para correr y consultar corridas (v3 §6.2, §14).

Endpoints (todo JSON salvo los reportes):
    GET  /health                     estado y version
    GET  /runs?limit=N               lista de corridas guardadas
    POST /runs    {"objetivo":..., "inputs":{...}, "seed":N}   ejecuta y guarda
    GET  /runs/{id}                  detalle de una corrida
    DEL  /runs/{id}                  borra una corrida
    GET  /runs/{id}/report.{xml,html,md,json}
    POST /suite   (body = suite JSON)  ejecuta una suite completa
    POST /golden  {"path": "...json"}  corre un golden set (gate 200/422)
    GET  /schemas[/nombre]           esquemas JSON Schema publicados
    GET  /tools                      catalogo de herramientas registradas
    GET  /events?timeout=S           stream SSE de eventos del bus

Seguridad: cuerpo limitado a 1 MB, sin logueo de cuerpos, acepta cualquier
Host (necesario para el preview), y las tareas ejecutadas pasan por XEV/WEV
(allowlist + sandbox) como cualquier otra corrida. Pensado para correr local
(``harness-candy serve --port 8000``); detras de un proxy publico va con TLS.
"""
from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from . import __version__
from .agents import SecurityScanAgent
from .alerts import BudgetMonitor, LogSink
from .auth import IpRateLimiter, TokenAuth
from .components import WEV
from .evalkit import run_golden
from .factory import build_runner, make_backend, make_pool
from .harness import Budget, HarnessStore
from .metrics_export import prometheus_text
from .report import write_report
from .schemas import SCHEMAS, SCHEMA_VERSION, schema_json
from .scheduler import Scheduler
from .security import SecurityGate
from .storage import JsonRunStore, RunStore, open_store
from .streaming import EventBus, SseBroadcaster
from .suite import Suite, run_suite
from .tools import default_registry
from .web import dashboard_html

MAX_BODY = 1_000_000  # 1 MB


class ServerConfig:
    def __init__(
        self,
        *,
        store: RunStore | None = None,
        trace_dir: str | Path = "traces",
        runs_dir: str | Path = "runs",
        backend_kind: str = "scripted",
        bus: EventBus | None = None,
        base_dir: str | Path = ".",
        auth: TokenAuth | None = None,
        rate_limit: int = 120,
        rate_window_s: float = 60.0,
        enable_scheduler: bool = True,
    ):
        self.store = store or JsonRunStore(runs_dir)
        self.trace_dir = trace_dir
        self.backend_kind = backend_kind
        self.bus = bus or EventBus()
        self.broadcaster = SseBroadcaster(self.bus)
        self.base_dir = Path(base_dir).resolve()
        self.tools = default_registry(self.base_dir)
        self.auth = auth if auth is not None else TokenAuth()  # se activa solo si hay HARNESS_API_TOKEN
        self.limiter = IpRateLimiter(limit=rate_limit, window_s=rate_window_s)
        self._runner = None
        self._runner_lock = threading.Lock()
        self.budget_monitor: BudgetMonitor | None = None
        # scheduler de suites periodicas (jobs), con run_fn real
        if enable_scheduler:
            self.scheduler = Scheduler(self._run_suite_job, base_dir=self.base_dir)
        else:
            self.scheduler = None

    def _run_suite_job(self, job) -> str:
        """Ejecuta la suite de un job y guarda el resultado; devuelve el status."""
        from .suite import load_suite

        p = (self.base_dir / job.suite_path).resolve()
        suite = load_suite(p)
        for t in suite.tasks:
            if "root" in t.get("inputs", {}):
                t["inputs"]["root"] = str((self.base_dir / t["inputs"]["root"]).resolve())
        pool = make_pool()
        agent = SecurityScanAgent("XEV", "modelo-ligero", make_backend(self.backend_kind))
        budget = Budget(**(suite.budget or {"total": 10_000, "beta": 0.5, "k": 2, "m": 3}))
        self.budget_monitor = BudgetMonitor(budget, LogSink(), event_bus=self.bus)
        result = run_suite(
            suite, agent=agent, pool=pool, store=HarnessStore(), budget=budget,
            wev=WEV(SecurityGate()), trace_dir=self.trace_dir,
            on_event=lambda ev, d: self.bus.emit(ev, d),
        )
        data = result.to_dict()
        self.store.save(data)
        self.budget_monitor.notify_spent()
        estados = {r["status"] for r in data["dag_results"].values()}
        return ",".join(sorted(estados))

    @property
    def runner(self):
        """Runner perezoso (se crea al primer uso para no pagar arranque en /health)."""
        with self._runner_lock:
            if self._runner is None:
                self._runner = build_runner(self.trace_dir, backend_kind=self.backend_kind)
            return self._runner


class HarnessHandler(BaseHTTPRequestHandler):
    server_version = f"HarnessCandy/{__version__}"
    protocol_version = "HTTP/1.1"

    # -- utilidades ---------------------------------------------------------
    def log_message(self, fmt, *args):  # silencio de access log (los cuerpos nunca se loguean)
        pass

    @property
    def cfg(self) -> ServerConfig:
        return self.server.cfg  # type: ignore[attr-defined]

    def _send_json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, content_type: str, status: int = 200) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError(f"cuerpo demasiado grande ({length} bytes > {MAX_BODY})")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON invalido: {e}") from e
        if not isinstance(data, dict):
            raise ValueError("el cuerpo debe ser un objeto JSON")
        return data

    # -- guardas de acceso (auth bearer opcional + rate limit por IP) --------
    def _guard(self, path: str):
        """Devuelve (status, payload) de rechazo, o None si se puede seguir."""
        if path != "/health" and not self.cfg.auth.check_header(self.headers.get("Authorization")):
            return 401, {"error": "falta o invalido Authorization: Bearer <HARNESS_API_TOKEN>"}
        ip = self.client_address[0] if self.client_address else "?"
        if not self.cfg.limiter.allow(ip):
            return 429, {"error": "rate limit excedido", "remaining": 0}
        return None

    # -- rutas ----------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        try:
            u = urlparse(self.path)
            path = u.path.rstrip("/") or "/"
            qs = parse_qs(u.query)
            rech = self._guard(path)
            if rech is not None:
                return self._send_json(rech[1], status=rech[0])
            if path == "/" or path == "/index.html":
                return self._send_text(dashboard_html(), "text/html; charset=utf-8")
            if path == "/metrics":
                return self._send_text(self._prometheus(), "text/plain; version=0.0.4; charset=utf-8")
            if path == "/jobs":
                sched = self.cfg.scheduler
                if sched is None:
                    return self._send_json({"error": "scheduler desactivado"}, status=404)
                return self._send_json({"jobs": sched.list(), "history": sched.history[-50:]})
            if path == "/health":
                return self._send_json({"status": "ok", "version": __version__, "schema_version": SCHEMA_VERSION, "time": time.time()})
            if path == "/runs":
                limit = int(qs.get("limit", ["100"])[0])
                runs = self.cfg.store.list(limit=limit)
                return self._send_json({"count": len(runs), "runs": [{k: r.get(k) for k in ("run_id", "objetivo", "duracion")} for r in runs]})
            m = re.fullmatch(r"/runs/([A-Za-z0-9_-]+)", path)
            if m:
                run = self.cfg.store.get(m.group(1))
                if run is None:
                    return self._send_json({"error": "run no encontrada"}, status=404)
                return self._send_json(run)
            m = re.fullmatch(r"/runs/([A-Za-z0-9_-]+)/report\.(xml|html|md|json)", path)
            if m:
                run = self.cfg.store.get(m.group(1))
                if run is None:
                    return self._send_json({"error": "run no encontrada"}, status=404)
                fmt = m.group(2)
                if fmt == "xml":
                    from .report import junit_xml

                    return self._send_text(junit_xml(run), "application/xml; charset=utf-8")
                if fmt == "html":
                    from .report import html_report

                    return self._send_text(html_report(run), "text/html; charset=utf-8")
                if fmt == "md":
                    from .report import markdown_report

                    return self._send_text(markdown_report(run), "text/markdown; charset=utf-8")
                return self._send_json(run)
            if path == "/schemas":
                return self._send_text(schema_json(None), "application/json; charset=utf-8")
            m = re.fullmatch(r"/schemas/([a-z_]+)", path)
            if m:
                if m.group(1) not in SCHEMAS:
                    return self._send_json({"error": "esquema desconocido", "disponibles": sorted(SCHEMAS)}, status=404)
                return self._send_text(schema_json(m.group(1)), "application/json; charset=utf-8")
            if path == "/tools":
                return self._send_json({"tools": self.cfg.tools.catalog()})
            if path == "/events":
                return self._handle_events(qs)
            return self._send_json({"error": "ruta desconocida", "path": path}, status=404)
        except ValueError as e:
            return self._send_json({"error": str(e)}, status=400)
        except Exception as e:  # noqa: BLE001
            return self._send_json({"error": f"{type(e).__name__}: {e}"}, status=500)

    def _prometheus(self) -> str:
        """Métricas agregadas del store + métricas de la corrida más reciente."""
        try:
            total = self.cfg.store.count()
        except Exception:
            total = -1
        metricas: dict = {"corridas_total": total}
        try:
            ultimos = self.cfg.store.list(limit=1)
            if ultimos:
                m = ultimos[0].get("metrics", {})
                for k, v in m.items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        metricas[f"ultima_{k}"] = v
        except Exception:
            pass
        return prometheus_text(metricas, labels={"servicio": "harness-candy"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            u = urlparse(self.path)
            path = u.path.rstrip("/") or "/"
            rech = self._guard(path)
            if rech is not None:
                return self._send_json(rech[1], status=rech[0])
            body = self._read_body()
            if path == "/jobs":
                sched = self.cfg.scheduler
                if sched is None:
                    return self._send_json({"error": "scheduler desactivado"}, status=404)
                try:
                    job = sched.add(
                        name=body.get("name") or body.get("suite_path", "job"),
                        suite_path=body["suite_path"],
                        interval_s=float(body.get("interval_s", 300)),
                        jitter_s=float(body.get("jitter_s", 0.0)),
                    )
                except (KeyError, ValueError) as e:
                    return self._send_json({"error": str(e)}, status=400)
                return self._send_json(job.to_dict(), status=201)
            if path == "/runs":
                objetivo = body.get("objetivo")
                if not objetivo:
                    return self._send_json({"error": "falta 'objetivo'"}, status=400)
                self.cfg.bus.emit("run_start", {"objetivo": objetivo})
                run = self.cfg.runner.run(
                    objetivo,
                    inputs=body.get("inputs") or {},
                    seed=int(body.get("seed", 0)),
                )
                data = run.to_dict()
                self.cfg.store.save(data)
                self.cfg.bus.emit("run_end", {"run_id": data["run_id"], "duracion": data["duracion"]})
                return self._send_json(data, status=201)
            if path == "/suite":
                suite = Suite.from_dict(body)
                pool = make_pool()
                backend = make_backend(self.cfg.backend_kind)
                agent = SecurityScanAgent("XEV", "modelo-ligero", backend)
                store = HarnessStore()
                budget = Budget(**(suite.budget or {"total": 10_000, "beta": 0.5, "k": 2, "m": 3}))
                wev = WEV(SecurityGate())
                result = run_suite(
                    suite, agent=agent, pool=pool, store=store, budget=budget, wev=wev,
                    trace_dir=self.cfg.trace_dir,
                    on_event=lambda ev, d: self.cfg.bus.emit(ev, d),
                )
                data = result.to_dict()
                self.cfg.store.save(data)
                return self._send_json(data, status=201)
            if path == "/golden":
                gpath = body.get("path", "")
                p = (self.cfg.base_dir / gpath).resolve()
                if not str(p).startswith(str(self.cfg.base_dir)) or not p.exists() or p.suffix != ".json":
                    return self._send_json({"error": "path fuera del directorio base o inexistente"}, status=400)
                pool = make_pool()
                backend = make_backend(self.cfg.backend_kind)
                agent = SecurityScanAgent("XEV", "modelo-ligero", backend)
                report = run_golden(
                    p, agent=agent, pool=pool, store=HarnessStore(), wev=WEV(SecurityGate()),
                    trace_dir=self.cfg.trace_dir, seed=int(body.get("seed", 0)),
                )
                return self._send_json(report.to_dict(), status=200 if report.pass_rate >= report.min_pass_rate else 422)
            return self._send_json({"error": "ruta desconocida", "path": path}, status=404)
        except ValueError as e:
            return self._send_json({"error": str(e)}, status=400)
        except Exception as e:  # noqa: BLE001
            return self._send_json({"error": f"{type(e).__name__}: {e}"}, status=500)

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            path = urlparse(self.path).path.rstrip("/")
            rech = self._guard(path)
            if rech is not None:
                return self._send_json(rech[1], status=rech[0])
            m = re.fullmatch(r"/runs/([A-Za-z0-9_-]+)", path)
            if m:
                ok = self.cfg.store.delete(m.group(1))
                return self._send_json({"deleted": ok}, status=200 if ok else 404)
            m = re.fullmatch(r"/jobs/(job-[A-Za-z0-9]+)", path)
            if m and self.cfg.scheduler is not None:
                ok = self.cfg.scheduler.remove(m.group(1))
                return self._send_json({"deleted": ok}, status=200 if ok else 404)
            return self._send_json({"error": "ruta desconocida"}, status=404)
        except Exception as e:  # noqa: BLE001
            return self._send_json({"error": str(e)}, status=500)

    def _handle_events(self, qs: dict) -> None:
        timeout = min(float(qs.get("timeout", ["30"])[0]), 300.0)
        q = self.cfg.broadcaster.connect()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        inicio = time.time()
        try:
            while time.time() - inicio < timeout:
                try:
                    frame = q.get(timeout=1.0)
                    self.wfile.write(frame.encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    break  # cola vacia: seguimos esperando hasta el timeout
        finally:
            self.cfg.broadcaster.disconnect(q)
            self.close_connection = True


class HarnessServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host: str, port: int, cfg: ServerConfig):
        super().__init__((host, port), HarnessHandler)
        self.cfg = cfg


def make_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    *,
    store: RunStore | str | None = None,
    trace_dir: str | Path = "traces",
    runs_dir: str | Path = "runs",
    backend_kind: str = "scripted",
    bus: EventBus | None = None,
    base_dir: str | Path = ".",
    auth: TokenAuth | None = None,
    rate_limit: int = 120,
    rate_window_s: float = 60.0,
    enable_scheduler: bool = True,
) -> HarnessServer:
    """Crea el servidor (todavia no atiende): usar ``serve_forever()`` o en un thread."""
    if isinstance(store, (str, Path)):
        store = open_store(store)
    cfg = ServerConfig(
        store=store, trace_dir=trace_dir, runs_dir=runs_dir, backend_kind=backend_kind,
        bus=bus, base_dir=base_dir, auth=auth, rate_limit=rate_limit,
        rate_window_s=rate_window_s, enable_scheduler=enable_scheduler,
    )
    return HarnessServer(host, port, cfg)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="harness-candy serve", description="Servidor HTTP local de Harness-Candy")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--store", default="json://runs", help="json://dir | sqlite://path.db")
    p.add_argument("--trace-dir", default="traces")
    p.add_argument("--backend", default="scripted", choices=["scripted", "xkiro"])
    args = p.parse_args(argv)
    server = make_server(args.host, args.port, store=args.store, trace_dir=args.trace_dir, backend_kind=args.backend)
    print(f"Harness-Candy v{__version__} escuchando en http://{args.host}:{args.port} (Ctrl+C para salir)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
