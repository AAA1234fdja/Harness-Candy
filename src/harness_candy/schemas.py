"""Esquemas JSON Schema publicos de los contratos del sistema (checklist v3 §7.1).

Publica, como datos, el contrato de cada mensaje de protocolo y de las
estructuras de configuracion/resultado. El validador es propio (stdlib),
para no depender de la libreria ``jsonschema``: soporta el subconjunto
documentado abajo.

Subconjunto soportado por ``validate_schema``:
    type:        "object" | "array" | "string" | "number" | "integer" |
                 "boolean" | "null"  (o lista de ellos)
    properties:  dict campo -> subesquema        (con required: list[str])
    additionalProperties: bool | subesquema
    items:       subesquema para cada elemento
    enum:        list de valores permitidos
    const:       valor unico permitido
    minimum / maximum / exclusiveMinimum / exclusiveMaximum
    minLength / maxLength / pattern (regex)
    minItems / maxItems / uniqueItems
    anyOf / oneOf / allOf: list de subesquemas
    $ref:        "#/definitions/Nombre" (solo definiciones internas)

Uso:
    from harness_candy.schemas import validate_named, schema_json
    validate_named("task", {...})     # lanza SchemaError si no cumple
    print(schema_json("task"))        # el esquema como texto JSON
"""
from __future__ import annotations

import json
import re
from typing import Any

SCHEMA_VERSION = "1.0.0"


class SchemaError(ValueError):
    """El dato no cumple el esquema publicado."""


# ---------------------------------------------------------------------------
# Definiciones compartidas
# ---------------------------------------------------------------------------

_DEFINITIONS: dict[str, dict] = {
    "Envelope": {
        "type": "object",
        "required": ["protocol", "task_id", "origen", "destino"],
        "additionalProperties": True,
        "properties": {
            "protocol": {"enum": ["yev", "zev", "xev", "wev"]},
            "version": {"type": "string"},
            "task_id": {"type": "string", "minLength": 1},
            "origen": {"type": "string", "minLength": 1},
            "destino": {"type": "string", "minLength": 1},
            "msg_id": {"type": "string"},
            "timestamp": {"type": "number"},
        },
    },
    "Hallazgo": {
        "type": "object",
        "required": ["herramienta", "severidad", "detalle"],
        "additionalProperties": False,
        "properties": {
            "herramienta": {"type": "string", "minLength": 1},
            "severidad": {"enum": ["baja", "media", "alta", "critica"]},
            "detalle": {"type": "string"},
        },
    },
    "Criterion": {
        "type": "object",
        "required": ["id"],
        "additionalProperties": True,
        "properties": {
            "id": {"type": "string", "minLength": 1},
            "descripcion": {"type": "string"},
            "peso": {"type": "number", "minimum": 0.0},
        },
    },
}


def _msg_schema(proto: str, extra_required: list[str], extra_props: dict) -> dict:
    return {
        "type": "object",
        "required": ["protocol"] + extra_required,
        "additionalProperties": True,
        "properties": {
            "protocol": {"const": proto},
            **{k: {"$ref": "#/definitions/Envelope"} for k in []},  # envelope inline abajo
            "task_id": {"type": "string", "minLength": 1},
            "origen": {"type": "string", "minLength": 1},
            "destino": {"type": "string", "minLength": 1},
            **extra_props,
        },
    }


