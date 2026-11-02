# Roadmap por fases (checklist v3 §23, aterrizado a este repo)

## Fase 0 — Descubrimiento ✅ (hecha)
- ADRs aprobados: `docs/adr/ADR-001..005`.
- Alcance y no-objetivos: README "Limitaciones" + `docs/DISENO_COMBINADO.md`.
- Riesgos: §22 del checklist v3 → mapeados en `docs/CHECKLIST_V3_ESTADO.md`.
- Evidencia externa: paper Harness2 (arXiv:2610.14224) citado en `docs/adr/README.md`.

## Fase 1 — MVP ✅ (hecho en este repo)
- Núcleo de orquestación (DAG paralelo, reintentos, cancelación, human-review).
- Adaptador Harness² (P-P-C) con calidad medible (Q, ec. 2, presupuesto ec. 3).
- Protocolos tipados versionados; seguridad (sandbox, inyección, PII); trazabilidad JSONL.
- CI verde: `.github/workflows/ci.yml` (lint+secretos, tests 3.10–3.12, contrato, smoke de ejemplos).
- Docs de inicio rápido: README + `examples/` (4 ejemplos ejecutables).

## Fase 2 — Beta ⚠️ (en curso)
- Evaluación con golden set en CI: existe `ablation.py` + tests; pendiente: golden set
  propio por dominio y umbrales mínimos en CI (job `contract` ampliado).
- Memoria de largo plazo con búsqueda semántica: `KnowledgeMemory` con `embedder`
  inyectable; pendiente: backend real (vector DB) en despliegue.
- Multi-agente con handoff: YEV/ISA/ELY ya son roles separados; pendiente: handoff
  explícito entre agentes de tarea con presupuestos independientes.
- Seguridad revisada: `SECURITY.md` + modelo de amenazas; pendiente: revisión externa.

## Fase 3 — GA ⚠️ (pendiente organizacional)
- SLOs/alertas, dashboards, presupuesto FinOps, soporte/on-call, comunicación de GA:
  son responsabilidad de la organización (ver 🏢 en `docs/CHECKLIST_V3_ESTADO.md`).

## Fase 4 — Post-GA 🟢 (continuo)
- Migración selectiva a Rust con mediciones (`docs/INDEPENDENCIA.md` + bench).
- Marketplace interno de plugins/skills; mejoras 🟢 del checklist v3.
- Curva k medida con datos propios (`ablation.k_curve`) para fijar k por tarea.
