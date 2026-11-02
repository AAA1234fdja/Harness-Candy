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

## [0.1.0] - 2026-11-02

### Añadido
- Implementación inicial del diseño combinado Ely–Cowork ADK+Harness²:
  protocolos tipados `yev`/`zev`/`xev`/`wev`; capa de calidad (Q ec. 1, regla estadística ec. 2, TraceLog JSONL, RegressionGuard);
  adaptador Harness² (Propose→Probe→Compose) con `Budget` (ec. 3) y `HarnessStore`; DAG con ejecución paralela, reintentos y escalamiento;
  pool de modelos por rol; memoria de variables y de conocimiento; seguridad (inyección/PII) y sandbox efímero sin red;
  componentes ISA/YEV/ZEV/XEV/WEV/ELY; `runner.run_task` (Listado 1) y `CoworkRunner` (flujo de 8 pasos);
  `adk_bridge` (DAG → flujo ADK real si está instalado); ablación A/B/C/D; 83 tests; demos e2e y de ablación.
