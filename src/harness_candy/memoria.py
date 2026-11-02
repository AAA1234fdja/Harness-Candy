"""Memoria administrada en tres capas (carpeta ``memoria/`` del repo).

Diseno pedido por el usuario:

- ``memoria/cache/``      datos MOMENTANEOS: cada entrada tiene TTL y
  ``purgar_cache()`` borra las expiradas. No se commitea (va al .gitignore).
- ``memoria/chat/``       datos BUSCABLES dentro del PROYECTO:
  ``memoria/chat/<proyecto>/<id>.json``. Solo se admiten las cosas mas
  relevantes (``relevancia >= umbral``); el resto se rechaza.
- ``memoria/ecosistema/`` memoria GLOBAL entre proyectos:
  ``memoria/ecosistema/<id>.json``, con ``proyecto`` como etiqueta de origen.

Regla comun a las tres capas: una entrada NO es un volcado, es
``tipo + idea + explicacion`` de MAXIMO 300 palabras (fail-closed: se rechaza
la entrada que se pase). La busqueda es BM25 lexico (reusa rag.BM25Index).

Uso::

    from harness_candy.memoria import GestorMemoria

    g = GestorMemoria("memoria")
    g.guardar_chat("Harness-Candy", "decision", "usamos BM25 local", "sin dependencias", relevancia=0.9)
    g.guardar_cache("borrador", "estado", "compilando ola 7", ttl=600)
    g.guardar_ecosistema("patron", "300 palabras", "cada entrada es tipo+idea+explicacion", proyecto="Harness-Candy")
    for score, entrada in g.buscar("chat", "por que BM25?", proyecto="Harness-Candy"):
        print(score, entrada.idea)
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from .rag import BM25Index, Chunk

CAPA_CACHE = "cache"
CAPA_CHAT = "chat"
CAPA_ECOSISTEMA = "ecosistema"
CAPAS = (CAPA_CACHE, CAPA_CHAT, CAPA_ECOSISTEMA)

MAX_PALABRAS = 300
UMBRAL_RELEVANCIA = 0.5
TTL_CACHE_DEFAULT = 3600.0  # 1 hora: la cache es momentanea


class EntradaLargaError(ValueError):
    """La entrada supera MAX_PALABRAS (tipo + idea + explicacion)."""


class CapaDesconocidaError(ValueError):
    pass


def contar_palabras(texto: str) -> int:
    return len(texto.split())


def _slug(texto: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")
    return s[:max_len] or "entrada"


@dataclass
class EntradaMemoria:
    """Una entrada de memoria: tipo + idea + explicacion (<= 300 palabras)."""

    id: str
    capa: str
    tipo: str            # p.ej. "decision", "patron", "hallazgo", "borrador"
    idea: str            # la idea central en una linea
    explicacion: str     # el por que / contexto, acotado
    proyecto: str = ""   # obligatorio en chat; etiqueta de origen en ecosistema
    tags: list[str] = field(default_factory=list)
    creado_en: float = field(default_factory=time.time)
    expira_en: float = 0.0    # solo cache (TTL); 0 = sin expiracion
    relevancia: float = 1.0    # solo chat (admission control)
    palabras: int = 0

    def texto_busqueda(self) -> str:
        return " ".join([self.tipo, self.idea, self.explicacion, " ".join(self.tags), self.proyecto])

    @property
    def expirada(self) -> bool:
        return self.capa == CAPA_CACHE and self.expira_en > 0 and time.time() > self.expira_en

    def to_dict(self) -> dict:
        d = asdict(self)
        d["expirada"] = self.expirada
        return d

    @staticmethod
    def from_dict(d: dict) -> "EntradaMemoria":
        return EntradaMemoria(**{k: d.get(k) for k in (
            "id", "capa", "tipo", "idea", "explicacion", "proyecto", "tags",
            "creado_en", "expira_en", "relevancia", "palabras")})


def validar_entrada(tipo: str, idea: str, explicacion: str) -> int:
    """Fail-closed: rechaza entradas de mas de MAX_PALABRAS palabras."""
    if not tipo.strip() or not idea.strip():
        raise ValueError("tipo e idea son obligatorios y no pueden ser vacios")
    n = contar_palabras(f"{tipo} {idea} {explicacion}")
    if n > MAX_PALABRAS:
        raise EntradaLargaError(
            f"la entrada tiene {n} palabras (> {MAX_PALABRAS}): resuma tipo+idea+explicacion"
        )
    return n


class GestorMemoria:
    """Administra la carpeta ``memoria/`` con sus tres capas."""

    def __init__(self, root: str | Path = "memoria", *, umbral_relevancia: float = UMBRAL_RELEVANCIA) -> None:
        self.root = Path(root)
        self.umbral_relevancia = umbral_relevancia
        for capa in CAPAS:
            (self.root / capa).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- rutas
    def _dir_capa(self, capa: str, proyecto: str = "") -> Path:
        if capa not in CAPAS:
            raise CapaDesconocidaError(f"capa desconocida {capa!r}; use {CAPAS}")
        d = self.root / capa
        if capa == CAPA_CHAT:
            if not proyecto:
                raise ValueError("la capa chat requiere proyecto")
            d = d / _slug(proyecto, 60)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _path_entrada(self, capa: str, id_entrada: str, proyecto: str = "") -> Path:
        return self._dir_capa(capa, proyecto) / f"{id_entrada}.json"

    def _nuevo_id(self, capa: str, tipo: str, proyecto: str = "") -> str:
        base = f"{int(time.time() * 1000)}-{_slug(tipo)}"
        i = 0
        while self._path_entrada(capa, f"{base}-{i}" if i else base, proyecto).exists():
            i += 1
        return f"{base}-{i}" if i else base

    # ------------------------------------------------------------- guardar
    def _guardar(self, entrada: EntradaMemoria, proyecto: str = "") -> Path:
        p = self._path_entrada(entrada.capa, entrada.id, proyecto)
        p.write_text(json.dumps(entrada.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    def guardar_cache(
        self,
        tipo: str,
        idea: str,
        explicacion: str = "",
        *,
        ttl: float = TTL_CACHE_DEFAULT,
        tags: Sequence[str] = (),
    ) -> EntradaMemoria:
        """Cache: dato momentaneo con TTL. Se purga con ``purgar_cache``."""
        n = validar_entrada(tipo, idea, explicacion)
        e = EntradaMemoria(
            id=self._nuevo_id(CAPA_CACHE, tipo), capa=CAPA_CACHE, tipo=tipo, idea=idea,
            explicacion=explicacion, tags=list(tags), creado_en=time.time(),
            expira_en=time.time() + max(1.0, ttl), palabras=n,
        )
        self._guardar(e)
        return e

    def guardar_chat(
        self,
        proyecto: str,
        tipo: str,
        idea: str,
        explicacion: str = "",
        *,
        relevancia: float = 1.0,
        tags: Sequence[str] = (),
        forzar: bool = False,
    ) -> Optional[EntradaMemoria]:
        """Chat: dentro del proyecto, SOLO se admiten las entradas relevantes.

        Si ``relevancia < umbral`` la entrada se RECHAZA (devuelve None) salvo
        ``forzar=True``. Devuelve la entrada guardada o None.
        """
        if not proyecto.strip():
            raise ValueError("guardar_chat requiere proyecto")
        n = validar_entrada(tipo, idea, explicacion)
        if not forzar and relevancia < self.umbral_relevancia:
            return None  # no relevante: no entra a la memoria del proyecto
        e = EntradaMemoria(
            id=self._nuevo_id(CAPA_CHAT, tipo, proyecto), capa=CAPA_CHAT, tipo=tipo, idea=idea,
            explicacion=explicacion, proyecto=proyecto, tags=list(tags),
            creado_en=time.time(), relevancia=float(relevancia), palabras=n,
        )
        self._guardar(e, proyecto)
        return e

    def guardar_ecosistema(
        self,
        tipo: str,
        idea: str,
        explicacion: str = "",
        *,
        proyecto: str = "",
        tags: Sequence[str] = (),
    ) -> EntradaMemoria:
        """Ecosistema: memoria global, visible entre todos los proyectos."""
        n = validar_entrada(tipo, idea, explicacion)
        e = EntradaMemoria(
            id=self._nuevo_id(CAPA_ECOSISTEMA, tipo), capa=CAPA_ECOSISTEMA, tipo=tipo, idea=idea,
            explicacion=explicacion, proyecto=proyecto, tags=list(tags), palabras=n,
        )
        self._guardar(e)
        return e

    # ------------------------------------------------------------- leer/listar
    def listar(self, capa: str, *, proyecto: Optional[str] = None, incluir_expiradas: bool = False) -> list[EntradaMemoria]:
        if capa not in CAPAS:
            raise CapaDesconocidaError(f"capa desconocida {capa!r}; use {CAPAS}")
        base = self.root / capa
        if capa == CAPA_CHAT:
            dirs = [base / _slug(proyecto, 60)] if proyecto else [d for d in base.iterdir() if d.is_dir()]
        else:
            dirs = [base]
        out: list[EntradaMemoria] = []
        for d in dirs:
            if not d.exists():
                continue
            for p in sorted(d.glob("*.json")):
                try:
                    e = EntradaMemoria.from_dict(json.loads(p.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError, TypeError):
                    continue  # entrada corrupta no tumba el listado
                if e.expirada and not incluir_expiradas:
                    continue
                out.append(e)
        out.sort(key=lambda e: e.creado_en, reverse=True)
        return out

    def leer(self, capa: str, id_entrada: str, *, proyecto: str = "") -> Optional[EntradaMemoria]:
        p = self._path_entrada(capa, id_entrada, proyecto)
        if not p.exists():
            return None
        return EntradaMemoria.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def borrar(self, capa: str, id_entrada: str, *, proyecto: str = "") -> bool:
        p = self._path_entrada(capa, id_entrada, proyecto)
        if p.exists():
            p.unlink()
            return True
        return False

    # ------------------------------------------------------------- buscar
    def buscar(
        self,
        capa: str,
        query: str,
        *,
        proyecto: Optional[str] = None,
        top_k: int = 5,
    ) -> list[tuple[float, EntradaMemoria]]:
        """Busqueda BM25 sobre una capa. En chat, filtra por proyecto si se indica."""
        entradas = self.listar(capa, proyecto=proyecto)
        if not entradas or not query.strip():
            return []
        index = BM25Index()
        index.add([Chunk(contenido=e.texto_busqueda(), source=e.id, start=0, end=len(e.texto_busqueda()), indice=i)
                   for i, e in enumerate(entradas)])
        hits = index.search(query, k=max(1, top_k))
        por_id = {e.id: e for e in entradas}
        # OJO: Chunk.source guarda el id; recuperamos la entrada completa
        out: list[tuple[float, EntradaMemoria]] = []
        for score, chunk in hits:
            e = por_id.get(chunk.source)
            if e is not None:
                out.append((score, e))
        return out

    # ------------------------------------------------------------- cache
    def purgar_cache(self, *, ahora: Optional[float] = None) -> int:
        """Borra las entradas de cache expiradas. Devuelve cuantas borro."""
        ahora = time.time() if ahora is None else ahora
        borradas = 0
        for e in self.listar(CAPA_CACHE, incluir_expiradas=True):
            if e.expira_en > 0 and ahora > e.expira_en:
                if self.borrar(CAPA_CACHE, e.id):
                    borradas += 1
        return borradas

    # ------------------------------------------------------------- stats
    def stats(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for capa in CAPAS:
            entradas = self.listar(capa, incluir_expiradas=True)
            palabras = [e.palabras for e in entradas]
            out[capa] = {
                "entradas": len(entradas),
                "palabras_media": round(sum(palabras) / len(palabras), 1) if palabras else 0.0,
                "palabras_max": max(palabras) if palabras else 0,
                "max_permitido": MAX_PALABRAS,
                "expiradas_pendientes": sum(1 for e in entradas if e.expirada) if capa == CAPA_CACHE else 0,
                "proyectos": sorted({e.proyecto for e in entradas if e.proyecto}) if capa != CAPA_CACHE else [],
            }
        return {"root": str(self.root), "capas": out}
