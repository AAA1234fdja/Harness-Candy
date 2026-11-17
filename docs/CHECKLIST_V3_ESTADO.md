# Checklist extendido v3 — estado en Harness-Candy

Aplicación del "Checklist extendido (v3) para habilitar Harness2 y ADK" a este
repositorio. Leyenda de estado:

- ✅ cumplido en el repo (con evidencia ejecutable)
- ⚠️ parcial / pendiente técnico concreto (se indica cuál)
- 🏢 organizacional: no se cierra desde un repo (owner sugerido entre paréntesis)

Prioridades del original: 🔴 bloqueante go-live · 🟡 recomendado · 🟢 mejora post-GA.

Evidencia general: `python -m unittest discover -s tests` (**764 tests OK**) · CI en
`.github/workflows/ci.yml` · paper base: Xu et al., *Harness 2: Recursive Agent
Harnessing for an Open World*, arXiv:2610.14224 (`docs/adr/README.md`).

## Actualización tras la expansión del proyecto (2026-11-02)

La expansión añadió ~14 módulos stdlib-only + CLI + servidor HTTP + 160 tests
nuevos. Ítems que pasan de ⚠️ a ✅ en este repo:

| Ítem (sección) | Antes | Ahora | Evidencia |
|---|---|---|---|
| §4.2 CLI (run/list/report/version/bench/serve) | ⚠️ | ✅ | `harness-candy ...` (`cli.py`, entry point en pyproject); `python -m harness_candy` |
| §4.3 Backoff con jitter entre reintentos | ⚠️ | ✅ | `retry.py` (`backoff_delays` determinista por seed, `retry_call`, `RetryExhausted`) |
| §4.5 Reportes JUnit XML + HTML + Markdown | ⚠️ | ✅ | `report.py` (`junit_xml`, `html_report`, `markdown_report`, `write_report`); `report --run ... --format html`; `/runs/{id}/report.html` |
| §4.8 Registro de plugins con hooks | ⚠️ | ✅ | `plugins.py` (`PluginRegistry`, hooks on_run_start/node_start/node_end/run_end/alert/tool_call, carga por módulo) |
| §5.3 defineTool tipada (JSON Schema, permisos, rate limit, timeout, errores tipados) | ⚠️ | ✅ | `tools.py` (`ToolSpec`+`ToolRegistry`, allowlist de permisos, `_TokenBucket`, sandbox para exec, auditoría `calls`) |
| §5.6 Fallback multi-modelo automático | ⚠️ | ✅ | `failover.py` (`FailoverBackend`, `AllBackendsFailed`, timeout total, registro de intentos) — R11 mitigado en código |
| §5.7 Observabilidad: eventos + SSE + métricas | ⚠️ | ✅ (base propia) | `streaming.py` (EventBus, SSE), `metrics.py`, TraceLog JSONL; OTel sigue 🏢 |
| §5.9 Golden set + umbral en CI | ⚠️ | ✅ | `evalkit.py` (`run_golden`, `EvalReport.assert_gate`), `examples/golden/security_scan.json`, `harness-candy golden` (exit 2 si falla), `POST /golden` (200/422) |
| §7.1 JSON Schema publicado de contratos | ⚠️ | ✅ | `schemas.py` (16 esquemas, `SCHEMA_VERSION`, validador propio stdlib); `GET /schemas`, `harness-candy schemas/validate` |
| §7.2 Esquemas de resultado/traza/evaluación versionados | ⚠️ | ✅ | `run_result`, `trace_event`, `suite`, `golden_set` en `SCHEMAS`; `RunResult.to_dict` estable |
| §8.3 Caché de respuestas del modelo | ⚠️ | ✅ | `cache.py` (`ResponseCache` en disco con TTL+evicción, `CachedBackend`, clave SHA-256 sin la API key); `harness-candy cache --stats/--clear` |
| §12.1–12.3 Persistencia de corridas con backends | ⚠️ | ✅ | `storage.py` (`RunStore`, `JsonRunStore`, `SqliteRunStore` stdlib, `open_store("json://" \| "sqlite://")`); servidor y CLI guardan corridas |
| §13.2 Alertas de presupuesto 50/80/100% + webhook | ⚠️ | ✅ | `alerts.py` (`BudgetMonitor`, `LogSink`, `WebhookSink` sin secretos, `MultiSink`, eventos en el bus) |
| §14.1 Referencia de API publicada | ⚠️ | ✅ | `docs/API.md` (módulos, CLI, HTTP, esquemas) |
| §11.3/§18.2 Runbooks | ⚠️ | ✅ | `docs/OPERACION.md` (10 runbooks: run, suite, golden, alertas, caché, failover, incidente de seguridad, regresión, rollback, limpieza) |
| §6.2 API/visor de corridas (drill-down) | ⚠️ | ✅ | `server.py`: `/runs`, `/runs/{id}`, reportes por formato, `/events` SSE, `/suite`, `/golden`, `/schemas`, `/tools` |
| §4.4 DSL de suites JSON + ejecución como DAG | ⚠️ | ✅ | `suite.py` + `examples/suites/demo.json` + `demo_suite.py` |

