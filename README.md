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
python -m unittest discover -s tests -v   # 79 tests
python examples/demo_e2e.py               # flujo completo ISA→…→ELY
python examples/demo_ablation.py          # experimento de ablación A/B/C/D
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
tests/            79 tests (unittest, sin dependencias)
examples/         demo_e2e.py, demo_ablation.py
docs/             DISENO_COMBINADO.md (mapeo detallado al PDF)
```

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
