import unittest

import psycopg
from psycopg import errors

from backend.tests.pg_temp import MIGRATIONS, TempPostgres

_pg: TempPostgres | None = None


def setUpModule():
    global _pg
    _pg = TempPostgres().start()


def tearDownModule():
    if _pg is not None:
        _pg.stop()


def _conn():
    return psycopg.connect(_pg.dsn, autocommit=True)


class MigracoesAlunoTests(unittest.TestCase):
    def test_migracoes_043_a_045_aplicam_em_banco_descartavel(self):
        for nome in ("043_aluno_email.sql", "044_aluno_credenciais_sessoes.sql", "045_aluno_codigos.sql"):
            self.assertTrue((MIGRATIONS / nome).is_file(), nome)
        with _conn() as c:
            tabelas = {r[0] for r in c.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'")}
            self.assertTrue({"aluno_credenciais", "aluno_sessoes", "aluno_codigos"} <= tabelas)
            colunas = {r[0] for r in c.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='alunos' AND table_schema='public'")}
            self.assertIn("email", colunas)
            cols_cod = {r[0] for r in c.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name='aluno_codigos'")}
            self.assertTrue({"ticket_hash", "ticket_expira_em", "ticket_usado_em"} <= cols_cod)

    def test_email_unico_por_academia_entre_ativos(self):
        with _conn() as c:
            a1 = c.execute("INSERT INTO academias (nome) VALUES ('A1') RETURNING id").fetchone()[0]
            a2 = c.execute("INSERT INTO academias (nome) VALUES ('A2') RETURNING id").fetchone()[0]
            ins = ("INSERT INTO alunos (academia_id, nome, documento, email, status) "
                   "VALUES (%s, 'X', %s, %s, %s)")
            c.execute(ins, (a1, "d1", "aluno@gmail.com", "ativo"))
            with self.assertRaises(errors.UniqueViolation):
                c.execute(ins, (a1, "d2", "ALUNO@gmail.com", "ativo"))
            c.execute(ins, (a2, "d3", "aluno@gmail.com", "ativo"))
            c.execute(ins, (a1, "d4", "aluno@gmail.com", "inativo"))


if __name__ == "__main__":
    unittest.main()
