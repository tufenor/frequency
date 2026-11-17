import unittest
from datetime import datetime, timedelta, timezone

from backend.tests import _path  # noqa: F401
from backend.tests.pg_temp import TempPostgres
from backend.tests import _aluno_fixtures as fx
import aluno_auth

_pg = None


def setUpModule():
    global _pg
    _pg = TempPostgres().start()


def tearDownModule():
    _pg.stop()


class Caixa:
    def __init__(self):
        self.mensagens = []

    def __call__(self, destino, assunto, corpo):
        self.mensagens.append((destino, assunto, corpo))
        return True


def _ok(conn, academia_id):
    return True


class IniciarAcessoTests(unittest.TestCase):
    def setUp(self):
        self.conn = fx.conectar(_pg.dsn)
        self.conn.execute("TRUNCATE aluno_codigos, aluno_sessoes, aluno_credenciais, alunos, academia_recursos, academias RESTART IDENTITY CASCADE")
        self.conn.commit()
        self.aid = fx.criar_academia(self.conn)
        self.caixa = Caixa()

    def tearDown(self):
        self.conn.close()

    def _iniciar(self, email="aluno@gmail.com", agora=None):
        aluno_auth.iniciar_acesso(self.conn, email, "1.2.3.4", enviar=self.caixa, assinatura_ok=_ok, agora=agora)
        self.conn.commit()

    def test_email_cadastrado_recebe_codigo_de_6_digitos(self):
        fx.criar_aluno(self.conn, self.aid)
        self._iniciar("  ALUNO@gmail.com ")
        self.assertEqual(len(self.caixa.mensagens), 1)
        destino, _, corpo = self.caixa.mensagens[0]
        self.assertEqual(destino, "aluno@gmail.com")
        import re
        self.assertRegex(corpo, r"\b\d{6}\b")

    def test_email_desconhecido_responde_igual_sem_enviar(self):
        self._iniciar("ninguem@gmail.com")
        self.assertEqual(self.caixa.mensagens, [])

    def test_aluno_inativo_nao_recebe(self):
        fx.criar_aluno(self.conn, self.aid, status="inativo")
        self._iniciar()
        self.assertEqual(self.caixa.mensagens, [])

    def test_academia_sem_recurso_ligado_nao_envia(self):
        outra = fx.criar_academia(self.conn, nome="Sem flag", ligar_login=False)
        fx.criar_aluno(self.conn, outra, email="x@gmail.com")
        self._iniciar("x@gmail.com")
        self.assertEqual(self.caixa.mensagens, [])

    def test_reenvio_antes_de_60s_nao_gera_novo_codigo(self):
        fx.criar_aluno(self.conn, self.aid)
        t0 = datetime.now(timezone.utc)
        self._iniciar(agora=t0)
        self._iniciar(agora=t0 + timedelta(seconds=30))
        self.assertEqual(len(self.caixa.mensagens), 1)
        self._iniciar(agora=t0 + timedelta(seconds=61))
        self.assertEqual(len(self.caixa.mensagens), 2)

    def test_sexto_envio_na_hora_e_negado_silenciosamente(self):
        fx.criar_aluno(self.conn, self.aid)
        t0 = datetime.now(timezone.utc)
        for i in range(6):
            self._iniciar(agora=t0 + timedelta(seconds=61 * i))
        self.assertEqual(len(self.caixa.mensagens), 5)

    def test_codigo_nao_aparece_no_banco_em_texto(self):
        fx.criar_aluno(self.conn, self.aid)
        self._iniciar()
        import re
        codigo = re.search(r"\b(\d{6})\b", self.caixa.mensagens[0][2]).group(1)
        linhas = self.conn.execute("SELECT * FROM aluno_codigos").fetchall()
        self.assertEqual(len(linhas), 1)
        self.assertNotIn(codigo, str(dict(linhas[0])))
        self.assertTrue(aluno_auth.codigo_valido(codigo, linhas[0]["aluno_id"], linhas[0]["codigo_hash"]))

    def test_novo_codigo_invalida_o_anterior(self):
        fx.criar_aluno(self.conn, self.aid)
        t0 = datetime.now(timezone.utc)
        self._iniciar(agora=t0)
        self._iniciar(agora=t0 + timedelta(seconds=61))
        validos = self.conn.execute("SELECT count(*) AS n FROM aluno_codigos WHERE usado_em IS NULL").fetchone()["n"]
        self.assertEqual(validos, 1)


if __name__ == "__main__":
    unittest.main()


class RotaIniciarTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        self.conn = fx.conectar(_pg.dsn)
        self.conn.execute("TRUNCATE aluno_codigos, aluno_sessoes, aluno_credenciais, alunos, academia_recursos, academias RESTART IDENTITY CASCADE")
        self.conn.commit()
        self.app = FastAPI()
        self.app.include_router(aluno_auth.router)
        self.app.dependency_overrides[aluno_auth.conexao] = lambda: self.conn
        aluno_auth._limitador = None
        self.caixa = Caixa()
        aluno_auth.ENVIAR_EMAIL = self.caixa
        aluno_auth.ASSINATURA_OK = _ok

    def tearDown(self):
        aluno_auth.ENVIAR_EMAIL = aluno_auth.enviar_email_texto
        aluno_auth.ASSINATURA_OK = aluno_auth._assinatura_em_dia
        self.conn.close()

    def test_rota_responde_igual_para_cadastrado_e_desconhecido(self):
        from backend.tests._asgi import chamar
        aid = fx.criar_academia(self.conn)
        fx.criar_aluno(self.conn, aid)
        a = chamar(self.app, "POST", "/aluno/auth/iniciar", {"email": "aluno@gmail.com"})
        b = chamar(self.app, "POST", "/aluno/auth/iniciar", {"email": "outro@gmail.com"})
        self.assertEqual((a[0], a[2]), (200, {"enviado": True}))
        self.assertEqual((b[0], b[2]), (200, {"enviado": True}))
        self.assertEqual(len(self.caixa.mensagens), 1)

    def test_nona_chamada_seguida_recebe_429(self):
        from backend.tests._asgi import chamar
        for _ in range(8):
            self.assertEqual(chamar(self.app, "POST", "/aluno/auth/iniciar", {"email": "a@b.com"})[0], 200)
        status, headers, _ = chamar(self.app, "POST", "/aluno/auth/iniciar", {"email": "a@b.com"})
        self.assertEqual(status, 429)
        self.assertIn("retry-after", headers)