| §5.2 Agentes declarativos desde archivo (agents.yaml) | ⚠️ | ✅ | `agents_catalog.py` + esquema `agents_catalog` |
| §5.8 Guardrails de salida componibles | ⚠️ | ✅ | `guards.py` (NoSecrets/MaxLength/JsonSchema/RequiredKeys/ForbiddenPatterns + pipeline tolerante a fallos) |
| §4.3 Scheduling justo de suites | ⚠️ | ✅ | `scheduler.py` (jobs por intervalo, sin solapamiento, historial); `POST/GET/DELETE /jobs` |
| §10.2 Auth del servidor + rate limit | ⚠️ | ✅ | `auth.py` (bearer `HARNESS_API_TOKEN`, comparación en tiempo constante; 120 req/min por IP) |
| §1.2 Multi-tenant base | ⚠️ | ✅ | `tenancy.py` (stores/trace_dir aislados por tenant, validación anti-traversal) |
| §11.1 Métricas a Prometheus/OTLP + visor | ⚠️ | ✅ (base) | `metrics_export.py` (`/metrics` texto Prometheus, spans OTLP/JSON, `OtlpExporter`); `web.py` dashboard en `/` con SSE; OTel nativo sigue 🏢 |
| §5.9/§21 Evaluación en lote + comparación A/B | ⚠️ | ✅ | `datasets.py` (JSONL + `compare_reports` con delta en pp y casos que cambian) |
| §6.2/§21.4 Dashboard unificado | ⚠️ | ✅ | `web.py` + endpoints `/`, `/metrics`, `/jobs`, `/events`, `/compare` |
| §5.8 Review automático de PRs (diff en alcance, sintaxis, secretos) | — | ✅ | `review.py` (`ReviewAgent.review_diff` → WevMessage medible) |
| §8.1 Latencia medida con percentiles | ⚠️ | ✅ | `latencia.py` (`bench_latencia` p50/p90/p95/p99, `comparar_latencias`) |
| §5.2 Ejemplo ejecutable de catálogo de agentes | ⚠️ | ✅ | `examples/agents.json` + `examples/demo_agents.py` |

Sigue pendiente técnico (⚠️): cassettes HTTP de proveedores reales; sharding/watch
de suites; cobertura con herramienta en CI; contenedor/gVisor para aislamiento
fuerte; actions de GitHub pineadas por SHA; Dockerfile de servicio; OTel nativo.

---

## 1. Gobernanza, alcance y decisiones previas

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 1.1 Problema que resuelven harness2/adk | 🔴 | ✅ | README + `docs/DISENO_COMBINADO.md` (problema: falta de calidad medible y de señal de evaluación para Harness²) |
| 1.1 Objetivos medibles con cifras (flakiness, tiempo CI, coste, alta de agente) | 🔴 | 🏢 (producto) | Métricas base en `metrics.py`; objetivos X% son de la org. Base medible: `bench_escalabilidad.py` |
| 1.1 No-objetivos explícitos | 🔴 | ✅ | README "Limitaciones" |
| 1.1 Stakeholders y roles | 🔴 | 🏢 (líder de proyecto) | `CODEOWNERS` define owners de código |
| 1.1 Consumidores internos y casos de uso | 🟡 | 🏢 (producto) | Caso de uso medible ya: informe de seguridad de repo (`demo_e2e.py`) |
| 1.1 Esfuerzo por fase (t-shirt) | 🟡 | ✅ | `docs/ROADMAP.md` (Fase 0 hecha, 1 hecha, 2 en curso, 3-4 org) |
| 1.1 KPIs y umbrales por fase | 🟡 | ⚠️ | Umbrales de calidad en `quality`/`security` (≥0.98, <5%, m≥3); KPIs de adopción 🏢 |
| 1.1 Dependencias externas | 🟡 | ✅ | `docs/INDEPENDENCIA.md` (ADK opcional, Harness² aislado, proveedor LLM, unshare) |
| 1.1 Visión de 1 página | 🟢 | ✅ | README (resumen del diseño) |
| 1.2 ADR-001 reemplaza v1 vs convive | 🔴 | ✅ | `docs/adr/ADR-001` (adaptador propio, reemplazable; convive con el paper oficial) |
| 1.2 ADR-002 adk propio vs wrapper externo | 🔴 | ✅ | `docs/adr/ADR-002` (núcleo independiente; google-adk como capa opcional) |
| 1.2 ADR-003 aislamiento de ejecución | 🔴 | ✅ | `docs/adr/ADR-003` (subproceso + unshare -rn; contenedor pendiente) |
| 1.2 ADR-004 lenguajes/runtimes | 🔴 | ✅ | `docs/adr/ADR-004` (Python ≥3.10 stdlib; ruta a Rust selectiva con mediciones) |
| 1.2 ADR-005 persistencia | 🔴 | ✅ | `docs/adr/ADR-005` (JSON/JSONL local, backends enchufables) |
| 1.2 ADR-006..014 (OTel, secretos, SemVer, plugins, multi-tenant, caché, streaming, i18n) | 🟡🟢 | ⚠️ | SemVer ✅ (`CHANGELOG.md`); OTel/caché/multi-tenant 🏢; secretos ✅ política env (`SECURITY.md`) |
| 1.3 Owner técnico, reviewers, aprobaciones | 🔴 | ✅/🏢 | `CODEOWNERS` (owners de ruta); proceso de PR en `CONTRIBUTING.md` |
| 1.3 Cadencia de releases, freezes, canal soporte, RACI, early adopters, on-call | 🟡🟢 | 🏢 (org) | — |
| 1.4 Supuestos/riesgos/registro/decisiones reversibles | 🟡🟢 | ✅ | Riesgos mapeados en §22 de este doc; supuestos en ADRs |

