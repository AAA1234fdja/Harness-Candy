"""Estadistica descriptiva e inferencial propia, solo stdlib (math + math.erf).

Incluye lo que el sistema necesita para evaluar corridas sin scipy:
  - descriptiva: mean, variance, stdev, median, percentil, iqr, describe
  - correlacion: pearson, spearman (rangos), kendall tau-a
  - distribuciones: normal_cdf (via math.erf), _gammainc (serie + fraccion
    continua), _betai (fraccion continua) -> p-valores de chi2, t y F
  - inferencia: ic_media (t), ic_proporcion_wilson, chi2_contingencia,
    anova_oneway, bootstrap_ci (generico sobre cualquier estadistico)

Usado por evalsuite (intervalos del pass_rate) y por quality (decisiones
estadisticas). Todo determinista.
"""
from __future__ import annotations

import math
import random
from typing import Any, Callable, Sequence


# ---------------------------------------------------------------------------
# Descriptiva
# ---------------------------------------------------------------------------

def mean(xs: Sequence[float]) -> float:
    xs = list(xs)
    if not xs:
        raise ValueError("media de secuencia vacia")
    return sum(xs) / len(xs)


def variance(xs: Sequence[float], *, muestral: bool = True) -> float:
    xs = list(xs)
    n = len(xs)
    if n < 2 and muestral:
        raise ValueError("varianza muestral requiere n >= 2")
    m = mean(xs)
    denom = n - 1 if muestral else n
    return sum((x - m) ** 2 for x in xs) / denom


def stdev(xs: Sequence[float], *, muestral: bool = True) -> float:
    return math.sqrt(variance(xs, muestral=muestral))


def median(xs: Sequence[float]) -> float:
    return percentil(50, xs)


