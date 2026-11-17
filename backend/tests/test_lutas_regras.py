import unittest
from datetime import date, datetime, time, timedelta, timezone

from backend.tests import _path  # noqa: F401
import lutas_regras as r


class RegrasLutas(unittest.TestCase):
    def test_ocorrencia_usa_o_fuso_da_academia(self):
        a, b = r.ocorrencia(date(2026, 10, 12), time(19, 0), time(20, 0), "America/Sao_Paulo")
        self.assertEqual(a, datetime(2026, 10, 12, 22, 0, tzinfo=timezone.utc))  # UTC-3
        self.assertEqual(b - a, timedelta(hours=1))

    def test_janela_de_30_min_antes_a_15_depois(self):
        ini = datetime(2026, 10, 12, 22, 0, tzinfo=timezone.utc)
        self.assertFalse(r.na_janela(ini - timedelta(minutes=31), ini))
        self.assertTrue(r.na_janela(ini - timedelta(minutes=30), ini))
        self.assertTrue(r.na_janela(ini + timedelta(minutes=15), ini))
        self.assertFalse(r.na_janela(ini + timedelta(minutes=16), ini))

    def test_dia_da_semana_domingo_zero(self):
        self.assertEqual(r.dia_da_semana(date(2026, 10, 11)), 0)  # domingo
        self.assertEqual(r.dia_da_semana(date(2026, 10, 12)), 1)  # segunda
        self.assertEqual(r.dia_da_semana(date(2026, 10, 17)), 6)

    def test_haversine_conhecido(self):
        # ~111,2 km por grau de latitude
        d = r.haversine_m(0.0, 0.0, 1.0, 0.0)
        self.assertAlmostEqual(d, 111_195, delta=300)
        self.assertEqual(r.haversine_m(-23.55, -46.63, -23.55, -46.63), 0)

    def test_raio(self):
        c = (-23.5505, -46.6333)
        self.assertTrue(r.dentro_do_raio(-23.5506, -46.6333, *c, 150))
        self.assertFalse(r.dentro_do_raio(-23.5605, -46.6333, *c, 150))  # ~1,1 km

    def test_coordenada_invalida(self):
        self.assertFalse(r.coordenada_valida(91, 0))
        self.assertFalse(r.coordenada_valida("x", 1))
        self.assertFalse(r.coordenada_valida(0, 0))
        self.assertTrue(r.coordenada_valida(-23.5, -46.6))

    def test_transicoes(self):
        self.assertEqual(r.transicao(None, "confirmar"), "confirmada")
        self.assertEqual(r.transicao("confirmada", "confirmar"), "confirmada")
        self.assertEqual(r.transicao("validada", "confirmar"), "validada")
        self.assertEqual(r.transicao("ausente", "confirmar"), "ausente")
        self.assertEqual(r.transicao("confirmada", "validar"), "validada")
        self.assertEqual(r.transicao("validada", "ausentar"), "ausente")
        with self.assertRaises(ValueError):
            r.transicao(None, "x")

    def test_ajuste_retroativo_24h(self):
        fim = datetime(2026, 10, 12, 23, 0, tzinfo=timezone.utc)
        self.assertTrue(r.pode_ajustar(fim + timedelta(hours=24), fim))
        self.assertFalse(r.pode_ajustar(fim + timedelta(hours=24, seconds=1), fim))

    def test_elegibilidade_atestado_vagas(self):
        self.assertTrue(r.elegivel({1, 2}, 2))
        self.assertFalse(r.elegivel(set(), 2))
        self.assertTrue(r.atestado_ok(date(2026, 10, 12), date(2026, 10, 12)))
        self.assertFalse(r.atestado_ok(date(2026, 10, 11), date(2026, 10, 12)))
        self.assertFalse(r.atestado_ok(None, date(2026, 10, 12)))
        self.assertEqual(r.vagas(10, 12), 0)

    def test_progresso_de_faixa(self):
        fx = [{"nome": "Branca", "ordem": 0, "aulas_minimas": 0}, {"nome": "Azul", "ordem": 1, "aulas_minimas": 100},
              {"nome": "Roxa", "ordem": 2, "aulas_minimas": 300}]
        p = r.progresso_faixa(50, fx, 0)
        self.assertEqual((p["atual"], p["proxima"], p["faltam"], p["percentual"]), ("Branca", "Azul", 50, 50))
        self.assertEqual(r.progresso_faixa(500, fx, 2)["proxima"], None)
        self.assertEqual(r.progresso_faixa(0, fx, None)["proxima"], "Branca")


if __name__ == "__main__":
    unittest.main()
