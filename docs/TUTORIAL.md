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

## 8. Quinta ola: Harness^2 avanzado, Vertex/Gemini, runners y scripts (5 min)

```python
from harness_candy import (LLMProposer, run_recursion, HarnessTree, seleccionar_adoptado,
                           construir_contexto, crear_runmark, VertexBackend, grid_sweep)

# 1) Proponer candidatos con LLM (fail-closed a reglas si el LLM falla)
proposer = LLMProposer(mi_backend)          # mi_backend.complete(prompt, system=, model=, seed=)
candidatos = proposer(h0, "security_scan", k=2, task=tarea, evidencia={"q_ref": 0.6})

# 2) Recursion task-level: paralela o secuencial con contexto acumulado
res = run_recursion(["paso1", "paso2"], ejecutar, modo="parallel")   # o "sequential"

# 3) Árbol de candidatos + selección estadística del adoptado
tree = HarnessTree("h0", 0.5); tree.add_candidate("cand-1", 0.8)
sel = seleccionar_adoptado([0.5, 0.5, 0.5], [CandidateScore("cand-1", [0.9, 0.95, 0.85])])

# 4) Contexto del executor y marca de corrida (reproducibilidad, sin secretos)
bundle = construir_contexto(tarea, fragmentos=rag.query("guía de seguridad"), max_tokens=2000)
marca = crear_runmark("run-1", seed=0, params={"k": 2})   # env solo como NOMBRES

# 5) Gemini en Vertex AI con ADC (GOOGLE_CLOUD_PROJECT/VERTEX_LOCATION/VERTEX_MODEL en env)
vertex = VertexBackend.from_env()            # token vía metadata GCE / gcloud / archivo ADC
texto = vertex.complete("resume este informe")
```

Runners de terceros (en `third_party/`, stdlib-only, sin depender del paquete):

```python
import sys; sys.path.insert(0, "third_party")
from jb_runner import Job, JobRunner, JobStore        # cola con prioridad + resume
store = JobStore("/tmp/jobs.json")
JobRunner(store, mi_evaluador).run([Job("a", prioridad=10), Job("b")])

from lab_runner import Experimento                   # grid de hyperparámetros en paralelo local
res = Experimento("sweep", grid={"k": [1, 2, 4]}, ejecutar=mi_eval).correr()
print(res.mejor_params, res.ic95, res.reporte_md())

from wb_runner import WorkBuddy                      # Docker + Harbor (claves solo en env)
wb = WorkBuddy.from_env("registry.empresa.co", proyecto="hc", dry_run=True)
res = wb.run("mi-app", dockerfile_dir=".", comando=["python", "-m", "app"])
```

Scripts operativos (ejecutables, desde la raíz del repo):

```bash
scripts/harness2-setup                 # prepara store/traces e informa el entorno (sin valores de env)
scripts/harness2-check                 # compileall + escaneo de secretos + tests rapidos (--full = suite completa)
scripts/harness2-judge                 # golden con gate; exit 2 si pass_rate < umbral
scripts/harness2-report --run-id judge-security-scan-basico-2 --store json://runs_h2 --out reporte.html
```

## 9. Sexta ola: benchmarks, safety, juez calibrado, QA y multi-backend (5 min)

```python
from harness_candy import (run_benchmark, load_benchmark, benchmark_card, SafetySuite,
                           CalibratedJudge, calibrar_juez, TorneoElo, run_mutation, fuzz_funcion,
                           evidence_pack, verificar_pack, evaluar_alertas, AnthropicBackend,
                           OllamaBackend, SelectorModelos, failover_desde_env)

# 1) Benchmark local estilo MMLU/SWE (suites en benchmarks/)
suite = load_benchmark("benchmarks/mini_mmlu.json")
rep = run_benchmark(suite, mi_backend.complete, modelo="mi-modelo", seeds=(0, 1), k=2)
card = benchmark_card(suite, rep)          # BenchmarkCard JSON interoperable

# 2) Safety continua: JSR, refusal, toxicidad e incidentes
safety = SafetySuite()                       # corpus red-team embebido
reporte = safety.run(mi_pipeline)            # gate propio + incidentes con TTD

# 3) Juez calibrado + leaderboard Elo
juez = CalibratedJudge(mi_backend)
cal = calibrar_juez(juez, muestras_con_q_humano)   # MAE, sesgo, Pearson, por dominio
torneo = TorneoElo(); torneo.partida("modeloA", "modeloB", "A")

# 4) QA del codigo generado: mutation + fuzz
rep_mut = run_mutation(src, "mi_funcion", mis_tests)          # mutation score
rep_fuzz = fuzz_funcion(mi_fn, generador, propiedad, n=200, seed=0, guardar_en="corpus.json")

# 5) Evidence pack firmado + alertas + rollback
pack = evidence_pack(run_dict, key=None)     # firma con HARNESS_SIGNING_KEY (env)
ok = verificar_pack(pack)
alertas = evaluar_alertas({"toxicity_rate": [...], "q_media": [...]})

# 6) Multi-backend real: anthropic / vertex / ollama local con failover
fo = failover_desde_env()                    # detecta proveedores por env
texto = fo.complete("hola")                  # reintenta en orden hasta responder
sel = SelectorModelos("calidad"); sel.registrar("flash", costo_per_1k=0.0001, p95_s=0.2, q_media=0.7)
```

## 10. Memoria administrada en 3 capas (2 min)

```python
from harness_candy import GestorMemoria

g = GestorMemoria("memoria")                     # carpeta del repo
# cache: momentanea, con TTL (no va a git)
g.guardar_cache("borrador", "estado del build", "compilando", ttl=600)
# chat: dentro del proyecto, solo lo relevante (relevancia >= 0.5)
g.guardar_chat("Harness-Candy", "decision", "usamos BM25 local", "sin dependencias", relevancia=0.9)
# ecosistema: global, entre todos los proyectos
g.guardar_ecosistema("patron", "max 300 palabras por entrada", "tipo+idea+explicacion", proyecto="Harness-Candy")

for score, e in g.buscar("chat", "por que BM25?", proyecto="Harness-Candy"):
    print(score, e.tipo, e.idea)
g.purgar_cache()                                 # borra lo expirado
print(g.stats())                                 # entradas y palabras por capa
```

```bash
scripts/memoria guardar-chat Harness-Candy decision "usamos BM25 local" "sin dependencias" --relevancia 0.9
scripts/memoria buscar ecosistema "300 palabras"
scripts/memoria purgar && scripts/memoria stats
```

Regla: **ninguna entrada es un volcado** — `tipo + idea + explicacion`, máximo 300 palabras; lo que se pasa se rechaza.

## 11. Dónde seguir

- `docs/API.md` — referencia completa (módulos, CLI, HTTP, esquemas).
- `docs/OPERACION.md` — runbooks (incidentes, rollback, caché, FinOps...).
- `docs/CHECKLIST_V3_ESTADO.md` — estado ítem por ítem del checklist v3.
- `docs/adr/` — decisiones (ADR-001..005) con el paper como fundamento.
- `docs/ROADMAP.md` — fases 0–4; `docs/INDEPENDENCIA.md` — ruta a Rust medida.
