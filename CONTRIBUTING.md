# Contribuir a Harness-Candy

Gracias por querer mejorar el proyecto. Este repo implementa el diseño
combinado **Ely–Cowork ADK+Harness²** (ver `README.md` y `docs/DISENO_COMBINADO.md`).

## Flujo de trabajo

1. Abre un issue describiendo el cambio (bug, mejora, propuesta). Para cambios
   de diseño, usa una plantilla RFC (ver `docs/adr/` para el formato ADR).
2. Crea una rama `feat/…`, `fix/…`, `docs/…`, `test/…`, `refactor/…`, `perf/…`.
3. Commits con convención **Conventional Commits**: `tipo(alcance): descripción`
   (ej.: `fix(dag): no reintentar tareas canceladas`).
4. Abre un PR con: enlace al issue, resumen, evidencia de tests
   (`python -m unittest discover -s tests`) y nota de *breaking change* si aplica.

## Calidad mínima (se verifica en CI)

- `python -m unittest discover -s tests` en verde (añade tests para todo cambio).
- `python -m compileall -q src` sin errores.
- Sin dependencias nuevas fuera de la librería estándar (el núcleo es stdlib-only;
  las extras van en `pyproject.toml` como opcionales, p. ej. `adk`).
- **Nunca** añadas claves API, tokens o datos personales al repo
  (`git grep` lo comprueba en CI; ver `SECURITY.md`).

## Estilo

- Español en documentación y mensajes de cara al usuario; inglés en identificadores.
- Type hints en firmas públicas. Funciones pequeñas; sin prints de depuración.
- Los tests van en `tests/test_*.py` (unittest, sin dependencias externas).

## Revisión

- Un maintainer de cada ruta (ver `CODEOWNERS`) debe aprobar.
- Cambios de seguridad o de contratos (protocolos/esquemas) requieren revisión
  obligatoria del área de seguridad.

## Código de conducta

Sé respetuoso y constructivo. Reporta comportamientos inaceptables según `SECURITY.md`.