def percentil(p: float, xs: Sequence[float]) -> float:
    """Percentil p (0-100) con interpolacion lineal (metodo 'linear')."""
    if not 0 <= p <= 100:
        raise ValueError("p fuera de [0, 100]")
    datos = sorted(xs)
    if not datos:
        raise ValueError("percentil de secuencia vacia")
    if len(datos) == 1:
        return float(datos[0])
    k = (len(datos) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(datos[int(k)])
    return datos[f] + (datos[c] - datos[f]) * (k - f)


def iqr(xs: Sequence[float]) -> float:
    return percentil(75, xs) - percentil(25, xs)


def describe(xs: Sequence[float]) -> dict[str, float]:
    xs = list(xs)
    if not xs:
        raise ValueError("describe de vacio")
    return {
        "n": len(xs),
        "media": round(mean(xs), 6),
        "mediana": round(median(xs), 6),
        "desv": round(stdev(xs), 6) if len(xs) >= 2 else 0.0,
        "min": min(xs),
        "p25": round(percentil(25, xs), 6),
        "p50": round(percentil(50, xs), 6),
        "p75": round(percentil(75, xs), 6),
        "max": max(xs),
        "iqr": round(iqr(xs), 6),
    }


# ---------------------------------------------------------------------------
# Correlacion
# ---------------------------------------------------------------------------

def _rangos(xs: Sequence[float]) -> list[float]:
    """Rangos con empate a media (para Spearman)."""
    orden = sorted(range(len(xs)), key=lambda i: xs[i])
    rangos = [0.0] * len(xs)
    i = 0
    while i < len(orden):
        j = i
        while j + 1 < len(orden) and xs[orden[j + 1]] == xs[orden[i]]:
            j += 1
        media = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            rangos[orden[k]] = media
        i = j + 1
    return rangos


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("pearson requiere misma longitud >= 2")
    mx, my = mean(x), mean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if sx == 0 or sy == 0:
        return 0.0
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return cov / (sx * sy)


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("spearman requiere misma longitud >= 2")
    return pearson(_rangos(list(x)), _rangos(list(y)))


def kendall_tau(x: Sequence[float], y: Sequence[float]) -> float:
    """Tau-a de Kendall (sin correccion por empates)."""
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("kendall requiere misma longitud >= 2")
    n = len(x)
    concordantes = discordantes = 0
    for i in range(n):
        for j in range(i + 1, n):
            sx = (x[i] - x[j])
            sy = (y[i] - y[j])
            if sx == 0 or sy == 0:
                continue
            if sx * sy > 0:
                concordantes += 1
            else:
                discordantes += 1
    denom = n * (n - 1) / 2.0
    return (concordantes - discordantes) / denom


# ---------------------------------------------------------------------------
# Distribuciones (p-valores propios)
# ---------------------------------------------------------------------------

def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _gammln(xx: float) -> float:
    cof = [76.18009172947146, -86.50532032941677, 24.01409824083091,
           -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5]
    x = xx
    y = xx
    tmp = x + 5.5
    tmp -= (x + 0.5) * math.log(tmp)
    ser = 1.000000000190015
    for j in range(6):
        y += 1
        ser += cof[j] / y
    return -tmp + math.log(2.5066282746310005 * ser / x)


def _gammainc_lower(a: float, x: float) -> float:
    """P(a, x) gamma incompleta inferior (serie para x < a+1, fraccion continua si no)."""
    if x <= 0:
        return 0.0
    if x < a + 1.0:
        ap = a
        summ = 1.0 / a
        delt = summ
        for _ in range(200):
            ap += 1
            delt *= x / ap
            summ += delt
            if abs(delt) < abs(summ) * 1e-14:
                break
        return summ * math.exp(-x + a * math.log(x) - _gammln(a))
    # fraccion continua (Lentz)
    b = x + 1.0 - a
    c = 1.0e30
    d = 1.0 / b
    h = d
    for i in range(1, 200):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-30:
            d = 1e-30
        c = b + an / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delt = d * c
        h *= delt
        if abs(delt - 1.0) < 1e-14:
            break
    return 1.0 - math.exp(-x + a * math.log(x) - _gammln(a)) * h


def chi2_sf(x: float, gl: float) -> float:
    """Cola superior de chi2: P(X > x) con gl grados de libertad."""
    if x <= 0:
        return 1.0
    return 1.0 - _gammainc_lower(gl / 2.0, x / 2.0)


def _betacf(a: float, b: float, x: float) -> float:
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delt = d * c
        h *= delt
        if abs(delt - 1.0) < 1e-14:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """I_x(a, b) beta incompleta regularizada."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(_gammln(a + b) - _gammln(a) - _gammln(b) + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


# t de Student con gl grados (cola superior, aproximacion via beta)
_T_TABLE = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
            12: 2.179, 15: 2.131, 20: 2.086, 25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980}


def t_sf(t: float, gl: int) -> float:
    """P(T > t) para t de Student con gl grados (dos colas simetricas: usa |t|)."""
    if gl < 1:
        raise ValueError("gl >= 1")
    x = gl / (gl + t * t)
    return 0.5 * _betai(gl / 2.0, 0.5, x)  # una cola


def t_crit(alpha_two_sided: float, gl: int) -> float:
    """Valor critico t para nivel alpha (dos colas) aproximado desde tabla."""
    if gl >= 120:
        # aproximacion normal
        from math import sqrt
        z = 1.959964  # alpha=0.05
        # aproximacion simple por tabla conocido; para otros alpha usar busqueda sobre normal_cdf
        lo, hi = 0.0, 10.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if 2 * (1 - normal_cdf(mid)) > alpha_two_sided:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    claves = sorted(_T_TABLE)
    if gl <= 1:
        return _T_TABLE[1]
    # interpolar en la tabla segun gl (tabla para alpha=0.05); para otros alpha, escalar con normal
    inferior = max(k for k in claves if k <= gl)
    superior = min(k for k in claves if k >= gl)
    if inferior == superior:
        base = _T_TABLE[inferior]
    else:
        w = (gl - inferior) / (superior - inferior)
        base = _T_TABLE[inferior] * (1 - w) + _T_TABLE[superior] * w
    if abs(alpha_two_sided - 0.05) < 1e-9:
        return base
    # escala por la razon de cuantiles normales
    lo, hi = 0.0, 10.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if 2 * (1 - normal_cdf(mid)) > alpha_two_sided:
            lo = mid
        else:
            hi = mid
    z_alpha = (lo + hi) / 2
    return base * (z_alpha / 1.959964)


def f_sf(f: float, gl1: float, gl2: float) -> float:
    """Cola superior de F: P(F > f)."""
    if f <= 0:
        return 1.0
    x = gl2 / (gl2 + gl1 * f)
    return _betai(gl2 / 2.0, gl1 / 2.0, x)


# ---------------------------------------------------------------------------
# Inferencia
# ---------------------------------------------------------------------------

def ic_media(xs: Sequence[float], alpha: float = 0.05) -> tuple[float, float]:
    """Intervalo de confianza de la media (t de Student)."""
    xs = list(xs)
    n = len(xs)
    if n < 2:
        m = mean(xs) if xs else 0.0
        return (m, m)
    m = mean(xs)
    s = stdev(xs)
    t = t_crit(alpha, n - 1)
    margen = t * s / math.sqrt(n)
    return (m - margen, m + margen)


def ic_proporcion_wilson(exitos: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """IC de Wilson para una proporcion (mejor cobertura que el normal approx)."""
    if n == 0:
        return (0.0, 1.0)
    z = t_crit(alpha, 10_000)  # ~ z normal
    p = exitos / n
    denom = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / denom
    margen = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def chi2_contingencia(tabla: Sequence[Sequence[float]]) -> dict[str, float]:
    """Chi2 de independencia sobre tabla de contingencia (con correccion de Yates si 2x2)."""
    filas = [sum(r) for r in tabla]
    cols = [sum(tabla[i][j] for i in range(len(tabla))) for j in range(len(tabla[0]))]
    n = sum(filas)
    if n == 0:
        raise ValueError("tabla vacia")
    chi2 = 0.0
    yates = len(tabla) == 2 and len(tabla[0]) == 2
    for i, fila in enumerate(tabla):
        for j, obs in enumerate(fila):
            esp = filas[i] * cols[j] / n
            if esp <= 0:
                continue
            dif = abs(obs - esp) - (0.5 if yates else 0.0)
            if dif < 0:
                dif = 0.0
            chi2 += dif * dif / esp
    gl = (len(tabla) - 1) * (len(tabla[0]) - 1)
    return {"chi2": round(chi2, 6), "gl": gl, "p": round(chi2_sf(chi2, gl), 6)}


def anova_oneway(grupos: Sequence[Sequence[float]]) -> dict[str, float]:
    """ANOVA de un factor: F y p-valor."""
    grupos = [list(g) for g in grupos if len(g) > 0]
    k = len(grupos)
    if k < 2:
        raise ValueError("anova requiere >= 2 grupos")
    n = sum(len(g) for g in grupos)
    media_total = sum(sum(g) for g in grupos) / n
    ssb = sum(len(g) * (mean(g) - media_total) ** 2 for g in grupos)  # entre grupos
    ssw = sum(sum((x - mean(g)) ** 2 for x in g) for g in grupos)  # intra
    gl1 = k - 1
    gl2 = n - k
    if gl2 <= 0 or ssw == 0:
        return {"F": float("inf") if ssb > 0 else 0.0, "gl1": gl1, "gl2": gl2, "p": 0.0 if ssb > 0 else 1.0}
    f = (ssb / gl1) / (ssw / gl2)
    return {"F": round(f, 6), "gl1": gl1, "gl2": gl2, "p": round(f_sf(f, gl1, gl2), 6)}


def bootstrap_ci(
    datos: Sequence[Any],
    stat: Callable[[list], float] = mean,
    *,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float, float]:
    """IC percentil bootstrap de cualquier estadistico. Devuelve (p_alpha/2, mediana, p_1-alpha/2)."""
    datos = list(datos)
    if not datos:
        raise ValueError("bootstrap de vacio")
    rng = random.Random(seed)
    n = len(datos)
    vals = []
    for _ in range(n_boot):
        muestra = [datos[rng.randrange(n)] for _ in range(n)]
        vals.append(stat(muestra))
    vals.sort()
    lo = vals[int((alpha / 2) * len(vals))]
    hi = vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))]
    return (lo, vals[len(vals) // 2], hi)
