import unittest

from backend.tests import _path  # noqa: F401
from backend.tests.pg_temp import TempPostgres
from backend.tests import _aluno_fixtures as fx
from backend.tests._asgi import chamar
import aluno_auth
import aluno_catalogo_painel
import aluno_treinos
import seguranca

_pg = None


def setUpModule():
    global _pg
    _pg = TempPostgres().start()


def tearDownModule():
    _pg.stop()


def _ok(conn, academia_id):
    return True


class CatalogoPainelTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        self.conn = fx.conectar(_pg.dsn)
        self.conn.execute("TRUNCATE treinos, exercicios_custom, academia_exercicios_visibilidade, aluno_sessoes, "
                          "aluno_credenciais, alunos, academia_recursos, academias RESTART IDENTITY CASCADE")
        self.conn.commit()
        self.aid = fx.criar_academia(self.conn)
        self.outra = fx.criar_academia(self.conn, nome="Outra")
        self.aluno = fx.criar_aluno(self.conn, self.aid, email="a@gmail.com", documento="d1")
        self.usuario = {"id": 1, "academia_id": self.aid, "papel": "dono", "nome": "D"}
        self.app = FastAPI()
        self.app.include_router(aluno_catalogo_painel.router)
        self.app.include_router(aluno_treinos.router)
        self.app.dependency_overrides[aluno_auth.conexao] = lambda: self.conn
        self.app.dependency_overrides[seguranca.usuario_de_academia] = lambda: self.usuario
        self.app.dependency_overrides[seguranca.somente_dono] = self._dono
        aluno_auth.ASSINATURA_OK = _ok

    def _dono(self):
        if self.usuario["papel"] != "dono":
            from fastapi import HTTPException
            raise HTTPException(403, "sem_permissao")
        return self.usuario

    def tearDown(self):
        aluno_auth.ASSINATURA_OK = aluno_auth._assinatura_em_dia
        self.conn.close()

    def test_lista_com_contagem_por_grupo(self):
        s, _, c = chamar(self.app, "GET", f"/academias/{self.aid}/exercicios")
        self.assertEqual(s, 200)
        self.assertEqual(len(c["grupos"]), 12)
        peito = next(g for g in c["grupos"] if g["grupo"] == "peito")
        self.assertGreaterEqual(peito["ativos"], 12)
        self.assertFalse(peito["aviso"])

    def test_ocultar_reflete_na_contagem_e_avisa_abaixo_de_10(self):
        ex = [e for e in chamar(self.app, "GET", f"/academias/{self.aid}/exercicios")[2]["exercicios"] if e["grupo"] == "peito"]
        for e in ex[:3]:
            s, _, _ = chamar(self.app, "PUT", f"/academias/{self.aid}/exercicios/{e['ref'][2:]}/visibilidade", {"oculto": True})
            self.assertEqual(s, 200)
        c = chamar(self.app, "GET", f"/academias/{self.aid}/exercicios")[2]
        peito = next(g for g in c["grupos"] if g["grupo"] == "peito")
        self.assertEqual(peito["ativos"], len(ex) - 3)
        self.assertTrue(peito["aviso"])
        # reativar
        chamar(self.app, "PUT", f"/academias/{self.aid}/exercicios/{ex[0]['ref'][2:]}/visibilidade", {"oculto": False})
        c = chamar(self.app, "GET", f"/academias/{self.aid}/exercicios")[2]
        self.assertEqual(next(g for g in c["grupos"] if g["grupo"] == "peito")["ativos"], len(ex) - 2)

    def test_so_a_propria_academia(self):
        for metodo, caminho, corpo in (("GET", f"/academias/{self.outra}/exercicios", None),
                                      ("PUT", f"/academias/{self.outra}/exercicios/pushups/visibilidade", {"oculto": True}),
                                      ("POST", f"/academias/{self.outra}/exercicios", {"nome": "X1", "grupo": "peito"})):
            s, _, _ = chamar(self.app, metodo, caminho, corpo)
            self.assertEqual(s, 403, caminho)

    def test_recepcao_le_mas_nao_escreve(self):
        self.usuario["papel"] = "recepcao"
        self.assertEqual(chamar(self.app, "GET", f"/academias/{self.aid}/exercicios")[0], 200)
        s, _, _ = chamar(self.app, "PUT", f"/academias/{self.aid}/exercicios/pushups/visibilidade", {"oculto": True})
        self.assertEqual(s, 403)

    def test_exercicio_inexistente_e_grupo_invalido(self):
        s, _, _ = chamar(self.app, "PUT", f"/academias/{self.aid}/exercicios/nao_existe/visibilidade", {"oculto": True})
        self.assertEqual(s, 404)
        s, _, _ = chamar(self.app, "POST", f"/academias/{self.aid}/exercicios", {"nome": "Algo", "grupo": "cardio"})
        self.assertEqual(s, 422)

    def test_exercicio_da_academia_aparece_para_o_aluno_e_some_ao_remover(self):
        s, _, novo = chamar(self.app, "POST", f"/academias/{self.aid}/exercicios", {"nome": "Supino da casa", "grupo": "peito", "equipamento": "Máquina"})
        self.assertEqual(s, 201)
        s, _, sess = None, None, aluno_auth.criar_sessao(self.conn, {"id": self.aluno, "nome": "A", "academia_id": self.aid})
        self.conn.commit()
        cab = {"Authorization": "Bearer " + sess["token"]}
        refs = [e["ref"] for e in chamar(self.app, "GET", "/aluno/catalogo", None, cab)[2]["exercicios"]]
        self.assertIn(novo["ref"], refs)
        s, _, _ = chamar(self.app, "DELETE", f"/academias/{self.aid}/exercicios/{novo['ref'][2:]}")
        self.assertEqual(s, 204)
        refs = [e["ref"] for e in chamar(self.app, "GET", "/aluno/catalogo", None, cab)[2]["exercicios"]]
        self.assertNotIn(novo["ref"], refs)

    def test_ajustar_exercicio_da_academia(self):
        _, _, novo = chamar(self.app, "POST", f"/academias/{self.aid}/exercicios", {"nome": "Antigo", "grupo": "peito"})
        s, _, r = chamar(self.app, "PATCH", f"/academias/{self.aid}/exercicios/{novo['ref'][2:]}", {"nome": "Novo", "grupo": "costas"})
        self.assertEqual((s, r["nome"]), (200, "Novo"))
        lista = chamar(self.app, "GET", f"/academias/{self.aid}/exercicios")[2]["exercicios"]
        achado = next(e for e in lista if e["ref"] == novo["ref"])
        self.assertEqual((achado["nome"], achado["grupo"]), ("Novo", "costas"))

    def test_atalhos_usam_a_academia_do_usuario(self):
        s, _, c = chamar(self.app, "GET", "/academia/exercicios")
        self.assertEqual(s, 200)
        self.assertEqual(len(c["grupos"]), 12)
        self.assertEqual(chamar(self.app, "PUT", "/academia/exercicios/pushups/visibilidade", {"oculto": True})[0], 200)
        row = self.conn.execute("SELECT academia_id, oculto FROM academia_exercicios_visibilidade WHERE exercicio_id='pushups'").fetchone()
        self.assertEqual((row["academia_id"], row["oculto"]), (self.aid, True))
        s, _, novo = chamar(self.app, "POST", "/academia/exercicios", {"nome": "Meu ex", "grupo": "costas"})
        self.assertEqual(s, 201)
        self.assertEqual(chamar(self.app, "PATCH", f"/academia/exercicios/{novo['ref'][2:]}", {"nome": "Meu ex 2"})[0], 200)
        self.assertEqual(chamar(self.app, "DELETE", f"/academia/exercicios/{novo['ref'][2:]}")[0], 204)

    def test_nao_ajusta_exercicio_de_outra_academia(self):
        cid = self.conn.execute("INSERT INTO exercicios_custom (escopo, academia_id, nome, grupo) VALUES ('academia',%s,'Dela','peito') RETURNING id",
                                (self.outra,)).fetchone()["id"]
        self.conn.commit()
        self.assertEqual(chamar(self.app, "PATCH", f"/academias/{self.aid}/exercicios/{cid}", {"nome": "Hack"})[0], 404)
        self.assertEqual(chamar(self.app, "DELETE", f"/academias/{self.aid}/exercicios/{cid}")[0], 404)


if __name__ == "__main__":
    unittest.main()
