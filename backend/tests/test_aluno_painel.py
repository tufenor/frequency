import re
import unittest
from datetime import datetime, timezone

from backend.tests import _path  # noqa: F401
from backend.tests.pg_temp import TempPostgres
from backend.tests import _aluno_fixtures as fx
from backend.tests._asgi import chamar
import aluno_auth
import seguranca

_pg = None


def setUpModule():
    global _pg
    _pg = TempPostgres().start()


def tearDownModule():
    _pg.stop()


def _ok(conn, academia_id):
    return True


class PainelAlunoTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        self.conn = fx.conectar(_pg.dsn)
        self.conn.execute("TRUNCATE aluno_codigos, aluno_sessoes, aluno_credenciais, alunos, academia_recursos, academias RESTART IDENTITY CASCADE")
        self.conn.commit()
        self.aid = fx.criar_academia(self.conn)
        self.outra = fx.criar_academia(self.conn, nome="Outra")
        self.aluno = fx.criar_aluno(self.conn, self.aid, email=None, documento="d-sem-email")
        self.msgs = []
        self.usuario = {"id": 1, "academia_id": self.aid, "papel": "dono", "nome": "Dono"}
        self.app = FastAPI()
        self.app.include_router(aluno_auth.router)
        self.app.include_router(aluno_auth.router_painel)
        self.app.dependency_overrides[aluno_auth.conexao] = lambda: self.conn
        self.app.dependency_overrides[seguranca.usuario_de_academia] = lambda: self.usuario
        aluno_auth._limitador = None
        aluno_auth.ENVIAR_EMAIL = lambda d, a, c: self.msgs.append(c) or True
        aluno_auth.ASSINATURA_OK = _ok

    def tearDown(self):
        aluno_auth.ENVIAR_EMAIL = aluno_auth.enviar_email_texto
        aluno_auth.ASSINATURA_OK = aluno_auth._assinatura_em_dia
        self.conn.close()

    def _put_email(self, email, aluno=None):
        return chamar(self.app, "PUT", f"/alunos/{aluno or self.aluno}/email", {"email": email})

    def test_email_e_normalizado_e_estado_vira_convidado(self):
        self.assertEqual(self._put_email("  Novo@Gmail.COM ")[0], 200)
        s, _, corpo = chamar(self.app, "GET", f"/alunos/{self.aluno}/acesso-app")
        self.assertEqual((s, corpo["email"], corpo["acesso_app"]), (200, "novo@gmail.com", "convidado"))
        self.assertTrue(corpo["app_ligado"])

    # --- correções da revisão final ---
    def test_convite_de_uma_academia_nao_envia_codigo_a_aluno_de_outra(self):
        self._put_email("mesmo@gmail.com")
        fx.criar_aluno(self.conn, self.outra, email="mesmo@gmail.com", documento="x-outra")
        self.msgs.clear()
        s, _, _ = chamar(self.app, "POST", f"/alunos/{self.aluno}/convite")
        self.assertEqual(s, 200)
        self.assertEqual(len(self.msgs), 1)
        n = self.conn.execute("SELECT count(*) AS n FROM aluno_codigos c JOIN alunos a ON a.id=c.aluno_id "
                              "WHERE a.academia_id = %s", (self.outra,)).fetchone()["n"]
        self.assertEqual(n, 0)

    def test_recepcao_nao_troca_email_existente_nem_redefine_acesso(self):
        self._put_email("antigo@gmail.com")
        self.usuario["papel"] = "recepcao"
        s, _, c = self._put_email("novo@gmail.com")
        self.assertEqual((s, c["detail"]), (403, "sem_permissao"))
        self.assertEqual(chamar(self.app, "POST", f"/alunos/{self.aluno}/redefinir-acesso")[0], 403)
        # cadastrar e-mail de aluno que ainda não tem continua permitido
        sem = fx.criar_aluno(self.conn, self.aid, email=None, documento="d-sem2")
        self.assertEqual(self._put_email("primeiro@gmail.com", aluno=sem)[0], 200)

    def test_trocar_email_revoga_sessoes_e_senha(self):
        self._put_email("antigo@gmail.com")
        fx.criar_aluno_demo(self.conn, self.aid, email="demo@gmail.com")
        demo = self.conn.execute("SELECT id FROM alunos WHERE email='demo@gmail.com'").fetchone()["id"]
        aluno_auth.criar_sessao(self.conn, {"id": demo, "nome": "D", "academia_id": self.aid}, "tel")
        self.conn.commit()
        self.assertEqual(self._put_email("outro@gmail.com", aluno=demo)[0], 200)
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM aluno_credenciais WHERE aluno_id=%s", (demo,)).fetchone()["n"], 0)
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM aluno_sessoes WHERE aluno_id=%s AND revogada_em IS NULL", (demo,)).fetchone()["n"], 0)

    def test_sem_email_estado_sem_email(self):
        _, _, corpo = chamar(self.app, "GET", f"/alunos/{self.aluno}/acesso-app")
        self.assertEqual(corpo["acesso_app"], "sem_email")

    def test_email_invalido_retorna_422(self):
        s, _, c = self._put_email("sem-arroba")
        self.assertEqual((s, c["detail"]), (422, "email_invalido"))

    def test_email_duplicado_na_academia_retorna_409(self):
        outro = fx.criar_aluno(self.conn, self.aid, email="dup@gmail.com", documento="d2")
        s, _, c = self._put_email("DUP@gmail.com")
        self.assertEqual((s, c["detail"]), (409, "email_ja_cadastrado"))
        self.assertEqual(self._put_email("dup@gmail.com", aluno=outro)[0], 200)  # o mesmo aluno pode regravar

    def test_aluno_de_outra_academia_e_404(self):
        alheio = fx.criar_aluno(self.conn, self.outra, email="x@gmail.com", documento="dx")
        self.assertEqual(self._put_email("a@b.com", aluno=alheio)[0], 404)
        self.assertEqual(chamar(self.app, "POST", f"/alunos/{alheio}/convite")[0], 404)

    def test_convite_envia_codigo(self):
        self._put_email("novo@gmail.com")
        s, _, c = chamar(self.app, "POST", f"/alunos/{self.aluno}/convite")
        self.assertEqual((s, c), (200, {"enviado": True}))
        self.assertRegex(self.msgs[0], r"\b\d{6}\b")

    def test_convite_sem_email_retorna_409(self):
        s, _, c = chamar(self.app, "POST", f"/alunos/{self.aluno}/convite")
        self.assertEqual((s, c["detail"]), (409, "aluno_sem_email"))

    def test_convite_com_recurso_desligado_retorna_409(self):
        self.conn.execute("UPDATE academia_recursos SET ligado = FALSE")
        self.conn.commit()
        self._put_email("novo@gmail.com")
        s, _, c = chamar(self.app, "POST", f"/alunos/{self.aluno}/convite")
        self.assertEqual((s, c["detail"]), (409, "recurso_desligado"))

    def test_redefinir_acesso_revoga_sessoes_e_apaga_credencial(self):
        self._put_email("novo@gmail.com")
        chamar(self.app, "POST", f"/alunos/{self.aluno}/convite")
        codigo = re.search(r"\b(\d{6})\b", self.msgs[0]).group(1)
        _, _, t = chamar(self.app, "POST", "/aluno/auth/codigo", {"email": "novo@gmail.com", "codigo": codigo})
        _, _, sessao = chamar(self.app, "POST", "/aluno/auth/definir-senha", {"ticket": t["ticket"], "senha": "senha-segura-1"})
        self.assertEqual(chamar(self.app, "GET", f"/alunos/{self.aluno}/acesso-app")[2]["acesso_app"], "ativo")
        self.assertEqual(chamar(self.app, "POST", f"/alunos/{self.aluno}/redefinir-acesso")[0], 200)
        self.assertEqual(chamar(self.app, "GET", "/aluno/eu", cabecalhos={"Authorization": "Bearer " + sessao["token"]})[0], 401)
        self.assertEqual(chamar(self.app, "GET", f"/alunos/{self.aluno}/acesso-app")[2]["acesso_app"], "convidado")

    def test_papel_sem_permissao_recebe_403(self):
        from fastapi import HTTPException

        def negar():
            raise HTTPException(403, "sem_permissao")

        self.app.dependency_overrides[seguranca.usuario_de_academia] = negar
        self.assertEqual(self._put_email("a@b.com")[0], 403)

    def test_modo_espelho_somente_leitura_bloqueia_escrita(self):
        import os
        os.environ["SYNC_MIRROR_READ_ONLY"] = "YES"
        try:
            s, _, c = self._put_email("a@b.com")
        finally:
            os.environ.pop("SYNC_MIRROR_READ_ONLY")
        self.assertEqual((s, c["detail"]), (403, "modo_somente_consulta"))


if __name__ == "__main__":
    unittest.main()
