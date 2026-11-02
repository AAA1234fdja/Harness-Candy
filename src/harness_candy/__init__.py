"""Harness-Candy: implementacion del diseno combinado Ely-Cowork ADK+Harness^2.

Ver docs/DISENO_COMBINADO.md para el mapeo seccion-del-PDF -> modulo.
"""
from . import protocols, quality, harness, memory, pool, security, sandbox, dag, agents, components, runner, adk_bridge, ablation, backends, judge, metrics
from . import schemas, retry, streaming, plugins, cache, failover, tools, alerts, report, storage, suite, evalkit, factory
from . import auth, tenancy, agents_catalog, guards, scheduler, datasets, metrics_export, web, review, latencia
from .backends import BackendError, OpenAICompatibleBackend
from .judge import LLMJudge, calibrate, swap_test
from .metrics import MetricsCollector
from .components import check_diff_paths, linter_basico
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
from .ablation import AblationReport, k_curve, run_ablation
from .quality import mann_whitney_adopt
from .schemas import SCHEMAS, SCHEMA_VERSION, SchemaError, schema_json, schema_names, validate_named, validate_schema
from .retry import RetryExhausted, backoff_delays, retry_call, retryable
from .streaming import EventBus, EventCollector, SseBroadcaster, sse
from .plugins import CompositePlugin, LoggingPlugin, PluginRegistry
from .cache import CachedBackend, ResponseCache, cache_key
from .failover import AllBackendsFailed, FailoverBackend
from .tools import ToolRegistry, ToolSpec, default_registry
from .alerts import Alert, BudgetMonitor, LogSink, MultiSink, WebhookSink, quality_alert
from .report import html_report, junit_xml, markdown_report, write_report
from .storage import JsonRunStore, SqliteRunStore, open_store
from .suite import Suite, SuiteResult, load_suite, run_suite
from .evalkit import CaseResult, EvalReport, GoldenCase, GoldenSet, load_golden, run_golden
from .factory import build_runner, make_backend, make_pool
from .auth import IpRateLimiter, TokenAuth
from .tenancy import TenantManager, validate_tenant
from .agents_catalog import AgentCatalog, AgentSpec, load_catalog
from .guards import ForbiddenPatternsGuard, GuardPipeline, JsonSchemaGuard, MaxLengthGuard, NoSecretsGuard, RequiredKeysGuard, default_pipeline
from .scheduler import Job, Scheduler
from .datasets import Comparison, compare_reports, load_dataset, run_dataset
from .metrics_export import OtlpExporter, otlp_spans, prometheus_text
from .web import dashboard_html
from .review import ReviewAgent, DEFAULT_ALLOWED_PREFIXES
from .latencia import bench_latencia, comparar_latencias, percentiles

__version__ = "0.1.0"

__all__ = [
    "protocols", "quality", "harness", "memory", "pool", "security", "sandbox",
    "dag", "agents", "components", "runner", "adk_bridge", "ablation", "backends",
    "judge", "metrics",
    "BackendError", "OpenAICompatibleBackend", "LLMJudge", "calibrate", "swap_test",
    "MetricsCollector", "check_diff_paths", "linter_basico",
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
    "schemas", "retry", "streaming", "plugins", "cache", "failover", "tools", "alerts",
    "report", "storage", "suite", "evalkit", "factory",
    "SCHEMAS", "SCHEMA_VERSION", "SchemaError", "schema_json", "schema_names", "validate_named", "validate_schema",
    "RetryExhausted", "backoff_delays", "retry_call", "retryable",
    "EventBus", "EventCollector", "SseBroadcaster", "sse",
    "CompositePlugin", "LoggingPlugin", "PluginRegistry",
    "CachedBackend", "ResponseCache", "cache_key",
    "AllBackendsFailed", "FailoverBackend",
    "ToolRegistry", "ToolSpec", "default_registry",
    "Alert", "BudgetMonitor", "LogSink", "MultiSink", "WebhookSink", "quality_alert",
    "html_report", "junit_xml", "markdown_report", "write_report",
    "JsonRunStore", "SqliteRunStore", "open_store",
    "Suite", "SuiteResult", "load_suite", "run_suite",
    "CaseResult", "EvalReport", "GoldenCase", "GoldenSet", "load_golden", "run_golden",
    "build_runner", "make_backend", "make_pool",
    "auth", "tenancy", "agents_catalog", "guards", "scheduler", "datasets", "metrics_export", "web",
    "IpRateLimiter", "TokenAuth", "TenantManager", "validate_tenant",
    "AgentCatalog", "AgentSpec", "load_catalog",
    "ForbiddenPatternsGuard", "GuardPipeline", "JsonSchemaGuard", "MaxLengthGuard", "NoSecretsGuard", "RequiredKeysGuard", "default_pipeline",
    "Job", "Scheduler", "Comparison", "compare_reports", "load_dataset", "run_dataset",
    "OtlpExporter", "otlp_spans", "prometheus_text", "dashboard_html",
    "__version__",
]
