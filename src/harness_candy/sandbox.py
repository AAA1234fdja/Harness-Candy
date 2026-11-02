"""Sandbox efimero y red restringida para XEV (secciones 9 y 13).

Harness^2 no restringe la red de su ejecutor por defecto: aqui el codigo
generado SIEMPRE corre aislado:

* directorio de trabajo efimero (se crea y se borra),
* timeout estricto,
* sin red por defecto: si ``unshare`` esta disponible se ejecuta dentro de
  un namespace de red propio (``unshare -rn``); si no, se ejecuta con un
  entorno minimo y se marca ``network_isolated=False`` para auditarlo,
* variables de entorno minimas (sin credenciales heredadas).

Objetivo del documento: 0 fallos de aislamiento en cada version.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

_UNSHARE_OK: bool | None = None


def _probe_unshare() -> bool:
    global _UNSHARE_OK
    if _UNSHARE_OK is None:
        unshare = shutil.which("unshare")
        if not unshare:
            _UNSHARE_OK = False
        else:
            try:
                r = subprocess.run(
                    [unshare, "-rn", "true"], capture_output=True, timeout=5
                )
                _UNSHARE_OK = r.returncode == 0
            except Exception:
                _UNSHARE_OK = False
    return _UNSHARE_OK


@dataclass
class SandboxResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    duration: float
    workdir: str
    network_isolated: bool
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout[-4000:],
            "stderr": self.stderr[-4000:],
            "timed_out": self.timed_out,
            "duration": round(self.duration, 3),
            "network_isolated": self.network_isolated,
        }


def run_sandboxed(
    command: list[str] | str,
    *,
    timeout: float = 30.0,
    allow_network: bool = False,
    env: dict | None = None,
    extra_files: dict[str, str] | None = None,
) -> SandboxResult:
    """Ejecuta ``command`` aislado. Devuelve SandboxResult con la evidencia."""
    cmd = [command] if isinstance(command, str) else list(command)
    workdir = tempfile.mkdtemp(prefix="xev-sandbox-")
    if extra_files:
        for name, content in extra_files.items():
            (tempfile.Path(workdir) / name).write_text(content, encoding="utf-8")
    isolated = False
    final_cmd = list(cmd)
    if not allow_network and _probe_unshare():
        # -r: mapea el usuario a root dentro del namespace; -n: sin red;
        # --kill-child: mata el proceso si el padre muere (util-linux >= 2.36)
        final_cmd = ["unshare", "-rn", "--kill-child", *cmd]
        isolated = True
    base_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": workdir,
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if env:
        base_env.update(env)
    start = time.time()
    timed_out = False
    try:
        proc = subprocess.run(
            final_cmd,
            cwd=workdir,
            env=base_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        timed_out = True
        rc = -1
        out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = (e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        err += f"\n[timeout] comando excedio {timeout}s"
    duration = time.time() - start
    try:
        shutil.rmtree(workdir, ignore_errors=True)
    except Exception:
        pass
    return SandboxResult(
        command=cmd,
        returncode=rc,
        stdout=out,
        stderr=err,
        timed_out=timed_out,
        duration=duration,
        workdir=workdir,
        network_isolated=isolated,
        extra={"cwd_efimero": True},
    )
