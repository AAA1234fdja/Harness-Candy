"""WorkBuddy: pipeline build -> login -> push -> run -> artefactos.

Orquesta un DockerRunner y un HarborClient sobre un proyecto empaquetado.
Pensado para correr un harness/evaluacion dentro de un contenedor y publicar
la imagen en Harbor (runtime), recogiendo los artefactos que deje el job.

Seguridad: WorkBuddy jamas recibe claves como argumento; HarborClient las toma
de HARBOR_USERNAME / HARBOR_PASSWORD del entorno. ``from_env`` falla con
HarborError si faltan.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from .docker_runner import DockerRunner
from .harbor import HarborClient, HarborError


@dataclass
class ResumenWorkBuddy:
    nombre: str
    tag_local: str
    tag_remoto: str
    pasos: list[dict] = field(default_factory=list)
    artefactos: list[str] = field(default_factory=list)
    ok: bool = True
    error: str = ""
    duracion: float = 0.0

    def to_dict(self) -> dict:
        return {
            "nombre": self.nombre,
            "tag_local": self.tag_local,
            "tag_remoto": self.tag_remoto,
            "ok": self.ok,
            "error": self.error,
            "duracion": round(self.duracion, 3),
            "pasos": self.pasos,
            "artefactos": self.artefactos,
        }


class WorkBuddy:
    """Orquestador build -> push -> run -> artefactos sobre Docker+Harbor."""

    def __init__(
        self,
        harbor: HarborClient,
        *,
        docker: Optional[DockerRunner] = None,
        workdir: str | Path = ".",
    ) -> None:
        self.harbor = harbor
        self.docker = docker or harbor.docker
        self.workdir = Path(workdir)

    @classmethod
    def from_env(
        cls,
        registry_url: str,
        *,
        proyecto: str = "library",
        dry_run: bool = False,
        workdir: str | Path = ".",
        environ: Optional[dict] = None,
    ) -> "WorkBuddy":
        """Construye el cliente leyendo credenciales SOLO del entorno."""
        docker = DockerRunner(dry_run=dry_run)
        harbor = HarborClient(registry_url, proyecto=proyecto, docker=docker, environ=environ)
        return cls(harbor, docker=docker, workdir=workdir)

    def _paso(self, pasos: list[dict], nombre: str, ok: bool, detalle: str = "") -> None:
        pasos.append({"paso": nombre, "ok": ok, "detalle": detalle})

    def run(
        self,
        nombre_imagen: str,
        *,
        dockerfile_dir: str | Path = ".",
        tag: str = "latest",
        comando: Sequence[str] = (),
        build_args: Optional[dict] = None,
        variables: Optional[list[str]] = None,
        volumenes: Optional[dict[str, str]] = None,
        artefactos_de: Optional[str] = None,
        artefactos_dir: str | Path = "artefactos",
        login: bool = True,
        push: bool = True,
    ) -> ResumenWorkBuddy:
        """Pipeline completo. ``comando`` son los args dentro del contenedor."""
        inicio = time.time()
        tag_local = f"{nombre_imagen}:{tag}"
        tag_remoto = self.harbor.imagen_tag(nombre_imagen, tag)
        resumen = ResumenWorkBuddy(nombre=nombre_imagen, tag_local=tag_local, tag_remoto=tag_remoto)
        try:
            r = self.docker.build(self.workdir / dockerfile_dir, tag_local, build_args=build_args)
            self._paso(resumen.pasos, "build", r.ok, r.stderr[-200:] if not r.ok else tag_local)
            if not r.ok:
                raise RuntimeError("build fallo")
            if login:
                r = self.harbor.login()
                self._paso(resumen.pasos, "login", r.ok, self.harbor.url)
                if not r.ok:
                    raise HarborError("login en Harbor fallo")
            if push:
                r = self.docker.tag(tag_local, tag_remoto)
                self._paso(resumen.pasos, "tag", r.ok, tag_remoto)
                r = self.docker.push(tag_remoto)
                self._paso(resumen.pasos, "push", r.ok, tag_remoto if r.ok else r.stderr[-200:])
                if not r.ok:
                    raise RuntimeError("push fallo")
            nombre_contenedor = f"wb-{nombre_imagen}-{int(inicio)}"
            r = self.docker.run(
                tag_local,
                comando,
                nombre=nombre_contenedor,
                volumenes=volumenes,
                variables=variables,
                quitar=True,
                workdir="/work",
            )
            self._paso(resumen.pasos, "run", r.ok, (r.stderr or r.stdout)[-300:])
            if artefactos_de:
                r = self.docker.copiar_artefactos(nombre_contenedor, artefactos_de, self.workdir / artefactos_dir)
                self._paso(resumen.pasos, "artefactos", r.ok, artefactos_de)
                dir_art = self.workdir / artefactos_dir
                if dir_art.exists():
                    resumen.artefactos = sorted(str(p.relative_to(self.workdir)) for p in dir_art.rglob("*") if p.is_file())
        except Exception as e:  # noqa: BLE001 - el pipeline marca el error y sigue trazable
            resumen.ok = False
            resumen.error = f"{type(e).__name__}: {e}"
            self._paso(resumen.pasos, "error", False, resumen.error)
        resumen.duracion = time.time() - inicio
        return resumen
