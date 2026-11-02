"""Tests de las terceras partes empaquetadas: jb_runner, lab_runner, wb_runner.

 Hacen sys.path.insert de <repo>/third_party (son paquetes standalone,
 sin depender de harness_candy). Todo sin red ni docker real: fakes inyectados.
"""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TP = REPO / "third_party"
if str(TP) not in sys.path:
    sys.path.insert(0, str(TP))

from jb_runner import ESTADO_FALLIDO, ESTADO_OK, Job, JobQueue, JobRunner, JobStore  # noqa: E402
from lab_runner import Experimento, desviacion, ic95_bootstrap, media  # noqa: E402
from wb_runner import DockerRunner, HarborClient, HarborError, WorkBuddy  # noqa: E402
from wb_runner.docker_runner import ComandoResultado  # noqa: E402


# ------------------------------------------------------------------ jb_runner
class TestJobQueue(unittest.TestCase):
    def test_prioridad_descendente_fifo_en_empate(self):
        q = JobQueue()
        for j in [Job("baja", prioridad=1), Job("alta", prioridad=10), Job("media", prioridad=5), Job("alta2", prioridad=10)]:
            q.encolar(j)
        self.assertEqual([q.desencolar().id for _ in range(4)], ["alta", "alta2", "media", "baja"])
        self.assertIsNone(q.desencolar())
        self.assertTrue(q.vacia)


