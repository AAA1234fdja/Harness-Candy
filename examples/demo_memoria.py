#!/usr/bin/env python3
"""Demo: memoria administrada en 3 capas (memoria/).

    python examples/demo_memoria.py [--root DIR]

Crea entradas de ejemplo en cache/chat/ecosistema (en un dir temporal por
defecto para no ensuciar el repo), las busca con BM25 y purga la cache.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness_candy.memoria import GestorMemoria


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None, help="carpeta memoria/ (default: dir temporal)")
    args = ap.parse_args()
    td = None
    root = args.root
    if root is None:
        td = tempfile.TemporaryDirectory()
        root = str(Path(td.name) / "memoria")
    g = GestorMemoria(root)
    print(f"memoria en: {root}")

    g.guardar_cache("borrador", "estado del build", "compilando la ola 8", ttl=600)
    e = g.guardar_chat("Harness-Candy", "decision", "busqueda BM25 local",
                       "determinista, sin dependencias externas; reusa rag.BM25Index",
                       relevancia=0.9, tags=["rag", "memoria"])
    print("chat guardada:", e.id if e else "RECHAZADA")
    g.guardar_chat("Harness-Candy", "ruido", "nota al margen", "poco relevante para el proyecto", relevancia=0.1)
    g.guardar_ecosistema("patron", "maximo 300 palabras por entrada",
                         "tipo + idea + explicacion; la entrada larga se rechaza (fail-closed)",
                         proyecto="Harness-Candy", tags=["memoria", "regla"])

    for capa, q, kw in (("chat", "por que BM25?", {"proyecto": "Harness-Candy"}),
                        ("ecosistema", "cuantas palabras por entrada?", {})):
        print(f"\nbuscar en {capa}: {q!r}")
        for score, entrada in g.buscar(capa, q, top_k=3, **kw):
            print(f"  [{score:.3f}] {entrada.tipo}: {entrada.idea} ({entrada.palabras} palabras)")

    print("\nstats:")
    print(json.dumps(g.stats()["capas"], ensure_ascii=False, indent=2))
    print("purgadas:", g.purgar_cache())
    if td:
        td.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
