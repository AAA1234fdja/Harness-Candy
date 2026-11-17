"""Capa LLM avanzada, solo stdlib (v3 §5.6): plantillas, few-shot, chat multi-turn
y salida estructurada validada contra esquema.

* ``PromptTemplate``: plantillas con variables (motor propio en templates.py).
* ``build_few_shot``: ejemplos few-shot formateados.
* ``ChatSession``: conversacion multi-turn con historial acotado y
  persistencia opcional en JSON (reanudar sesiones).
* ``structured_output``: le pide al modelo un JSON, lo parsea y lo valida
  contra un esquema publicado (``schemas``); reintenta con el error como
  realimentacion (fail-closed: si no valida, lanza ``StructuredOutputError``).
* ``estimate_tokens``: estimacion heuristica (~4 caracteres/token en es/en).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .retry import retry_call
from .schemas import SchemaError, validate_schema
from .templates import render_string


class StructuredOutputError(ValueError):
    pass


def estimate_tokens(text: str) -> int:
    """Estimacion heuristica de tokens (~4 caracteres por token)."""
    return max(1, len(text) // 4)


class PromptTemplate:
    """Plantilla de prompt con variables: ``PromptTemplate("...{{ x }}...")``."""

    def __init__(self, text: str, *, example: str = ""):
        self.text = text
        self.example = example

    def render(self, **ctx) -> str:
        return render_string(self.text, **ctx)

    def __call__(self, **ctx) -> str:
        return self.render(**ctx)


@dataclass
class FewShotExample:
    input: str
    output: str


def build_few_shot(examples: list[FewShotExample], *, input_key: str = "entrada", output_key: str = "salida") -> str:
    """Formatea ejemplos few-shot como bloques Entrada/Salida."""
    lineas = []
    for i, ex in enumerate(examples, 1):
        lineas.append(f"Ejemplo {i}:\n{input_key}: {ex.input}\n{output_key}: {ex.output}")
    return "\n\n".join(lineas)


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}

    @staticmethod
    def from_dict(d: dict) -> "ChatMessage":
        return ChatMessage(d["role"], d["content"])


class ChatSession:
    """Sesion de chat multi-turn sobre un LLMBackend, con historial acotado.

    ``max_messages`` recorta el historial (conservando el system prompt) para
    no explotar el contexto. Se puede persistir en JSON y reanudar.
    """

    def __init__(self, backend, *, model: str = "", system: str = "", max_messages: int = 40, path: str | Path | None = None):
        self.backend = backend
        self.model = model or getattr(backend, "default_model", "")
        self.system = system
        self.max_messages = max_messages
        self.path = Path(path) if path else None
        self.history: list[ChatMessage] = [ChatMessage("system", system)] if system else []

    def _recortar(self) -> None:
        if len(self.history) <= self.max_messages:
            return
        system = [m for m in self.history if m.role == "system"]
        resto = [m for m in self.history if m.role != "system"]
        self.history = system + resto[-(self.max_messages - len(system)):]

    def send(self, mensaje: str, *, seed: int = 0) -> str:
        """Envia un mensaje de usuario y devuelve la respuesta del modelo."""
        self.history.append(ChatMessage("user", mensaje))
        self._recortar()
        # construimos el prompt con historial plano (los backends son stateless)
        partes = []
        for m in self.history:
            partes.append(f"{m.role.upper()}: {m.content}")
        prompt = "\n".join(partes)
        respuesta = self.backend.complete(prompt, model=self.model, seed=seed)
        self.history.append(ChatMessage("assistant", respuesta))
        self._recortar()
        self._persist()
        return respuesta

    def tokens_estimados(self) -> int:
        return sum(estimate_tokens(m.content) for m in self.history)

    def to_dict(self) -> dict:
        return {"model": self.model, "system": self.system, "history": [m.to_dict() for m in self.history]}

    def _persist(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path, backend, *, model: str = "") -> "ChatSession":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        s = cls(backend, model=model or data.get("model", ""), system=data.get("system", ""), path=path)
        s.history = [ChatMessage.from_dict(m) for m in data.get("history", [])]
        return s


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extraer_json(texto: str) -> Any:
    """Extrae el primer JSON de la respuesta (bloque ```json o objeto suelto)."""
    m = _JSON_BLOCK_RE.search(texto)
    candidatos = [m.group(1)] if m else []
    # objeto o array suelto
    for ch_open, ch_close in (("{", "}"), ("[", "]")):
        i = texto.find(ch_open)
        if i >= 0:
            profundidad = 0
            for j in range(i, len(texto)):
                if texto[j] == ch_open:
                    profundidad += 1
                elif texto[j] == ch_close:
                    profundidad -= 1
                    if profundidad == 0:
                        candidatos.append(texto[i:j + 1])
                        break
    for cand in candidatos:
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    raise StructuredOutputError(f"no se encontro JSON valido en la respuesta: {texto[:200]!r}")


def structured_output(
    backend,
    prompt: str,
    schema: dict,
    *,
    system: str = "Devuelve SOLO un objeto JSON que cumpla el esquema. Nada mas.",
    model: str = "",
    seed: int = 0,
    max_retries: int = 2,
    schema_name: str = "salida",
) -> tuple[Any, str]:
    """Salida estructurada validada: pide JSON, parsea, valida contra ``schema``.

    Si no valida, reintenta con el error como realimentacion (hasta
    ``max_retries``). Si agota, lanza ``StructuredOutputError`` (fail-closed).
    Devuelve ``(dato_validado, respuesta_cruda)``.
    """
    intento = 0
    realimentacion = ""
    ultimo_error = ""
    while intento <= max_retries:
        texto = prompt + realimentacion
        try:
            raw = backend.complete(texto, system=system, model=model, seed=seed + intento)
        except Exception as e:  # noqa: BLE001 - el backend puede fallar; reintentar
            ultimo_error = f"{type(e).__name__}: {e}"
            intento += 1
            realimentacion = f"\n\nTu respuesta anterior fallo con: {ultimo_error}. Devuelve SOLO el JSON pedido."
            continue
        try:
            data = _extraer_json(raw)
            validate_schema(data, schema, path=f"{schema_name}.$")
            return data, raw
        except (StructuredOutputError, SchemaError, json.JSONDecodeError) as e:
            ultimo_error = str(e)
            intento += 1
            realimentacion = (
                f"\n\nTu respuesta anterior no cumplio el esquema: {ultimo_error}. "
                f"Corrige y devuelve SOLO el objeto JSON valido."
            )
    raise StructuredOutputError(f"tras {max_retries + 1} intentos no se obtuvo JSON valido: {ultimo_error}")


def complete_with_retry(backend, prompt: str, *, system: str = "", model: str = "", seed: int = 0, attempts: int = 3) -> str:
    """complete con reintentos ante fallos transitorios (usa retry_call)."""
    return retry_call(
        lambda: backend.complete(prompt, system=system, model=model, seed=seed),
        attempts=attempts, seed=seed,
    )


# ---------------------------------------------------------------------------
# Costos, truncado de contexto y batch
# ---------------------------------------------------------------------------

def estimate_cost(tokens: int, cost_per_1k: float) -> float:
    """Costo estimado en unidades monetarias: tokens/1000 * cost_per_1k."""
    return tokens / 1000.0 * cost_per_1k


def truncar_contexto(texto: str, *, max_tokens: int = 4000, desde: str = "inicio") -> str:
    """Recorta el texto a ~max_tokens (4 chars/token); conserva inicio o fin."""
    limite = max_tokens * 4
    if len(texto) <= limite:
        return texto
    if desde == "fin":
        return texto[-limite:]
    return texto[:limite]


class PromptBuilder:
    """Constructor de prompts por secciones (system, few-shot, instruccion, contexto)."""

    def __init__(self, *, system: str = "", instruction: str = ""):
        self.system = system
        self.instruction = instruction
        self.secciones: list[tuple[str, str]] = []

    def add(self, nombre: str, contenido: str) -> "PromptBuilder":
        self.secciones.append((nombre, contenido))
        return self

    def add_few_shot(self, examples: list[FewShotExample]) -> "PromptBuilder":
        return self.add("ejemplos", build_few_shot(examples))

    def build(self, **ctx) -> str:
        partes = []
        if self.system:
            partes.append(f"SYSTEM: {self.system}")
        for nombre, contenido in self.secciones:
            partes.append(f"[{nombre.upper()}]\n{contenido}")
        if self.instruction:
            partes.append(f"INSTRUCCION: {render_string(self.instruction, **ctx)}")
        return "\n\n".join(partes)


def batch_complete(backend, prompts: list[str], *, model: str = "", seed: int = 0, max_workers: int = 4) -> list[str]:
    """Ejecuta varios prompts en paralelo (ThreadPoolExecutor) y devuelve las respuestas en orden."""
    from concurrent.futures import ThreadPoolExecutor

    def _uno(i_p):
        i, p = i_p
        return i, backend.complete(p, model=model, seed=seed + i)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        resultados = list(ex.map(_uno, enumerate(prompts)))
    resultados.sort()
    return [r for _, r in resultados]


# ---------------------------------------------------------------------------
# Persistencia de sesiones y ajuste de contexto por presupuesto de tokens
# ---------------------------------------------------------------------------

class ConversationLogger:
    """Escribe la conversacion (mensajes) como JSONL para auditar."""

    def __init__(self, path):
        from pathlib import Path

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, ses: "ChatSession") -> None:
        with self.path.open("a", encoding="utf-8") as f:
            for m in ses.history:
                f.write(json.dumps(m.to_dict(), ensure_ascii=False) + "\n")

    def leer(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]


def fit_context(ses: "ChatSession", *, max_tokens: int = 4000) -> int:
    """Recorta el historial de la sesion a ~max_tokens (4 chars/token).

    Conserva siempre el system prompt y los mensajes mas recientes.
    Devuelve cuantos mensajes quedo.
    """
    system = [m for m in ses.history if m.role == "system"]
    resto = [m for m in ses.history if m.role != "system"]
    presupuesto = max_tokens * 4
    usados = sum(len(m.content) for m in system)
    mantener: list[ChatMessage] = []
    for m in reversed(resto):
        if usados + len(m.content) > presupuesto and mantener:
            break
        mantener.insert(0, m)
        usados += len(m.content)
    ses.history = system + mantener
    return len(ses.history)


def resumen_historial(ses: "ChatSession", *, k: int = 3) -> str:
    """Resume la conversacion con el resumen extractivo propio (sin costo LLM)."""
    from .summarize import summarize

    texto = "\n".join(f"{m.role}: {m.content}" for m in ses.history)
    return summarize(texto, k=k).texto
