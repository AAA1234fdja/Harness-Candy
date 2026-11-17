"""Harness-Candy: implementacion del diseno combinado Ely-Cowork ADK+Harness^2.

Ver docs/DISENO_COMBINADO.md para el mapeo seccion-del-PDF -> modulo.
"""
from . import protocols, quality, harness, memory, pool, security, sandbox, dag, agents, components, runner, adk_bridge, ablation, backends, judge, metrics
from . import schemas, retry, streaming, plugins, cache, failover, tools, alerts, report, storage, suite, evalkit, factory
from . import auth, tenancy, agents_catalog, guards, scheduler, datasets, metrics_export, web, review, latencia
from . import templates, config, summarize, watch, llm, rag, planner, codeedit, diffengine, workflow, orchestrator, codegen, evalsuite
from . import stats, graph, textdiff, crypto, i18n, viz, notify
from . import proposer, schedule, recursion, tree, selection, context, runmark, vertex
from . import benchmarks, safety, judge_calib, qatest, evidence, backends_multi, memoria
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
from .proposer import CANDIDATO_SCHEMA, LLMProposer, proposer_desde_config
from .schedule import ScheduleItem, ScheduleResult, ScheduleRunner, SweepPoint, SweepResult, grid_sweep, particionar, shard_de, sweep_con_early_stop
from .recursion import PARALLEL, SEQUENTIAL, RecursionResult, SubResult, reflection_post_adopcion, run_recursion
from .tree import HarnessTree, TreeNode
from .selection import CandidateScore, SelectionResult, seleccionar_adoptado
from .context import ContextBundle, Fragmento, construir_contexto
from .runmark import ENV_RELEVANTES, RunMark, crear_runmark, fingerprint_env, verificar_reproducibilidad
from .vertex import ADCError, VertexBackend, obtener_token_adc, token_desde_adc_file, token_desde_gcloud, token_desde_metadata
from .benchmarks import BenchmarkCase, BenchmarkReport, BenchmarkSuite, benchmark_card, comparar_modelos, construir_prompt, evaluation_card, export_olmes, load_benchmark, puntuar_caso, reporte_benchmark_md, run_benchmark, suites_desde_directorio
from .safety import SafetyMetrics, SafetyReport, SafetySuite, SafetyVerdict, corpus_ampliado, corpus_redteam, detectar_jailbreak, detectar_refusal, evaluar_respuesta, metricas_seguridad, redteam_por_plantilla, toxicidad, variantes_redteam
from .judge_calib import CalibratedJudge, CalibrationReport, EloEntry, JudgeVote, TorneoElo, calibrar_juez, consenso, consenso_pares, reporte_calibracion_md
from .qatest import FuzzReport, Mantenibilidad, MutationReport, funciones_cambiadas, fuzz_funcion, metricas_mantenibilidad, metricas_proyecto, mutar_fuente, run_mutation, run_mutation_diff
from .evidence import ReglaAlerta, evaluar_alertas, evidence_pack, export_otlp_end_to_end, exportar_pack_zip, guardar_pack, cargar_pack, marcar_rollback_en_store, pack_desde_store, rollback_si_regresion, verificar_pack
from .backends_multi import AnthropicBackend, FailoverPorModelo, MetricasModelo, OllamaBackend, SelectorModelos, TokenBudget, backends_disponibles, failover_desde_env
from .memoria import CAPAS, MAX_PALABRAS, UMBRAL_RELEVANCIA, CapaDesconocidaError, EntradaLargaError, EntradaMemoria, GestorMemoria, contar_palabras, validar_entrada
from .templates import TemplateError, compile_template, render_file, render_string
from .config import DEFAULTS as CONFIG_DEFAULTS, ENV_PREFIX, Config, ConfigWatcher, default_config, diff_configs, interpolar, load_config
from .summarize import Summary, detectar_duplicados, keywords, resumen_por_parrafos, similitud_jaccard, summarize, summarize_longitud, tfidf_lite
from .watch import DebouncedWatchRunner, WatchEvent, WatchRunner, changed_since, diff_contenido, diff_snapshots, resumen_cambios, snapshot
from .llm import ChatMessage, ChatSession, ConversationLogger, FewShotExample, PromptBuilder, PromptTemplate, StructuredOutputError, batch_complete, build_few_shot, complete_with_retry, estimate_cost, estimate_tokens, fit_context, resumen_historial, structured_output, truncar_contexto
from .rag import BM25Index, Chunk, HashingEmbedder, HybridRetriever, RAGPipeline, VectorIndex, chunk_text, cobertura_terminos, cosine, evaluate_retrieval, expand_query, rerank_por_cobertura, tokenize
from .planner import Operator, Planner, PlanningError, plan_simple
from .codeedit import CodeEditError, DiffApplicationError, FileSpec, add_class, add_decorator, add_function, add_import, apply_unified_diff, generate_file_from_spec, generate_tests_for, list_functions, parse_module, remove_function, remove_import, rename_function, set_function_body, validate_code
from .diffengine import CodeDiff, ast_diff, ast_diff_detallado, complejidad_ciclomatica, diff_arboles
from .workflow import StepResult, Workflow, WorkflowResult, run_workflow
from .orchestrator import Campaign, CampaignResult, run_campaign, run_campaign_ab
from .codegen import scaffold_agent, scaffold_project
from .evalsuite import EvalSuiteResult, curva_pass_k, exportar_csv, html_eval_report, markdown_eval_report, pass_at_k, run_eval_suite, significancia_vs
from .stats import anova_oneway, bootstrap_ci, chi2_contingencia, chi2_sf, describe, ic_media, ic_proporcion_wilson, iqr, kendall_tau, mean, median, normal_cdf, pearson, percentil, spearman, stdev, t_sf, variance
from .graph import CycleError, DiGraph, dependencias_a_grafo
from .textdiff import DiffStats, diff_lineas, diff_stats, resaltar_cambios, resumen_diff, similarity, unified_diff
from .crypto import SIGNING_KEY_ENV, buscar_secretos, clave_desde_env, constant_time_eq, derive_key, gen_token, hmac_sha256, mask_secret, redact_text, sha256_hex, sign_run, signing_key, verify_run
from .i18n import MESSAGES, agregar_mensajes, detectar_idioma, idiomas, t
from .viz import bar_chart, heatmap, histogram, line_chart, progress_bar, resumen_serie, sparkline, table_html, tarjeta_html
from .notify import CallbackSink, JsonlSink, Notification, Notifier, WebhookSink, notificar_evento_watch

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
    "templates", "config", "summarize", "watch", "llm", "rag", "planner", "codeedit", "diffengine", "workflow", "orchestrator", "codegen", "evalsuite",
    "TemplateError", "compile_template", "render_file", "render_string",
    "CONFIG_DEFAULTS", "ENV_PREFIX", "Config", "default_config", "load_config",
    "Summary", "resumen_por_parrafos", "summarize",
    "WatchEvent", "WatchRunner", "changed_since", "diff_snapshots", "snapshot",
    "ChatMessage", "ChatSession", "FewShotExample", "PromptTemplate", "StructuredOutputError", "build_few_shot", "complete_with_retry", "estimate_tokens", "structured_output",
    "BM25Index", "Chunk", "HashingEmbedder", "HybridRetriever", "RAGPipeline", "VectorIndex", "chunk_text", "cosine", "tokenize",
    "Operator", "Planner", "PlanningError", "plan_simple",
    "CodeEditError", "DiffApplicationError", "FileSpec", "add_function", "add_import", "apply_unified_diff", "generate_file_from_spec", "generate_tests_for", "parse_module", "remove_import", "rename_function", "set_function_body", "validate_code",
    "CodeDiff", "ast_diff",
    "StepResult", "Workflow", "WorkflowResult", "run_workflow",
    "Campaign", "CampaignResult", "run_campaign",
    "scaffold_agent", "scaffold_project",
    "EvalSuiteResult", "html_eval_report", "run_eval_suite", "significancia_vs",
    "stats", "graph", "textdiff", "crypto", "i18n", "viz",
    "anova_oneway", "bootstrap_ci", "chi2_contingencia", "chi2_sf", "describe", "ic_media", "ic_proporcion_wilson", "iqr", "kendall_tau", "mean", "median", "normal_cdf", "pearson", "percentil", "spearman", "stdev", "t_sf", "variance",
    "CycleError", "DiGraph", "dependencias_a_grafo",
    "DiffStats", "diff_lineas", "diff_stats", "resaltar_cambios", "resumen_diff", "similarity", "unified_diff",
    "SIGNING_KEY_ENV", "buscar_secretos", "constant_time_eq", "gen_token", "hmac_sha256", "mask_secret", "redact_text", "sha256_hex", "sign_run", "signing_key", "verify_run",
    "MESSAGES", "agregar_mensajes", "detectar_idioma", "idiomas", "t",
    "bar_chart", "histogram", "progress_bar", "resumen_serie", "sparkline", "table_html",
    "notify",
    "detectar_duplicados", "keywords", "similitud_jaccard", "summarize_longitud", "tfidf_lite",
    "ConfigWatcher", "diff_configs", "interpolar",
    "DebouncedWatchRunner", "diff_contenido", "resumen_cambios",
    "PromptBuilder", "batch_complete", "estimate_cost", "truncar_contexto",
    "add_class", "add_decorator", "list_functions", "remove_function",
    "cobertura_terminos", "expand_query", "rerank_por_cobertura",
    "run_campaign_ab", "exportar_csv", "pass_at_k",
    "CallbackSink", "JsonlSink", "Notification", "Notifier", "WebhookSink", "notificar_evento_watch",
    "ast_diff_detallado", "complejidad_ciclomatica", "diff_arboles",
    "heatmap", "line_chart", "tarjeta_html",
    "clave_desde_env", "derive_key",
    "ConversationLogger", "fit_context", "resumen_historial",
    "curva_pass_k", "markdown_eval_report", "evaluate_retrieval",
    "proposer", "schedule", "recursion", "tree", "selection", "context", "runmark", "vertex",
    "CANDIDATO_SCHEMA", "LLMProposer", "proposer_desde_config",
    "ScheduleItem", "ScheduleResult", "ScheduleRunner", "SweepPoint", "SweepResult", "grid_sweep", "particionar", "shard_de", "sweep_con_early_stop",
    "PARALLEL", "SEQUENTIAL", "RecursionResult", "SubResult", "reflection_post_adopcion", "run_recursion",
    "HarnessTree", "TreeNode",
    "CandidateScore", "SelectionResult", "seleccionar_adoptado",
    "ContextBundle", "Fragmento", "construir_contexto",
    "ENV_RELEVANTES", "RunMark", "crear_runmark", "fingerprint_env", "verificar_reproducibilidad",
    "ADCError", "VertexBackend", "obtener_token_adc", "token_desde_adc_file", "token_desde_gcloud", "token_desde_metadata",
    "benchmarks", "safety", "judge_calib", "qatest", "evidence", "backends_multi",
    "BenchmarkCase", "BenchmarkReport", "BenchmarkSuite", "benchmark_card", "comparar_modelos", "reporte_benchmark_md", "suites_desde_directorio", "construir_prompt", "evaluation_card", "export_olmes", "load_benchmark", "puntuar_caso", "run_benchmark",
    "SafetyMetrics", "SafetyReport", "SafetySuite", "SafetyVerdict", "corpus_ampliado", "corpus_redteam", "detectar_jailbreak", "detectar_refusal", "evaluar_respuesta", "metricas_seguridad", "redteam_por_plantilla", "toxicidad", "variantes_redteam",
    "CalibratedJudge", "CalibrationReport", "EloEntry", "JudgeVote", "TorneoElo", "calibrar_juez", "consenso", "consenso_pares", "reporte_calibracion_md",
    "FuzzReport", "Mantenibilidad", "MutationReport", "funciones_cambiadas", "fuzz_funcion", "metricas_mantenibilidad", "metricas_proyecto", "mutar_fuente", "run_mutation", "run_mutation_diff",
    "ReglaAlerta", "evaluar_alertas", "evidence_pack", "export_otlp_end_to_end", "guardar_pack", "cargar_pack", "exportar_pack_zip", "marcar_rollback_en_store", "pack_desde_store", "rollback_si_regresion", "verificar_pack",
    "AnthropicBackend", "FailoverPorModelo", "MetricasModelo", "OllamaBackend", "SelectorModelos", "TokenBudget", "backends_disponibles", "failover_desde_env",
    "CAPAS", "MAX_PALABRAS", "UMBRAL_RELEVANCIA", "CapaDesconocidaError", "EntradaLargaError", "EntradaMemoria", "GestorMemoria", "contar_palabras", "validar_entrada",
    "__version__",
]
