# Operación y runbooks (checklist v3 §11.3, §18.2)

Cómo operar Harness-Candy día a día. Pensado para correr local o en un
contenedor; los SLOs/canales formales son responsabilidad de la organización
(ver 🏢 en `docs/CHECKLIST_V3_ESTADO.md`).

## Puesta en marcha

```bash
pip install -e .                 # núcleo sin dependencias
harness-candy serve --port 8000  # API REST local (bind 0.0.0.0 por defecto)
python -m unittest discover -s tests -v   # 264 tests
```

## Runbooks

### 1. Ejecutar una corrida y ver su reporte
```bash
harness-candy run --objetivo "informe de seguridad de src/" --input root=src \
    --out /tmp/run.json --report /tmp/run.html
# o vía HTTP:  curl -X POST localhost:8000/runs -d '{"objetivo":"...","inputs":{"root":"src"}}'
# reporte:     curl localhost:8000/runs/<id>/report.html
```

### 2. Correr una suite de tareas (DAG explícito)
```bash
harness-candy suite list --file examples/suites/demo.json
harness-candy suite run --file examples/suites/demo.json --report out.html
python examples/demo_suite.py
```

### 3. Golden set en CI (puerta de regresión)
```bash
harness-candy golden --file examples/golden/security_scan.json   # exit 2 si pass_rate < min
python examples/demo_golden.py
```

### 4. Alertas de presupuesto (FinOps)
En código: `BudgetMonitor(budget, sink)` emite al cruzar 50/80/100% del
presupuesto (una vez cada umbral). Sumideros: `LogSink` (stderr),
`WebhookSink(url)` (POST JSON, nunca envía claves), `MultiSink`.
El bus de eventos publica las alertas como `alert` (ver `/events` SSE).

### 5. Cache de respuestas LLM
```bash
harness-candy cache --stats          # hit rate, entradas, TTL
harness-candy cache --clear          # limpia .harness_cache
```
En código: `CachedBackend(OpenAICompatibleBackend())`. La clave es
SHA-256 de {model, system, prompt, seed}: nunca se cachea la API key.

### 6. Failover de proveedor (R11)
```python
from harness_candy.failover import FailoverBackend
from harness_candy.backends import OpenAICompatibleBackend
backend = FailoverBackend([OpenAICompatibleBackend(), mi_backend_local])
# si el primario falla, usa el siguiente; cada intento queda en backend.attempts
```

### 7. Incidente de seguridad (sospecha de clave expuesta)
1. **Rotar la clave inmediatamente** en el proveedor (no esperar).
2. `git grep -n -E "sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY" -- src` → si aparece, revocar y purgar del historial (BFG/git filter-repo) y notificar según `SECURITY.md`.
3. Revisar trazas: `grep -l "sk-\|AKIA" traces/*.jsonl` (la puerta de salida de WEV bloquea PII/secretos, pero auditar igual).
4. Abrir postmortem con `docs/templates/POSTMORTEM.md`.

### 8. Regresión de calidad detectada (ELY/WEV)
- Ver la corrida: `GET /runs/{id}` y su `report.html`; la traza JSONL
  (`traces/<run_id>.jsonl`) tiene run_id/model/seed/harness/phase/q por corrida.
- `RegressionGuard` alerta si Q cae > 2 pp respecto a la baseline.
- Reproducir 100%: misma `seed` → mismas corridas (test de reproducción en `test_extras.py`).
- Si el gate del golden falla en CI: `harness-candy golden --file ...` local y
  comparar `pass_rate` contra `min_pass_rate`.

### 9. Rollback
- El harness por defecto `h0` siempre se conserva (ec. 2: si ningún candidato
  supera el ruido, se adopta h0) → rollback = no adoptar.
- Corridas: `DELETE /runs/{id}` o borrar `runs/<id>.json`.
- Versión: `CHANGELOG.md` + tags SemVer; volver a la versión anterior con
  `pip install harness-candy==X.Y.Z`.

### 10. Limpieza
```bash
harness-candy cache --clear
rm -rf traces/*.jsonl runs_demo/   # según retención acordada (🏢 org)
```

### 11. Panel web y métricas
```bash
harness-candy serve --port 8000
# abrir http://localhost:8000/  -> panel con corridas, lanzador y eventos SSE en vivo
curl localhost:8000/metrics      # formato Prometheus (raspable)
```

### 12. Jobs programados (scheduler de suites)
```bash
curl -X POST localhost:8000/jobs -d '{"name":"scan-diario","suite_path":"examples/suites/demo.json","interval_s":3600}'
curl localhost:8000/jobs
curl -X DELETE localhost:8000/jobs/<job_id>
```

### 13. Proteger el servidor con token (opcional)
```bash
export HARNESS_API_TOKEN="$(openssl rand -hex 32)"   # solo en el entorno, nunca en el repo
harness-candy serve --port 8000
# todas las rutas salvo /health exigen:  Authorization: Bearer $HARNESS_API_TOKEN
```

### 14. Multi-tenant (namespaces por proyecto)
```python
from harness_candy.tenancy import TenantManager
tm = TenantManager("data")
store = tm.store("proyecto-a")        # aislado en data/runs/proyecto-a/
trace_dir = tm.trace_dir("proyecto-a")  # data/taces/proyecto-a/
```

### 15. Exportar métricas a Prometheus / OTLP
```python
from harness_candy.metrics_export import prometheus_text, OtlpExporter, otlp_spans
prometheus_text(run["metrics"], labels={"run_id": run["run_id"]})   # endpoint /metrics
OtlpExporter("http://collector:4318/v1/traces").export(trace_entries)  # mejor esfuerzo
```

## Métricas que ver
`RunResult.metrics` (y `/runs/{id}`): tasa de requisitos, pruebas
superadas/total, defectos por severidad, tiempo, costo de adaptación,
tokens, trabajo duplicado, mantenibilidad, escaladas/human_review/canceladas.
**No** se miden líneas de código generadas (el diseño lo desaconseja).