## 2. Estructura del repositorio y monorepo

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 2.1 Layout src/tests/docs/examples/config | 🔴 | ✅ | `src/harness_candy`, `tests/`, `examples/` (4), `docs/`, `benchmarks/` |
| 2.1 Monorepo vs polirepo + workspaces | 🟡 | ✅ | Monorepo simple de un paquete (`pyproject.toml` src-layout); ADR-004 |
| 2.1 packages/ compartidos, tools/, integrations/ | 🟢🟡 | ⚠️ | Un solo paquete hoy; separar cuando haya segundo módulo |
| 2.2 README, CHANGELOG, LICENSE, CONTRIBUTING | 🔴 | ✅ | raíz del repo |
| 2.2 CODEOWNERS, .editorconfig/.gitattributes/.gitignore, SECURITY.md, SUPPORT.md, ARCHITECTURE.md | 🟡 | ✅/⚠️ | Todos creados; SUPPORT.md → canal interno 🏢 (nota en SECURITY.md) |
| 2.2 GOVERNANCE.md, ROADMAP.md | 🟢 | ✅ | `docs/ROADMAP.md`; gobernanza = CODEOWNERS |
| 2.3 Linter, formateador, typecheck estricto | 🔴 | ⚠️ | CI: `compileall` ✅; añadir ruff/mypy como extra opcional pendiente |
| 2.3 pre-commit, commitlint, markdownlint, complejidad, dead-code | 🟡🟢 | ⚠️ | Convención de commits ✅ en CONTRIBUTING; hooks pendientes |
| 2.4 Convenciones de código/errores | 🟡🟢 | ✅ | `CONTRIBUTING.md` (estilo, errores como excepciones tipadas `ProtocolError`/`BackendError`/`PermissionError`) |

## 3. Diseño de API y contratos públicos

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 3.1 API pública estable de harness2 (nuestro adaptador) | 🔴 | ✅ | `harness.py` exports + `__all__` en `__init__.py` |
| 3.2 API pública de adk (defineAgent/defineTool/MemoryStore/ModelProvider) | 🔴 | ✅ | Equivalentes: `agents.Agent`, XEV allowlist+checks, `memory.*`, `backends`/`pool` (`LLMBackend`, `ModelPool`) |
| 3.3 Contrato versionado harness2↔adk + tests de contrato en CI | 🔴🟡 | ✅ | Protocolos tipados versionados (`protocols.py`) + job `contract` en CI |
| 3.4 SemVer + matriz de compatibilidad + detección de breaking | 🔴🟡🟢 | ✅/⚠️ | SemVer ✅ (`CHANGELOG.md`, `pyproject`); api-extractor automático ⚠️ |

