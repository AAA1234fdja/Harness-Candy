# ADR-004: Lenguaje y runtime — Python ≥ 3.10, núcleo solo con librería estándar

- Estado: **Aceptado**
- Fecha: 2026-11-02

## Contexto
El diseño combinado menciona ADK (Python code-first) y una ruta futura a Rust para
componentes críticos. El repo debe poder testearse y ejecutarse sin instalar nada.

## Decisión
Python ≥ 3.10, **cero dependencias obligatorias** en el núcleo (`pyproject.toml`
declara `dependencies = []`). Tests con `unittest` (stdlib). Las integraciones
opcionales viven en extras (`adk`, `test`). La migración a Rust es selectiva y solo
con mediciones (docs/INDEPENDENCIA.md): candidatos = YEV/planificador, almacén de
variables, ejecutor sandbox.

## Alternativas
- Node/TS o Go para el núcleo: el ecosistema ADK es Python-first; no aporta beneficio
  medido aquí.
- Rust desde el inicio: costo de desarrollo alto sin mediciones que lo justifiquen.

## Consecuencias
- CI corre en cualquier Python 3.10–3.12 sin `pip install` de terceros.
- La ruta a Rust queda como hipótesis a validar con `bench_escalabilidad.py`.
