# Mapeo detallado: documento «Ely–Cowork·ADK+Harness²: diseño combinado» → código

Este paquete implementa, de forma ejecutable y testeada, las propuestas del
documento de diseño combinado (2026-11-02). A continuación, sección por sección.

**Leyenda usada en este documento** (ítem 10 del checklist): cada afirmación se
etiqueta como **[EXISTENTE]** (está en ADK/Harness² o en la literatura citada),
**[PROPUESTA]** (lo añade este diseño y hay que validarlo experimentalmente) o
**[HIPÓTESIS]** (idea a confirmar con mediciones).

## 1. Principio de diseño: tres responsabilidades separadas

| Pieza del documento | Implementación |
|---|---|
| ADK: estructura y paralelización (`SequentialAgent`, `ParallelAgent`, `LoopAgent`, `session.state`) | `adk_bridge.py` traduce el DAG a flujo ADK; `memory.VariableMemory` es el análogo de `session.state`; con `google-adk` instalado, `build_adk_flow` construye los agentes reales |
| Harness²: mejorar a cada agente en su tarea (8 componentes editables, pesos fijos) | `harness.Harness` (system_prompt, guardrails, memory, tool_guidance, subagents, skills, scripts, plugins) + `Harness2Adapter` |
| Capa de calidad (nueva en el documento) | `quality.py` + `components.WEV` + `components.ELY` + `security.py` |

Los dos tipos de paralelismo se distinguen: `dag.DAGExecutor` (work
parallelism, ramas del DAG en paralelo) vs. el adaptador con `--k N` (testing
parallelism, N configuraciones del **mismo** agente).

## 2. Cómo funciona cada marco

- **ADK**: `adk_bridge.build_flow_spec(dag)` produce la especificación
  determinista (`sequential` de capas, cada capa `parallel` si tiene varios
  nodos) y `build_adk_flow` los agentes `google.adk` reales (extra `adk`).
- **Harness² (Propose→Probe→Compose)**: `harness.Harness2Adapter.adapt`.

## 3. Reglas de acoplamiento

- YEV es el puente con ADK: `components.YEV.build_dag` + `adk_bridge`.
- Harness² se ejecuta **por agente, antes de la tarea**, mediante el adaptador:
  `runner.run_task` (Listado 1 del documento, implementado literalmente).
- La decisión estratégica (ISA/ELY) y la ejecución (YEV/ZEV/XEV/WEV) son
  componentes distintos; el Nivel 3 asigna modelo y clave por rol
  (`pool.ModelPool.select`).

## 4. Los seis componentes

`components.py`: `ISA` (plan con requisitos, hitos, **criterios de aceptación**
y operaciones irreversibles), `YEV` (DAG + despacho `yev`), `ZEV` (RAG con
procedencia, `zev`), `XEV` (micro-tareas en sandbox, `xev`), `WEV` (valida,
`wev`, decide el veredicto; **DONE ≠ CORRECT**), `ELY` (meta-evaluador,
regresión, propuestas de mejora). La validación combina juicio y mecanismos
deterministas (py_compile, escaneo de secretos, puertas de seguridad).

## 5. Acoplamiento de Harness² con la capa de calidad (ecuaciones)

**Ecuación (1)** — `quality.score_q(criterios, cumplidos, hallazgos)`:

```
Q(a) = max(0, Σ wᵢcᵢ / Σ wᵢ  −  Σⱼ ρ_sⱼ)  ∈ [0, 1]
```

con `cᵢ ∈ {0,1}` por criterio (pesos `wᵢ`) y `ρ_sⱼ` la penalización por
severidad del hallazgo (`protocols.PENALTY_BY_SEVERITY`).

**Ecuación (2)** — `quality.compose_delta` / `quality.should_adopt`:

```
Q̄(h′) − Q̄(h₀) > δ,   δ = z₁₋α · √(s₀² + s′²) / √m
```

> Nota: el PDF imprime el denominador como `m`; aquí usamos la forma
> estadísticamente estándar del error estándar de la diferencia de medias
> (`√m`). Con m corridas por configuración (`m ≥ 3`), si no se cumple se
> conserva `h₀` (Compose descarta lo que solo es ruido).

**Ecuación (3)** — `harness.Budget`:

```
C_adapt = (1 − r) · Σₐ (1 + 2kₐ) · m · cₐ  ≤  β·B
```

