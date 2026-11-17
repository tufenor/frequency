import unittest
from datetime import datetime, timedelta, timezone

from backend.tests import _path  # noqa: F401
from backend.tests.pg_temp import TempPostgres
from backend.tests import _aluno_fixtures as fx
from backend.tests._asgi import chamar
import aluno_auth
import aluno_evolucao

_pg = None


def setUpModule():
    global _pg
    _pg = TempPostgres().start()


def tearDownModule():
    _pg.stop()


def _ok(conn, academia_id):
    return True


def serie(cid, **kw):
    base = {"client_id": cid, "registrada_em": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "exercicio_ref": "c:pushups", "exercicio_nome": "Flexão", "grupo": "peito", "serie_numero": 1,
            "carga": 20, "reps": 10, "concluida": True}
    base.update(kw)
    return base


class EvolucaoTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        self.conn = fx.conectar(_pg.dsn)
        self.conn.execute("TRUNCATE aluno_series_registradas, aluno_medidas, aluno_metas, aluno_consentimentos, presencas, "
                          "aluno_sessoes, aluno_credenciais, alunos, academia_recursos, academias RESTART IDENTITY CASCADE")
        self.conn.commit()
        self.aid = fx.criar_academia(self.conn)
        self.a1 = fx.criar_aluno(self.conn, self.aid, email="a1@gmail.com", documento="d1")
        self.a2 = fx.criar_aluno(self.conn, self.aid, email="a2@gmail.com", documento="d2")
        self.t = {}
        for nome, al in (("a1", self.a1), ("a2", self.a2)):
            s = aluno_auth.criar_sessao(self.conn, {"id": al, "nome": nome, "academia_id": self.aid})
            self.t[nome] = {"Authorization": "Bearer " + s["token"]}
        self.conn.commit()
        self.app = FastAPI()
        self.app.include_router(aluno_evolucao.router)
        self.app.dependency_overrides[aluno_auth.conexao] = lambda: self.conn
        aluno_auth.ASSINATURA_OK = _ok

    def tearDown(self):
        aluno_auth.ASSINATURA_OK = aluno_auth._assinatura_em_dia
        self.conn.close()

    def _c(self, quem, metodo, caminho, corpo=None):
        return chamar(self.app, metodo, caminho, corpo, self.t[quem])

    def test_exige_token(self):
        self.assertEqual(chamar(self.app, "POST", "/aluno/series", {"series": []})[0], 401)

    def test_client_id_repetido_nao_duplica(self):
        s, _, r = self._c("a1", "POST", "/aluno/series", {"series": [serie("cid-00000001"), serie("cid-00000002")]})
        self.assertEqual((s, r["novas"]), (200, 2))
        s, _, r = self._c("a1", "POST", "/aluno/series", {"series": [serie("cid-00000001"), serie("cid-00000003")]})
        self.assertEqual((r["novas"], r["confirmadas"]), (1, ["cid-00000001", "cid-00000003"]))
        _, _, l = self._c("a1", "GET", "/aluno/series")
        self.assertEqual(len(l["series"]), 3)

    def test_mesmo_client_id_em_alunos_diferentes_nao_colide(self):
        self._c("a1", "POST", "/aluno/series", {"series": [serie("cid-00000001")]})
        s, _, r = self._c("a2", "POST", "/aluno/series", {"series": [serie("cid-00000001", carga=99)]})
        self.assertEqual(r["novas"], 1)

    def test_serie_de_outro_aluno_nunca_aparece(self):
        self._c("a1", "POST", "/aluno/series", {"series": [serie("cid-00000001")]})
        _, _, l = self._c("a2", "GET", "/aluno/series")
        self.assertEqual(l["series"], [])
        _, _, e = self._c("a2", "GET", "/aluno/evolucao")
        self.assertEqual(e["semana"]["series"], 0)
        self.assertEqual(e["recordes"], [])

    def test_limites_422(self):
        for extra in ({"carga": 1001}, {"carga": -1}, {"reps": 501}, {"reps": -1}, {"serie_numero": 0},
                      {"client_id": "curto"}):
            s, _, _ = self._c("a1", "POST", "/aluno/series", {"series": [serie("cid-00000009", **extra)]})
            self.assertEqual(s, 422, extra)
        futuro = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        s, _, c = self._c("a1", "POST", "/aluno/series", {"series": [serie("cid-00000009", registrada_em=futuro)]})
        self.assertEqual((s, c["detail"]), (422, "data_no_futuro"))

    def test_lote_maior_que_200_413_e_nada_grava(self):
        s, _, c = self._c("a1", "POST", "/aluno/series", {"series": [serie(f"cid-{i:08d}") for i in range(201)]})
        self.assertEqual((s, c["detail"]), (413, "lote_grande_demais"))
        n = self.conn.execute("SELECT count(*) AS n FROM aluno_series_registradas").fetchone()["n"]
        self.assertEqual(n, 0)
        s, _, _ = self._c("a1", "POST", "/aluno/series", {"series": [serie(f"cid-{i:08d}") for i in range(200)]})
        self.assertEqual(s, 200)

    def test_apagar_serie_e_idempotente_e_isolado(self):
        self._c("a1", "POST", "/aluno/series", {"series": [serie("cid-00000001")]})
        self.assertEqual(self._c("a2", "DELETE", "/aluno/series/cid-00000001")[0], 204)  # outro aluno: nada acontece
        self.assertEqual(len(self._c("a1", "GET", "/aluno/series")[2]["series"]), 1)
        self.assertEqual(self._c("a1", "DELETE", "/aluno/series/cid-00000001")[0], 204)
        self.assertEqual(self._c("a1", "DELETE", "/aluno/series/cid-00000001")[0], 204)
        self.assertEqual(self._c("a1", "GET", "/aluno/series")[2]["series"], [])

    def test_medidas_upsert_listar_apagar_isolamento(self):
        s, _, m = self._c("a1", "POST", "/aluno/medidas", {"data": "2026-10-01", "tipo": "peso", "valor": 80.5})
        self.assertEqual(s, 201)
        s, _, m2 = self._c("a1", "POST", "/aluno/medidas", {"data": "2026-10-01", "tipo": "peso", "valor": 80.0})
        self.assertEqual(m2["id"], m["id"])
        _, _, l = self._c("a1", "GET", "/aluno/medidas?tipo=peso")
        self.assertEqual([x["valor"] for x in l["medidas"]], [80.0])
        self.assertEqual(self._c("a2", "DELETE", f"/aluno/medidas/{m['id']}")[0], 404)
        self.assertEqual(self._c("a2", "GET", "/aluno/medidas")[2]["medidas"], [])
        self.assertEqual(self._c("a1", "DELETE", f"/aluno/medidas/{m['id']}")[0], 204)

    def test_medida_invalida(self):
        for corpo in ({"data": "2026-10-01", "tipo": "bicho", "valor": 5},
                      {"data": "2026-10-01", "tipo": "peso", "valor": 0},
                      {"data": "2026-10-01", "tipo": "peso", "valor": 1000},
                      {"data": "2099-01-01", "tipo": "peso", "valor": 70}):
            self.assertEqual(self._c("a1", "POST", "/aluno/medidas", corpo)[0], 422, corpo)

    def test_meta_peso(self):
        self.assertEqual(self._c("a1", "PUT", "/aluno/meta-peso", {"peso_alvo": 75})[0], 200)
        self.assertEqual(self._c("a1", "GET", "/aluno/evolucao")[2]["peso_alvo"], 75)
        self.assertIsNone(self._c("a2", "GET", "/aluno/evolucao")[2]["peso_alvo"])
        self.assertEqual(self._c("a1", "PUT", "/aluno/meta-peso", {"peso_alvo": 5})[0], 422)
        self._c("a1", "PUT", "/aluno/meta-peso", {"peso_alvo": None})
        self.assertIsNone(self._c("a1", "GET", "/aluno/evolucao")[2]["peso_alvo"])

    def test_consentimento_comeca_desligado(self):
        self.assertFalse(self._c("a1", "GET", "/aluno/consentimento")[2]["compartilhar_com_academia"])
        self._c("a1", "PUT", "/aluno/consentimento", {"compartilhar_com_academia": True})
        self.assertTrue(self._c("a1", "GET", "/aluno/consentimento")[2]["compartilhar_com_academia"])
        self.assertFalse(self._c("a2", "GET", "/aluno/consentimento")[2]["compartilhar_com_academia"])

    def test_evolucao_resumo(self):
        self._c("a1", "POST", "/aluno/series", {"series": [
            serie("cid-00000001", carga=50, reps=8), serie("cid-00000002", carga=60, reps=5, serie_numero=2),
            serie("cid-00000003", carga=90, reps=1, serie_numero=3, concluida=False)]})
        self._c("a1", "POST", "/aluno/medidas", {"data": "2026-10-01", "tipo": "peso", "valor": 81})
        self.conn.execute("INSERT INTO presencas (academia_id, aluno_id, liberado) VALUES (%s,%s,TRUE)", (self.aid, self.a1))
        self.conn.commit()
        s, _, e = self._c("a1", "GET", "/aluno/evolucao")
        self.assertEqual(s, 200)
        self.assertEqual(e["recordes"][0]["carga"], 60)  # a série não concluída (90) não vale
        self.assertEqual(e["mapa_7_dias"], {"peito": 2})
        self.assertGreaterEqual(e["sequencia_semanas"], 1)
        self.assertEqual(e["peso"][-1]["valor"], 81)
        self.assertEqual(sum(e["pulso"]), 2)


if __name__ == "__main__":
    unittest.main()
