"""jb_runner: cola de jobs con prioridad, store/checkpoint JSON y resume.

Paquete de tercera parte empaquetado con Harness-Candy (stdlib-only, sin
dependencias externas). Pensado para lanzar corridas de evaluacion de
harnesses en cola: cada job tiene prioridad, reintentos y su estado se
persiste en disco para reanudar una corrida interrumpida sin repetir trabajo.

Uso tipico::

    from jb_runner import Job, JobRunner, JobStore

    store = JobStore("/tmp/jobs.json")
    runner = JobRunner(store, ejecutar=mi_evaluador)
    resumen = runner.run([Job("a", prioridad=10), Job("b", prioridad=1)])
"""
from .core import (
    ESTADO_OK,
    ESTADO_PENDIENTE,
    ESTADO_FALLIDO,
    Job,
    JobQueue,
    JobStore,
    ResumenCorrida,
    ResultadoJob,
    JobRunner,
)

__all__ = [
    "ESTADO_OK",
    "ESTADO_PENDIENTE",
    "ESTADO_FALLIDO",
    "Job",
    "JobQueue",
    "JobStore",
    "ResumenCorrida",
    "ResultadoJob",
    "JobRunner",
]

__version__ = "0.1.0"
