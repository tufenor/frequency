"""Apply Frequency SQL migrations once, safely, on a local installation.

The Windows installer used to run every ``backend/migrations/*.sql`` file on
each install. Most early migrations are not re-runnable, so reinstalling or
updating over an existing local database failed at ``001_initial_schema.sql``.

This helper keeps a small history table (``frequency_migracoes_aplicadas``):

* fresh database: every migration is applied in name order and recorded;
* existing database without history (installed by an older package): each
  migration whose schema objects are already complete is recorded as
  ``detectada`` without running it again; a migration with no objects is
  applied; a *partial* migration stops the process without changing data;
* migrations already recorded are skipped.

SQL files are executed by the bundled ``psql`` with ``ON_ERROR_STOP`` exactly as
before, so dump-specific statements and ``CREATE INDEX CONCURRENTLY`` keep
working. No migration is ever reverted or dropped.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import psycopg

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from verificar_migracoes import REQUIRED_OBJECTS, classify_migrations  # noqa: E402

HISTORY_TABLE = "frequency_migracoes_aplicadas"
COMPLETE = "todos os objetos esperados presentes"
EMPTY = "nenhum objeto esperado encontrado"

# Migrations that fail when executed a second time (verified on PostgreSQL 17
# by applying the whole folder twice). Only these are ever "detected" from the
# schema; every other migration is idempotent (IF NOT EXISTS, DROP ... IF
# EXISTS + ADD, ON CONFLICT) and is simply executed again, which also fixes
# weak fingerprints such as 033 re-creating a constraint name used by 019.
NOT_RERUNNABLE = frozenset({
    "001_initial_schema.sql", "002_tenant_integrity.sql", "003_sync_outbox.sql",
    "004_qr_cobranca_academia.sql", "005_idioma_moeda.sql", "006_foto_alunos.sql",
    "007_tela_aluno.sql", "008_cobranca_frequency.sql", "009_recursos_premium.sql",
    "010_localizacao_academia.sql", "011_biometria_facial.sql", "012_origem_acesso.sql",
    "013_youtube_premium.sql", "015_pagamentos_online.sql",
    "020_precos_publicos_frequency.sql", "021_hardware_frequency.sql",
    "022_monitores_eventos_individuais.sql", "023_sessoes_telas_acesso.sql",
    "024_relogio_local.sql", "027_bairro_aluno.sql",
    "041_reservas_aulas_areas.sql", "042_vinculo_frequency_local.sql",
})


class MigrationError(RuntimeError):
    """Raised when a migration cannot be applied safely."""


def _connect(args: argparse.Namespace) -> psycopg.Connection:
    return psycopg.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=os.getenv("PGPASSWORD") or None,
        autocommit=True,
    )


def schema_states(conn: psycopg.Connection) -> dict[str, str]:
    relations = conn.execute(
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_schema = 'public'"
    ).fetchall()
    columns = conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public'"
    ).fetchall()
    constraints = conn.execute(
        "SELECT conname FROM pg_constraint WHERE connamespace = 'public'::regnamespace"
    ).fetchall()
    tables = {name for name, kind in relations if kind == "BASE TABLE"}
    views = {name for name, kind in relations if kind == "VIEW"}
    column_names = {f"{table}.{column}" for table, column in columns}
    constraint_names = {row[0] for row in constraints}
    return classify_migrations(tables, views, column_names, constraint_names)


def ensure_history(conn: psycopg.Connection) -> set[str]:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS public.{HISTORY_TABLE} ("
        " nome text PRIMARY KEY,"
        " modo text NOT NULL CHECK (modo IN ('aplicada', 'detectada')),"
        " registrada_em timestamptz NOT NULL DEFAULT now())"
    )
    return {row[0] for row in conn.execute(f"SELECT nome FROM public.{HISTORY_TABLE}")}


def _record(conn: psycopg.Connection, name: str, mode: str) -> None:
    conn.execute(
        f"INSERT INTO public.{HISTORY_TABLE} (nome, modo) VALUES (%s, %s) "
        "ON CONFLICT (nome) DO NOTHING",
        (name, mode),
    )


def _run_psql(args: argparse.Namespace, sql_file: Path) -> None:
    command = [
        args.psql, "-h", args.host, "-p", str(args.port), "-U", args.user,
        "-d", args.dbname, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(sql_file),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        # psql errors describe schema objects only; they never contain row data.
        detail = (result.stderr or "").strip().splitlines()[-1:] or ["erro desconhecido"]
        raise MigrationError(f"{sql_file.name}: {detail[0]}")


def plan(
    files: list[str], recorded: set[str], states: dict[str, str], existing_schema: bool
) -> list[tuple[str, str]]:
    """Return (name, action) pairs: action is skip, detect, apply or partial."""
    steps = []
    for name in files:
        if name in recorded:
            steps.append((name, "skip"))
        elif not existing_schema:
            steps.append((name, "apply"))
        elif name in NOT_RERUNNABLE and states.get(name) == COMPLETE:
            steps.append((name, "detect"))
        elif name in NOT_RERUNNABLE and states.get(name) != EMPTY:
            # Partial, or a non-rerunnable file without a fingerprint.
            steps.append((name, "partial"))
        else:
            # No objects yet, or an idempotent data/index migration without a
            # structural fingerprint (IF NOT EXISTS / ON CONFLICT).
            steps.append((name, "apply"))
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--psql", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=55432)
    parser.add_argument("--user", default="frequency")
    parser.add_argument("--dbname", default="frequency_local")
    parser.add_argument("--migrations-dir", default=str(BACKEND_DIR / "migrations"))
    args = parser.parse_args(argv)

    files = sorted(path.name for path in Path(args.migrations_dir).glob("*.sql"))
    try:
        with _connect(args) as conn:
            existing_schema = conn.execute(
                "SELECT to_regclass('public.academias') IS NOT NULL"
            ).fetchone()[0]
            recorded = ensure_history(conn)
            states = schema_states(conn) if existing_schema and not recorded else {}
            steps = plan(files, recorded, states, existing_schema and not recorded)
            partial = [name for name, action in steps if action == "partial"]
            if partial:
                print(
                    "Migração parcial encontrada; nada foi alterado: " + ", ".join(partial),
                    file=sys.stderr,
                )
                return 3
            for name, action in steps:
                if action == "skip":
                    continue
                if action == "detect":
                    _record(conn, name, "detectada")
                    print(f"Já presente: {name}")
                    continue
                print(f"Aplicando {name}...")
                _run_psql(args, Path(args.migrations_dir) / name)
                _record(conn, name, "aplicada")
    except MigrationError as exc:
        print(f"A migração falhou: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error:
        print("Não foi possível abrir o banco local para aplicar migrações.", file=sys.stderr)
        return 2
    print("Banco local atualizado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
