# ADR-003: Modelo de aislamiento de ejecución

- Estado: **Aceptado**
- Fecha: 2026-11-02

## Contexto
El código generado por agentes (XEV) debe ejecutarse aislado: el repositorio oficial
de Harness² advierte que su ejecutor **no restringe la red por defecto**, y el diseño
combinado exige sandbox efímero + red restringida + credenciales fuera del proceso.

## Decisión
`sandbox.run_sandboxed`: subproceso con (1) directorio de trabajo efímero que se
borra, (2) timeout estricto, (3) entorno mínimo sin credenciales heredadas,
(4) si el SO lo permite, namespace de usuario+red propio (`unshare -rn --kill-child`)
→ `network_isolated=True`; si no, se marca `False` para auditoría. XEV además tiene
allowlist de herramientas/comandos (`PermissionError` fuera de ella).

## Alternativas
- Contenedor (Docker/gVisor): más fuerte, pero requiere daemon y no está disponible en
  CI/entornos restringidos → pendiente como mejora (ver docs/INDEPENDENCIA.md).
- WASM/VM: overhead y ecosistema; no necesario para comandos de escaneo.
- Solo proceso: insuficiente (el paper y el diseño exigen red restringida).

## Consecuencias
- En CI/sandbox sin `unshare`, el test de red aislada se salta y el flag queda en falso
  (auditado); objetivo: 0 fallos de aislamiento por versión cuando el SO lo permita.
