import unittest
from datetime import date, datetime, timedelta, timezone

from backend.tests import _path  # noqa: F401
import desafios_regras as dr
import gerador_treino as gt
import mensalidade_regras as mr

SEG = "segredo-de-teste-com-mais-de-32-caracteres!!"
AGORA = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


class Mensalidade(unittest.TestCase):
    def test_liberacao_igual_a_catraca(self):
        v = date(2026, 10, 20)
        self.assertEqual(mr.decidir_liberacao("ativo", 1, v, "em_dia"), (True, None))
        self.assertEqual(mr.decidir_liberacao("inativo", 1, v, "em_dia"), (False, "aluno_inativo"))
        self.assertEqual(mr.decidir_liberacao("ativo", None, v, "em_dia"), (False, "plano_nao_cadastrado"))
        self.assertEqual(mr.decidir_liberacao("ativo", 1, None, "em_dia"), (False, "sem_pagamento_em_aberto"))
        self.assertEqual(mr.decidir_liberacao("ativo", 1, v, "atrasado"), (False, "mensalidade_atrasada"))

    def test_situacao(self):
        h = date(2026, 10, 12)
        self.assertEqual(mr.situacao(None, h)["estado"], "sem_cobranca")
        self.assertEqual(mr.situacao(date(2026, 10, 10), h), {"estado": "atrasada", "dias": 2})
        self.assertEqual(mr.situacao(date(2026, 10, 17), h), {"estado": "vence_em_breve", "dias": 5})
        self.assertEqual(mr.situacao(date(2026, 10, 18), h)["estado"], "em_dia")

    def test_qr_valido_adulterado_expirado_e_de_outra_academia(self):
        cod, exp = mr.gerar_qr(SEG, 7, 3, AGORA)
        self.assertTrue(cod.startswith("fqm_"))
        self.assertEqual(exp, AGORA + timedelta(seconds=120))
        self.assertEqual(mr.validar_qr(SEG, cod, 3, AGORA + timedelta(seconds=119)), 7)
        self.assertIsNone(mr.validar_qr(SEG, cod, 3, AGORA + timedelta(seconds=121)))
        self.assertIsNone(mr.validar_qr(SEG, cod, 4, AGORA))               # outra academia
        self.assertIsNone(mr.validar_qr("outro-segredo-com-mais-de-32-caracteres!!", cod, 3, AGORA))
        corpo, ass = cod[4:].rsplit(".", 1)
        self.assertIsNone(mr.validar_qr(SEG, "fqm_" + corpo[:-2] + "xx." + ass, 3, AGORA))
        self.assertIsNone(mr.validar_qr(SEG, "fqm_" + corpo + "." + "0" * 32, 3, AGORA))
        for lixo in ("", "fqm_", "fqm_abc", "xyz", "fqm_." , "fqm_" + "a" * 500):
            self.assertIsNone(mr.validar_qr(SEG, lixo, 3, AGORA))

    def test_dois_qr_do_mesmo_aluno_sao_diferentes(self):
        self.assertNotEqual(mr.gerar_qr(SEG, 7, 3, AGORA)[0], mr.gerar_qr(SEG, 7, 3, AGORA)[0])


def s(dia, h, carga=50, reps=10, ok=True):
    return {"registrada_em": datetime(2026, 10, dia, h, 0, tzinfo=timezone.utc), "carga": carga, "reps": reps, "concluida": ok}


