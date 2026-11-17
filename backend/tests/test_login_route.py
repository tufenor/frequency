import os
import sys
import unittest
from pathlib import Path

import dotenv

from backend.rate_limiting import LoginRateLimiter


TEST_SECRET = "synthetic-integration-secret-not-for-use"
main = None
security = None
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


def setUpModule():
    global main, security, _MODULES_BEFORE_SETUP
    _MODULES_BEFORE_SETUP = set(sys.modules)
    original_load_dotenv = dotenv.load_dotenv
    original_secret = os.environ.get("SECRET_KEY")
    os.environ["SECRET_KEY"] = TEST_SECRET
    dotenv.load_dotenv = lambda *args, **kwargs: False
    backend_path = str(Path(__file__).resolve().parents[1])
    inserted_backend_path = backend_path not in sys.path
    if inserted_backend_path:
        sys.path.insert(0, backend_path)
    try:
        import main as main_module
        import seguranca as security_module

        main = main_module
        security = security_module
    finally:
        dotenv.load_dotenv = original_load_dotenv
        for module_name in ("database", "seguranca"):
            module = sys.modules.get(module_name)
            if module is not None:
                module.load_dotenv = original_load_dotenv
        if inserted_backend_path:
            sys.path.remove(backend_path)
        if original_secret is None:
            os.environ.pop("SECRET_KEY", None)
        else:
            os.environ["SECRET_KEY"] = original_secret


def tearDownModule():
    for module_name in _BACKEND_MODULES:
        if module_name not in _MODULES_BEFORE_SETUP:
            sys.modules.pop(module_name, None)


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row, calls):
        self.row = row
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, *_args):
        self.calls.append(True)
        return FakeCursor(self.row)


class LoginRouteTests(unittest.TestCase):
    def setUp(self):
        self.original_get_connection = main.get_connection
        self.original_verificar_senha = main.verificar_senha
        self.main_limiter = main.login_rate_limiter
        main.login_rate_limiter = LoginRateLimiter(TEST_SECRET)
        self.calls = []

    def tearDown(self):
        main.get_connection = self.original_get_connection
        main.verificar_senha = self.original_verificar_senha
        main.login_rate_limiter = self.main_limiter

    def request(self):
        from starlette.requests import Request

        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/login",
                "raw_path": b"/login",
                "query_string": b"",
                "headers": [],
                "client": ("198.51.100.77", 1234),
                "server": ("127.0.0.1", 8000),
            }
        )

    def form(self, password="wrong-password"):
        from fastapi.security import OAuth2PasswordRequestForm

        return OAuth2PasswordRequestForm(
            username="missing@example.test",
            password=password,
        )

    def test_unknown_user_has_uniform_401_then_429_and_dummy_argon2_check(self):
        from fastapi import HTTPException

        main.get_connection = lambda: FakeConnection(None, self.calls)
        checked_hashes = []
        original_verify = security.hasher.verify

        def verify_spy(password, password_hash):
            checked_hashes.append(password_hash)
            return original_verify(password, password_hash)

        security.hasher.verify = verify_spy
        try:
            for _ in range(8):
                with self.assertRaises(HTTPException) as raised:
                    main.login(self.request(), self.form())
                self.assertEqual(raised.exception.status_code, 401)
                self.assertEqual(raised.exception.detail, "email_ou_senha_incorretos")

            self.assertEqual(checked_hashes, [security.DUMMY_PASSWORD_HASH] * 8)
            self.assertEqual(len(self.calls), 8)

            with self.assertRaises(HTTPException) as limited:
                main.login(self.request(), self.form())
            self.assertEqual(limited.exception.status_code, 429)
            self.assertGreater(int(limited.exception.headers["Retry-After"]), 0)
            self.assertEqual(len(self.calls), 8)
        finally:
            security.hasher.verify = original_verify

    def test_successful_login_clears_prior_failures(self):
        password = "synthetic-correct-password"
        row = {
            "id": 7,
            "nome": "Usuário de teste",
            "senha_hash": security.gerar_hash(password),
            "papel": "dono",
        }
        main.get_connection = lambda: FakeConnection(row, self.calls)
        for attempt in range(7):
            main.login_rate_limiter.record_failure(
                "missing@example.test",
                "198.51.100.77",
            )

        response = main.login(self.request(), self.form(password))

        self.assertEqual(response["token_type"], "bearer")
        self.assertTrue(response["access_token"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(
            main.login_rate_limiter.retry_after("missing@example.test", "198.51.100.77"),
            0,
        )


if __name__ == "__main__":
    unittest.main()
