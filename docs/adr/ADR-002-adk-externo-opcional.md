# ADR-002: ADK externo (google-adk) como capa opcional vs. orquestación propia

- Estado: **Aceptado**
- Fecha: 2026-11-02

## Contexto
El diseño combinado usa ADK para la estructura (grafo de agentes, session.state,
ParallelAgent/SequentialAgent/LoopAgent) y nuestro sistema para la calidad. No
queremos depender de google-adk para poder ejecutar y testear sin instalación.

## Decisión
El núcleo es **independiente de ADK** (stdlib puro): `dag.TaskDAG`/`DAGExecutor`
ejecutan el paralelismo, `memory.VariableMemory` es el análogo de `session.state`.
`adk_bridge.build_adk_flow` construye los agentes reales de `google.adk` **solo si**
está instalado (extra `pip install -e .[adk]`); si no, `build_flow_spec` da la
especificación determinista. Los agentes son model-agnostic (`LLMBackend`;
`backends.OpenAICompatibleBackend` para xkiro/LiteLLM sin cambiar código).

## Alternativas
- **Solo google-adk**: más integración con el ecosistema Google, pero sin ADK no se
  puede ni testear ni ejecutar;LAYER de acoplamiento innecesario para el núcleo.
- **Solo propio**: perdemos despliegue A2A/Vertex; por eso ADK queda como capa opcional.

## Consecuencias
- Tests y demos corren sin dependencias externas; con ADK se obtiene despliegue real.
- Pendiente: envolver nodos con reintentos en `LoopAgent` real cuando ADK esté presente.
