# Política de seguridad

## Reportar vulnerabilidades

Reporta vulnerabilidades de forma privada a los mantenedores (ver `CODEOWNERS`)
por el canal interno acordado o abriendo un *security advisory* privado en GitHub.
No abras issues públicos con detalles de una vulnerabilidad. Tiempo esperado de
respuesta inicial: 72 h. Te pediremos un PoC mínimo si falta.

## Reglas duras del proyecto

- **Nunca** cometas claves API, tokens, credenciales o PII** en el repo.
  CI lo verifica (`git grep` de patrones `sk-…`, `AKIA…`, claves privadas).
  Las claves viven solo en variables de entorno (p. ej. `XKIRO_API_KEY`).
- El código generado por agentes corre **siempre** en sandbox
  (`sandbox.run_sandboxed`): directorio efímero, timeout, entorno mínimo sin
  credenciales heredadas y, si el SO lo permite, namespace de red propio
  (`unshare -rn`).
- Las puertas de entrada/salida (`security.SecurityGate`) bloquean inyección de
  instrucciones y fugan PII/secretos en las salidas (objetivo: fuga de PII = 0,
  seguridad ≥ 0.98, falsos positivos en prompts benignos < 5 %).
- Harness² es un proyecto de investigación externo (Apache 2.0, sin soporte
  oficial): está **aislado tras el adaptador** (`Harness2Adapter`) para poder
  reemplazarlo sin tocar el resto del sistema.

## Modelo de amenazas (resumen)

Ver `docs/DISENO_COMBINADO.md` §13. Amenazas principales: prompt injection en
entradas, ejecución de código generado, exfiltración de secretos/PII en salidas,
coste descontrolado de inferencia (mitigado con `Budget` ec. 3), sesgo del juez
LLM (mitigado con juez independiente + calibración, `judge.py`).

## Dependencias

El núcleo no tiene dependencias externas (solo stdlib de Python ≥ 3.10), lo que
minimiza la superficie de SCA. Las opcionales (`google-adk`) se auditan antes de
activarse. Ejecuta el escaneo de dependencias de tu organización sobre
`pyproject.toml` antes de cada release.
