"""HarborClient: cliente del registry Harbor (runtime de WorkBuddy).

Politica de seguridad estricta:
- Las credenciales SOLO se leen de las variables de entorno
  ``HARBOR_USERNAME`` y ``HARBOR_PASSWORD`` (o del dict ``environ`` inyectado
  en tests). NUNCA se aceptan como argumento de linea de comandos, nunca se
  escriben a disco ni a logs.
- El login se hace via ``docker login --password-stdin`` pasando la clave por
  stdin: no aparece en ``ps`` ni en el historial del runner.
- La API REST usa un ``transport`` inyectable (por defecto urllib) para poder
  probar sin red; el token Basic se construye en memoria y solo vive en el
  header Authorization de cada request.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from .docker_runner import DockerRunner, ComandoResultado

HARBOR_USERNAME_ENV = "HARBOR_USERNAME"
HARBOR_PASSWORD_ENV = "HARBOR_PASSWORD"


class HarborError(RuntimeError):
    """Fallo de autenticacion o de la API de Harbor."""


@dataclass
class RepoInfo:
    nombre: str
    artefactos: int = 0
    tamano_bytes: int = 0
    ultima_actualizacion: str = ""

    def to_dict(self) -> dict:
        return {
            "nombre": self.nombre,
            "artefactos": self.artefactos,
            "tamano_bytes": self.tamano_bytes,
            "ultima_actualizacion": self.ultima_actualizacion,
        }


Transport = Callable[[urllib.request.Request, int], "object"]


def _transport_urllib(req: urllib.request.Request, timeout: int = 30):
    return urllib.request.urlopen(req, timeout=timeout)


class HarborClient:
    """Cliente de un registry Harbor: login + API REST (v2)."""

    def __init__(
        self,
        url: str,
        *,
        proyecto: str = "library",
        docker: Optional[DockerRunner] = None,
        environ: Optional[dict] = None,
        transport: Optional[Transport] = None,
        timeout: int = 30,
    ) -> None:
        self.url = url.rstrip("/")
        self.proyecto = proyecto.strip("/")
        self.docker = docker or DockerRunner()
        self._environ = environ if environ is not None else dict(os.environ)
        self._transport: Transport = transport or _transport_urllib
        self.timeout = timeout
        self._logueado = False

    # --------------------------------------------------------- credenciales
    def credenciales(self) -> tuple[str, str]:
        """Lee usuario/clave SOLO del entorno. Lanza HarborError si faltan."""
        user = self._environ.get(HARBOR_USERNAME_ENV, "")
        password = self._environ.get(HARBOR_PASSWORD_ENV, "")
        if not user or not password:
            raise HarborError(
                f"faltan credenciales: defina {HARBOR_USERNAME_ENV} y {HARBOR_PASSWORD_ENV} en el entorno"
            )
        return user, password

    # ------------------------------------------------------------------ login
    def login(self) -> ComandoResultado:
        """docker login con --password-stdin (la clave viaja por stdin)."""
        user, password = self.credenciales()
        res = self.docker.login(self.url, user, password)
        if res.ok:
            self._logueado = True
        return res

    def imagen_tag(self, nombre_imagen: str, tag: str) -> str:
        """Etiqueta completa para Harbor: url/proyecto/nombre:tag."""
        return f"{self.url}/{self.proyecto}/{nombre_imagen}:{tag}"

    # -------------------------------------------------------------- API REST
    def _request(self, path: str, *, metodo: str = "GET") -> dict | list:
        user, password = self.credenciales()
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        url = f"https://{self.url}/api/v2.0/{path.lstrip('/')}"
        req = urllib.request.Request(url, method=metodo)
        req.add_header("Authorization", f"Basic {token}")  # solo en memoria/header
        try:
            with self._transport(req, self.timeout) as resp:
                cuerpo = resp.read()
        except Exception as e:  # noqa: BLE001 - cualquier fallo de red es HarborError
            raise HarborError(f"API Harbor fallo en {metodo} {path}: {type(e).__name__}: {e}") from e
        if not cuerpo:
            return {}
        return json.loads(cuerpo.decode("utf-8"))

    def listar_repositorios(self) -> list[RepoInfo]:
        data = self._request(f"projects/{self.proyecto}/repositories?page_size=100")
        if isinstance(data, dict):
            data = data.get("items", [])
        repos = []
        for r in data or []:
            repos.append(
                RepoInfo(
                    nombre=r.get("name", ""),
                    artefactos=int(r.get("artifact_count", 0)),
                    tamano_bytes=int(r.get("size", 0)),
                    ultima_actualizacion=str(r.get("update_time", "")),
                )
            )
        return repos

    def artefactos(self, repo: str) -> list[dict]:
        data = self._request(f"projects/{self.proyecto}/repositories/{repo}/artifacts?page_size=100")
        if isinstance(data, dict):
            data = data.get("items", [])
        return list(data or [])

    def estadistica_imagen(self, repo: str, referencia: str) -> dict:
        """Detalle de un artefacto concreto (digest, tags, tamano)."""
        return self._request(
            f"projects/{self.proyecto}/repositories/{repo}/artifacts/{referencia}"
        )
