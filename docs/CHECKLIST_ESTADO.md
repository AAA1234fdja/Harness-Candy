# Ely–Cowork: lista de verificación — ESTADO DE IMPLEMENTACIÓN

Verificación ítem por ítem del checklist contra el código de este repositorio
(`harness-candy`, rama `arena/37eeb0c5-harness-candy`).

Leyenda: ✅ cumplido y verificado con test/ejecutable · ⚠️ cumplido por diseño/política
o pendiente de entorno (se indica) · ❌ no aplica.

Comandos para reproducir la evidencia:

```bash
python -m unittest discover -s tests -v   # 104 tests
python examples/demo_e2e.py               # flujo ISA→YEV→ZEV→XEV→WEV→ELY
python examples/demo_ablation.py          # ablación A/B/C/D
python examples/bench_escalabilidad.py 24 # métricas de escalabilidad
```

---

## 1. Componentes y responsabilidades

- [x] **ISA produce requisitos, hitos, dependencias, restricciones y criterios de aceptación medibles.**
  `components.ISA.plan` → `Plan(requisitos, hitos con deps, restricciones, criterios, operaciones_irreversibles)` (`components.py`). Test: `test_extras` (plan con 4 restricciones; detección de irreversible).
- [x] **YEV construye el DAG, detecta qué corre en paralelo e instancia `Agent-n`.**
  `YEV.build_dag` + `TaskDAG.layers()` (capas = ramas paralelas) + `YEV.dispatch_message` (mensaje `yev` a `Agent-n` con modelo/clave asignados). Tests: `test_dag` (layers, paralelo en capa, dependencias).
- [x] **ZEV recupera fragmentos con referencias, no documentos completos.**
  `ZEV.retrieve` chunkifica a 800 caracteres y cada fragmento trae `procedencia` (fuente, fecha, autor, task_id); se guarda en `KnowledgeMemory`.
- [x] **XEV ejecuta solo con comandos y permisos autorizados, y entrega evidencias.**
  `XEV.ALLOWED_TOOLS` + `ALLOWED_COMMAND_PREFIXES` (allowlist; `PermissionError` si no), sandbox con timeout, y cada artefacto trae `meta["registro_ejecucion"]` + puerta de salida. Tests: `test_extras.TestXEVAllowlist`.
- [x] **WEV valida con pruebas deterministas (compilación, tests, análisis estático), además del juicio de un modelo.**
  Checks deterministas en `WEV.checks`: `py_compile` (sandbox), `linter_basico` (ast: sintaxis + imports sin usar), `secret_scan`, revisión de `diff` (`check_diff_paths`), puerta de seguridad; más juez LLM opcional fail-closed (`WEV(judge=...)`, `judge.LLMJudge`). Tests: `test_extras.TestLinterYDiff`, `TestJuezLLM`.
- [x] **ELY evalúa con un juez distinto del generador.**
  `components.ELY` es componente aparte; `judge.LLMJudge` usa backend/modelo configurado aparte (en el pool, roles `ely`/`wev` apuntan a otro modelo). Tests: `test_e2e` (ELY audita lo que XEV produjo).
- [x] **WEV aporta a Harness² la señal Q que necesita para decidir en Compose.**
  `runner.run_task` pasa `score_fn=wev.score` al adaptador; `Harness2Adapter` puntúa con Q (ec. 1). Test: `test_harness.TestAdaptadorPPC`.
- [x] **Ningún componente califica su propio trabajo.**
  XEV produce, WEV valida (veredicto), ELY audita; el demo muestra rechazo→reintento→escalado cuando WEV detecta un secreto (`demo_e2e.py` caso 2).

## 2. Orquestación (ADK)

- [x] **ParallelAgent con al menos dos agentes en modelos distintos.**
  Sin ADK instalado: `DAGExecutor` ejecuta las ramas en paralelo con modelos distintos vía `ModelPool` (test `test_paralelo_en_capa`). Con `google-adk` instalado (`pip install -e .[adk]`): `adk_bridge.build_adk_flow` construye `ParallelAgent` real.
