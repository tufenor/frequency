import re
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


def _ok(conn, academia_id):
    return True


class SenhaTests(unittest.TestCase):
    def setUp(self):
        self.conn = fx.conectar(_pg.dsn)
        self.conn.execute("TRUNCATE aluno_codigos, aluno_sessoes, aluno_credenciais, alunos, academia_recursos, academias RESTART IDENTITY CASCADE")
        self.conn.commit()
        self.aid = fx.criar_academia(self.conn)
        self.aluno = fx.criar_aluno(self.conn, self.aid)
        self.msgs = []
        self.t0 = datetime.now(timezone.utc)
        aluno_auth.iniciar_acesso(self.conn, "aluno@gmail.com", enviar=lambda d, a, c: self.msgs.append(c) or True,
                                  assinatura_ok=_ok, agora=self.t0)
        self.conn.commit()
        self.codigo = re.search(r"\b(\d{6})\b", self.msgs[0]).group(1)

    def tearDown(self):
        self.conn.close()

    def _verificar(self, codigo, agora=None):
        r = aluno_auth.verificar_codigo(self.conn, "aluno@gmail.com", codigo, assinatura_ok=_ok, agora=agora or self.t0)
        self.conn.commit()
        return r

    def test_codigo_correto_gera_ticket(self):
        ticket = self._verificar(self.codigo)
        self.assertTrue(ticket and len(ticket) >= 40)

    def test_sexta_tentativa_invalida_o_codigo(self):
        errado = "000000" if self.codigo != "000000" else "111111"
        for _ in range(5):
            self.assertIsNone(self._verificar(errado))
        self.assertIsNone(self._verificar(self.codigo))  # já invalidado

    def test_codigo_expirado_e_negado(self):
        self.assertIsNone(self._verificar(self.codigo, self.t0 + timedelta(minutes=11)))

    def test_codigo_usado_nao_vale_duas_vezes(self):
        self.assertIsNotNone(self._verificar(self.codigo))
        self.assertIsNone(self._verificar(self.codigo))

    def test_definir_senha_cria_credencial_e_sessao(self):
        ticket = self._verificar(self.codigo)
        sessao = aluno_auth.definir_senha(self.conn, ticket, "senha-segura-1", "Pixel 8", agora=self.t0)
        self.conn.commit()
        self.assertEqual(sessao["aluno"]["id"], self.aluno)
        h = aluno_auth.hash_token(sessao["token"])
        linha = self.conn.execute("SELECT * FROM aluno_sessoes WHERE token_hash = %s", (h,)).fetchone()
        self.assertEqual(linha["aparelho"], "Pixel 8")
        self.assertAlmostEqual((linha["expira_em"] - self.t0).days, 30, delta=1)
        cred = self.conn.execute("SELECT senha_hash FROM aluno_credenciais WHERE aluno_id = %s", (self.aluno,)).fetchone()
        self.assertTrue(cred["senha_hash"].startswith("$argon2"))
        self.assertNotIn("senha-segura-1", cred["senha_hash"])

    def test_senha_curta_e_recusada_sem_gastar_o_ticket(self):
        ticket = self._verificar(self.codigo)
        with self.assertRaises(ValueError) as cm:
            aluno_auth.definir_senha(self.conn, ticket, "curta", "", agora=self.t0)
        self.assertEqual(str(cm.exception), "senha_curta")
        self.assertIsNotNone(aluno_auth.definir_senha(self.conn, ticket, "senha-segura-1", "", agora=self.t0))

    def test_ticket_so_vale_uma_vez(self):
        ticket = self._verificar(self.codigo)
        aluno_auth.definir_senha(self.conn, ticket, "senha-segura-1", "", agora=self.t0)
        with self.assertRaises(ValueError) as cm:
            aluno_auth.definir_senha(self.conn, ticket, "outra-senha-2", "", agora=self.t0)
        self.assertEqual(str(cm.exception), "ticket_invalido")

    def test_ticket_expira_em_10_minutos(self):
        ticket = self._verificar(self.codigo)
        with self.assertRaises(ValueError) as cm:
            aluno_auth.definir_senha(self.conn, ticket, "senha-segura-1", "", agora=self.t0 + timedelta(minutes=11))
        self.assertEqual(str(cm.exception), "ticket_invalido")

    def test_aluno_inativado_depois_do_codigo_nao_define_senha(self):
        ticket = self._verificar(self.codigo)
        self.conn.execute("UPDATE alunos SET status='inativo' WHERE id = %s", (self.aluno,))
        self.conn.commit()
        with self.assertRaises(ValueError):
            aluno_auth.definir_senha(self.conn, ticket, "senha-segura-1", "", agora=self.t0)


if __name__ == "__main__":
    unittest.main()