class TestJobRunner(unittest.TestCase):
    def test_run_checkpoint_y_resume(self):
        with tempfile.TemporaryDirectory() as td:
            store = JobStore(Path(td) / "jobs.json")
            llamadas = []

            def ej(job):
                llamadas.append(job.id)
                if job.payload.get("falla"):
                    raise RuntimeError("boom")
                return {"score": job.prioridad}

            jobs = [Job("a", 10, {"x": 1}), Job("b", 1, {"falla": True}), Job("c", 5)]
            r1 = JobRunner(store, ej).run(jobs)
            self.assertEqual((r1.procesados, r1.fallidos, r1.reanudado), (2, 1, False))
            self.assertEqual(store.estado("a"), ESTADO_OK)
            self.assertEqual(store.estado("b"), ESTADO_FALLIDO)
            self.assertEqual(llamadas.count("b"), 3)  # max_intentos por defecto

            r2 = JobRunner(store, ej).run(jobs + [Job("d", 3)])
            self.assertTrue(r2.reanudado)
            self.assertEqual(r2.procesados, 3)  # a, c (resume) + d (nuevo)
            self.assertEqual(r2.fallidos, 1)
            self.assertEqual(llamadas.count("a"), 1)  # no se re-ejecuto
            self.assertEqual(llamadas.count("b"), 3)  # fallido final no se reintenta

    def test_reintentar_fallidos(self):
        with tempfile.TemporaryDirectory() as td:
            store = JobStore(Path(td) / "j.json")
            llamadas = []

            def ej(job):
                llamadas.append(job.id)
                raise RuntimeError("siempre")

            jobs = [Job("z", 1, {"falla": True}, max_intentos=1)]
            JobRunner(store, ej).run(jobs)
            JobRunner(store, ej, reintentar_fallidos=True).run(jobs)
            self.assertEqual(llamadas.count("z"), 2)

    def test_store_corrupto_arranca_de_cero(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "roto.json"
            p.write_text("{no es json")
            store = JobStore(p)
            self.assertEqual(store.estado("x"), "pendiente")


# ----------------------------------------------------------------- lab_runner
class TestEstadistica(unittest.TestCase):
    def test_media_desviacion(self):
        self.assertAlmostEqual(media([1, 2, 3]), 2.0)
        self.assertEqual(desviacion([5, 5, 5]), 0.0)
        with self.assertRaises(ValueError):
            media([])

    def test_ic95_contiene_media(self):
        xs = [0.5, 0.6, 0.7, 0.8]
        lo, hi = ic95_bootstrap(xs, n_boot=500, seed=1)
        self.assertLessEqual(lo, media(xs))
        self.assertLessEqual(media(xs), hi)
        self.assertLess(lo, hi)

    def test_ic95_un_valor(self):
        self.assertEqual(ic95_bootstrap([0.3]), (0.3, 0.3))


class TestExperimento(unittest.TestCase):
    def test_grid_y_mejor(self):
        def ev(p):
            return 1.0 - abs(p["k"] - 4) * 0.1 - abs(p["m"] - 3) * 0.05
        res = Experimento("sweep", grid={"k": [1, 2, 4], "m": [2, 3]}, ejecutar=ev, repeticiones=2, max_workers=3, n_boot=200).correr()
        self.assertEqual(res.mejor_params, {"k": 4, "m": 3})
        self.assertAlmostEqual(res.mejor_score, 1.0)
        self.assertEqual(len(res.puntos), 12)  # 6 configs x 2 repeticiones
        self.assertEqual(res.ic95[0], 1.0)  # todas las repeticiones del mejor dan 1.0

    def test_acepta_dict_con_score(self):
        res = Experimento("d", grid={"x": [1]}, ejecutar=lambda p: {"score": 0.9}).correr()
        self.assertAlmostEqual(res.mejor_score, 0.9)

    def test_paralelo_local_es_mas_rapido(self):
        def lenta(p):
            time.sleep(0.15)
            return p["x"]
        t0 = time.time()
        Experimento("par", grid={"x": [1, 2, 3, 4]}, ejecutar=lenta, max_workers=4).correr()
        t_par = time.time() - t0
        t0 = time.time()
        Experimento("ser", grid={"x": [1, 2, 3, 4]}, ejecutar=lenta, max_workers=1).correr()
        t_ser = time.time() - t0
        self.assertLess(t_par, t_ser * 0.75)

    def test_reporte_y_json(self):
        res = Experimento("r", grid={"x": [1, 2]}, ejecutar=lambda p: p["x"] / 10, n_boot=50).correr()
        md = res.reporte_md()
        self.assertIn("| params | score |", md)
        self.assertIn("Mejor configuracion", md)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "res.json"
            res.guardar_json(p)
            d = json.loads(p.read_text())
            self.assertEqual(d["mejor_params"], {"x": 2})
            self.assertEqual(d["n_puntos"], 2)

    def test_grid_vacio_error(self):
        with self.assertRaises(ValueError):
            Experimento("v", grid={}, ejecutar=lambda p: 1)
        with self.assertRaises(ValueError):
            Experimento("v2", grid={"x": []}, ejecutar=lambda p: 1)


# ------------------------------------------------------------------ wb_runner
class TestDockerRunner(unittest.TestCase):
    def setUp(self):
        self.comandos = []

        def fake(argv, stdin=None):
            self.comandos.append((list(argv), stdin))
            return ComandoResultado(list(argv), 0, stdout="ok", stderr="")

        self.docker = DockerRunner(ejecutar=fake)

    def test_build_tag_push(self):
        self.docker.build(".", "img:1", build_args={"A": "1"})
        argv = self.comandos[-1][0]
        self.assertEqual(argv[:2], ["docker", "build"])
        self.assertIn("--build-arg", argv)
        self.docker.tag("img:1", "reg/img:1")
        self.assertEqual(self.comandos[-1][0][:2], ["docker", "tag"])
        self.docker.push("reg/img:1")
        self.assertEqual(self.comandos[-1][0], ["docker", "push", "reg/img:1"])

    def test_login_clave_solo_por_stdin(self):
        self.docker.login("reg.co", "user", "clave-secreta")
        argv, stdin = self.comandos[-1]
        self.assertIn("--password-stdin", argv)
        self.assertEqual(stdin, "clave-secreta\n")
        self.assertNotIn("clave-secreta", " ".join(argv))  # jamas en argv

    def test_login_sin_clave_error(self):
        with self.assertRaises(ValueError):
            self.docker.login("reg.co", "user", "")

    def test_run_con_volumenes_y_env_nombres(self):
        self.docker.run("img", ["python", "-m", "app"], nombre="c1", volumenes={"/tmp/a": "/w"}, variables=["XKIRO_API_KEY"])
        argv = self.comandos[-1][0]
        self.assertIn("--rm", argv)
        self.assertIn("--name", argv)
        self.assertIn("-v", argv)
        i = argv.index("-e")
        self.assertEqual(argv[i + 1], "XKIRO_API_KEY")  # solo el nombre, sin valor
        self.assertEqual(argv[-2:], ["-m", "app"])

    def test_fallo_lanza(self):
        d = DockerRunner(ejecutar=lambda argv, stdin=None: ComandoResultado(list(argv), 1, stderr="no daemon"))
        with self.assertRaises(RuntimeError):
            d.build(".", "x:1")

    def test_dry_run_no_ejecuta(self):
        d = DockerRunner(dry_run=True)
        self.assertTrue(d.disponible())
        r = d.build(".", "x:1")
        self.assertTrue(r.dry_run and r.ok)


def _transport_repos(req, timeout=30):
    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            if "/repositories?" in req.full_url:
                return json.dumps([{"name": "app", "artifact_count": 2, "size": 99, "update_time": "2026-11-02"}]).encode()
            return json.dumps({"digest": "sha256:abc"}).encode()
    return R()


class TestHarborClient(unittest.TestCase):
    def test_credenciales_solo_de_env(self):
        hc = HarborClient("reg.co", environ={})
        with self.assertRaises(HarborError):
            hc.credenciales()
        hc2 = HarborClient("reg.co", environ={"HARBOR_USERNAME": "u", "HARBOR_PASSWORD": "p"})
        self.assertEqual(hc2.credenciales(), ("u", "p"))

    def test_imagen_tag(self):
        hc = HarborClient("reg.empresa.co/", proyecto="hc/", environ={"HARBOR_USERNAME": "u", "HARBOR_PASSWORD": "p"})
        self.assertEqual(hc.imagen_tag("app", "v1"), "reg.empresa.co/hc/app:v1")

    def test_api_rest_con_transport_falso(self):
        comandos = []
        def fake(argv, stdin=None):
            comandos.append((list(argv), stdin))
            return ComandoResultado(list(argv), 0, stdout="ok")
        env = {"HARBOR_USERNAME": "u", "HARBOR_PASSWORD": "p-secreto"}
        hc = HarborClient("reg.empresa.co", proyecto="hc",
                          docker=DockerRunner(ejecutar=fake), environ=env, transport=_transport_repos)
        r = hc.login()
        self.assertTrue(r.ok)
        # login: clave por stdin, jamas en argv
        login_cmd = [c for c in comandos if c[0][1:2] == ["login"]][0]
        self.assertEqual(login_cmd[1], "p-secreto\n")
        self.assertNotIn("p-secreto", " ".join(login_cmd[0]))
        repos = hc.listar_repositorios()
        self.assertEqual(repos[0].nombre, "app")
        self.assertEqual(repos[0].artefactos, 2)
        self.assertEqual(hc.estadistica_imagen("app", "v1")["digest"], "sha256:abc")


class TestWorkBuddy(unittest.TestCase):
    def test_pipeline_dry_run(self):
        env = {"HARBOR_USERNAME": "u", "HARBOR_PASSWORD": "p"}
        wb = WorkBuddy.from_env("reg.empresa.co", proyecto="hc", dry_run=True, environ=env)
        res = wb.run("mi-app", dockerfile_dir=".", comando=["python", "-m", "app"], artefactos_de="/out", artefactos_dir="art")
        self.assertTrue(res.ok)
        self.assertEqual([p["paso"] for p in res.pasos], ["build", "login", "tag", "push", "run", "artefactos"])
        self.assertTrue(all(p["ok"] for p in res.pasos))
        self.assertEqual(res.tag_remoto, "reg.empresa.co/hc/mi-app:latest")
        json.dumps(res.to_dict())

    def test_pipeline_fallo_build(self):
        env = {"HARBOR_USERNAME": "u", "HARBOR_PASSWORD": "p"}
        wb = WorkBuddy.from_env("reg.co", proyecto="hc", dry_run=False, environ=env)
        wb.docker = DockerRunner(ejecutar=lambda argv, stdin=None: ComandoResultado(list(argv), 1, stderr="sin daemon"))
        res = wb.run("x", dockerfile_dir=".")
        self.assertFalse(res.ok)
        self.assertFalse(res.pasos[0]["ok"])
        self.assertIn("error", [p["paso"] for p in res.pasos])


if __name__ == "__main__":
    unittest.main()
