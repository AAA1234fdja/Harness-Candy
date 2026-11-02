"""Resumen extractivo de textos (sin LLM, solo stdlib) (v3 §5.6 modelos ligeros).

Algoritmo tipo TextRank-lite:
  1. segmentar en oraciones;
  2. puntuar palabras por frecuencia (sin stopwords del espanol);
  3. puntuar oraciones = suma normalizada de sus palabras;
  4. devolver las top-k en su orden original.

Con un LLM real se puede usar resumen abstractivo (``llm.ChatSession``);
aqui la version determinista sirve para ZEV/resúmenes rapidos sin costo.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

STOPWORDS_ES = frozenset(
    """a al como con de del desde e el en entre es esta estan este esta esto
    ha han hasta hay la las le les lo los mas me mi mis no o para pero por
    porque que se segun sin sobre su sus te tu tus un una uno y ya yo del
    una unos unas ser son fue eran sera seran""".split()
)

_SENT_RE = re.compile(r"(?<=[.!?¿¡])\s+")
_WORD_RE = re.compile(r"[a-záéíóúñ0-9]+", re.IGNORECASE)


@dataclass
class Summary:
    texto: str
    oraciones_seleccionadas: list[str]
    k: int
    proporcion: float

    def to_dict(self) -> dict:
        return {
            "texto": self.texto,
            "oraciones_seleccionadas": self.oraciones_seleccionadas,
            "k": self.k,
            "proporcion": round(self.proporcion, 4),
        }


def _oraciones(texto: str) -> list[str]:
    partes = [p.strip() for p in _SENT_RE.split(texto.strip()) if p.strip()]
    return partes or ([texto.strip()] if texto.strip() else [])


def _tokens(texto: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(texto) if t.lower() not in STOPWORDS_ES and len(t) > 2]


def summarize(texto: str, k: int = 3, *, min_palabras: int = 5) -> Summary:
    """Devuelve las k oraciones mas relevantes (extractivo), en orden original."""
    oraciones = _oraciones(texto)
    if not oraciones:
        return Summary("", [], k, 0.0)
    if len(oraciones) <= k:
        return Summary(" ".join(oraciones), list(oraciones), k, 1.0)
    k = max(1, min(k, len(oraciones)))
    freq = Counter(_tokens(texto))
    if not freq:
        # sin contenido: primeras k oraciones
        sel = oraciones[:k]
        return Summary(" ".join(sel), sel, k, k / len(oraciones))
    max_f = max(freq.values())
    pesos = {w: c / max_f for w, c in freq.items()}

    puntuadas: list[tuple[float, int, str]] = []
    for i, oracion in enumerate(oraciones):
        toks = _tokens(oracion)
        if len(toks) < min_palabras:
            puntuadas.append((0.0, i, oracion))
            continue
        score = sum(pesos.get(t, 0.0) for t in toks) / math.sqrt(len(toks))
        puntuadas.append((score, i, oracion))
    top = sorted(puntuadas, key=lambda x: x[0], reverse=True)[:k]
    seleccionadas = [o for _, _, o in sorted(top, key=lambda x: x[1])]
    return Summary(" ".join(seleccionadas), seleccionadas, k, k / len(oraciones))


def resumen_por_parrafos(texto: str, k_por_parrafo: int = 1) -> str:
    """Resume cada parrafo por separado (util para actas/informes largos)."""
    out = []
    for parrafo in texto.split("\n"):
        parrafo = parrafo.strip()
        if not parrafo:
            continue
        out.append(summarize(parrafo, k_por_parrafo).texto)
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# Keywords (TF-IDF-lite sobre un corpus dado) y deteccion de duplicados
# ---------------------------------------------------------------------------

def keywords(texto: str, *, top: int = 10, ngram: int = 1) -> list[tuple[str, float]]:
    """Extrae palabras clave por frecuencia (sin stopwords), opcionalmente n-gramas."""
    toks = [t for t in _tokens(texto) if t not in STOPWORDS_ES and len(t) > 2]
    if ngram > 1:
        extra = [" ".join(toks[i:i + ngram]) for i in range(len(toks) - ngram + 1)]
        toks = toks + extra
    freq = Counter(toks)
    total = sum(freq.values()) or 1
    return [(t, round(c / total, 6)) for t, c in freq.most_common(top)]


def tfidf_lite(corpus: list[str], *, top: int = 10) -> list[list[tuple[str, float]]]:
    """TF-IDF simple por documento sobre un corpus (idf = log(N/df))."""
    import math as _math

    n = len(corpus)
    docs_toks = [[t for t in _tokens(d) if t not in STOPWORDS_ES and len(t) > 2] for d in corpus]
    df: Counter = Counter()
    for toks in docs_toks:
        for t in set(toks):
            df[t] += 1
    out = []
    for toks in docs_toks:
        freq = Counter(toks)
        total = sum(freq.values()) or 1
        scores = {
            t: (c / total) * _math.log((n + 1) / (df[t] + 1)) + 0.0
            for t, c in freq.items()
        }
        out.append(sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top])
    return out


def _shingles(texto: str, k: int = 5) -> set[str]:
    # sin quitar stopwords: los shingles son sobre la secuencia cruda
    palabras = [t.lower() for t in _WORD_RE.findall(texto)]
    return {" ".join(palabras[i:i + k]) for i in range(max(0, len(palabras) - k + 1))}


def similitud_jaccard(a: str, b: str, *, k: int = 5) -> float:
    """Similitud de Jaccard sobre shingles (deteccion de near-duplicados)."""
    sa, sb = _shingles(a, k), _shingles(b, k)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def detectar_duplicados(textos: list[str], *, umbral: float = 0.8) -> list[tuple[int, int, float]]:
    """Pares (i, j, similitud) de textos casi duplicados (i < j)."""
    out = []
    for i in range(len(textos)):
        for j in range(i + 1, len(textos)):
            sim = similitud_jaccard(textos[i], textos[j])
            if sim >= umbral:
                out.append((i, j, round(sim, 4)))
    return out


def summarize_longitud(texto: str, *, max_palabras: int = 50) -> Summary:
    """Resumen extractivo acotado a ``max_palabras`` palabras en total."""
    import math as _math

    oraciones = _oraciones(texto)
    if not oraciones:
        return Summary(texto="", oraciones_seleccionadas=[], k=0, proporcion=0.0)
    k = max(1, min(len(oraciones), max(1, int(_math.ceil(max_palabras / 8)))))
    return summarize(texto, k=k)
