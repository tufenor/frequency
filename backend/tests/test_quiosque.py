import base64
import unittest
from datetime import datetime, timedelta, timezone

from backend.tests import _path  # noqa: F401
from backend.tests.pg_temp import TempPostgres
from backend.tests import _aluno_fixtures as fx
from backend.tests._asgi import chamar
import aluno_auth
import quiosque
import seguranca

_pg = None


def setUpModule():
    global _pg
    _pg = TempPostgres().start()


def tearDownModule():
    _pg.stop()


def _ok(conn, academia_id):
    return True


class _FaceError(Exception):
    pass


def foto(rotulo: str) -> str:
    return base64.b64encode(rotulo.encode()).decode()


def motor_falso():
    def emb(conteudo):
        if conteudo == b"sem-rosto":
            raise _FaceError("rosto_nao_detectado")
        return conteudo

    def sim(template, sonda):
        rotulo = template.rstrip(b"\0")
        if rotulo == sonda:
            return 0.9
        if rotulo.split(b"~")[0] == sonda.split(b"~")[0]:
            return 0.88  # gêmeo: segundo lugar quase igual → ambíguo
        return 0.1
    return {"embedding": emb, "similarity": sim, "modelo": "teste", "FaceError": _FaceError}


class QuiosqueTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        self.conn = fx.conectar(_pg.dsn)
        self.conn.execute("TRUNCATE quiosque_tickets, aluno_qr_quiosque, quiosques, aluno_series_registradas, treinos, aluno_codigos, "
                          "biometrias_faciais, aluno_sessoes, aluno_credenciais, alunos, academia_recursos, academias RESTART IDENTITY CASCADE")
        self.conn.commit()
        self.aid = fx.criar_academia(self.conn)
        self.outra = fx.criar_academia(self.conn, nome="Outra")
        for a in (self.aid, self.outra):
            self.conn.execute("INSERT INTO academia_recursos (academia_id, recurso, ligado) VALUES (%s,'quiosque',TRUE)", (a,))
        self.ana = fx.criar_aluno(self.conn, self.aid, email="ana@gmail.com", nome="Ana Souza", documento="d1")
        self.bia = fx.criar_aluno(self.conn, self.aid, email="bia@gmail.com", nome="Bia Lima", documento="d2")
        self.inativo = fx.criar_aluno(self.conn, self.aid, email="in@gmail.com", nome="Inativo", status="inativo", documento="d3")
        self.de_fora = fx.criar_aluno(self.conn, self.outra, email="fora@gmail.com", nome="Fora", documento="d4")
        for aluno, acad, rot in ((self.ana, self.aid, "ana"), (self.bia, self.aid, "bia"), (self.inativo, self.aid, "in"), (self.de_fora, self.outra, "fora")):
            self.conn.execute(
                "INSERT INTO biometrias_faciais (academia_id, aluno_id, id_biometria, template, modelo, amostras, consentimento_em) "
                "VALUES (%s,%s,%s,%s,'teste',3,now())", (acad, aluno, aluno + 100, rot.encode().ljust(512, b"\0")))
        self.conn.commit()
        self.dono = {"id": 1, "academia_id": self.aid, "papel": "dono", "nome": "D"}
        self.app = FastAPI()
        self.app.include_router(quiosque.router)
        self.app.dependency_overrides[aluno_auth.conexao] = lambda: self.conn
        self.app.dependency_overrides[seguranca.somente_dono] = lambda: self.dono
        aluno_auth.ASSINATURA_OK = _ok
        aluno_auth._limitador = None
        self._motor = quiosque.MOTOR
        quiosque.MOTOR = motor_falso
        self.token = quiosque.criar_quiosque(self.conn, self.aid, "Recepção")["token"]
        self.token_fora = quiosque.criar_quiosque(self.conn, self.outra, "Outro")["token"]

    def tearDown(self):
        quiosque.MOTOR = self._motor
        aluno_auth.ASSINATURA_OK = aluno_auth._assinatura_em_dia
        aluno_auth._limitador = None
        self.conn.close()

    def _k(self, metodo, caminho, corpo=None, token=None, ticket=None):
        h = {"X-Quiosque-Token": token or self.token}
        if ticket:
            h["X-Quiosque-Ticket"] = ticket
        return chamar(self.app, metodo, caminho, corpo, h)

    def _ticket(self, quem="ana"):
        s, _, c = self._k("POST", "/quiosque/identificar", {"foto_base64": foto(quem)})
        self.assertEqual(s, 200, c)
        return c

    # ----- identificação
    def test_reconhece_e_emite_ticket_com_primeiro_nome(self):
        c = self._ticket("ana")
        self.assertTrue(c["identificado"] and c["liberado"])
        self.assertEqual(c["nome"], "Ana")
        self.assertTrue(c["ticket"].startswith("fqt_"))
        self.assertNotIn("foto", str(c))

    def test_rosto_ambiguo_entre_dois_alunos_nao_identifica(self):
        self.conn.execute("DELETE FROM biometrias_faciais WHERE aluno_id = %s", (self.bia,))
        self.conn.execute(
            "INSERT INTO biometrias_faciais (academia_id, aluno_id, id_biometria, template, modelo, amostras, consentimento_em) "
            "VALUES (%s,%s,%s,%s,'teste',3,now())", (self.aid, self.bia, 999, b"ana~gemea".ljust(512, b"\0")))
        self.conn.commit()
        c = self._ticket("ana")
        self.assertEqual((c["identificado"], c["ticket"]), (False, None))

    def test_rosto_desconhecido_nao_emite_ticket(self):
        c = self._ticket("estranho")
        self.assertEqual((c["identificado"], c["liberado"], c["ticket"]), (False, False, None))

    def test_aluno_inativo_e_reconhecido_mas_nao_liberado(self):
        c = self._ticket("in")
        self.assertEqual((c["identificado"], c["liberado"], c["motivo"], c["ticket"]), (True, False, "aluno_inativo", None))

    def test_rosto_de_outra_academia_nao_identifica(self):
        c = self._ticket("fora")
        self.assertFalse(c["identificado"])

    def test_foto_invalida_grande_e_sem_rosto(self):
        self.assertEqual(self._k("POST", "/quiosque/identificar", {"foto_base64": "@@@@@@@@@@@@"})[0], 400)
        grande = base64.b64encode(b"x" * 700_001).decode()
        self.assertEqual(self._k("POST", "/quiosque/identificar", {"foto_base64": grande})[0], 413)
        s, _, c = self._k("POST", "/quiosque/identificar", {"foto_base64": foto("sem-rosto")})
        self.assertEqual((s, c["detail"]), (422, "rosto_nao_detectado"))

    def test_nenhuma_imagem_fica_guardada(self):
        self._ticket("ana")
        cols = [r["column_name"] for r in self.conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name IN ('quiosque_tickets','quiosques','aluno_qr_quiosque')").fetchall()]
        self.assertFalse([c for c in cols if "foto" in c or "imagem" in c])

    # ----- autenticação do aparelho
    def test_exige_token_do_quiosque(self):
        self.assertEqual(chamar(self.app, "POST", "/quiosque/identificar", {"foto_base64": foto("ana")})[0], 401)
        self.assertEqual(self._k("POST", "/quiosque/identificar", {"foto_base64": foto("ana")}, token="fq_errado")[0], 401)

    def test_recurso_desligado_ou_assinatura_bloqueada_barra_o_quiosque(self):
        self.conn.execute("UPDATE academia_recursos SET ligado = FALSE WHERE academia_id = %s", (self.aid,))
        self.conn.commit()
        s, _, c = self._k("POST", "/quiosque/identificar", {"foto_base64": foto("ana")})
        self.assertEqual((s, c["detail"]), (403, "quiosque_indisponivel"))
        self.conn.execute("UPDATE academia_recursos SET ligado = TRUE WHERE academia_id = %s", (self.aid,))
        self.conn.commit()
        aluno_auth.ASSINATURA_OK = lambda conn, a: False
        self.assertEqual(self._k("POST", "/quiosque/identificar", {"foto_base64": foto("ana")})[0], 403)

    def test_quiosque_revogado_para_de_funcionar_e_derruba_tickets(self):
        t = self._ticket("ana")["ticket"]
        qid = self.conn.execute("SELECT id FROM quiosques WHERE academia_id = %s", (self.aid,)).fetchone()["id"]
        self.assertEqual(chamar(self.app, "DELETE", f"/academia/quiosques/{qid}")[0], 204)
        self.assertEqual(self._k("GET", "/quiosque/treino-do-dia", ticket=t)[0], 401)

    # ----- ticket
    def test_treino_do_dia_com_ultimas_cargas(self):
        self.conn.execute("INSERT INTO treinos (aluno_id, nome, dias_semana) VALUES (%s,'Peito',ARRAY[1])", (self.ana,))
        tid = self.conn.execute("SELECT id FROM treinos").fetchone()["id"]
        self.conn.execute("INSERT INTO treino_blocos (treino_id, grupo, nome, ordem) VALUES (%s,'peito','Peito',0)", (tid,))
        bid = self.conn.execute("SELECT id FROM treino_blocos").fetchone()["id"]
        self.conn.execute("INSERT INTO treino_itens (bloco_id, catalogo_id, series, reps, descanso_s, ordem) VALUES (%s,'pushups',3,'10',60,0)", (bid,))
        self.conn.execute("INSERT INTO aluno_series_registradas (aluno_id, client_id, registrada_em, exercicio_ref, exercicio_nome, grupo, serie_numero, carga, reps) "
                          "VALUES (%s,'cid-00000001',now() - interval '2 days','c:pushups','Flexão','peito',1,25,10)", (self.ana,))
        self.conn.commit()
        t = self._ticket("ana")["ticket"]
        s, _, c = self._k("GET", "/quiosque/treino-do-dia?dia=1", ticket=t)
        self.assertEqual(s, 200)
        self.assertEqual(c["aluno"], {"nome": "Ana"})
        self.assertEqual([x["nome"] for x in c["treinos"]], ["Peito"])
        self.assertEqual(c["ultimas_cargas"]["c:pushups"]["carga"], 25)
        s, _, c2 = self._k("GET", "/quiosque/treino-do-dia?dia=3", ticket=t)
        self.assertEqual(c2["treinos"], [])
        self.assertEqual([x["nome"] for x in c2["outros"]], ["Peito"])
        self.assertEqual(self._k("GET", "/quiosque/treino-do-dia?dia=9", ticket=t)[0], 422)

    def test_resposta_nao_traz_dados_sensiveis(self):
        t = self._ticket("ana")["ticket"]
        _, _, c = self._k("GET", "/quiosque/treino-do-dia", ticket=t)
        texto = str(c).lower()
        for proibido in ("email", "ana@gmail", "documento", "d1", "souza", "telefone"):
            self.assertNotIn(proibido, texto)

    def test_ticket_expirado_nao_vale(self):
        t = self._ticket("ana")["ticket"]
        self.conn.execute("UPDATE quiosque_tickets SET expira_em = now() - interval '1 second'")
        self.conn.commit()
        s, _, c = self._k("GET", "/quiosque/treino-do-dia", ticket=t)
        self.assertEqual((s, c["detail"]), (401, "ticket_invalido"))

    def test_ticket_de_outro_quiosque_ou_academia_nao_vale(self):
        t = self._ticket("ana")["ticket"]
        self.assertEqual(self._k("GET", "/quiosque/treino-do-dia", ticket=t, token=self.token_fora)[0], 401)
        self.assertEqual(self._k("GET", "/quiosque/treino-do-dia", ticket="fqt_inventado")[0], 401)
        self.assertEqual(self._k("GET", "/quiosque/treino-do-dia")[0], 401)

    def test_ticket_nao_funciona_como_token_de_aluno(self):
        from fastapi import FastAPI
        import aluno_treinos
        app = FastAPI()
        app.include_router(aluno_treinos.router)
        app.dependency_overrides[aluno_auth.conexao] = lambda: self.conn
        t = self._ticket("ana")["ticket"]
        self.assertEqual(chamar(app, "GET", "/aluno/treinos", None, {"Authorization": "Bearer " + t})[0], 401)

    def test_encerrar_invalida_o_ticket(self):
        t = self._ticket("ana")["ticket"]
        self.assertEqual(self._k("POST", "/quiosque/encerrar", ticket=t)[0], 204)
        self.assertEqual(self._k("GET", "/quiosque/treino-do-dia", ticket=t)[0], 401)

    def test_limite_de_leituras_do_ticket(self):
        t = self._ticket("ana")["ticket"]
        self.conn.execute("UPDATE quiosque_tickets SET leituras = %s", (quiosque.MAX_LEITURAS_TICKET,))
        self.conn.commit()
        self.assertEqual(self._k("GET", "/quiosque/treino-do-dia", ticket=t)[0], 429)

    def test_aluno_desativado_depois_do_ticket_perde_acesso(self):
        t = self._ticket("ana")["ticket"]
        self.conn.execute("UPDATE alunos SET status = 'inativo' WHERE id = %s", (self.ana,))
        self.conn.commit()
        self.assertEqual(self._k("GET", "/quiosque/treino-do-dia", ticket=t)[0], 401)

    def test_ticket_so_le_nao_ha_rota_de_escrita(self):
        t = self._ticket("ana")["ticket"]
        for metodo, caminho in (("POST", "/quiosque/treino-do-dia"), ("PUT", "/quiosque/treino-do-dia"), ("DELETE", "/quiosque/treino-do-dia")):
            self.assertEqual(self._k(metodo, caminho, {} if metodo != "DELETE" else None, ticket=t)[0], 405)

    # ----- QR
    def _qr(self, quem=None):
        quem = quem or self.ana
        s = aluno_auth.criar_sessao(self.conn, {"id": quem, "nome": "x", "academia_id": self.aid})
        self.conn.commit()
        s, _, c = chamar(self.app, "POST", "/aluno/quiosque/qr", None, {"Authorization": "Bearer " + s["token"]})
        self.assertEqual(s, 200, c)
        return c["codigo"]

    def test_qr_serve_uma_vez(self):
        codigo = self._qr()
        s, _, c = self._k("POST", "/quiosque/qr", {"codigo": codigo})
        self.assertEqual((s, c["liberado"], c["nome"]), (200, True, "Ana"))
        s, _, c = self._k("POST", "/quiosque/qr", {"codigo": codigo})
        self.assertEqual((s, c["detail"]), (400, "qr_invalido"))

    def test_qr_expira(self):
        codigo = self._qr()
        self.conn.execute("UPDATE aluno_qr_quiosque SET expira_em = now() - interval '1 second'")
        self.conn.commit()
        self.assertEqual(self._k("POST", "/quiosque/qr", {"codigo": codigo})[0], 400)

    def test_qr_de_outra_academia_nao_vale(self):
        codigo = self._qr()
        self.assertEqual(self._k("POST", "/quiosque/qr", {"codigo": codigo}, token=self.token_fora)[0], 400)

    def test_novo_qr_invalida_o_anterior(self):
        a = self._qr()
        b = self._qr()
        self.assertEqual(self._k("POST", "/quiosque/qr", {"codigo": a})[0], 400)
        self.assertEqual(self._k("POST", "/quiosque/qr", {"codigo": b})[0], 200)

    def test_gerar_qr_exige_login_e_recurso(self):
        self.assertEqual(chamar(self.app, "POST", "/aluno/quiosque/qr")[0], 401)
        self.conn.execute("UPDATE academia_recursos SET ligado = FALSE WHERE academia_id = %s AND recurso = 'quiosque'", (self.aid,))
        self.conn.commit()
        s = aluno_auth.criar_sessao(self.conn, {"id": self.ana, "nome": "x", "academia_id": self.aid})
        self.conn.commit()
        self.assertEqual(chamar(self.app, "POST", "/aluno/quiosque/qr", None, {"Authorization": "Bearer " + s["token"]})[0], 403)

    def test_tentativas_ruins_de_qr_sao_limitadas(self):
        codigos = [self._k("POST", "/quiosque/qr", {"codigo": f"fqr_errado_{i}_xx"})[0] for i in range(12)]
        self.assertEqual(codigos[0], 400)
        self.assertIn(429, codigos)

    # ----- e-mail + código
    def test_email_codigo_gera_ticket_e_nao_revela_existencia(self):
        enviados = []
        aluno_auth.ENVIAR_EMAIL = lambda d, a, c: enviados.append((d, a, c)) or True
        try:
            s, _, c = self._k("POST", "/quiosque/email/pedir", {"email": "naoexiste@gmail.com"})
            self.assertEqual((s, c), (200, {"enviado": True}))
            self.assertEqual(enviados, [])
            s, _, c = self._k("POST", "/quiosque/email/pedir", {"email": "ana@gmail.com"})
            self.assertEqual(s, 200)
            self.assertEqual(len(enviados), 1)
            import re
            codigo = re.search(r"\b(\d{6})\b", enviados[0][2]).group(1)
            self.assertEqual(self._k("POST", "/quiosque/email/confirmar", {"email": "ana@gmail.com", "codigo": "000000"})[0], 400)
            s, _, c = self._k("POST", "/quiosque/email/confirmar", {"email": "ana@gmail.com", "codigo": codigo})
            self.assertEqual((s, c["liberado"], c["nome"]), (200, True, "Ana"))
        finally:
            aluno_auth.ENVIAR_EMAIL = aluno_auth.enviar_email_texto

    def test_email_de_aluno_de_outra_academia_nao_libera_neste_quiosque(self):
        enviados = []
        aluno_auth.ENVIAR_EMAIL = lambda d, a, c: enviados.append(c) or True
        try:
            self._k("POST", "/quiosque/email/pedir", {"email": "fora@gmail.com"}, token=self.token)
            codigo = None
            import re
            if enviados:
                codigo = re.search(r"\b(\d{6})\b", enviados[0]).group(1)
            s, _, c = self._k("POST", "/quiosque/email/confirmar", {"email": "fora@gmail.com", "codigo": codigo or "123456"}, token=self.token)
            self.assertEqual(s, 400)
        finally:
            aluno_auth.ENVIAR_EMAIL = aluno_auth.enviar_email_texto

    # ----- painel
    def test_painel_cria_mostra_token_uma_vez_e_lista_sem_token(self):
        s, _, c = chamar(self.app, "POST", "/academia/quiosques", {"nome": "Tablet 2"})
        self.assertEqual(s, 201)
        self.assertTrue(c["token"].startswith("fq_"))
        _, _, l = chamar(self.app, "GET", "/academia/quiosques")
        self.assertTrue(l["recurso_ligado"])
        self.assertEqual(len(l["quiosques"]), 2)
        self.assertNotIn("token", str(l["quiosques"]))
        hashes = [r["token_hash"] for r in self.conn.execute("SELECT token_hash FROM quiosques").fetchall()]
        self.assertNotIn(c["token"], hashes)

    def test_painel_exige_recurso_e_respeita_limite(self):
        for i in range(quiosque.MAX_QUIOSQUES - 1):
            self.assertEqual(chamar(self.app, "POST", "/academia/quiosques", {"nome": f"T{i}x"})[0], 201)
        self.assertEqual(chamar(self.app, "POST", "/academia/quiosques", {"nome": "Demais"})[0], 409)
        self.conn.execute("UPDATE academia_recursos SET ligado = FALSE WHERE academia_id = %s", (self.aid,))
        self.conn.commit()
        self.assertEqual(chamar(self.app, "POST", "/academia/quiosques", {"nome": "Outro"})[0], 403)

    def test_painel_nao_revoga_quiosque_de_outra_academia(self):
        qid = self.conn.execute("SELECT id FROM quiosques WHERE academia_id = %s", (self.outra,)).fetchone()["id"]
        self.assertEqual(chamar(self.app, "DELETE", f"/academia/quiosques/{qid}")[0], 404)
        self.assertEqual(self._k("POST", "/quiosque/qr", {"codigo": "fqr_qualquer_coisa"}, token=self.token_fora)[0], 400)  # segue ativo


if __name__ == "__main__":
    unittest.main()