`r` = tasa de reutilización de harness validados (`HarnessStore.reuse_rate`),
`cₐ` = costo de una corrida. Además la heurística del documento:
sondear solo si `E[ΔQ]·Vₐ > 2 k m cₐ` (`Budget.justifies_probe`).

El adaptador ejecuta referencia + 2k candidatos (k generales invariantes + k
de dominio) × m corridas, puntúa con WEV (ec. 1) y adopta el mejor solo si
supera δ (ec. 2). Evidencia y harness adoptado se guardan en `HarnessStore`
(biblioteca de harness, nivel 2 de «harnessing»).

## 6. Multi-API, subagentes y administración

- `pool.ModelPool`: entradas con alias, modelo, **secreto en variable de
  entorno** (nunca en claro), costo, velocidad, capacidades, roles; selección
  por rol (ligeros para ZEV/XEV, potentes para ISA/ELY), cuotas y rotación
  round-robin.
- Subagentes con autonomía limitada: `DAGExecutor` impone `max_concurrency` y
  `max_depth`; cada nodo trae `presupuesto` y `max_reintentos`.

## 7. Memoria

`memory.VariableMemory` (ámbitos session/task/project/user/app, versiones,
permisos por prefijo, detección de conflictos write-write) y
`memory.KnowledgeMemory` (persistente en JSON, con **procedencia** de cada
dato, recuperable sin reconstruir el contexto; búsqueda por tokens o con
`embedder` inyectable).

## 8. Flujo general de 8 pasos

`runner.CoworkRunner.run`: recepción → plan (ISA) → contexto (ZEV) →
distribución (YEV/DAG) → ejecución (XEV con Harness² por agente) →
validación (WEV) → evaluación global (ELY) → consolidación en memoria.

## 9. Qué agregar para elevar la calidad (tabla del §9)

Implementado en `quality.py`, `security.py`, `sandbox.py`, `components.WEV/ELY`:
criterios medibles, juez independiente (WEV/ELY distintos del generador),
decisión estadística (ec. 2), protocolos tipados, seguridad en 3 puntos
(entrada/ejecución/salida), sandbox efímero + red restringida, trazabilidad
JSONL (`run_id`, modelo, semilla, versión del harness), regresión/deriva
(> 2 pp alerta; éxito ≥ referencia − 3 %), reutilización de harness con
presupuestos, revisión humana en puntos críticos (operaciones irreversibles
que ISA marca y el flujo escala a `escalated`).

## 10–11. Escalabilidad y ruta a independencia (Rust)

El DAG + pool + memoria están pensados para repositorios grandes; los
protocolos tipados (`protocols.py`) son las **interfaces internas estables**
del paso 4 de la migración: permiten reemplazar un componente (p. ej.
YEV o el almacén de variables) sin tocar a los demás.

## 12. Ruta de implementación y validación

Los 7 pasos del documento quedan como: (1) base de orquestación →
`dag`/`adk_bridge`; (2) contratos y calidad mínima → `protocols` + `WEV`;
(3) adaptador Harness² → `harness.Harness2Adapter`; (4) memoria y delegación
controlada → `memory`, `dag`; (5) ELY y regresión → `components.ELY` +
`quality.RegressionGuard`; (6) escala y costo → `Budget`/`HarnessStore`;
(7) independencia progresiva → interfaces tipadas.

El **experimento de ablación** (`ablation.run_ablation`, demo en
`examples/demo_ablation.py`) ejecuta el mismo conjunto de tareas en:

```
A  base (solo ejecutar)
B  A + protocolos tipados + criterios + WEV
C  B + adaptador Harness²
D  C + ELY (juez independiente, regresión, ajustes)
```

y compara Q̄, tasa de éxito y costo/tarea. Veredicto: si C no supera a B por
encima de δ, el costo de Harness² no se justifica para esa tarea.

## 13. Riesgos y límites (implementados como mitigaciones)

- Harness² aislado tras el adaptador (se puede reemplazar).
- Costo: presupuestos por tarea (`Budget`), reutilización (`HarnessStore`).
- Juez LLM: WEV usa verificación determinista donde existe (compilación,
  secretos, PII) y el juicio del modelo solo como complemento.
- Seguridad: código siempre en sandbox; claves en variables de entorno.
- Paralelización: límites de concurrencia, profundidad y presupuesto.

## Reproducción de trazas

Cada corrida escribe una línea JSONL en `traces/<run_id>.jsonl` con
`run_id, task_id, model, seed, harness (versión+fingerprint), phase, q,
verdict`. Con backends deterministas (misma semilla) la reproducción es del
100 % (objetivo del documento).
