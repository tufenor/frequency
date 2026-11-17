"""Business-flow integration tests isolated in a temporary PostgreSQL cluster."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "backend" / "migrations"
TEST_SECRET = "synthetic-postgres-integration-secret-not-for-use"
main = None
security = None
psycopg = None
dict_row = None
_MODULES_BEFORE_SETUP: set[str] = set()
_BACKEND_MODULES = (
    "main",
    "database",
    "seguranca",
    "cobranca_saas",
    "regionalizacao",
    "sincronizacao",
    "sync_protocol",
    "sync_receiver",
)
_ORIGINAL_ENV: dict[str, str | None] = {}
_ORIGINAL_GET_CONNECTION = None
_ORIGINAL_SECURITY_GET_CONNECTION = None
_TEMPORARY_DIRECTORY = None
_PG_BIN: Path | None = None
_PG_DATA: Path | None = None
_PG_LOG: Path | None = None
_PG_PORT: int | None = None
_PG_RUNNING = False
TEST_DSN: str | None = None


def _api_call(method: str, target: str, *, body: bytes = b"", headers=None):
    """Send one synthetic HTTP request through the real ASGI application."""
    parsed = urlsplit(target)
    request_headers = {
        key.lower(): value for key, value in (headers or {}).items()
    }
    request_headers.setdefault("host", "127.0.0.1:8000")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": parsed.path,
        "raw_path": parsed.path.encode("ascii"),
        "query_string": parsed.query.encode("ascii"),
        "headers": [
            (key.encode("ascii"), value.encode("latin-1"))
            for key, value in request_headers.items()
        ],
        "client": ("198.51.100.81", 1234),
        "server": ("127.0.0.1", 8000),
        "root_path": "",
        "state": {},
    }
    receive_messages = [
        {"type": "http.request", "body": body, "more_body": False}
    ]
    response_messages = []

    async def receive():
        if receive_messages:
            return receive_messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        response_messages.append(message)

    async def run_app():
        await main.app(scope, receive, send)

    asyncio.run(run_app())
    start = next(message for message in response_messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"")
        for message in response_messages
        if message["type"] == "http.response.body"
    )
    response_headers = {
        key.decode("ascii").lower(): value.decode("latin-1")
        for key, value in start.get("headers", [])
    }
    content_type = response_headers.get("content-type", "")
    if content_type.startswith("application/json"):
        return start["status"], response_headers, json.loads(response_body or b"null")
    return start["status"], response_headers, response_body


def _find_postgres_bin() -> Path | None:
    configured = os.environ.get("POSTGRES_BIN_DIR")
    candidates = [Path(configured)] if configured else []
    if os.name == "nt":
        candidates.extend(
            sorted(
                Path("C:/Program Files/PostgreSQL").glob("*/bin"),
                reverse=True,
            )
        )
    else:
        for name in ("initdb", "pg_ctl", "psql"):
            executable = shutil.which(name)
            if executable:
                candidates.append(Path(executable).parent)
                break

    for candidate in candidates:
        if all((candidate / f"{name}{'.exe' if os.name == 'nt' else ''}").is_file()
               for name in ("initdb", "pg_ctl", "psql")):
            return candidate
    return None


def _executable(name: str) -> str:
    assert _PG_BIN is not None
    return str(_PG_BIN / f"{name}{'.exe' if os.name == 'nt' else ''}")


def _run(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"Temporary PostgreSQL command failed ({result.returncode}): "
            f"{result.stdout}\n{result.stderr}"
        )
    return result


def _stop_postgres() -> None:
    global _PG_RUNNING
    if _PG_DATA is None or not _PG_DATA.exists():
        _PG_RUNNING = False
        return

    pid_file = _PG_DATA / "postmaster.pid"
    if not _PG_RUNNING and not pid_file.exists():
        return

    stopped = subprocess.run(
        [_executable("pg_ctl"), "-D", str(_PG_DATA), "-m", "fast", "-w", "stop"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if stopped.returncode:
        status = subprocess.run(
            [_executable("pg_ctl"), "-D", str(_PG_DATA), "status"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if status.returncode == 0:
            raise RuntimeError(
                "PostgreSQL temporário continua ativo; mantendo o diretório de dados."
            )
    _PG_RUNNING = False


def _cleanup_postgres() -> None:
    _stop_postgres()
    if _TEMPORARY_DIRECTORY is not None:
        _TEMPORARY_DIRECTORY.cleanup()


def _initialize_postgres() -> None:
    global _TEMPORARY_DIRECTORY, _PG_BIN, _PG_DATA, _PG_LOG, _PG_PORT, _PG_RUNNING, TEST_DSN

    _PG_BIN = _find_postgres_bin()
    if _PG_BIN is None:
        raise unittest.SkipTest(
            "PostgreSQL initdb, pg_ctl e psql não foram encontrados; "
            "configure POSTGRES_BIN_DIR para executar os testes de integração."
        )

    _TEMPORARY_DIRECTORY = tempfile.TemporaryDirectory(
        prefix="frequency_postgres_test_"
    )
    root = Path(_TEMPORARY_DIRECTORY.name)
    _PG_DATA = root / "data"
    _PG_LOG = root / "postgres.log"

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        _PG_PORT = listener.getsockname()[1]

    try:
        _run(
            [
                _executable("initdb"),
                "-D",
                str(_PG_DATA),
                "--username=frequency_test",
                "--encoding=UTF8",
                "--auth-local=trust",
                "--auth-host=trust",
                "--no-instructions",
                "--no-sync",
            ],
            timeout=120,
        )
        start_result = subprocess.run(
            [
                _executable("pg_ctl"),
                "-D",
                str(_PG_DATA),
                "-o",
                f"-h 127.0.0.1 -p {_PG_PORT}",
                "-l",
                str(_PG_LOG),
                "-w",
                "start",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
            check=False,
        )
        if start_result.returncode:
            log = (
                _PG_LOG.read_text(encoding="utf-8", errors="replace")
                if _PG_LOG.exists()
                else ""
            )
            raise RuntimeError(
                f"Could not start temporary PostgreSQL ({start_result.returncode}).\n{log}"
            )
        _PG_RUNNING = True

        base_connection = [
            _executable("psql"),
            "-h",
            "127.0.0.1",
            "-p",
            str(_PG_PORT),
            "-U",
            "frequency_test",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        _run(base_connection + ["-c", "CREATE DATABASE frequency_test"])

        database_connection = base_connection.copy()
        database_connection[database_connection.index("postgres")] = "frequency_test"
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            _run(database_connection + ["-f", str(migration)], timeout=60)

        TEST_DSN = (
            f"host=127.0.0.1 port={_PG_PORT} dbname=frequency_test "
            "user=frequency_test connect_timeout=3"
        )
    except Exception:
        _cleanup_postgres()
        raise


def _test_connection():
    assert psycopg is not None and dict_row is not None and TEST_DSN is not None
    return psycopg.connect(TEST_DSN, row_factory=dict_row)


def _restore_test_environment() -> None:
    for key, original_value in _ORIGINAL_ENV.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value


def setUpModule():
    global main, security, psycopg, dict_row, _MODULES_BEFORE_SETUP
    global _ORIGINAL_GET_CONNECTION, _ORIGINAL_SECURITY_GET_CONNECTION
    _MODULES_BEFORE_SETUP = set(sys.modules)
    _ORIGINAL_ENV.update(
        {
            key: os.environ.get(key)
            for key in (
                "SECRET_KEY",
                "SYNC_OUTBOX_ENABLED",
                "SYNC_MIRROR_READ_ONLY",
                "DB_HOST",
                "DB_PORT",
                "DB_NAME",
                "DB_USER",
                "DB_PASSWORD",
                "FREQUENCY_SPOTIFY_COMMERCIAL_APPROVED",
            )
        }
    )
    os.environ["SECRET_KEY"] = TEST_SECRET
    os.environ["SYNC_OUTBOX_ENABLED"] = "NO"
    os.environ["SYNC_MIRROR_READ_ONLY"] = "NO"
    os.environ["FREQUENCY_SPOTIFY_COMMERCIAL_APPROVED"] = "false"

    try:
        _initialize_postgres()
    except BaseException:
        _restore_test_environment()
        raise

    os.environ.update(
        {
            "DB_HOST": "127.0.0.1",
            "DB_PORT": str(_PG_PORT),
            "DB_NAME": "frequency_test",
            "DB_USER": "frequency_test",
            "DB_PASSWORD": "",
        }
    )

    original_load_dotenv = dotenv.load_dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
    backend_path = str(ROOT / "backend")
    inserted_backend_path = backend_path not in sys.path
    if inserted_backend_path:
        sys.path.insert(0, backend_path)
    try:
        import psycopg as psycopg_module
        from psycopg.rows import dict_row as dict_row_factory
        import main as main_module
        import seguranca as security_module

        psycopg = psycopg_module
        dict_row = dict_row_factory
        main = main_module
        security = security_module
    except Exception:
        _cleanup_postgres()
        _restore_test_environment()
        raise
    finally:
        dotenv.load_dotenv = original_load_dotenv
        for module_name in ("database", "seguranca"):
            module = sys.modules.get(module_name)
            if module is not None:
                module.load_dotenv = original_load_dotenv
        if inserted_backend_path:
            sys.path.remove(backend_path)

    _ORIGINAL_GET_CONNECTION = main.get_connection
    main.get_connection = _test_connection
    _ORIGINAL_SECURITY_GET_CONNECTION = security.get_connection
    security.get_connection = _test_connection


def tearDownModule():
    if main is not None and _ORIGINAL_GET_CONNECTION is not None:
        main.get_connection = _ORIGINAL_GET_CONNECTION
    if security is not None and _ORIGINAL_SECURITY_GET_CONNECTION is not None:
        security.get_connection = _ORIGINAL_SECURITY_GET_CONNECTION
    _cleanup_postgres()
    _restore_test_environment()
    for module_name in _BACKEND_MODULES:
        if module_name not in _MODULES_BEFORE_SETUP:
            sys.modules.pop(module_name, None)


class BusinessPostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.original_rate_limiter = main.login_rate_limiter
        main.login_rate_limiter = main.LoginRateLimiter(TEST_SECRET)
        with _test_connection() as conn:
            conn.execute(
                "TRUNCATE TABLE presencas, pagamentos, alunos, planos, "
                "leitores, usuarios, academias, planos_frequency RESTART IDENTITY CASCADE"
            )

    def tearDown(self):
        main.login_rate_limiter = self.original_rate_limiter

    def test_postgres_custom_dump_restores_schema_and_data(self):
        academy_name = "Academia Restore Teste"
        self.create_academy(academy_name, "Brasil")
        restore_database = "frequency_restore_test"
        admin_connection = [
            _executable("psql"),
            "-h", "127.0.0.1",
            "-p", str(_PG_PORT),
            "-U", "frequency_test",
            "-d", "postgres",
            "-v", "ON_ERROR_STOP=1",
        ]

        with tempfile.TemporaryDirectory(prefix="frequency-restore-") as temp_dir:
            dump_path = Path(temp_dir) / "frequency.dump"
            try:
                _run([
                    _executable("pg_dump"),
                    "-h", "127.0.0.1",
                    "-p", str(_PG_PORT),
                    "-U", "frequency_test",
                    "-d", "frequency_test",
                    "--format=custom",
                    "--file", str(dump_path),
                ])
                self.assertGreater(dump_path.stat().st_size, 0)

                _run(admin_connection + ["-c", f"CREATE DATABASE {restore_database}"])
                _run([
                    _executable("pg_restore"),
                    "-h", "127.0.0.1",
                    "-p", str(_PG_PORT),
                    "-U", "frequency_test",
                    "-d", restore_database,
                    "--exit-on-error",
                    str(dump_path),
                ])

                restored_dsn = (
                    f"host=127.0.0.1 port={_PG_PORT} dbname={restore_database} "
                    "user=frequency_test connect_timeout=3"
                )
                with psycopg.connect(restored_dsn, row_factory=dict_row) as conn:
                    restored = conn.execute(
                        "SELECT nome FROM academias WHERE nome = %s",
                        (academy_name,),
                    ).fetchone()
                    self.assertEqual(restored["nome"], academy_name)
                    table_count = conn.execute(
                        "SELECT count(*) AS total FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    ).fetchone()["total"]
                    self.assertGreater(table_count, 0)
            finally:
                _run(
                    admin_connection
                    + ["-c", f"DROP DATABASE IF EXISTS {restore_database} WITH (FORCE)"],
                )

    def test_initial_snapshot_applies_in_order_to_replica(self):
        from backend import criar_snapshot_sync
        from sync_protocol import SyncEvent
        from sync_receiver import receber_evento

        academy_id = self.create_academy("Academia Origem Sync", "Brasil")
        with _test_connection() as conn:
            plan = conn.execute(
                "INSERT INTO planos (academia_id, nome, valor, moeda, duracao_dias) "
                "VALUES (%s, 'Mensal', 99.90, 'BRL', 30) RETURNING id",
                (academy_id,),
            ).fetchone()
            student = conn.execute(
                "INSERT INTO alunos (academia_id, nome, documento, data_inicio, plano_id) "
                "VALUES (%s, 'Aluno Sync', 'SYNC-LOCAL', CURRENT_DATE, %s) RETURNING id",
                (academy_id, plan["id"]),
            ).fetchone()
            conn.execute(
                "INSERT INTO pagamentos "
                "(academia_id, aluno_id, valor, moeda, vencimento, status) "
                "VALUES (%s, %s, 99.90, 'BRL', CURRENT_DATE, 'em_aberto')",
                (academy_id, student["id"]),
            )
            conn.execute(
                "INSERT INTO presencas (academia_id, aluno_id, liberado, motivo) "
                "VALUES (%s, %s, true, 'acesso_liberado')",
                (academy_id, student["id"]),
            )

        previous_outbox = os.environ.get("SYNC_OUTBOX_ENABLED")
        os.environ["SYNC_OUTBOX_ENABLED"] = "YES"
        try:
            self.assertEqual(criar_snapshot_sync.enfileirar_snapshot(academy_id), 4)
        finally:
            if previous_outbox is None:
                os.environ.pop("SYNC_OUTBOX_ENABLED", None)
            else:
                os.environ["SYNC_OUTBOX_ENABLED"] = previous_outbox

        with _test_connection() as conn:
            source_id = conn.execute(
                "SELECT sync_id FROM academias WHERE id = %s", (academy_id,)
            ).fetchone()["sync_id"]
            rows = conn.execute(
                "SELECT event_id, academia_sync_id, revision, entity_type, "
                "entity_sync_id, operation, schema_version, payload "
                "FROM sync_outbox WHERE academia_sync_id = %s ORDER BY revision",
                (source_id,),
            ).fetchall()

        replica_database = "frequency_sync_replica_test"
        admin_connection = [
            _executable("psql"), "-h", "127.0.0.1", "-p", str(_PG_PORT),
            "-U", "frequency_test", "-d", "postgres", "-v", "ON_ERROR_STOP=1",
        ]
        try:
            _run(admin_connection + ["-c", f"CREATE DATABASE {replica_database}"])
            replica_cli = admin_connection.copy()
            replica_cli[replica_cli.index("postgres")] = replica_database
            for migration in sorted(MIGRATIONS.glob("*.sql")):
                _run(replica_cli + ["-f", str(migration)])

            replica_dsn = (
                f"host=127.0.0.1 port={_PG_PORT} dbname={replica_database} "
                "user=frequency_test connect_timeout=3"
            )
            events = [SyncEvent.model_validate(dict(row)) for row in rows]
            with psycopg.connect(replica_dsn, row_factory=dict_row) as replica:
                target_id = replica.execute(
                    "INSERT INTO academias (nome, pais) "
                    "VALUES ('Academia Réplica', 'Brasil') RETURNING id"
                ).fetchone()["id"]
                replica.commit()

                with self.assertRaises(main.HTTPException) as out_of_order:
                    with replica.transaction():
                        receber_evento(
                            replica,
                            academia_id=target_id,
                            source_academia_sync_id=source_id,
                            evento=events[1],
                        )
                self.assertEqual(out_of_order.exception.detail, "sync_revisao_fora_de_ordem")

                for event in events:
                    with replica.transaction():
                        self.assertFalse(receber_evento(
                            replica,
                            academia_id=target_id,
                            source_academia_sync_id=source_id,
                            evento=event,
                        ))

                with replica.transaction():
                    self.assertTrue(receber_evento(
                        replica,
                        academia_id=target_id,
                        source_academia_sync_id=source_id,
                        evento=events[-1],
                    ))

                counts = replica.execute(
                    "SELECT "
                    "(SELECT count(*) FROM planos WHERE academia_id = %s) AS planos, "
                    "(SELECT count(*) FROM alunos WHERE academia_id = %s) AS alunos, "
                    "(SELECT count(*) FROM pagamentos WHERE academia_id = %s) AS pagamentos, "
                    "(SELECT count(*) FROM presencas WHERE academia_id = %s) AS presencas",
                    (target_id, target_id, target_id, target_id),
                ).fetchone()
                self.assertEqual(dict(counts), {
                    "planos": 1, "alunos": 1, "pagamentos": 1, "presencas": 1,
                })
        finally:
            _run(
                admin_connection
                + ["-c", f"DROP DATABASE IF EXISTS {replica_database} WITH (FORCE)"],
            )

    def test_http_serves_application_and_monitor_from_selected_frontend_directory(self):
        original = main.PASTA_FRONTEND
        directories = [main.PASTA_FRONTEND_PUBLICA]
        if (main.PASTA_BACKEND.parent / "frontend" / "dist" / "index.html").is_file():
            directories.append(main.PASTA_BACKEND.parent / "frontend" / "dist")
        try:
            for directory in directories:
                main.PASTA_FRONTEND = directory
                for route, marker in (("/app", "Frequency"), ("/monitor", "monitor"),
                                      ("/cameras", "Câmeras"), ("/youtube", "YouTube")):
                    with self.subTest(directory=directory, route=route):
                        status, _headers, body = _api_call("GET", route)
                        self.assertEqual(status, 200)
                        self.assertIn(marker.lower().encode(), body.lower())
                status, headers, body = _api_call("GET", "/static/integracoes.mjs")
                self.assertEqual(status, 200)
                self.assertIn("javascript", headers.get("content-type", ""))
                self.assertIn(b"youtubeVideoId", body)
        finally:
            main.PASTA_FRONTEND = original

    def create_academy(self, name: str, country: str):
        with _test_connection() as conn:
            return conn.execute(
                "INSERT INTO academias (nome, pais) VALUES (%s, %s) RETURNING id",
                (name, country),
            ).fetchone()["id"]

    def owner(self, academy_id: int, country: str):
        language, currency = main.preferencias_iniciais_academia(country)
        return {
            "id": academy_id + 100,
            "academia_id": academy_id,
            "papel": "dono",
            "idioma": language,
            "moeda": currency,
        }

    def new_plan(self, owner, name="Mensal", value="50.00", duration=30):
        return main.criar_plano(
            main.NovoPlano(
                nome=name,
                valor=Decimal(value),
                duracao_dias=duration,
            ),
            dono=owner,
        )

    def new_student(self, owner, plan_id, document, biometric_id):
        return main.criar_aluno(
            main.NovoAluno(
                nome="Aluno sintético",
                documento=document,
                plano_id=plan_id,
                id_biometria=biometric_id,
            ),
            usuario=owner,
        )

    def test_student_limit_counts_only_active_students_of_subscribed_academy(self):
        admin_token = self.login_token(self.create_user("limit-admin@example.test", "admin_plataforma"))
        academy_id = self.create_academy("Academia limite sintética", "Brasil")
        status, _, plan = self.json_api("POST", "/admin/frequency/planos", token=admin_token,
            body={"nome": "Limite sintético", "valor": "40.00", "moeda": "BRL", "duracao_dias": 30,
                  "max_alunos": 1})
        self.assertEqual(status, 201, plan)
        status, _, subscription = self.json_api("POST", "/admin/frequency/assinaturas", token=admin_token,
            body={"academia_id": academy_id, "plano_id": plan["id"],
                  "vencimento": (date.today() + timedelta(days=30)).isoformat()})
        self.assertEqual(status, 201, subscription)
        owner = self.owner(academy_id, "Brasil")
        gym_plan = self.new_plan(owner)
        first = self.new_student(owner, gym_plan["id"], "LIM-001", 9101)
        with self.assertRaises(main.HTTPException) as blocked:
            self.new_student(owner, gym_plan["id"], "LIM-002", 9102)
        self.assertEqual(blocked.exception.status_code, 403)
        self.assertEqual(blocked.exception.detail, "limite_de_alunos_do_plano_atingido")
        with _test_connection() as conn:
            conn.execute("UPDATE alunos SET status = 'inativo' WHERE id = %s", (first["id"],))
        self.new_student(owner, gym_plan["id"], "LIM-003", 9103)
        with self.assertRaises(main.HTTPException) as reactivation:
            main.mudar_status_aluno(first["id"], main.StatusAluno(ativo=True), dono=owner)
        self.assertEqual(reactivation.exception.status_code, 403)

    def test_face_enrollment_generates_biometric_id_without_storing_samples(self):
        academy_id = self.create_academy("Academia facial sintética", "Brasil")
        owner = self.owner(academy_id, "Brasil")
        samples = [base64.b64encode(value).decode("ascii") for value in (b"one", b"two", b"three")]

        with self.assertRaises(main.HTTPException) as forbidden:
            main.criar_aluno(
                main.NovoAluno(
                    nome="Cadastro sem permissão",
                    documento="FACE-FORBIDDEN",
                    fotos_rosto_base64=samples,
                    consentimento_facial=True,
                ),
                usuario={**owner, "papel": "recepcao"},
            )
        self.assertEqual(forbidden.exception.status_code, 403)

        with patch.object(main, "enrollment_template", return_value=b"\x01" * 512), \
                patch.object(main.secrets, "randbelow", return_value=2345):
            created = main.criar_aluno(
                main.NovoAluno(
                    nome="Aluno Facial",
                    documento="FACE-SYNTHETIC-1",
                    fotos_rosto_base64=samples,
                    consentimento_facial=True,
                ),
                usuario=owner,
            )

        self.assertEqual(created["id_biometria"], 100002345)
        with _test_connection() as conn:
            stored = conn.execute(
                "SELECT b.id_biometria, b.modelo, b.amostras, octet_length(b.template) AS bytes, "
                "a.id_biometria AS aluno_biometria "
                "FROM biometrias_faciais b JOIN alunos a ON a.id = b.aluno_id "
                "WHERE b.aluno_id = %s AND b.academia_id = %s",
                (created["id"], academy_id),
            ).fetchone()
        self.assertEqual(stored["id_biometria"], 100002345)
        self.assertEqual(stored["aluno_biometria"], 100002345)
        self.assertEqual(stored["modelo"], main.MODEL_VERSION)
        self.assertEqual(stored["amostras"], 3)
        self.assertEqual(stored["bytes"], 512)

        with _test_connection() as conn:
            reader = conn.execute(
                "INSERT INTO leitores (academia_id, nome, chave_hash) "
                "VALUES (%s, 'Câmera facial', %s) RETURNING id, academia_id, nome",
                (academy_id, hashlib.sha256(b"face-reader-key").hexdigest()),
            ).fetchone()
            conn.execute(
                "UPDATE academias SET chave_monitor_hash = %s WHERE id = %s",
                (hashlib.sha256(b"face-monitor-key").hexdigest(), academy_id),
            )
        monitor_reader = main.origem_acesso_facial(
            chave_leitor=None,
            chave_monitor="face-monitor-key",
        )
        self.assertEqual(monitor_reader["id"], reader["id"])
        facial_request = main.PedidoAcessoFacial(
            foto_base64=base64.b64encode(b"probe").decode("ascii")
        )
        with patch.object(main, "embedding", return_value=object()), \
                patch.object(main, "similarity", return_value=0.82), \
                patch.object(main, "estado_assinatura_frequency", return_value={"bloqueada_frequency": False}):
            first = main.verificar_acesso_facial(facial_request, leitor=reader)
            repeated = main.verificar_acesso_facial(facial_request, leitor=reader)
        self.assertTrue(first["identificado"])
        self.assertFalse(first["repetido"])
        self.assertEqual(first["motivo"], "plano_nao_cadastrado")
        self.assertTrue(repeated["repetido"])
        with _test_connection() as conn:
            presence = conn.execute(
                "SELECT count(*) AS total, min(metodo_identificacao) AS metodo "
                "FROM presencas WHERE academia_id = %s AND aluno_id = %s",
                (academy_id, created["id"]),
            ).fetchone()
        self.assertEqual(presence["total"], 1)
        self.assertEqual(presence["metodo"], "facial")
        with patch.object(main, "embedding", return_value=object()), \
                patch.object(main, "similarity", return_value=0.20), \
                patch.object(main, "estado_assinatura_frequency", return_value={"bloqueada_frequency": False}):
            unknown = main.verificar_acesso_facial(facial_request, leitor=reader)
        self.assertFalse(unknown["identificado"])
        self.assertEqual(unknown["motivo"], "rosto_nao_identificado")
        with _test_connection() as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) AS total FROM presencas WHERE academia_id = %s AND aluno_id = %s",
                    (academy_id, created["id"]),
                ).fetchone()["total"],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) AS total FROM presencas WHERE academia_id = %s AND aluno_id IS NULL",
                    (academy_id,),
                ).fetchone()["total"],
                1,
            )

    def test_plan_can_be_created_and_only_unused_plan_can_be_deleted(self):
        academy_id = self.create_academy("Academia planos sintética", "Brasil")
        owner = self.owner(academy_id, "Brasil")
        unused = self.new_plan(owner, name="Plano descartável")
        response = main.excluir_plano(unused["id"], dono=owner)
        self.assertEqual(response.status_code, 204)

        used = self.new_plan(owner, name="Plano em uso")
        self.new_student(owner, used["id"], "PLAN-IN-USE", 8181)
        with self.assertRaises(main.HTTPException) as blocked:
            main.excluir_plano(used["id"], dono=owner)
        self.assertEqual(blocked.exception.status_code, 409)
        self.assertEqual(blocked.exception.detail, "plano_em_uso")

    def test_assigning_plan_to_existing_student_creates_first_charge(self):
        academy_id = self.create_academy("Academia vínculo de plano", "Brasil")
        owner = self.owner(academy_id, "Brasil")
        plan = self.new_plan(owner, name="Plano para matrícula", value="89.90")
        student = main.criar_aluno(
            main.NovoAluno(
                nome="Aluno sem plano",
                documento="WITHOUT-PLAN",
                id_biometria=9191,
            ),
            usuario=owner,
        )

        linked = main.atribuir_plano_aluno(
            student["id"],
            main.AtualizacaoPlanoAluno(plano_id=plan["id"]),
            usuario=owner,
        )
        self.assertEqual((linked["plano_id"], linked["criado"]), (plan["id"], True))
        payment = self.payment_for(student["id"])
        self.assertEqual((payment["valor"], payment["status"]), (Decimal("89.90"), "em_aberto"))
        with _test_connection() as conn:
            self.assertEqual(
                conn.execute("SELECT plano_id FROM alunos WHERE id = %s", (student["id"],)).fetchone()["plano_id"],
                plan["id"],
            )

        repeated = main.atribuir_plano_aluno(
            student["id"],
            main.AtualizacaoPlanoAluno(plano_id=plan["id"]),
            usuario=owner,
        )
        self.assertFalse(repeated["criado"])
        with _test_connection() as conn:
            self.assertEqual(
                conn.execute("SELECT count(*) AS total FROM pagamentos WHERE aluno_id = %s", (student["id"],)).fetchone()["total"],
                1,
            )

    def test_payment_for_student_without_plan_is_rejected(self):
        academy_id = self.create_academy("Academia cobrança sem plano", "Brasil")
        owner = self.owner(academy_id, "Brasil")
        student = main.criar_aluno(
            main.NovoAluno(nome="Sem plano", documento="NO-PLAN-PAY", id_biometria=9292),
            usuario=owner,
        )
        with _test_connection() as conn:
            payment = conn.execute(
                "INSERT INTO pagamentos (academia_id, aluno_id, valor, moeda, vencimento) "
                "VALUES (%s, %s, 10.00, 'BRL', CURRENT_DATE) RETURNING id",
                (academy_id, student["id"]),
            ).fetchone()
        with self.assertRaises(main.HTTPException) as blocked:
            main.pagar(payment["id"], usuario=owner)
        self.assertEqual((blocked.exception.status_code, blocked.exception.detail), (409, "aluno_sem_plano"))

    def payment_for(self, student_id):
        with _test_connection() as conn:
            return conn.execute(
                "SELECT id, academia_id, aluno_id, valor, moeda, vencimento, status "
                "FROM pagamentos WHERE aluno_id = %s ORDER BY id LIMIT 1",
                (student_id,),
            ).fetchone()

    def create_user(self, email, role, academy_id=None, password="Synthetic.Pass.123"):
        with _test_connection() as conn:
            user = conn.execute(
                "INSERT INTO usuarios "
                "(academia_id, nome, email, senha_hash, papel, ativo) "
                "VALUES (%s, %s, %s, %s, %s, TRUE) RETURNING id",
                (
                    academy_id,
                    f"Conta sintética {role}",
                    email,
                    main.gerar_hash(password),
                    role,
                ),
            ).fetchone()
        return {"id": user["id"], "email": email, "password": password}

    def login_token(self, account):
        form = urlencode(
            {
                "username": account["email"],
                "password": account["password"],
            }
        ).encode("ascii")
        status, _headers, result = _api_call(
            "POST",
            "/login",
            body=form,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(status, 200, result)
        self.assertEqual(result["token_type"], "bearer")
        return result["access_token"]

    def json_api(self, method, target, *, token=None, body=None, extra_headers=None):
        headers = {"content-type": "application/json"}
        if token is not None:
            headers["authorization"] = f"Bearer {token}"
        headers.update(extra_headers or {})
        encoded_body = (
            json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None
            else b""
        )
        return _api_call(method, target, body=encoded_body, headers=headers)

    def test_bolivian_plan_student_and_first_charge_keep_bob(self):
        self.assertEqual(main.preferencias_iniciais_academia("Bolívia"), ("es-BO", "BOB"))
        academy_id = self.create_academy("Academia sintética BO", "Bolivia")
        owner = self.owner(academy_id, "Bolivia")
        plan = self.new_plan(owner, value="149.90")
        student = self.new_student(owner, plan["id"], "DOC-BO-1", 3101)
        payment = self.payment_for(student["id"])

        self.assertEqual((owner["idioma"], owner["moeda"]), ("es-BO", "BOB"))
        self.assertEqual(plan["moeda"], "BOB")
        self.assertEqual(payment["moeda"], "BOB")
        self.assertEqual(payment["vencimento"], date.today())
        self.assertEqual(payment["status"], "em_aberto")

    def test_overdue_payment_blocks_access_then_payment_renews_once(self):
        academy_a = self.create_academy("Academia sintética A", "Brasil")
        academy_b = self.create_academy("Academia sintética B", "Brasil")
        owner_a = self.owner(academy_a, "Brasil")
        owner_b = self.owner(academy_b, "Brasil")
        plan = self.new_plan(owner_a, duration=30)
        student = self.new_student(owner_a, plan["id"], "DOC-BR-1", 4101)
        payment = self.payment_for(student["id"])
        reader_a = {"academia_id": academy_a}
        reader_b = {"academia_id": academy_b}

        with self.assertRaises(main.HTTPException) as foreign_payment:
            main.pagar(payment["id"], usuario=owner_b)
        self.assertEqual(foreign_payment.exception.status_code, 404)

        with patch.object(main, "estado_assinatura_frequency", return_value={"bloqueada_frequency": False}):
            wrong_academy_access = main.verificar_acesso(
                main.PedidoAcesso(id_biometria=4101), leitor=reader_b
            )
        self.assertFalse(wrong_academy_access["liberado"])
        self.assertEqual(wrong_academy_access["motivo"], "digital_nao_cadastrada")

        with _test_connection() as conn:
            conn.execute(
                "UPDATE pagamentos SET vencimento = CURRENT_DATE - 1 WHERE id = %s",
                (payment["id"],),
            )

        with patch.object(main, "estado_assinatura_frequency", return_value={"bloqueada_frequency": False}):
            denied = main.verificar_acesso(
                main.PedidoAcesso(id_biometria=4101), leitor=reader_a
            )
        self.assertFalse(denied["liberado"])
        self.assertEqual(denied["motivo"], "mensalidade_atrasada")

        paid = main.pagar(payment["id"], usuario=owner_a)
        self.assertTrue(paid["pago"])
        self.assertEqual(paid["proximo_vencimento"], date.today() + timedelta(days=30))
        with self.assertRaises(main.HTTPException) as duplicate:
            main.pagar(payment["id"], usuario=owner_a)
        self.assertEqual(duplicate.exception.status_code, 409)

        with _test_connection() as conn:
            payments = conn.execute(
                "SELECT status, vencimento FROM pagamentos "
                "WHERE academia_id = %s AND aluno_id = %s ORDER BY id",
                (academy_a, student["id"]),
            ).fetchall()
        self.assertEqual(len(payments), 2)
        self.assertEqual(payments[0]["status"], "pago")
        self.assertEqual(payments[1]["status"], "em_aberto")
        self.assertEqual(payments[1]["vencimento"], date.today() + timedelta(days=30))

        with patch.object(main, "estado_assinatura_frequency", return_value={"bloqueada_frequency": False}):
            allowed = main.verificar_acesso(
                main.PedidoAcesso(id_biometria=4101), leitor=reader_a
            )
        self.assertTrue(allowed["liberado"])

        main.mudar_status_aluno(
            student["id"], main.StatusAluno(ativo=False), dono=owner_a
        )
        with patch.object(main, "estado_assinatura_frequency", return_value={"bloqueada_frequency": False}):
            inactive = main.verificar_acesso(
                main.PedidoAcesso(id_biometria=4101), leitor=reader_a
            )
        self.assertFalse(inactive["liberado"])
        self.assertEqual(inactive["motivo"], "aluno_inativo")

    def test_foreign_plan_cannot_be_assigned_by_route_or_database(self):
        from psycopg import errors
        from fastapi import HTTPException

        academy_a = self.create_academy("Academia sintética A", "Brasil")
        academy_b = self.create_academy("Academia sintética B", "Brasil")
        owner_a = self.owner(academy_a, "Brasil")
        owner_b = self.owner(academy_b, "Brasil")
        plan_a = self.new_plan(owner_a)

        with self.assertRaises(HTTPException) as route_rejection:
            self.new_student(owner_b, plan_a["id"], "DOC-CROSS-1", 5101)
        self.assertEqual(route_rejection.exception.status_code, 400)

        with self.assertRaises(errors.ForeignKeyViolation):
            with _test_connection() as conn:
                conn.execute(
                    "INSERT INTO alunos "
                    "(academia_id, nome, documento, plano_id) "
                    "VALUES (%s, %s, %s, %s)",
                    (academy_b, "Aluno sintético", "DOC-CROSS-2", plan_a["id"]),
                )

        with _test_connection() as conn:
            count = conn.execute(
                "SELECT count(*) AS total FROM alunos WHERE academia_id = %s",
                (academy_b,),
            ).fetchone()["total"]
        self.assertEqual(count, 0)

    def test_http_login_hides_hash_and_protected_routes_reject_missing_token(self):
        academy_id = self.create_academy("Academia HTTP sintética", "Brasil")
        account = self.create_user(
            "owner-http@example.test", "dono", academy_id
        )

        form = urlencode(
            {
                "username": account["email"],
                "password": "wrong synthetic password",
            }
        ).encode("ascii")
        wrong_status, _wrong_headers, wrong_result = _api_call(
            "POST",
            "/login",
            body=form,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(wrong_status, 401)
        self.assertEqual(wrong_result["detail"], "email_ou_senha_incorretos")

        token = self.login_token(account)
        status, headers, current_user = _api_call(
            "GET",
            "/eu",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(current_user["papel"], "dono")
        self.assertNotIn("senha_hash", current_user)
        self.assertEqual(headers["x-content-type-options"], "nosniff")

        anonymous_status, _headers, anonymous_result = self.json_api(
            "GET", "/planos"
        )
        self.assertEqual(anonymous_status, 401)
        self.assertEqual(anonymous_result["detail"], "Not authenticated")

    def test_google_oauth_state_is_bound_to_the_browser_that_started_it(self):
        academy = self.create_academy("Academia OAuth", "Brasil")
        owner = self.create_user("owner-oauth@example.test", "dono", academy)
        owner_token = self.login_token(owner)
        google_env = {
            "GOOGLE_OAUTH_CLIENT_ID": "synthetic-client",
            "GOOGLE_OAUTH_CLIENT_SECRET": "synthetic-secret",
        }
        with patch.dict(os.environ, google_env):
            status, headers, started = self.json_api(
                "GET", "/auth/google/gmail/start?format=json", token=owner_token
            )
            self.assertEqual(status, 200, started)
            cookie_header = headers.get("set-cookie", "")
            self.assertIn("frequency_oauth_nonce=", cookie_header)
            self.assertIn("HttpOnly", cookie_header)
            self.assertIn("Path=/auth/google", cookie_header)
            self.assertIn("samesite=lax", cookie_header.lower())
            nonce = cookie_header.split("frequency_oauth_nonce=", 1)[1].split(";", 1)[0]
            state = parse_qs(urlsplit(started["url"]).query)["state"][0]
            callback = f"/auth/google/gmail/callback?code=synthetic&state={state}"

            # Link aberto em outro navegador (sem o cookie): nada é trocado com o Google.
            with patch.object(main, "_google_request") as exchange:
                status, headers, _body = self.json_api("GET", callback)
                exchange.assert_not_called()
            self.assertIn(status, {302, 307})
            self.assertEqual(headers["location"], "/app?gmail_error=google_sessao_oauth_invalida")

            status, headers, _body = self.json_api(
                "GET", callback, extra_headers={"cookie": "frequency_oauth_nonce=outro-navegador"}
            )
            self.assertEqual(headers["location"], "/app?gmail_error=google_sessao_oauth_invalida")

            # Mesmo navegador: segue para a troca do código; uma falha do Google
            # vira mensagem compreensível em vez de JSON cru.
            with patch.object(
                main, "_google_request",
                side_effect=main.HTTPException(status_code=502, detail="google_indisponivel"),
            ) as exchange:
                status, headers, _body = self.json_api(
                    "GET", callback, extra_headers={"cookie": f"frequency_oauth_nonce={nonce}"}
                )
                exchange.assert_called_once()
            self.assertEqual(headers["location"], "/app?gmail_error=google_indisponivel")

            status, headers, _body = self.json_api(
                "GET", "/auth/google/callback?code=synthetic&state=adulterado.assinatura"
            )
            self.assertEqual(headers["location"], "/app?google_error=google_state_invalido")

        with patch.dict(os.environ, {"GOOGLE_OAUTH_CLIENT_ID": "", "GOOGLE_OAUTH_CLIENT_SECRET": ""}):
            status, headers, _body = self.json_api("GET", "/auth/google/start?flow=login")
            self.assertEqual(headers["location"], "/app?google_error=google_nao_configurado")

    def test_installer_download_uses_a_short_lived_admin_link(self):
        academy = self.create_academy("Academia Instalador", "Brasil")
        owner = self.create_user("owner-installer@example.test", "dono", academy)
        platform_admin = self.create_user("platform-installer@example.test", "admin_plataforma")
        owner_token = self.login_token(owner)
        admin_token = self.login_token(platform_admin)
        filename = "FrequencyGym-1.0.001-Setup.zip"
        downloads = Path(main.PASTA_FRONTEND) / "downloads"
        created = not (downloads / filename).exists()
        if created:
            downloads.mkdir(parents=True, exist_ok=True)
            (downloads / filename).write_bytes(b"synthetic installer")
        try:
            status, _headers, denied = self.json_api("POST", f"/downloads/{filename}/link", token=owner_token)
            self.assertEqual(status, 403, denied)
            status, _headers, link = self.json_api("POST", f"/downloads/{filename}/link", token=admin_token)
            self.assertEqual(status, 200, link)
            status, headers, body = self.json_api("GET", link["url"])
            self.assertEqual(status, 200)
            self.assertIn("attachment", headers.get("content-disposition", ""))
            tampered = link["url"].replace("ticket=", "ticket=0")
            status, _headers, expired = self.json_api("GET", tampered)
            self.assertEqual((status, expired["detail"]), (403, "link_download_expirado"))
            status, _headers, bare = self.json_api("GET", f"/downloads/{filename}")
            self.assertEqual(status, 403, bare)
            status, _headers, other = self.json_api("POST", "/downloads/..%2F.env/link", token=admin_token)
            self.assertEqual(status, 404, other)
        finally:
            if created:
                (downloads / filename).unlink()

    def test_cloud_backup_operations_are_reserved_to_the_platform_admin(self):
        academy = self.create_academy("Academia Backup Nuvem", "Brasil")
        owner = self.create_user("owner-backup@example.test", "dono", academy)
        platform_admin = self.create_user("platform-backup@example.test", "admin_plataforma")
        owner_token = self.login_token(owner)
        admin_token = self.login_token(platform_admin)

        with patch.dict(os.environ, {"FREQUENCY_INSTALLATION_MODE": "cloud", "BACKUP_ENABLE": "NO"}):
            # O banco da nuvem contém todas as academias: um dono não pode
            # configurar, iniciar nem baixar esse backup.
            for method, path, body in (
                ("GET", "/operacao/backup-config", None),
                ("PUT", "/operacao/backup-config", {"destino": "/tmp/frequency-owner-attempt"}),
                ("POST", "/operacao/backup", None),
                ("GET", "/operacao/backup/download", None),
            ):
                status, _headers, denied = self.json_api(method, path, token=owner_token, body=body)
                self.assertEqual(status, 403, (path, denied))
                self.assertEqual(denied["detail"], "backup_gerenciado_pela_plataforma")
            status, _headers, owner_view = self.json_api("GET", "/operacao/status", token=owner_token)
            self.assertEqual(status, 200, owner_view)
            self.assertEqual(owner_view["backup"]["status"], "gerenciado_pela_plataforma")
            self.assertNotIn("worker", owner_view["sincronizacao"])
            status, _headers, admin_config = self.json_api("GET", "/operacao/backup-config", token=admin_token)
            self.assertEqual(status, 200, admin_config)

        with patch.dict(os.environ, {"FREQUENCY_INSTALLATION_MODE": "local", "BACKUP_ENABLE": "NO"}):
            status, _headers, local_config = self.json_api("GET", "/operacao/backup-config", token=owner_token)
            self.assertEqual(status, 200, local_config)

    def test_http_roles_and_tenant_isolation(self):
        academy_a = self.create_academy("Academia HTTP A", "Brasil")
        academy_b = self.create_academy("Academia HTTP B", "Bolivia")
        owner_a = self.create_user("owner-a@example.test", "dono", academy_a)
        reception_a = self.create_user("front-a@example.test", "recepcao", academy_a)
        owner_b = self.create_user("owner-b@example.test", "dono", academy_b)
        platform_admin = self.create_user("platform@example.test", "admin_plataforma")
        owner_a_token = self.login_token(owner_a)
        reception_token = self.login_token(reception_a)
        owner_b_token = self.login_token(owner_b)
        admin_token = self.login_token(platform_admin)

        # Isola o teste do backup real configurado no .env da máquina.
        with patch.dict(os.environ, {"BACKUP_ENABLE": "NO"}):
            owner_status, _headers, owner_operation = self.json_api(
                "GET", "/operacao/status", token=owner_a_token
            )
        self.assertEqual(owner_status, 200, owner_operation)
        self.assertEqual(owner_operation["banco"], "conectado")
        self.assertIn(owner_operation["backup"]["status"], {"desativado", "nunca_executado", "indisponivel"})
        admin_status, _headers, admin_operation = self.json_api(
            "GET", "/operacao/status", token=admin_token
        )
        self.assertEqual(admin_status, 200, admin_operation)
        reception_status, _headers, reception_operation = self.json_api(
            "GET", "/operacao/status", token=reception_token
        )
        self.assertEqual(reception_status, 403, reception_operation)

        status, _headers, plans = self.json_api(
            "GET", "/planos", token=reception_token
        )
        self.assertEqual((status, plans), (200, []))

        admin_plan_status, _headers, admin_plan_denied = self.json_api(
            "GET", "/planos", token=admin_token
        )
        self.assertEqual(admin_plan_status, 403)
        self.assertEqual(admin_plan_denied["detail"], "sem_permissao")

        status, _headers, plan = self.json_api(
            "POST",
            "/planos",
            token=owner_a_token,
            body={"nome": "Mensal HTTP", "valor": "75.00", "duracao_dias": 30},
        )
        self.assertEqual(status, 201, plan)
        self.assertEqual(plan["moeda"], "BRL")

        forbidden_status, _headers, forbidden = self.json_api(
            "POST",
            "/planos",
            token=reception_token,
            body={"nome": "Proibido", "valor": "1.00", "duracao_dias": 30},
        )
        self.assertEqual(forbidden_status, 403)
        self.assertEqual(forbidden["detail"], "sem_permissao")

        status, _headers, student = self.json_api(
            "POST",
            "/alunos",
            token=reception_token,
            body={
                "nome": "Aluno HTTP sintético",
                "documento": "HTTP-DOC-A",
                "plano_id": plan["id"],
                "id_biometria": 7101,
            },
        )
        self.assertEqual(status, 201, student)
        payment = self.payment_for(student["id"])

        reception_payments_status, _headers, reception_payments = self.json_api(
            "GET",
            f"/pagamentos?aluno_id={student['id']}",
            token=reception_token,
        )
        self.assertEqual(reception_payments_status, 200)
        self.assertEqual(len(reception_payments), 1)

        status, _headers, students_b = self.json_api(
            "GET", "/alunos", token=owner_b_token
        )
        self.assertEqual((status, students_b), (200, []))
        status, _headers, payments_b = self.json_api(
            "GET",
            f"/pagamentos?aluno_id={student['id']}",
            token=owner_b_token,
        )
        self.assertEqual((status, payments_b), (200, []))

        foreign_payment_status, _headers, foreign_payment = self.json_api(
            "POST",
            f"/pagamentos/{payment['id']}/pagar",
            token=owner_b_token,
        )
        self.assertEqual(foreign_payment_status, 404)
        self.assertEqual(foreign_payment["detail"], "pagamento_nao_encontrado")

        with _test_connection() as conn:
            unchanged_payment = conn.execute(
                "SELECT status FROM pagamentos WHERE id = %s",
                (payment["id"],),
            ).fetchone()["status"]
        self.assertEqual(unchanged_payment, "em_aberto")

        paid_status, _headers, paid = self.json_api(
            "POST",
            f"/pagamentos/{payment['id']}/pagar",
            token=reception_token,
        )
        self.assertEqual(paid_status, 200, paid)
        self.assertTrue(paid["pago"])
        duplicate_status, _headers, duplicate = self.json_api(
            "POST",
            f"/pagamentos/{payment['id']}/pagar",
            token=reception_token,
        )
        self.assertEqual(duplicate_status, 409)
        self.assertEqual(duplicate["detail"], "pagamento_ja_pago")

        reception_status, _headers, reception_forbidden = self.json_api(
            "PATCH",
            f"/alunos/{student['id']}/status",
            token=reception_token,
            body={"ativo": False},
        )
        self.assertEqual(reception_status, 403)
        self.assertEqual(reception_forbidden["detail"], "sem_permissao")

        owner_status, _headers, updated_student = self.json_api(
            "PATCH",
            f"/alunos/{student['id']}/status",
            token=owner_a_token,
            body={"ativo": False},
        )
        self.assertEqual(owner_status, 200)
        self.assertEqual(updated_student["status"], "inativo")

        reception_team_status, _headers, team_denied = self.json_api(
            "GET", "/usuarios/recepcao", token=reception_token
        )
        self.assertEqual(reception_team_status, 403)
        self.assertEqual(team_denied["detail"], "sem_permissao")

        new_reception_status, _headers, new_reception = self.json_api(
            "POST",
            "/usuarios/recepcao",
            token=owner_a_token,
            body={
                "nome": "Recepção HTTP adicional",
                "email": "front-extra-a@example.test",
                "senha": "Synthetic.Front.123",
            },
        )
        self.assertEqual(new_reception_status, 201, new_reception)
        owner_team_status, _headers, team = self.json_api(
            "GET", "/usuarios/recepcao", token=owner_a_token
        )
        self.assertEqual(owner_team_status, 200)
        self.assertEqual(len(team), 2)
        foreign_team_status, _headers, foreign_team = self.json_api(
            "PATCH",
            f"/usuarios/recepcao/{new_reception['id']}/status",
            token=owner_b_token,
            body={"ativo": False},
        )
        self.assertEqual(foreign_team_status, 404)
        self.assertEqual(foreign_team["detail"], "recepcionista_nao_encontrado")

        admin_status, _headers, academies = self.json_api(
            "GET", "/admin/academias", token=admin_token
        )
        self.assertEqual(admin_status, 200)
        self.assertEqual({row["id"] for row in academies}, {academy_a, academy_b})
        owner_admin_status, _headers, owner_admin_denied = self.json_api(
            "GET", "/admin/academias", token=owner_a_token
        )
        self.assertEqual(owner_admin_status, 403)
        self.assertEqual(owner_admin_denied["detail"], "sem_permissao")

        onboarding_logo_buffer = io.BytesIO()
        Image.new("RGB", (36, 24), (198, 239, 98)).save(onboarding_logo_buffer, format="PNG")
        created_status, _headers, created_academy = self.json_api(
            "POST",
            "/admin/academias",
            token=admin_token,
            body={
                "nome_academia": "Academia HTTP onboarding",
                "pais": "Bolivia",
                "nome_dono": "Dono onboarding sintético",
                "email_dono": "new-owner-bo@example.test",
                "senha_dono": "Synthetic.Owner.123",
                "logo_monitor_base64": base64.b64encode(onboarding_logo_buffer.getvalue()).decode("ascii"),
                "logo_monitor_media_type": "image/png",
            },
        )
        self.assertEqual(created_status, 201, created_academy)
        with _test_connection() as conn:
            onboarding_logo = conn.execute(
                "SELECT logo_monitor_media_type, octet_length(logo_monitor) AS size "
                "FROM academias WHERE id = %s",
                (created_academy["academia_id"],),
            ).fetchone()
        self.assertEqual(onboarding_logo["logo_monitor_media_type"], "image/jpeg")
        self.assertGreater(onboarding_logo["size"], 0)
        onboarded_owner = {
            "email": created_academy["email_dono"],
            "password": "Synthetic.Owner.123",
        }
        onboarded_token = self.login_token(onboarded_owner)
        onboarded_status, _headers, onboarded_user = _api_call(
            "GET",
            "/eu",
            headers={"authorization": f"Bearer {onboarded_token}"},
        )
        self.assertEqual(onboarded_status, 200)
        self.assertEqual((onboarded_user["idioma"], onboarded_user["moeda"]), ("es-BO", "BOB"))
        self.assertNotIn("senha_hash", onboarded_user)

        admin_status, _headers, academies = self.json_api(
            "GET", "/admin/academias", token=admin_token
        )
        self.assertEqual(
            {row["id"] for row in academies},
            {academy_a, academy_b, created_academy["academia_id"]},
        )

        with _test_connection() as conn:
            after_payment = conn.execute(
                "SELECT status FROM pagamentos WHERE id = %s",
                (payment["id"],),
            ).fetchone()["status"]
        self.assertEqual(after_payment, "pago")

    def test_http_reader_key_allows_only_valid_reader_to_check_entry(self):
        academy_id = self.create_academy("Academia leitor HTTP", "Brasil")
        owner = self.owner(academy_id, "Brasil")
        plan = self.new_plan(owner)
        student = self.new_student(owner, plan["id"], "HTTP-READER-DOC", 8101)
        reader_key = "synthetic-reader-key-for-test-only"
        with _test_connection() as conn:
            conn.execute(
                "INSERT INTO leitores (academia_id, nome, chave_hash) "
                "VALUES (%s, %s, %s)",
                (
                    academy_id,
                    "Leitor sintético",
                    hashlib.sha256(reader_key.encode("utf-8")).hexdigest(),
                ),
            )

        payload = {"id_biometria": 8101}
        denied_status, _headers, denied = self.json_api(
            "POST",
            "/acesso",
            body=payload,
            extra_headers={"X-Reader-Key": "wrong synthetic reader key"},
        )
        self.assertEqual(denied_status, 401)
        self.assertEqual(denied["detail"], "chave_do_leitor_invalida")

        allowed_status, _headers, allowed = self.json_api(
            "POST",
            "/acesso",
            body=payload,
            extra_headers={"X-Reader-Key": reader_key},
        )
        self.assertEqual(allowed_status, 200)
        self.assertTrue(allowed["liberado"])
        self.assertEqual(allowed["nome"], "Aluno sintético")

        payment = self.payment_for(student["id"])
        with _test_connection() as conn:
            conn.execute(
                "UPDATE pagamentos SET vencimento = CURRENT_DATE - 1 WHERE id = %s",
                (payment["id"],),
            )
        overdue_status, _headers, overdue = self.json_api(
            "POST",
            "/acesso",
            body=payload,
            extra_headers={"X-Reader-Key": reader_key},
        )
        self.assertEqual(overdue_status, 200)
        self.assertFalse(overdue["liberado"])
        self.assertEqual(overdue["motivo"], "mensalidade_atrasada")

    def test_student_photo_and_entry_monitor_are_private_and_tenant_scoped(self):
        academy_a = self.create_academy("Academia monitor sintética A", "Brasil")
        academy_b = self.create_academy("Academia monitor sintética B", "Bolivia")
        owner_a = self.create_user("monitor-owner-a@example.test", "dono", academy_a)
        owner_b = self.create_user("monitor-owner-b@example.test", "dono", academy_b)
        reception = self.create_user("monitor-front@example.test", "recepcao", academy_a)
        admin = self.create_user("monitor-admin@example.test", "admin_plataforma")
        owner_token = self.login_token(owner_a)
        owner_b_token = self.login_token(owner_b)
        reception_token = self.login_token(reception)
        admin_token = self.login_token(admin)
        # Telas de entrada dependem de uma assinatura ativa com vaga de monitor.
        status, _, plan = self.json_api("POST", "/admin/frequency/planos", token=admin_token,
            body={"nome": "Monitor sintético", "valor": "50.00", "moeda": "BRL", "duracao_dias": 30,
                  "max_monitores": 1})
        self.assertEqual(status, 201, plan)
        status, _, subscription = self.json_api("POST", "/admin/frequency/assinaturas", token=admin_token,
            body={"academia_id": academy_a, "plano_id": plan["id"],
                  "vencimento": (date.today() + timedelta(days=30)).isoformat()})
        self.assertEqual(status, 201, subscription)

        monitor_page_status, monitor_page_headers, monitor_page = _api_call(
            "GET", "/monitor"
        )
        self.assertEqual(monitor_page_status, 200)
        self.assertIn("Tela de entrada", monitor_page.decode("utf-8"))
        self.assertIn("content-security-policy", monitor_page_headers)

        image_buffer = io.BytesIO()
        Image.new("RGB", (40, 30), (51, 93, 66)).save(image_buffer, format="PNG")
        image_b64 = base64.b64encode(image_buffer.getvalue()).decode("ascii")
        logo_status, _headers, logo_result = self.json_api(
            "PUT",
            "/academia/tela-acesso/logo",
            token=owner_token,
            body={"foto_base64": image_b64, "foto_media_type": "image/png"},
        )
        self.assertEqual((logo_status, logo_result), (200, {"salva": True}))

        config_status, _headers, config = self.json_api(
            "GET", "/academia/tela-acesso", token=owner_token
        )
        self.assertEqual(config_status, 200)
        self.assertFalse(config["chave_ativa"])
        self.assertTrue(config["logo_cadastrada"])

        key_status, _headers, key_result = self.json_api(
            "POST", "/academia/tela-acesso/chave", token=owner_token
        )
        self.assertEqual(key_status, 200)
        monitor_key = key_result["chave"]
        self.assertNotIn(monitor_key, json.dumps(config))
        monitor_headers = {"X-Monitor-Key": monitor_key}

        anonymous_status, _headers, _result = self.json_api("GET", "/monitor/estado")
        self.assertEqual(anonymous_status, 401)
        reception_key_status, _headers, _result = self.json_api(
            "POST", "/academia/tela-acesso/chave", token=reception_token
        )
        self.assertEqual(reception_key_status, 403)
        admin_key_status, _headers, _result = self.json_api(
            "POST", "/academia/tela-acesso/chave", token=admin_token
        )
        self.assertEqual(admin_key_status, 403)

        state_status, _headers, monitor_state = _api_call(
            "GET", "/monitor/estado", headers=monitor_headers
        )
        self.assertEqual(state_status, 200)
        self.assertEqual(monitor_state["academia"], "Academia monitor sintética A")
        self.assertEqual(monitor_state["ultimo_evento"], 0)
        self.assertTrue(monitor_state["logo_cadastrada"])
        logo_read_status, logo_headers, stored_logo = _api_call(
            "GET", "/monitor/logo", headers=monitor_headers
        )
        self.assertEqual(logo_read_status, 200)
        self.assertEqual(logo_headers["content-type"], "image/jpeg")
        self.assertEqual(logo_headers["cache-control"], "private, no-store")
        with Image.open(io.BytesIO(stored_logo)) as decoded_logo:
            self.assertEqual(decoded_logo.format, "JPEG")

        with _test_connection() as conn:
            conn.execute(
                "INSERT INTO leitores (academia_id, nome, chave_hash) VALUES (%s, %s, %s)",
                (academy_a, "Leitor do monitor sintético", hashlib.sha256(b"monitor-reader-key").hexdigest()),
            )
        business_owner = self.owner(academy_a, "Brasil")
        plan = self.new_plan(business_owner)
        student_response_status, _headers, student = self.json_api(
            "POST",
            "/alunos",
            token=owner_token,
            body={
                "nome": "Marina Silva",
                "documento": "MONITOR-SYNTHETIC-1",
                "plano_id": plan["id"],
                "id_biometria": 9201,
                "foto_base64": image_b64,
                "foto_media_type": "image/png",
            },
        )
        self.assertEqual(student_response_status, 201, student)

        photo_status, photo_headers, stored_photo = _api_call(
            "GET",
            f"/alunos/{student['id']}/foto",
            headers={"authorization": f"Bearer {owner_token}"},
        )
        self.assertEqual(photo_status, 200)
        self.assertEqual(photo_headers["content-type"], "image/jpeg")
        with Image.open(io.BytesIO(stored_photo)) as decoded_photo:
            self.assertEqual(decoded_photo.format, "JPEG")
        foreign_photo_status, _headers, _result = self.json_api(
            "GET", f"/alunos/{student['id']}/foto", token=owner_b_token
        )
        self.assertEqual(foreign_photo_status, 404)

        first_access_status, _headers, first_access = self.json_api(
            "POST",
            "/acesso",
            body={"id_biometria": 9201},
            extra_headers={"X-Reader-Key": "monitor-reader-key"},
        )
        self.assertEqual(first_access_status, 200)
        self.assertTrue(first_access["liberado"])
        event_status, _headers, events = _api_call(
            "GET", "/monitor/eventos?depois=0", headers=monitor_headers
        )
        self.assertEqual(event_status, 200)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["nome"], "Marina S.")
        self.assertTrue(events[0]["foto_disponivel"])
        self.assertNotIn("documento", events[0])
        self.assertNotIn("telefone", events[0])
        event_photo_status, _headers, monitor_photo = _api_call(
            "GET",
            f"/monitor/eventos/{events[0]['id']}/foto",
            headers=monitor_headers,
        )
        self.assertEqual(event_photo_status, 200)
        self.assertEqual(monitor_photo, stored_photo)

        for _ in range(2):
            burst_status, _headers, burst_access = self.json_api(
                "POST",
                "/acesso",
                body={"id_biometria": 9201},
                extra_headers={"X-Reader-Key": "monitor-reader-key"},
            )
            self.assertEqual(burst_status, 200)
            self.assertTrue(burst_access["liberado"])
        burst_event_status, _headers, burst_events = _api_call(
            "GET",
            f"/monitor/eventos?depois={events[0]['id']}",
            headers=monitor_headers,
        )
        self.assertEqual(burst_event_status, 200)
        self.assertEqual(len(burst_events), 2)
        self.assertLess(burst_events[0]["id"], burst_events[1]["id"])

        payment = self.payment_for(student["id"])
        with _test_connection() as conn:
            conn.execute(
                "UPDATE pagamentos SET vencimento = CURRENT_DATE - 1 WHERE id = %s",
                (payment["id"],),
            )
        overdue_status, _headers, overdue = self.json_api(
            "POST",
            "/acesso",
            body={"id_biometria": 9201},
            extra_headers={"X-Reader-Key": "monitor-reader-key"},
        )
        self.assertEqual(overdue_status, 200)
        self.assertFalse(overdue["liberado"])
        events_status, _headers, new_events = _api_call(
            "GET",
            f"/monitor/eventos?depois={burst_events[-1]['id']}",
            headers=monitor_headers,
        )
        self.assertEqual(events_status, 200)
        self.assertEqual(len(new_events), 1)
        self.assertFalse(new_events[0]["liberado"])
        self.assertEqual(new_events[0]["motivo"], "mensalidade_atrasada")
        with _test_connection() as conn:
            conn.execute(
                "UPDATE presencas SET data_hora = CURRENT_TIMESTAMP - INTERVAL '1 minute' "
                "WHERE academia_id = %s",
                (academy_a,),
            )
        old_event_status, _headers, old_events = _api_call(
            "GET", "/monitor/eventos?depois=0", headers=monitor_headers
        )
        self.assertEqual((old_event_status, old_events), (200, []))
        old_photo_status, _headers, _body = _api_call(
            "GET",
            f"/monitor/eventos/{new_events[0]['id']}/foto",
            headers=monitor_headers,
        )
        self.assertEqual(old_photo_status, 404)
        wrong_key_status, _headers, _result = _api_call(
            "GET", "/monitor/estado", headers={"X-Monitor-Key": "wrong"}
        )
        self.assertEqual(wrong_key_status, 401)

        delete_photo_status, _headers, delete_photo = self.json_api(
            "DELETE", f"/alunos/{student['id']}/foto", token=owner_token
        )
        self.assertEqual((delete_photo_status, delete_photo), (200, {"removida": True}))
        missing_photo_status, _headers, _result = _api_call(
            "GET",
            f"/alunos/{student['id']}/foto",
            headers={"authorization": f"Bearer {owner_token}"},
        )
        self.assertEqual(missing_photo_status, 404)

    def test_student_profile_is_editable_without_exposing_biometric_id(self):
        academy_a = self.create_academy("Academia perfil sintética A", "Brasil")
        academy_b = self.create_academy("Academia perfil sintética B", "Brasil")
        owner_a = self.create_user("profile-owner-a@example.test", "dono", academy_a)
        reception_a = self.create_user("profile-front-a@example.test", "recepcao", academy_a)
        owner_b = self.create_user("profile-owner-b@example.test", "dono", academy_b)
        platform_admin = self.create_user("profile-admin@example.test", "admin_plataforma")
        owner_a_token = self.login_token(owner_a)
        reception_token = self.login_token(reception_a)
        owner_b_token = self.login_token(owner_b)
        admin_token = self.login_token(platform_admin)

        created_status, _headers, created = self.json_api(
            "POST",
            "/alunos",
            token=owner_a_token,
            body={
                "nome": "Aluno perfil sintético",
                "documento": "PROFILE-DOC-A",
                "telefone": "+55 11 90000-0001",
                "data_nascimento": "2000-01-02",
                "id_biometria": 9101,
            },
        )
        self.assertEqual(created_status, 201, created)
        student_id = created["id"]

        anonymous_read_status, _headers, anonymous_read = self.json_api(
            "GET", f"/alunos/{student_id}"
        )
        self.assertEqual(anonymous_read_status, 401)
        self.assertEqual(anonymous_read["detail"], "Not authenticated")
        anonymous_update_status, _headers, anonymous_update = self.json_api(
            "PATCH", f"/alunos/{student_id}", body={"telefone": "anonymous"}
        )
        self.assertEqual(anonymous_update_status, 401)
        self.assertEqual(anonymous_update["detail"], "Not authenticated")

        read_status, _headers, profile = self.json_api(
            "GET", f"/alunos/{student_id}", token=reception_token
        )
        self.assertEqual(read_status, 200, profile)
        self.assertEqual(
            profile,
            {
                "id": student_id,
                "documento": "PROFILE-DOC-A",
                "telefone": "+55 11 90000-0001",
                "data_nascimento": "2000-01-02",
            },
        )
        self.assertNotIn("id_biometria", profile)

        update_status, _headers, updated = self.json_api(
            "PATCH",
            f"/alunos/{student_id}",
            token=reception_token,
            body={
                "documento": "PROFILE-DOC-A2",
                "telefone": "+55 11 90000-0002",
                "data_nascimento": "2001-03-04",
            },
        )
        self.assertEqual(update_status, 200, updated)
        self.assertEqual(updated["documento"], "PROFILE-DOC-A2")
        self.assertEqual(updated["telefone"], "+55 11 90000-0002")
        self.assertEqual(updated["data_nascimento"], "2001-03-04")

        clear_status, _headers, cleared = self.json_api(
            "PATCH",
            f"/alunos/{student_id}",
            token=owner_a_token,
            body={"telefone": None, "data_nascimento": None},
        )
        self.assertEqual(clear_status, 200, cleared)
        self.assertIsNone(cleared["telefone"])
        self.assertIsNone(cleared["data_nascimento"])

        foreign_read_status, _headers, foreign_read = self.json_api(
            "GET", f"/alunos/{student_id}", token=owner_b_token
        )
        self.assertEqual(foreign_read_status, 404)
        self.assertEqual(foreign_read["detail"], "aluno_nao_encontrado")
        foreign_update_status, _headers, foreign_update = self.json_api(
            "PATCH",
            f"/alunos/{student_id}",
            token=owner_b_token,
            body={"telefone": "foreign-change"},
        )
        self.assertEqual(foreign_update_status, 404)
        self.assertEqual(foreign_update["detail"], "aluno_nao_encontrado")

        admin_status, _headers, admin_denied = self.json_api(
            "GET", f"/alunos/{student_id}", token=admin_token
        )
        self.assertEqual(admin_status, 403)
        self.assertEqual(admin_denied["detail"], "sem_permissao")
        admin_update_status, _headers, admin_update = self.json_api(
            "PATCH",
            f"/alunos/{student_id}",
            token=admin_token,
            body={"telefone": "admin não deve gravar"},
        )
        self.assertEqual(admin_update_status, 403)
        self.assertEqual(admin_update["detail"], "sem_permissao")

        with _test_connection() as conn:
            saved = conn.execute(
                "SELECT documento, telefone, data_nascimento, id_biometria "
                "FROM alunos WHERE id = %s AND academia_id = %s",
                (student_id, academy_a),
            ).fetchone()
        self.assertEqual(saved["documento"], "PROFILE-DOC-A2")
        self.assertIsNone(saved["telefone"])
        self.assertIsNone(saved["data_nascimento"])
        self.assertEqual(saved["id_biometria"], 9101)

    def test_student_profile_rejects_invalid_and_duplicate_updates_atomically(self):
        academy_id = self.create_academy("Academia validação de perfil", "Brasil")
        owner = self.create_user("profile-validation@example.test", "dono", academy_id)
        token = self.login_token(owner)
        ids = []
        for document, biometric_id in (("PROFILE-UNIQUE-A", 9201), ("PROFILE-UNIQUE-B", 9202)):
            status, _headers, result = self.json_api(
                "POST",
                "/alunos",
                token=token,
                body={
                    "nome": "Aluno validação sintético",
                    "documento": document,
                    "telefone": "telefone original",
                    "data_nascimento": "1999-05-06",
                    "id_biometria": biometric_id,
                },
            )
            self.assertEqual(status, 201, result)
            ids.append(result["id"])
        target_id, duplicate_id = ids

        duplicate_status, _headers, duplicate = self.json_api(
            "PATCH",
            f"/alunos/{target_id}",
            token=token,
            body={
                "documento": "PROFILE-UNIQUE-B",
                "telefone": "telefone que não deve gravar",
                "data_nascimento": "2002-03-04",
            },
        )
        self.assertEqual(duplicate_status, 409)
        self.assertEqual(duplicate["detail"], "documento_ja_cadastrado")

        for payload, expected_detail in (
            ({"documento": "   "}, "documento_obrigatorio"),
            ({"data_nascimento": (date.today() + timedelta(days=1)).isoformat()}, "data_nascimento_invalida"),
            ({}, "nenhum_campo_para_atualizar"),
            ({"nome": "campo não permitido"}, "nenhum_campo_para_atualizar"),
        ):
            status, _headers, result = self.json_api(
                "PATCH", f"/alunos/{target_id}", token=token, body=payload
            )
            self.assertEqual(status, 400, result)
            self.assertEqual(result["detail"], expected_detail)

        with _test_connection() as conn:
            rows = conn.execute(
                "SELECT id, documento, telefone, data_nascimento "
                "FROM alunos WHERE academia_id = %s ORDER BY id",
                (academy_id,),
            ).fetchall()
        self.assertEqual(
            rows,
            [
                {
                    "id": target_id,
                    "documento": "PROFILE-UNIQUE-A",
                    "telefone": "telefone original",
                    "data_nascimento": date(1999, 5, 6),
                },
                {
                    "id": duplicate_id,
                    "documento": "PROFILE-UNIQUE-B",
                    "telefone": "telefone original",
                    "data_nascimento": date(1999, 5, 6),
                },
            ],
        )

    def test_student_can_be_registered_with_email_for_the_app(self):
        academy_id = self.create_academy("Academia e-mail do app", "Brasil")
        owner = self.create_user("email-app-owner@example.test", "dono", academy_id)
        token = self.login_token(owner)
        body = {"nome": "Aluno e-mail", "documento": "EMAIL-DOC-1", "email": "  Aluno.App@Example.test "}
        status, _headers, created = self.json_api("POST", "/alunos", token=token, body=body)
        self.assertEqual(status, 201, created)
        status, _headers, acesso = self.json_api("GET", f"/alunos/{created['id']}/acesso-app", token=token)
        self.assertEqual((status, acesso["email"], acesso["acesso_app"]), (200, "aluno.app@example.test", "convidado"))

        duplicate = dict(body, documento="EMAIL-DOC-2", email="ALUNO.APP@example.test")
        status, _headers, result = self.json_api("POST", "/alunos", token=token, body=duplicate)
        self.assertEqual((status, result["detail"]), (409, "email_ja_cadastrado"))

        invalid = dict(body, documento="EMAIL-DOC-3", email="sem-arroba")
        status, _headers, result = self.json_api("POST", "/alunos", token=token, body=invalid)
        self.assertEqual((status, result["detail"]), (422, "email_invalido"))

    def test_student_profile_routes_are_disabled_on_read_only_mirror(self):
        academy_id = self.create_academy("Academia espelho sintética", "Brasil")
        owner = self.create_user("profile-mirror@example.test", "dono", academy_id)
        token = self.login_token(owner)
        status, _headers, student = self.json_api(
            "POST",
            "/alunos",
            token=token,
            body={
                "nome": "Aluno espelho sintético",
                "documento": "PROFILE-MIRROR",
                "id_biometria": 9301,
            },
        )
        self.assertEqual(status, 201, student)

        previous = os.environ.get("SYNC_MIRROR_READ_ONLY")
        os.environ["SYNC_MIRROR_READ_ONLY"] = "YES"
        try:
            read_status, _headers, read_result = self.json_api(
                "GET", f"/alunos/{student['id']}", token=token
            )
            self.assertEqual(read_status, 403)
            self.assertEqual(read_result["detail"], "modo_somente_consulta")
            update_status, _headers, update_result = self.json_api(
                "PATCH",
                f"/alunos/{student['id']}",
                token=token,
                body={"telefone": "não deve gravar"},
            )
            self.assertEqual(update_status, 403)
            self.assertEqual(update_result["detail"], "modo_somente_consulta")
        finally:
            if previous is None:
                os.environ.pop("SYNC_MIRROR_READ_ONLY", None)
            else:
                os.environ["SYNC_MIRROR_READ_ONLY"] = previous

        with _test_connection() as conn:
            saved_phone = conn.execute(
                "SELECT telefone FROM alunos WHERE id = %s",
                (student["id"],),
            ).fetchone()["telefone"]
        self.assertIsNone(saved_phone)

    def premium_test_plans(self, admin_token, premium_price="120.00", days=30):
        base = {"moeda": "BRL", "duracao_dias": days}
        def create(name, price, tier, **extra):
            status, _, body = self.json_api("POST", "/admin/frequency/planos", token=admin_token,
                body={**base, "nome": name, "valor": price, "nivel": tier, "cameras": False, "youtube": False, **extra})
            return status, body
        return create

    def test_premium_resources_require_the_matching_active_subscription(self):
        admin = self.login_token(self.create_user("premium-admin@example.test", "admin_plataforma"))
        create_plan = self.premium_test_plans(admin)
        status, basic = create_plan("Basic entitlement", "30.00", "essencial")
        self.assertEqual(status, 201, basic)
        status, premium = create_plan("Premium entitlement", "120.00", "premium", cameras=True, youtube=False)
        self.assertEqual(status, 201, premium)
        self.assertEqual((premium["nivel"], premium["cameras"], premium["youtube"]), ("premium", True, False))
        identities = {}
        for name, plan in (("basic", basic), ("premium", premium)):
            academy = self.create_academy(f"Academia {name}", "Brasil")
            account = self.create_user(f"{name}-owner@example.test", "dono", academy)
            owner = self.login_token(account)
            status, _, result = self.json_api("POST", "/admin/frequency/assinaturas", token=admin,
                body={"academia_id": academy, "plano_id": plan["id"], "vencimento": date.today().isoformat()})
            self.assertEqual(status, 201, result)
            identities[name] = owner
        self.assertFalse(self.json_api("GET", "/eu", token=identities["basic"])[2]["recursos_frequency"]["cameras"])
        self.assertEqual(self.json_api("GET", "/academia/integracoes/cameras", token=identities["basic"])[0], 403)
        self.assertEqual(self.json_api("GET", "/academia/integracoes/youtube", token=identities["premium"])[0], 403)
        self.assertEqual(self.json_api("GET", "/academia/integracoes/cameras", token=identities["premium"])[0], 200)
        self.assertEqual(self.json_api("GET", "/academia/integracoes/desconhecido", token=identities["premium"])[0], 404)

    def test_premium_flags_and_price_order_are_enforced(self):
        admin = self.login_token(self.create_user("premium-price-admin@example.test", "admin_plataforma"))
        create_plan = self.premium_test_plans(admin)
        status, body = create_plan("Valid starter", "30.00", "essencial")
        self.assertEqual(status, 201, body)
        status, body = create_plan("Invalid feature", "20.00", "essencial", cameras=True)
        self.assertEqual(status, 400, body)
        status, body = create_plan("YouTube premium", "90.00", "premium", youtube=True)
        self.assertEqual(status, 201, body)
        status, body = create_plan("Premium must cost more", "20.00", "premium", youtube=True)
        self.assertEqual(status, 400, body)
        self.assertEqual(body["detail"], "premium_deve_ser_mais_caro")
        status, body = create_plan("Valid top tier", "90.00", "premium", cameras=True)
        self.assertEqual(status, 201, body)
        status, body = create_plan("Starter priced above premium", "91.00", "profissional")
        self.assertEqual(status, 400, body)

    def test_gym_location_update_preserves_currency_of_existing_student_plans(self):
        academy = self.create_academy("Localização sintética", "Brasil")
        owner = self.owner(academy, "Brasil")
        plan = self.new_plan(owner, name="Moeda histórica")
        status, _, saved = self.json_api("PATCH", "/academia/preferencias", token=self.login_token(
            self.create_user("location-owner@example.test", "dono", academy)), body={
                "pais": "Brasil", "cidade": "Manaus", "estado": "AM", "endereco": "Rua sintética 10", "codigo_postal": "69000-000"})
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["cidade"], "Manaus")
        self.assertEqual(saved["moeda"], "BRL")
        with _test_connection() as conn:
            historical = conn.execute("SELECT moeda FROM planos WHERE id = %s", (plan["id"],)).fetchone()
        self.assertEqual(historical["moeda"], "BRL")
        admin = self.login_token(self.create_user("location-admin@example.test", "admin_plataforma"))
        self.assertEqual(self.json_api("PATCH", "/academia/preferencias", token=admin, body={"pais": "Brasil"})[0], 403)

    def billing_fixture(self):
        admin = self.create_user("billing-regression@example.test", "admin_plataforma")
        token = self.login_token(admin)
        academy = self.create_academy("Cobrança isolada", "Brasil")
        owner = self.create_user("billing-owner@example.test", "dono", academy)
        status, _, plan = self.json_api("POST", "/admin/frequency/planos", token=token,
            body={"nome": "Regressão", "valor": "100.00", "moeda": "BRL", "duracao_dias": 30})
        self.assertEqual(status, 201, plan)
        status, _, subscription = self.json_api("POST", "/admin/frequency/assinaturas", token=token,
            body={"academia_id": academy, "plano_id": plan["id"],
                  "vencimento": (date.today() - timedelta(days=5)).isoformat()})
        self.assertEqual(status, 201, subscription)
        return token, self.login_token(owner), plan, subscription

    def test_billing_reschedule_updates_invoice_and_preserves_history(self):
        token, owner, plan, subscription = self.billing_fixture()
        sid, fid = subscription["assinatura_id"], subscription["fatura_id"]
        self.assertTrue(self.json_api("GET", "/eu", token=owner)[2]["bloqueada_frequency"])
        with _test_connection() as conn:
            before = conn.execute("SELECT * FROM faturas_frequency WHERE id = %s", (fid,)).fetchone()
        due = (date.today() + timedelta(days=10)).isoformat()
        status, _, result = self.json_api("PATCH", f"/admin/frequency/assinaturas/{sid}",
            token=token, body={"proximo_vencimento": due})
        self.assertEqual(status, 200, result)
        invoices = self.json_api("GET", "/admin/frequency/faturas", token=token)[2]
        self.assertEqual(invoices[0]["vencimento"], due)
        self.assertFalse(self.json_api("GET", "/eu", token=owner)[2]["bloqueada_frequency"])
        self.assertEqual(self.json_api("GET", "/alunos", token=owner)[0], 200)
        with _test_connection() as conn:
            after = conn.execute("SELECT * FROM faturas_frequency WHERE id = %s", (fid,)).fetchone()
        self.assertEqual({k: v for k, v in before.items() if k != "vencimento"},
                         {k: v for k, v in after.items() if k != "vencimento"})
        status, _, paid = self.json_api("PATCH", f"/admin/frequency/faturas/{fid}/pagar",
            token=token, body={"meio_pagamento": "PIX"})
        self.assertEqual(status, 200, paid)
        self.assertEqual(self.json_api("PATCH", f"/admin/frequency/faturas/{fid}/pagar",
            token=token, body={"meio_pagamento": "PIX"})[0], 409)
        self.assertEqual(self.json_api("PATCH", f"/admin/frequency/assinaturas/{sid}", token=token,
            body={"proximo_vencimento": (date.today() + timedelta(days=40)).isoformat()})[0], 200)
        with _test_connection() as conn:
            rows = conn.execute("SELECT * FROM faturas_frequency ORDER BY id").fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["vencimento"].isoformat(), due)
        self.assertEqual(rows[0]["valor"], before["valor"])
        self.assertEqual(rows[0]["periodo_fim"], before["periodo_fim"])

    def test_billing_plan_validation_has_no_partial_writes(self):
        token, _, plan, _ = self.billing_fixture()
        for body, expected in [({"nome": None, "valor": "200.00"}, 422),
                               ({"nome": "   ", "valor": "200.00"}, 422), ({}, 400)]:
            with self.subTest(body=body):
                status, _, result = self.json_api("PATCH", f"/admin/frequency/planos/{plan['id']}",
                    token=token, body=body)
                self.assertEqual(status, expected, result)
        with _test_connection() as conn:
            saved = conn.execute("SELECT nome, valor FROM planos_frequency WHERE id = %s", (plan["id"],)).fetchone()
        self.assertEqual(saved, {"nome": "Regressão", "valor": Decimal("100.00")})

    def test_billing_concurrent_cancellation_keeps_one_open_invoice(self):
        token, _, _, subscription = self.billing_fixture()
        sid, fid = subscription["assinatura_id"], subscription["fatura_id"]
        with _test_connection() as conn:
            second = conn.execute(
                "INSERT INTO faturas_frequency (academia_id, assinatura_id, referencia, "
                "periodo_inicio, periodo_fim, valor, moeda, vencimento) "
                "SELECT academia_id, assinatura_id, referencia, periodo_inicio + 30, "
                "periodo_fim + 30, valor, moeda, vencimento + 30 "
                "FROM faturas_frequency WHERE id = %s RETURNING id", (fid,),
            ).fetchone()["id"]
        barrier = Barrier(2)

        def cancel(invoice):
            barrier.wait(timeout=10)
            return self.json_api("PATCH", f"/admin/frequency/faturas/{invoice}/cancelar",
                token=token, body={"observacao_admin": "Concorrência sintética"})[0]

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(cancel, [fid, second]))
        self.assertEqual(sorted(results), [200, 409])
        self.assertEqual(self.json_api("PATCH", f"/admin/frequency/assinaturas/{sid}/status",
            token=token, body={"status": "suspensa"})[0], 200)
        with _test_connection() as conn:
            remaining = conn.execute("SELECT id FROM faturas_frequency WHERE status = 'em_aberto'").fetchall()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(self.json_api("PATCH", f"/admin/frequency/faturas/{remaining[0]['id']}/cancelar",
            token=token, body={"observacao_admin": "Suspensão explícita"})[0], 200)

    def test_billing_cancel_guard_and_suspended_payment(self):
        token, owner, _, subscription = self.billing_fixture()
        sid, fid = subscription["assinatura_id"], subscription["fatura_id"]
        status, _, result = self.json_api("PATCH", f"/admin/frequency/faturas/{fid}/cancelar",
            token=token, body={"observacao_admin": "Teste isolado"})
        self.assertEqual(status, 409, result)
        self.assertEqual(result["detail"], "fatura_necessaria_para_assinatura_ativa")
        self.assertEqual(self.json_api("PATCH", f"/admin/frequency/assinaturas/{sid}/status",
            token=token, body={"status": "suspensa"})[0], 200)
        status, _, paid = self.json_api("PATCH", f"/admin/frequency/faturas/{fid}/pagar",
            token=token, body={"meio_pagamento": "PIX"})
        self.assertEqual(status, 200, paid)
        self.assertIsNone(paid["proxima_fatura_id"])
        self.assertTrue(self.json_api("GET", "/eu", token=owner)[2]["bloqueada_frequency"])
        status, _, result = self.json_api("PATCH", f"/admin/frequency/assinaturas/{sid}", token=token,
            body={"status": "ativa", "proximo_vencimento": date.today().isoformat()})
        self.assertEqual(status, 409, result)
        with _test_connection() as conn:
            saved = conn.execute("SELECT status FROM assinaturas_frequency WHERE id = %s", (sid,)).fetchone()
        self.assertEqual(saved["status"], "suspensa")

    def test_premium_integrations_are_enforced_by_backend_subscription_entitlement(self):
        admin = self.create_user("premium-admin@example.test", "admin_plataforma")
        token = self.login_token(admin)
        academy = self.create_academy("Premium isolado", "Brasil")
        owner = self.create_user("premium-owner@example.test", "dono", academy)
        status, _, essential = self.json_api("POST", "/admin/frequency/planos", token=token,
            body={"nome": "Essencial regressão", "valor": "100.00", "moeda": "BRL",
                  "duracao_dias": 30, "nivel": "essencial"})
        self.assertEqual(status, 201, essential)
        status, _, premium = self.json_api("POST", "/admin/frequency/planos", token=token,
            body={"nome": "Premium regressão", "valor": "300.00", "moeda": "BRL",
                  "duracao_dias": 30, "nivel": "premium", "cameras": True, "youtube": True})
        self.assertEqual(status, 201, premium)
        status, _, subscription = self.json_api("POST", "/admin/frequency/assinaturas", token=token,
            body={"academia_id": academy, "plano_id": premium["id"], "vencimento": date.today().isoformat()})
        self.assertEqual(status, 201, subscription)
        owner_token = self.login_token(owner)
        me = self.json_api("GET", "/eu", token=owner_token)[2]
        self.assertEqual(me["recursos_frequency"], {
            "nivel": "premium", "cameras": True, "youtube": True,
            "max_monitores": 0, "max_leitores": 0, "max_alunos": 120,
        })
        self.assertEqual(self.json_api("GET", "/academia/integracoes/cameras", token=owner_token)[0], 200)
        self.assertEqual(self.json_api("GET", "/academia/integracoes/youtube", token=owner_token)[0], 200)
        status, _, updated = self.json_api("PATCH", f"/admin/frequency/planos/{premium['id']}",
            token=token, body={"nome": "Premium isolado atualizado"})
        self.assertEqual(status, 200, updated)
        status, _, result = self.json_api("PATCH", f"/admin/frequency/assinaturas/{subscription['assinatura_id']}",
            token=token, body={"plano_id": essential["id"]})
        self.assertEqual(status, 200, result)
        me = self.json_api("GET", "/eu", token=owner_token)[2]
        self.assertEqual(me["recursos_frequency"], {
            "nivel": "essencial", "cameras": False, "youtube": False,
            "max_monitores": 0, "max_leitores": 0, "max_alunos": 120,
        })
        for feature in ("cameras", "youtube"):
            status, _, result = self.json_api("GET", f"/academia/integracoes/{feature}", token=owner_token)
            self.assertEqual(status, 403, result)
            self.assertEqual(result["detail"], "recurso_exclusivo_plano_premium")

    def test_platform_billing_customer_edit_overdue_sheet_qr_and_lock_rules(self):
        admin_account = self.create_user("frequency-admin@example.test", "admin_plataforma")
        admin_token = self.login_token(admin_account)

        plan_status, _headers, plan = self.json_api(
            "POST",
            "/admin/frequency/planos",
            token=admin_token,
            body={
                "nome": "Plano Frequency integração",
                "descricao": "Plano de teste isolado",
                "valor": "120.00",
                "moeda": "BRL",
                "duracao_dias": 30,
            },
        )
        self.assertEqual(plan_status, 201, plan)

        onboarding_status, _headers, created = self.json_api(
            "POST",
            "/admin/academias",
            token=admin_token,
            body={
                "nome_academia": "Academia SaaS sintética",
                "pais": "Brasil",
                "nome_dono": "Dono SaaS sintético",
                "email_dono": "owner-saas@example.test",
                "senha_dono": "Synthetic.Owner.123",
                "plano_frequency_id": plan["id"],
                "vencimento_frequency": date.today().isoformat(),
            },
        )
        self.assertEqual(onboarding_status, 201, created)
        self.assertTrue(created["assinatura_frequency_criada"])
        self.assertIsNotNone(created["fatura_frequency_id"])

        academy_id = created["academia_id"]
        owner_account = {
            "email": "owner-saas@example.test",
            "password": "Synthetic.Owner.123",
        }
        owner_token = self.login_token(owner_account)

        list_status, _headers, customers = self.json_api(
            "GET", "/admin/frequency/academias", token=admin_token
        )
        self.assertEqual(list_status, 200, customers)
        customer = next(row for row in customers if row["academia_id"] == academy_id)
        self.assertEqual(customer["plano"], plan["nome"])
        self.assertEqual(customer["email_dono"], owner_account["email"])
        self.assertEqual(customer["vencimento"], date.today().isoformat())
        self.assertIsNone(customer["ultimo_pagamento"])

        price_update_status, _headers, updated_plan = self.json_api(
            "PATCH",
            f"/admin/frequency/planos/{plan['id']}",
            token=admin_token,
            body={"valor": "150.00", "duracao_dias": 45},
        )
        self.assertEqual(price_update_status, 200, updated_plan)
        self.assertEqual(Decimal(str(updated_plan["valor"])), Decimal("150.00"))
        self.assertEqual(updated_plan["duracao_dias"], 45)
        subscription_update_status, _headers, updated_subscription = self.json_api(
            "PATCH",
            f"/admin/frequency/assinaturas/{customer['assinatura_id']}",
            token=admin_token,
            body={"proximo_vencimento": (date.today() + timedelta(days=10)).isoformat()},
        )
        self.assertEqual(subscription_update_status, 200, updated_subscription)
        self.assertEqual(
            updated_subscription["proximo_vencimento"],
            (date.today() + timedelta(days=10)).isoformat(),
        )

        edit_status, _headers, edited = self.json_api(
            "PATCH",
            f"/admin/academias/{academy_id}",
            token=admin_token,
            body={
                "nome_academia": "Academia editada sintética",
                "pais": "Bolivia",
                "nome_dono": "Dono atualizado",
                "email_dono": "owner-saas-updated@example.test",
            },
        )
        self.assertEqual(edit_status, 200, edited)
        self.assertEqual(edited["academia"], "Academia editada sintética")
        self.assertEqual(edited["email_dono"], "owner-saas-updated@example.test")
        owner_account["email"] = "owner-saas-updated@example.test"
        owner_token = self.login_token(owner_account)

        with _test_connection() as conn:
            conn.execute(
                "UPDATE public.faturas_frequency SET vencimento = CURRENT_DATE - 2 "
                "WHERE id = %s",
                (created["fatura_frequency_id"],),
            )
        current_status, _headers, current = self.json_api("GET", "/eu", token=owner_token)
        self.assertEqual(current_status, 200, current)
        self.assertEqual(current["idioma"], "es-BO")
        self.assertEqual(current["moeda"], "BOB")
        self.assertEqual(current["dias_atraso_frequency"], 2)
        self.assertTrue(current["aviso_frequency"])
        self.assertFalse(current["bloqueada_frequency"])

        late_status, _headers, late_invoices = self.json_api(
            "GET", "/admin/frequency/faturas?status=atrasadas", token=admin_token
        )
        self.assertEqual(late_status, 200, late_invoices)
        self.assertEqual(len(late_invoices), 1)
        self.assertEqual(late_invoices[0]["dias_atraso"], 2)
        self.assertTrue(late_invoices[0]["aviso"])
        self.assertFalse(late_invoices[0]["bloqueada"])

        image = io.BytesIO()
        Image.new("RGB", (24, 24), (20, 34, 28)).save(image, format="PNG")
        qr_status, _headers, qr_result = _api_call(
            "PUT",
            "/admin/frequency/qr/BRL",
            body=image.getvalue(),
            headers={
                "authorization": f"Bearer {admin_token}",
                "content-type": "image/png",
            },
        )
        self.assertEqual(qr_status, 200, qr_result)
        qr_read_status, qr_headers, qr_image = _api_call(
            "GET",
            "/assinatura-frequency/qr",
            headers={"authorization": f"Bearer {owner_token}"},
        )
        self.assertEqual(qr_read_status, 200)
        self.assertEqual(qr_headers["content-type"], "image/png")
        self.assertEqual(qr_image, image.getvalue())

        with _test_connection() as conn:
            conn.execute(
                "UPDATE public.faturas_frequency SET vencimento = CURRENT_DATE - 5 "
                "WHERE id = %s",
                (created["fatura_frequency_id"],),
            )
        current_status, _headers, current = self.json_api("GET", "/eu", token=owner_token)
        self.assertEqual(current_status, 200, current)
        self.assertTrue(current["bloqueada_frequency"])
        blocked_status, _headers, blocked = self.json_api(
            "GET", "/alunos", token=owner_token
        )
        self.assertEqual(blocked_status, 402, blocked)
        self.assertEqual(blocked["detail"], "assinatura_frequency_bloqueada")
        access = main.verificar_acesso(
            main.PedidoAcesso(id_biometria=9999), leitor={"academia_id": academy_id}
        )
        self.assertFalse(access["liberado"])
        self.assertEqual(access["motivo"], "assinatura_frequency_bloqueada")

        invoice_status, _headers, billing = self.json_api(
            "GET", "/assinatura-frequency", token=owner_token
        )
        self.assertEqual(invoice_status, 200, billing)
        self.assertTrue(billing["bloqueada_frequency"])
        self.assertEqual(billing["fatura_atual"]["id"], created["fatura_frequency_id"])

        paid_status, _headers, paid = self.json_api(
            "PATCH",
            f"/admin/frequency/faturas/{created['fatura_frequency_id']}/pagar",
            token=admin_token,
            body={
                "meio_pagamento": "PIX",
                "referencia_pagamento": "comprovante-sintetico",
                "observacao_admin": "Pagamento confirmado no teste",
            },
        )
        self.assertEqual(paid_status, 200, paid)
        self.assertTrue(paid["pago"])
        self.assertIsNotNone(paid["proxima_fatura_id"])
        with _test_connection() as conn:
            next_invoice = conn.execute(
                "SELECT valor, moeda, periodo_fim - periodo_inicio + 1 AS duracao "
                "FROM public.faturas_frequency WHERE id = %s",
                (paid["proxima_fatura_id"],),
            ).fetchone()
        self.assertEqual(next_invoice["valor"], Decimal("150.00"))
        self.assertEqual(next_invoice["duracao"], 45)
        current_status, _headers, current = self.json_api("GET", "/eu", token=owner_token)
        self.assertEqual(current_status, 200, current)
        self.assertFalse(current["bloqueada_frequency"])

        summary_status, _headers, summary = self.json_api(
            "GET", "/admin/frequency/resumo", token=admin_token
        )
        self.assertEqual(summary_status, 200, summary)
        self.assertEqual(summary["academias"], 1)
        self.assertEqual(summary["assinaturas_ativas"], 1)
        self.assertTrue(summary["receita_mensal"])
        self.assertTrue(summary["vendas_mensais"])
        updated_customers_status, _headers, updated_customers = self.json_api(
            "GET", "/admin/frequency/academias", token=admin_token
        )
        self.assertEqual(updated_customers_status, 200, updated_customers)
        paid_customer = next(row for row in updated_customers if row["academia_id"] == academy_id)
        self.assertIsNotNone(paid_customer["ultimo_pagamento"])
        self.assertEqual(Decimal(str(paid_customer["ultimo_valor_pago"])), Decimal("120.00"))

        audit_status, _headers, audit = self.json_api(
            "GET", "/admin/frequency/auditoria", token=admin_token
        )
        self.assertEqual(audit_status, 200, audit)
        actions = {row["acao"] for row in audit}
        self.assertIn("cliente_cadastrado_com_assinatura", actions)
        self.assertIn("academia_atualizada", actions)
        self.assertIn("fatura_paga", actions)
        self.assertIn("plano_atualizado", actions)
        self.assertIn("assinatura_atualizada", actions)

    def test_platform_prospecting_keeps_leads_separate_and_requires_an_admin(self):
        admin = self.create_user("prospecting-admin@example.test", "admin_plataforma")
        admin_token = self.login_token(admin)
        academy_id = self.create_academy("Academia Prospecting", "Bolivia")
        owner = self.create_user("prospecting-owner@example.test", "dono", academy_id)
        owner_token = self.login_token(owner)

        denied_status, _headers, denied = self.json_api(
            "GET", "/admin/prospeccao/leads", token=owner_token
        )
        self.assertEqual(denied_status, 403, denied)

        created_status, _headers, lead = self.json_api(
            "POST",
            "/admin/prospeccao/leads",
            token=admin_token,
            body={
                "nome": "Power Gym",
                "cidade": "Cochabamba",
                "endereco": "Av. América 123",
                "telefone": "+591 70000000",
                "email": "contato@powergym.example",
                "site_instagram": "https://instagram.com/powergym",
                "avaliacao": "4.5",
                "observacoes": "Primeiro contato pelo WhatsApp.",
                "prioridade": "A",
                "status_comercial": "nao_contatado",
                "origem": "manual",
            },
        )
        self.assertEqual(created_status, 201, lead)
        self.assertEqual(lead["nome"], "Power Gym")
        self.assertEqual(lead["prioridade"], "A")
        self.assertEqual(lead["status_comercial"], "nao_contatado")
        self.assertIn("Hola", lead["email_corpo"])
        self.assertIn("Power Gym", lead["email_corpo"])
        self.assertIn("Frequency", lead["email_assunto"])

        updated_status, _headers, updated = self.json_api(
            "PATCH",
            f"/admin/prospeccao/leads/{lead['id']}",
            token=admin_token,
            body={
                "status_comercial": "mensagem_enviada",
                "ultimo_contato": "2026-10-07",
                "prioridade": "B",
            },
        )
        self.assertEqual(updated_status, 200, updated)
        self.assertEqual(updated["status_comercial"], "mensagem_enviada")
        self.assertEqual(updated["ultimo_contato"], "2026-10-07")
        self.assertEqual(updated["prioridade"], "B")

        listed_status, _headers, listed = self.json_api(
            "GET",
            "/admin/prospeccao/leads?prioridade=B&status=mensagem_enviada&cidade=Cochabamba",
            token=admin_token,
        )
        self.assertEqual(listed_status, 200, listed)
        self.assertEqual([row["id"] for row in listed["leads"]], [lead["id"]])
        self.assertEqual(listed["funil"]["total"], 1)
        self.assertEqual(listed["funil"]["mensagem_enviada"], 1)

        deleted_status, _headers, deleted = self.json_api(
            "DELETE", f"/admin/prospeccao/leads/{lead['id']}", token=admin_token
        )
        self.assertEqual(deleted_status, 200, deleted)
        self.assertTrue(deleted["excluido"])
        visible_status, _headers, visible = self.json_api(
            "GET", "/admin/prospeccao/leads", token=admin_token
        )
        self.assertEqual(visible_status, 200, visible)
        self.assertEqual(visible["leads"], [])
        with _test_connection() as conn:
            archived = conn.execute(
                "SELECT excluido_em, excluido_por FROM public.leads_prospeccao WHERE id = %s",
                (lead["id"],),
            ).fetchone()
        self.assertIsNotNone(archived["excluido_em"])
        self.assertEqual(archived["excluido_por"], admin["id"])

    def test_platform_prospecting_uses_the_admin_whatsapp_template(self):
        admin = self.create_user("prospecting-template@example.test", "admin_plataforma")
        admin_token = self.login_token(admin)
        settings_status, _headers, settings = self.json_api(
            "PATCH",
            "/admin/prospeccao/configuracao",
            token=admin_token,
            body={"whatsapp_template": "Hola {academia} de {cidade}, ¿podemos hablar de Frequency?"},
        )
        self.assertEqual(settings_status, 200, settings)
        self.assertIn("{academia}", settings["whatsapp_template"])

        created_status, _headers, lead = self.json_api(
            "POST", "/admin/prospeccao/leads", token=admin_token,
            body={"nome": "Gimnasio Central", "cidade": "Cochabamba", "telefone": "+591 70000001"},
        )
        self.assertEqual(created_status, 201, lead)
        self.assertEqual(lead["whatsapp_mensagem"], "Hola Gimnasio Central de Cochabamba, ¿podemos hablar de Frequency?")

    def test_platform_prospecting_stores_a_campaign_image_for_manual_attachment(self):
        admin = self.create_user("prospecting-image@example.test", "admin_plataforma")
        admin_token = self.login_token(admin)
        image = io.BytesIO()
        Image.new("RGB", (24, 16), "#2d6045").save(image, format="PNG")
        upload_status, _headers, uploaded = _api_call(
            "PUT", "/admin/prospeccao/imagem", body=image.getvalue(),
            headers={"authorization": f"Bearer {admin_token}", "content-type": "image/png"},
        )
        self.assertEqual(upload_status, 200, uploaded)
        self.assertTrue(uploaded["imagem_cadastrada"])
        read_status, read_headers, content = _api_call(
            "GET", "/admin/prospeccao/imagem", headers={"authorization": f"Bearer {admin_token}"}
        )
        self.assertEqual(read_status, 200)
        self.assertEqual(read_headers["content-type"], "image/jpeg")
        self.assertTrue(content.startswith(b"\xff\xd8\xff"))

    def test_reservations_are_isolated_and_can_be_cancelled_and_rebooked(self):
        academy_a = self.create_academy("Academia reservas A", "Brasil")
        academy_b = self.create_academy("Academia reservas B", "Brasil")
        owner_a = self.create_user("reservas-owner-a@example.test", "dono", academy_a)
        reception_a = self.create_user("reservas-reception-a@example.test", "recepcao", academy_a)
        owner_b = self.create_user("reservas-owner-b@example.test", "dono", academy_b)
        owner_a_token = self.login_token(owner_a)
        reception_a_token = self.login_token(reception_a)
        owner_b_token = self.login_token(owner_b)

        student_status, _headers, student_a = self.json_api(
            "POST", "/alunos", token=reception_a_token,
            body={"nome": "Aluno Reserva A", "documento": "RES-A"},
        )
        self.assertEqual(student_status, 201, student_a)
        student_b_status, _headers, student_b = self.json_api(
            "POST", "/alunos", token=owner_b_token,
            body={"nome": "Aluno Reserva B", "documento": "RES-B"},
        )
        self.assertEqual(student_b_status, 201, student_b)

        resource_status, _headers, resource = self.json_api(
            "POST", "/recursos-agendaveis", token=owner_a_token,
            body={"nome": "Sala de Yoga", "tipo": "aula", "capacidade": 1},
        )
        self.assertEqual(resource_status, 201, resource)
        listed_status, _headers, listed = self.json_api(
            "GET", "/recursos-agendaveis", token=reception_a_token,
        )
        self.assertEqual(listed_status, 200, listed)
        self.assertEqual([item["id"] for item in listed], [resource["id"]])

        start = datetime.now(timezone.utc) + timedelta(minutes=20)
        end = start + timedelta(hours=1)
        session_status, _headers, session = self.json_api(
            "POST", "/sessoes-agendadas", token=owner_a_token,
            body={"recurso_id": resource["id"], "inicio": start.isoformat(), "fim": end.isoformat()},
        )
        self.assertEqual(session_status, 201, session)
        session_list_status, _headers, sessions = self.json_api(
            "GET", "/sessoes-agendadas", token=reception_a_token,
        )
        self.assertEqual(session_list_status, 200, sessions)
        self.assertEqual(sessions[0]["vagas_disponiveis"], 1)

        reservation_status, _headers, reservation = self.json_api(
            "POST", f"/sessoes-agendadas/{session['id']}/reservas", token=reception_a_token,
            body={"aluno_id": student_a["id"]},
        )
        self.assertEqual(reservation_status, 201, reservation)
        duplicate_status, _headers, duplicate = self.json_api(
            "POST", f"/sessoes-agendadas/{session['id']}/reservas", token=reception_a_token,
            body={"aluno_id": student_a["id"]},
        )
        self.assertEqual(duplicate_status, 409, duplicate)
        self.assertEqual(duplicate["detail"], "reserva_duplicada")

        foreign_status, _headers, foreign = self.json_api(
            "POST", f"/sessoes-agendadas/{session['id']}/reservas", token=reception_a_token,
            body={"aluno_id": student_b["id"]},
        )
        self.assertEqual(foreign_status, 404, foreign)
        self.assertEqual(foreign["detail"], "aluno_nao_encontrado")

        cancel_status, _headers, cancelled = self.json_api(
            "DELETE", f"/reservas-agendadas/{reservation['id']}", token=reception_a_token,
        )
        self.assertEqual(cancel_status, 200, cancelled)
        self.assertEqual(cancelled["status"], "cancelada")
        rebook_status, _headers, rebooked = self.json_api(
            "POST", f"/sessoes-agendadas/{session['id']}/reservas", token=reception_a_token,
            body={"aluno_id": student_a["id"]},
        )
        self.assertEqual(rebook_status, 201, rebooked)

    def test_reservation_capacity_is_atomic_under_concurrent_requests(self):
        academy_id = self.create_academy("Academia capacidade reservas", "Brasil")
        owner = self.create_user("reservas-capacity-owner@example.test", "dono", academy_id)
        reception = self.create_user("reservas-capacity-reception@example.test", "recepcao", academy_id)
        owner_token = self.login_token(owner)
        reception_token = self.login_token(reception)
        student_ids = []
        for suffix in ("A", "B"):
            status, _headers, student = self.json_api(
                "POST", "/alunos", token=reception_token,
                body={"nome": f"Aluno capacidade {suffix}", "documento": f"CAP-{suffix}"},
            )
            self.assertEqual(status, 201, student)
            student_ids.append(student["id"])
        resource_status, _headers, resource = self.json_api(
            "POST", "/recursos-agendaveis", token=owner_token,
            body={"nome": "Área limitada", "tipo": "area", "capacidade": 1},
        )
        self.assertEqual(resource_status, 201, resource)
        start = datetime.now(timezone.utc) + timedelta(minutes=30)
        session_status, _headers, session = self.json_api(
            "POST", "/sessoes-agendadas", token=owner_token,
            body={"recurso_id": resource["id"], "inicio": start.isoformat(),
                  "fim": (start + timedelta(hours=1)).isoformat()},
        )
        self.assertEqual(session_status, 201, session)

        def reserve(student_id):
            return self.json_api(
                "POST", f"/sessoes-agendadas/{session['id']}/reservas",
                token=reception_token, body={"aluno_id": student_id},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, student_ids))
        statuses = sorted(result[0] for result in results)
        self.assertEqual(statuses, [201, 409], results)
        with _test_connection() as conn:
            total = conn.execute(
                "SELECT count(*) AS total FROM public.reservas_agendadas "
                "WHERE sessao_id = %s AND status = 'reservada'",
                (session["id"],),
            ).fetchone()["total"]
        self.assertEqual(total, 1)

    def test_reservation_permissions_and_past_sessions(self):
        academy_id = self.create_academy("Academia permissões reservas", "Brasil")
        owner = self.create_user("reservas-permission-owner@example.test", "dono", academy_id)
        reception = self.create_user("reservas-permission-reception@example.test", "recepcao", academy_id)
        owner_token = self.login_token(owner)
        reception_token = self.login_token(reception)
        denied_status, _headers, denied = self.json_api(
            "POST", "/recursos-agendaveis", token=reception_token,
            body={"nome": "Sem permissão", "tipo": "area", "capacidade": 2},
        )
        self.assertEqual(denied_status, 403, denied)
        resource_status, _headers, resource = self.json_api(
            "POST", "/recursos-agendaveis", token=owner_token,
            body={"nome": "Área teste", "tipo": "area", "capacidade": 2},
        )
        self.assertEqual(resource_status, 201, resource)
        denied_session_status, _headers, denied_session = self.json_api(
            "POST", "/sessoes-agendadas", token=reception_token,
            body={"recurso_id": resource["id"],
                  "inicio": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                  "fim": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()},
        )
        self.assertEqual(denied_session_status, 403, denied_session)
        past = datetime.now(timezone.utc) - timedelta(minutes=10)
        past_status, _headers, past_result = self.json_api(
            "POST", "/sessoes-agendadas", token=owner_token,
            body={"recurso_id": resource["id"], "inicio": past.isoformat(),
                  "fim": (past + timedelta(hours=1)).isoformat()},
        )
        self.assertEqual(past_status, 409, past_result)
        self.assertEqual(past_result["detail"], "sessao_no_passado")

    def test_resource_patch_rejects_null_for_every_optional_field(self):
        academy_id = self.create_academy("Academia nulos reservas", "Brasil")
        owner = self.create_user("reservas-null-owner@example.test", "dono", academy_id)
        owner_token = self.login_token(owner)
        resource_status, _headers, resource = self.json_api(
            "POST", "/recursos-agendaveis", token=owner_token,
            body={"nome": "Recurso nulos", "tipo": "area", "descricao": "Inicial", "capacidade": 2},
        )
        self.assertEqual(resource_status, 201, resource)
        for campo in ("nome", "descricao", "tipo", "capacidade", "ativo"):
            status, _headers, result = self.json_api(
                "PATCH", f"/recursos-agendaveis/{resource['id']}", token=owner_token,
                body={campo: None},
            )
            self.assertEqual(status, 422, (campo, result))
            self.assertEqual(result["detail"], "campos_nulos_nao_permitidos")

    def test_resource_capacity_cannot_drop_below_active_reservations(self):
        academy_id = self.create_academy("Academia capacidade mínima", "Brasil")
        owner = self.create_user("reservas-capacity-update-owner@example.test", "dono", academy_id)
        reception = self.create_user("reservas-capacity-update-reception@example.test", "recepcao", academy_id)
        owner_token = self.login_token(owner)
        reception_token = self.login_token(reception)
        resource_status, _headers, resource = self.json_api(
            "POST", "/recursos-agendaveis", token=owner_token,
            body={"nome": "Sala cheia", "tipo": "aula", "capacidade": 2},
        )
        self.assertEqual(resource_status, 201, resource)
        student_ids = []
        for suffix in ("A", "B"):
            status, _headers, student = self.json_api(
                "POST", "/alunos", token=reception_token,
                body={"nome": f"Aluno cheio {suffix}", "documento": f"FULL-{suffix}"},
            )
            self.assertEqual(status, 201, student)
            student_ids.append(student["id"])
        start = datetime.now(timezone.utc) + timedelta(hours=2)
        status, _headers, session = self.json_api(
            "POST", "/sessoes-agendadas", token=owner_token,
            body={"recurso_id": resource["id"], "inicio": start.isoformat(),
                  "fim": (start + timedelta(hours=1)).isoformat()},
        )
        self.assertEqual(status, 201, session)
        for student_id in student_ids:
            status, _headers, result = self.json_api(
                "POST", f"/sessoes-agendadas/{session['id']}/reservas", token=reception_token,
                body={"aluno_id": student_id},
            )
            self.assertEqual(status, 201, result)
        status, _headers, result = self.json_api(
            "PATCH", f"/recursos-agendaveis/{resource['id']}", token=owner_token,
            body={"capacidade": 1},
        )
        self.assertEqual(status, 409, result)
        self.assertEqual(result["detail"], "capacidade_inferior_reservas_ativas")

    def test_resource_sessions_reject_overlap_allow_touching_and_serialize_creation(self):
        academy_id = self.create_academy("Academia conflito horários", "Brasil")
        owner = self.create_user("reservas-conflict-owner@example.test", "dono", academy_id)
        owner_token = self.login_token(owner)
        status, _headers, resource = self.json_api(
            "POST", "/recursos-agendaveis", token=owner_token,
            body={"nome": "Sala horários", "tipo": "area", "capacidade": 5},
        )
        self.assertEqual(status, 201, resource)
        base = datetime.now(timezone.utc) + timedelta(hours=2)
        status, _headers, first = self.json_api(
            "POST", "/sessoes-agendadas", token=owner_token,
            body={"recurso_id": resource["id"], "inicio": base.isoformat(),
                  "fim": (base + timedelta(hours=1)).isoformat()},
        )
        self.assertEqual(status, 201, first)
        status, _headers, overlap = self.json_api(
            "POST", "/sessoes-agendadas", token=owner_token,
            body={"recurso_id": resource["id"],
                  "inicio": (base + timedelta(minutes=30)).isoformat(),
                  "fim": (base + timedelta(hours=1, minutes=30)).isoformat()},
        )
        self.assertEqual(status, 409, overlap)
        self.assertEqual(overlap["detail"], "recurso_agendavel_ocupado")
        status, _headers, touching = self.json_api(
            "POST", "/sessoes-agendadas", token=owner_token,
            body={"recurso_id": resource["id"], "inicio": (base + timedelta(hours=1)).isoformat(),
                  "fim": (base + timedelta(hours=2)).isoformat()},
        )
        self.assertEqual(status, 201, touching)

        concurrent_start = base + timedelta(hours=5)

        def create_concurrent_session(_index):
            return self.json_api(
                "POST", "/sessoes-agendadas", token=owner_token,
                body={"recurso_id": resource["id"], "inicio": concurrent_start.isoformat(),
                      "fim": (concurrent_start + timedelta(hours=1)).isoformat()},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            concurrent_results = list(pool.map(create_concurrent_session, (1, 2)))
        self.assertEqual(sorted(result[0] for result in concurrent_results), [201, 409], concurrent_results)
        self.assertEqual(
            [result[2]["detail"] for result in concurrent_results if result[0] == 409],
            ["recurso_agendavel_ocupado"],
        )

    def test_partial_reservation_schema_fails_closed_with_503(self):
        class Result:
            def __init__(self, rows=None, row=None):
                self.rows = rows or []
                self.row = row

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return self.row

        class PartialConnection:
            def execute(self, sql, *params):
                if "information_schema.columns" in sql:
                    return Result([{"table_name": "recursos_agendaveis", "column_name": "id"}])
                if "pg_constraint" in sql:
                    return Result([])
                return Result(row=None)

        with self.assertRaises(main.HTTPException) as blocked:
            main.exigir_esquema_reservas(PartialConnection())
        self.assertEqual((blocked.exception.status_code, blocked.exception.detail),
                         (503, "migracao_reservas_pendente"))


if __name__ == "__main__":
    unittest.main()
