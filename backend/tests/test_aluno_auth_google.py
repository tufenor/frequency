import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from backend.tests import _path  # noqa: F401
from backend.tests.pg_temp import TempPostgres
from backend.tests import _aluno_fixtures as fx
import aluno_auth

_pg = None
CLIENT = "app-aluno.apps.googleusercontent.com"
_chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_outra = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks():
    jwk = RSAAlgorithm.to_jwk(_chave.public_key(), as_dict=True)
    jwk.update(kid="k1", alg="RS256", use="sig")
    return {"keys": [jwk]}


def _token(email="aluno@gmail.com", sub="g-123", aud=CLIENT, exp=None, verified=True, iss="https://accounts.google.com", chave=None):
    corpo = {"iss": iss, "aud": aud, "sub": sub, "email": email, "email_verified": verified,
             "exp": exp if exp is not None else int(time.time()) + 600}
    return jwt.encode(corpo, chave or _chave, algorithm="RS256", headers={"kid": "k1"})


def _ok(conn, academia_id):
    return True


def setUpModule():
    global _pg
    _pg = TempPostgres().start()


def tearDownModule():
    _pg.stop()


class GoogleTests(unittest.TestCase):
    def setUp(self):
        self.conn = fx.conectar(_pg.dsn)
        self.conn.execute("TRUNCATE aluno_codigos, aluno_sessoes, aluno_credenciais, alunos, academia_recursos, academias RESTART IDENTITY CASCADE")
        self.conn.commit()
        self.aid = fx.criar_academia(self.conn)
        self.aluno = fx.criar_aluno(self.conn, self.aid)

    def tearDown(self):
        self.conn.close()

    def _entrar(self, token):
        r = aluno_auth.entrar_com_google(self.conn, token, audiencias=[CLIENT], jwks_fetch=_jwks, assinatura_ok=_ok)
        self.conn.commit()
        return r

    def test_google_com_email_cadastrado_entra_e_vincula_sub(self):
        r = self._entrar(_token(email="Aluno@Gmail.com"))
        self.assertEqual(r["aluno"]["id"], self.aluno)
        sub = self.conn.execute("SELECT google_sub FROM aluno_credenciais WHERE aluno_id=%s", (self.aluno,)).fetchone()
        self.assertEqual(sub["google_sub"], "g-123")

    def test_mesmo_email_em_duas_academias_nao_gera_erro_500_no_google(self):
        outra = fx.criar_academia(self.conn, nome="Outra")
        segundo = fx.criar_aluno(self.conn, outra, email="aluno@gmail.com", documento="d-outra")
        self.assertEqual(self._entrar(_token())["aluno"]["id"], self.aluno)
        self.conn.execute("UPDATE alunos SET status='inativo' WHERE id=%s", (self.aluno,))
        self.conn.commit()
        self.assertEqual(self._entrar(_token())["aluno"]["id"], segundo)

    def test_audiencias_usam_client_web_existente_quando_a_lista_do_app_esta_vazia(self):
        import os
        antigo = {k: os.environ.get(k) for k in ("GOOGLE_ALUNO_CLIENT_IDS", "GOOGLE_OAUTH_CLIENT_ID")}
        try:
            os.environ["GOOGLE_ALUNO_CLIENT_IDS"] = ""
            os.environ["GOOGLE_OAUTH_CLIENT_ID"] = "web.apps.googleusercontent.com"
            self.assertEqual(aluno_auth.audiencias_google(), ["web.apps.googleusercontent.com"])
            os.environ["GOOGLE_ALUNO_CLIENT_IDS"] = "a.apps, b.apps"
            self.assertEqual(aluno_auth.audiencias_google(), ["a.apps", "b.apps", "web.apps.googleusercontent.com"])
        finally:
            for k, v in antigo.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_google_com_email_nao_cadastrado_e_negado(self):
        self.assertIsNone(self._entrar(_token(email="intruso@gmail.com")))

    def test_google_email_nao_verificado_e_negado(self):
        self.assertIsNone(self._entrar(_token(verified=False)))

    def test_audiencia_errada_e_negada(self):
        self.assertIsNone(self._entrar(_token(aud="outro-app")))

    def test_token_expirado_e_negado(self):
        self.assertIsNone(self._entrar(_token(exp=int(time.time()) - 10)))

    def test_emissor_errado_e_negado(self):
        self.assertIsNone(self._entrar(_token(iss="https://evil.example")))

    def test_assinatura_de_outra_chave_e_negada(self):
        self.assertIsNone(self._entrar(_token(chave=_outra)))

    def test_segundo_login_exige_mesmo_sub(self):
        self.assertIsNotNone(self._entrar(_token(sub="g-123")))
        self.assertIsNotNone(self._entrar(_token(sub="g-123")))
        self.assertIsNone(self._entrar(_token(sub="g-999")))

    def test_aluno_inativo_com_google_e_negado(self):
        self.conn.execute("UPDATE alunos SET status='inativo'")
        self.conn.commit()
        self.assertIsNone(self._entrar(_token()))


if __name__ == "__main__":
    unittest.main()