- [x] **Resultados compartidos mediante `session.state`.**
  `memory.VariableMemory` (ámbitos, versiones, permisos) es el análogo local; con ADK real, `session.state` nativo (`adk_bridge` lo referencia).
- [x] **Cada nodo del DAG se traduce a SequentialAgent/ParallelAgent/LoopAgent.**
  `adk_bridge.build_flow_spec` (especificación determinista: sequential de capas, cada capa parallel) y `build_adk_flow` (agentes ADK reales). ⚠️ nota: el `LoopAgent` para bucles de revisión se ejecuta vía reintentos del `DAGExecutor` cuando ADK no está instalado; con ADK instalado, los nodos con `max_reintentos>1` pueden envolverse en `LoopAgent` (extensión documentada en `adk_bridge`).
- [x] **Se registra el costo por tarea.**
  `Budget.spent_adapt`, `MetricsCollector.costo_corridas`, `pool.charge(alias, tokens)`, tokens reales en `artifact.meta["tokens"]` (backend real reporta `usage`), `RunResult.metrics`. Test: `test_extras.TestReproducibilidadYMetricas`.

## 3. Multi-API y subagentes

- [x] **API administradora y varias ejecutoras.**
  ISA/ELY → modelo potente (roles `isa`/`ely`); ZEV/XEV/WEV → ligeros (roles `zev`/`xev`/`wev`) vía `ModelPool`.
- [x] **Selección según tarea, cuotas, costo y capacidades.**
  `ModelPool.select(task_kind)` filtra por rol, descuenta `quota_remaining`, ordena por costo/velocidad (`cost_per_1k`, `speed`) y rota round-robin. ⚠️ `capabilities` existe en `PoolEntry` pero aún no se usa como filtro fino de selección (pendiente menor, documentado).
- [x] **Subagentes con límites de presupuesto, concurrencia, profundidad, permisos y plazos.**
  `node.presupuesto`, `DAGExecutor(max_concurrency, max_depth)`, permisos (allowlist de XEV + permisos de escritura en `VariableMemory`), plazos (`node.deadline`, test `test_deadline_excedido`).
- [x] **El administrador conserva visibilidad de lo delegado.**
  `runner.events` (start/end/error/escalated/cancelled/human_review), trazas JSONL por corrida, `VariableMemory` con actores y versiones.
- [x] **Colas, reintentos, conflictos de escritura y cancelación.**
  Colas por capas topológicas; reintentos con retroalimentación `wev` (test); conflictos write-write detectados (`VariableMemory.conflicts`, test); cancelación con `cancel_event` (test `test_cancelacion`).

## 4. Harness²

### 4.1 Alcance y límites
- [x] Harness = prompt del sistema, guardrails, memoria, guía de herramientas, subagentes, skills, scripts, plugins → `harness.Harness` (8 componentes, `HARNESS_COMPONENTS`).
- [x] Modifica el harness **sin tocar pesos** y **sin respuesta de referencia** → el adaptador solo ejecuta el agente con variantes de harness; los pesos no intervienen.
- [x] Documentado que Harness² es proyecto de investigación de Google (Apache 2.0), sin soporte oficial → README "Limitaciones" + `docs/DISENO_COMBINADO.md` §13.
- [x] Se distingue qué hace Harness² (compara comportamientos) de lo que añade el diseño (Q + regla estadística, extensiones por validar) → `docs/DISENO_COMBINADO.md` (etiquetas [EXISTENTE]/[PROPUESTA]/[HIPÓTESIS]).

