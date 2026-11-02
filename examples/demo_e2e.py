#!/usr/bin/env python3
"""Demo end-to-end de Ely-Cowork (diseno combinado ADK+Harness^2).

Crea un repositorio temporal con un secreto hardcodeado, ejecuta el flujo
completo (ISA -> YEV/DAG -> ZEV -> XEV con adaptador Harness^2 -> WEV -> ELY)
y muestra el informe wev, las trazas JSONL y la auditoria de ELY.

Uso:  python examples/demo_e2e.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness_candy.agents import ScriptedBackend, SecurityScanAgent
from harness_candy.components import ELY, ISA, WEV, XEV, YEV, ZEV
from harness_candy.harness import Budget, HarnessStore
from harness_candy.memory import KnowledgeMemory
from harness_candy.pool import LIGHT_TAG, POWER_TAG, ModelPool, PoolEntry
from harness_candy.quality import RegressionGuard
from harness_candy.runner import CoworkRunner
from harness_candy.security import SecurityGate


def build_runner(trace_dir: Path) -> CoworkRunner:
    pool = ModelPool()
    pool.add(PoolEntry("flash-1", "modelo-ligero-1", "KEY_FLASH_1", 0.0001, roles={"xev", "zev"}, tag=LIGHT_TAG))
    pool.add(PoolEntry("flash-2", "modelo-ligero-2", "KEY_FLASH_2", 0.0001, roles={"xev", "zev"}, tag=LIGHT_TAG))
    pool.add(PoolEntry("opus-1", "modelo-potente-1", "KEY_OPUS_1", 0.015, roles={"isa", "ely"}, tag=POWER_TAG))
    knowledge = KnowledgeMemory(Path(trace_dir).parent / "knowledge.json")
    security = SecurityGate()
    agent = SecurityScanAgent("XEV", "modelo-ligero-1", ScriptedBackend(lambda *a, **k: "ok"))
    # Harness ya validado (biblioteca de Harness^2): se reutiliza sin sondear.
    from harness_candy.harness import Harness

    store = HarnessStore()
    validado = Harness(guardrails=["json_strict"], skills=["secrets_v2", "recomendaciones"])
    for kind in ("security_scan", "write_report"):
        for model in ("modelo-ligero-1", "modelo-ligero-2"):
            store.save(kind, model, validado, evidence={"q": [1.0, 1.0, 1.0]})
    return CoworkRunner(
        pool=pool,
        store=store,
        budget=Budget(total=10_000, beta=0.5, k=2, m=3),
        isa=ISA(model="modelo-potente-1"),
        yev=YEV(pool),
        zev=ZEV(knowledge, sources=[Path(__file__).resolve().parents[1] / "README.md"]),
        xev=XEV({"XEV": agent}, security),
        wev=WEV(security),
        ely=ELY(RegressionGuard(), knowledge),
        trace_dir=trace_dir,
        max_concurrency=4,
    )


def show(res, titulo: str) -> None:
    print("=" * 78)
    print(titulo)
    print("run_id:", res.run_id)
    print("\n--- RESULTADOS DEL DAG (XEV + WEV) ---")
    for tid, r in res.dag_results.items():
        print(f"{tid}: status={r.status} intentos={r.attempts} q={res.qs.get(tid, 0):.3f}")
        if r.wev:
            print(f"   veredicto={r.wev.veredicto} checks={r.wev.checks}")
            for h in r.wev.hallazgos:
                print(f"   hallazgo [{h.severidad}] ({h.herramienta}): {h.detalle[:90]}")

    print("\n--- AUDITORIA GLOBAL (ELY) ---")
    print(json.dumps({k: v for k, v in res.ely_audit.items() if k != "detalle"}, ensure_ascii=False, indent=2))

    print("\n--- TRAZAS JSONL (primeras lineas) ---")
    print("archivo:", res.trace_path)
    for line in Path(res.trace_path).read_text().strip().splitlines()[:6]:
        e = json.loads(line)
        print(f"  phase={e['phase']:<10} task={e['task_id']} model={e['model']:<18} seed={e['seed']:<4} q={e['q']:.3f} harness={e['harness'][:18]}")
    print(f"  costo de adaptacion (sondeos Harness^2): {res.costo_adaptacion:.1f} corridas")
    print(f"  duracion total: {res.duracion:.2f}s")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ely-demo-") as td:
        td = Path(td)
        repo_limpio = td / "repo_limpio"
        (repo_limpio / "src").mkdir(parents=True)
        (repo_limpio / "src" / "ok.py").write_text("def suma(a, b):\n    return a + b\n", encoding="utf-8")
        (repo_limpio / "README.md").write_text("# repo demo limpio\n", encoding="utf-8")
        repo_con_secreto = td / "repo_con_secreto"
        (repo_con_secreto / "src").mkdir(parents=True)
        (repo_con_secreto / "src" / "ok.py").write_text("def resta(a, b):\n    return a - b\n", encoding="utf-8")
        (repo_con_secreto / "src" / "config.py").write_text("AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n", encoding="utf-8")

        runner = build_runner(td / "traces")
        print("### CASO 1: repo LIMPIO (WEV debe aprobar; DONE = CORRECT aqui) ###")
        res1 = runner.run(
            f"Generar un informe de seguridad del repositorio {repo_limpio}",
            inputs={"root": str(repo_limpio)}, seed=0,
        )
        show(res1, "CASO 1: repo limpio")

        print()
        print("### CASO 2: repo CON SECRETO hardcodeado (WEV detecta, rechaza, escala) ###")
        res2 = runner.run(
            f"Generar un informe de seguridad del repositorio {repo_con_secreto}",
            inputs={"root": str(repo_con_secreto)}, seed=1,
        )
        show(res2, "CASO 2: repo con secreto AKIA...")

        print("\n--- PLAN (ISA) del caso 2 ---")
        print(json.dumps(res2.plan, ensure_ascii=False, indent=2)[:700])


if __name__ == "__main__":
    main()