SCHEMAS: dict[str, dict] = {
    "schema_version": {"type": "string", "const": SCHEMA_VERSION},
    "envelope": {"$ref": "#/definitions/Envelope"},
    "hallazgo": {"$ref": "#/definitions/Hallazgo"},
    "criterion": {"$ref": "#/definitions/Criterion"},
    "yev": _msg_schema(
        "yev",
        ["depende_de", "instruccion", "agente_destino"],
        {
            "depende_de": {"type": "array", "items": {"type": "string"}},
            "instruccion": {"type": "string", "minLength": 1},
            "agente_destino": {"type": "string", "minLength": 1},
            "modelo": {"type": ["string", "null"]},
            "clave": {"type": ["string", "null"]},
            "presupuesto": {"type": "object"},
            "criterios_aceptacion": {"type": "array", "items": {"type": "string"}},
        },
    ),
    "zev": _msg_schema(
        "zev",
        ["consulta", "nivel_confianza", "fragmentos"],
        {
            "consulta": {"type": "string", "minLength": 1},
            "fuentes": {"type": "array", "items": {"type": "string"}},
            "fragmentos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["contenido", "procedencia"],
                    "properties": {
                        "contenido": {"type": "string"},
                        "procedencia": {"type": "string"},
                    },
                },
            },
            "nivel_confianza": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
    ),
    "xev": _msg_schema(
        "xev",
        ["instruccion"],
        {
            "instruccion": {"type": "string", "minLength": 1},
            "entradas": {"type": "object"},
            "herramienta": {"type": "string"},
            "artefacto": {},
            "registro_ejecucion": {"type": "object"},
        },
    ),
    "wev": _msg_schema(
        "wev",
        ["artefacto_id", "veredicto"],
        {
            "artefacto_id": {"type": "string", "minLength": 1},
            "checks": {
                "type": "object",
                "additionalProperties": {"type": "boolean"},
            },
            "veredicto": {"enum": ["aprobado", "rechazado"]},
            "hallazgos": {"type": "array", "items": {"$ref": "#/definitions/Hallazgo"}},
            "accion": {"type": "string"},
        },
    ),
    "task": {
        "type": "object",
        "required": ["task_id", "kind", "instruction"],
        "additionalProperties": True,
        "properties": {
            "task_id": {"type": "string", "minLength": 1},
            "kind": {"type": "string", "minLength": 1},
            "instruction": {"type": "string", "minLength": 1},
            "inputs": {"type": "object"},
            "criterios": {"type": "array", "items": {"$ref": "#/definitions/Criterion"}},
            "max_reintentos": {"type": "integer", "minimum": 0},
            "meta": {"type": "object"},
        },
    },
    "harness": {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "version": {"type": "string"},
            "system_prompt": {"type": "string"},
            "guardrails": {"type": "array", "items": {"type": "string"}},
            "memory": {"type": "object"},
            "tool_guidance": {"type": "string"},
            "subagents": {"type": "array", "items": {"type": "string"}},
            "skills": {"type": "array", "items": {"type": "string"}},
            "scripts": {"type": "array", "items": {"type": "string"}},
            "plugins": {"type": "array", "items": {"type": "string"}},
        },
    },
    "budget": {
        "type": "object",
        "required": ["total"],
        "additionalProperties": True,
        "properties": {
            "total": {"type": "number", "exclusiveMinimum": 0},
            "beta": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "k": {"type": "integer", "minimum": 0},
            "m": {"type": "integer", "minimum": 1},
            "spent_adapt": {"type": "number", "minimum": 0.0},
        },
    },
    "pool_entry": {
        "type": "object",
        "required": ["alias", "model", "secret_env"],
        "additionalProperties": True,
        "properties": {
            "alias": {"type": "string", "minLength": 1},
            "model": {"type": "string", "minLength": 1},
            "secret_env": {"type": "string", "minLength": 1, "pattern": "^[A-Z_][A-Z0-9_]*$"},
            "cost_per_1k": {"type": "number", "minimum": 0.0},
            "speed": {"type": "number", "exclusiveMinimum": 0},
            "capabilities": {"type": "array", "items": {"type": "string"}},
            "roles": {"type": "array", "items": {"type": "string"}},
            "quota_remaining": {"type": "number"},
            "tag": {"enum": ["light", "power"]},
        },
    },
    "trace_event": {
        "type": "object",
        "required": ["ts", "run_id", "task_id", "model", "seed", "harness", "phase", "q"],
        "additionalProperties": True,
        "properties": {
            "ts": {"type": "number"},
            "run_id": {"type": "string"},
            "task_id": {"type": "string"},
            "model": {"type": "string"},
            "seed": {"type": "integer"},
            "harness": {"type": "string"},
            "phase": {"type": "string"},
            "q": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "verdict": {"type": "string"},
            "extra": {"type": "object"},
        },
    },
    "run_result": {
        "type": "object",
        "required": ["run_id", "objetivo", "dag_results", "duracion"],
        "additionalProperties": True,
        "properties": {
            "run_id": {"type": "string", "pattern": "^run-[0-9a-f]{12}$"},
            "objetivo": {"type": "string"},
            "plan": {"type": "object"},
            "dag_results": {"type": "object"},
            "wev_reports": {"type": "object"},
            "qs": {"type": "object"},
            "ely_audit": {"type": "object"},
            "costo_adaptacion": {"type": "number"},
            "trace_path": {"type": "string"},
            "duracion": {"type": "number", "minimum": 0.0},
            "metrics": {"type": "object"},
        },
    },
    "suite": {
        "type": "object",
        "required": ["name", "tasks"],
        "additionalProperties": True,
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "seed": {"type": "integer"},
            "max_concurrency": {"type": "integer", "minimum": 1},
            "budget": {"$ref": "#budget"},
            "tasks": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["task_id", "kind", "instruction"],
                    "properties": {
                        "task_id": {"type": "string", "minLength": 1},
                        "kind": {"type": "string", "minLength": 1},
                        "instruction": {"type": "string"},
                        "deps": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
                        "agent": {"type": "string"},
                        "inputs": {"type": "object"},
                        "criterios": {"type": "array", "items": {"$ref": "#/definitions/Criterion"}},
                        "max_reintentos": {"type": "integer", "minimum": 0},
                        "herramienta": {"type": "string"},
                    },
                },
            },
        },
    },
    "golden_set": {
        "type": "object",
        "required": ["name", "cases"],
        "additionalProperties": True,
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "min_pass_rate": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "cases": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["id", "task", "expect"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "task": {"$ref": "#task"},
                        "expect": {
                            "type": "object",
                            "properties": {
                                "status": {"type": "string"},
                                "q_min": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                                "veredicto": {"enum": ["aprobado", "rechazado"]},
                                "artifact_contains": {"type": "array", "items": {"type": "string"}},
                                "artifact_json_keys": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
            },
        },
    },
    "tool_spec": {
        "type": "object",
        "required": ["name", "description", "parameters", "permission"],
        "additionalProperties": True,
        "properties": {
            "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,63}$"},
            "description": {"type": "string"},
            "parameters": {"type": "object"},
            "permission": {"enum": ["read", "write", "exec"]},
            "timeout": {"type": "number", "exclusiveMinimum": 0},
            "rate_limit": {"type": "integer", "minimum": 0},
            "rate_window_s": {"type": "number", "exclusiveMinimum": 0},
        },
    },
}

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


