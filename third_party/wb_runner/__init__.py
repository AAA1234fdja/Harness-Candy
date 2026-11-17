"""wb_runner: WorkBuddy — orquestacion build -> push -> run -> artefactos.

Paquete de tercera parte empaquetado con Harness-Candy (stdlib-only).

Componentes:
- ``DockerRunner``: envoltorio del CLI ``docker`` con modo ``dry_run`` (imprime
  los comandos sin ejecutarlos) y ``ejecutar`` inyectable para tests.
- ``HarborClient``: cliente del registry Harbor. Las credenciales SOLO salen
  de las variables de entorno ``HARBOR_USERNAME`` / ``HARBOR_PASSWORD`` y se
  pasan a ``docker login`` por stdin (``--password-stdin``): nunca aparecen en
  argv, logs ni archivos. La API REST usa transport inyectable.
- ``WorkBuddy``: pipeline completo sobre un workdir de proyecto.

Uso tipico::

    from wb_runner import WorkBuddy

    wb = WorkBuddy.from_env("registry.empresa.co", proyecto="harness-candy")
    resumen = wb.run("mi-imagen", dockerfile_dir=".", comando=["python", "-m", "app"])
"""
from .docker_runner import DockerRunner, ComandoResultado
from .harbor import HarborClient, HarborError
from .workbuddy import WorkBuddy, ResumenWorkBuddy

__all__ = [
    "DockerRunner",
    "ComandoResultado",
    "HarborClient",
    "HarborError",
    "WorkBuddy",
    "ResumenWorkBuddy",
]

__version__ = "0.1.0"
