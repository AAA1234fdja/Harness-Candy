"""Marcas de corrida (run marks) para reproducibilidad (v3 §11 trazabilidad).

Un ``RunMark`` fija TODO lo que hace reproducible una corrida: run_id, seed,
version del paquete, commit git (y si el repo estaba sucio), hashes sha256 de
los archivos de configuracion clave, lista de NOMBRES de variables de entorno
presentes (nunca sus valores), parametros y timestamp. Se serializa a JSON.

``verificar_reproducibilidad(a, b)`` compara dos marcas y devuelve las
diferencias (sin exponer secretos).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .crypto import sha256_hex

# Variables de entorno relevantes cuyos NOMBRES se registran (nunca valores)
ENV_RELEVANTES = ("XKIRO_API_KEY", "XKIRO_BASE_URL", "XKIRO_MODEL", "HARNESS_API_TOKEN", "HARNESS_SIGNING_KEY", "HARNESS_DERIVE_KEY", "HARBOR_USERNAME", "HARBOR_PASSWORD")


@dataclass
class RunMark:
    run_id: str
    seed: int
    version: str
    git_commit: str
    git_dirty: bool
    archivos: dict[str, str]  # ruta -> sha256
    env_presentes: list[str]   # solo nombres
    params: dict[str, Any]
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "RunMark":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**d)


def _git(root: Path, *args: str) -> tuple[str, bool]:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else "unknown", r.returncode != 0
    except Exception:
        return "unknown", True


def fingerprint_env(environ: dict | None = None) -> list[str]:
    """Nombres de variables de entorno relevantes presentes (sin valores)."""
    env = os.environ if environ is None else environ
    return sorted(k for k in ENV_RELEVANTES if env.get(k))


def crear_runmark(
    run_id: str,
    seed: int = 0,
    *,
    params: Optional[dict] = None,
    root: str | Path = ".",
    archivos: Optional[list[str | Path]] = None,
    environ: dict | None = None,
) -> RunMark:
    """Crea la marca de una corrida (commit git, hashes de archivos clave, env)."""
    root_p = Path(root)
    commit, ok_commit = _git(root_p, "rev-parse", "HEAD")
    salida_status, ok_status = _git(root_p, "status", "--porcelain")
    dirty = bool(salida_status.strip()) if ok_status else not ok_commit
    if archivos is None:
        archivos = ["pyproject.toml", "src/harness_candy/__init__.py"]
    from . import __version__  # import diferido: __init__ aun no define la version
    hashes: dict[str, str] = {}
    for a in archivos:
        p = root_p / a
        if p.exists():
            hashes[str(a)] = sha256_hex(p.read_bytes())
    return RunMark(
        run_id=run_id,
        seed=int(seed),
        version=__version__,
        git_commit=commit,
        git_dirty=dirty,
        archivos=hashes,
        env_presentes=fingerprint_env(environ),
        params=dict(params or {}),
    )


def verificar_reproducibilidad(a: RunMark, b: RunMark) -> dict[str, Any]:
    """Compara dos marcas; devuelve {'iguales': bool, 'diferencias': [...]}."""
    diffs: list[str] = []
    if a.seed != b.seed:
        diffs.append(f"seed: {a.seed} != {b.seed}")
    if a.version != b.version:
        diffs.append(f"version: {a.version} != {b.version}")
    if a.git_commit != b.git_commit:
        diffs.append(f"git_commit: {a.git_commit} != {b.git_commit}")
    if a.git_dirty != b.git_dirty:
        diffs.append(f"git_dirty: {a.git_dirty} != {b.git_dirty}")
    if a.params != b.params:
        diffs.append(f"params difieren: {sorted(set(a.params) ^ set(b.params)) or 'valores'}")
    for k in sorted(set(a.archivos) | set(b.archivos)):
        if a.archivos.get(k) != b.archivos.get(k):
            diffs.append(f"archivo {k}: hash distinto o ausente")
    if a.env_presentes != b.env_presentes:
        diffs.append(f"env presentes difieren: {sorted(set(a.env_presentes) ^ set(b.env_presentes))}")
    return {"iguales": not diffs, "diferencias": diffs}