## 4. Harness2 — núcleo de ejecución (aquí: el adaptador P-P-C + runner del DAG)

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 4.1 Config con esquema validado, overrides por entorno, precedencia CLI>env>archivo | 🔴 | ✅ | `Budget`, `PoolEntry`, `Harness` como config tipada; precedencia en `run_task` (store → budget → default) |
| 4.2 CLI run/list/report/config/version/init | 🔴 | ⚠️ | Equivalente script: `examples/*.py`; CLI empaquetada pendiente |
| 4.3 Aislamiento por caso con límites de recursos | 🔴 | ✅ | `sandbox.run_sandboxed` (ADR-003) |
| 4.3 Timeouts por caso/suite/global + cancelación cooperativa | 🔴 | ✅ | timeout en sandbox + `node.deadline` + `cancel_event` (tests) |
| 4.3 Paralelo con control de concurrencia | 🔴 | ✅ | `DAGExecutor(max_concurrency)` (test de paralelismo) |
| 4.3 Sharding, reintentos con backoff, detección de flaky, hooks, watch, filtros, priorización, changed-only, scheduling justo | 🟡🟢 | ⚠️ | Reintentos con feedback ✅ (test); backoff/flaky-detection/sharding/watch 🏢 o pendientes menores |
| 4.4 DSL de casos/suites, async, fixtures, data-driven, snapshots, matchers | 🔴🟡 | ✅/⚠️ | `Task`/criterios como casos; fixtures en `tests/helpers.py`; snapshots → trazas JSONL ✅; matchers → checks de WEV |
| 4.5 Reportes: consola, JUnit, JSON, HTML, artefactos, agregados | 🔴🟡 | ✅/⚠️ | JSON ✅ (`RunResult.to_dict`, TraceLog), consola ✅ (demos), métricas agregadas ✅ (`MetricsCollector`); JUnit/HTML ⚠️ |
| 4.6 Determinismo: seed, tiempo congelado, red aislada, cassettes, replay/record | 🔴🟡 | ✅/⚠️ | seed propagada ✅ + test de reproducción 100%; red aislada ✅; cassettes HTTP ⚠️ (mock local en tests; cassettes reales pendientes) |
| 4.7 Compatibilidad v1 + guía de migración + modo dual + codemod | 🔴🟡🟢 | 🏢 | No hay v1 en este repo; ADR-001 documenta convivencia con el paper oficial |
| 4.8 Plugins/middleware/registro de plugins | 🟡🟢 | ✅/⚠️ | `Proposer` protocol, `extra_checks` de WEV, `embedder` de KnowledgeMemory = puntos de extensión ✅; registro/marketplace 🟢 |
| 4.9 Casos avanzados (contrato, carga, fuzzing, mutation) | 🟡🟢 | ⚠️ | Carga ✅ parcial (`bench_escalabilidad.py`); mutation/fuzz 🟢 |

## 5. ADK — Agent Development Kit (aquí: agentes model-agnostic + componentes)

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 5.1 adk init + plantillas | 🔴 | ⚠️ | Equivalente: `examples/` (basic=e2e, tool-using=SecurityScanAgent, multi-agente=runner, evaluator=ablation); comando `init` pendiente |
| 5.2 defineAgent declarativo + validación + prompts versionados + herencia + multi-agente + registro + policy + roles | 🔴🟡 | ✅/⚠️ | `Agent(name, model, backend, Harness)` ✅; Harness versionado con fingerprint ✅; multi-agente vía DAG/roles ✅; `agents.yaml` 🟡 |
| 5.3 defineTool tipada con JSON Schema + registro + validación runtime + permisos + sandbox + timeouts/rate/budget + errores tipados + catálogo + mocks | 🔴🟡🟢 | ✅/⚠️ | Allowlist XEV + checks registry + sandbox + timeout ✅; JSON Schema publicado ⚠️; mocks ✅ (ScriptedBackend/mock HTTP) |
| 5.4 Motor de ejecución: estados, despacho de tool calls, cancelación, budgets, errores con reintentos | 🔴🟡 | ✅ | Estados en `NodeResult`; presupuestos `Budget`/nodo; reintentos con feedback ✅; streaming 🟡 |
| 5.5 Memoria: interfaz MemoryStore, PII antes de persistir, corto/largo plazo, truncado, búsqueda semántica, export, versionado | 🔴🟡🟢 | ✅/⚠️ | `VariableMemory`+`KnowledgeMemory` ✅; PII bloqueada en salida antes de log ✅; búsqueda semántica vía `embedder` inyectable ⚠️; esquema versionado ⚠️ |
| 5.6 ModelProvider multi-proveedor, config por agente, pin de modelo, fallbacks, límites de coste, local, routing, caché | 🔴🟡🟢 | ✅/⚠️ | `LLMBackend` + `OpenAICompatibleBackend` + `ModelPool` (roles/cuotas/costo) ✅; fallback multi-modelo ⚠️ (hay pool; falta failover automático); caché ⚠️ |
| 5.7 Observabilidad del agente: logs estructurados trace_id, OTel, métricas, exportadores, visor, replay | 🔴🟡🟢 | ✅/🏢 | `TraceLog` JSONL con run_id/model/seed/harness ✅; métricas (tokens/coste/latencia) ✅ en `metrics.py`; OTel 🏢 (estándar org) |
| 5.8 Seguridad: permisos por tool, sandbox, secretos fuera de logs, guardrails E/S, auditoría, prompt injection, exfiltración, salida estructurada, kill switch | 🔴🟡🟢 | ✅/⚠️ | Allowlist+permisos ✅, sandbox ✅, claves solo env ✅ (CI verifica), guardias entrada/salida ✅, auditoría vía trazas ✅, inyección ✅ detectada, PII salida ✅; kill switch = `cancel_event` ✅; red teaming 🟢 |
| 5.9 Evaluación: golden set, rúbricas, regresión en CI con umbrales, A/B, judge calibrado, leaderboard, robustez, humana | 🔴🟡🟢 | ✅/⚠️ | Rúbrica=Q(criterios ISA) ✅, regresión ✅ (`RegressionGuard`, CI job contract), A/B ✅ (`ablation`, `k_curve`), juez calibrado ✅ (`judge.calibrate/swap_test`); golden set propio por dominio ⚠️ |
| 5.10 Ciclo de vida del agente (draft/beta/stable/deprecated/retired) | 🟡🟢 | 🏢 | Estados de tarea ✅; estados de agente como catálogo org 🏢 |

