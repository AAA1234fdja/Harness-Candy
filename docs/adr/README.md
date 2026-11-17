# ADRs — Architecture Decision Records

Decisiones arquitectónicas del proyecto, con la plantilla del checklist v3 §24.1.
Cada ADR indica **Estado**, contexto, decisión, alternativas, consecuencias y métricas.

| ADR | Tema | Estado |
|---|---|---|
| [ADR-001](ADR-001-harness2-propio-vs-externo.md) | Nuestro adaptador Harness² propio vs. usar el repo oficial `google-research/harness2` | Aceptado |
| [ADR-002](ADR-002-adk-externo-opcional.md) | ADK externo (google-adk) como capa opcional vs. orquestación propia | Aceptado |
| [ADR-003](ADR-003-aislamiento-ejecucion.md) | Aislamiento de ejecución: subproceso + namespace de red (sandbox) | Aceptado |
| [ADR-004](ADR-004-lenguaje-python-stdlib.md) | Lenguaje/runtime: Python ≥ 3.10, solo librería estándar en el núcleo | Aceptado |
| [ADR-005](ADR-005-persistencia-local-json.md) | Persistencia: JSON local (trazas, memoria, store) sin dependencias | Aceptado |

Referencia externa clave: Xu et al., *"Harness 2: Recursive Agent Harnessing for an
Open World"*, arXiv:2610.14224 (2026-10-12), Google Cloud AI Research — describe el
ciclo contrastivo Propose–Probe–Compose sin ground-truth, la recursión a nivel de
tarea (budget k) y a nivel de harnessing (biblioteca de experiencia), con ganancias
medidas en WorkBuddy-Bench (+11.5), JobBench (+4.5) y LAB (+11.8 pp). Nuestro
diseño combinado (Ely–Cowork) añade la capa de calidad (Q, regla estadística,
seguridad, trazabilidad) sobre ese núcleo. Limitación citada por los autores (ap. F):
el refinamiento recursivo **añade coste de inferencia**; el paralelismo reduce
latencia, no coste — por eso nuestro `Budget` (ec. 3) existe.
