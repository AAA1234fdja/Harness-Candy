# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) + SemVer.

## [Unreleased]

### Añadido
- `backends.OpenAICompatibleBackend` (xkiro/LiteLLM/vLLM...): la API key solo se lee de `XKIRO_API_KEY` (variable de entorno), endpoint vía `XKIRO_BASE_URL`, modelo vía `XKIRO_MODEL`.
- `examples/demo_xkiro.py` para probar con un modelo real.
- `judge.py`: juez LLM independiente con rúbrica, `swap_test` (sesgo de posición) y `calibrate` (vs. anotaciones humanas); WEV lo integra opcional fail-closed.
- `metrics.py`: métricas de ejecución (requisitos, pruebas, defectos, tiempo, costo, tokens, trabajo duplicado, mantenibilidad). Nunca líneas de código.
- `dag.py`: cancelación (`cancel_event`), plazos (`node.deadline`), operaciones irreversibles → `human_review`.
- `components.py`: `Plan.restricciones`; ISA detecta operaciones irreversibles; XEV con allowlist de herramientas/comandos; WEV con `linter_basico` (ast) y `diff_dentro_de_alcance`.
- `quality.mann_whitney_u` / `mann_whitney_adopt` (alternativa a la ec. 2 para Q binaria/discreta).
- `harness`: la evidencia del adaptador guarda **trayectorias**; Compose fusiona lo que funcionó (`merge_harnesses`).
- `security.SecurityGate.evaluate_false_positive_rate` (objetivo: rechazo de benignos < 5 %).
- `ablation.k_curve` (curva de mejora vs. k medida con datos propios).
- `examples/bench_escalabilidad.py` (bench de escalabilidad con métricas y tiempos).
- Docs: `docs/CHECKLIST_ESTADO.md`, `docs/CHECKLIST_V3_ESTADO.md`, `docs/INDEPENDENCIA.md`, `docs/arquitectura.mmd`, ADRs en `docs/adr/`, `docs/ROADMAP.md`.
- Repo base: `CONTRIBUTING.md`, `SECURITY.md`, `CODEOWNERS`, `.editorconfig`, `.gitattributes`, CI en `.github/workflows/ci.yml`.

### Añadido (expansión del proyecto)
- `schemas.py`: 16 esquemas JSON Schema publicados (`SCHEMAS`, `SCHEMA_VERSION="1.0.0"`) de todo el contrato (protocolos, task, harness, budget, pool_entry, trace_event, run_result, suite, golden_set, tool_spec) + validador propio stdlib (`validate_schema`, `validate_named`, `schema_json`).
- `tools.py`: registro de herramientas tipadas (`ToolSpec`/`ToolRegistry`) con validación de argumentos contra su JSON Schema, allowlist de permisos (read/write/exec), rate limit (token bucket), timeout, ejecución en sandbox para comandos, auditoría de llamadas y errores tipados. Herramientas incluidas: `echo`, `list_files`, `read_file`, `py_compile`, `git_version` (root acotado).
- `cli.py` + `__main__.py` + entry point `harness-candy`: subcomandos `version, schemas, validate, run, task, suite (run|list), golden, report, bench, cache, tools, serve`.
- `server.py`: servidor HTTP local (stdlib) con API REST (`/health`, `/runs` GET/POST/DELETE, `/runs/{id}`, `/runs/{id}/report.{xml,html,md,json}`, `/suite`, `/golden` con gate 200/422, `/schemas`, `/tools`) y stream SSE `/events`. Cuerpo ≤ 1 MB, sin logueo de cuerpos, acepta cualquier Host (preview local).
- `suite.py`: suites JSON de tareas (esquema `suite`) ejecutadas como DAG con Harness²+WEV por nodo (`run_suite` → `SuiteResult`); `examples/suites/demo.json` + `examples/demo_suite.py`.
- `evalkit.py`: golden sets (`load_golden`, `run_golden` → `EvalReport` con `pass_rate`, `assert_gate()` para CI); `examples/golden/security_scan.json` + `examples/demo_golden.py`.
- `report.py`: reportes JUnit XML, HTML autocontenido y Markdown de cualquier corrida (`write_report` por extensión).
- `storage.py`: `RunStore` con `JsonRunStore` y `SqliteRunStore` (sqlite3 stdlib) + `open_store("json://dir" | "sqlite://x.db")`.
- `cache.py`: caché en disco de respuestas LLM (`ResponseCache` con TTL y evicción LRU; clave SHA-256 de {model, system, prompt, seed}, nunca la API key) y `CachedBackend`.
- `failover.py`: `FailoverBackend` (lista ordenada de backends, reintento ante `BackendError`, timeout total, registro de intentos en `attempts`) — mitiga R11 en código.
- `retry.py`: `retry_call`/`retryable` con backoff exponencial + jitter **determinista por seed** (`backoff_delays`), `RetryExhausted`.
- `plugins.py`: `PluginRegistry` con hooks (`on_run_start/node_start/node_end/run_end/alert/tool_call`), carga por módulo (`load_module`), tolerancia a fallos (un plugin roto se deshabilita y queda en `errors`), `LoggingPlugin`, `CompositePlugin`.
- `streaming.py`: `EventBus` pub/sub con historial acotado y tolerancia a fallos, `sse()` (Server-Sent Events), `SseBroadcaster`, `EventCollector` para tests.
- `alerts.py`: `BudgetMonitor` con umbrales 50/80/100% (una vez cada uno) sobre `Budget`, sumideros `LogSink`/`WebhookSink` (POST JSON, nunca envía claves)/`MultiSink`, y emisión de alertas al bus de eventos.
- `factory.py`: constructores por defecto compartidos por CLI, servidor y ejemplos (`build_runner`, `make_pool`, `make_backend`).
- Ejemplos nuevos: `demo_suite.py`, `demo_golden.py`, `demo_cli.py`, `demo_server.py`, `suites/demo.json`, `golden/security_scan.json`, `golden/limpio/` (repo demo sin secretos).
- Docs nuevas: `docs/API.md` (referencia de API/CLI/HTTP/esquemas), `docs/OPERACION.md` (10 runbooks); `docs/CHECKLIST_V3_ESTADO.md` actualizado con los ítems que pasan a ✅.
- Fix: `SecurityScanAgent` resuelve `inputs.root` a ruta absoluta (el sandbox usa cwd efímero).
- Tests: 160 nuevos (264 en total) — `test_schemas, test_tools, test_cache, test_failover, test_retry, test_plugins, test_streaming, test_alerts, test_report, test_storage, test_suite, test_evalkit, test_cli, test_server`.