## 6. Integración Harness2 ↔ ADK

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 6.1 Suites que invocan agentes + fixtures + aislamiento entre casos | 🔴🟡 | ✅ | tests e2e + `helpers.make_runner`; store/budget fresh por run ✅ |
| 6.1 Cassettes, determinismo (seed, temp 0), aserciones específicas, trace_id, golden e2e, mocks de provider | 🟡 | ✅/⚠️ | seed ✅, mocks ✅, run_id ✅, aserciones=wev checks ✅; cassettes HTTP ⚠️ |
| 6.2 Reporte unificado + drill-down + comparativa + BI | 🔴🟡🟢 | ✅/⚠️ | `RunResult.to_dict` unifica ✅; comparativa ✅ (ablation); BI 🟢 |
| 6.3 Contrato público versionado + tests de contrato + matriz | 🔴🟡 | ✅ | protocolos v0.1 + job `contract` CI ✅ |
| 6.4 Flujos integrados (definir→test→evaluar→promover; regresión→traza→fix) | 🟡🟢 | ✅ | demos e2e + ablation; promoción de harness vía store ✅ |

## 7. Modelo de datos y esquemas

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 7.1 JSON Schema publicado de configs | 🔴 | ⚠️ | Validación en código (`protocols.validate`); publicar JSON Schema pendiente |
| 7.2 Esquemas de resultados/reportes/traza/evaluación estables + versionado | 🔴🟡 | ✅/⚠️ | `to_dict` estables en mensajes/RunResult/TraceLog/AblationReport ✅; versionado de esquema de reporte ⚠️ |
| 7.3 Esquemas de dominio adk (agente/tool/memoria/guardrail) | 🟡🟢 | ⚠️ | Análogos en dataclasses; publicar como JSON Schema pendiente |
| 7.4 Migraciones de datos | 🟡🟢 | ⚠️ | Persistencia JSON versionada por archivo; herramientas de migración 🟡 |

## 8. Ingeniería de rendimiento

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 8.1 Objetivos de rendimiento (suite, agente, arranque, memoria) | 🔴🟡🟢 | ⚠️/🏢 | Datos base: `bench_escalabilidad.py` (tiempo/tarea); objetivos numéricos 🏢 |
| 8.2 Suite de benchmarks reproducible + CI + histórica | 🔴🟡🟢 | ✅/⚠️ | `benchmarks/bench_escalabilidad.py` ✅; smoke en CI ✅; dashboard histórico 🏢 |
| 8.3 Caché de deps/artefactos/respuestas, arranque frío, paralelización | 🟡🟢 | ⚠️ | Caché de respuestas de modelo pendiente; paralelización ✅ (DAG) |
| 8.4 Capacity planning, escalado horizontal, pruebas de carga | 🟡🟢 | ⚠️/🏢 | Bench de carga ✅ parcial; capacity 🏢 |

