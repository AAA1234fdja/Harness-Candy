"""Tests de reintentos con backoff exponencial + jitter determinista."""
import unittest

import _path  # noqa: F401
from harness_candy.retry import RetryExhausted, backoff_delays, retry_call, retryable


class TestBackoffDelays(unittest.TestCase):
    def test_determinista_con_seed(self):
        a = backoff_delays(5, base_delay=0.1, seed=42)
        b = backoff_delays(5, base_delay=0.1, seed=42)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 4)  # attempts-1 esperas

    def test_otra_seed_otros_valores(self):
        a = backoff_delays(5, seed=1)
        b = backoff_delays(5, seed=2)
        self.assertNotEqual(a, b)

    def test_cap_en_max_delay(self):
        d = backoff_delays(10, base_delay=1.0, max_delay=2.0, jitter=0.0, seed=0)
        self.assertTrue(all(x <= 2.0 for x in d))
        self.assertAlmostEqual(d[0], 1.0)

    def test_crece_hasta_el_cap(self):
        d = backoff_delays(6, base_delay=0.5, factor=2.0, max_delay=10.0, jitter=0.0, seed=0)
        self.assertEqual([round(x, 6) for x in d], [0.5, 1.0, 2.0, 4.0, 8.0])


class TestRetryCall(unittest.TestCase):
    def test_exito_en_el_primer_intento(self):
        llamadas = []

        def fn():
            llamadas.append(1)
            return "ok"

        self.assertEqual(retry_call(fn, attempts=3, sleep=lambda s: None), "ok")
        self.assertEqual(len(llamadas), 1)

    def test_exito_tras_fallos(self):
        estado = {"n": 0}

        def fn():
            estado["n"] += 1
            if estado["n"] < 3:
                raise ValueError("fallo transitorio")
            return "ok"

        self.assertEqual(retry_call(fn, attempts=5, sleep=lambda s: None), "ok")
        self.assertEqual(estado["n"], 3)

    def test_agotado_lanza_retry_exhausted(self):
        def fn():
            raise ValueError("siempre falla")

        with self.assertRaises(RetryExhausted) as ctx:
            retry_call(fn, attempts=3, sleep=lambda s: None)
        self.assertEqual(ctx.exception.attempts, 3)
        self.assertIsInstance(ctx.exception.last, ValueError)

    def test_solo_reintenta_las_excepciones_indicadas(self):
        def fn():
            raise KeyError("no reintentar")

        with self.assertRaises(KeyError):
            retry_call(fn, attempts=3, retry_on=(ValueError,), sleep=lambda s: None)

    def test_on_retry_recibe_intento_y_espera(self):
        eventos = []

        def fn():
            raise ValueError("x")

        with self.assertRaises(RetryExhausted):
            retry_call(fn, attempts=3, base_delay=0.1, seed=7, sleep=lambda s: None,
                       on_retry=lambda n, e, w: eventos.append((n, round(w, 3))))
        self.assertEqual([n for n, _ in eventos], [1, 2])
        # las esperas son las del backoff determinista
        esperado = backoff_delays(3, base_delay=0.1, seed=7)
        self.assertEqual([w for _, w in eventos], [round(x, 3) for x in esperado])

    def test_sleep_inyectado_efectivamente_espera(self):
        esperas = []

        def fn():
            raise ValueError("x")

        with self.assertRaises(RetryExhausted):
            retry_call(fn, attempts=3, base_delay=0.01, jitter=0.0, seed=0, sleep=esperas.append)
        self.assertEqual(len(esperas), 2)
        self.assertTrue(all(w >= 0 for w in esperas))

    def test_attempts_invalido(self):
        with self.assertRaises(ValueError):
            retry_call(lambda: 1, attempts=0)

    def test_decorator_retryable(self):
        estado = {"n": 0}

        @retryable(attempts=4, sleep=lambda s: None)
        def fn():
            estado["n"] += 1
            if estado["n"] < 2:
                raise ValueError("x")
            return 42

        self.assertEqual(fn(), 42)
        self.assertEqual(estado["n"], 2)
        self.assertEqual(fn.__name__, "fn")


if __name__ == "__main__":
    unittest.main()
