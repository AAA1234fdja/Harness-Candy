"""Tests del esquema JSON Schema publicado y su validador propio (schemas.py)."""
import json
import unittest

import _path  # noqa: F401
from harness_candy.schemas import (
    SCHEMAS,
    SCHEMA_VERSION,
    SchemaError,
    schema_json,
    schema_names,
    validate_named,
    validate_schema,
)


def task_ok():
    return {
        "task_id": "t-1",
        "kind": "security_scan",
        "instruction": "escanear",
        "inputs": {"root": "."},
        "criterios": [{"id": "json_valido", "peso": 1.0}],
        "max_reintentos": 2,
    }


class TestEsquemasPublicados(unittest.TestCase):
    def test_hay_esquemas_para_todo_el_contrato(self):
        for nombre in ("yev", "zev", "xev", "wev", "task", "harness", "budget", "pool_entry", "trace_event", "run_result", "suite", "golden_set", "tool_spec", "envelope", "hallazgo", "criterion"):
            self.assertIn(nombre, SCHEMAS)

    def test_schema_json_es_json_valido_y_versionado(self):
        data = json.loads(schema_json("task"))
        self.assertEqual(data["$schema_version"], SCHEMA_VERSION)
        self.assertEqual(data["type"], "object")
        todo = json.loads(schema_json(None))
        self.assertIn("schemas", todo)
        self.assertIn("task", todo["schemas"])

    def test_schema_desconocido(self):
        with self.assertRaises(SchemaError):
            validate_named("no_existe", {})
        with self.assertRaises(SchemaError):
            schema_json("no_existe")
        self.assertIn("task", schema_names())


class TestValidateTask(unittest.TestCase):
    def test_task_valida(self):
        validate_named("task", task_ok())

    def test_falta_campo_obligatorio(self):
        t = task_ok()
        del t["kind"]
        with self.assertRaises(SchemaError) as ctx:
            validate_named("task", t)
        self.assertIn("kind", str(ctx.exception))

    def test_tipo_invalido(self):
        t = task_ok()
        t["max_reintentos"] = "dos"
        with self.assertRaises(SchemaError):
            validate_named("task", t)

    def test_criterio_con_peso_negativo_rechazado(self):
        t = task_ok()
        t["criterios"] = [{"id": "x", "peso": -1}]
        with self.assertRaises(SchemaError):
            validate_named("task", t)

    def test_bool_no_cuenta_como_integer(self):
        t = task_ok()
        t["max_reintentos"] = True
        with self.assertRaises(SchemaError):
            validate_named("task", t)


class TestProtocolos(unittest.TestCase):
    def _env(self, proto):
        return {"protocol": proto, "task_id": "t", "origen": "A", "destino": "B"}

    def test_wev_valido(self):
        m = self._env("wev")
        m.update({"artefacto_id": "a1", "veredicto": "aprobado", "checks": {"json": True},
                  "hallazgos": [{"herramienta": "x", "severidad": "baja", "detalle": "d"}]})
        validate_named("wev", m)

    def test_wev_veredicto_invalido(self):
        m = self._env("wev")
        m.update({"artefacto_id": "a1", "veredicto": "quizas"})
        with self.assertRaises(SchemaError):
            validate_named("wev", m)

    def test_wev_hallazgo_severidad_invalida(self):
        m = self._env("wev")
        m.update({"artefacto_id": "a1", "veredicto": "rechazado",
                  "hallazgos": [{"herramienta": "x", "severidad": "apocalipsis", "detalle": "d"}]})
        with self.assertRaises(SchemaError):
            validate_named("wev", m)

    def test_zev_confianza_fuera_de_rango(self):
        m = self._env("zev")
        m.update({"consulta": "q", "nivel_confianza": 1.5, "fragmentos": []})
        with self.assertRaises(SchemaError):
            validate_named("zev", m)

    def test_zev_fragmento_sin_procedencia(self):
        m = self._env("zev")
        m.update({"consulta": "q", "nivel_confianza": 0.5, "fragmentos": [{"contenido": "x"}]})
        with self.assertRaises(SchemaError):
            validate_named("zev", m)

    def test_protocolo_desconocido(self):
        m = self._env("otro")
        with self.assertRaises(SchemaError):
            validate_named("envelope", m)


