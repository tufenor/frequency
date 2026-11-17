"""FÃ¡brica de dados de teste para o login do aluno. SÃ³ roda em banco descartÃ¡vel (â€¦_test)."""
import psycopg
from psycopg.rows import dict_row


def conectar(dsn: str):
    conn = psycopg.connect(dsn, row_factory=dict_row)
    base = conn.execute("SELECT current_database() AS d").fetchone()["d"]
    if not base.endswith("_test"):
        conn.close()
        raise RuntimeError("Fixtures de aluno sÃ³ rodam em banco descartÃ¡vel (nome terminando em _test).")
    return conn


def criar_academia(conn, nome="Academia Teste", pais="BR", ligar_login=True) -> int:
    aid = conn.execute("INSERT INTO academias (nome, pais) VALUES (%s, %s) RETURNING id", (nome, pais)).fetchone()["id"]
    if ligar_login:
        conn.execute("INSERT INTO academia_recursos (academia_id, recurso, ligado) VALUES (%s, 'app_aluno_login', TRUE)", (aid,))
    conn.commit()
    return aid


def criar_aluno(conn, academia_id, email="aluno@gmail.com", status="ativo", nome="Aluno Teste", documento=None) -> int:
    documento = documento or f"doc-{email}-{academia_id}-{status}"
    aid = conn.execute(
        "INSERT INTO alunos (academia_id, nome, documento, email, status) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (academia_id, nome, documento, email, status)).fetchone()["id"]
    conn.commit()
    return aid


def criar_aluno_demo(conn, academia_id, email="aluno.demo@example.test", senha="Demo.Pass.123", nome="Aluno DemonstraÃ§Ã£o") -> int:
    """Aluno de demonstraÃ§Ã£o com senha jÃ¡ definida. Hash gerado em tempo de execuÃ§Ã£o; nunca persistido em arquivo."""
    import aluno_auth
    from seguranca import gerar_hash
    aluno_id = criar_aluno(conn, academia_id, email=email, nome=nome)
    conn.execute(
        "INSERT INTO aluno_credenciais (aluno_id, senha_hash) VALUES (%s, %s)",
        (aluno_id, gerar_hash(senha)))
    conn.commit()
    return aluno_id

