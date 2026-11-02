"""Protocolos tipados y versionados: yev, zev, xev, wev.

Implementacion de la seccion 5.3 / 5.6 del diseno combinado
(Ely-Cowork ADK+Harness^2, 2026-11-02):

* Cada protocolo es un formato de mensaje tipado asociado a un rol.
* Todos comparten un encabezado comun (protocolo, version, task_id,
  origen, destino) y anaden campos propios.
* Un mensaje que no cumple su esquema SE RECHAZA antes de procesarse:
  objetivo "0 mensajes malformados aceptados".

Tabla de protocolos (diseno combinado, tabla 3):
  yev  ISA -> YEV ; YEV -> Agent-n   planificar y despachar tareas en el DAG
  zev  Agent-n <-> ZEV               recuperar informacion y registrar su origen
  xev  YEV -> XEV ; XEV -> WEV       ejecutar micro-tareas y entregar artefactos
  wev  WEV -> YEV y ELY              validar salidas antes de consolidar
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Union

PROTOCOL_VERSION = "0.1"
SUPPORTED_VERSIONS = frozenset({"0.1"})
PROTOCOL_NAMES = frozenset({"yev", "zev", "xev", "wev"})

SEVERIDADES = ("baja", "media", "alta", "critica")
VEREDICTOS = ("aprobado", "rechazado")

# Penalizacion rho_s por severidad de hallazgo (ecuacion 1, seccion 5).
PENALTY_BY_SEVERITY = {
    "baja": 0.05,
    "media": 0.20,
    "alta": 0.50,
    "critica": 1.00,
}


class ProtocolError(ValueError):
    """Mensaje malformado: se rechaza antes de procesarse."""


@dataclass
class Envelope:
    """Encabezado comun a los cuatro protocolos."""

    protocol: str
    task_id: str
    origen: str
    destino: str
    version: str = PROTOCOL_VERSION
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)

    def base_dict(self) -> dict:
        return {
            "protocol": self.protocol,
            "version": self.version,
            "task_id": self.task_id,
            "origen": self.origen,
            "destino": self.destino,
            "msg_id": self.msg_id,
            "timestamp": self.timestamp,
        }


@dataclass
class Hallazgo:
    """Hallazgo de WEV (o de la puerta de seguridad) con severidad."""

    herramienta: str
    severidad: str
    detalle: str

    def penalty(self) -> float:
        return PENALTY_BY_SEVERITY[self.severidad]

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Hallazgo":
        _require(d, "herramienta", str, "hallazgo")
        _require(d, "severidad", str, "hallazgo")
        _require(d, "detalle", str, "hallazgo")
        if d["severidad"] not in SEVERIDADES:
            raise ProtocolError(f"severidad desconocida: {d['severidad']!r}")
        return Hallazgo(d["herramienta"], d["severidad"], d["detalle"])


@dataclass
class YevMessage:
    """yev: ISA -> YEV (plan) y YEV -> Agent-n (despacho en el DAG)."""

    envelope: Envelope
    depende_de: list[str]
    instruccion: str
    agente_destino: str
    modelo: Optional[str] = None
    clave: Optional[str] = None
    presupuesto: dict = field(default_factory=dict)
    criterios_aceptacion: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = self.envelope.base_dict()
        d.update(
            {
                "depende_de": list(self.depende_de),
                "instruccion": self.instruccion,
                "agente_destino": self.agente_destino,
                "modelo": self.modelo,
                "clave": self.clave,
                "presupuesto": dict(self.presupuesto),
                "criterios_aceptacion": list(self.criterios_aceptacion),
            }
        )
        return d


@dataclass
class ZevMessage:
    """zev: Agent-n <-> ZEV y ZEV -> memoria compartida (con procedencia)."""

    envelope: Envelope
    consulta: str
    fuentes: list[str] = field(default_factory=list)
    fragmentos: list[dict] = field(default_factory=list)
    nivel_confianza: float = 1.0

    def to_dict(self) -> dict:
        d = self.envelope.base_dict()
        d.update(
            {
                "consulta": self.consulta,
                "fuentes": list(self.fuentes),
                "fragmentos": [dict(f) for f in self.fragmentos],
                "nivel_confianza": self.nivel_confianza,
            }
        )
        return d


@dataclass
class XevMessage:
    """xev: YEV -> XEV (instruccion atomica) y XEV -> WEV (artefacto)."""

    envelope: Envelope
    instruccion: str
    entradas: dict = field(default_factory=dict)
    herramienta: str = ""
    artefacto: Any = None
    registro_ejecucion: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = self.envelope.base_dict()
        d.update(
            {
                "instruccion": self.instruccion,
                "entradas": dict(self.entradas),
                "herramienta": self.herramienta,
                "artefacto": self.artefacto,
                "registro_ejecucion": dict(self.registro_ejecucion),
            }
        )
        return d


@dataclass
class WevMessage:
    """wev: WEV -> YEV y ELY (veredicto, hallazgos con severidad, accion)."""

    envelope: Envelope
    artefacto_id: str
    checks: dict[str, bool] = field(default_factory=dict)
    veredicto: str = "rechazado"
    hallazgos: list[Hallazgo] = field(default_factory=list)
    accion: str = "reintentar con retroalimentacion"

    def to_dict(self) -> dict:
        d = self.envelope.base_dict()
        d.update(
            {
                "artefacto_id": self.artefacto_id,
                "checks": dict(self.checks),
                "veredicto": self.veredicto,
                "hallazgos": [h.to_dict() for h in self.hallazgos],
                "accion": self.accion,
            }
        )
        return d


ProtocolMessage = Union[YevMessage, ZevMessage, XevMessage, WevMessage]


# ---------------------------------------------------------------------------
# Validacion de esquemas
# ---------------------------------------------------------------------------

def _require(d: dict, name: str, types: type | tuple, ctx: str) -> Any:
    if name not in d:
        raise ProtocolError(f"[{ctx}] falta campo obligatorio: {name!r}")
    v = d[name]
    expected = types if isinstance(types, tuple) else (types,)
    if isinstance(v, bool) and bool not in expected:
        raise ProtocolError(f"[{ctx}] campo {name!r} no debe ser bool: {v!r}")
    if not isinstance(v, types):
        raise ProtocolError(f"[{ctx}] campo {name!r} tiene tipo invalido: {type(v).__name__}")
    return v


def _opt(d: dict, name: str, types: type | tuple, ctx: str, default=None):
    if name not in d or d[name] is None:
        return default
    return _require(d, name, types, ctx)


def _str_list(d: dict, name: str, ctx: str, required: bool = True) -> list[str]:
    v = _require(d, name, list, ctx) if required else _opt(d, name, list, ctx, [])
    for item in v:
        if not isinstance(item, str):
            raise ProtocolError(f"[{ctx}] {name!r} debe ser list[str]")
    return v


def _check_envelope(d: dict) -> Envelope:
    protocol = _require(d, "protocol", str, "envelope")
    if protocol not in PROTOCOL_NAMES:
        raise ProtocolError(f"protocolo desconocido: {protocol!r}")
    version = _opt(d, "version", str, "envelope", PROTOCOL_VERSION)
    if version not in SUPPORTED_VERSIONS:
        raise ProtocolError(f"version de protocolo no soportada: {version!r}")
    task_id = _require(d, "task_id", str, "envelope")
    origen = _require(d, "origen", str, "envelope")
    destino = _require(d, "destino", str, "envelope")
    msg_id = _opt(d, "msg_id", str, "envelope", uuid.uuid4().hex[:12])
    ts = _opt(d, "timestamp", (int, float), "envelope", time.time())
    return Envelope(protocol, task_id, origen, destino, version, msg_id, float(ts))


def validate(raw: Any) -> ProtocolMessage:
    """Valida un mensaje crudo (dict) y lo convierte a su dataclass tipada.

    Lanza ProtocolError si el mensaje esta malformado: los agentes no
    dependen de texto libre para los datos criticos.
    """
    if not isinstance(raw, dict):
        raise ProtocolError("el mensaje debe ser un objeto JSON (dict)")
    env = _check_envelope(raw)
    proto = env.protocol

    if proto == "yev":
        return YevMessage(
            envelope=env,
            depende_de=_str_list(raw, "depende_de", "yev"),
            instruccion=_require(raw, "instruccion", str, "yev"),
            agente_destino=_require(raw, "agente_destino", str, "yev"),
            modelo=_opt(raw, "modelo", str, "yev"),
            clave=_opt(raw, "clave", str, "yev"),
            presupuesto=_opt(raw, "presupuesto", dict, "yev", {}) or {},
            criterios_aceptacion=_str_list(raw, "criterios_aceptacion", "yev", required=False),
        )
    if proto == "zev":
        conf = _require(raw, "nivel_confianza", (int, float), "zev")
        if not 0.0 <= float(conf) <= 1.0:
            raise ProtocolError("[zev] nivel_confianza debe estar en [0, 1]")
        fragmentos = _require(raw, "fragmentos", list, "zev")
        for f in fragmentos:
            if not isinstance(f, dict):
                raise ProtocolError("[zev] fragmentos debe ser list[dict]")
            if "contenido" not in f or "procedencia" not in f:
                raise ProtocolError("[zev] cada fragmento requiere 'contenido' y 'procedencia'")
        return ZevMessage(
            envelope=env,
            consulta=_require(raw, "consulta", str, "zev"),
            fuentes=_str_list(raw, "fuentes", "zev", required=False),
            fragmentos=fragmentos,
            nivel_confianza=float(conf),
        )
    if proto == "xev":
        return XevMessage(
            envelope=env,
            instruccion=_require(raw, "instruccion", str, "xev"),
            entradas=_opt(raw, "entradas", dict, "xev", {}) or {},
            herramienta=_opt(raw, "herramienta", str, "xev", ""),
            artefacto=raw.get("artefacto"),
            registro_ejecucion=_opt(raw, "registro_ejecucion", dict, "xev", {}) or {},
        )
    # wev
    veredicto = _require(raw, "veredicto", str, "wev")
    if veredicto not in VEREDICTOS:
        raise ProtocolError(f"[wev] veredicto debe ser uno de {VEREDICTOS}")
    hallazgos_raw = _opt(raw, "hallazgos", list, "wev", []) or []
    hallazgos = [Hallazgo.from_dict(h) if isinstance(h, dict) else _reject_h(h) for h in hallazgos_raw]
    checks = _opt(raw, "checks", dict, "wev", {}) or {}
    for k, v in checks.items():
        if not isinstance(v, bool):
            raise ProtocolError("[wev] checks debe ser dict[str, bool]")
    return WevMessage(
        envelope=env,
        artefacto_id=_require(raw, "artefacto_id", str, "wev"),
        checks=checks,
        veredicto=veredicto,
        hallazgos=hallazgos,
        accion=_opt(raw, "accion", str, "wev", "reintentar con retroalimentacion"),
    )


def _reject_h(h: Any) -> Hallazgo:
    raise ProtocolError(f"[wev] hallazgo malformado: {h!r}")


def dump(msg: ProtocolMessage) -> dict:
    """Serializa un mensaje tipado a dict (para transporte/almacenamiento)."""
    return msg.to_dict()
