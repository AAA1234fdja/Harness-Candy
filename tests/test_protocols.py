import unittest

try:
    import _path  # noqa: F401
except ModuleNotFoundError:  # al importar como tests.test_* desde la raiz del repo
    from tests import _path  # noqa: F401
from harness_candy.protocols import (
    Envelope,
    Hallazgo,
    ProtocolError,
    WevMessage,
    XevMessage,
    YevMessage,
    ZevMessage,
    validate,
)


def yev_ok():
    return {
        "protocol": "yev",
        "version": "0.1",
        "task_id": "t-004",
        "origen": "ISA",
        "destino": "Agent-2/XEV",
        "depende_de": ["t-002", "t-003"],
        "instruccion": "Implementar la validacion de entradas",
        "agente_destino": "XEV",
        "modelo": "gemini-2.5-flash",
        "clave": "flash-1",
        "presupuesto": {"max_tokens": 8000, "max_reintentos": 2},
        "criterios_aceptacion": ["pasa linter", "pruebas unitarias en verde"],
    }


def wev_ok():
    return {
        "protocol": "wev",
        "task_id": "t-004",
        "origen": "WEV",
        "destino": "YEV",
        "artefacto_id": "t-004",
        "checks": {"pasa_linter": False},
        "veredicto": "rechazado",
        "hallazgos": [{"herramienta": "linter", "severidad": "media", "detalle": "variable sin usar en validar()"}],
        "accion": "reintentar con retroalimentacion",
    }


class TestProtocolos(unittest.TestCase):
    def test_yev_valido(self):
        msg = validate(yev_ok())
        self.assertIsInstance(msg, YevMessage)
        self.assertEqual(msg.depende_de, ["t-002", "t-003"])
        self.assertEqual(msg.criterios_aceptacion[0], "pasa linter")

    def test_wev_valido(self):
        msg = validate(wev_ok())
        self.assertIsInstance(msg, WevMessage)
        self.assertEqual(msg.veredicto, "rechazado")
        self.assertEqual(msg.hallazgos[0].severidad, "media")
        self.assertAlmostEqual(msg.hallazgos[0].penalty(), 0.20)

    def test_zev_valido(self):
        msg = validate(
            {
                "protocol": "zev",
                "task_id": "t-1",
                "origen": "ZEV",
                "destino": "memoria",
                "consulta": "arquitectura del repo",
                "fuentes": ["README.md"],
                "fragmentos": [{"contenido": "...", "procedencia": {"fuente": "README.md"}}],
                "nivel_confianza": 0.9,
            }
        )
        self.assertIsInstance(msg, ZevMessage)
        self.assertEqual(msg.nivel_confianza, 0.9)

    def test_xev_valido(self):
        msg = validate(
            {
                "protocol": "xev",
                "task_id": "t-1",
                "origen": "YEV",
                "destino": "XEV",
                "instruccion": "compilar",
                "entradas": {"root": "."},
                "herramienta": "shell",
                "artefacto": {"ok": True},
                "registro_ejecucion": {"duracion": 1.2},
            }
        )
        self.assertIsInstance(msg, XevMessage)
        self.assertEqual(msg.artefacto, {"ok": True})

    def test_rechaza_protocolo_desconocido(self):
        d = yev_ok()
        d["protocol"] = "otro"
        with self.assertRaises(ProtocolError):
            validate(d)

    def test_rechaza_version_no_soportada(self):
        d = yev_ok()
        d["version"] = "9.9"
        with self.assertRaises(ProtocolError):
            validate(d)

    def test_rechaza_falta_campo(self):
        d = yev_ok()
        del d["instruccion"]
        with self.assertRaises(ProtocolError):
            validate(d)

    def test_rechaza_tipo_invalido(self):
        d = yev_ok()
        d["depende_de"] = "t-002"  # debe ser lista
        with self.assertRaises(ProtocolError):
            validate(d)

    def test_rechaza_bool_como_numero(self):
        d = {
            "protocol": "zev", "task_id": "t", "origen": "a", "destino": "b",
            "consulta": "x", "fragmentos": [], "nivel_confianza": True,
        }
        with self.assertRaises(ProtocolError):
            validate(d)

    def test_rechaza_confianza_fuera_de_rango(self):
        d = {
            "protocol": "zev", "task_id": "t", "origen": "a", "destino": "b",
            "consulta": "x", "fragmentos": [], "nivel_confianza": 1.5,
        }
        with self.assertRaises(ProtocolError):
            validate(d)

    def test_rechaza_fragmento_sin_procedencia(self):
        d = {
            "protocol": "zev", "task_id": "t", "origen": "a", "destino": "b",
            "consulta": "x", "fragmentos": [{"contenido": "hola"}], "nivel_confianza": 0.5,
        }
        with self.assertRaises(ProtocolError):
            validate(d)

    def test_rechaza_veredicto_invalido(self):
        d = wev_ok()
        d["veredicto"] = "quizas"
        with self.assertRaises(ProtocolError):
            validate(d)

    def test_rechaza_severidad_invalida(self):
        d = wev_ok()
        d["hallazgos"] = [{"herramienta": "linter", "severidad": "megacritica", "detalle": "x"}]
        with self.assertRaises(ProtocolError):
            validate(d)

    def test_rechaza_no_dict(self):
        with self.assertRaises(ProtocolError):
            validate("texto suelto")

    def test_roundtrip(self):
        msg = validate(wev_ok())
        msg2 = validate(msg.to_dict())
        self.assertEqual(msg2.to_dict()["veredicto"], "rechazado")
        self.assertEqual(msg2.hallazgos[0].herramienta, "linter")

    def test_hallazgo_penalizaciones(self):
        self.assertEqual(Hallazgo("t", "critica", "x").penalty(), 1.0)
        self.assertEqual(Hallazgo("t", "baja", "x").penalty(), 0.05)


if __name__ == "__main__":
    unittest.main()