## 9. Infraestructura, CI/CD y DevOps

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 9.1 Dockerfile multi-stage, imagen base, devcontainer, lockfiles, imágenes firmadas, SBOM | 🔴🟡🟢 | ⚠️/🏢 | Librería Python: se publica vía `pyproject.toml` (PyPI) ✅; Dockerfile/SBOM 🏢 (no hay servicio que desplegar aún) |
| 9.2 Pipelines CI: lint+typecheck, unit, integración, evaluación, caché, sharding, reportes en PR, matriz, bench, seguridad | 🔴🟡🟢 | ✅/⚠️ | `.github/workflows/ci.yml`: lint+secretos, tests 3.10–3.12, contrato, smoke ✅; sharding/matriz extra ⚠️ |
| 9.3 Release: tag→build→publish→changelog, SemVer verificado, firma, registro interno, canales, backports | 🔴🟡🟢 | ⚠️/🏢 | CHANGELOG ✅; pipeline de publicación a registro 🏢; pin de actions por SHA ⚠️ |
| 9.4 Entornos dev/staging/prod, aislamiento, chaos, canary, flags | 🟡🟢 | 🏢 | — |
| 9.5 Build reproducible | 🔴🟡🟢 | ✅ | Cero dependencias externas; CI en matriz de versiones fija ✅ |

## 10. Seguridad transversal

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 10.1 SCA, escaneo de secretos, SAST, SBOM, política de dependencias, pin SHA, provenance, licencias | 🔴🟡🟢 | ✅/🏢 | Secret scan en CI ✅; cero deps en núcleo ✅; SCA/SAST/SBOM/provenance 🏢 |
| 10.2 Superficie adk: revisión de tools, límites de recursos, validación de tool calls, red aislada, prompt injection, red team, kill switch, revisión de prompts | 🔴🟡🟢 | ✅/🟢 | Allowlist+límites+sandbox+guardia inyección+kill switch (cancel_event) ✅; red team 🟢 |
| 10.3 Datos/privacidad: clasificación, redacción antes de logs, retención, borrado GDPR, cifrado, RBAC, auditoría de acceso | 🔴🟡🟢 | ✅/🏢 | PII bloqueada/redactada en salida ✅; no se persisten PII ✅; retención/borrado/cifrado en reposo 🏢 |
| 10.4 Respuesta a incidentes de seguridad | 🟡🟢 | 🏢 | `SECURITY.md` (canal privado, 72 h) ✅ base; runbook/simulacros 🏢 |

## 11. Observabilidad y SRE

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 11.1 OTel adoptado, convención de spans, dashboards, alertas, retención, muestreo, correlación | 🔴🟡🟢 | ✅/🏢 | Base propia ✅: TraceLog JSONL (run_id/model/seed/harness/phase/q) + métricas; OTel 🏢 (estándar org) |
| 11.2 SLOs/SLIs/error budgets/burn rate | 🟡🟢 | 🏢 | — |
| 11.3 Runbooks, on-call, postmortems, game days | 🟡🟢 | ⚠️/🏢 | Plantilla postmortem ✅ (`docs/templates/POSTMORTEM.md`); runbooks/on-call 🏢 |

## 12. Datos, almacenamiento y persistencia

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 12.1 Resultados de suites: dónde, esquema versionado, backups, retención, índices | 🔴🟡🟢 | ✅/🏢 | JSONL local ✅ (ADR-005); backups/retención 🏢 |
| 12.2 Trazas: backend, muestreo, consultas | 🟡🟢 | ✅/🏢 | JSONL ✅; backend org 🏢 |
| 12.3 Memoria de agentes: backend, esquema, cifrado en reposo, TTL, semántica | 🔴🟡🟢 | ✅/⚠️ | Interfaz + JSON ✅; vector DB/cifrado 🏢 |
| 12.4 Cassettes: almacenamiento, sin secretos, regeneración, compresión | 🟡🟢 | ⚠️ | Mocks en tests ✅; cassettes HTTP con scan de secretos pendiente |

## 13. Costes, presupuesto y FinOps

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 13.1 Presupuesto mensual, budget caps duros | 🔴🟡 | ✅/🏢 | Caps por tarea ✅ (`Budget`, ec. 3); presupuesto mensual org 🏢 |
| 13.2 Alertas 50/80/100%, dashboard de coste, optimizaciones, atribución | 🟡🟢 | ⚠️/🏢 | `allows_probe`/`charge` ✅; alertas y dashboard 🏢; costo por corrida y tokens medidos ✅ |
| 13.3 Análisis de operaciones costosas, política de modelos, caché, budgets adaptativos | 🟡🟢 | ⚠️/🟢 | Selección de modelo por rol (ligero/potente) ✅; caché 🟢 |

