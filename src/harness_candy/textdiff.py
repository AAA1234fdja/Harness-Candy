"""Diff de texto linea a linea propio (sobre difflib, stdlib) con salida de
hunks unificados COMPATIBLE con codeedit.apply_unified_diff (v3 §5.8 review).

  - ``diff_lineas(a, b)``: lista de operaciones ('=', '-', '+', '?')
  - ``unified_diff(a, b, fromfile, tofile, n_contexto)``: texto de diff unificado
  - ``similarity(a, b)``: ratio 0..1
  - ``diff_stats(a, b)``: {anadidas, eliminadas, iguales, ratio, bloques}
  - ``resaltar_cambios(linea_vieja, linea_nueva)``: diff intra-linea con difflib
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field


@dataclass
class DiffStats:
    iguales: int = 0
    anadidas: int = 0
    eliminadas: int = 0
    bloques: int = 0
    ratio: float = 0.0

    def to_dict(self) -> dict:
        return {
            "iguales": self.iguales,
            "anadidas": self.anadidas,
            "eliminadas": self.eliminadas,
            "bloques": self.bloques,
            "ratio": round(self.ratio, 6),
        }


def _lineas(texto: str) -> list[str]:
    return texto.splitlines(keepends=True)


def diff_lineas(a: str, b: str) -> list[tuple[str, str]]:
    """Operaciones de SequenceMatcher como pares (tag, linea)."""
    sa, sb = _lineas(a), _lineas(b)
    sm = difflib.SequenceMatcher(a=sa, b=sb, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        for linea in sa[i1:i2]:
            if tag in ("replace", "delete"):
                out.append(("-", linea))
        for linea in sb[j1:j2]:
            if tag in ("replace", "insert"):
                out.append(("+", linea))
        if tag == "equal":
            for linea in sa[i1:i2]:
                out.append(("=", linea))
    return out


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(a=_lineas(a), b=_lineas(b), autojunk=False).ratio()


def unified_diff(a: str, b: str, *, fromfile: str = "a", tofile: str = "b", n: int = 3) -> str:
    """Diff unificado con cabeceras ---/+++ (estilo a/ b/) y hunks @@."""
    sa, sb = _lineas(a), _lineas(b)
    lineas = list(
        difflib.unified_diff(sa, sb, fromfile=f"a/{fromfile}", tofile=f"b/{tofile}", n=n, lineterm="")
    )
    # difflib ya emite cabeceras y hunks; asegurar terminacion de linea
    out = []
    for l in lineas:
        out.append(l if l.endswith("\n") else l + "\n")
    return "".join(out)


def diff_stats(a: str, b: str) -> DiffStats:
    ops = diff_lineas(a, b)
    st = DiffStats()
    bloque_actual = False
    for tag, _ in ops:
        if tag == "=":
            st.iguales += 1
            bloque_actual = False
        elif tag == "+":
            st.anadidas += 1
            if not bloque_actual:
                st.bloques += 1
                bloque_actual = True
        elif tag == "-":
            st.eliminadas += 1
    st.ratio = similarity(a, b)
    return st


def resaltar_cambios(vieja: str, nueva: str) -> tuple[str, str]:
    """Marca intra-linea con ‹› lo anadido y [ ] lo eliminado (para reportes)."""
    sm = difflib.SequenceMatcher(a=vieja, b=nueva, autojunk=False)
    out_a, out_b = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out_a.append(vieja[i1:i2])
            out_b.append(nueva[j1:j2])
        elif tag == "delete":
            out_a.append("[" + vieja[i1:i2] + "]")
        elif tag == "insert":
            out_b.append("‹" + nueva[j1:j2] + "›")
        elif tag == "replace":
            out_a.append("[" + vieja[i1:i2] + "]")
            out_b.append("‹" + nueva[j1:j2] + "›")
    return "".join(out_a), "".join(out_b)


def resumen_diff(a: str, b: str, *, max_lineas: int = 20) -> str:
    """Resumen legible (ES) del diff para logs/reportes."""
    st = diff_stats(a, b)
    lineas = [f"diff: +{st.anadidas} -{st.eliminadas} ={st.iguales} (similitud {st.ratio:.0%}, {st.bloques} bloques)"]
    cuenta = 0
    for tag, linea in diff_lineas(a, b):
        if tag == "=":
            continue
        lineas.append(f"  {tag} {linea.rstrip()}")
        cuenta += 1
        if cuenta >= max_lineas:
            lineas.append(f"  ... (+{st.anadidas + st.eliminadas - cuenta} mas)")
            break
    return "\n".join(lineas)
