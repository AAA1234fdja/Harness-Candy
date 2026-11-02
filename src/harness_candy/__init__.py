"""Harness-Candy: implementacion del diseno combinado Ely-Cowork ADK+Harness^2.

Ver docs/DISENO_COMBINADO.md para el mapeo seccion-del-PDF -> modulo.
"""
from . import protocols, quality, harness, memory, pool, security, sandbox, dag, agents, components, runner, adk_bridge, ablation
from .protocols import (
    Envelope, Hallazgo, ProtocolError, ProtocolMessage, WevMessage, XevMessage, YevMessage, ZevMessage, validate,
)
from .quality import Criterion, RegressionGuard, TraceLog, compose_delta, score_q, should_adopt
from .harness import Budget, Harness, Harness2Adapter, HarnessStore, RuleBasedProposer, harness2_adapter
from .memory import KnowledgeMemory, VariableMemory
from .pool import ModelPool, PoolEntry
from .security import SecurityGate, scan_injection, scan_pii
from .sandbox import SandboxResult, run_sandboxed
from .dag import DAGExecutor, NodeResult, TaskDAG, TaskNode
from .agents import Agent, Artifact, LLMBackend, ScriptedBackend, SecurityScanAgent, Task
from .components import ELY, ISA, WEV, XEV, YEV, ZEV, Plan
from .runner import CoworkRunner, RunResult, run_task
from .adk_bridge import build_adk_flow, build_flow_spec
from .ablation import AblationReport, run_ablation

__version__ = "0.1.0"

__all__ = [
    "protocols", "quality", "harness", "memory", "pool", "security", "sandbox",
    "dag", "agents", "components", "runner", "adk_bridge", "ablation",
    "Envelope", "Hallazgo", "ProtocolError", "ProtocolMessage", "WevMessage", "XevMessage", "YevMessage", "ZevMessage", "validate",
    "Criterion", "RegressionGuard", "TraceLog", "compose_delta", "score_q", "should_adopt",
    "Budget", "Harness", "Harness2Adapter", "HarnessStore", "RuleBasedProposer", "harness2_adapter",
    "KnowledgeMemory", "VariableMemory",
    "ModelPool", "PoolEntry",
    "SecurityGate", "scan_injection", "scan_pii",
    "SandboxResult", "run_sandboxed",
    "DAGExecutor", "NodeResult", "TaskDAG", "TaskNode",
    "Agent", "Artifact", "LLMBackend", "ScriptedBackend", "SecurityScanAgent", "Task",
    "ELY", "ISA", "WEV", "XEV", "YEV", "ZEV", "Plan",
    "CoworkRunner", "RunResult", "run_task",
    "build_adk_flow", "build_flow_spec",
    "AblationReport", "run_ablation",
    "__version__",
]