class Desafios(unittest.TestCase):
    ENTRADA = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)

    def test_treino_so_conta_com_3_series_concluidas_no_dia(self):
        series = [s(5, 12), s(5, 13), s(5, 14), s(6, 12), s(6, 13), s(7, 12, ok=False), s(7, 13, ok=False), s(7, 14, ok=False)]
        self.assertEqual(dr.pontuar(series, "treinos", date(2026, 10, 1), date(2026, 10, 31), self.ENTRADA, "UTC"), 1.0)

    def test_volume_soma_carga_vezes_reps_com_teto_por_serie(self):
        series = [s(5, 12, 100, 10), s(5, 13, 1000, 500)]  # 1000 + (500000 → teto 10000)
        self.assertEqual(dr.pontuar(series, "volume", date(2026, 10, 1), date(2026, 10, 31), self.ENTRADA, "UTC"), 11000.0)

    def test_nao_conta_antes_da_entrada_nem_fora_do_periodo(self):
        entrou = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
        series = [s(5, 12, 100, 10), s(10, 12, 100, 10), s(20, 12, 100, 10), s(25, 12, 100, 10)]
        self.assertEqual(dr.pontuar(series, "volume", date(2026, 10, 1), date(2026, 10, 20), entrou, "UTC"), 2000.0)

    def test_dia_segue_o_fuso_da_academia(self):
        # 01:00 UTC do dia 6 ainda é dia 5 em São Paulo
        series = [{"registrada_em": datetime(2026, 10, 6, 1, 0, tzinfo=timezone.utc), "carga": 10, "reps": 10, "concluida": True}] * 3
        self.assertEqual(dr.pontuar(series, "treinos", date(2026, 10, 6), date(2026, 10, 6), self.ENTRADA, "America/Sao_Paulo"), 0.0)
        self.assertEqual(dr.pontuar(series, "treinos", date(2026, 10, 5), date(2026, 10, 5), self.ENTRADA, "America/Sao_Paulo"), 1.0)

    def test_nome_publico(self):
        self.assertEqual(dr.nome_publico("Ana Souza Lima"), "Ana L.")
        self.assertEqual(dr.nome_publico("Ana"), "Ana")
        self.assertEqual(dr.nome_publico("  "), "Aluno")

    def test_classificacao_com_empate_e_zero(self):
        r = dr.classificar([{"aluno_id": 1, "nome": "Bia", "valor": 5}, {"aluno_id": 2, "nome": "Ana", "valor": 5},
                            {"aluno_id": 3, "nome": "Caio", "valor": 3}, {"aluno_id": 4, "nome": "Dani", "valor": 0}])
        self.assertEqual([(p["nome"], p["posicao"]) for p in r], [("Ana", 1), ("Bia", 1), ("Caio", 3), ("Dani", None)])

    def test_situacao_do_desafio(self):
        h = date(2026, 10, 12)
        self.assertEqual(dr.situacao_do_desafio(date(2026, 10, 13), date(2026, 10, 20), True, h), "em_breve")
        self.assertEqual(dr.situacao_do_desafio(date(2026, 10, 1), date(2026, 10, 12), True, h), "em_andamento")
        self.assertEqual(dr.situacao_do_desafio(date(2026, 10, 1), date(2026, 10, 11), True, h), "encerrado")
        self.assertEqual(dr.situacao_do_desafio(date(2026, 10, 1), date(2026, 10, 30), False, h), "encerrado")


def cat():
    out = []
    def add(i, g, eq, nv, tempo=False):
        out.append({"ref": "c:" + i, "nome": i, "grupo": g, "equipamento": eq, "nivel": nv, "tempo": tempo})
    for g in gt.NOME_GRUPO:
        add(f"{g}_barra", g, "Barra", "Intermediario".replace("Intermediario", "Intermediário"))
        add(f"{g}_maq", g, "Máquina", "Iniciante")
        add(f"{g}_hal", g, "Halteres", "Iniciante")
        add(f"{g}_corpo", g, "Peso do corpo", "Iniciante")
        add(f"{g}_av", g, "Polia", "Avançado")
    return out


