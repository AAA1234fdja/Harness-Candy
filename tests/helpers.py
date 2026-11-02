"""Constructores compartidos para tests y demos."""
import tempfile
from pathlib import Path

try:
    import _path  # noqa: F401
except ModuleNotFoundError:  # al importar como tests.test_* desde la raiz del repo
    from tests import _path  # noqa: F401
from harness_candy.agents import ScriptedBackend, SecurityScanAgent
from harness_candy.components import ELY, ISA, WEV, XEV, YEV, ZEV
from harness_candy.harness import Budget, HarnessStore
from harness_candy.memory import KnowledgeMemory
from harness_candy.pool import LIGHT_TAG, POWER_TAG, ModelPool, PoolEntry
from harness_candy.quality import RegressionGuard
from harness_candy.runner import CoworkRunner
from harness_candy.security import SecurityGate


def make_pool() -> ModelPool:
    pool = ModelPool()
    pool.add(PoolEntry("flash-1", "modelo-ligero", "KEY_FLASH_1", cost_per_1k=0.0001, roles={"xev", "zev", "wev"}, tag=LIGHT_TAG))
    pool.add(PoolEntry("opus-1", "modelo-potente", "KEY_OPUS_1", cost_per_1k=0.015, roles={"isa", "ely"}, tag=POWER_TAG))
    return pool


def make_runner(trace_dir) -> CoworkRunner:
    pool = make_pool()
    store = HarnessStore()
    budget = Budget(total=10_000, beta=0.5, k=2, m=3)
    knowledge = KnowledgeMemory()
    security = SecurityGate()
    isa = ISA(backend=None, model="modelo-potente")
    yev = YEV(pool)
    zev = ZEV(knowledge)
    agent = SecurityScanAgent("XEV", "modelo-ligero", ScriptedBackend(lambda *a, **k: "ok"))
    xev = XEV({"XEV": agent}, security)
    wev = WEV(security)
    ely = ELY(RegressionGuard(), knowledge)
    return CoworkRunner(
        pool=pool, store=store, budget=budget, isa=isa, yev=yev, zev=zev,
        xev=xev, wev=wev, ely=ely, trace_dir=trace_dir, max_concurrency=4,
    )


def make_repo(td: str, with_secret: bool = False) -> Path:
    root = Path(td) / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "ok.py").write_text("def suma(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "README.md").write_text("# Proyecto demo\nSin secretos.\n", encoding="utf-8")
    if with_secret:
        (root / "src" / "config.py").write_text(
            "AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n", encoding="utf-8"
        )
    return root
