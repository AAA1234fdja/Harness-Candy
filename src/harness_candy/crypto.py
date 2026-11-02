"""Criptografia minima para integridad y secretos, solo stdlib (v3 §10 seguridad).

  - sha256_hex / hmac_sha256: huellas e integridad de corridas y artefactos.
  - sign_run / verify_run: firma HMAC de un RunResult (detecta mutaciones).
  - gen_token: tokens seguros con ``secrets`` (sesiones, API keys propias).
  - constant_time_eq: comparacion sin timing attacks.
  - mask_secret / redact_text: enmascarar secretos en textos (logs, reportes).

NUNCA guarda claves aqui: la clave de firma viene de variable de entorno
(HARNESS_SIGNING_KEY) o se pasa por parametro; jamas se escribe a disco.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from typing import Any

SIGNING_KEY_ENV = "HARNESS_SIGNING_KEY"

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
]


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hmac_sha256(key: str | bytes, msg: str | bytes) -> str:
    if isinstance(key, str):
        key = key.encode("utf-8")
    if isinstance(msg, str):
        msg = msg.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def gen_token(nbytes: int = 32) -> str:
    """Token URL-safe seguro (sesiones, claves propias del sistema)."""
    return secrets.token_urlsafe(nbytes)


def signing_key(environ: dict | None = None) -> str:
    """Clave de firma desde el entorno; lanza si no esta (fail-closed)."""
    env = os.environ if environ is None else environ
    key = env.get(SIGNING_KEY_ENV, "")
    if not key:
        raise RuntimeError(f"falta la variable de entorno {SIGNING_KEY_ENV} (clave de firma); no se usa ninguna por defecto")
    return key


def _canonico(obj: Any) -> str:
    import json

    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def sign_run(run: dict, key: str | None = None, environ: dict | None = None) -> str:
    """Firma HMAC del contenido canonico de una corrida."""
    k = key or signing_key(environ)
    return hmac_sha256(k, _canonico(run))


def verify_run(run: dict, firma: str, key: str | None = None, environ: dict | None = None) -> bool:
    """Verifica la firma de una corrida (constant-time)."""
    esperada = sign_run(run, key=key, environ=environ)
    return constant_time_eq(esperada, firma)


def sign_text(texto: str, key: str | None = None, environ: dict | None = None) -> str:
    k = key or signing_key(environ)
    return hmac_sha256(k, texto)


def mask_secret(valor: str, *, visibles: int = 4) -> str:
    """Enmascara un secreto: muestra solo los primeros ``visibles`` caracteres."""
    if not valor:
        return ""
    if len(valor) <= visibles:
        return "***"
    return valor[:visibles] + "***" + f"(len={len(valor)})"


def redact_text(texto: str) -> str:
    """Reemplaza patrones de secretos en un texto por *** (para logs/reportes)."""
    out = texto
    for pat in _SECRET_PATTERNS:
        out = pat.sub("***", out)
    return out


def buscar_secretos(texto: str) -> list[str]:
    """Devuelve los hallazgos (patron + contexto) de secretos en el texto."""
    hallazgos = []
    for pat in _SECRET_PATTERNS:
        for m in pat.finditer(texto):
            hallazgos.append({"patron": pat.pattern[:24], "inicio": m.start(), "fragmento": mask_secret(m.group(0))})
    return hallazgos


def derive_key(password: str | bytes, *, salt: bytes | None = None, iterations: int = 100_000, dklen: int = 32) -> tuple[bytes, bytes]:
    """Deriva una clave con PBKDF2-HMAC-SHA256 (hashlib). Devuelve (clave, salt)."""
    if isinstance(password, str):
        password = password.encode("utf-8")
    salt = salt or secrets.token_bytes(16)
    return hashlib.pbkdf2_hmac("sha256", password, salt, iterations, dklen=dklen), salt


def clave_desde_env(nombre_var: str = "HARNESS_DERIVE_KEY", environ: dict | None = None, **kw) -> bytes:
    """Deriva la clave desde una variable de entorno (fail-closed si falta)."""
    env = os.environ if environ is None else environ
    pw = env.get(nombre_var, "")
    if not pw:
        raise RuntimeError(f"falta la variable de entorno {nombre_var} para derivar la clave")
    return derive_key(pw, **kw)[0]
