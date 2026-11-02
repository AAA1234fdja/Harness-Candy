# ADR-001: Adaptador Harness² propio vs. usar el repo oficial google-research/harness2

- Estado: **Aceptado**
- Fecha: 2026-11-02
- Owners: @AAA1234fdja
- Revisores: plataforma, seguridad

## Contexto
Harness2 (Xu et al., arXiv:2610.14224) es un proyecto de investigación de Google
(Apache 2.0, sin soporte oficial) que mejora el harness de un agente con un ciclo
contrastivo Propose–Probe–Compose sin ground-truth. El diseño combinado Ely–Cowork
necesita ese ciclo **aislado y reemplazable**, con una señal de evaluación medible
(Q) que el proyecto oficial no incorpora, y con trazabilidad completa (JSONL).

## Decisión
Implementamos nuestro propio **adaptador** (`harness.Harness2Adapter`) que envuelve
el ciclo Propose–Probe–Compose (misma idea del paper: referencia + 2k candidatos ×
m corridas, composición por evidencia de comportamiento) y le añadimos la capa de
calidad del diseño combinado: score Q (ec. 1), regla estadística (ec. 2), Mann–Whitney
alternativo, presupuesto (ec. 3), store con evidencia y trazabilidad JSONL.
El adaptador es una interfaz (`Proposer` protocol + `Harness2Adapter`); si el repo
oficial madura, se puede enchufar detrás sin tocar agentes ni orquestación.

## Alternativas consideradas
- **Usar google-research/harness2 directamente**: pros, código oficial con benchmarks;
  contras, sin soporte, sin capa de calidad/Q/trazabilidad propia, acoplamiento a su API.
- **No usar Harness²**: descarta la mejora medible del agente por tarea (el paper
  muestra ganancias de hasta +11.5 puntos en WorkBuddy-Bench).

## Consecuencias
- Positivas: control total del contrato interno, reemplazable, testeable sin red
  (`ScriptedBackend`), con ablación A/B/C/D para justificar su costo.
- Negativas: mantenemos código propio de P-P-C; el paper advierte (ap. F) que la
  recursión añade coste de inferencia → mitigado con `Budget` y reutilización (`r`).

## Métricas de éxito
- La ablación muestra C > B por encima de δ en tareas propias (`examples/demo_ablation.py`);
  si no, se descarta el adaptador para esa tarea (regla del diseño combinado §12).
