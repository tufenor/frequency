import unittest

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


class FixturesAlunoTests(unittest.TestCase):
    def test_fixture_nao_roda_fora_de_banco_descartavel(self):
        import re
        dsn_prod = re.sub(r"dbname=\S+", "dbname=postgres", _pg.dsn)
        with self.assertRaises(RuntimeError):
            fx.conectar(dsn_prod)

    def test_aluno_demo_entra_com_senha_de_teste(self):
        conn = fx.conectar(_pg.dsn)
        try:
            aid = fx.criar_academia(conn, nome="Demo")
            fx.criar_aluno_demo(conn, aid)
            sessao = aluno_auth.entrar_com_senha(
                conn, "testealuno@gmail.com", "qwerty135", assinatura_ok=lambda c, a: True)
            self.assertIsNotNone(sessao)
            self.assertIsNone(aluno_auth.entrar_com_senha(
                conn, "testealuno@gmail.com", "errada", assinatura_ok=lambda c, a: True))
        finally:
            conn.close()

    def test_senha_errada_custa_o_mesmo_numero_de_argon2_que_email_inexistente(self):
        import seguranca
        conn = fx.conectar(_pg.dsn)
        chamadas = []
        original = seguranca.verificar_senha
        seguranca.verificar_senha = lambda s, h: chamadas.append(1) or original(s, h)
        try:
            aid = fx.criar_academia(conn, nome="Timing")
            fx.criar_aluno_demo(conn, aid, email="timing@gmail.com")
            ok = lambda c, a: True
            aluno_auth.entrar_com_senha(conn, "timing@gmail.com", "errada", assinatura_ok=ok)
            com_conta = len(chamadas)
            chamadas.clear()
            aluno_auth.entrar_com_senha(conn, "ninguem@gmail.com", "errada", assinatura_ok=ok)
            self.assertEqual((com_conta, len(chamadas)), (1, 1))
        finally:
            seguranca.verificar_senha = original
            conn.close()

    def test_senha_errada_custa_o_mesmo_numero_de_argon2_que_email_inexistente(self):
        import seguranca
        conn = fx.conectar(_pg.dsn)
        chamadas = []
        original = seguranca.verificar_senha
        seguranca.verificar_senha = lambda s, h: chamadas.append(1) or original(s, h)
        try:
            aid = fx.criar_academia(conn, nome="Timing")
            fx.criar_aluno_demo(conn, aid, email="timing@gmail.com")
            ok = lambda c, a: True
            aluno_auth.entrar_com_senha(conn, "timing@gmail.com", "errada", assinatura_ok=ok)
            com_conta = len(chamadas)
            chamadas.clear()
            aluno_auth.entrar_com_senha(conn, "ninguem@gmail.com", "errada", assinatura_ok=ok)
            self.assertEqual((com_conta, len(chamadas)), (1, 1))
        finally:
            seguranca.verificar_senha = original
            conn.close()


if __name__ == "__main__":
    unittest.main()
