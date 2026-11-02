"""Los seis componentes de Ely-Cowork (seccion 4 del diseno combinado).

Son responsabilidades diferenciadas, no necesariamente seis modelos
independientes. La regla clave: quien produce no acepta su propio trabajo
(DONE no significa CORRECT): WEV valida, ELY meta-evalua.

  ISA  Instruction & System Architect   planifica: requisitos, arquitectura,
                                          hitos, criterios de aceptacion
  YEV  Yield Execution & Vector-dispatcher  construye el DAG, asigna tareas,
                                          modelos y claves, supervisa
  ZEV  Zone Extraction & Verifier        investiga (RAG) y alimenta la memoria
  XEV  eXecution Engine Variant          ejecuta micro-tareas (en sandbox)
  WEV  Workload Error & Validation       audita: linters, pruebas, criterios,
                                          veredicto y hallazgos con severidad
  ELY  Executive Loop & Yield-monitor    meta-evaluacion, regresion, ajustes
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .agents import Agent, Artifact, LLMBackend, Task
from .dag import TaskDAG, TaskNode
from .memory import KnowledgeMemory, VariableMemory
from .pool import ModelPool
from .protocols import Envelope, Hallazgo, WevMessage, YevMessage, ZevMessage, validate
from .quality import Criterion, RegressionGuard, score_q
from .security import SecurityGate
from .harness import Harness


# ---------------------------------------------------------------------------
# ISA: planificacion (nivel estrategico)
# ---------------------------------------------------------------------------

DEFAULT_CRITERIA = {
    "security_scan": [
        Criterion("informe_json_valido", "el informe es JSON estructurado", 3.0),
        Criterion("compile_ok", "todos los .py compilan (py_compile)", 2.0),
        Criterion("sin_secretos_criticos", "no se detectan secretos hardcodeados", 3.0),
        Criterion("tiene_recomendaciones", "incluye recomendaciones de mitigacion", 1.0),
        Criterion("pasa_guardias_salida", "la salida pasa la puerta de seguridad", 2.0),
    ],
    "write_report": [
        Criterion("informe_json_valido", "el informe es JSON estructurado", 3.0),
        Criterion("pasa_guardias_salida", "la salida pasa la puerta de seguridad", 2.0),
    ],
}


@dataclass
class Plan:
    objetivo: str
    arquitectura: str
    requisitos: list[str]
    hitos: list[dict]  # {task_id, kind, instruction, deps, agent, irreversible?, herramienta?}
    criterios: dict[str, list[Criterion]]  # por task_id
    restricciones: list[str] = field(default_factory=list)
    operaciones_irreversibles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "objetivo": self.objetivo,
            "arquitectura": self.arquitectura,
            "requisitos": self.requisitos,
            "hitos": self.hitos,
            "criterios": {k: [c.to_dict() for c in v] for k, v in self.criterios.items()},
            "restricciones": self.restricciones,
            "operaciones_irreversibles": self.operaciones_irreversibles,
        }


# Palabras clave que marcan una operacion como IRREVERSIBLE (revision humana)
IRREVERSIBLE_KEYWORDS = (
    "borrar", "eliminar", "delete", "drop", "deploy", "desplegar", "publicar",
    "produccion", "producción", "irreversible", "ejecutar en prod",
)

RESTRICCIONES_DEFAULT = [
    "XEV no ejecuta comandos fuera de su allowlist",
    "XEV corre en sandbox sin red y sin credenciales heredadas",
    "ningun agente modifica archivos fuera del alcance permitido",
    "toda salida pasa la puerta de seguridad (PII/secretos)",
]


class ISA:
    """Convierte el objetivo del usuario en plan con criterios medibles."""

    def __init__(self, backend: Optional[LLMBackend] = None, model: str = "isa-model"):
        self.backend = backend
        self.model = model

    def plan(self, objetivo: str, inputs: dict | None = None) -> Plan:
        inputs = inputs or {}
        if self.backend is not None:
            raw = self.backend.complete(
                f"Convierte este objetivo en un plan JSON con requisitos, hitos y criterios de aceptacion: {objetivo}",
                system="Eres ISA, arquitecto de sistema. Devuelve solo JSON.",
                model=self.model,
            )
            try:
                data = json.loads(raw)
                return Plan(
                    objetivo=objetivo,
                    arquitectura=data.get("arquitectura", ""),
                    requisitos=data.get("requisitos", []),
                    hitos=data.get("hitos", []),
                    criterios={k: [Criterion(**c) for c in v] for k, v in data.get("criterios", {}).items()},
                    restricciones=data.get("restricciones", list(RESTRICCIONES_DEFAULT)),
                    operaciones_irreversibles=data.get("operaciones_irreversibles", []),
                )
            except Exception:
                pass  # cae a la heuristica determinista
        # Plan determinista por defecto (sirve sin LLM externo)
        irreversible = any(k in objetivo.lower() for k in IRREVERSIBLE_KEYWORDS)
        if "seguridad" in objetivo.lower() or "security" in objetivo.lower():
            root = inputs.get("root", ".")
            hitos = [
                {"task_id": "t-001", "kind": "security_scan", "instruction": f"Escanear seguridad del repo {root}", "deps": [], "agent": "XEV", "herramienta": "security_scan"},
                {"task_id": "t-002", "kind": "write_report", "instruction": "Redactar informe final a partir del escaneo", "deps": ["t-001"], "agent": "XEV", "herramienta": "security_scan"},
            ]
            criterios = {"t-001": DEFAULT_CRITERIA["security_scan"], "t-002": DEFAULT_CRITERIA["write_report"]}
            return Plan(
                objetivo=objetivo,
                arquitectura="Escaneo (XEV) -> informe (XEV) -> validacion (WEV) -> auditoria (ELY)",
                requisitos=["informe JSON valido", "sin secretos hardcodeados", "recomendaciones incluidas"],
                hitos=hitos,
                criterios=criterios,
                restricciones=list(RESTRICCIONES_DEFAULT),
                operaciones_irreversibles=[objetivo] if irreversible else [],
            )
        hitos = [{"task_id": "t-001", "kind": "execute", "instruction": objetivo, "deps": [], "agent": "XEV", "irreversible": irreversible}]
        return Plan(
            objetivo=objetivo,
            arquitectura="tarea unica",
            requisitos=[],
            hitos=hitos,
            criterios={"t-001": DEFAULT_CRITERIA.get("write_report", [])},
            restricciones=list(RESTRICCIONES_DEFAULT),
            operaciones_irreversibles=[objetivo] if irreversible else [],
        )


# ---------------------------------------------------------------------------
# YEV: orquestacion y distribucion (DAG -> flujo ADK)
# ---------------------------------------------------------------------------

class YEV:
    """Recibe el plan de ISA, construye el DAG y asigna modelo/clave por nodo."""

    def __init__(self, pool: ModelPool):
        self.pool = pool

    def build_dag(self, plan: Plan, run_id: str = "") -> TaskDAG:
        dag = TaskDAG()
        for hito in plan.hitos:
            clave, modelo = self.pool.select(hito["kind"])
            node = TaskNode(
                task_id=hito["task_id"],
                kind=hito["kind"],
                instruction=hito["instruction"],
                deps=list(hito.get("deps", [])),
                agent=hito.get("agent", "XEV"),
                model=modelo,
                clave=clave,
                presupuesto={"max_reintentos": 2},
                criterios=list(plan.criterios.get(hito["task_id"], DEFAULT_CRITERIA.get(hito["kind"], []))),
                inputs=hito.get("inputs", {}),
            )
            dag.add(node)
        dag.validate()
        return dag

    def dispatch_message(self, node: TaskNode, origen: str = "YEV") -> YevMessage:
        """Emite el mensaje yev de despacho hacia Agent-n."""
        return YevMessage(
            envelope=Envelope("yev", node.task_id, origen, f"Agent-{node.agent}"),
            depende_de=list(node.deps),
            instruccion=node.instruction,
            agente_destino=node.agent,
            modelo=node.model,
            clave=node.clave,
            presupuesto=dict(node.presupuesto),
            criterios_aceptacion=[c.id for c in node.criterios],
        )


# ---------------------------------------------------------------------------
# ZEV: investigacion y recuperacion (RAG) con procedencia
# ---------------------------------------------------------------------------

class ZEV:
    def __init__(self, knowledge: KnowledgeMemory, sources: Optional[list[Path]] = None):
        self.knowledge = knowledge
        self.sources = sources or []

    def retrieve(self, consulta: str, task_id: str = "") -> ZevMessage:
        """Recupera fragmentos pertinentes y los registra con procedencia."""
        fragmentos = []
        for src in self.sources:
            if src.is_file():
                text = src.read_text(encoding="utf-8", errors="ignore")
                for i, chunk in enumerate(_chunks(text, 800)):
                    if any(t in chunk.lower() for t in consulta.lower().split() if len(t) > 3):
                        fragmentos.append(
                            {
                                "contenido": chunk,
                                "procedencia": {"fuente": str(src), "task_id": task_id, "fecha": _now(), "autor": "ZEV"},
                                "nivel_confianza": 0.8,
                            }
                        )
        for entry in self.knowledge.recall(consulta, top_k=3):
            fragmentos.append(
                {
                    "contenido": entry.content,
                    "procedencia": {**entry.procedencia, "autor": "ZEV-memoria"},
                    "nivel_confianza": entry.nivel_confianza,
                }
            )
        return ZevMessage(
            envelope=Envelope("zev", task_id, "ZEV", "memoria_compartida"),
            consulta=consulta,
            fuentes=[str(s) for s in self.sources],
            fragmentos=fragmentos,
            nivel_confianza=1.0 if fragmentos else 0.5,
        )

    def remember(self, zev_msg: ZevMessage) -> None:
        for frag in zev_msg.fragmentos:
            self.knowledge.remember(
                frag["contenido"][:2000],
                fuente=frag["procedencia"].get("fuente", "zev"),
                task_id=zev_msg.envelope.task_id,
                autor="ZEV",
                nivel_confianza=frag.get("nivel_confianza", 0.8),
                tags=[zev_msg.consulta[:40]],
            )


def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def _now() -> float:
    import time

    return time.time()


# ---------------------------------------------------------------------------
# XEV: ejecucion de micro-tareas (herramientas autorizadas, sandbox)
# ---------------------------------------------------------------------------

class XEV:
    """Ejecuta micro-tareas atomicas SOLO con herramientas/comandos autorizados.

    Allowlist (el ejecutor no corre nada fuera de ella) y entrega evidencias
    (registro de ejecucion en el mensaje xev / meta del artefacto).
    """

    ALLOWED_TOOLS = {"security_scan", "read_file", "list_files", "write_report", "shell"}
    # prefijos de comando autorizados para la herramienta "shell" (sandbox)
    ALLOWED_COMMAND_PREFIXES: tuple[str, ...] = ()

    def __init__(self, agents: dict[str, Agent], security: SecurityGate | None = None,
                 allowed_command_prefixes: tuple[str, ...] | None = None):
        self.agents = agents
        self.security = security or SecurityGate()
        import sys as _sys

        self.allowed_command_prefixes = allowed_command_prefixes or (_sys.executable, "git", "ls", "cat", "grep")

    def check_tool_allowed(self, herramienta: str) -> None:
        if herramienta and herramienta not in self.ALLOWED_TOOLS:
            raise PermissionError(f"herramienta no autorizada para XEV: {herramienta!r}")

    def check_command_allowed(self, command: list[str]) -> None:
        if not command:
            raise PermissionError("comando vacio")
        exe = command[0]
        if not any(exe == p or exe.endswith("/" + p) or p in exe for p in self.allowed_command_prefixes):
            raise PermissionError(f"comando no autorizado para XEV: {exe!r}")

    def execute(self, node: TaskNode, context: dict) -> Artifact:
        self.check_tool_allowed(node.herramienta or node.kind)
        agent = self.agents.get(node.agent) or self.agents.get("XEV")
        if agent is None:
            raise RuntimeError("no hay agente registrado para XEV")
        if node.model:
            agent = agent.with_model(node.model)
        task = Task(
            task_id=node.task_id,
            kind=node.kind,
            instruction=node.instruction,
            inputs={**node.inputs, **context.get("inputs", {})},
            criterios=node.criterios,
            max_reintentos=node.max_reintentos,
        )
        harness = context.get("harnesses", {}).get(node.task_id) or context.get("harness")
        artifact = agent.run(task, harness=harness, seed=context.get("seed", 0))
        artifact.meta["registro_ejecucion"] = {
            "herramienta": node.herramienta or node.kind,
            "agente": agent.name,
            "modelo": agent.model,
            "allowlist_ok": True,
        }
        # puerta de seguridad de SALIDA sobre el artefacto
        gate = self.security.check_output(artifact.to_text())
        artifact.meta["security_gate"] = gate.to_dict()
        if not gate.ok and self.security.block_pii:
            artifact = Artifact(task_id=artifact.task_id, content=gate.redacted, meta=artifact.meta)
        return artifact


# ---------------------------------------------------------------------------
# WEV: auditoria, control de calidad y validacion (juez de los criterios)
# ---------------------------------------------------------------------------

CheckFn = Callable[[Artifact], tuple[bool, list[Hallazgo]]]


def linter_basico(root: str) -> list[Hallazgo]:
    """Analisis estatico con ast sobre los .py de ``root``: archivos que no
    parsean e imports declarados pero no usados (hallazgos de mantenibilidad)."""
    import ast

    hallazgos: list[Hallazgo] = []
    root_p = Path(root)
    for p in sorted(root_p.rglob("*.py")):
        if ".git" in p.parts or "__pycache__" in p.parts:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"), filename=str(p))
        except SyntaxError as e:
            hallazgos.append(Hallazgo("linter", "alta", f"{p}: error de sintaxis: {e}"))
            continue
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imported.add((a.asname or a.name).split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    imported.add(a.asname or a.name)
        usados = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        }
        for nombre in sorted(imported - usados):
            hallazgos.append(Hallazgo("linter", "baja", f"{p}: import sin usar: {nombre}"))
    return hallazgos


def check_diff_paths(diff_text: str, allowed_prefixes: list[str]) -> tuple[bool, list[Hallazgo]]:
    """Revisa el diff: todos los archivos tocados deben estar dentro del
    alcance permitido (WEV revisa el diff, no solo el resultado final)."""
    import re as _re

    paths = _re.findall(r"^\+\+\+ b?/?(.+)$", diff_text, flags=_re.MULTILINE)
    paths += _re.findall(r"^--- a?/?(.+)$", diff_text, flags=_re.MULTILINE)
    paths = [p.strip() for p in paths if p.strip() and p.strip() != "/dev/null"]
    fuera = [p for p in paths if not any(p.startswith(pref) for pref in allowed_prefixes)]
    hallazgos = [Hallazgo("diff", "alta", f"el diff toca archivos fuera del alcance: {p}") for p in fuera]
    return (not fuera), hallazgos


class WEV:
    """Valida entregables contra los criterios de aceptacion de ISA.

    La validacion combina juicio y mecanismos deterministas (compilacion,
    pruebas, analisis estatico, revision del diff, puertas de seguridad).
    WEV decide si el entregable cumple las condiciones para aceptarse.
    El juez LLM (opcional) es fail-closed: solo puede restar calidad, nunca
    sumar; en criterios objetivos pesa mas lo determinista.
    """

    def __init__(self, security: SecurityGate | None = None, extra_checks: dict[str, CheckFn] | None = None,
                 judge=None):
        self.security = security or SecurityGate()
        self.judge = judge
        self.checks: dict[str, CheckFn] = {
            "informe_json_valido": self._check_json,
            "compile_ok": self._check_compile,
            "sin_secretos_criticos": self._check_secrets,
            "tiene_recomendaciones": self._check_recs,
            "pasa_guardias_salida": self._check_security,
            "linter_basico": self._check_linter,
            "diff_dentro_de_alcance": self._check_diff,
        }
        if extra_checks:
            self.checks.update(extra_checks)

    # -- checks deterministas sobre artefactos de security_scan / report --
    def _check_json(self, artifact: Artifact) -> tuple[bool, list[Hallazgo]]:
        ok = isinstance(artifact.content, (dict, list))
        return ok, [] if ok else [Hallazgo("wev", "alta", "el artefacto no es JSON estructurado")]

    def _check_compile(self, artifact: Artifact) -> tuple[bool, list[Hallazgo]]:
        errs = artifact.content.get("compile_errors", []) if isinstance(artifact.content, dict) else []
        return (not errs), [Hallazgo("py_compile", "alta", str(e)) for e in errs]

    def _check_secrets(self, artifact: Artifact) -> tuple[bool, list[Hallazgo]]:
        secrets = artifact.content.get("secrets", []) if isinstance(artifact.content, dict) else []
        hallazgos = [
            Hallazgo("secret_scan", "critica", s.get("fragmento", str(s)) if isinstance(s, dict) else str(s))
            for s in secrets
        ]
        return (not secrets), hallazgos

    def _check_recs(self, artifact: Artifact) -> tuple[bool, list[Hallazgo]]:
        recs = artifact.content.get("recommendations", []) if isinstance(artifact.content, dict) else []
        return bool(recs), [] if recs else [Hallazgo("wev", "media", "faltan recomendaciones de mitigacion")]

    def _check_security(self, artifact: Artifact) -> tuple[bool, list[Hallazgo]]:
        gate = self.security.check_output(artifact.to_text())
        return gate.ok, gate.hallazgos

    def _check_linter(self, artifact: Artifact) -> tuple[bool, list[Hallazgo]]:
        root = ""
        if isinstance(artifact.content, dict):
            root = artifact.content.get("repo", "") or artifact.content.get("root", "")
        root = root or artifact.meta.get("root", "")
        if not root or not Path(root).exists():
            return True, []  # nada que analizar -> no aplica
        hallazgos = linter_basico(root)
        graves = [h for h in hallazgos if h.severidad in ("alta", "critica")]
        return (not graves), hallazgos

    def _check_diff(self, artifact: Artifact) -> tuple[bool, list[Hallazgo]]:
        diff = artifact.meta.get("diff")
        if not diff:
            return True, []  # no hubo cambios de archivos -> no aplica
        allowed = artifact.meta.get("allowed_paths", ["."])
        return check_diff_paths(diff, allowed)

    def _apply_judge(self, artifact: Artifact, criterios: list[Criterion], hallazgos: list[Hallazgo]) -> list[Hallazgo]:
        """Juez LLM independiente, fail-closed: solo puede restar calidad."""
        if self.judge is None:
            return hallazgos
        js = self.judge.score(artifact.meta.get("instruction", artifact.task_id), artifact, criterios)
        out = list(hallazgos) + js.hallazgos
        if js.q < 0.5:
            out.append(Hallazgo("juez_llm", "alta", f"el juez independiente puntuo {js.q:.2f} (< 0.5)"))
        return out

    # -- evaluacion completa --
    def evaluate(self, artifact: Artifact, criterios: list[Criterion]) -> tuple[WevMessage, float]:
        checks: dict[str, bool] = {}
        cumplidos: list[str] = []
        hallazgos: list[Hallazgo] = []
        for c in criterios:
            fn = self.checks.get(c.id)
            if fn is None:
                checks[c.id] = False
                hallazgos.append(Hallazgo("wev", "alta", f"criterio sin check registrado: {c.id}"))
                continue
            ok, found = fn(artifact)
            checks[c.id] = ok
            if ok:
                cumplidos.append(c.id)
            hallazgos.extend(found)
        hallazgos = self._apply_judge(artifact, criterios, hallazgos)
        q = score_q(criterios, cumplidos, hallazgos)
        veredicto = "aprobado" if q >= 0.6 and all(checks.get(c.id, False) for c in criterios if c.peso >= 2.0) else "rechazado"
        # pesos altos = criterios criticos: deben cumplirse para aprobar
        accion = "consolidar" if veredicto == "aprobado" else "reintentar con retroalimentacion"
        env = Envelope("wev", artifact.task_id, "WEV", "YEV/ELY")
        msg = WevMessage(
            envelope=env,
            artefacto_id=artifact.task_id,
            checks=checks,
            veredicto=veredicto,
            hallazgos=hallazgos,
            accion=accion,
        )
        return msg, q

    def score(self, artifact: Artifact, criterios: list[Criterion]) -> float:
        """Solo el score Q (ecuacion 1): es la senal que recibe el adaptador."""
        _, q = self.evaluate(artifact, criterios)
        return q


# ---------------------------------------------------------------------------
# ELY: meta-evaluacion, supervision y optimizacion global
# ---------------------------------------------------------------------------

class ELY:
    """Juez independiente (distinto del generador) + regresion + mejoras.

    No evalua una respuesta aislada: evalua rendement de agentes, calidad de
    entregables y eficiencia del proceso; detecta deriva y propone ajustes
    de prompts/harness para las ejecuciones siguientes.
    """

    def __init__(self, regression: RegressionGuard | None = None, knowledge: KnowledgeMemory | None = None):
        self.regression = regression or RegressionGuard()
        self.knowledge = knowledge

    def audit(self, results: dict, traces: list[dict], run_id: str = "") -> dict:
        """Audita los entregables y el proceso; devuelve informe global."""
        qs, statuses = [], []
        for tid, res in results.items():
            entry = {"task_id": tid, "status": res.status, "attempts": res.attempts}
            if res.wev is not None:
                checks = res.wev.checks
                # Q aproximado desde los checks (pesos iguales) menos penalizaciones
                cumplidos = [k for k, v in checks.items() if v]
                criterios = [Criterion(k, "", 1.0) for k in checks]
                entry["q"] = score_q(criterios, cumplidos, res.wev.hallazgos)
                entry["veredicto"] = res.wev.veredicto
                alert = self.regression.check(tid, entry["q"])
                if alert:
                    entry["alerta_deriva"] = alert.mensaje
                self.regression.update_baseline(tid, entry["q"])
            qs.append(entry.get("q", 0.0))
            statuses.append(res.status)
        informe = {
            "run_id": run_id,
            "tareas": len(results),
            "q_medio": sum(qs) / len(qs) if qs else 0.0,
            "tasa_exito": statuses.count("done") / len(statuses) if statuses else 0.0,
            "escaladas": statuses.count("escalated"),
            "fallidas": statuses.count("failed"),
            "detalle": [],
        }
        for tid, res in results.items():
            informe["detalle"].append({"task_id": tid, "status": res.status, "attempts": res.attempts})
        alertas = []
        for tid, res in results.items():
            if res.wev is not None and res.wev.veredicto == "rechazado":
                for h in res.wev.hallazgos:
                    alertas.append(f"{tid}: [{h.severidad}] {h.detalle}")
        informe["hallazgos_rechazos"] = alertas
        informe["propuestas"] = self._propose_improvements(results)
        return informe

    def _propose_improvements(self, results: dict) -> list[str]:
        propuestas = []
        for tid, res in results.items():
            if res.wev is None:
                continue
            for h in res.wev.hallazgos:
                if "secreto" in h.detalle.lower() or h.herramienta == "secret_scan":
                    propuestas.append(f"{tid}: anadir skill 'secrets_v2' y guardrail 'bloquear_secretos_en_salida' al harness de XEV")
                if "JSON" in h.detalle or "json" in h.detalle.lower():
                    propuestas.append(f"{tid}: anadir guardrail 'json_strict' al harness del agente generador")
                if "recomendaciones" in h.detalle.lower():
                    propuestas.append(f"{tid}: anadir skill 'recomendaciones' al harness")
        return sorted(set(propuestas))

    def remember_lessons(self, informe: dict, run_id: str) -> None:
        if self.knowledge is None:
            return
        for propuesta in informe.get("propuestas", []):
            self.knowledge.remember(
                propuesta, fuente="ELY", task_id=run_id, autor="ELY", nivel_confianza=0.7, tags=["leccion", "harness"]
            )