# Raiz global para resolver $ref: "#/definitions/X" -> definiciones internas,
# "#nombre" -> esquema publicado con ese nombre (p. ej. "#task").
_GLOBAL_ROOT: dict[str, Any] = {"definitions": _DEFINITIONS, **SCHEMAS}


def _resolve_ref(ref: str, root: dict) -> dict:
    if ref.startswith("#/"):
        node: Any = root
        for part in ref[2:].split("/"):
            node = node[part]
        return node
    if ref.startswith("#") and ref[1:] in root:  # "#task" -> esquema global
        return root[ref[1:]]
    raise SchemaError(f"$ref no soportado: {ref}")


def validate_schema(instance: Any, schema: dict, path: str = "$", root: dict | None = None) -> None:
    """Valida ``instance`` contra ``schema``; lanza SchemaError con la ruta."""
    root = root if root is not None else _GLOBAL_ROOT
    if "$ref" in schema:
        validate_schema(instance, _resolve_ref(schema["$ref"], root), path, root)
        return
    if "const" in schema and instance != schema["const"]:
        raise SchemaError(f"{path}: se esperaba const {schema['const']!r}, llego {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaError(f"{path}: {instance!r} no esta en enum {schema['enum']!r}")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        ok = False
        for t in types:
            py = _TYPES[t]
            if t == "integer" and isinstance(instance, bool):
                continue
            if t == "number" and isinstance(instance, bool):
                continue
            if isinstance(instance, py) and not (t in ("integer", "number") and isinstance(instance, bool)):
                ok = True
        if not ok:
            raise SchemaError(f"{path}: tipo invalido, se esperaba {types}, llego {type(instance).__name__}")
    if isinstance(instance, bool):
        pass  # los chequeos numericos de abajo no aplican a bool
    elif isinstance(instance, (int, float)):
        if "minimum" in schema and instance < schema["minimum"]:
            raise SchemaError(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            raise SchemaError(f"{path}: {instance} > maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            raise SchemaError(f"{path}: {instance} <= exclusiveMinimum {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
            raise SchemaError(f"{path}: {instance} >= exclusiveMaximum {schema['exclusiveMaximum']}")
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            raise SchemaError(f"{path}: longitud {len(instance)} < minLength {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            raise SchemaError(f"{path}: longitud {len(instance)} > maxLength {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            raise SchemaError(f"{path}: {instance!r} no cumple pattern {schema['pattern']!r}")
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise SchemaError(f"{path}: {len(instance)} items < minItems {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            raise SchemaError(f"{path}: {len(instance)} items > maxItems {schema['maxItems']}")
        if schema.get("uniqueItems"):
            seen = [json.dumps(x, sort_keys=True, default=str) for x in instance]
            if len(set(seen)) != len(seen):
                raise SchemaError(f"{path}: items duplicados (uniqueItems)")
        if "items" in schema:
            for i, item in enumerate(instance):
                validate_schema(item, schema["items"], f"{path}[{i}]", root)
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in instance:
                raise SchemaError(f"{path}: falta campo obligatorio {req!r}")
        addl = schema.get("additionalProperties", True)
        for key, value in instance.items():
            if key in props:
                validate_schema(value, props[key], f"{path}.{key}", root)
            elif addl is False:
                raise SchemaError(f"{path}.{key}: propiedad no permitida (additionalProperties=false)")
            elif isinstance(addl, dict):
                validate_schema(value, addl, f"{path}.{key}", root)
    for sub in schema.get("allOf", []):
        validate_schema(instance, sub, path, root)
    if "anyOf" in schema:
        errs = []
        for sub in schema["anyOf"]:
            try:
                validate_schema(instance, sub, path, root)
                errs = []
                break
            except SchemaError as e:
                errs.append(str(e))
        if errs:
            raise SchemaError(f"{path}: no cumple ningun anyOf: {errs[0]}")
    if "oneOf" in schema:
        n_ok = 0
        for sub in schema["oneOf"]:
            try:
                validate_schema(instance, sub, path, root)
                n_ok += 1
            except SchemaError:
                pass
        if n_ok != 1:
            raise SchemaError(f"{path}: oneOf exige exactamente 1 esquema cumplido, se cumplieron {n_ok}")


def validate_named(name: str, instance: Any) -> None:
    """Valida ``instance`` contra el esquema publicado ``name``."""
    if name not in SCHEMAS:
        raise SchemaError(f"esquema desconocido: {name!r}; disponibles: {sorted(SCHEMAS)}")
    validate_schema(instance, SCHEMAS[name], path=f"{name}.$")


def schema_json(name: str | None = None, *, indent: int = 2) -> str:
    """Devuelve el esquema (o todos) como texto JSON publicable."""
    if name is not None:
        if name not in SCHEMAS:
            raise SchemaError(f"esquema desconocido: {name!r}")
        return json.dumps({"$schema_version": SCHEMA_VERSION, **SCHEMAS[name]}, ensure_ascii=False, indent=indent)
    return json.dumps({"$schema_version": SCHEMA_VERSION, "schemas": SCHEMAS}, ensure_ascii=False, indent=indent)


def schema_names() -> list[str]:
    return sorted(SCHEMAS)
