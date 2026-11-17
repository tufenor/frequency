import re
import time
import unittest
from datetime import datetime, timedelta, timezone

from backend.tests import _path  # noqa: F401
from backend.tests.pg_temp import TempPostgres
from backend.tests import _aluno_fixtures as fx
from backend.tests._asgi import chamar
import aluno_auth

_pg = None


def setUpModule():
    global _pg
    _pg = TempPostgres().start()


def tearDownModule():
    _pg.stop()


def _ok(conn, academia_id):
    return True


class FluxoCompletoTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        self.conn = fx.conectar(_pg.dsn)
        self.conn.execute("TRUNCATE aluno_codigos, aluno_sessoes, aluno_credenciais, alunos, planos, academia_recursos, academias RESTART IDENTITY CASCADE")
        self.conn.commit()
        self.aid = fx.criar_academia(self.conn)
        self.aluno = fx.criar_aluno(self.conn, self.aid)
        self.msgs = []
        self.app = FastAPI()
        self.app.include_router(aluno_auth.router)
        self.app.dependency_overrides[aluno_auth.conexao] = lambda: self.conn
        aluno_auth._limitador = None
        aluno_auth.ENVIAR_EMAIL = lambda d, a, c: self.msgs.append(c) or True
        aluno_auth.ASSINATURA_OK = _ok

    def tearDown(self):
        aluno_auth.ENVIAR_EMAIL = aluno_auth.enviar_email_texto
        aluno_auth.ASSINATURA_OK = aluno_auth._assinatura_em_dia
        self.conn.close()

    def _primeiro_acesso(self, senha="senha-segura-1"):
        chamar(self.app, "POST", "/aluno/auth/iniciar", {"email": "Aluno@Gmail.com"})
        codigo = re.search(r"\b(\d{6})\b", self.msgs[-1]).group(1)
        s, _, corpo = chamar(self.app, "POST", "/aluno/auth/codigo", {"email": "aluno@gmail.com", "codigo": codigo})
        self.assertEqual(s, 200)
        s, _, sessao = chamar(self.app, "POST", "/aluno/auth/definir-senha", {"ticket": corpo["ticket"], "senha": senha})
        self.assertEqual(s, 200)
        return sessao

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_fluxo_primeiro_acesso_e_eu(self):
        sessao = self._primeiro_acesso()
        s, _, eu = chamar(self.app, "GET", "/aluno/eu", cabecalhos=self._auth(sessao["token"]))
        self.assertEqual(s, 200)
        self.assertEqual(eu["email"], "aluno@gmail.com")
        self.assertEqual(eu["academia"]["moeda"], "BRL")
        self.assertIsNone(eu["plano"])

    def test_codigo_errado_responde_400(self):
        chamar(self.app, "POST", "/aluno/auth/iniciar", {"email": "aluno@gmail.com"})
        s, _, corpo = chamar(self.app, "POST", "/aluno/auth/codigo", {"email": "aluno@gmail.com", "codigo": "000000" if "000000" not in self.msgs[-1] else "111111"})
        self.assertEqual((s, corpo["detail"]), (400, "codigo_invalido"))

    def test_entrar_com_senha_correta(self):
        self._primeiro_acesso()
        s, _, sessao = chamar(self.app, "POST", "/aluno/auth/entrar", {"email": " ALUNO@gmail.com", "senha": "senha-segura-1"})
        self.assertEqual(s, 200)
        self.assertIn("token", sessao)

    def test_senha_errada_e_email_inexistente_mesma_resposta(self):
        self._primeiro_acesso()
        a = chamar(self.app, "POST", "/aluno/auth/entrar", {"email": "aluno@gmail.com", "senha": "errada-123"})
        b = chamar(self.app, "POST", "/aluno/auth/entrar", {"email": "nao@existe.com", "senha": "errada-123"})
        self.assertEqual((a[0], a[2]), (401, {"detail": "credenciais_invalidas"}))
        self.assertEqual((b[0], b[2]), (401, {"detail": "credenciais_invalidas"}))

    def test_oitava_falha_bloqueia_com_429(self):
        self._primeiro_acesso()
        for _ in range(8):
            self.assertEqual(chamar(self.app, "POST", "/aluno/auth/entrar", {"email": "aluno@gmail.com", "senha": "errada-123"})[0], 401)
        s, h, _ = chamar(self.app, "POST", "/aluno/auth/entrar", {"email": "aluno@gmail.com", "senha": "senha-segura-1"})
        self.assertEqual(s, 429)
        self.assertIn("retry-after", h)

    def test_sair_revoga_sessao(self):
        sessao = self._primeiro_acesso()
        self.assertEqual(chamar(self.app, "POST", "/aluno/auth/sair", cabecalhos=self._auth(sessao["token"]))[0], 204)
        self.assertEqual(chamar(self.app, "GET", "/aluno/eu", cabecalhos=self._auth(sessao["token"]))[0], 401)

    def test_eu_exige_token_valido(self):
        self.assertEqual(chamar(self.app, "GET", "/aluno/eu")[0], 401)
        s, _, c = chamar(self.app, "GET", "/aluno/eu", cabecalhos=self._auth("lixo"))
        self.assertEqual((s, c["detail"]), (401, "token_invalido"))

    def test_sessao_expirada_da_401(self):
        sessao = self._primeiro_acesso()
        self.conn.execute("UPDATE aluno_sessoes SET expira_em = now() - interval '1 minute'")
        self.conn.commit()
        self.assertEqual(chamar(self.app, "GET", "/aluno/eu", cabecalhos=self._auth(sessao["token"]))[0], 401)

    def test_aluno_inativado_perde_acesso_imediatamente(self):
        sessao = self._primeiro_acesso()
        self.conn.execute("UPDATE alunos SET status='inativo'")
        self.conn.commit()
        self.assertEqual(chamar(self.app, "GET", "/aluno/eu", cabecalhos=self._auth(sessao["token"]))[0], 401)
        self.assertEqual(chamar(self.app, "POST", "/aluno/auth/entrar", {"email": "aluno@gmail.com", "senha": "senha-segura-1"})[0], 401)

    def test_plano_aparece_no_eu(self):
        pid = self.conn.execute("INSERT INTO planos (academia_id, nome, valor, duracao_dias) VALUES (%s,'Completo',100,30) RETURNING id", (self.aid,)).fetchone()["id"]
        self.conn.execute("UPDATE alunos SET plano_id = %s", (pid,))
        self.conn.commit()
        sessao = self._primeiro_acesso()
        _, _, eu = chamar(self.app, "GET", "/aluno/eu", cabecalhos=self._auth(sessao["token"]))
        self.assertEqual(eu["plano"]["nome"], "Completo")


if __name__ == "__main__":
    unittest.main()
