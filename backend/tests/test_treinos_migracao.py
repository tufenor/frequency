import unittest

from backend.tests import _path  # noqa: F401
from backend.tests.pg_temp import TempPostgres
from backend.tests import _aluno_fixtures as fx

_pg = None
GRUPOS = ["peito", "costas", "ombros", "biceps", "triceps", "antebraco", "abdomen", "lombar",
          "quadriceps", "posteriores", "gluteos", "panturrilhas"]


def setUpModule():
    global _pg
    _pg = TempPostgres().start()


def tearDownModule():
    _pg.stop()


class MigracaoTreinosTests(unittest.TestCase):
    def setUp(self):
        self.conn = fx.conectar(_pg.dsn)

    def tearDown(self):
        self.conn.close()

    def test_catalogo_tem_no_minimo_12_por_grupo(self):
        linhas = self.conn.execute("SELECT grupo, count(*) AS n FROM exercicios_catalogo GROUP BY grupo").fetchall()
        por_grupo = {l["grupo"]: l["n"] for l in linhas}
        self.assertEqual(sorted(por_grupo), sorted(GRUPOS))
        for g in GRUPOS:
            self.assertGreaterEqual(por_grupo[g], 12, g)

    def test_modelos_prontos_sao_20_ou_mais(self):
        n = self.conn.execute("SELECT count(*) AS n FROM treinos_modelo").fetchone()["n"]
        self.assertGreaterEqual(n, 20)

    def test_modelos_so_citam_exercicios_do_catalogo(self):
        ids = {l["id"] for l in self.conn.execute("SELECT id FROM exercicios_catalogo").fetchall()}
        for m in self.conn.execute("SELECT nome, conteudo FROM treinos_modelo").fetchall():
            for dia in m["conteudo"]["dias"]:
                for b in dia["blocos"]:
                    for e in b["exercicios"]:
                        self.assertIn(e, ids, m["nome"])

    def test_item_exige_exatamente_uma_referencia(self):
        aid = fx.criar_academia(self.conn, nome="M1")
        al = fx.criar_aluno(self.conn, aid, email="m1@gmail.com", documento="m1")
        t = self.conn.execute("INSERT INTO treinos (aluno_id, nome) VALUES (%s,'T') RETURNING id", (al,)).fetchone()["id"]
        b = self.conn.execute("INSERT INTO treino_blocos (treino_id, grupo, nome) VALUES (%s,'peito','Peito') RETURNING id", (t,)).fetchone()["id"]
        self.conn.commit()
        import psycopg
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.conn.execute("INSERT INTO treino_itens (bloco_id, series, reps) VALUES (%s,3,'10')", (b,))
        self.conn.rollback()
        self.conn.execute("INSERT INTO treino_itens (bloco_id, catalogo_id, series, reps) VALUES (%s,'pushups',3,'10')", (b,))
        self.conn.commit()

    def test_exercicio_custom_exige_escopo_coerente(self):
        aid = fx.criar_academia(self.conn, nome="M2")
        import psycopg
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.conn.execute("INSERT INTO exercicios_custom (escopo, academia_id, nome, grupo) VALUES ('aluno',%s,'X','peito')", (aid,))
        self.conn.rollback()
