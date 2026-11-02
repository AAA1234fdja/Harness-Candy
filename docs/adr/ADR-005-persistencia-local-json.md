# ADR-005: Persistencia — JSON local sin dependencias, interfaces para backends

- Estado: **Aceptado**
- Fecha: 2026-11-02

## Contexto
Se necesita persistencia de trazas (JSONL), memoria de conocimiento, store de
harness y métricas, sin atar el núcleo a una base de datos externa.

## Decisión
- Trazas: JSONL append-only (`quality.TraceLog`) — auditable, reproducible, diff-friendly.
- Conocimiento: JSON (`memory.KnowledgeMemory`, con `embedder` inyectable para búsqueda
  semántica futura).
- Harness validados: `HarnessStore` (memoria; persistencia opcional a JSON).
- Variables de sesión: en memoria (`VariableMemory`).
Todas las rutas de persistencia son inyectables (path/None), así que un despliegue
real puede cambiar a Postgres/Redis/S3 sin tocar la lógica (interfaces estables =
los protocolos tipados + estas clases).

## Alternativas
- SQLite/Postgres desde el inicio: innecesario para el núcleo; queda como backend
  enchufable detrás de las mismas interfaces.

## Consecuencias
- Cero dependencias; backups = copiar archivos JSON/JSONL; retención configurable por
  borrado de archivos (ver §12 del checklist v3 — política organizacional).
