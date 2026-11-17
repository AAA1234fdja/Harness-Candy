# Independencia tecnológica (sección 9/11 del diseño combinado)

Objetivo: reducir la dependencia de terceros sin interrumpir el desarrollo.
La regla operativa: las **interfaces internas estables** (los protocolos tipados
`yev`/`zev`/`xev`/`wev` en `protocols.py`) son el contrato; cualquier componente
puede sustituirse sin tocar a los demás.

## Dependencias críticas identificadas

| Dependencia | Dónde se usa | Riesgo | Mitigación implementada |
|---|---|---|---|
| Google ADK (`google-adk`) | `adk_bridge.build_adk_flow` (opcional, extra `adk`) | framework maduro pero externo; el resto del sistema NO depende de él | el núcleo (DAG, memoria, calidad) es stdlib puro; ADK solo entra como capa de orquestación opcional |
| Harness² (proyecto de investigación Google, Apache 2.0, sin soporte oficial) | `harness.Harness2Adapter` | puede cambiar o desaparecer | **aislado tras el adaptador**: `Proposer`/`Harness2Adapter` son interfaces propias; se reemplaza sin tocar agentes ni ADK |
| Proveedor LLM (xkiro u otro, API OpenAI-compatible) | `backends.OpenAICompatibleBackend` | cambio de API/precios/disponibilidad | `LLMBackend` protocol: un backend por proveedor; el pool elige modelo/clave por rol; `ScriptedBackend` permite operar sin red |
| `unshare`/namespaces del SO | `sandbox.run_sandboxed` | no disponible en todos los entornos | best-effort: si no hay `unshare`, se ejecuta con entorno mínimo y se registra `network_isolated=False` para auditoría; pendiente: gVisor/Firecracker |
| LiteLLM (mencionado en el PDF) | no requerido | — | el backend propio cubre el caso OpenAI-compatible sin añadir dependencias |

## Lista priorizada para migrar a Rust (hipótesis del PDF §11 — confirmar con mediciones)

1. **YEV / planificador y concurrencia** (`dag.py` + `pool.py`): hot path de coordinación; Rust da concurrencia y control de recursos sin GIL.
2. **Almacén de variables** (`memory.VariableMemory`): versiones, permisos y sincronización concurrentes.
3. **Ejecutor sandbox** (`sandbox.py`): lanzar procesos aislados con límites es crítico para seguridad y se beneficia de memoria segura.

Mediciones de partida: `python examples/bench_escalabilidad.py 24` reporta
tiempo total y tiempo/tarea del pipeline completo (en la última corrida: ~5.5 s
para 25 tareas con concurrencia 8, dominado por lanzar procesos `py_compile` en
sandbox — precisamente el candidato #3). ⚠️ pendiente: implementar las versiones
Rust y comparar; el PDF exige decidir solo con mediciones.

## Reglas de la migración

1. Estabilizar la infraestructura actual (hecho: 104 tests verdes).
2. Interfaces internas estables primero (hecho: protocolos tipados versionados).
3. Sustituir componente por componente detrás de la interfaz (el adaptador de
   Harness² es el modelo a seguir).
4. La interfaz y el resto del sistema conservan su tecnología salvo que haya una
   razón técnica medida para cambiarla.
