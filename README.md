# Harness-Candy — Ely–Cowork: diseño combinado ADK + Harness² (implementado)

Implementación ejecutable del documento de diseño
**«Ely–Cowork·ADK+Harness²: diseño combinado» (2026-11-02)**: un entorno de
orquestación multiagente que separa la **administración** del trabajo
(estructura, DAG, modelos) de su **ejecución** (cada agente mejorado para su
tarea) y de su **calidad** (criterios medibles, juez independiente, decisión
estadística, seguridad y trazabilidad).

```
Nivel 1  Orquestación (ADK):  ISA planifica · YEV traduce el plan a un DAG
Nivel 2  Agentes de tarea:    ZEV investiga · XEV ejecuta · WEV valida
                               (cada uno con su ciclo Harness² P→P→C)
Nivel 3  Recursos:            pool de claves/modelos por rol, MCP, sandbox
Capa transversal de calidad:  criterios · Q(a) · regla estadística ·
                               seguridad · trazabilidad JSONL · regresión
```

Los **seis componentes** son responsabilidades diferenciadas (no obligatoriamente
seis modelos): `ISA`, `YEV`, `ZEV`, `XEV`, `WEV`, `ELY`. La regla clave del
documento se respeta: **quien produce no acepta su propio trabajo**
(`DONE ≠ CORRECT`): WEV valida, ELY meta-evalúa.

## Instalación y uso rápido

Solo usa la librería estándar de Python (≥ 3.10). Sin dependencias obligatorias:

```bash
pip install -e .          # o simplemente añade src/ al PYTHONPATH
python -m unittest discover -s tests -v   # 322 tests
python examples/demo_e2e.py               # flujo completo ISA→…→ELY
python examples/demo_ablation.py          # experimento de ablación A/B/C/D
python examples/demo_suite.py             # suite JSON de tareas como DAG
python examples/demo_golden.py            # golden set con puerta (gate) de CI
python examples/demo_server.py            # servidor HTTP local + pedidos reales
harness-candy --help                      # CLI: run/suite/golden/report/serve/...
harness-candy serve --port 8000           # API REST local (ver docs/API.md)
```

Ejemplo mínimo:

```python
from harness_candy import ModelPool, PoolEntry, HarnessStore, Budget, WEV, SecurityGate
from harness_candy.agents import SecurityScanAgent, ScriptedBackend, Task
from harness_candy.runner import run_task

pool = ModelPool()
pool.add(PoolEntry("flash-1", "modelo-ligero", "MI_API_KEY", roles={"xev"}))
wev = WEV(SecurityGate())
agent = SecurityScanAgent("XEV", "modelo-ligero", ScriptedBackend(lambda *a, **k: "…"))

task = Task(task_id="t-1", kind="security_scan", instruction="escanear repo",
            inputs={"root": "."}, criterios=[...])
artifact = run_task(task, agent, pool, HarnessStore(),
                    Budget(total=10_000, beta=0.5, k=2, m=3), wev)
```

Para ejecutar con **modelos reales** no hace falta cambiar nada: implementa
`LLMBackend.complete(prompt, system, model, seed)` sobre LiteLLM/ADK y pásalo
al agente (los agentes son *model-agnostic*; el Nivel 3 elige modelo y clave
por rol). Para construir los agentes de flujo reales de ADK desde el DAG usa
`harness_candy.adk_bridge.build_adk_flow(dag, agent_factory)` (extra `adk`).

### Probar con un modelo real de xkiro (API OpenAI-compatible)

Ya viene listo un backend estándar (`backends.OpenAICompatibleBackend`, solo
stdlib, sin guardar claves en el repo):

```bash
export XKIRO_API_KEY="sk-..."                    # tu clave (variable de entorno, NUNCA en el codigo)
export XKIRO_BASE_URL="https://api.xkiro.ai/v1"  # opcional, ese es el default
export XKIRO_MODEL="nombre-del-modelo"           # opcional
python examples/demo_xkiro.py                    # ping al modelo + run_task con adaptador Harness^2
```

> Seguridad: si una clave se comparte por chat queda expuesta — rómpela/rotala
> en el panel del proveedor. El paquete solo lee `XKIRO_API_KEY` del entorno;
> `git grep` no debe encontrar ninguna clave.

## Qué se implementó del documento (mapeo)

