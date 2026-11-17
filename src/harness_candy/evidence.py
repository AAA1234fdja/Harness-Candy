"""Evidence packs y observabilidad production-grade (capitulos 05/13/15).

- ``evidence_pack``: agrupa una corrida (run dict), su RunMark y las cards de
  benchmark/evaluacion, y la FIRMA con HMAC (crypto.sign_run, clave solo en
  env HARNESS_SIGNING_KEY). ``verificar_pack`` comprueba integridad.
- ``export_otlp_end_to_end``: genera spans OTLP de una corrida y los envia a
  un collector via transport inyectable (POST /v1/traces); verifica la ruta
  completa (200 + respuesta parseable) y reporta latencia del export.
- ``evaluar_alertas``: reglas avanzadas sobre series temporales: toxicity
  trend, jailbreak rate, judge agreement drop, model regression (reusa
  RegressionGuard). Devuelve alertas con severidad.
- ``rollback_si_regresion``: compara la q media de una corrida contra el
  baseline del store; si cae mas de la banda, marca la corrida como rollback
  y devuelve el harness anterior (para rollback automatico explicable).
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .alerts import Alert
from .crypto import sha256_hex, sign_run, verify_run
from .metrics_export import otlp_spans
from .quality import RegressionGuard
from .runmark import crear_runmark


# ------------------------------------------------------------- evidence pack
def evidence_pack(
    run: dict,
    *,
    cards: Optional[list[dict]] = None,
    runmark: Optional[dict] = None,
    autor: str = "harness-candy",
    key: Optional[str] = None,
    environ: Optional[dict] = None,
) -> dict:
    """Empaqueta evidencia auditable de una corrida y la firma (HMAC-SHA256).

    La firma cubre run + cards + runmark; la clave sale SOLO de
    HARNESS_SIGNING_KEY (env) o del argumento ``key`` (tests).
    """
    pack = {
        "schema": "harness-candy/evidence-pack",
        "version": 1,
        "autor": autor,
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "run": run,
        "cards": list(cards or []),
        "runmark": runmark or {},
        "hash_contenido": sha256_hex(json.dumps({"run": run, "cards": cards or [], "runmark": runmark or {}}, sort_keys=True, default=str)),
    }
    pack["firma"] = sign_run(pack, key=key, environ=environ)
    return pack


def verificar_pack(pack: dict, *, key: Optional[str] = None, environ: Optional[dict] = None) -> dict:
    """Verifica la firma y el hash de contenido de un evidence pack."""
    firma = pack.get("firma", "")
    copia = {k: v for k, v in pack.items() if k != "firma"}
    firma_ok = verify_run(copia, firma, key=key, environ=environ)
    hash_ok = pack.get("hash_contenido") == sha256_hex(json.dumps(
        {"run": pack.get("run"), "cards": pack.get("cards", []), "runmark": pack.get("runmark", {})},
        sort_keys=True, default=str))
    return {"firma_ok": firma_ok, "hash_ok": hash_ok, "ok": bool(firma_ok and hash_ok)}


def guardar_pack(pack: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(pack, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def cargar_pack(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ------------------------------------------------------------- OTLP e2e
def export_otlp_end_to_end(
    trace_entries: Sequence[dict],
    *,
    collector_url: str = "http://localhost:4318/v1/traces",
    transport: Optional[Callable] = None,
    service_name: str = "harness-candy",
    timeout: float = 10.0,
) -> dict:
    """Ruta OTLP completa: spans -> POST al collector -> verifica recepcion.

    ``transport(req, timeout)`` inyectable (por defecto urllib). Devuelve
    {ok, status, n_spans, duracion_ms, error}.
    """
    payload = otlp_spans(trace_entries, service_name=service_name)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        collector_url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    opener = transport or urllib.request.urlopen
    inicio = time.time()
    try:
        with opener(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            resp.read()
        return {
            "ok": 200 <= int(status) < 300,
            "status": int(status),
            "n_spans": len(payload.get("resourceSpans", [{}])[0].get("scopeSpans", [{}])[0].get("spans", [])) if payload.get("resourceSpans") else 0,
            "duracion_ms": round((time.time() - inicio) * 1000, 2),
            "error": "",
        }
    except Exception as e:  # noqa: BLE001 - el export es best-effort pero reportado
        return {"ok": False, "status": 0, "n_spans": 0,
                "duracion_ms": round((time.time() - inicio) * 1000, 2),
                "error": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------------- alertas avanzadas
@dataclass
class ReglaAlerta:
    """Regla sobre una serie temporal de metricas.

    - ``tendencia``: alerta si la media de la ultima ``ventana`` supera ``umbral``.
    - ``caida``: alerta si la ultima ventana cae mas de ``delta`` respecto a la anterior.
    """

    metrica: str
    tipo: str = "tendencia"  # "tendencia" | "caida"
    ventana: int = 5
    umbral: float = 0.0
    delta: float = 0.0
    severidad: str = "alta"


REGLAS_DEFAULT: list[ReglaAlerta] = [
    ReglaAlerta("toxicity_rate", "tendencia", ventana=5, umbral=0.02, severidad="critica"),
    ReglaAlerta("jsr", "tendencia", ventana=5, umbral=0.05, severidad="critica"),
    ReglaAlerta("judge_agreement", "caida", ventana=5, delta=0.2, severidad="media"),
    ReglaAlerta("q_media", "caida", ventana=5, delta=0.03, severidad="alta"),
]


_NIVEL = {"critica": "critical", "alta": "warning", "media": "info", "baja": "info"}
_KIND = {"toxicity_rate": "security", "jsr": "security", "q_media": "quality", "judge_agreement": "quality"}


def _alert(regla: ReglaAlerta, message: str, data: dict) -> Alert:
    return Alert(
        ts=time.time(),
        level=_NIVEL.get(regla.severidad, "warning"),
        kind=_KIND.get(regla.metrica, "quality"),
        message=message,
        data=data,
    )


def evaluar_alertas(historial: dict[str, list[float]], reglas: Sequence[ReglaAlerta] = REGLAS_DEFAULT) -> list[Alert]:
    """Evalua reglas sobre el historial {metrica: [valores en orden temporal]}."""
    alertas: list[Alert] = []
    for regla in reglas:
        serie = historial.get(regla.metrica, [])
        if len(serie) < regla.ventana:
            continue
        ult = serie[-regla.ventana:]
        media_ult = sum(ult) / len(ult)
        if regla.tipo == "tendencia" and media_ult > regla.umbral:
            alertas.append(_alert(
                regla,
                f"{regla.metrica}: media ultimos {regla.ventana} = {media_ult:.4f} > umbral {regla.umbral}",
                {"metrica": regla.metrica, "media_ventana": round(media_ult, 4), "umbral": regla.umbral},
            ))
        elif regla.tipo == "caida" and len(serie) >= 2 * regla.ventana:
            ant = serie[-2 * regla.ventana:-regla.ventana]
            media_ant = sum(ant) / len(ant)
            if media_ant - media_ult > regla.delta:
                alertas.append(_alert(
                    regla,
                    f"{regla.metrica}: caida de {media_ant:.4f} a {media_ult:.4f} (delta {media_ant - media_ult:.4f} > {regla.delta})",
                    {"metrica": regla.metrica, "antes": round(media_ant, 4), "despues": round(media_ult, 4), "delta": regla.delta},
                ))
    return alertas


# ------------------------------------------------------------- rollback
def rollback_si_regresion(
    qs_actuales: Sequence[float],
    baseline: dict[str, float],
    *,
    banda: float = 0.03,
    drop_pp: float = 2.0,
) -> dict:
    """Decide rollback automatico: compara q media actual vs baseline por tarea.

    Si alguna tarea cae mas de ``drop_pp`` puntos porcentuales (o la media
    global cae mas de ``banda``), recomienda rollback al harness anterior.
    """
    guard = RegressionGuard(drop_pp=drop_pp, success_band=banda)
    for t, q in baseline.items():
        guard.set_baseline(t, q)
    alertas = []
    for i, q in enumerate(qs_actuales):
        t = f"tarea-{i}"
        if t in baseline:
            a = guard.check(t, q)
            if a is not None:
                alertas.append(a.mensaje)
    media_actual = sum(qs_actuales) / len(qs_actuales) if qs_actuales else 0.0
    media_base = sum(baseline.values()) / len(baseline) if baseline else 0.0
    caida_global = media_base - media_actual
    rollback = bool(alertas) or (media_base > 0 and caida_global > banda)
    return {
        "rollback": rollback,
        "caida_global": round(caida_global, 4),
        "banda": banda,
        "alertas": alertas,
        "accion": "volver al harness anterior (HarnessStore)" if rollback else "mantener harness actual",
    }


def marcar_rollback_en_store(run: dict, decision: dict, store) -> dict:
    """Persiste la decision de rollback en el store (trazabilidad explicable)."""
    run = dict(run)
    run["rollback"] = decision
    run["status"] = "rollback" if decision.get("rollback") else run.get("status", "done")
    store.save(run)
    return run


# ------------------------------------------------------- pack desde el store
def pack_desde_store(
    store,
    run_id: str,
    *,
    cards: Optional[list[dict]] = None,
    root: str | Path = ".",
    seed: int = 0,
    autor: str = "harness-candy",
    key: Optional[str] = None,
    environ: Optional[dict] = None,
) -> dict:
    """Arma un evidence pack firmado desde una corrida guardada en el store.

    Incluye la RunMark real (commit git + hashes + env como nombres) para
    trazabilidad regulatoria (NIST AI RMF / EU AI Act: evidencia por corrida).
    """
    run = store.get(run_id)
    if run is None:
        raise KeyError(f"run_id {run_id!r} no esta en el store")
    mark = crear_runmark(run_id, seed=seed, root=root, environ=environ).to_dict()
    return evidence_pack(run, cards=cards, runmark=mark, autor=autor, key=key, environ=environ)


def exportar_pack_zip(pack: dict, path: str | Path, *, incluir_run: bool = True) -> Path:
    """Empaqueta el evidence pack en un ZIP (stdlib zipfile) para auditoria."""
    import zipfile

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("pack.json", json.dumps(pack, ensure_ascii=False, indent=2, default=str))
        if incluir_run and isinstance(pack.get("run"), dict):
            z.writestr("run.json", json.dumps(pack["run"], ensure_ascii=False, indent=2, default=str))
        z.writestr("VERIFICACION.txt", "firma HMAC-SHA256 en pack['firma']; verificar con harness_candy.verificar_pack")
    return p