class TestOtrosEsquemas(unittest.TestCase):
    def test_pool_entry_secret_env_debe_ser_nombre_de_env(self):
        validate_named("pool_entry", {"alias": "a", "model": "m", "secret_env": "XKIRO_API_KEY"})
        with self.assertRaises(SchemaError):
            validate_named("pool_entry", {"alias": "a", "model": "m", "secret_env": "clave-en-minuscula"})

    def test_run_result_exige_run_id_con_formato(self):
        base = {"run_id": "run-0123456789ab", "objetivo": "o", "dag_results": {}, "duracion": 1.0}
        validate_named("run_result", base)
        bad = dict(base, run_id="otra-cosa")
        with self.assertRaises(SchemaError):
            validate_named("run_result", bad)

    def test_trace_event_q_en_rango(self):
        ev = {"ts": 1.0, "run_id": "r", "task_id": "t", "model": "m", "seed": 0, "harness": "h", "phase": "probe", "q": 0.5}
        validate_named("trace_event", ev)
        with self.assertRaises(SchemaError):
            validate_named("trace_event", dict(ev, q=1.5))

    def test_suite_valida_y_deps_unicas(self):
        s = {"name": "s", "tasks": [
            {"task_id": "a", "kind": "k", "instruction": "i", "deps": ["b"]},
            {"task_id": "b", "kind": "k", "instruction": "i", "deps": []},
        ]}
        validate_named("suite", s)
        bad = {"name": "s", "tasks": [{"task_id": "a", "kind": "k", "instruction": "i", "deps": ["b", "b"]}]}
        with self.assertRaises(SchemaError):
            validate_named("suite", bad)

    def test_golden_set(self):
        g = {"name": "g", "min_pass_rate": 0.9, "cases": [
            {"id": "c1", "task": task_ok(), "expect": {"veredicto": "aprobado", "q_min": 0.9}}
        ]}
        validate_named("golden_set", g)

    def test_tool_spec_nombre_con_pattern(self):
        validate_named("tool_spec", {"name": "read_file", "description": "d", "parameters": {}, "permission": "read"})
        with self.assertRaises(SchemaError):
            validate_named("tool_spec", {"name": "Read File!", "description": "d", "parameters": {}, "permission": "read"})
        with self.assertRaises(SchemaError):
            validate_named("tool_spec", {"name": "x", "description": "d", "parameters": {}, "permission": "admin"})


class TestValidadorGenerico(unittest.TestCase):
    def test_enum_const_pattern(self):
        validate_schema("rojo", {"enum": ["rojo", "verde"]})
        with self.assertRaises(SchemaError):
            validate_schema("azul", {"enum": ["rojo", "verde"]})
        validate_schema("abc", {"const": "abc"})
        with self.assertRaises(SchemaError):
            validate_schema("abd", {"const": "abc"})
        validate_schema("hola123", {"type": "string", "pattern": r"^[a-z]+[0-9]+$"})
        with self.assertRaises(SchemaError):
            validate_schema("123hola", {"type": "string", "pattern": r"^[a-z]+[0-9]+$"})

    def test_numeros_limites(self):
        validate_schema(5, {"type": "integer", "minimum": 0, "maximum": 10, "exclusiveMinimum": -1})
        with self.assertRaises(SchemaError):
            validate_schema(0, {"type": "integer", "exclusiveMinimum": 0})
        with self.assertRaises(SchemaError):
            validate_schema(11, {"type": "integer", "maximum": 10})

    def test_anyOf_oneOf(self):
        validate_schema(1, {"anyOf": [{"type": "string"}, {"type": "integer"}]})
        with self.assertRaises(SchemaError):
            validate_schema(1.5, {"anyOf": [{"type": "string"}, {"type": "integer"}]})
        # oneOf: exactamente uno cumplido
        validate_schema(1, {"oneOf": [{"type": "integer"}, {"type": "string"}]})
        validate_schema("a", {"oneOf": [{"type": "integer"}, {"type": "string"}]})
        with self.assertRaises(SchemaError):
            validate_schema(1.5, {"oneOf": [{"type": "integer"}, {"type": "string"}]})  # ninguno
        with self.assertRaises(SchemaError):
            validate_schema(2, {"oneOf": [{"type": "integer"}, {"type": "number"}]})  # cumple los dos

    def test_additional_properties_false(self):
        validate_schema({"a": 1}, {"type": "object", "properties": {"a": {"type": "integer"}}, "additionalProperties": False})
        with self.assertRaises(SchemaError):
            validate_schema({"a": 1, "b": 2}, {"type": "object", "properties": {"a": {"type": "integer"}}, "additionalProperties": False})

    def test_ref_interno(self):
        validate_schema({"herramienta": "x", "severidad": "baja", "detalle": "d"}, SCHEMAS["hallazgo"])
        with self.assertRaises(SchemaError):
            validate_schema({"herramienta": "x", "severidad": "mala", "detalle": "d"}, SCHEMAS["hallazgo"])


if __name__ == "__main__":
    unittest.main()
