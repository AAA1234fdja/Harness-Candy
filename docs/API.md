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
| `auth` | `TokenAuth` (bearer, comparación en tiempo constante, lee `HARNESS_API_TOKEN`), `IpRateLimiter` | §10.2/§5.8 auth + rate limit del servidor |
| `tenancy` | `TenantManager(base).store(tenant)`, `.trace_dir(tenant)`, `validate_tenant` | §1.2 multi-tenant base (aislamiento por namespace, anti-traversal) |
| `agents_catalog` | `AgentCatalog.load(path)`, `.build_agents(backend)`, esquema `agents_catalog` (con campo `class`) | §5.2 agentes declarativos desde archivo |
| `guards` | `GuardPipeline`, `NoSecretsGuard`, `MaxLengthGuard`, `JsonSchemaGuard`, `RequiredKeysGuard`, `ForbiddenPatternsGuard`, `default_pipeline()` | §5.8 guardrails de salida componibles |
| `scheduler` | `Scheduler(run_fn, base_dir)`, `job = sched.add(name, suite_path, interval_s)`, `tick()/tick_blocking()` | §4.3 scheduling justo de suites |
| `datasets` | `load_dataset(path.jsonl)`, `run_dataset(...)`, `compare_reports(a, b)` → `Comparison` | §5.9/§21 evaluación en lote + A/B |
| `metrics_export` | `prometheus_text(metrics, labels)`, `otlp_spans(traces)`, `OtlpExporter(endpoint)` | §11.1 métricas a Prometheus/OTLP |
| `web` | `dashboard_html()` (panel en `/` con SSE en vivo) | §6.2/§21.4 visor |
| `review` | `ReviewAgent().review_diff(diff_text)` → `WevMessage` (checks: diff_en_alcance, sintaxis_ok, sin_secretos_en_diff) | §5.8 review automático de PRs |
| `latencia` | `bench_latencia(fn, n, warmup)` (p50/p90/p95/p99), `comparar_latencias(antes, despues)`, `percentiles(vals)` | §8.1 latencia medida |
| `cli` | `main(argv)`; entry point `harness-candy` | §4.2 CLI |
| `server` | `make_server(host, port, store=...)`, `HarnessServer` | §6.2 API REST local |

## Cuarta ola: utilidades de sistema (stdlib-only)