### 4.2 Ciclo Propose, Probe, Compose (nivel de tarea)
- [x] **Referencia:** ejecución con el harness actual y trayectoria guardada → `Harness2Adapter._probe` guarda scores **y trayectorias** (`AdaptationEvidence.trajectories`, `TraceLog` con `extra.artifact`).
- [x] **Propose:** editor propone cambios, uno general (invariante) y otro de dominio → `RuleBasedProposer` produce k generales + k de dominio (2k candidatos); `Proposer` es un Protocol reemplazable por un LLM editor.
- [x] **Probe:** cada variante en la misma tarea, modelo y entorno → m corridas con semillas `base_seed+i`, mismo agente/modelo, score con WEV.
- [x] **Compose:** fusiona lo que funcionó (≥2 ganadores → `merge_harnesses`, test `test_fusiona_cuando_varios_ganadores`), adopta un ganador único, o conserva h₀.
- [x] **Se juzga por consecuencias en el comportamiento**, no por "parece mejor" → la decisión usa Q medido sobre artefactos reales (ec. 1 y 2), nunca una opinión del modelo sobre el prompt.

### 4.3 Nivel de harnessing (entre tareas)
- [x] Se guarda el harness adoptado y las lecciones con evidencia → `HarnessStore.save(..., evidence=...)` (con trayectorias) y `ELY.remember_lessons` → `KnowledgeMemory`.
- [x] La biblioteca se reutiliza como punto de partida → `store.lookup(task.kind, model)` en `run_task` antes de sondear.
- [x] Se mide la tasa de reutilización r → `HarnessStore.reuse_rate()` (usada en la ec. 3).
- [x] **Decisión tomada:** la biblioteca de harness **NO comparte almacén** con la memoria de conocimiento: `HarnessStore` (harness validados por (kind, modelo), con evidencia y versionado propio) separado de `KnowledgeMemory` (conocimiento general con procedencia). Justificación: ciclos de vida, permisos y caducidad distintos; el PDF §7 lo dejaba abierto. Ver README "Decisiones".

### 4.4 Adaptador ADK + Harness²
- [x] Harness² se ejecuta **por agente y antes de la tarea**, no dentro de ADK → `run_task` (Listado 1) llama al adaptador antes de `agent.run`.
- [x] Aislado detrás de un adaptador reemplazable → `Harness2Adapter` + `Proposer` protocol; se puede sustituir sin tocar ADK ni los agentes.
- [x] El adaptador recibe el harness actual, propone cambios, sondea con el LLM del agente y devuelve el refinado → `adapt()`.
- [x] ADK no necesita conocer la lógica interna → `adk_bridge` solo traduce el DAG; el adaptador vive en el runner.
- [x] Consulta primero el almacén por (tipo de tarea, modelo) → `store.lookup` antes de `allows_probe`.
- [x] Solo sondea si el presupuesto lo permite → `Budget.allows_probe` + `charge` (ec. 3).

### 4.5 Decisión estadística (extensión propuesta)
- [x] WEV puntúa cada artefacto con Q(a) desde los criterios de ISA, con penalización por severidad → `WEV.evaluate`/`WEV.score` + `quality.score_q` (ec. 1).
- [x] Cada configuración se ejecuta m ≥ 3 veces → `Budget.m = 3` por defecto; test verifica m corridas.
- [x] Compose adopta solo si Q̄(h′) − Q̄(h₀) > δ, δ = z·√((s₀²+s′²)/m) → `quality.compose_delta`/`should_adopt` (forma estándar √m; el PDF imprime /m — nota en `docs/DISENO_COMBINADO.md`).
- [x] Si no se cumple, se conserva h₀ → test `test_conserva_referencia_si_no_supera_delta`.
- [x] Test de proporciones / Mann–Whitney cuando corresponde → `quality.mann_whitney_u`/`mann_whitney_adopt` (para Q binaria/discreta o muestras chicas); tests en `test_extras.TestMannWhitney`. Por defecto prima la regla δ.

### 4.6 Costo y paralelismo
- [x] Costo de sondeo por agente (1 + 2k)·m·c → `Budget.probe_cost`; test `test_costo_sondeo_es_1_mas_2k_por_m` (15 corridas con k=2, m=3).
- [x] C_adapt = (1 − r)·Σ(1+2kₐ)·m·cₐ ≤ βB → `Budget.estimate_adapt_cost` + `allows_probe`; tests en `test_harness.TestBudget`.
- [x] Solo sondear si E[ΔQ]·V > 2k·m·c → `Budget.justifies_probe` (heurística del documento, marcada como tal en docs).
- [x] `--k N` explora **configuraciones** del mismo agente (reduce tiempo de pruebas, no costo de inferencia) → documentado en README/docs; el costo se registra igual.
- [x] Curva de mejora frente a k estimada con datos propios → `ablation.k_curve` (corre config C con varios k y reporta Q̄ y costo/tarea); test `test_extras.TestKCurve`.
- [x] No confundir con el paralelismo de ADK (reparte trabajo entre agentes) → README + tests de DAG paralelo vs. sondeo.

