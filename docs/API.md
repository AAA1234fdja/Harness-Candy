# Referencia de la API pública (v3 §14.1)

Superficie estable: lo que exporta `harness_candy/__init__.py` (`__all__`).
El contrato de datos está publicado como **JSON Schema** (módulo `schemas`,
`SCHEMAS`, versión `SCHEMA_VERSION = "1.0.0"`); para validar un JSON externo:
`validate_named("task", {...})` o `harness-candy validate --schema task --file x.json`.

## Núcleo (ya existente)

| Módulo | API clave |
|---|---|
| `protocols` | `validate(raw)` → mensaje tipado; `dump(msg)`; `ProtocolError` |
| `quality` | `Criterion`, `score_q` (ec. 1), `should_adopt`/`compose_delta` (ec. 2), `mann_whitney_adopt`, `TraceLog` (JSONL), `RegressionGuard`, `new_run_id` |
| `harness` | `Harness` (8 componentes, `fingerprint`, `evolve`), `HarnessStore`, `Budget` (ec. 3), `Harness2Adapter` (Propose→Probe→Compose), `RuleBasedProposer`, `merge_harnesses` |
| `memory` | `VariableMemory` (session.state), `KnowledgeMemory` |
| `pool` | `ModelPool`, `PoolEntry` (clave por **variable de entorno**, nunca en claro) |
| `security` | `SecurityGate`, `scan_injection`, `scan_pii` |
| `sandbox` | `run_sandboxed(cmd, timeout)` → `SandboxResult` (cwd efímero, red aislada con `unshare -rn` si el SO lo permite) |
| `dag` | `TaskDAG`, `TaskNode`, `DAGExecutor` (paralelo por capas, reintentos, cancel_event, deadline, human_review) |
| `agents` | `Agent`, `LLMBackend` (Protocol), `ScriptedBackend`, `Task`, `Artifact`, `SecurityScanAgent` |
| `components` | `ISA`, `YEV`, `ZEV`, `XEV`, `WEV`, `ELY`, `Plan` |
| `runner` | `run_task` (Listado 1), `CoworkRunner`, `RunResult` |
| `adk_bridge` | `build_flow_spec(dag)`, `build_adk_flow(...)` (extra `adk`) |
| `ablation` | `run_ablation` (A/B/C/D), `k_curve`, `AblationReport` |
| `backends` | `OpenAICompatibleBackend` (xkiro/LiteLLM/Ollama; clave solo en env `XKIRO_API_KEY`), `BackendError` |
| `judge` | `LLMJudge` (fail-closed), `calibrate`, `swap_test` |
| `metrics` | `MetricsCollector` (sin LOC, como indica el diseño §10) |

## Expansión (nueva)

| Módulo | API clave | Cierra (checklist v3) |
|---|---|---|
| `schemas` | `SCHEMAS`, `validate_named`, `validate_schema`, `schema_json`, `SchemaError`, `SCHEMA_VERSION` | §7.1–7.2 esquemas publicados |
| `tools` | `ToolSpec`, `ToolRegistry`, `default_registry(root)`, errores `ToolError`/`ToolValidationError`/`RateLimitError`/`ToolTimeoutError` | §5.3 defineTool tipada |
| `cache` | `ResponseCache(dir, ttl_s)`, `CachedBackend(backend)`, `cache_key` | §8.3/§13.3 caché de respuestas |
| `failover` | `FailoverBackend([b1, b2])`, `AllBackendsFailed` | §5.6/R11 failover multi-modelo |
| `retry` | `retry_call(fn, attempts, seed=...)`, `backoff_delays`, `retryable`, `RetryExhausted` | §4.3 backoff+jitter determinista |
| `plugins` | `PluginRegistry` (`register`, `load_module`, `run_hook`, hooks `on_run_start/on_node_start/on_node_end/on_run_end/on_alert/on_tool_call`), `LoggingPlugin`, `CompositePlugin` | §4.8/§17.1 plugins |
| `streaming` | `EventBus`, `EventCollector`, `SseBroadcaster`, `sse(event, data)` | §5.7/§6.2 observabilidad en vivo |
| `alerts` | `BudgetMonitor(budget, sink, thresholds=(.5,.8,1.0))`, `Alert`, `LogSink`, `WebhookSink`, `MultiSink`, `quality_alert` | §13.2/§11 alertas 50/80/100% |
| `report` | `junit_xml(run)`, `html_report(run)`, `markdown_report(run)`, `write_report(run, path)` | §4.5 reportes JUnit/HTML/MD |
| `storage` | `RunStore`, `JsonRunStore`, `SqliteRunStore`, `open_store("json://dir" \| "sqlite://x.db")` | §12 persistencia de corridas |
| `suite` | `Suite.from_dict`, `load_suite(path)`, `suite.to_dag()`, `run_suite(...)` → `SuiteResult` | §4.4 DSL de suites JSON |
| `evalkit` | `GoldenSet`, `load_golden(path)`, `run_golden(...)` → `EvalReport` (`assert_gate()` para CI) | §5.9/§19 golden sets |
| `factory` | `build_runner(trace_dir, backend_kind=...)`, `make_pool()`, `make_backend("scripted" \| "xkiro")` | cableado por defecto |
| `cli` | `main(argv)`; entry point `harness-candy` | §4.2 CLI |
| `server` | `make_server(host, port, store=...)`, `HarnessServer` | §6.2 API REST local |

## CLI

```
harness-candy version
harness-candy run --objetivo "..." --input root=src --seed 0 --out run.json --report run.html
harness-candy task --file tarea.json
harness-candy suite [run|list] --file suite.json [--report out.html]
harness-candy golden --file golden.json [--min-pass-rate 0.9]   # exit 2 si falla el gate
harness-candy report --run run.json --format html --out run.html
harness-candy validate --schema task --file x.json
harness-candy schemas [--name task] [--out esquema.json]
harness-candy bench [N]
harness-candy cache [--dir .harness_cache] [--clear | --stats]
harness-candy tools [--root .]
harness-candy serve --host 0.0.0.0 --port 8000 --store json://runs
```

Códigos de salida de `run`/`suite`/`task`: 0 = todo aprobado, 2 = alguna tarea
no aprobada (sirve para CI). `golden`: 0 si pasa el gate, 2 si no.

## HTTP (servidor local)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | estado + versiones |
| GET | `/runs?limit=N` | corridas guardadas |
| POST | `/runs` | `{"objetivo", "inputs", "seed"}` → ejecuta y guarda (201) |
| GET | `/runs/{id}` | detalle |
| DELETE | `/runs/{id}` | borra |
| GET | `/runs/{id}/report.{xml,html,md,json}` | reporte |
| POST | `/suite` | body = suite JSON → ejecuta |
| POST | `/golden` | `{"path": "...json"}` dentro del base_dir → 200 si gate OK, 422 si no |
| GET | `/schemas[/nombre]` | esquemas publicados |
| GET | `/tools` | catálogo de herramientas |
| GET | `/events?timeout=S` | stream SSE del bus de eventos |

Seguridad del servidor: cuerpo ≤ 1 MB, sin logueo de cuerpos, acepta cualquier
Host (necesario para preview local); las ejecuciones pasan por XEV/WEV (allowlist
+ sandbox). Para exponerlo fuera de localhost, ponlo detrás de TLS.

## Esquemas publicados (`harness-candy schemas`)

`envelope`, `yev`, `zev`, `xev`, `wev`, `hallazgo`, `criterion`, `task`,
`harness`, `budget`, `pool_entry`, `trace_event`, `run_result`, `suite`,
`golden_set`, `tool_spec`.
