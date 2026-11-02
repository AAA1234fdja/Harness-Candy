# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) + SemVer.

## [Unreleased]

### Añadido (séptima ola: memoria administrada en 3 capas — carpeta `memoria/`; suite 747 → 764 tests OK)
- `memoria.py`: `GestorMemoria` sobre `memoria/` con tres capas — **cache** (datos momentáneos con TTL, `purgar_cache()`, fuera de git vía .gitignore), **chat** (buscable por proyecto en `chat/<proyecto>/`, admisión solo si `relevancia >= 0.5`, con `--forzar`), **ecosistema** (global entre proyectos, `proyecto` como etiqueta de origen). Regla común fail-closed: cada entrada es `tipo + idea + explicacion` de **máx. 300 palabras** (`EntradaLargaError` si se pasa). Búsqueda BM25 léxica (reusa `rag.BM25Index`) por capa; `listar/leer/borrar/stats` con palabras medias y expiradas pendientes.
- `memoria/README.md`: contrato de las 3 capas y ejemplos de uso.
- `scripts/memoria` (ejecutable): `guardar-cache | guardar-chat | guardar-eco | buscar | listar | purgar | stats | leer`; exit 2 cuando una entrada se rechaza (>300 palabras o relevancia insuficiente).
- `examples/demo_memoria.py`: demo end-to-end en directorio temporal.
- Tests: 17 nuevos (764 en total) — `test_memoria` (validación 300 palabras, TTL/purga, admisión por relevancia, scoping por proyecto, búsqueda BM25, persistencia JSON, CLI vía subprocess).
- Docs actualizadas: `API.md` (sección séptima ola), README, `CHECKLIST_V3_ESTADO.md`, TUTORIAL.

### Añadido (sexta ola: cierra brechas del documento exhaustivo — eval multi-benchmark, safety continua, juez calibrado, QA mutation/fuzz/PBT, evidence packs, multi-backend; suite 669 → 747 tests OK)
- `benchmarks.py`: evaluador multi-benchmark local — casos `mcq`/`codigo` (sandbox)/`abierto`, few-shot, semillas, `pass@k`, gate por suite, por dominio/seed; `comparar_modelos` con delta + Mann-Whitney; export `BenchmarkCard`/`EvaluationCard`/`export_olmes`; suites de ejemplo en `benchmarks/mini_mmlu.json` y `benchmarks/swe_mini.json`.
- `safety.py`: safety harness continuo stdlib (léxicos ES/EN): `detectar_jailbreak`, `toxicidad`, `detectar_refusal`, `evaluar_respuesta` (veredicto con jailbreak exitoso separado); métricas JSR / refusal_rate / toxicity_rate / precision-recall del guard vs anotaciones; `SafetySuite` con corpus red-team embebido, incidentes con severidad y time-to-detect, gate propio; `redteam_por_plantilla` ordena qué plantillas rompen más.
- `judge_calib.py`: juez calibrado — modos `single` (0..5), `pairwise` (con medición de sesgo de posición vía swap_test) y `reference_guided`; `calibrar_juez` reporta MAE, sesgo medio, correlación Pearson y MAE por dominio; `consenso` multi-juez (media + entropía normalizada como acuerdo); `TorneoElo` para leaderboard entre modelos.
- `qatest.py`: mutation testing sobre AST (AOR/ROR/inversión de condición/return None/quitar llamada/constante) con `mutation_score`; `run_mutation_diff` muta SOLO las funciones cambiadas por el diff (propuesta del cap. 03 para CI); `fuzz_funcion` (PBT con seed reproducible, crashes → corpus de regresión persistido); `metricas_mantenibilidad`/`metricas_proyecto` (LOC, complejidad ciclomática, duplicación, deuda técnica estimada).
- `evidence.py`: evidence packs firmados HMAC (`HARNESS_SIGNING_KEY` solo en env) con hash de contenido verificable, `pack_desde_store` (incluye RunMark real) y `exportar_pack_zip`; `export_otlp_end_to_end` (spans OTLP → collector con transport inyectable, verifica 200); `evaluar_alertas` con reglas de tendencia/caída (toxicity trend, JSR, judge agreement drop, caída de q); `rollback_si_regresion` + `marcar_rollback_en_store` (rollback automático trazable al harness anterior).
- `backends_multi.py`: `AnthropicBackend` (clave solo `ANTHROPIC_API_KEY`), `OllamaBackend` (local-first, sin clave), `SelectorModelos` por política costo/latencia/calidad con métricas desde `bench_latencia`, `FailoverPorModelo` con reintentos, `backends_disponibles`/`failover_desde_env` (detecta proveedores reales por env) y `TokenBudget` (tope de tokens por dominio con alertas al 80%/100%, green AI).
- Tests: 78 nuevos (747 en total) — `test_benchmarks_ola6`, `test_safety_ola6`, `test_judge_calib_ola6`, `test_qatest_ola6`, `test_evidence_ola6`, `test_backends_multi_ola6`.
- Docs actualizadas: `API.md` (sección sexta ola), README, `CHECKLIST_V3_ESTADO.md`, TUTORIAL.