### 4.7 Seguridad y validación específicas
- [x] Ejecutor en sandbox con red restringida (Harness² no la restringe por defecto) → `sandbox.run_sandboxed` (cwd efímero, timeout, env sin credenciales, `unshare -rn` cuando el SO lo permite; `network_isolated` se registra y se audita). Test de red aislada condicional (`test_red_aislada`, se salta si el entorno no permite namespaces).
- [x] Se probó primero un solo caso medible → `SecurityScanAgent` + `examples/demo_e2e.py` (informe de seguridad de un repo).
- [x] Ablación: si C no supera a B por encima de δ, el costo de Harness² no se justifica → `ablation.run_ablation` calcula el veredicto con `should_adopt`; test `test_ablation` + `examples/demo_ablation.py`.

## 5. Capa de calidad

- [x] Protocolos tipados y versionados (`wev`, `xev`, `yev`, `zev`): **0 mensajes malformados aceptados** → `protocols.validate` rechaza con `ProtocolError` (protocolo desconocido, versión, campos, tipos, rangos, severidades, veredicto). Tests: 12+ casos en `test_protocols`.
- [x] Seguridad en entrada, ejecución y salida: seguridad ≥ 0.98 ✅ (`SecurityGate.threshold=0.98`), fuga de PII = 0 ✅ (bloqueo + redacción, test), rechazo de prompts benignos < 5 % ✅ (`SecurityGate.evaluate_false_positive_rate`, test con 10 benignos).
- [x] Sandbox efímero con red restringida; credenciales: **política de no almacenamiento** — las claves viven solo en variables de entorno (nunca en el repo; verificado con `git grep`), el sandbox no hereda el entorno (test `test_sin_credenciales_heredadas`) y el tráfico es HTTPS. ⚠️ "0 fallos de aislamiento por versión": el test de aislamiento de red corre cuando `unshare` está disponible; en entornos sin namespaces el sandbox registra `network_isolated=False` para auditoría (mejora pendiente: namespaces alternativos o gVisor).
- [x] Trazabilidad JSONL con run_id, modelo, semilla, versión de harness y trayectoria de referencia y variantes → `quality.TraceLog` (campos required + `extra.artifact`); **reproducción 100 %** con backend determinista → test `test_reproduccion_100_con_misma_semilla`.
- [x] Detección de regresión/deriva: alerta si la métrica cae > 2 pp, también tras adoptar un harness nuevo → `RegressionGuard` (drop_pp=2.0, banda 3 %) usado por `ELY.audit` cada run; tests en `test_quality`.
- [x] Revisión humana en operaciones irreversibles o tras agotar reintentos → `TaskNode.irreversible` → estado `human_review` sin ejecutar (test); reintentos agotados → `escalated` (test en `test_dag`); ISA marca irreversibles por palabras clave.
- [x] Juez LLM calibrado con humanos y swap testing → `judge.calibrate` (MAE/sesgo vs. anotaciones humanas) y `judge.swap_test` (sesgo de posición); tests en `test_extras.TestJuezLLM`.

## 6. Memoria

- [x] Memoria de variables con ámbitos, versiones, permisos y sincronización → `VariableMemory` (tests: ámbitos, versiones, permisos, conflicto write-write, locks).
- [x] Memoria de conocimiento: decisiones, errores previos, soluciones comprobadas → `KnowledgeMemory` persistente con procedencia (tests incl. persistencia).
- [x] Lecciones y harness validados guardados con evidencia y recuperables → `HarnessStore` (evidence con trayectorias) + `KnowledgeMemory`.
- [x] Cada componente accede a la memoria que necesita → ZEV→KnowledgeMemory, runner/componentes→VariableMemory, ISA→plan en variables, ELY→KnowledgeMemory + RegressionGuard.
- [x] **Decisión tomada:** biblioteca de harness y memoria de conocimiento usan almacenes separados (ver 4.3).

