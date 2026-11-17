import unittest
from datetime import date, datetime, timedelta, timezone

from backend.tests import _path  # noqa: F401
from backend.tests.pg_temp import TempPostgres
from backend.tests import _aluno_fixtures as fx
from backend.tests._asgi import chamar
import aluno_auth
import aluno_gerador
import aluno_mensalidade
import desafios
import seguranca

_pg = None
HOJE = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def setUpModule():
    global _pg
    _pg = TempPostgres().start()


def tearDownModule():
    _pg.stop()


def _ok(conn, academia_id):
    return True


class Base(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        self.conn = fx.conectar(_pg.dsn)
        self.conn.execute("TRUNCATE desafios_participacao, desafios, academia_equipamentos, aluno_series_registradas, treino_itens, treino_blocos, treinos, "
                          "pagamentos, aluno_sessoes, aluno_credenciais, alunos, planos, usuarios, academia_local, academia_recursos, academias RESTART IDENTITY CASCADE")
        self.conn.commit()
        self.aid = fx.criar_academia(self.conn)
        self.outra = fx.criar_academia(self.conn, nome="Outra")
        for a in (self.aid, self.outra):
            for r in ("mensalidade_qr", "desafios", "gerador_treino"):
                self.conn.execute("INSERT INTO academia_recursos (academia_id, recurso, ligado) VALUES (%s,%s,TRUE)", (a, r))
        self.plano = self.conn.execute("INSERT INTO planos (academia_id, nome, valor, duracao_dias) VALUES (%s,'Mensal',99.9,30) RETURNING id", (self.aid,)).fetchone()["id"]
        self.ana = self._aluno("ana@gmail.com", "Ana Souza Lima", "d1")
        self.bia = self._aluno("bia@gmail.com", "Bia Santos", "d2")
        self.cai = self._aluno("cai@gmail.com", "Caio", "d3")
        self.de_fora = self._aluno("fora@gmail.com", "Fora Total", "d4", academia=self.outra)
        self.conn.commit()
        self.dono = {"id": 1, "academia_id": self.aid, "papel": "dono", "nome": "D"}
        self.usuario = self.dono
        self.aluno_atual = self.ana
        self.app = FastAPI()
        for m in (aluno_mensalidade, desafios, aluno_gerador):
            self.app.include_router(m.router)
        o = self.app.dependency_overrides
        o[aluno_auth.conexao] = lambda: self.conn
        o[seguranca.somente_dono] = lambda: self._dono()
        o[seguranca.usuario_de_academia] = lambda: self.usuario
        o[aluno_auth.aluno_atual] = lambda: self.conn.execute("SELECT id, nome, email, academia_id, plano_id, status FROM alunos WHERE id = %s", (self.aluno_atual,)).fetchone()
        aluno_auth.ASSINATURA_OK = _ok
        aluno_auth._limitador = None
        self._agoras = (aluno_mensalidade.AGORA, desafios.AGORA)
        aluno_mensalidade.AGORA = desafios.AGORA = lambda: HOJE

    def tearDown(self):
        aluno_mensalidade.AGORA, desafios.AGORA = self._agoras
        aluno_auth.ASSINATURA_OK = aluno_auth._assinatura_em_dia
        aluno_auth._limitador = None
        self.conn.close()

    def _dono(self):
        if self.usuario["papel"] != "dono":
            raise aluno_mensalidade._erro(403, "sem_permissao")
        return self.usuario

    def _aluno(self, email, nome, doc, academia=None, plano=True):
        ac = academia or self.aid
        return self.conn.execute("INSERT INTO alunos (academia_id, nome, documento, email, plano_id) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                                 (ac, nome, doc, email, self.plano if plano and ac == self.aid else None)).fetchone()["id"]

    def api(self, metodo, caminho, corpo=None):
        return chamar(self.app, metodo, caminho, corpo, {})

    def flag(self, recurso, ligado, academia=None):
        self.conn.execute("UPDATE academia_recursos SET ligado = %s WHERE academia_id = %s AND recurso = %s", (ligado, academia or self.aid, recurso))
        self.conn.commit()


class MensalidadeTests(Base):
    def cobranca(self, aluno, vencimento, status="em_aberto", valor=99.9):
        self.conn.execute("INSERT INTO pagamentos (academia_id, aluno_id, valor, vencimento, status, data_pagamento) VALUES (%s,%s,%s,%s,%s,%s)",
                          (self.aid, aluno, valor, vencimento, status, vencimento if status == "pago" else None))
        self.conn.commit()

    def test_flag_desligada(self):
        self.flag("mensalidade_qr", False)
        self.assertEqual(self.api("GET", "/aluno/mensalidade")[2]["detail"], "mensalidade_desligada")

    def test_status_em_dia_em_breve_e_atrasada(self):
        self.cobranca(self.ana, date.today() + timedelta(days=20))
        c = self.api("GET", "/aluno/mensalidade")[2]
        self.assertEqual((c["estado"], c["liberado"], c["plano"], c["valor_em_aberto"], c["pagamento_online"]), ("em_dia", True, "Mensal", 99.9, False))
        self.conn.execute("DELETE FROM pagamentos"); self.cobranca(self.ana, date.today() - timedelta(days=3))
        c = self.api("GET", "/aluno/mensalidade")[2]
        self.assertEqual((c["estado"], c["liberado"], c["motivo"]), ("atrasada", False, "mensalidade_atrasada"))
        self.conn.execute("DELETE FROM pagamentos"); self.cobranca(self.ana, date.today() + timedelta(days=2))
        self.assertEqual(self.api("GET", "/aluno/mensalidade")[2]["estado"], "vence_em_breve")

    def test_sem_cobranca_nao_libera(self):
        c = self.api("GET", "/aluno/mensalidade")[2]
        self.assertEqual((c["estado"], c["liberado"], c["motivo"]), ("sem_cobranca", False, "sem_pagamento_em_aberto"))

    def test_qr_ciclo_completo_na_recepcao(self):
        self.cobranca(self.ana, date.today() + timedelta(days=10))
        qr = self.api("POST", "/aluno/mensalidade/qr")[2]
        self.assertTrue(qr["codigo"].startswith("fqm_"))
        s, _, c = self.api("POST", "/academia/acesso/qr", {"codigo": qr["codigo"]})
        self.assertEqual((s, c["nome"], c["liberado"]), (200, "Ana Souza Lima", True))

    def test_qr_de_aluno_atrasado_mostra_bloqueio(self):
        self.cobranca(self.ana, date.today() - timedelta(days=9))
        qr = self.api("POST", "/aluno/mensalidade/qr")[2]
        c = self.api("POST", "/academia/acesso/qr", {"codigo": qr["codigo"]})[2]
        self.assertEqual((c["liberado"], c["motivo"]), (False, "mensalidade_atrasada"))

    def test_qr_adulterado_expirado_ou_de_outra_academia(self):
        self.cobranca(self.ana, date.today() + timedelta(days=10))
        qr = self.api("POST", "/aluno/mensalidade/qr")[2]["codigo"]
        self.assertEqual(self.api("POST", "/academia/acesso/qr", {"codigo": qr[:-3] + "abc"})[2]["detail"], "qr_invalido")
        aluno_mensalidade.AGORA = lambda: HOJE + timedelta(seconds=121)
        self.assertEqual(self.api("POST", "/academia/acesso/qr", {"codigo": qr})[0], 400)
        aluno_mensalidade.AGORA = lambda: HOJE
        self.usuario = {"id": 2, "academia_id": self.outra, "papel": "recepcao", "nome": "R"}
        self.assertEqual(self.api("POST", "/academia/acesso/qr", {"codigo": qr})[0], 400)

    def test_tentativas_invalidas_esgotam_o_limite(self):
        codigos = [self.api("POST", "/academia/acesso/qr", {"codigo": "fqm_" + "a" * 20})[0] for _ in range(30)]
        self.assertIn(429, codigos)

    def test_pagamento_online_esta_desligado(self):
        s, _, c = self.api("POST", "/aluno/mensalidade/pagar")
        self.assertEqual((s, c["detail"]), (503, "pagamento_online_desligado"))
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM pagamentos").fetchone()["n"], 0)

    def test_qr_nao_guarda_nada_no_banco(self):
        self.api("POST", "/aluno/mensalidade/qr")
        tabelas = {r["table_name"] for r in self.conn.execute("SELECT table_name FROM information_schema.columns WHERE column_name ILIKE '%qr%' AND table_schema='public'").fetchall()}
        self.assertNotIn("pagamentos", tabelas)


class DesafiosTests(Base):
    def setUp(self):
        super().setUp()
        desafios.AGORA = lambda: datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)   # os desafios de teste começam em 1/10

    def novo(self, **kw):
        corpo = {"nome": "Outubro Forte", "metrica": "treinos", "inicio": "2026-10-01", "fim": "2026-10-31", **kw}
        s, _, c = self.api("POST", "/academia/desafios", corpo)
        self.assertEqual(s, 201, c)
        return c["id"]

    def series(self, aluno, dia, n=3, carga=50, reps=10):
        for i in range(n):
            self.conn.execute("INSERT INTO aluno_series_registradas (aluno_id, client_id, registrada_em, exercicio_ref, exercicio_nome, grupo, serie_numero, carga, reps, concluida) "
                              "VALUES (%s,%s,%s,'c:x','X','peito',%s,%s,%s,TRUE)", (aluno, f"cli-{aluno}-{dia}-{i}-teste", datetime(2026, 10, dia, 15, i, tzinfo=timezone.utc), i + 1, carga, reps))
        self.conn.commit()

    def test_criacao_valida_periodo_e_permissao(self):
        self.assertEqual(self.api("POST", "/academia/desafios", {"nome": "X1", "metrica": "treinos", "inicio": "2026-10-10", "fim": "2026-10-01"})[2]["detail"], "periodo_invalido")
        self.assertEqual(self.api("POST", "/academia/desafios", {"nome": "X1", "metrica": "pontos", "inicio": "2026-10-01", "fim": "2026-10-10"})[0], 422)
        self.usuario = {"id": 3, "academia_id": self.aid, "papel": "recepcao", "nome": "R"}
        self.assertEqual(self.api("POST", "/academia/desafios", {"nome": "X1", "metrica": "treinos", "inicio": "2026-10-01", "fim": "2026-10-10"})[0], 403)
        self.assertEqual(self.api("GET", "/academia/desafios")[0], 200)

    def test_limite_de_desafios_ativos(self):
        self.conn.execute("SELECT 1")
        for i in range(10):
            self.conn.execute("INSERT INTO desafios (academia_id, nome, metrica, inicio, fim) VALUES (%s,%s,'treinos',CURRENT_DATE,CURRENT_DATE + 5)", (self.aid, f"Desafio {i}"))
        self.conn.commit()
        self.assertEqual(self.api("POST", "/academia/desafios", {"nome": "Mais um", "metrica": "treinos", "inicio": "2026-10-01", "fim": "2026-10-10"})[2]["detail"], "limite_de_desafios")

    def test_participar_ranking_e_posicao_propria(self):
        did = self.novo()
        for q, n_dias in ((self.ana, 3), (self.bia, 2), (self.cai, 3)):
            self.aluno_atual = q
            self.assertEqual(self.api("POST", f"/aluno/desafios/{did}/participar")[0], 200)
            self.series(q, 5)
            for d in range(6, 6 + n_dias - 1):
                self.series(q, d)
        self.aluno_atual = self.bia
        r = self.api("GET", f"/aluno/desafios/{did}/ranking")[2]
        self.assertEqual([(p["nome"], p["posicao"], p["valor"]) for p in r["ranking"]], [("Ana L.", 1, 3.0), ("Caio", 1, 3.0), ("Bia S.", 3, 2.0)])
        self.assertEqual(r["eu"], {"posicao": 3, "valor": 2.0})
        lista = self.api("GET", "/aluno/desafios")[2]["desafios"][0]
        self.assertEqual((lista["participo"], lista["minha_posicao"], lista["situacao"]), (True, 3, "em_andamento"))

    def test_ranking_nunca_mostra_sobrenome_completo_nem_ids(self):
        did = self.novo()
        self.api("POST", f"/aluno/desafios/{did}/participar")
        self.series(self.ana, 5)
        txt = str(self.api("GET", f"/aluno/desafios/{did}/ranking")[2]["ranking"])
        self.assertNotIn("Souza", txt); self.assertNotIn("aluno_id", txt)

    def test_so_quem_participa_pontua_e_sair_remove(self):
        did = self.novo()
        self.series(self.bia, 5)
        self.api("POST", f"/aluno/desafios/{did}/participar")   # Ana
        self.series(self.ana, 5)
        nomes = [p["nome"] for p in self.api("GET", f"/aluno/desafios/{did}/ranking")[2]["ranking"]]
        self.assertEqual(nomes, ["Ana L."])
        self.assertEqual(self.api("DELETE", f"/aluno/desafios/{did}/participar")[0], 204)
        self.assertEqual(self.api("GET", f"/aluno/desafios/{did}/ranking")[2]["ranking"], [])

    def test_serie_anterior_a_entrada_nao_conta(self):
        did = self.novo()
        self.series(self.ana, 5)                                   # antes de entrar
        self.conn.execute("INSERT INTO desafios_participacao (desafio_id, aluno_id, entrou_em) VALUES (%s,%s,%s)", (did, self.ana, datetime(2026, 10, 8, tzinfo=timezone.utc)))
        self.conn.commit()
        self.assertEqual(self.api("GET", f"/aluno/desafios/{did}/ranking")[2]["ranking"], [])

    def test_volume_com_teto_por_serie(self):
        did = self.novo(metrica="volume")
        self.api("POST", f"/aluno/desafios/{did}/participar")
        self.series(self.ana, 5, n=3, carga=1000, reps=500)
        self.assertEqual(self.api("GET", f"/aluno/desafios/{did}/ranking")[2]["ranking"][0]["valor"], 30000.0)

    def test_isolamento_entre_academias(self):
        did = self.novo()
        self.aluno_atual = self.de_fora
        self.assertEqual(self.api("POST", f"/aluno/desafios/{did}/participar")[0], 404)
        self.assertEqual(self.api("GET", f"/aluno/desafios/{did}/ranking")[0], 404)
        self.assertEqual(self.api("GET", "/aluno/desafios")[2]["desafios"], [])
        self.usuario = {"id": 9, "academia_id": self.outra, "papel": "dono", "nome": "Outro"}
        self.assertEqual(self.api("GET", f"/academia/desafios/{did}/ranking")[0], 404)
        self.assertEqual(self.api("POST", f"/academia/desafios/{did}/tv")[0], 404)

    def test_encerrado_nao_aceita_participacao(self):
        did = self.novo(inicio="2026-09-01", fim="2026-09-30")
        self.assertEqual(self.api("POST", f"/aluno/desafios/{did}/participar")[2]["detail"], "desafio_encerrado")

    def test_flag_desligada(self):
        self.flag("desafios", False)
        self.assertEqual(self.api("GET", "/aluno/desafios")[2]["detail"], "desafios_desligado")
        self.assertEqual(self.api("GET", "/academia/desafios")[2]["detail"], "desafios_desligado")

    # ----- TV
    def test_tv_token_ciclo_rotacao_e_revogacao(self):
        did = self.novo()
        self.api("POST", f"/aluno/desafios/{did}/participar"); self.series(self.ana, 5)
        t1 = self.api("POST", f"/academia/desafios/{did}/tv")[2]["token"]
        self.assertTrue(t1.startswith("frk_"))
        self.assertNotIn(t1, str(self.conn.execute("SELECT * FROM desafios").fetchall()))      # só o hash fica
        s, h, c = self.api("GET", f"/painel/ranking/{t1}/dados")
        self.assertEqual((s, c["academia"], c["ranking"][0]["nome"]), (200, "Academia Teste", "Ana L."))
        self.assertEqual(h["cache-control"], "no-store")
        t2 = self.api("POST", f"/academia/desafios/{did}/tv")[2]["token"]
        self.assertEqual(self.api("GET", f"/painel/ranking/{t1}/dados")[0], 404)
        self.assertEqual(self.api("GET", f"/painel/ranking/{t2}/dados")[0], 200)
        self.assertEqual(self.api("DELETE", f"/academia/desafios/{did}/tv")[0], 204)
        self.assertEqual(self.api("GET", f"/painel/ranking/{t2}/dados")[0], 404)

    def test_tv_nao_expoe_dados_sensiveis_e_exige_token_certo(self):
        did = self.novo()
        self.api("POST", f"/aluno/desafios/{did}/participar"); self.series(self.ana, 5)
        t = self.api("POST", f"/academia/desafios/{did}/tv")[2]["token"]
        txt = str(self.api("GET", f"/painel/ranking/{t}/dados")[2])
        for proibido in ("ana@gmail", "Souza", "documento", "aluno_id", "token", "email"):
            self.assertNotIn(proibido, txt)
        for ruim in ("frk_", "frk_abc", "qualquer", "x" * 90):
            self.assertEqual(self.api("GET", f"/painel/ranking/{ruim}/dados")[0], 404)

    def test_tv_para_de_funcionar_quando_encerra_ou_flag_desliga(self):
        did = self.novo()
        t = self.api("POST", f"/academia/desafios/{did}/tv")[2]["token"]
        self.flag("desafios", False)
        self.assertEqual(self.api("GET", f"/painel/ranking/{t}/dados")[0], 404)
        self.flag("desafios", True)
        self.assertEqual(self.api("PATCH", f"/academia/desafios/{did}", {"ativo": False})[0], 200)
        self.assertEqual(self.api("GET", f"/painel/ranking/{t}/dados")[0], 404)
        self.assertEqual(self.api("POST", f"/academia/desafios/{did}/tv")[2]["detail"], "desafio_encerrado")

    def test_tv_tentativas_erradas_viram_429(self):
        codigos = [self.api("GET", f"/painel/ranking/frk_{i:040d}/dados")[0] for i in range(40)]
        self.assertIn(429, codigos)

    def test_pagina_da_tv_e_estatica_com_csp_restrita(self):
        s, h, corpo = self.api("GET", "/painel/ranking/frk_qualquer")
        self.assertEqual(s, 200)
        self.assertIn("text/html", h["content-type"])
        self.assertIn("script-src 'self'", h["content-security-policy"])
        self.assertIn("default-src 'none'", h["content-security-policy"])
        self.assertEqual(h["referrer-policy"], "no-referrer")
        self.assertNotIn("frk_qualquer", corpo if isinstance(corpo, str) else corpo.decode())


class GeradorTests(Base):
    BODY = {"objetivo": "hipertrofia", "nivel": "Intermediário", "dias": 3}

    def test_proposta_nao_grava(self):
        s, _, c = self.api("POST", "/aluno/treinos/gerar", self.BODY)
        self.assertEqual((s, len(c["treinos"])), (200, 3))
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM treinos").fetchone()["n"], 0)

    def test_salvar_cria_treinos_editaveis(self):
        c = self.api("POST", "/aluno/treinos/gerar", {**self.BODY, "salvar": True})[2]
        self.assertEqual(len(c["criados"]), 3)
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM treinos WHERE aluno_id = %s", (self.ana,)).fetchone()["n"], 3)
        self.assertGreater(self.conn.execute("SELECT count(*) AS n FROM treino_itens").fetchone()["n"], 10)

    def test_respeita_limite_de_treinos(self):
        for i in range(28):
            self.conn.execute("INSERT INTO treinos (aluno_id, nome) VALUES (%s,%s)", (self.ana, f"T{i}"))
        self.conn.commit()
        self.assertEqual(self.api("POST", "/aluno/treinos/gerar", {**self.BODY, "salvar": True})[2]["detail"], "limite_de_treinos")
        self.assertEqual(self.api("POST", "/aluno/treinos/gerar", self.BODY)[0], 200)   # só ver continua valendo

    def test_aparelhos_marcados_como_indisponiveis_somem_da_proposta(self):
        eq = {e["equipamento"] for e in self.api("GET", "/academia/equipamentos")[2]["equipamentos"]}
        self.assertIn("Barra", eq)
        self.assertEqual(self.api("PUT", "/academia/equipamentos", {"indisponiveis": ["Barra", "Polia"]})[0], 200)
        c = self.api("POST", "/aluno/treinos/gerar", {"objetivo": "forca", "nivel": "Avançado", "dias": 4})[2]
        refs = [i["ref"][2:] for t in c["treinos"] for b in t["blocos"] for i in b["itens"] if "ref" in i]
        eqs = {r["equipamento"] for r in self.conn.execute("SELECT equipamento FROM exercicios_catalogo WHERE id = ANY(%s)", (refs,)).fetchall()}
        self.assertTrue(eqs)
        self.assertFalse(eqs & {"Barra", "Polia"})

    def test_equipamentos_so_do_dono_e_validados(self):
        self.assertEqual(self.api("PUT", "/academia/equipamentos", {"indisponiveis": ["Foguete"]})[2]["detail"], "equipamento_invalido")
        todos = [e["equipamento"] for e in self.api("GET", "/academia/equipamentos")[2]["equipamentos"]]
        self.assertEqual(self.api("PUT", "/academia/equipamentos", {"indisponiveis": todos})[2]["detail"], "pelo_menos_um_equipamento")
        self.usuario = {"id": 3, "academia_id": self.aid, "papel": "recepcao", "nome": "R"}
        self.assertEqual(self.api("PUT", "/academia/equipamentos", {"indisponiveis": ["Barra"]})[0], 403)

    def test_equipamentos_de_uma_academia_nao_afetam_outra(self):
        self.api("PUT", "/academia/equipamentos", {"indisponiveis": ["Barra"]})
        self.aluno_atual = self.de_fora
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM academia_equipamentos WHERE academia_id = %s", (self.outra,)).fetchone()["n"], 0)
        c = self.api("POST", "/aluno/treinos/gerar", {"objetivo": "hipertrofia", "nivel": "Avançado", "dias": 3})[2]
        self.assertTrue(any("Barra" == r["equipamento"] for r in self.conn.execute(
            "SELECT equipamento FROM exercicios_catalogo WHERE id = ANY(%s)", ([i["ref"][2:] for t in c["treinos"] for b in t["blocos"] for i in b["itens"] if "ref" in i],)).fetchall()))

    def test_entradas_invalidas_e_flag(self):
        self.assertEqual(self.api("POST", "/aluno/treinos/gerar", {**self.BODY, "objetivo": "x"})[2]["detail"], "objetivo_invalido")
        self.assertEqual(self.api("POST", "/aluno/treinos/gerar", {**self.BODY, "nivel": "Deus"})[2]["detail"], "nivel_invalido")
        self.assertEqual(self.api("POST", "/aluno/treinos/gerar", {**self.BODY, "dias": 9})[0], 422)
        self.flag("gerador_treino", False)
        self.assertEqual(self.api("POST", "/aluno/treinos/gerar", self.BODY)[2]["detail"], "gerador_desligado")

    def test_exercicio_proprio_do_aluno_entra_no_catalogo_mas_nao_de_outro(self):
        self.conn.execute("INSERT INTO exercicios_custom (escopo, academia_id, aluno_id, nome, grupo, equipamento) VALUES ('aluno',%s,%s,'Meu supino','peito','Barra')", (self.aid, self.bia))
        self.conn.commit()
        c = self.api("POST", "/aluno/treinos/gerar", {"objetivo": "hipertrofia", "nivel": "Avançado", "dias": 3})[2]
        self.assertFalse([i for t in c["treinos"] for b in t["blocos"] for i in b["itens"] if i.get("ref", "").startswith("x:")])


if __name__ == "__main__":
    unittest.main()
