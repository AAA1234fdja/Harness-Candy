"""RAG propio, solo stdlib (v3 §5.5 memoria de largo plazo con busqueda semantica).

Componentes:
* ``chunk_text``: chunking por caracteres con solapamiento y metadatos.
* ``BM25Index``: indice BM25 (lexico) propio.
* ``HashingEmbedder`` + ``VectorIndex``: embeddings por feature hashing de
  tokens (deterministas, sin modelo externo) + similitud coseno.
* ``HybridRetriever``: fusion RRF de BM25 + vectorial.
* ``RAGPipeline``: ingesta textos/archivos con procedencia, responde
  ``query`` devolviendo fragmentos con citas (formato zev: contenido +
  procedencia) y se puede persistir en JSON.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

_WORD_RE = re.compile(r"[a-záéíóúñ0-9]+", re.IGNORECASE)


def tokenize(texto: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(texto)]


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    contenido: str
    source: str
    start: int
    end: int
    indice: int = 0

    def to_dict(self) -> dict:
        return {"contenido": self.contenido, "source": self.source, "start": self.start, "end": self.end, "indice": self.indice}


def chunk_text(texto: str, *, size: int = 800, overlap: int = 120, source: str = "") -> list[Chunk]:
    """Parte el texto en chunks de ``size`` caracteres con ``overlap`` de solapamiento."""
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("size > 0 y 0 <= overlap < size")
    texto = texto.strip()
    if not texto:
        return []
    # cortar en limites de palabra cuando sea posible
    palabras = texto.split(" ")
    chunks: list[Chunk] = []
    paso = size - overlap
    pos = 0
    buf: list[str] = []
    i = 0
    while i < len(palabras):
        buf.append(palabras[i])
        i += 1
        if sum(len(w) + 1 for w in buf) >= size:
            contenido = " ".join(buf)
            chunks.append(Chunk(contenido, source, pos, pos + len(contenido), len(chunks)))
            # backtrack para solapamiento
            acum = 0
            nuevo_buf: list[str] = []
            for w in reversed(buf):
                if acum + len(w) + 1 > overlap:
                    break
                nuevo_buf.insert(0, w)
                acum += len(w) + 1
            buf = nuevo_buf
            pos += len(contenido) - overlap
    if buf:
        contenido = " ".join(buf)
        chunks.append(Chunk(contenido, source, pos, pos + len(contenido), len(chunks)))
    return chunks


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

class BM25Index:
    """Indice BM25 lexico (k1=1.5, b=0.75)."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: list[Chunk] = []
        self.doc_freqs: list[Counter] = []
        self.idf: dict[str, float] = {}
        self.doc_len: list[int] = []
        self.avg_len = 0.0

    def add(self, chunks: Iterable[Chunk]) -> None:
        for c in chunks:
            toks = tokenize(c.contenido)
            self.docs.append(c)
            self.doc_freqs.append(Counter(toks))
            self.doc_len.append(len(toks))
        self._recompute()

    def _recompute(self) -> None:
        n = len(self.docs)
        if n == 0:
            return
        df: Counter = Counter()
        for fd in self.doc_freqs:
            for t in fd:
                df[t] += 1
        self.idf = {t: math.log((n - c + 0.5) / (c + 0.5) + 1.0) for t, c in df.items()}
        self.avg_len = sum(self.doc_len) / n

    def search(self, query: str, k: int = 4) -> list[tuple[float, Chunk]]:
        if not self.docs:
            return []
        qtoks = tokenize(query)
        scores: list[tuple[float, int]] = []
        for i, fd in enumerate(self.doc_freqs):
            s = 0.0
            dl = self.doc_len[i] or 1
            for t in qtoks:
                if t not in fd:
                    continue
                idf = self.idf.get(t, 0.0)
                tf = fd[t]
                s += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * dl / (self.avg_len or 1)))
            if s > 0:
                scores.append((s, i))
        scores.sort(reverse=True)
        return [(s, self.docs[i]) for s, i in scores[:k]]


# ---------------------------------------------------------------------------
# Embeddings por feature hashing + coseno
# ---------------------------------------------------------------------------