## 14. Documentación y formación

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 14.1 docs técnica (inicio rápido, referencia, integración, seguridad, operaciones, performance, migración, ADRs, versionada, búsqueda) | 🔴🟡🟢 | ✅/⚠️ | README ✅, `docs/DISENO_COMBINADO.md` ✅, `docs/CHECKLIST_ESTADO.md` ✅, seguridad ✅ (`SECURITY.md`), performance ✅ (bench), ADRs ✅; despliegue versionado/búsqueda 🏢 |
| 14.2 Ejemplos (≥3 ejecutables), tutorial, vídeos, FAQ, recetario, codelabs | 🔴🟡🟢 | ✅/🏢 | 4 ejemplos ✅ (`demo_e2e`, `demo_ablation`, `demo_xkiro`, `bench_escalabilidad`); tutorial/vídeos 🏢 |
| 14.3 Formación, certificación, champions | 🟡🟢 | 🏢 | — |

## 15. Migración y rollout

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 15.1 Fases shadow→opt-in→default, feature flags, criterios de salida, rollback | 🔴🟡 | 🏢 | No hay v1 que migrar en este repo; ADR-001; rollback = conservar h0 (ec. 2) ✅ a nivel de harness |
| 15.2 Adopción (métricas, office hours, early adopters, NPS) | 🟡🟢 | 🏢 | — |
| 15.3 Sunset de v1 | 🟡🟢 | 🏢 | — |

## 16. Cumplimiento, legal y licencias

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 16.1 Licencias: revisión de dependencias, política, atribución, SBOM | 🔴🟡🟢 | ✅/🏢 | LICENSE MIT ✅; núcleo sin dependencias ✅; SBOM 🏢 |
| 16.2 Cumplimiento (GDPR/SOC2/HIPAA), retención, auditoría, certificaciones | 🟡🟢 | 🏢 | PII no se persiste y se bloquea en salida ✅ (base técnica) |
| 16.3 Contratos con proveedores de modelo | 🟡🟢 | ⚠️/🏢 | xkiro: clave solo en env, HTTPS, sin logs de clave ✅; due diligence 🏢 |

## 17. Ecosistema, plugins y comunidad

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 17.1 Modelo de plugins, registro, versionado, guía, marketplace | 🟡🟢 | ✅/🟢 | Puntos de extensión ✅ (Proposer, checks, embedder); marketplace 🟢 |
| 17.2 Comunidad interna (canal, RFC, bugs, reconocimiento, meetups) | 🟡🟢 | 🏢 | Plantilla RFC ✅ (`docs/templates/RFC.md`) |
| 17.3 Integraciones externas (ticketing, CI, observabilidad, secretos) | 🟡🟢 | ✅/🏢 | CI GitHub Actions ✅; resto 🏢 |

## 18. Operación, incidentes y continuidad

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 18.1 Niveles de servicio, monitorización, feature flags, self-healing | 🟡🟢 | 🏢 | — |
| 18.2 Incidentes: proceso, roles, runbooks, postmortems | 🟡🟢 | ⚠️/🏢 | Plantilla ✅; proceso org 🏢 |
| 18.3 Continuidad: plan ante fallo de proveedor, backups, comunicación, simulacros | 🟡🟢 | ⚠️/🏢 | Fallback multi-modelo vía pool ⚠️; backups 🏢 |

## 19. Estrategia de testing de Harness2 y ADK

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 19.1/19.2 Unitarios + integración + contrato + rendimiento + robustez + flakiness propio | 🔴🟡🟢 | ✅ | 104 tests: protocolos, calidad, harness, dag, memoria/pool, seguridad/sandbox, backends (mock), e2e, ablación, extras |
| 19.2 Seguridad (sandbox, permisos) y evaluación con golden set | 🟡 | ✅/⚠️ | Tests de inyección/PII/aislamiento/allowlist ✅; golden set propio por dominio ⚠️ |
| 19.3 Integrado e2e con agentes, carga, caos | 🔴🟡🟢 | ✅/⚠️ | e2e ✅ (`test_e2e`), carga ✅ parcial (bench); caos ⚠️ |
| 19.4 Cobertura mínima acordada | 🟡🟢 | ⚠️ | Sin herramienta de cobertura en CI aún (stdlib `trace` posible); objetivo 🏢 |