| Módulo | API clave | Para qué sirve |
|---|---|---|
| `templates` | `compile_template(src)`, `render_string(src, **ctx)`, `render_file(path)`, herencia `{% extends/block %}`, `{% include %}` | plantillas propias (filtros upper/lower/trim/length/tojson/join/default/int/float, for/if/set, comentarios) |
| `config` | `Config.load(path?, environ?, **kw)`, `ConfigWatcher` (hot-reload), `interpolar` (`${VAR}`), `diff_configs`, esquema `config` | configuración con precedencia archivo < env `HARNESS_*` < kwargs; secretos enmascarados (`to_safe_dict`) |
| `summarize` | `summarize(texto, k)` → `Summary`, `resumen_por_parrafos`, `keywords`, `tfidf_lite`, `similitud_jaccard`, `detectar_duplicados`, `summarize_longitud` | resumen extractivo TextRank-lite (sin LLM) |
| `watch` | `snapshot(dir, globs)`, `diff_snapshots`, `WatchRunner(dir, on_change).poll_once()/start()/stop()`, `DebouncedWatchRunner`, `resumen_cambios`, `diff_contenido` | vigilar archivos por sha256+mtime |
| `llm` | `PromptTemplate`, `build_few_shot`, `ChatSession` (multi-turn, persistencia JSON, `fit_context`, `ConversationLogger`, `resumen_historial`), `structured_output` (valida contra esquema + reintentos fail-closed), `estimate_tokens`, `estimate_cost`, `truncar_contexto`, `PromptBuilder`, `batch_complete` | capa LLM avanzada sobre cualquier backend |
| `rag` | `RAGPipeline` (`add_text/add_file/add_dir`, `query` con citas zev, `save/load`), `chunk_text`, `BM25Index`, `HashingEmbedder`+`VectorIndex`, `HybridRetriever` (RRF + rerank por cobertura + expansión de query), `evaluate_retrieval` (recall@k, MRR) | RAG propio sin dependencias externas |
| `planner` | `Planner(ops).plan(goal, estado)`, `Operator(preconditions, effects, subtasks)`, `verificar_plan`, `niveles` (paralelismo), `estimate_cost`, `plan_simple()` | HTN-lite con precondiciones/efectos |
| `codeedit` | `add_import`, `add_function`, `rename_function`, `set_function_body`, `add_class`, `add_decorator`, `remove_function`, `list_functions`, `apply_unified_diff` (valida contexto, fail-closed), `validate_code` (ast+py_compile en sandbox), `FileSpec`+`generate_file_from_spec`, `generate_tests_for` | edición estructurada de código vía AST |
| `diffengine` | `ast_diff(a, b)` → `CodeDiff`, `ast_diff_detallado` (complejidad ciclomática delta), `complejidad_ciclomatica`, `diff_arboles(dir_a, dir_b)` | diff semántico (qué cambió, no el texto) |
| `textdiff` | `diff_lineas`, `unified_diff` (compatible con `codeedit.apply_unified_diff`), `similarity`, `diff_stats`, `resaltar_cambios`, `resumen_diff` | diff línea a línea propio |
| `workflow` | `Workflow.from_dict/load`, `run_workflow(...)` → `WorkflowResult`; steps `task`/`set`/`parallel`/`foreach` con `when` (eval restringida), `retry`, `depends_on` (orden topológico) | pipelines declarativos JSON |
| `orchestrator` | `Campaign.load(path)`, `run_campaign(...)` → `CampaignResult` (q medio, tasa aprobados, costo total, early-stop), `run_campaign_ab` (A/B con Mann-Whitney) | campañas multi-objetivo con presupuesto global (FinOps) |
| `codegen` | `scaffold_project(dir, name)` (pyproject/CI/tests/LICENSE/agents.json), `scaffold_agent(dir, name, model)` | esqueletos de proyecto nuevos |
| `evalsuite` | `run_eval_suite(golden, seeds=(0,1,2))` → `EvalSuiteResult` (matriz de confusión, bootstrap IC95), `significancia_vs`, `pass_at_k`, `curva_pass_k`, `html_eval_report`, `markdown_eval_report`, `exportar_csv` | evaluación agregada multi-semilla con estadística |
| `stats` | `describe`, `mean/median/percentil/stdev/variance/iqr`, `pearson/spearman/kendall_tau`, `ic_media`, `ic_proporcion_wilson`, `chi2_contingencia`, `anova_oneway`, `bootstrap_ci`, `normal_cdf/chi2_sf/t_sf` | estadística propia (p-valores incluidos, sin scipy) |
| `graph` | `DiGraph` (`topo_sort`, `niveles`, `critical_path`, `max_paralelismo`, `alcanzables`), `dependencias_a_grafo`, persistencia JSON | análisis de DAGs |
| `crypto` | `sha256_hex`, `hmac_sha256`, `sign_run/verify_run`, `gen_token`, `constant_time_eq`, `derive_key` (PBKDF2), `mask_secret`, `redact_text`, `buscar_secretos` | integridad y manejo seguro de secretos (claves solo en env) |
| `i18n` | `t(lang, clave, **ctx)` (es/en), `detectar_idioma`, `agregar_mensajes` | mensajes del sistema en ES/EN |
| `viz` | `sparkline`, `bar_chart`, `histogram`, `line_chart`, `heatmap`, `progress_bar`, `table_html`, `resumen_serie`, `tarjeta_html` | gráficos ASCII/HTML para reportes |
| `notify` | `Notifier([sinks])`, `CallbackSink`, `JsonlSink`, `WebhookSink`, `notificar_evento_watch` | notificaciones de eventos (un sink caído no tumba a los demás) |


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
harness-candy config [--file c.json|.env] [--full]        # config efectiva (secretos enmascarados)
harness-candy summarize --file texto.md -k 3 | --text "..."
harness-candy rag index --dir docs --out rag_index.json
harness-candy rag query --index rag_index.json --query "..." -k 4
harness-candy plan [--objetivo informe_de_seguridad]
harness-candy review --file diff.patch                      # exit 2 si el review rechaza
harness-candy workflow --file examples/workflows/demo.json
harness-candy campaign --file examples/campaigns/demo.json
harness-candy codegen DIR --name mi-proyecto
harness-candy evalsuite --file golden.json --seeds 0,1,2 --html eval.html
harness-candy watch DIR [--once]
```

Códigos de salida de `run`/`suite`/`task`: 0 = todo aprobado, 2 = alguna tarea
no aprobada (sirve para CI). `golden`: 0 si pasa el gate, 2 si no.

## HTTP (servidor local)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | dashboard web (HTML+JS, consulta la API con URLs relativas) |
| GET | `/health` | estado + versiones (siempre abierto) |
| GET | `/metrics` | métricas en formato texto Prometheus |
| GET | `/jobs` | jobs programados (scheduler) + historial |
| POST | `/jobs` | `{"name", "suite_path", "interval_s", "jitter_s?"}` → 201 |
| DELETE | `/jobs/{job_id}` | elimina un job |
| GET | `/runs?limit=N` | corridas guardadas |
| GET | `/compare?a=<run_id>&b=<run_id>` | delta de Q medio, duración y métricas entre dos corridas |
| POST | `/runs` | `{"objetivo", "inputs", "seed"}` → ejecuta y guarda (201) |
| GET | `/runs/{id}` | detalle |
| DELETE | `/runs/{id}` | borra |
| GET | `/runs/{id}/report.{xml,html,md,json}` | reporte |
| POST | `/suite` | body = suite JSON → ejecuta |
| POST | `/golden` | `{"path": "...json"}` dentro del base_dir → 200 si gate OK, 422 si no |
| GET | `/schemas[/nombre]` | esquemas publicados |
| GET | `/tools` | catálogo de herramientas |
| GET | `/events?timeout=S` | stream SSE del bus de eventos |
| GET | `/config` | configuración efectiva (secretos enmascarados) |
| GET | `/plan?objetivo=...` | plan HTN-lite de ejemplo |
| POST | `/review` | `{"diff": "..."}` → veredicto WEV (200 aprobado / 422 rechazado) |
| POST | `/workflow` | body = workflow JSON → ejecuta (201) |
| POST | `/rag/index` | `{"dir": "docs", "out": "rag_index.json", "chunk"?, "overlap"?}` → 201 |
| GET/POST | `/rag/query` | `{"q": "...", "k": 4}` o `?q=...&k=4` → fragmentos con procedencia |
| POST | `/summarize` | `{"texto": "...", "k": 3}` → resumen extractivo |

Seguridad del servidor: cuerpo ≤ 1 MB, sin logueo de cuerpos, acepta cualquier
Host (necesario para preview local); las ejecuciones pasan por XEV/WEV (allowlist
+ sandbox). Para exponerlo fuera de localhost, ponlo detrás de TLS.

## Esquemas publicados (`harness-candy schemas`)

`envelope`, `yev`, `zev`, `xev`, `wev`, `hallazgo`, `criterion`, `task`,
`harness`, `budget`, `pool_entry`, `trace_event`, `run_result`, `suite`,
`golden_set`, `tool_spec`.