### Añadido (segunda ola)
- `auth.py`: `TokenAuth` (bearer desde `HARNESS_API_TOKEN`, comparación en tiempo constante con `hmac.compare_digest`) e `IpRateLimiter` (ventana deslizante por IP). El servidor exige token en todas las rutas salvo `/health` cuando el env está definido, y aplica rate limit (120/min por defecto).
- `tenancy.py`: `TenantManager` — stores y trace_dir aislados por tenant (`data/runs/<tenant>/`) con validación anti-traversal del nombre.
- `agents_catalog.py`: catálogo de agentes desde JSON (nuevo esquema publicado `agents_catalog`) con `build_agents(backend)`.
- `guards.py`: pipeline de guardrails de salida (`NoSecretsGuard`, `MaxLengthGuard`, `JsonSchemaGuard`, `RequiredKeysGuard`, `ForbiddenPatternsGuard`); un guard roto no tumba la corrida.
- `scheduler.py`: jobs de suites por intervalo con anti-solapamiento e historial; endpoints `POST/GET/DELETE /jobs`.
- `datasets.py`: datasets JSONL de evaluación (`load_dataset`, `run_dataset`) y comparación A/B (`compare_reports`, delta en puntos porcentuales + casos que cambian).
- `metrics_export.py`: `prometheus_text` (endpoint `/metrics`), `otlp_spans` (OTLP/JSON) y `OtlpExporter` (POST al collector, mejor esfuerzo).
- `web.py`: dashboard en `/` (HTML+JS vanilla, URLs relativas, SSE en vivo de `/events`, tabla de corridas con enlaces a reportes).
- Servidor: nuevas rutas `/`, `/metrics`, `/jobs`; guardas de auth + rate limit en todos los handlers.
- Tests: 58 nuevos (322 en total) — `test_auth, test_tenancy, test_agents_catalog, test_guards, test_scheduler, test_datasets, test_metrics_export, test_server_extra`.
- Docs actualizadas: `API.md`, `OPERACION.md` (runbooks 11–15), `CHECKLIST_V3_ESTADO.md`, README.

### Añadido (tercera ola)
- `review.py`: `ReviewAgent` — revisión automática de PRs sobre el diff (allowlist de rutas con `check_diff_paths`, sintaxis `ast` de los .py añadidos, bloqueo de secretos/PII en el diff) → `WevMessage` con checks medibles.
- `latencia.py`: `bench_latencia` con percentiles p50/p90/p95/p99 + `comparar_latencias` (delta % antes/después, p. ej. para justificar Rust).
- `agents_catalog.py`: campo `class` en el catálogo (`SecurityScanAgent` real); `examples/agents.json` + `examples/demo_agents.py`.
- Servidor: `GET /compare?a=<run>&b=<run>` (delta de Q medio, duración y métricas).
- `docs/TUTORIAL.md`: recorrido de 15 minutos (instalar → tests → CLI → servidor → Python → xkiro).
- Tests: 338 en total (16 nuevos: `test_review`, `test_latencia`, `/compare` en `test_server_extra`).

## [0.1.0] - 2026-11-02

### Añadido
- Implementación inicial del diseño combinado Ely–Cowork ADK+Harness²:
  protocolos tipados `yev`/`zev`/`xev`/`wev`; capa de calidad (Q ec. 1, regla estadística ec. 2, TraceLog JSONL, RegressionGuard);
  adaptador Harness² (Propose→Probe→Compose) con `Budget` (ec. 3) y `HarnessStore`; DAG con ejecución paralela, reintentos y escalamiento;
  pool de modelos por rol; memoria de variables y de conocimiento; seguridad (inyección/PII) y sandbox efímero sin red;
  componentes ISA/YEV/ZEV/XEV/WEV/ELY; `runner.run_task` (Listado 1) y `CoworkRunner` (flujo de 8 pasos);
  `adk_bridge` (DAG → flujo ADK real si está instalado); ablación A/B/C/D; 83 tests; demos e2e y de ablación.
