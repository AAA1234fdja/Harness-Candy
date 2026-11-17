"""lab_runner: experimentos con grid de parametros y reporte con estadistica.

Paquete de tercera parte empaquetado con Harness-Candy (stdlib-only).
Sirve para barrer hiperparametros de un harness (k, m, temperatura...) en
paralelo local (ThreadPoolExecutor), quedarse con la mejor configuracion y
reportar media e intervalo de confianza bootstrap del score.

Uso tipico::

    from lab_runner import Experimento

    exp = Experimento("sweep-k", grid={"k": [1, 2, 4], "m": [2, 3]}, ejecutar=mi_eval)
    res = exp.correr()
    print(res.mejor_params, res.mejor_score, res.ic95)
    print(res.reporte_md())
"""
from .experiment import Experimento, PuntoGrid, ResultadoLab, media, ic95_bootstrap, desviacion

__all__ = [
    "Experimento",
    "PuntoGrid",
    "ResultadoLab",
    "media",
    "ic95_bootstrap",
    "desviacion",
]

__version__ = "0.1.0"