class Gerador(unittest.TestCase):
    def test_estrutura_por_dias(self):
        for dias in range(2, 7):
            r = gt.gerar(cat(), "hipertrofia", "Intermediário", dias)
            self.assertEqual(len(r["treinos"]), dias)
            self.assertEqual(len({t["letra"] for t in r["treinos"]}), dias)
            self.assertEqual(r["avisos"], [])
            for t in r["treinos"]:
                self.assertEqual(t["blocos"][0]["grupo"], "aquecimento")
                self.assertEqual(len(t["dias_semana"]), 1)

    def test_nivel_iniciante_nunca_recebe_exercicio_avancado_nem_intermediario(self):
        r = gt.gerar(cat(), "hipertrofia", "Iniciante", 3)
        refs = [i["ref"] for t in r["treinos"] for b in t["blocos"] for i in b["itens"] if "ref" in i]
        self.assertTrue(refs)
        self.assertFalse([x for x in refs if x.endswith("_av") or x.endswith("_barra")])

    def test_aparelho_indisponivel_e_respeitado_e_avisa_quando_falta_tudo(self):
        r = gt.gerar(cat(), "hipertrofia", "Avançado", 3, indisponiveis={"Barra", "Polia"})
        refs = [i["ref"] for t in r["treinos"] for b in t["blocos"] for i in b["itens"] if "ref" in i]
        self.assertFalse([x for x in refs if x.endswith("_barra") or x.endswith("_av")])
        so_polia = [e for e in cat() if e["equipamento"] == "Polia"]
        r2 = gt.gerar(so_polia, "hipertrofia", "Avançado", 3, indisponiveis={"Polia"})
        self.assertTrue(r2["avisos"])
        self.assertTrue(all(len(t["blocos"]) == 1 for t in r2["treinos"]))  # só o aquecimento

    def test_objetivo_define_series_reps_descanso_e_cardio(self):
        f = gt.gerar(cat(), "forca", "Avançado", 3)["treinos"][0]
        item = f["blocos"][1]["itens"][0]
        self.assertEqual((item["series"], item["reps"], item["descanso_s"]), (5, "4-6", 120))
        e = gt.gerar(cat(), "emagrecimento", "Iniciante", 3)["treinos"][0]
        self.assertEqual(e["blocos"][-1]["grupo"], "cardio")
        self.assertEqual(e["blocos"][-1]["itens"][0]["reps"], "1200")
        self.assertNotEqual(gt.gerar(cat(), "hipertrofia", "Iniciante", 3)["treinos"][0]["blocos"][-1]["grupo"], "cardio")

    def test_deterministico_e_variacao_troca_exercicios(self):
        a = gt.gerar(cat(), "hipertrofia", "Avançado", 3)
        self.assertEqual(a, gt.gerar(cat(), "hipertrofia", "Avançado", 3))
        b = gt.gerar(cat(), "hipertrofia", "Avançado", 3, variacao=1)
        self.assertNotEqual(a["treinos"], b["treinos"])

    def test_sem_repetir_exercicio_no_mesmo_bloco(self):
        for t in gt.gerar(cat(), "hipertrofia", "Avançado", 5)["treinos"]:
            for b in t["blocos"]:
                refs = [i.get("ref") for i in b["itens"] if i.get("ref")]
                self.assertEqual(len(refs), len(set(refs)))

    def test_entradas_invalidas(self):
        for args in (("x", "Iniciante", 3), ("forca", "Mestre", 3), ("forca", "Iniciante", 7), ("forca", "Iniciante", 1)):
            with self.assertRaises(gt.PedidoInvalido):
                gt.gerar(cat(), *args)

    def test_tamanho_cabe_nos_limites_do_treino(self):
        import aluno_treinos as at
        for dias in range(2, 7):
            for t in gt.gerar(cat(), "hipertrofia", "Avançado", dias)["treinos"]:
                self.assertLessEqual(len(t["blocos"]), at.MAX_BLOCOS)
                for b in t["blocos"]:
                    self.assertLessEqual(len(b["itens"]), at.MAX_ITENS)


if __name__ == "__main__":
    unittest.main()