| Sección del PDF | Módulo |
|---|---|
| §3/§5.3 Protocolos tipados y versionados `yev/zev/xev/wev`, rechazo de malformados | `protocols.py` |
| §5 Ec. (1) score Q(a); §9 criterios de aceptación medibles | `quality.py` (`score_q`), `components.py` (`WEV`) |
| §5 Ec. (2) decisión estadística candidato vs. referencia (m corridas) | `quality.py` (`compose_delta`, `should_adopt`) |
| §2.2/§5/§12 Harness²: 8 componentes editables, ciclo Propose→Probe→Compose | `harness.py` (`Harness`, `Harness2Adapter`) |
| §5 Ec. (3) costo de adaptación y presupuestos; reutilización de harness | `harness.py` (`Budget`, `HarnessStore`) |
| §5 Listado 1 `run_task` | `runner.py` (`run_task`) |
| §6 Pool de claves/modelos por rol (Nivel 3) | `pool.py` |
| §6.3 DAG con dependencias, paralelización, reintentos, escalamiento | `dag.py` |
| §7 Memoria de variables (ámbitos, versiones, permisos) + conocimiento | `memory.py` |
| §9 Seguridad en 3 puntos (inyección, PII/secretos en salida) | `security.py` |
| §9/§13 Sandbox efímero y red restringida para XEV | `sandbox.py` |
| §4/§8 Seis componentes y flujo de 8 pasos | `components.py`, `runner.py` |
| §3 YEV como puente con ADK (DAG → Sequential/Parallel/Loop) | `adk_bridge.py` |
| §12 Experimento de ablación A/B/C/D | `ablation.py` |
| §9/§5 Trazabilidad JSONL (run_id, modelo, semilla, harness) y regresión/deriva | `quality.py` (`TraceLog`, `RegressionGuard`) |

Ver `docs/DISENO_COMBINADO.md` para el detalle, las ecuaciones y las notas
de implementación (p. ej. la forma estándar `√m` del error estándar en la
ecuación 2).

## Estructura

```
src/harness_candy/
  protocols.py    yev/zev/xev/wev tipados y versionados (rechazo de malformados)
  quality.py      Q(a) ec.(1), regla ec.(2), TraceLog JSONL, RegressionGuard
  harness.py      Harness (8 componentes), HarnessStore, Budget ec.(3), adaptador P-P-C
  memory.py       VariableMemory (session.state) + KnowledgeMemory (largo plazo)
  pool.py         ModelPool: modelo y clave por rol, cuotas, rotación
  dag.py          TaskDAG + DAGExecutor (paralelo por capas, reintentos, escala)
  security.py     SecurityGate: inyección de instrucciones (entrada), PII/secretos (salida)
  sandbox.py      run_sandboxed: cwd efímero, timeout, red aislada (unshare -rn)
  agents.py       Agent/LLMBackend model-agnostic + SecurityScanAgent (demo)
  components.py   ISA, YEV, ZEV, XEV, WEV, ELY
  runner.py       run_task (Listado 1) + CoworkRunner (flujo de 8 pasos)
  adk_bridge.py   DAG → flujo ADK (Sequential/Parallel) si google-adk está instalado
  ablation.py     experimento A/B/C/D con veredicto estadístico
tests/            264 tests (unittest, sin dependencias)
examples/         demo_e2e, demo_ablation, demo_xkiro, demo_suite, demo_golden,
                  demo_cli, demo_server, bench_escalabilidad, suites/, golden/
benchmarks/       bench_escalabilidad.py (escalabilidad del DAG, métricas y tiempos)
docs/             DISENO_COMBINADO.md (mapeo al PDF), adr/ (ADR-001..005), ROADMAP.md,
                  CHECKLIST_V3_ESTADO.md, API.md (referencia), OPERACION.md (runbooks),
                  templates/ (RFC, postmortem)
.github/workflows/ci.yml  (lint + escaneo de secretos + tests 3.10-3.12 + contrato + smoke)

Nuevos módulos de la expansión (stdlib-only):
  schemas.py    JSON Schema publicados de todo el contrato + validador propio
  tools.py      registro de herramientas tipadas (permisos, rate limit, sandbox, auditoría)
  cli.py        harness-candy run|suite|golden|report|validate|schemas|serve|...
  server.py     API REST local + SSE (/runs, /suite, /golden, /schemas, /tools, /events)
  suite.py      suites JSON de tareas ejecutadas como DAG
  evalkit.py    golden sets con gate min_pass_rate (CI)
  report.py     reportes JUnit XML / HTML / Markdown
  storage.py    RunStore: JSON en disco o SQLite (stdlib)
  cache.py      caché en disco de respuestas LLM (SHA-256, TTL, sin la API key)
  failover.py   failover automático multi-backend (R11)
  retry.py      backoff exponencial + jitter determinista
  plugins.py    registro de plugins con hooks tolerantes a fallos
  streaming.py  EventBus + formato SSE
  alerts.py     alertas de presupuesto 50/80/100% (log/webhook, sin secretos)
  factory.py    constructores por defecto (CLI, servidor, ejemplos)
  auth.py       TokenAuth (bearer, HARNESS_API_TOKEN) + rate limit por IP
  tenancy.py    TenantManager: stores/trace_dir aislados por proyecto
  agents_catalog.py  catalogo de agentes desde JSON (esquema agents_catalog)
  guards.py     guardrails de salida componibles (pipeline tolerante a fallos)
  scheduler.py  jobs de suites por intervalo (sin solapamiento) -> /jobs
  datasets.py   datasets JSONL de evaluacion + comparacion A/B
  metrics_export.py  /metrics (Prometheus) + spans OTLP/JSON + OtlpExporter
  web.py        dashboard en / (HTML+JS, SSE en vivo, URLs relativas)
```

