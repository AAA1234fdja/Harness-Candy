# Tutorial de 15 minutos

Recorrido práctico por Harness-Candy: del código al servidor en vivo.

## 1. Instalar y probar (2 min)

```bash
pip install -e .                                  # núcleo sin dependencias
python -m unittest discover -s tests -v           # 322 tests
python examples/demo_e2e.py                       # flujo ISA→YEV→XEV→WEV→ELY
```

## 2. La idea en un párrafo

Un objetivo entra, ISA lo convierte en plan, YEV lo parte en un DAG de
tareas, cada tarea la ejecuta XEV **mejorando su propio harness**
(Propose→Probe→Compose, como el paper arXiv:2610.14224), WEV valida con
criterios medibles (Q, ec. 1 y 2) y ELY audita. Todo queda en trazas JSONL
reproducibles (misma seed → mismas corridas).

## 3. CLI (3 min)

```bash
harness-candy version
harness-candy run --objetivo "informe de seguridad de src/" --input root=src --out /tmp/run.json --report /tmp/run.html
harness-candy suite list --file examples/suites/demo.json
harness-candy suite run --file examples/suites/demo.json --report /tmp/suite.html
harness-candy golden --file examples/golden/security_scan.json   # exit 2 si falla el gate
harness-candy validate --schema task --data '{"task_id":"t","kind":"k","instruction":"i"}'
harness-candy schemas --name suite | head
```

## 4. Servidor + panel (4 min)

```bash
harness-candy serve --port 8000
# abrir http://localhost:8000/  (panel: lanzar corridas, ver reportes, eventos SSE en vivo)
curl -X POST localhost:8000/runs -d '{"objetivo":"informe de seguridad de examples/golden/limpio","inputs":{"root":"examples/golden/limpio"}}'
curl localhost:8000/runs?limit=10
curl localhost:8000/metrics                       # Prometheus
curl -X POST localhost:8000/jobs -d '{"name":"demo","suite_path":"examples/suites/demo.json","interval_s":300}'
```

Con `export HARNESS_API_TOKEN=...` todas las rutas salvo `/health` exigen
`Authorization: Bearer ...`.

## 5. Programar (Python) (3 min)

```python
from harness_candy import build_runner, run_task, Task, Criterion, Budget, HarnessStore, WEV, SecurityGate
from harness_candy.factory import make_pool, make_backend
from harness_candy.agents import SecurityScanAgent

runner = build_runner("traces")                    # backend scripted (sin red)
res = runner.run("informe de seguridad de examples/golden/limpio",
                 inputs={"root": "examples/golden/limpio"})
print(res.qs, res.metrics)

# una sola tarea con Harness^2 (Listado 1)
agent = SecurityScanAgent("XEV", "modelo-ligero", make_backend("scripted"))
task = Task(task_id="t1", kind="security_scan", instruction="escanear",
            inputs={"root": "examples/golden/limpio"},
            criterios=[Criterion("informe_json_valido", peso=3.0)])
art = run_task(task, agent, make_pool(), HarnessStore(), Budget(total=10_000, beta=0.5, k=2, m=3), WEV(SecurityGate()))
```

## 6. Con un modelo real (xkiro)

```bash
export XKIRO_API_KEY="sk-..."        # solo en TU entorno, nunca en el repo
export XKIRO_MODEL="nombre-modelo"
harness-candy run --objetivo "informe de seguridad de src/" --input root=src --backend xkiro
# o en Python: make_backend("xkiro") / OpenAICompatibleBackend(); con cache:
#   CachedBackend(OpenAICompatibleBackend())  y  con failover:
#   FailoverBackend([OpenAICompatibleBackend(), backend_local])
```

## 7. Utilidades de sistema (cuarta ola, 3 min)

Además del núcleo Ely-Cowork, el paquete incluye utilidades propias (solo stdlib):

```bash
# RAG propio: indexar docs y preguntar con citas
harness-candy rag index --dir docs --out /tmp/idx.json
harness-candy rag query --index /tmp/idx.json --query "dónde va la clave API?" -k 3

# Workflow declarativo (steps task/set/parallel/foreach con when y depends_on)
harness-candy workflow --file examples/workflows/demo.json --out /tmp/wf.json

# Campaña multi-objetivo con presupuesto global
harness-candy campaign --file examples/campaigns/demo.json

# Evaluación agregada: golden x semillas con bootstrap e informe HTML
harness-candy evalsuite --file examples/golden/security_scan.json --seeds 0,1,2 --html /tmp/eval.html

# Resumen extractivo, plan HTN, review de diff, config, watch, codegen
harness-candy summarize --file README.md -k 3
harness-candy plan
harness-candy review --file mi.diff
harness-candy config
harness-candy watch src --once
harness-candy codegen /tmp/mi-proy --name mi-proy
```

En Python: `harness_candy.RAGPipeline`, `Workflow`/`run_workflow`, `Campaign`/`run_campaign`, `run_eval_suite`, `Planner`, `codeedit`/`diffengine`/`textdiff`, `stats`, `crypto` (firma de corridas), `graph`, `viz`, `notify`, `templates`, `config`, `summarize`, `watch`, `llm` (`ChatSession`, `structured_output`). Ver `docs/API.md` §"Cuarta ola".

## 8. Dónde seguir

- `docs/API.md` — referencia completa (módulos, CLI, HTTP, esquemas).
- `docs/OPERACION.md` — runbooks (incidentes, rollback, caché, FinOps...).
- `docs/CHECKLIST_V3_ESTADO.md` — estado ítem por ítem del checklist v3.
- `docs/adr/` — decisiones (ADR-001..005) con el paper como fundamento.
- `docs/ROADMAP.md` — fases 0–4; `docs/INDEPENDENCIA.md` — ruta a Rust medida.
