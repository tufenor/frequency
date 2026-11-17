import unittest

from backend.tests import _path  # noqa: F401
from backend.tests.pg_temp import TempPostgres
from backend.tests import _aluno_fixtures as fx
from backend.tests._asgi import chamar
import aluno_auth
import aluno_treinos

_pg = None


def setUpModule():
    global _pg
    _pg = TempPostgres().start()


def tearDownModule():
    _pg.stop()


def _ok(conn, academia_id):
    return True


class TreinosTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        self.conn = fx.conectar(_pg.dsn)
        self.conn.execute("TRUNCATE treinos, exercicios_custom, academia_exercicios_visibilidade, aluno_sessoes, "
                          "aluno_credenciais, alunos, academia_recursos, academias RESTART IDENTITY CASCADE")
        self.conn.commit()
        self.aid = fx.criar_academia(self.conn)
        self.outra = fx.criar_academia(self.conn, nome="Outra")
        self.a1 = fx.criar_aluno(self.conn, self.aid, email="a1@gmail.com", documento="d1")
        self.a2 = fx.criar_aluno(self.conn, self.aid, email="a2@gmail.com", documento="d2")
        self.b1 = fx.criar_aluno(self.conn, self.outra, email="b1@gmail.com", documento="d3")
        self.t = {}
        for nome, aid, al in (("a1", self.aid, self.a1), ("a2", self.aid, self.a2), ("b1", self.outra, self.b1)):
            s = aluno_auth.criar_sessao(self.conn, {"id": al, "nome": nome, "academia_id": aid})
            self.t[nome] = {"Authorization": "Bearer " + s["token"]}
        self.conn.commit()
        self.app = FastAPI()
        self.app.include_router(aluno_treinos.router)
        self.app.dependency_overrides[aluno_auth.conexao] = lambda: self.conn
        aluno_auth.ASSINATURA_OK = _ok

    def tearDown(self):
        aluno_auth.ASSINATURA_OK = aluno_auth._assinatura_em_dia
        self.conn.close()

    def _c(self, quem, metodo, caminho, corpo=None):
        return chamar(self.app, metodo, caminho, corpo, self.t[quem])

    def _treino(self, quem="a1", **extra):
        corpo = {"nome": "Peito e tríceps", "dias_semana": [1, 4], "blocos": [
            {"grupo": "peito", "nome": "Peito", "itens": [{"ref": "c:pushups", "series": 4, "reps": "8-10", "carga": 20.5}]},
            {"grupo": "triceps", "nome": "Tríceps", "itens": [{"ref": "c:bench_dips"}]}]}
        corpo.update(extra)
        s, _, c = self._c(quem, "POST", "/aluno/treinos", corpo)
        self.assertEqual(s, 201, c)
        return c

    # ----- catálogo
    def test_exige_token(self):
        s, _, _ = chamar(self.app, "GET", "/aluno/catalogo")
        self.assertEqual(s, 401)

    def test_catalogo_efetivo_tem_12_grupos_com_12_ou_mais(self):
        s, _, c = self._c("a1", "GET", "/aluno/catalogo")
        self.assertEqual(s, 200)
        por = {}
        for e in c["exercicios"]:
            por[e["grupo"]] = por.get(e["grupo"], 0) + 1
        self.assertEqual(len(por), 12)
        self.assertTrue(all(n >= 12 for n in por.values()))

    def test_exercicio_oculto_pela_academia_some_do_catalogo_mas_fica_no_treino(self):
        t = self._treino()
        self.conn.execute("INSERT INTO academia_exercicios_visibilidade (academia_id, exercicio_id, oculto) VALUES (%s,'pushups',TRUE)", (self.aid,))
        self.conn.commit()
        _, _, c = self._c("a1", "GET", "/aluno/catalogo")
        self.assertNotIn("c:pushups", [e["ref"] for e in c["exercicios"]])
        _, _, lista = self._c("a1", "GET", "/aluno/treinos")
        item = lista["treinos"][0]["blocos"][0]["itens"][0]
        self.assertEqual(item["ref"], "c:pushups")
        self.assertTrue(item["removido_pela_academia"])
        # outra academia continua vendo
        _, _, c2 = self._c("b1", "GET", "/aluno/catalogo")
        self.assertIn("c:pushups", [e["ref"] for e in c2["exercicios"]])

    def test_nao_adiciona_exercicio_oculto_em_treino_novo(self):
        self.conn.execute("INSERT INTO academia_exercicios_visibilidade (academia_id, exercicio_id, oculto) VALUES (%s,'pushups',TRUE)", (self.aid,))
        self.conn.commit()
        s, _, c = self._c("a1", "POST", "/aluno/treinos", {"nome": "X", "blocos": [
            {"grupo": "peito", "nome": "Peito", "itens": [{"ref": "c:pushups"}]}]})
        self.assertEqual((s, c["detail"]), (422, "exercicio_indisponivel"))

    # ----- exercício próprio
    def test_exercicio_proprio_so_o_dono_ve_e_usa(self):
        s, _, ex = self._c("a1", "POST", "/aluno/exercicios", {"nome": "Meu supino", "grupo": "peito", "equipamento": "Barra"})
        self.assertEqual(s, 201)
        _, _, c2 = self._c("a2", "GET", "/aluno/catalogo")
        self.assertNotIn(ex["ref"], [e["ref"] for e in c2["exercicios"]])
        s, _, c = self._c("a2", "POST", "/aluno/treinos", {"nome": "X", "blocos": [
            {"grupo": "peito", "nome": "P", "itens": [{"ref": ex["ref"]}]}]})
        self.assertEqual(s, 422)
        s, _, c = self._c("a1", "POST", "/aluno/treinos", {"nome": "X", "blocos": [
            {"grupo": "peito", "nome": "P", "itens": [{"ref": ex["ref"]}]}]})
        self.assertEqual(s, 201)
        self.assertEqual(c["blocos"][0]["itens"][0]["nome"], "Meu supino")

    def test_exercicio_proprio_grupo_invalido(self):
        s, _, _ = self._c("a1", "POST", "/aluno/exercicios", {"nome": "Algo", "grupo": "cardio"})
        self.assertEqual(s, 422)

    # ----- treinos
    def test_cria_e_lista_treino_com_dias_da_semana(self):
        t = self._treino()
        self.assertEqual(t["dias_semana"], [1, 4])
        self.assertEqual(t["versao"], 1)
        self.assertEqual(t["blocos"][0]["itens"][0]["carga"], 20.5)
        _, _, l = self._c("a1", "GET", "/aluno/treinos")
        self.assertEqual(len(l["treinos"]), 1)

    def test_aluno_nao_ve_nem_altera_treino_de_outro(self):
        t = self._treino("a1")
        for metodo, caminho, corpo in (("GET", f"/aluno/treinos/{t['id']}", None),
                                      ("DELETE", f"/aluno/treinos/{t['id']}", None),
                                      ("POST", f"/aluno/treinos/{t['id']}/duplicar", None),
                                      ("PUT", f"/aluno/treinos/{t['id']}", {"nome": "x", "versao": 1})):
            s, _, _ = self._c("a2", metodo, caminho, corpo)
            self.assertEqual(s, 404, (metodo, caminho))
        _, _, l = self._c("b1", "GET", "/aluno/treinos")
        self.assertEqual(l["treinos"], [])

    def test_put_com_versao_antiga_da_409(self):
        t = self._treino()
        corpo = {"nome": "Novo nome", "versao": t["versao"], "blocos": [{"id": b["id"], "grupo": b["grupo"], "nome": b["nome"],
                 "itens": [{"id": i["id"], "ref": i["ref"]} for i in b["itens"]]} for b in t["blocos"]]}
        s, _, novo = self._c("a1", "PUT", f"/aluno/treinos/{t['id']}", corpo)
        self.assertEqual((s, novo["versao"], novo["nome"]), (200, 2, "Novo nome"))
        s, _, c = self._c("a1", "PUT", f"/aluno/treinos/{t['id']}", corpo)
        self.assertEqual((s, c["detail"]), (409, "versao_desatualizada"))

    def test_put_edita_remove_e_reordena_blocos_e_itens(self):
        t = self._treino()
        b1, b2 = t["blocos"]
        corpo = {"nome": "A", "versao": 1, "dias_semana": [2], "blocos": [
            {"id": b2["id"], "grupo": "triceps", "nome": "Tríceps", "itens": [
                {"id": b2["itens"][0]["id"], "ref": "c:bench_dips", "series": 5, "reps": "12"},
                {"ref": "c:triceps_pushdown"}]}]}
        s, _, n = self._c("a1", "PUT", f"/aluno/treinos/{t['id']}", corpo)
        self.assertEqual(s, 200, n)
        self.assertEqual(len(n["blocos"]), 1)
        self.assertEqual(n["blocos"][0]["id"], b2["id"])
        self.assertEqual([i["series"] for i in n["blocos"][0]["itens"]], [5, 3])
        self.assertEqual(n["dias_semana"], [2])

    def test_put_com_id_de_bloco_de_outro_treino_e_rejeitado(self):
        t1 = self._treino("a1")
        t2 = self._treino("a2")
        corpo = {"nome": "A", "versao": 1, "blocos": [{"id": t2["blocos"][0]["id"], "grupo": "peito", "nome": "P", "itens": []}]}
        s, _, c = self._c("a1", "PUT", f"/aluno/treinos/{t1['id']}", corpo)
        self.assertEqual((s, c["detail"]), (422, "bloco_invalido"))

    def test_validacoes_de_entrada(self):
        casos = [
            ({"nome": "", "blocos": []}, 422),
            ({"nome": "X", "dias_semana": [7]}, 422),
            ({"nome": "X", "dias_semana": [1, 1]}, 422),
            ({"nome": "X", "blocos": [{"grupo": "pescoco", "nome": "P", "itens": []}]}, 422),
            ({"nome": "X", "blocos": [{"grupo": "peito", "nome": "P", "itens": [{"ref": "c:pushups", "series": 0}]}]}, 422),
            ({"nome": "X", "blocos": [{"grupo": "peito", "nome": "P", "itens": [{"ref": "c:pushups", "carga": 5000}]}]}, 422),
            ({"nome": "X", "blocos": [{"grupo": "peito", "nome": "P", "itens": [{}]}]}, 422),
            ({"nome": "X", "blocos": [{"grupo": "peito", "nome": "P", "itens": [{"ref": "c:pushups", "nome_livre": "x"}]}]}, 422),
            ({"nome": "X", "blocos": [{"grupo": "peito", "nome": "P", "itens": [{"ref": "c:nao_existe"}]}]}, 422),
            ({"nome": "X", "blocos": [{"grupo": "peito", "nome": "P", "itens": []}] * 13}, 422),
        ]
        for corpo, esperado in casos:
            s, _, _ = self._c("a1", "POST", "/aluno/treinos", corpo)
            self.assertEqual(s, esperado, corpo)

    def test_bloco_livre_com_nome_livre(self):
        s, _, c = self._c("a1", "POST", "/aluno/treinos", {"nome": "Cardio", "blocos": [
            {"grupo": "cardio", "nome": "Cardio", "itens": [{"nome_livre": "Esteira", "tempo": True, "reps": "900", "series": 1}]}]})
        self.assertEqual(s, 201)
        self.assertEqual(c["blocos"][0]["itens"][0]["nome"], "Esteira")
        self.assertIsNone(c["blocos"][0]["itens"][0]["ref"])

    def test_duplicar_cria_copia_independente(self):
        t = self._treino()
        s, _, copia = self._c("a1", "POST", f"/aluno/treinos/{t['id']}/duplicar")
        self.assertEqual(s, 201)
        self.assertNotEqual(copia["id"], t["id"])
        self.assertEqual(copia["nome"], "Peito e tríceps (cópia)")
        self.assertEqual(copia["dias_semana"], [])
        self.assertNotEqual(copia["blocos"][0]["id"], t["blocos"][0]["id"])
        self.assertEqual(len(copia["blocos"]), 2)

    def test_apagar_treino(self):
        t = self._treino()
        s, _, _ = self._c("a1", "DELETE", f"/aluno/treinos/{t['id']}")
        self.assertEqual(s, 204)
        _, _, l = self._c("a1", "GET", "/aluno/treinos")
        self.assertEqual(l["treinos"], [])

    def test_mover_bloco_so_troca_o_treino(self):
        t1 = self._treino()
        t2 = self._treino(nome="Costas")
        bloco = t1["blocos"][1]
        s, _, destino = self._c("a1", "POST", f"/aluno/treinos/blocos/{bloco['id']}/mover", {"treino_id": t2["id"]})
        self.assertEqual(s, 200, destino)
        self.assertIn(bloco["id"], [b["id"] for b in destino["blocos"]])
        _, _, origem = self._c("a1", "GET", f"/aluno/treinos/{t1['id']}")
        self.assertEqual(len(origem["blocos"]), 1)
        self.assertEqual(destino["blocos"][-1]["itens"][0]["ref"], "c:bench_dips")

    def test_mover_bloco_para_treino_de_outro_aluno_falha(self):
        t1 = self._treino("a1")
        t2 = self._treino("a2")
        s, _, _ = self._c("a1", "POST", f"/aluno/treinos/blocos/{t1['blocos'][0]['id']}/mover", {"treino_id": t2["id"]})
        self.assertEqual(s, 404)
        s, _, _ = self._c("a2", "POST", f"/aluno/treinos/blocos/{t1['blocos'][0]['id']}/mover", {"treino_id": t2["id"]})
        self.assertEqual(s, 404)

    def test_reordenar_exige_todos_os_treinos(self):
        a = self._treino(nome="A")
        b = self._treino(nome="B")
        s, _, c = self._c("a1", "PUT", "/aluno/treinos/ordem", {"ids": [b["id"], a["id"]]})
        self.assertEqual(s, 200)
        self.assertEqual([t["nome"] for t in c["treinos"]], ["B", "A"])
        s, _, _ = self._c("a1", "PUT", "/aluno/treinos/ordem", {"ids": [b["id"]]})
        self.assertEqual(s, 422)

    def test_limite_de_treinos(self):
        for i in range(aluno_treinos.MAX_TREINOS):
            s, _, _ = self._c("a1", "POST", "/aluno/treinos", {"nome": f"T{i}"})
            self.assertEqual(s, 201)
        s, _, c = self._c("a1", "POST", "/aluno/treinos", {"nome": "extra"})
        self.assertEqual((s, c["detail"]), (422, "limite_de_treinos"))

    # ----- modelos
    def test_lista_modelos_e_copia_sem_alterar_o_original(self):
        s, _, m = self._c("a1", "GET", "/aluno/modelos")
        self.assertGreaterEqual(len(m["modelos"]), 20)
        abc = next(x for x in m["modelos"] if x["nome"] == "ABC clássico")
        antes = self.conn.execute("SELECT conteudo FROM treinos_modelo WHERE id = %s", (abc["id"],)).fetchone()["conteudo"]
        s, _, c = self._c("a1", "POST", f"/aluno/modelos/{abc['id']}/copiar")
        self.assertEqual(s, 201)
        self.assertEqual(len(c["treinos"]), 3)
        self.assertEqual(c["treinos"][0]["modelo_origem_id"], abc["id"])
        # editar a cópia não muda o modelo
        t = c["treinos"][0]
        self._c("a1", "PUT", f"/aluno/treinos/{t['id']}", {"nome": "Mudei", "versao": 1, "blocos": []})
        depois = self.conn.execute("SELECT conteudo FROM treinos_modelo WHERE id = %s", (abc["id"],)).fetchone()["conteudo"]
        self.assertEqual(antes, depois)

    def test_todos_os_modelos_podem_ser_copiados(self):
        _, _, m = self._c("a1", "GET", "/aluno/modelos")
        for mod in m["modelos"]:
            self._c("a1", "DELETE", "/aluno/treinos/0") if False else None
            self.conn.execute("DELETE FROM treinos WHERE aluno_id = %s", (self.a1,))
            self.conn.commit()
            s, _, c = self._c("a1", "POST", f"/aluno/modelos/{mod['id']}/copiar")
            self.assertEqual(s, 201, mod["nome"])
            self.assertEqual(len(c["treinos"]), mod["dias"])

    def test_modelo_inexistente(self):
        s, _, _ = self._c("a1", "POST", "/aluno/modelos/9999/copiar")
        self.assertEqual(s, 404)


if __name__ == "__main__":
    unittest.main()
