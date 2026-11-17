import unittest

from backend.tests import _path  # noqa: F401
from backend.tests.pg_temp import TempPostgres
from backend.tests import _aluno_fixtures as fx
from backend.tests._asgi import chamar
import aluno_auth
import aluno_ficha
import seguranca

_pg = None


def setUpModule():
    global _pg
    _pg = TempPostgres().start()


def tearDownModule():
    _pg.stop()


class FichaAlunoTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        self.conn = fx.conectar(_pg.dsn)
        self.conn.execute("TRUNCATE aluno_ficha, aluno_codigos, aluno_sessoes, aluno_credenciais, alunos, academia_recursos, academias RESTART IDENTITY CASCADE")
        self.conn.commit()
        self.aid = fx.criar_academia(self.conn)
        self.outra = fx.criar_academia(self.conn, nome="Outra")
        self.aluno = fx.criar_aluno(self.conn, self.aid, email="a@gmail.com", documento="d1")
        self.de_outra = fx.criar_aluno(self.conn, self.outra, email="b@gmail.com", documento="d2")
        self.usuario = {"id": 1, "academia_id": self.aid, "papel": "recepcao", "nome": "R"}
        self.app = FastAPI()
        self.app.include_router(aluno_ficha.router)
        self.app.dependency_overrides[aluno_auth.conexao] = lambda: self.conn
        self.app.dependency_overrides[seguranca.usuario_de_academia] = lambda: self.usuario

    def tearDown(self):
        self.conn.close()

    def _put(self, corpo, aluno=None):
        return chamar(self.app, "PUT", f"/alunos/{aluno or self.aluno}/ficha", corpo)

    def test_ficha_vazia_retorna_campos_nulos(self):
        s, _, c = chamar(self.app, "GET", f"/alunos/{self.aluno}/ficha")
        self.assertEqual(s, 200)
        self.assertIsNone(c["contato_emergencia_nome"])
        self.assertIsNone(c["peso_kg"])

    def test_grava_e_le_ficha_completa(self):
        corpo = {"contato_emergencia_nome": "  Maria ", "contato_emergencia_telefone": "65999990000",
                 "endereco_rua": "Rua A", "endereco_numero": "10", "endereco_cidade": "Cuiabá",
                 "objetivo": "hipertrofia", "restricoes_saude": "joelho direito", "atestado_medico": True,
                 "sexo": "feminino", "peso_kg": 62.5, "altura_cm": 168}
        self.assertEqual(self._put(corpo)[0], 200)
        _, _, c = chamar(self.app, "GET", f"/alunos/{self.aluno}/ficha")
        self.assertEqual(c["contato_emergencia_nome"], "Maria")
        self.assertEqual((c["sexo"], c["altura_cm"], c["atestado_medico"]), ("feminino", 168, True))
        self.assertEqual(float(c["peso_kg"]), 62.5)

    def test_regravar_atualiza_sem_duplicar(self):
        self._put({"objetivo": "emagrecer"})
        self._put({"objetivo": "ganhar massa"})
        n = self.conn.execute("SELECT count(*) AS n FROM aluno_ficha WHERE aluno_id=%s", (self.aluno,)).fetchone()["n"]
        self.assertEqual(n, 1)
        _, _, c = chamar(self.app, "GET", f"/alunos/{self.aluno}/ficha")
        self.assertEqual(c["objetivo"], "ganhar massa")

    def test_valores_invalidos_sao_422(self):
        for corpo in ({"sexo": "xyz"}, {"peso_kg": 5}, {"peso_kg": 900}, {"altura_cm": 20}, {"altura_cm": 400}):
            with self.subTest(corpo=corpo):
                self.assertEqual(self._put(corpo)[0], 422)

    def test_nao_acessa_aluno_de_outra_academia(self):
        self.assertEqual(chamar(self.app, "GET", f"/alunos/{self.de_outra}/ficha")[0], 404)
        self.assertEqual(self._put({"objetivo": "x"}, aluno=self.de_outra)[0], 404)

    def test_modo_somente_consulta_bloqueia_escrita(self):
        import os
        os.environ["SYNC_MIRROR_READ_ONLY"] = "YES"
        try:
            self.assertEqual(self._put({"objetivo": "x"})[0], 403)
        finally:
            del os.environ["SYNC_MIRROR_READ_ONLY"]


if __name__ == "__main__":
    unittest.main()