El servidor (`harness-candy serve`) expone ademas: panel en `/`, `/metrics`,
`/jobs`, y auth bearer opcional con `HARNESS_API_TOKEN` (ver `docs/API.md`).

## Estado del checklist y documentación

- `docs/CHECKLIST_ESTADO.md` — el checklist de Ely–Cowork verificado ítem por ítem
  contra el código, con la evidencia (test/ejemplo) de cada uno y las decisiones
  que el documento dejaba abiertas (almacén de harness separado; forma `√m` de la ec. 2).
- `docs/DISENO_COMBINADO.md` — mapeo detallado sección-del-PDF → módulo, con leyenda
  [EXISTENTE] / [PROPUESTA] / [HIPÓTESIS] en cada afirmación.
- `docs/INDEPENDENCIA.md` — dependencias críticas identificadas y lista priorizada
  de migración a Rust (YEV, almacén de variables, sandbox), con mediciones de partida.
- `docs/arquitectura.mmd` — diagrama mermaid de niveles y componentes (se renderiza en GitHub).
- `docs/CHECKLIST_V3_ESTADO.md` — **checklist extendido v3 (24 secciones) auditado ítem por
  ítem** contra este repo: ✅ cumplido con evidencia / ⚠️ pendiente técnico concreto /
  🏢 organizacional (con responsable sugerido). Incluye el mapeo de los riesgos R1–R15.
- `docs/ROADMAP.md` — fases 0–4 del §23 aterrizadas: Fase 0 y 1 hechas, Fase 2 en curso, 3–4 organizacionales.
- `docs/adr/` — decisiones arquitectónicas (ADR-001 adaptador Harness² propio vs. repo
  oficial de Google; ADR-002 ADK externo opcional; ADR-003 aislamiento; ADR-004 Python
  stdlib; ADR-005 persistencia JSON), fundamentadas en el paper
  *Harness 2: Recursive Agent Harnessing for an Open World* (arXiv:2610.14224).
- `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODEOWNERS`, `.editorconfig`,
  `.gitattributes` — gobernanza y operación del repo; CI en `.github/workflows/ci.yml`
  (incluye **escaneo de secretos**: el repo no debe contener claves).
- `docs/API.md` — referencia de la API pública, la CLI y los endpoints HTTP;
  `docs/OPERACION.md` — runbooks (corridas, suites, golden en CI, alertas de
  presupuesto, caché, failover, incidente de seguridad, rollback).

## Métricas que se miden (y las que no)

`metrics.MetricsCollector` (expuesto en `RunResult.metrics`) mide requisitos
cumplidos, pruebas superadas, defectos por severidad, tiempo, costo de
adaptación y de corridas, tokens, trabajo duplicado, mantenibilidad y
escaladas/revisiones humanas. **No** se miden líneas de código generadas
(el diseño lo desaconseja). WEV además revisa el *diff* (`check_diff_paths`),
no solo el resultado final. Bench: `python examples/bench_escalabilidad.py 24`.

## Decisiones tomadas (que el PDF dejaba abiertas)

1. La biblioteca de harness (`HarnessStore`) **no comparte almacén** con la
   memoria de conocimiento (`KnowledgeMemory`): ciclos de vida, permisos y
   versionado distintos.
2. En la ec. (2) se usa la forma estándar del error estándar (`√m`); el PDF
   imprime `/m`.
3. Mann–Whitney se usa cuando Q es binaria/discreta o las muestras son chicas;
   por defecto Compose usa la regla δ de la ec. (2).

## Notas de seguridad

- El código generado por XEV **siempre** corre en `sandbox.run_sandboxed`:
  directorio efímero, timeout, entorno mínimo (sin credenciales heredadas) y,
  si el sistema lo permite, namespace de red propio (`unshare -rn`).
- Las claves API nunca se almacenan: el pool referencia variables de entorno.
- Las puertas de entrada/salida bloquean inyección de instrucciones y fugas de
  PII/secretos (objetivo del documento: seguridad ≥ 0.98, fuga de PII = 0).

## Limitaciones (honestas, como indica el PDF §13)

- `ScriptedBackend`/`SecurityScanAgent` son deterministas para tests y demos;
  con LLMs reales sustituye el backend (misma interfaz).
- Harness² es un proyecto de investigación sin soporte oficial: aquí está
  **aislado tras el adaptador** (`Harness2Adapter`) para poder reemplazarlo.
- La ruta a infraestructura propia (Rust, §11) queda como interfaz estable:
  los protocolos tipados son el contrato interno que permite sustituir
  componentes sin romper a los demás.

## Licencia

MIT (ver `LICENSE`).