### Añadido (quinta ola: Harness^2 avanzado, Vertex/Gemini ADC, runners de terceros y scripts harness2-*; suite 579 → 669 tests OK)
- `proposer.py`: `LLMProposer` — refinamiento de prompts del harness con LLM vía `structured_output` (esquema `CANDIDATO_SCHEMA`), conserva lo que funcionó y cae fail-closed a `RuleBasedProposer`; `proposer_desde_config`.
- `schedule.py`: partición LPT (`particionar`, `shard_de`), sweep de hyperparámetros (`grid_sweep`, `sweep_con_early_stop` con ventana de no-mejora) y `ScheduleRunner` con checkpoint JSON y resume (no re-ejecuta lo terminado).
- `recursion.py`: `run_recursion` con modos `parallel` (ThreadPoolExecutor, semillas por sub-objetivo, sin estado compartido) y `sequential` (contexto acumulado); `reflection_post_adopcion` guarda la reflexión del LLM en `KnowledgeMemory` (fail-closed determinista si el LLM falla).
- `tree.py`: `HarnessTree` — árbol de candidatos con `add_candidate`, `best(k)`, `path_to`, `podar(umbral)`, `ascii()`, persistencia JSON (`save`/`load`).
- `selection.py`: `seleccionar_adoptado` — elige el adoptado con Mann-Whitney one-sided + `compose_delta` + IC95 bootstrap; si nadie gana, vuelve a la referencia.
- `context.py`: `construir_contexto` → `ContextBundle` (tarea + fragmentos RAG ordenados por score y recortados por presupuesto de tokens + historial) con `to_prompt`/`to_dict`.
- `runmark.py`: `RunMark`/`crear_runmark` — commit git, sha256 de archivos clave, fingerprint de env SOLO con nombres (`fingerprint_env`), `verificar_reproducibilidad` entre dos marcas; nunca guarda valores de secretos.
- `vertex.py`: `VertexBackend` (implementa `LLMBackend`) contra la API generativa de Vertex AI (Gemini) vía REST `:generateContent`, con token ADC (`obtener_token_adc`: metadata GCE → `gcloud auth application-default print-access-token` → archivo ADC con refresh-token flow). El token solo vive en memoria/header `Authorization`; `from_env` usa `GOOGLE_CLOUD_PROJECT`/`VERTEX_LOCATION`/`VERTEX_MODEL`. Transport inyectable para tests sin red.
- `third_party/jb_runner/`: cola de jobs con prioridad (heap, FIFO en empates), `JobStore` JSON atómico con estados e intentos, `JobRunner` con reintentos y resume.
- `third_party/lab_runner/`: `Experimento` con grid de params (`itertools.product`), ejecución paralela local (ThreadPoolExecutor), mejor resultado + media/IC95 bootstrap propios, reporte Markdown/JSON.
- `third_party/wb_runner/`: `DockerRunner` (CLI docker con `dry_run` y `ejecutar` inyectable), `HarborClient` (credenciales SOLO de `HARBOR_USERNAME`/`HARBOR_PASSWORD`, login con `--password-stdin`, API REST v2 con transport inyectable) y `WorkBuddy` (pipeline build → login → tag → push → run → artefactos).
- `scripts/harness2-setup|check|judge|report` (ejecutables): setup de entorno (sin imprimir valores de env), check (compileall + escaneo de secretos + tests rápidos, `--full` para la suite completa), judge (golden con gate `min-pass-rate`, exit 2 si falla, guarda el reporte en el store) y report (HTML/MD desde archivo JSON o `run_id` del store).
- Tests: 90 nuevos (669 en total) — `test_proposer_ola5`, `test_schedule_ola5`, `test_recursion_ola5`, `test_tree_selection_ola5`, `test_context_runmark_ola5`, `test_vertex_ola5`, `test_third_party`, `test_scripts`.
- Docs actualizadas: `API.md` (sección quinta ola), README, `CHECKLIST_V3_ESTADO.md`, TUTORIAL.

