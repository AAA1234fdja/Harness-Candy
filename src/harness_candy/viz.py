"""Visualizacion en texto/HTML propio, solo stdlib (para reportes y terminal).

  - sparkline(datos) con bloques unicode
  - bar_chart(etiquetas, valores, ancho)
  - histogram(datos, bins)
  - table_html(headers, filas) tabla HTML minima
  - progress_bar(pct, ancho)
  - resumen_tabla(datos) describe + sparkline (para dashboards de corridas)
"""
from __future__ import annotations

from typing import Sequence

_BLOQUES = "▁▂▃▄▅▆▇█"


def sparkline(datos: Sequence[float]) -> str:
    """Sparklines unicode de una serie."""
    datos = list(datos)
    if not datos:
        return ""
    lo, hi = min(datos), max(datos)
    if hi == lo:
        return _BLOQUES[3] * len(datos)
    out = []
    for v in datos:
        idx = int((v - lo) / (hi - lo) * (len(_BLOQUES) - 1))
        out.append(_BLOQUES[idx])
    return "".join(out)


def bar_chart(etiquetas: Sequence[str], valores: Sequence[float], *, ancho: int = 40, unidad: str = "") -> str:
    """Grafico de barras horizontales en texto."""
    if len(etiquetas) != len(valores):
        raise ValueError("etiquetas y valores deben tener la misma longitud")
    if not valores:
        return ""
    max_v = max(valores) or 1.0
    ancho_etiqueta = max(len(str(e)) for e in etiquetas)
    lineas = []
    for et, v in zip(etiquetas, valores):
        n = int(round((v / max_v) * ancho)) if max_v else 0
        lineas.append(f"{str(et):>{ancho_etiqueta}} | {'█' * n} {v:g}{unidad}")
    return "\n".join(lineas)


def histogram(datos: Sequence[float], bins: int = 10) -> str:
    """Histograma en texto con barras ascii."""
    datos = list(datos)
    if not datos or bins < 1:
        return ""
    lo, hi = min(datos), max(datos)
    if hi == lo:
        return f"[{lo:g}] {'█' * len(datos)}"
    ancho = (hi - lo) / bins
    cuentas = [0] * bins
    for v in datos:
        idx = min(bins - 1, int((v - lo) / ancho))
        cuentas[idx] += 1
    max_c = max(cuentas) or 1
    lineas = []
    for i, c in enumerate(cuentas):
        inicio = lo + i * ancho
        n = int(round(c / max_c * 30))
        lineas.append(f"[{inicio:8.3f}, {inicio + ancho:8.3f}) {'█' * n} {c}")
    return "\n".join(lineas)


def progress_bar(pct: float, *, ancho: int = 30) -> str:
    """Barra de progreso 0..100."""
    pct = max(0.0, min(100.0, pct))
    lleno = int(round(pct / 100 * ancho))
    return "[" + "█" * lleno + "░" * (ancho - lleno) + f"] {pct:.0f}%"


def table_html(headers: Sequence[str], filas: Sequence[Sequence], *, clase: str = "hc-table") -> str:
    """Tabla HTML minima con escape."""
    import html

    def esc(x):
        return html.escape(str(x))

    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = ""
    for f in filas:
        body += "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in f) + "</tr>"
    return f'<table class="{clase}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def resumen_serie(nombre: str, datos: Sequence[float]) -> str:
    """Bloque resumen para dashboard: nombre, sparkline, min/med/max."""
    from .stats import describe

    if not datos:
        return f"{nombre}: sin datos"
    d = describe(datos)
    return (
        f"{nombre}: {sparkline(datos)}  "
        f"n={d['n']} min={d['min']:g} med={d['mediana']:g} max={d['max']:g} media={d['media']:g} desv={d['desv']:g}"
    )


def tarjeta_html(titulo: str, cuerpo_html: str, *, estilo: str = "") -> str:
    return (
        '<div class="hc-card" style="border:1px solid #ccc;border-radius:8px;padding:1rem;margin:.5rem;'
        f'{estilo}"><h3 style="margin-top:0">{titulo}</h3>{cuerpo_html}</div>'
    )


def line_chart(datos: Sequence[float], *, ancho: int = 50, alto: int = 10) -> str:
    """Grafico de linea ASCII en una rejilla ancho x alto."""
    datos = list(datos)
    if not datos:
        return ""
    lo, hi = min(datos), max(datos)
    if hi == lo:
        hi = lo + 1
    rejilla = [[" "] * ancho for _ in range(alto)]
    n = len(datos)
    puntos = []
    for i, v in enumerate(datos):
        x = int(i / max(1, n - 1) * (ancho - 1))
        y = int((v - lo) / (hi - lo) * (alto - 1))
        puntos.append((x, alto - 1 - y))
    for (x0, y0), (x1, y1) in zip(puntos, puntos[1:]):
        pasos = max(abs(x1 - x0), abs(y1 - y0), 1)
        for k in range(pasos + 1):
            x = x0 + (x1 - x0) * k // pasos
            y = y0 + (y1 - y0) * k // pasos
            rejilla[y][x] = "•"
    for x, y in puntos:
        rejilla[y][x] = "•"
    lineas = ["".join(fila) for fila in rejilla]
    lineas.append(f"min={lo:g} max={hi:g} n={n}")
    return "\n".join(lineas)


def heatmap(matriz: Sequence[Sequence[float]], *, escala: str = " .:-=+*#%@") -> str:
    """Mapa de calor ASCII de una matriz 2D."""
    plano = [v for fila in matriz for v in fila]
    if not plano:
        return ""
    lo, hi = min(plano), max(plano)
    if hi == lo:
        hi = lo + 1
    out = []
    for fila in matriz:
        out.append("".join(escala[int((v - lo) / (hi - lo) * (len(escala) - 1))] for v in fila))
    return "\n".join(out)
