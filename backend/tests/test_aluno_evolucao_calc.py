import unittest
from datetime import date, datetime, timezone

from backend.tests import _path  # noqa: F401
import aluno_evolucao_calc as c


def s(dia, ref="supino", carga=40, reps=10, ok=True, grupo="peito", hora=10):
    return {"registrada_em": datetime(2026, 10, dia, hora, tzinfo=timezone.utc), "exercicio_ref": ref,
            "exercicio_nome": ref, "grupo": grupo, "carga": carga, "reps": reps, "concluida": ok}


class CalcTests(unittest.TestCase):
    def test_volume_ignora_nao_concluidas(self):
        self.assertEqual(c.volume([s(1, carga=10, reps=10), s(1, carga=100, reps=10, ok=False)]), 100)

    def test_recorde_por_carga_depois_reps(self):
        r = c.recordes([s(1, carga=40, reps=10), s(2, carga=50, reps=5), s(3, carga=50, reps=8), s(4, carga=60, ok=False)])
        self.assertEqual((r["supino"]["carga"], r["supino"]["reps"], r["supino"]["data"]), (50, 8, "2026-10-03"))

    def test_recorde_ignora_peso_do_corpo(self):
        self.assertEqual(c.recordes([s(1, carga=0, reps=20)]), {})

    def test_sequencia_semanal(self):
        hoje = date(2026, 10, 12)  # segunda
        dias = {date(2026, 10, 6), date(2026, 9, 29), date(2026, 9, 22)}
        self.assertEqual(c.sequencia_semanal(dias, hoje), 3)  # semana atual vazia não quebra
        self.assertEqual(c.sequencia_semanal(dias | {date(2026, 10, 12)}, hoje), 4)
        self.assertEqual(c.sequencia_semanal({date(2026, 9, 22)}, hoje), 0)  # buraco quebra
        self.assertEqual(c.sequencia_semanal(set(), hoje), 0)

    def test_mapa_7_dias(self):
        agora = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
        m = c.mapa_do_corpo([s(11), s(11), s(2), s(10, grupo="costas"), s(10, grupo="costas", ok=False)], agora)
        self.assertEqual(m, {"peito": 2, "costas": 1})

    def test_pulso_segunda_a_domingo(self):
        p = c.pulso_semanal([s(12), s(12), s(14), s(18), s(19), s(11)], date(2026, 10, 14))
        self.assertEqual(p, [2, 0, 1, 0, 0, 0, 1])

    def test_sugestao_sobe_quando_completa(self):
        r = c.sugerir_carga([{"carga": 40, "reps": 10, "meta_reps": 10, "concluida": True}] * 3)
        self.assertEqual((r["carga"], r["motivo"]), (42.5, "subir"))

    def test_sugestao_mantem_quando_falha(self):
        r = c.sugerir_carga([{"carga": 40, "reps": 10, "meta_reps": 10, "concluida": True},
                             {"carga": 40, "reps": 7, "meta_reps": 10, "concluida": True}])
        self.assertEqual((r["carga"], r["motivo"]), (40, "manter"))
        r = c.sugerir_carga([{"carga": 40, "reps": 10, "concluida": False}])
        self.assertEqual(r["motivo"], "manter")

    def test_sugestao_sem_historico_e_peso_do_corpo(self):
        self.assertEqual(c.sugerir_carga([])["motivo"], "sem_historico")
        self.assertEqual(c.sugerir_carga([{"carga": 0, "reps": 10, "concluida": True}])["motivo"], "peso_do_corpo")

    def test_resumo_semanal(self):
        r = c.resumo_semanal([s(12), s(13), s(5, carga=10)], date(2026, 10, 14))
        self.assertEqual((r["treinos"], r["series"], r["volume"], r["volume_anterior"], r["treinos_anterior"]),
                         (2, 2, 800, 100, 1))


if __name__ == "__main__":
    unittest.main()
