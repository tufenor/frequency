import unittest
from datetime import datetime, timezone

from backend.tests import _path  # noqa: F401
from backend.tests.pg_temp import TempPostgres
from backend.tests import _aluno_fixtures as fx
from backend.tests._asgi import chamar
import aluno_auth
import lutas
import seguranca

_pg = None
SEG_22UTC = datetime(2026, 10, 12, 22, 0, tzinfo=timezone.utc)   # segunda 19:00 em São Paulo


def setUpModule():
    global _pg
    _pg = TempPostgres().start()


def tearDownModule():
    _pg.stop()


def _ok(conn, academia_id):
    return True


class LutasTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        self.conn = fx.conectar(_pg.dsn)
        self.conn.execute("TRUNCATE presencas_aula, aulas_realizadas, reservas_turma, aluno_graduacoes, faixas, atestados_aluno, turma_horarios, turmas, "
                          "professores, plano_modalidades, modalidades, academia_local, aluno_sessoes, aluno_credenciais, alunos, planos, usuarios, "
                          "academia_recursos, academias RESTART IDENTITY CASCADE")
        self.conn.commit()
        self.aid = fx.criar_academia(self.conn)
        self.outra = fx.criar_academia(self.conn, nome="Outra")
        for a in (self.aid, self.outra):
            self.conn.execute("INSERT INTO academia_recursos (academia_id, recurso, ligado) VALUES (%s,'lutas',TRUE)", (a,))
        self.plano_luta = self.conn.execute("INSERT INTO planos (academia_id, nome, valor, duracao_dias) VALUES (%s,'Combo',100,30) RETURNING id", (self.aid,)).fetchone()["id"]
        self.plano_so_musc = self.conn.execute("INSERT INTO planos (academia_id, nome, valor, duracao_dias) VALUES (%s,'Musculação',80,30) RETURNING id", (self.aid,)).fetchone()["id"]
        self.jiu = self.conn.execute("INSERT INTO modalidades (academia_id, nome) VALUES (%s,'Jiu-jitsu') RETURNING id", (self.aid,)).fetchone()["id"]
        self.muay = self.conn.execute("INSERT INTO modalidades (academia_id, nome) VALUES (%s,'Muay thai') RETURNING id", (self.aid,)).fetchone()["id"]
        self.conn.execute("INSERT INTO plano_modalidades (plano_id, modalidade_id) VALUES (%s,%s)", (self.plano_luta, self.jiu))
        self.u_dono = {"id": 1, "academia_id": self.aid, "papel": "dono", "nome": "D"}
        self.conn.execute("INSERT INTO usuarios (id, academia_id, nome, email, senha_hash, papel) VALUES (1,%s,'D','dono@x.com','x','dono'),"
                          "(2,%s,'Prof A','a@x.com','x','professor'),(3,%s,'Prof B','b@x.com','x','professor')", (self.aid, self.aid, self.aid))
        self.conn.execute("SELECT setval(pg_get_serial_sequence('usuarios','id'), 50)")
        self.prof_a = self.conn.execute("INSERT INTO professores (academia_id, nome, usuario_id) VALUES (%s,'Prof A',2) RETURNING id", (self.aid,)).fetchone()["id"]
        self.prof_b = self.conn.execute("INSERT INTO professores (academia_id, nome, usuario_id) VALUES (%s,'Prof B',3) RETURNING id", (self.aid,)).fetchone()["id"]
        self.turma = self.conn.execute("INSERT INTO turmas (academia_id, modalidade_id, professor_id, nome, capacidade) VALUES (%s,%s,%s,'Jiu iniciante',2) RETURNING id",
                                       (self.aid, self.jiu, self.prof_a)).fetchone()["id"]
        self.turma_b = self.conn.execute("INSERT INTO turmas (academia_id, modalidade_id, professor_id, nome, capacidade) VALUES (%s,%s,%s,'Jiu avançado',10) RETURNING id",
                                         (self.aid, self.jiu, self.prof_b)).fetchone()["id"]
        for t in (self.turma, self.turma_b):
            self.conn.execute("INSERT INTO turma_horarios (turma_id, dia_semana, inicio, fim) VALUES (%s,1,'19:00','20:00')", (t,))
        self.conn.execute("INSERT INTO academia_local (academia_id, latitude, longitude, raio_m) VALUES (%s,-23.5505,-46.6333,150)", (self.aid,))
        self.ana = self._aluno("ana@gmail.com", "Ana", "d1", self.plano_luta)
        self.bia = self._aluno("bia@gmail.com", "Bia", "d2", self.plano_luta)
        self.cai = self._aluno("cai@gmail.com", "Caio", "d3", self.plano_luta)
        self.sem = self._aluno("sem@gmail.com", "Sem Luta", "d4", self.plano_so_musc)
        self.conn.commit()
        self.usuario = self.u_dono
        self.app = FastAPI()
        self.app.include_router(lutas.router)
        o = self.app.dependency_overrides
        o[aluno_auth.conexao] = lambda: self.conn
        o[seguranca.somente_dono] = lambda: self._so_dono()
        o[lutas.gestao_ou_professor] = lambda: self.usuario
        o[lutas.gestao] = lambda: self._gestao()
        self.aluno_atual = None
        o[aluno_auth.aluno_atual] = lambda: self._aluno_sessao()
        aluno_auth.ASSINATURA_OK = _ok
        aluno_auth._limitador = None
        self._agora = lutas.AGORA
        lutas.AGORA = lambda: SEG_22UTC.replace(minute=0) - __import__("datetime").timedelta(minutes=15)

    def tearDown(self):
        lutas.AGORA = self._agora
        aluno_auth.ASSINATURA_OK = aluno_auth._assinatura_em_dia
        aluno_auth._limitador = None
        self.conn.close()

    def _aluno(self, email, nome, doc, plano):
        return self.conn.execute("INSERT INTO alunos (academia_id, nome, documento, email, plano_id) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                                 (self.aid, nome, doc, email, plano)).fetchone()["id"]

    def _so_dono(self):
        if self.usuario["papel"] != "dono":
            raise lutas._erro(403, "sem_permissao")
        return self.usuario

    def _gestao(self):
        if self.usuario["papel"] not in ("dono", "recepcao"):
            raise lutas._erro(403, "sem_permissao")
        return self.usuario

    def _aluno_sessao(self):
        a = self.conn.execute("SELECT id, nome, email, academia_id, plano_id, status FROM alunos WHERE id = %s", (self.aluno_atual,)).fetchone()
        return a

    def como_prof(self, uid):
        self.usuario = {"id": uid, "academia_id": self.aid, "papel": "professor", "nome": "P"}

    def aluno(self, aid):
        self.aluno_atual = aid

    def agora(self, minutos_apos_inicio):
        import datetime as d
        lutas.AGORA = lambda: SEG_22UTC + d.timedelta(minutes=minutos_apos_inicio)

    def api(self, metodo, caminho, corpo=None):
        return chamar(self.app, metodo, caminho, corpo, {})

    # ----- painel: estrutura
    def test_modalidade_e_plano_do_painel(self):
        s, _, c = self.api("POST", "/lutas/modalidades", {"nome": "Boxe"})
        self.assertEqual(s, 201)
        self.assertEqual(self.api("POST", "/lutas/modalidades", {"nome": "boxe"})[0], 409)
        s, _, c = self.api("PUT", f"/lutas/planos/{self.plano_so_musc}/modalidades", {"modalidade_ids": [self.jiu]})
        self.assertEqual((s, c["modalidade_ids"]), (200, [self.jiu]))
        self.assertEqual(self.api("PUT", f"/lutas/planos/{self.plano_so_musc}/modalidades", {"modalidade_ids": [9999]})[0], 422)

    def test_modalidade_de_outra_academia_nao_entra_no_plano(self):
        m = self.conn.execute("INSERT INTO modalidades (academia_id, nome) VALUES (%s,'Alheia') RETURNING id", (self.outra,)).fetchone()["id"]
        self.conn.commit()
        self.assertEqual(self.api("PUT", f"/lutas/planos/{self.plano_luta}/modalidades", {"modalidade_ids": [m]})[0], 422)

    def test_so_dono_configura_e_flag_desligada_bloqueia(self):
        self.usuario = {"id": 9, "academia_id": self.aid, "papel": "recepcao", "nome": "R"}
        self.assertEqual(self.api("POST", "/lutas/modalidades", {"nome": "Boxe"})[0], 403)
        self.usuario = self.u_dono
        self.conn.execute("UPDATE academia_recursos SET ligado = FALSE WHERE recurso = 'lutas'")
        self.conn.commit()
        self.assertEqual(self.api("GET", "/lutas/turmas")[2]["detail"], "lutas_desligado")

    def test_cria_professor_com_login_e_turma(self):
        s, _, c = self.api("POST", "/lutas/professores", {"nome": "Novo Prof", "email": "NOVO@x.com", "senha": "senhaforte123"})
        self.assertEqual((s, c["tem_login"]), (201, True))
        papel = self.conn.execute("SELECT papel, senha_hash FROM usuarios WHERE email = 'novo@x.com'").fetchone()
        self.assertEqual(papel["papel"], "professor")
        self.assertNotIn("senhaforte123", papel["senha_hash"])
        self.assertEqual(self.api("POST", "/lutas/professores", {"nome": "Dup", "email": "novo@x.com", "senha": "senhaforte123"})[0], 409)
        self.assertEqual(self.api("POST", "/lutas/professores", {"nome": "Sem senha", "email": "a@b.com"})[0], 422)
        s, _, t = self.api("POST", "/lutas/turmas", {"modalidade_id": self.jiu, "professor_id": c["id"], "nome": "Noite", "capacidade": 5})
        self.assertEqual(s, 201)
        s, _, h = self.api("POST", f"/lutas/turmas/{t['id']}/horarios", {"dia_semana": 3, "inicio": "18:00", "fim": "19:00"})
        self.assertEqual(s, 201)
        self.assertEqual(self.api("POST", f"/lutas/turmas/{t['id']}/horarios", {"dia_semana": 3, "inicio": "19:00", "fim": "18:00"})[0], 422)
        self.assertEqual(self.api("POST", f"/lutas/turmas/{t['id']}/horarios", {"dia_semana": 3, "inicio": "18:00", "fim": "19:30"})[0], 409)

    def test_turma_com_professor_de_outra_academia_e_rejeitada(self):
        p = self.conn.execute("INSERT INTO professores (academia_id, nome) VALUES (%s,'Alheio') RETURNING id", (self.outra,)).fetchone()["id"]
        self.conn.commit()
        self.assertEqual(self.api("POST", "/lutas/turmas", {"modalidade_id": self.jiu, "professor_id": p, "nome": "X"})[0], 422)

    # ----- professor só vê as suas turmas
    def test_professor_so_ve_as_proprias_turmas(self):
        self.como_prof(2)
        nomes = [t["nome"] for t in self.api("GET", "/lutas/turmas")[2]["turmas"]]
        self.assertEqual(nomes, ["Jiu iniciante"])
        self.assertEqual(self.api("GET", f"/lutas/turmas/{self.turma_b}/alunos")[0], 404)
        self.assertEqual(self.api("GET", f"/lutas/chamada?turma_id={self.turma_b}&data=2026-10-12")[0], 404)
        self.assertEqual(self.api("GET", "/lutas/relatorios/frequencia?turma_id=%d&de=2026-10-01&ate=2026-10-31" % self.turma_b)[0], 404)
        self.assertEqual([t["nome"] for t in self.api("GET", "/lutas/relatorios/ocupacao")[2]["turmas"]], ["Jiu iniciante"])

    # ----- aluno: grade e reserva
    def test_aluno_sem_modalidade_no_plano_nao_ve_nada(self):
        self.aluno(self.sem)
        self.assertEqual(self.api("GET", "/aluno/lutas")[2], {"disponivel": False})
        self.assertEqual(self.api("POST", f"/aluno/lutas/turmas/{self.turma}/reservar")[2]["detail"], "plano_sem_modalidade")

    def test_grade_mostra_turmas_e_vagas(self):
        self.aluno(self.ana)
        c = self.api("GET", "/aluno/lutas")[2]
        self.assertTrue(c["disponivel"])
        self.assertEqual(sorted(t["nome"] for t in c["grade"]), ["Jiu avançado", "Jiu iniciante"])
        self.assertEqual([t["vagas"] for t in c["grade"] if t["nome"] == "Jiu iniciante"], [2])

    def test_reserva_lotacao_e_fila_de_espera_com_promocao(self):
        for q in (self.ana, self.bia):
            self.aluno(q)
            self.assertEqual(self.api("POST", f"/aluno/lutas/turmas/{self.turma}/reservar")[2]["estado"], "ativa")
        self.aluno(self.cai)
        self.assertEqual(self.api("POST", f"/aluno/lutas/turmas/{self.turma}/reservar")[2]["detail"], "turma_cheia")
        self.assertEqual(self.api("POST", f"/aluno/lutas/turmas/{self.turma}/reservar", {"entrar_na_espera": True})[2]["estado"], "espera")
        self.aluno(self.ana)
        self.assertEqual(self.api("DELETE", f"/aluno/lutas/turmas/{self.turma}/reservar")[0], 204)
        est = self.conn.execute("SELECT estado FROM reservas_turma WHERE aluno_id = %s", (self.cai,)).fetchone()["estado"]
        self.assertEqual(est, "ativa")

    def test_reserva_repetida_e_idempotente(self):
        self.aluno(self.ana)
        self.api("POST", f"/aluno/lutas/turmas/{self.turma}/reservar")
        self.assertTrue(self.api("POST", f"/aluno/lutas/turmas/{self.turma}/reservar")[2]["ja_reservada"])
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM reservas_turma").fetchone()["n"], 1)

    def test_turma_de_outra_academia_e_404(self):
        mo = self.conn.execute("INSERT INTO modalidades (academia_id, nome) VALUES (%s,'Zz') RETURNING id", (self.outra,)).fetchone()["id"]
        to = self.conn.execute("INSERT INTO turmas (academia_id, modalidade_id, nome) VALUES (%s,%s,'Alheia') RETURNING id", (self.outra, mo)).fetchone()["id"]
        self.conn.commit()
        self.aluno(self.ana)
        self.assertEqual(self.api("POST", f"/aluno/lutas/turmas/{to}/reservar")[0], 404)
        self.assertEqual(self.api("POST", "/aluno/lutas/presenca", {"turma_id": to})[0], 404)

    # ----- presença: abuso
    def test_presenca_dentro_da_janela_dentro_do_raio(self):
        self.aluno(self.ana)
        self.agora(-30)
        s, _, c = self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma, "latitude": -23.5505, "longitude": -46.6333})
        self.assertEqual((s, c["estado"], c["dentro_do_raio"], c["ja_confirmada"]), (200, "confirmada", True, False))

    def test_fora_da_janela_antes_e_depois(self):
        self.aluno(self.ana)
        for minutos in (-31, 16):
            self.agora(minutos)
            s, _, c = self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma})
            self.assertEqual((s, c["detail"]), (422, "fora_da_janela"), minutos)
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM presencas_aula").fetchone()["n"], 0)

    def test_dia_errado_nao_confirma(self):
        import datetime as d
        self.aluno(self.ana)
        lutas.AGORA = lambda: SEG_22UTC + d.timedelta(days=1)
        self.assertEqual(self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma})[0], 422)

    def test_fora_do_raio_fica_marcado_e_nao_conta(self):
        self.aluno(self.ana)
        self.agora(0)
        c = self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma, "latitude": -23.6, "longitude": -46.7})[2]
        self.assertEqual((c["estado"], c["dentro_do_raio"]), ("confirmada", False))
        r = self.conn.execute("SELECT dentro_do_raio, estado FROM presencas_aula").fetchone()
        self.assertEqual((r["dentro_do_raio"], r["estado"]), (False, "confirmada"))

    def test_coordenada_nunca_e_gravada(self):
        self.aluno(self.ana)
        self.agora(0)
        self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma, "latitude": -23.5505, "longitude": -46.6333})
        cols = [r["column_name"] for r in self.conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'presencas_aula'").fetchall()]
        self.assertFalse({"latitude", "longitude", "lat", "lon"} & set(cols))

    def test_coordenada_invalida_e_rejeitada(self):
        self.aluno(self.ana)
        self.agora(0)
        self.assertEqual(self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma, "latitude": 95, "longitude": 0})[0], 422)

    def test_dupla_confirmacao_nao_duplica(self):
        self.aluno(self.ana)
        self.agora(0)
        self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma})
        c = self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma})[2]
        self.assertTrue(c["ja_confirmada"])
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM presencas_aula").fetchone()["n"], 1)

    def test_plano_sem_modalidade_nao_confirma(self):
        self.aluno(self.sem)
        self.agora(0)
        self.assertEqual(self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma})[2]["detail"], "plano_sem_modalidade")

    def test_turma_que_exige_reserva(self):
        self.conn.execute("UPDATE turmas SET exige_reserva = TRUE WHERE id = %s", (self.turma,))
        self.conn.commit()
        self.aluno(self.ana)
        self.agora(0)
        self.assertEqual(self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma})[2]["detail"], "sem_reserva")
        self.api("POST", f"/aluno/lutas/turmas/{self.turma}/reservar")
        self.assertEqual(self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma})[0], 200)

    def test_qr_exige_codigo_correto(self):
        self.aluno(self.ana)
        self.agora(0)
        self.assertEqual(self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma, "metodo": "qr", "codigo": "fa_errado"})[2]["detail"], "codigo_invalido")
        self.assertEqual(self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma, "metodo": "qr"})[0], 422)
        self.como_prof(2)
        codigo = self.api("GET", f"/lutas/chamada?turma_id={self.turma}&data=2026-10-12")[2]["codigo_qr"]
        # o código de uma turma não vale para outra
        self.aluno(self.ana)
        self.assertEqual(self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma_b, "metodo": "qr", "codigo": codigo})[2]["detail"], "codigo_invalido")
        self.assertEqual(self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma, "metodo": "qr", "codigo": codigo})[0], 200)

    def test_limite_de_tentativas_429(self):
        self.aluno(self.ana)
        self.agora(-120)
        codigos = [self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma})[0] for _ in range(60)]
        self.assertIn(429, codigos)

    # ----- chamada
    def _confirmar(self, quem):
        self.aluno(quem)
        self.agora(0)
        self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma})

    def test_professor_valida_ausenta_e_so_validada_conta(self):
        self._confirmar(self.ana)
        self._confirmar(self.bia)
        self.como_prof(2)
        ch = self.api("GET", f"/lutas/chamada?turma_id={self.turma}&data=2026-10-12")[2]
        self.assertEqual(sorted(a["nome"] for a in ch["alunos"]), ["Ana", "Bia"])
        aula = ch["aula_id"]
        self.assertEqual(self.api("PUT", f"/lutas/chamada/{aula}/alunos/{self.ana}", {"acao": "validar"})[2]["estado"], "validada")
        self.api("PUT", f"/lutas/chamada/{aula}/alunos/{self.bia}", {"acao": "ausentar"})
        rel = self.api("GET", f"/lutas/relatorios/frequencia?turma_id={self.turma}&de=2026-10-01&ate=2026-10-31")[2]
        por = {a["nome"]: (a["validadas"], a["ausencias"], a["pendentes"]) for a in rel["alunos"]}
        self.assertEqual(por, {"Ana": (1, 0, 0), "Bia": (0, 1, 0)})
        self.assertEqual(rel["aulas_no_periodo"], 1)

    def test_aluno_validado_nao_volta_a_confirmada_ao_reconfirmar(self):
        self._confirmar(self.ana)
        self.como_prof(2)
        aula = self.api("GET", f"/lutas/chamada?turma_id={self.turma}&data=2026-10-12")[2]["aula_id"]
        self.api("PUT", f"/lutas/chamada/{aula}/alunos/{self.ana}", {"acao": "validar"})
        self.aluno(self.ana)
        c = self.api("POST", "/aluno/lutas/presenca", {"turma_id": self.turma})[2]
        self.assertEqual((c["estado"], c["ja_confirmada"]), ("validada", True))

    def test_professor_nao_marca_aula_de_outro_professor(self):
        self._confirmar(self.ana)
        self.como_prof(2)
        aula = self.api("GET", f"/lutas/chamada?turma_id={self.turma}&data=2026-10-12")[2]["aula_id"]
        self.como_prof(3)
        self.assertEqual(self.api("PUT", f"/lutas/chamada/{aula}/alunos/{self.ana}", {"acao": "validar"})[0], 404)

    def test_ajuste_retroativo_ate_24h(self):
        import datetime as d
        self._confirmar(self.ana)
        self.como_prof(2)
        aula = self.api("GET", f"/lutas/chamada?turma_id={self.turma}&data=2026-10-12")[2]["aula_id"]
        fim = SEG_22UTC + d.timedelta(hours=1)
        lutas.AGORA = lambda: fim + d.timedelta(hours=24)
        self.assertEqual(self.api("PUT", f"/lutas/chamada/{aula}/alunos/{self.ana}", {"acao": "validar"})[0], 200)
        lutas.AGORA = lambda: fim + d.timedelta(hours=24, seconds=1)
        self.assertEqual(self.api("PUT", f"/lutas/chamada/{aula}/alunos/{self.ana}", {"acao": "ausentar"})[2]["detail"], "fora_do_prazo_de_ajuste")

    def test_validar_aluno_sem_modalidade_no_plano_e_rejeitado(self):
        self.agora(0)
        self.como_prof(2)
        aula = self.api("GET", f"/lutas/chamada?turma_id={self.turma}&data=2026-10-12")[2]["aula_id"]
        self.assertEqual(self.api("PUT", f"/lutas/chamada/{aula}/alunos/{self.sem}", {"acao": "validar"})[2]["detail"], "plano_sem_modalidade")

    def test_chamada_de_dia_sem_aula_e_aula_no_futuro(self):
        self.como_prof(2)
        self.assertEqual(self.api("GET", f"/lutas/chamada?turma_id={self.turma}&data=2026-10-13")[2]["detail"], "sem_aula_neste_dia")
        self.assertEqual(self.api("GET", f"/lutas/chamada?turma_id={self.turma}&data=2026-10-19")[2]["detail"], "aula_no_futuro")

    def test_gestao_valida_aluno_de_outra_academia_e_404(self):
        outro = self.conn.execute("INSERT INTO alunos (academia_id, nome, documento, email) VALUES (%s,'Z','dz','z@gmail.com') RETURNING id", (self.outra,)).fetchone()["id"]
        self.conn.commit()
        self.agora(0)
        aula = self.api("GET", f"/lutas/chamada?turma_id={self.turma}&data=2026-10-12")[2]["aula_id"]
        self.assertEqual(self.api("PUT", f"/lutas/chamada/{aula}/alunos/{outro}", {"acao": "validar"})[0], 404)

    # ----- faixas, graduação, atestado
    def test_faixa_graduacao_e_progresso(self):
        self.api("POST", "/lutas/faixas", {"modalidade_id": self.jiu, "nome": "Branca", "ordem": 0})
        s, _, azul = self.api("POST", "/lutas/faixas", {"modalidade_id": self.jiu, "nome": "Azul", "ordem": 1, "aulas_minimas": 2})
        self.assertEqual(s, 201)
        self.assertEqual(self.api("POST", "/lutas/faixas", {"modalidade_id": self.jiu, "nome": "Dup", "ordem": 1})[0], 409)
        self._confirmar(self.ana)
        self.usuario = self.u_dono
        aula = self.api("GET", f"/lutas/chamada?turma_id={self.turma}&data=2026-10-12")[2]["aula_id"]
        self.api("PUT", f"/lutas/chamada/{aula}/alunos/{self.ana}", {"acao": "validar"})
        self.assertEqual(self.api("POST", f"/lutas/alunos/{self.ana}/graduacao", {"faixa_id": azul["id"]})[0], 201)
        self.aluno(self.ana)
        f = self.api("GET", "/aluno/lutas")[2]["faixas"][0]
        self.assertEqual((f["modalidade"], f["aulas_validadas"], f["atual"]), ("Jiu-jitsu", 1, "Azul"))

    def test_graduacao_exige_plano_com_a_modalidade(self):
        s, _, f = self.api("POST", "/lutas/faixas", {"modalidade_id": self.muay, "nome": "Khan 1", "ordem": 0})
        self.assertEqual(self.api("POST", f"/lutas/alunos/{self.ana}/graduacao", {"faixa_id": f["id"]})[2]["detail"], "plano_sem_modalidade")

    def test_professor_so_gradua_aluno_das_suas_turmas(self):
        s, _, f = self.api("POST", "/lutas/faixas", {"modalidade_id": self.jiu, "nome": "Branca", "ordem": 0})
        self.aluno(self.ana)
        self.api("POST", f"/aluno/lutas/turmas/{self.turma_b}/reservar")   # Ana é da turma do Prof B
        self.como_prof(2)
        self.assertEqual(self.api("POST", f"/lutas/alunos/{self.ana}/graduacao", {"faixa_id": f["id"]})[0], 404)
        self.como_prof(3)
        self.assertEqual(self.api("POST", f"/lutas/alunos/{self.ana}/graduacao", {"faixa_id": f["id"]})[0], 201)

    def test_atestado_so_gestao_e_aparece_no_app(self):
        self.como_prof(2)
        self.assertEqual(self.api("POST", f"/lutas/alunos/{self.ana}/atestado", {"valido_ate": "2027-01-01"})[0], 403)
        self.usuario = self.u_dono
        self.assertEqual(self.api("POST", f"/lutas/alunos/{self.ana}/atestado", {"valido_ate": "2027-01-01", "observacao": "ok"})[0], 201)
        self.aluno(self.ana)
        self.assertEqual(self.api("GET", "/aluno/lutas")[2]["atestado"], {"valido_ate": "2027-01-01", "em_dia": True})

    def test_local_da_academia(self):
        self.assertEqual(self.api("PUT", "/lutas/local", {"latitude": 0, "longitude": 0})[0], 422)
        self.assertEqual(self.api("PUT", "/lutas/local", {"latitude": -23.5, "longitude": -46.6, "fuso": "Marte/Base"})[0], 422)
        self.assertEqual(self.api("PUT", "/lutas/local", {"latitude": -23.5, "longitude": -46.6, "raio_m": 200})[0], 200)
        self.assertEqual(self.api("GET", "/lutas/local")[2]["raio_m"], 200)

    def test_ocupacao(self):
        self.aluno(self.ana)
        self.api("POST", f"/aluno/lutas/turmas/{self.turma}/reservar")
        t = [x for x in self.api("GET", "/lutas/relatorios/ocupacao")[2]["turmas"] if x["id"] == self.turma][0]
        self.assertEqual((t["reservas"], t["capacidade"], t["ocupacao_pct"]), (1, 2, 50))

    def test_aulas_coletivas_usam_a_flag_agenda_aulas(self):
        self.conn.execute("INSERT INTO academia_recursos (academia_id, recurso, ligado) VALUES (%s,'agenda_aulas',TRUE)", (self.aid,))
        self.conn.execute("UPDATE academia_recursos SET ligado = FALSE WHERE recurso = 'lutas'")
        self.conn.commit()
        s, _, c = self.api("POST", "/lutas/modalidades", {"nome": "Yoga", "categoria": "aula"})
        self.assertEqual(s, 201)
        self.assertEqual(self.api("POST", "/lutas/modalidades", {"nome": "Boxe", "categoria": "luta"})[0], 403)
        nomes = [m["nome"] for m in self.api("GET", "/lutas/modalidades")[2]["modalidades"]]
        self.assertEqual(nomes, ["Yoga"])


if __name__ == "__main__":
    unittest.main()