## 20. Criterios de aceptación (DoD)

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 20.1 harness2 MVP: CI verde, reportes, config, adapter | 🔴🟡 | ✅ | CI ✅, TraceLog/metrics ✅, Budget ✅, tests ✅ |
| 20.2 adk MVP: agente con tools, evaluación, trazas, permisos, memoria | 🔴🟡 | ✅ | SecurityScanAgent+allowlist ✅, WEV/ablation ✅, TraceLog ✅, permisos ✅, VariableMemory/KnowledgeMemory ✅ |
| 20.3 Integración: reporte unificado, trace_id, aserciones, cassettes | 🔴🟡 | ✅/⚠️ | RunResult ✅, run_id ✅, checks ✅; cassettes ⚠️ |
| 20.4 GA global (seguridad sin hallazgos, docs, SLOs, presupuesto, aprobaciones, sunset v1) | 🔴🟡🟢 | 🏢 | Parte técnica ✅; aprobaciones/SLOs/presupuesto/sunset son de la org |

## 21. Métricas de éxito y dashboard

| Ítem | Prio | Estado | Evidencia / nota |
|---|---|---|---|
| 21.1-21.3 Tablas de métricas (suite, agente, integración) | — | ✅/🏢 | Métricas medibles ✅ (`MetricsCollector`, ablation, bench); objetivos numéricos y dashboard 🏢 |
| 21.4 Dashboard unificado + alertas + informes | 🟡🟢 | 🏢 | — |

## 22. Riesgos y mitigaciones (mapeo a este repo)

| # | Riesgo (checklist v3) | Estado en el repo |
|---|---|---|
| R1 | Coste de tokens descontrolado | ✅ `Budget` ec. 3, `allows_probe`, costo/tokens medidos; alertas 🏢 |
| R2 | Tests flaky por no determinismo | ✅ seeds fijas, test de reproducción 100%, varianza en ec. 2 |
| R3 | Duplicación v1 vs v2 | ✅ ADR-001 (un solo núcleo, adaptador reemplazable) |
| R4 | Tools peligrosas | ✅ allowlist XEV + sandbox + red restringida + auditoría |
| R5 | Curva de adopción | 🏢 (DevRel) |
| R6 | Regresiones sutiles de agentes | ✅ `RegressionGuard` (>2 pp), ablación, juez calibrado (`judge.py`) |
| R7 | Fuga de secretos a prompts/logs | ✅ output guard PII/secretos + CI secret scan + claves solo en env |
| R8 | Acoplamiento harness2↔adk | ✅ contrato = protocolos tipados + job `contract` en CI |
| R9 | Prompt injection | ✅ `SecurityGate.check_input` + tests; <5% falsos positivos medido |
| R10 | Deuda de migración | 🏢 (no hay v1 aquí) |
| R11 | Dependencia de proveedor único | ⚠️ abstracción `LLMBackend` + pool multi-modelo; failover automático pendiente |
| R12 | Cambio de términos de proveedor | 🏢 (legal) |
| R13 | Coste de trazas | ✅ JSONL local comprimible; retención 🏢 |
| R14 | Sobrecarga on-call | 🏢 |
| R15 | Escepticismo/adopción | 🏢 |

## 23. Roadmap por fases
✅ `docs/ROADMAP.md` (Fase 0 y 1 hechas en el repo; 2 en curso; 3-4 organizacionales).

## 24. Anexos
✅ Plantilla ADR (`docs/adr/`), plantilla RFC y postmortem (`docs/templates/`),
convención de commits/ramas (`CONTRIBUTING.md`), ejemplo de agente y de caso
integrado (`examples/demo_e2e.py`, `demo_xkiro.py`), config (`pyproject.toml`).

---

## Resumen ejecutivo

- **Cierre técnico en el repo**: **764 tests OK**, CI verde (lint+secretos+tests 3.10–3.12+
  contrato+smoke), 7 ejemplos ejecutables, bench, ADRs 001–005, CLI empaquetada
  (`harness-candy`), servidor HTTP local con API REST+SSE, esquemas JSON Schema
  publicados, golden sets con gate, reportes JUnit/HTML/MD, caché LLM, failover
  multi-modelo, alertas de presupuesto, plugins, suites JSON, stores JSON/SQLite,
  CHANGELOG/CONTRIBUTING/SECURITY/CODEOWNERS, docs completas (v1 y v3 verificadas).
- **Pendientes técnicos concretos (⚠️)**: cassettes HTTP de proveedores reales; sharding/watch
  de suites; cobertura con herramienta en CI; contenedor/gVisor para aislamiento fuerte;
  actions de CI pineadas por SHA; OTel real; Dockerfile de servicio; ruff/mypy opcionales;
  LoopAgent real en bridge ADK.
- **Organizacionales (🏢, no cerrables desde el repo)**: owners/SLAs/stakeholders, SLOs y
  dashboards, FinOps/chargeback, legal/cumplimiento, formación, canales, on-call, release a
  registros internos, entornos dev/staging/prod, marketplace, roadmap post-GA de la org.