### Añadido (cuarta ola: +~4.600 líneas en `src/`, 25 módulos nuevos, stdlib-only; suite 338 → 579 tests OK)
- `templates.py`: motor de plantillas mini-Jinja compilado a Python (filtros, for/if/set, comentarios, herencia extends/block, include con anti-ciclo y anti-traversal).
- `config.py`: esquema `config` publicado; precedencia archivo < env `HARNESS_*` < kwargs; interpolación `${VAR}`; `ConfigWatcher` (hot-reload por mtime); `to_safe_dict` enmascara secretos; `diff_configs`.
- `summarize.py`: resumen extractivo TextRank-lite (stopwords ES), `keywords`, `tfidf_lite`, `similitud_jaccard`/`detectar_duplicados` (shingles), `summarize_longitud`.
- `watch.py`: snapshots por sha256+mtime con globs/exclusiones, `diff_snapshots`, `WatchRunner` (poll/start/stop en hilo), `DebouncedWatchRunner`, `resumen_cambios`, `diff_contenido`.
- `llm.py`: `PromptTemplate`, few-shot, `ChatSession` multi-turn con persistencia JSON y recorte por `max_messages`/`fit_context`, `structured_output` validado contra esquema con reintentos fail-closed, `estimate_tokens`/`estimate_cost`, `truncar_contexto`, `PromptBuilder`, `batch_complete`, `ConversationLogger`, `resumen_historial`.
- `rag.py`: RAG propio sin dependencias: `chunk_text` con solapamiento, `BM25Index`, `HashingEmbedder`+`VectorIndex` (coseno), `HybridRetriever` (RRF + rerank por cobertura de términos + expansión de query), `RAGPipeline` con citas (contenido+procedencia, formato zev) y persistencia, `evaluate_retrieval` (recall@k, MRR).
- `planner.py`: HTN-lite — `Operator(preconditions, effects, subtasks)`, `Planner.plan` (busqueda con estado mutable), `verificar_plan`, `niveles` (ejecución paralela por niveles), `estimate_cost`, `plan_simple`.
- `codeedit.py`: edición estructurada vía AST — imports, funciones, renombrado (incluye llamadas), cuerpos, clases, decoradores, `apply_unified_diff` (valida contexto y offsets, rechaza si no cuadra), `validate_code` (ast + py_compile en sandbox), `generate_file_from_spec`, `generate_tests_for`.
- `diffengine.py`: `ast_diff` (funciones/clases/imports añadidos, eliminados, cambiados), `ast_diff_detallado` con complexité ciclomática delta, `diff_arboles` (diff de dos directorios).
- `textdiff.py`: diff línea a línea propio sobre difflib; `unified_diff` compatible con `codeedit.apply_unified_diff`; `diff_stats`, `resaltar_cambios`, `resumen_diff`.
- `workflow.py`: workflows declarativos JSON — steps `task`/`set`/`parallel`/`foreach` con `when` (eval restringida, sin builtins), `retry`, `depends_on` (orden topológico, fail-closed ante ciclos).
- `orchestrator.py`: `Campaign` con presupuesto global (tope duro FinOps), `run_campaign` (métricas agregadas, early-stop por calidad), `run_campaign_ab` (A/B con Mann-Whitney).
- `codegen.py`: `scaffold_project` (pyproject, paquete src, test smoke que pasa, CI GitHub, LICENSE MIT, agents.json) y `scaffold_agent`.
- `evalsuite.py`: golden × N semillas con matriz de confusión de veredictos, intervalo bootstrap del pass_rate, `significancia_vs` (p one-sided), `pass_at_k`/`curva_pass_k`, reportes HTML/Markdown y exportación CSV.
- `stats.py`: estadística propia sin scipy — descriptiva, pearson/spearman/kendall, IC de media (t) y de proporción (Wilson), chi2 de contingencia (con Yates), ANOVA unifactorial, bootstrap genérico; p-valores via gamma/beta incompletas (series + fracciones continuas).
- `graph.py`: `DiGraph` propio — orden topológico (Kahn FIFO), niveles, ruta crítica, paralelismo máximo, alcanzables, persistencia JSON.
- `crypto.py`: sha256/HMAC-SHA256, firma/verificación de corridas (`sign_run`/`verify_run`, clave solo desde `HARNESS_SIGNING_KEY`), `gen_token` (secrets), comparación en tiempo constante, `derive_key` (PBKDF2-HMAC-SHA256), `mask_secret`, `redact_text`, `buscar_secretos`.
- `i18n.py`: catálogo ES/EN con `t(lang, clave, **ctx)`, detección de idioma por stopwords, ampliación en runtime.
- `viz.py`: sparklines, barras, histogramas, line chart y heatmap ASCII, barras de progreso, tablas HTML.
- `notify.py`: `Notifier` multi-sink (`CallbackSink`, `JsonlSink`, `WebhookSink`) tolerante a fallos; `notificar_evento_watch`.
- CLI nuevos: `config`, `summarize`, `rag index|query`, `plan`, `review`, `workflow`, `campaign`, `codegen`, `evalsuite`, `watch`.
- HTTP nuevos: `GET /config`, `GET /plan`, `POST /review`, `POST /workflow`, `POST /rag/index`, `GET|POST /rag/query`, `POST /summarize`.
- Ejemplos: `examples/workflows/demo.json`, `examples/campaigns/demo.json`.


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
