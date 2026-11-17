"""Disposable local browser smoke server; never connects to the configured database."""

from __future__ import annotations

import hashlib
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend" / "dist"
TESTS = BACKEND / "tests"

os.environ["SECRET_KEY"] = "browser-smoke-only-secret-not-for-real-use-0123456789"
os.environ["FREQUENCY_SPOTIFY_COMMERCIAL_APPROVED"] = "false"
os.environ["FREQUENCY_FRONTEND_DIR"] = str(FRONTEND if (FRONTEND / "index.html").exists() else ROOT / "frontend" / "public")
sys.path.insert(0, str(TESTS))

import test_business_postgres as isolated  # noqa: E402


def seed():
    isolated.setUpModule()
    case = isolated.BusinessPostgresIntegrationTests()
    case.setUp()
    admin = case.create_user("admin@smoke.example.test", "admin_plataforma", password="Smoke.Admin.123")
    academy = case.create_academy("Academia Smoke Sintética", "Brasil")
    owner = case.create_user("dono@smoke.example.test", "dono", academy, password="Smoke.Owner.123")
    reception = case.create_user("recepcao@smoke.example.test", "recepcao", academy, password="Smoke.Reception.123")
    student_name = os.getenv("FREQUENCY_SMOKE_STUDENT_NAME", "Aluno Smoke").strip() or "Aluno Smoke"
    with isolated._test_connection() as conn:
        essential = conn.execute(
            "INSERT INTO planos_frequency (nome, valor, moeda, duracao_dias, nivel) "
            "VALUES ('Smoke Essencial', 100, 'BRL', 30, 'essencial') RETURNING id"
        ).fetchone()
        premium = conn.execute(
            "INSERT INTO planos_frequency (nome, valor, moeda, duracao_dias, nivel, cameras, youtube) "
            "VALUES ('Smoke Premium', 300, 'BRL', 30, 'premium', TRUE, TRUE) RETURNING id"
        ).fetchone()
        subscription = conn.execute(
            "INSERT INTO assinaturas_frequency (academia_id, plano_id, inicio, proximo_vencimento, criada_por) "
            "VALUES (%s, %s, CURRENT_DATE, CURRENT_DATE, %s) RETURNING id",
            (academy, premium["id"], admin["id"]),
        ).fetchone()
        conn.execute(
            "INSERT INTO faturas_frequency (academia_id, assinatura_id, referencia, periodo_inicio, "
            "periodo_fim, valor, moeda, vencimento, criada_por) "
            "VALUES (%s, %s, 'Smoke Premium', CURRENT_DATE, CURRENT_DATE + 29, 300, 'BRL', CURRENT_DATE, %s)",
            (academy, subscription["id"], admin["id"]),
        )
        plan = conn.execute(
            "INSERT INTO planos (academia_id, nome, valor, duracao_dias, moeda) "
            "VALUES (%s, 'Smoke Mensal', 50, 30, 'BRL') RETURNING id", (academy,)
        ).fetchone()
        student = conn.execute(
            "INSERT INTO alunos (academia_id, nome, documento, plano_id, id_biometria) "
            "VALUES (%s, %s, 'SMOKE-DOC', %s, 909090) RETURNING id",
            (academy, student_name, plan["id"]),
        ).fetchone()
        conn.execute(
            "INSERT INTO pagamentos (academia_id, aluno_id, valor, vencimento, status) "
            "VALUES (%s, %s, 50, CURRENT_DATE + 30, 'em_aberto')", (academy, student["id"])
        )
        conn.execute(
            "INSERT INTO presencas (academia_id, aluno_id, liberado, motivo) "
            "VALUES (%s, %s, TRUE, 'smoke_teste')", (academy, student["id"])
        )

    monitor_key = "monitor-smoke-local-key-001"
    reader_key = "reader-smoke-local-key-001"
    with isolated._test_connection() as conn:
        conn.execute(
            "UPDATE academias SET chave_monitor_hash = %s WHERE id = %s",
            (hashlib.sha256(monitor_key.encode()).hexdigest(), academy),
        )
        conn.execute(
            "INSERT INTO leitores (academia_id, nome, chave_hash) VALUES (%s, %s, %s)",
            (academy, "Leitor smoke sintético", hashlib.sha256(reader_key.encode()).hexdigest()),
        )
    return admin, academy, owner, reception, monitor_key, reader_key


def main():
    try:
        admin, academy, owner, reception, monitor_key, reader_key = seed()
        import uvicorn

        server = uvicorn.Server(uvicorn.Config(isolated.main.app, host="127.0.0.1", port=8765,
                                                log_level="warning", access_log=False))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 20
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.1)
        if not server.started:
            raise RuntimeError("Servidor descartável não iniciou")
        print("SMOKE_SERVER_READY http://127.0.0.1:8765/app", flush=True)
        print(f"ADMIN {admin['email']} / Smoke.Admin.123", flush=True)
        print(f"DONO {owner['email']} / Smoke.Owner.123", flush=True)
        print(f"RECEPCAO {reception['email']} / Smoke.Reception.123", flush=True)
        print(f"MONITOR_KEY {monitor_key}", flush=True)
        print(f"READER_KEY {reader_key}", flush=True)
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if "server" in locals():
            server.should_exit = True
            thread.join(timeout=10)
        isolated.tearDownModule()


if __name__ == "__main__":
    main()