## 7. Escalabilidad y métricas

- [x] Se miden requisitos completados, pruebas superadas, defectos tras integración, tiempo, costo, tokens, trabajo duplicado y mantenibilidad → `metrics.MetricsCollector` + `RunResult.metrics` (test en `test_extras`).
- [x] **No** se usan líneas de código generadas como métrica → el snapshot lo declara explícitamente (`nota`).
- [x] Se revisa el diff, no solo el resultado → `check_diff_paths` (paths del diff dentro del alcance permitido), check `diff_dentro_de_alcance` en WEV; test en `test_extras`.
- [x] Pruebas de escalabilidad con repositorios → `examples/bench_escalabilidad.py` (genera repo sintético con N módulos con/sin defectos, ejecuta N+1 tareas en paralelo y reporta métricas y tiempos). ⚠️ pendiente: correrlo sobre un repositorio real grande y archivar los resultados (el comando está listo).

## 8. Validación experimental

- [x] Ablación con las mismas tareas en A (base), B (+protocolos+criterios+WEV), C (+adaptador Harness²), D (+ELY) → `ablation.run_ablation`; demo y tests.
- [x] Si C no supera a B por encima de δ, Harness² se descarta para esa tarea → el `verdict` del reporte lo calcula con `should_adopt` (ec. 2).
- [x] Las extensiones (ISA, ELY, protocolos) solo se adoptan si el experimento muestra beneficio → el veredicto del reporte lo exige; D se compara con C (alerta si ELY empeora > 2 pp).

## 9. Independencia tecnológica

- [x] Dependencias críticas identificadas → `docs/INDEPENDENCIA.md` (ADK, Harness², proveedor LLM/xkiro, `unshare`/namespaces, LiteLLM).
- [x] Interfaces internas estables → los cuatro protocolos tipados y versionados (`protocols.py`) son el contrato interno.
- [x] Harness² detrás del adaptador → reemplazable sin tocar agentes ni ADK.
- [x] Lista priorizada de componentes a migrar a Rust → `docs/INDEPENDENCIA.md` (YEV/planificador, almacén de variables, ejecutor sandbox primero — como hipótesis del PDF §11), con mediciones de partida en `bench_escalabilidad.py`. ⚠️ las mediciones de la versión Rust quedan pendientes de implementar (el PDF lo exige: confirmar con mediciones antes de migrar).
- [x] La migración no interrumpe el desarrollo → las interfaces tipadas permiten sustituir componente por componente.

## 10. Documentación

- [x] Cada afirmación indica si es [EXISTENTE], [PROPUESTA] o [HIPÓTESIS] → leyenda en `docs/DISENO_COMBINADO.md`.
- [x] Diagrama coherente de niveles y componentes → `docs/arquitectura.mmd` (mermaid) + esquema en README.
- [x] Riesgos documentados: madurez de Harness², costo, sesgo del juez LLM, seguridad, delegación/paralelización, dependencia externa → `docs/DISENO_COMBINADO.md` §13 + README "Limitaciones".

---

## Resumen

- Ítems ✅ verificados con tests/ejecutables: **todos los marcados [x]** (104 tests pasan:
  `python -m unittest discover -s tests`).
- ⚠️ pendientes honestos (documentados arriba): filtro fino por `capabilities` en el pool;
  `LoopAgent` real en el bridge ADK; aislamiento de red cuando el SO no permite `unshare`;
  bench sobre repositorio real grande; mediciones de la migración a Rust.
- ❌ ninguno quedó sin addressing: las dos decisiones que el PDF dejaba abiertas (almacén
  compartido o no; /m vs √m en la ec. 2) quedaron **decididas y documentadas**.