class HashingEmbedder:
    """Embeddings deterministas por feature hashing de n-gramas (sin modelo)."""

    def __init__(self, dim: int = 256, ngram: int = 2):
        self.dim = dim
        self.ngram = ngram

    def embed(self, texto: str) -> list[float]:
        toks = tokenize(texto)
        vec = [0.0] * self.dim
        grams = list(toks)
        for n in range(2, self.ngram + 1):
            grams += [" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)]
        for g in grams:
            h = int(hashlib.sha256(g.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        norma = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norma for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1.0)


class VectorIndex:
    def __init__(self, embedder: Optional[HashingEmbedder] = None):
        self.embedder = embedder or HashingEmbedder()
        self.chunks: list[Chunk] = []
        self.vectores: list[list[float]] = []

    def add(self, chunks: Iterable[Chunk]) -> None:
        for c in chunks:
            self.chunks.append(c)
            self.vectores.append(self.embedder.embed(c.contenido))

    def search(self, query: str, k: int = 4) -> list[tuple[float, Chunk]]:
        if not self.chunks:
            return []
        qv = self.embedder.embed(query)
        scores = [(cosine(qv, v), c) for v, c in zip(self.vectores, self.chunks)]
        scores = [s for s in scores if s[0] > 0]
        scores.sort(key=lambda x: x[0], reverse=True)
        return scores[:k]

    def to_dict(self) -> dict:
        return {
            "dim": self.embedder.dim,
            "ngram": self.embedder.ngram,
            "chunks": [c.to_dict() for c in self.chunks],
            "vectores": self.vectores,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VectorIndex":
        emb = HashingEmbedder(dim=d.get("dim", 256), ngram=d.get("ngram", 2))
        vi = cls(emb)
        vi.chunks = [Chunk(**c) for c in d["chunks"]]
        vi.vectores = d["vectores"]
        return vi


# ---------------------------------------------------------------------------
# Recuperador hibrido (RRF)
# ---------------------------------------------------------------------------

class HybridRetriever:
    """Fusiona BM25 + vectorial con Reciprocal Rank Fusion (k=60)."""

    def __init__(self, bm25: BM25Index, vectores: VectorIndex, rrf_k: int = 60):
        self.bm25 = bm25
        self.vectores = vectores
        self.rrf_k = rrf_k

    def search(self, query: str, k: int = 4, *, rerank: bool = True, expand: bool = False) -> list[dict]:
        """RRF sobre los dos indices. Clave compartida = posicion del chunk
        (en RAGPipeline ambos indices reciben los mismos chunks en el mismo
        orden, asi que la posicion i es el mismo chunk en ambos)."""
        lex = self.bm25.search(query, k=k * 2)
        vec = self.vectores.search(query, k=k * 2)
        pos_bm25 = {id(c): i for i, c in enumerate(self.bm25.docs)}
        pos_vec = {id(c): i for i, c in enumerate(self.vectores.chunks)}
        scores: dict[int, float] = {}
        for rank, (s, chunk) in enumerate(lex):
            i = pos_bm25[id(chunk)]
            scores[i] = scores.get(i, 0.0) + 1.0 / (self.rrf_k + rank + 1)
        for rank, (s, chunk) in enumerate(vec):
            i = pos_vec[id(chunk)]
            scores[i] = scores.get(i, 0.0) + 1.0 / (self.rrf_k + rank + 1)
        if expand:
            query = expand_query(query, self.bm25)
            lex = self.bm25.search(query, k=k * 2)
            vec = self.vectores.search(query, k=k * 2)
            pos_bm25 = {id(c): i for i, c in enumerate(self.bm25.docs)}
            pos_vec = {id(c): i for i, c in enumerate(self.vectores.chunks)}
            scores = {}
            for rank, (s, chunk) in enumerate(lex):
                i = pos_bm25[id(chunk)]
                scores[i] = scores.get(i, 0.0) + 1.0 / (self.rrf_k + rank + 1)
            for rank, (s, chunk) in enumerate(vec):
                i = pos_vec[id(chunk)]
                scores[i] = scores.get(i, 0.0) + 1.0 / (self.rrf_k + rank + 1)
        ordenados = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
        out = []
        for i, s in ordenados:
            # preferimos el chunk del indice bm25 (fuente canonica)
            chunk = self.bm25.docs[i] if i < len(self.bm25.docs) else self.vectores.chunks[i]
            out.append({
                "score": round(s, 6),
                "contenido": chunk.contenido,
                "procedencia": chunk.source,
                "indice": chunk.indice,
            })
        if rerank:
            out = rerank_por_cobertura(query, out, k)
        return out


# ---------------------------------------------------------------------------
# Reranker por cobertura de terminos + expansion de query
# ---------------------------------------------------------------------------

def cobertura_terminos(query: str, doc: str) -> float:
    """Fraccion de terminos unicos de la query cubiertos por el doc (0..1)."""
    q = set(tokenize(query))
    if not q:
        return 0.0
    d = set(tokenize(doc))
    return len(q & d) / len(q)


def rerank_por_cobertura(query: str, resultados: list[dict], k: int | None = None) -> list[dict]:
    """Reordena resultados mezclando score RRF con cobertura de terminos."""
    if not resultados:
        return resultados
    max_score = max(r["score"] for r in resultados) or 1.0
    for r in resultados:
        r["cobertura"] = round(cobertura_terminos(query, r["contenido"]), 4)
        r["score_final"] = round(0.5 * (r["score"] / max_score) + 0.5 * r["cobertura"], 6)
    resultados.sort(key=lambda r: r["score_final"], reverse=True)
    return resultados[:k] if k else resultados


def expand_query(query: str, bm25: "BM25Index", max_extra: int = 3) -> str:
    """Anade a la query los terminos mas relevantes (mayor idf) de los docs top."""
    if not bm25.docs:
        return query
    top = bm25.search(query, k=3)
    freq: Counter = Counter()
    for _, chunk in top:
        for t in tokenize(chunk.contenido):
            freq[t] += 1
    qset = set(tokenize(query))
    extras = [t for t, _ in sorted(freq.items(), key=lambda kv: (bm25.idf.get(kv[0], 0.0), -kv[1])) if t not in qset][:max_extra]
    return query + (" " + " ".join(extras) if extras else "")


# ---------------------------------------------------------------------------
# Pipeline RAG completo (formato de respuesta compatible con zev)
# ---------------------------------------------------------------------------

class RAGPipeline:
    """Ingesta documentos y responde preguntas con fragmentos citado (zev)."""

    def __init__(self, *, chunk_size: int = 800, chunk_overlap: int = 120, dim: int = 256):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.bm25 = BM25Index()
        self.vectores = VectorIndex(HashingEmbedder(dim=dim))
        self.retriever = HybridRetriever(self.bm25, self.vectores)
        self.n_docs = 0

    def add_text(self, source: str, texto: str) -> int:
        chunks = chunk_text(texto, size=self.chunk_size, overlap=self.chunk_overlap, source=source)
        self.bm25.add(chunks)
        self.vectores.add(chunks)
        self.n_docs += 1
        return len(chunks)

    def add_file(self, path: str | Path) -> int:
        p = Path(path)
        return self.add_text(str(p), p.read_text(encoding="utf-8", errors="ignore"))

    def add_dir(self, directory: str | Path, *, globs: Iterable[str] = ("**/*.md", "**/*.txt", "**/*.py")) -> int:
        total = 0
        for g in globs:
            for p in Path(directory).glob(g):
                if p.is_file() and ".git" not in p.parts:
                    total += self.add_file(p)
        return total

    def query(self, pregunta: str, *, k: int = 4, rerank: bool = True, expand: bool = False) -> dict:
        """Devuelve {'consulta', 'fragmentos': [{contenido, procedencia, score, indice}]}."""
        fragmentos = self.retriever.search(pregunta, k=k, rerank=rerank, expand=expand)
        return {
            "consulta": pregunta,
            "n_fragmentos": len(fragmentos),
            "fragmentos": fragmentos,
            "nivel_confianza": round(fragmentos[0]["score"], 4) if fragmentos else 0.0,
        }

    def to_dict(self) -> dict:
        return {
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "n_docs": self.n_docs,
            "bm25_docs": [c.to_dict() for c in self.bm25.docs],
            "vector_index": self.vectores.to_dict(),
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "RAGPipeline":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        pipe = cls(chunk_size=d["chunk_size"], chunk_overlap=d["chunk_overlap"], dim=d["vector_index"]["dim"])
        chunks = [Chunk(**c) for c in d["bm25_docs"]]
        pipe.bm25.add(chunks)
        pipe.vectores = VectorIndex.from_dict(d["vector_index"])
        pipe.retriever = HybridRetriever(pipe.bm25, pipe.vectores)
        pipe.n_docs = d["n_docs"]
        return pipe

    def stats(self) -> dict:
        return {"docs": self.n_docs, "chunks": len(self.bm25.docs), "dim": self.vectores.embedder.dim}


# ---------------------------------------------------------------------------
# Evaluacion de la recuperacion: recall@k y MRR sobre pares (query, doc_esperado)
# ---------------------------------------------------------------------------

def evaluate_retrieval(pipe: "RAGPipeline", pares: list[tuple[str, str]], *, k: int = 4) -> dict:
    """Evalua el pipeline: para cada (pregunta, source_esperado) mira si el
    fragmento top-k es del source esperado. Devuelve recall@k y MRR."""
    hits = 0
    rr = 0.0
    for pregunta, esperado in pares:
        res = pipe.query(pregunta, k=k, rerank=False)
        procedencias = [f["procedencia"] for f in res["fragmentos"]]
        if esperado in procedencias:
            hits += 1
            rr += 1.0 / (procedencias.index(esperado) + 1)
    n = len(pares) or 1
    return {
        "n_consultas": len(pares),
        "k": k,
        "recall_at_k": round(hits / n, 4),
        "mrr": round(rr / n, 4),
    }
