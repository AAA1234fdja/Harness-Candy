"""DockerRunner: envoltorio seguro del CLI docker.

- Todo comando pasa por ``_ejecutar(argv, stdin)``, que por defecto usa
  subprocess; en tests se inyecta un fake. En modo ``dry_run`` solo se imprime
  el comando (util para CI sin docker).
- Ningun metodo escribe credenciales en disco ni en logs: los secretos entran
  solo por stdin (ver HarborClient.login).
- ``run`` soporta montar volumenes (-v), variables (-e nombre, sin valor: se
  toman del entorno del proceso) y recolectar artefactos del contenedor.
"""
from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence


@dataclass
class ComandoResultado:
    argv: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return self.dry_run or self.returncode == 0

    def to_dict(self) -> dict:
        return {
            "argv": self.argv if not self.dry_run else self.argv,
            "returncode": self.returncode,
            "stdout": self.stdout[-2000:],
            "stderr": self.stderr[-2000:],
            "dry_run": self.dry_run,
        }


Ejecutar = Callable[[Sequence[str], Optional[str]], ComandoResultado]


def _ejecutar_subprocess(argv: Sequence[str], stdin: Optional[str] = None) -> ComandoResultado:
    proc = subprocess.run(
        list(argv),
        input=stdin,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    return ComandoResultado(list(argv), proc.returncode, proc.stdout, proc.stderr)


class DockerRunner:
    """Cliente minimo del CLI docker (build/tag/push/pull/run/images)."""

    def __init__(
        self,
        *,
        dry_run: bool = False,
        ejecutar: Optional[Ejecutar] = None,
        binario: str = "docker",
    ) -> None:
        self.dry_run = dry_run
        self.binario = binario
        self._ejecutar: Ejecutar = ejecutar or _ejecutar_subprocess
        self.historial: list[ComandoResultado] = []

    # ------------------------------------------------------------- interno
    def _cmd(self, args: Sequence[str], stdin: Optional[str] = None) -> ComandoResultado:
        argv = [self.binario, *args]
        if self.dry_run:
            res = ComandoResultado(argv, 0, stdout="(dry-run) " + " ".join(shlex.quote(a) for a in argv), dry_run=True)
        else:
            res = self._ejecutar(argv, stdin)
        self.historial.append(res)
        return res

    @staticmethod
    def _check(res: ComandoResultado, operacion: str) -> ComandoResultado:
        if not res.ok:
            raise RuntimeError(f"docker {operacion} fallo (rc={res.returncode}): {res.stderr.strip()[:500]}")
        return res

    # ------------------------------------------------------------- publico
    def disponible(self) -> bool:
        """True si el CLI docker responde (en dry_run siempre True)."""
        if self.dry_run:
            return True
        return self._cmd(["version", "--format", "{{.Server.Version}}"]).ok

    def build(self, dockerfile_dir: str | Path, tag: str, *, build_args: Optional[dict] = None) -> ComandoResultado:
        args = ["build", "-t", tag]
        for k, v in (build_args or {}).items():
            args += ["--build-arg", f"{k}={v}"]
        args += ["-f", str(Path(dockerfile_dir) / "Dockerfile"), str(dockerfile_dir)]
        return self._check(self._cmd(args), "build")

    def tag(self, origen: str, destino: str) -> ComandoResultado:
        return self._check(self._cmd(["tag", origen, destino]), "tag")

    def push(self, imagen: str) -> ComandoResultado:
        return self._check(self._cmd(["push", imagen]), "push")

    def pull(self, imagen: str) -> ComandoResultado:
        return self._check(self._cmd(["pull", imagen]), "pull")

    def login(self, registry: str, username: str, password: str) -> ComandoResultado:
        """Login con la clave SOLO por stdin (--password-stdin): nunca en argv."""
        if not password:
            raise ValueError("password vacio: configure HARBOR_PASSWORD en el entorno")
        return self._check(
            self._cmd(["login", registry, "-u", username, "--password-stdin"], stdin=password + "\n"),
            "login",
        )

    def run(
        self,
        imagen: str,
        comando: Sequence[str] = (),
        *,
        nombre: Optional[str] = None,
        volumenes: Optional[dict[str, str]] = None,
        variables: Optional[list[str]] = None,
        quitar: bool = True,
        workdir: Optional[str] = None,
    ) -> ComandoResultado:
        """Corre un contenedor. ``variables`` son NOMBRES de env (nunca valores)."""
        args = ["run", "--rm" if quitar else "-d"]
        if nombre:
            args += ["--name", nombre]
        if workdir:
            args += ["-w", workdir]
        for host, cont in (volumenes or {}).items():
            args += ["-v", f"{host}:{cont}"]
        for var in variables or []:
            args += ["-e", var]  # docker toma el valor del entorno del proceso
        args.append(imagen)
        args += list(comando)
        return self._cmd(args)

    def copiar_artefactos(self, contenedor: str, origen_dentro: str, destino: str | Path) -> ComandoResultado:
        Path(destino).mkdir(parents=True, exist_ok=True)
        return self._check(self._cmd(["cp", f"{contenedor}:{origen_dentro}", str(destino)]), "cp")

    def imagenes(self, filtro: Optional[str] = None) -> list[str]:
        args = ["images", "--format", "{{.Repository}}:{{.Tag}}"]
        if filtro:
            args += ["--filter", f"reference={filtro}"]
        res = self._cmd(args)
        if not res.ok:
            return []
        return [l.strip() for l in res.stdout.splitlines() if l.strip() and l.strip() != "<none>:<none>"]

    def info_json(self, imagen: str) -> dict:
        res = self._cmd(["inspect", "--format", "{{json .Config}}", imagen])
        if not res.ok:
            return {}
        try:
            return json.loads(res.stdout.strip() or "{}")
        except json.JSONDecodeError:
            return {}
