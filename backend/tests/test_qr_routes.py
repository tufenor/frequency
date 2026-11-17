import os
import sys
import unittest
from pathlib import Path

import dotenv

TEST_SECRET = "synthetic-qr-test-secret-not-for-use"
main = None
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
    global main, _MODULES_BEFORE_SETUP
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

        main = main_module
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
    def __init__(self, calls, row=None, error=None):
        self.calls = calls
        self.row = row
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, parameters=()):
        self.calls.append((statement, parameters))
        if self.error is not None:
            raise self.error
        return FakeCursor(self.row)


class QRRouteTests(unittest.IsolatedAsyncioTestCase):
    academy_id = 71

    def setUp(self):
        self.original_get_connection = main.get_connection
        self.original_read_only = os.environ.pop("SYNC_MIRROR_READ_ONLY", None)
        self.calls = []
        self.row = {"id": self.academy_id}
        self.database_error = None
        self.user = {
            "id": 9,
            "academia_id": self.academy_id,
            "papel": "dono",
        }
        main.get_connection = lambda: FakeConnection(
            self.calls,
            row=self.row,
            error=self.database_error,
        )

    def tearDown(self):
        main.get_connection = self.original_get_connection
        os.environ.pop("SYNC_MIRROR_READ_ONLY", None)
        if self.original_read_only is not None:
            os.environ["SYNC_MIRROR_READ_ONLY"] = self.original_read_only

    def request(self, body=b"", media_type="image/png"):
        from starlette.requests import Request

        messages = [
            {"type": "http.request", "body": body, "more_body": False}
        ]

        async def receive():
            if messages:
                return messages.pop(0)
            return {"type": "http.disconnect"}

        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "PUT",
                "scheme": "http",
                "path": "/academia/qr",
                "raw_path": b"/academia/qr",
                "query_string": b"",
                "headers": [(b"content-type", media_type.encode("ascii"))],
                "client": ("198.51.100.78", 1234),
                "server": ("127.0.0.1", 8000),
            },
            receive,
        )

    def route_dependency_calls(self, path, method):
        route = next(
            route
            for route in main.app.routes
            if getattr(route, "path", None) == path
            and method in getattr(route, "methods", set())
        )
        return {dependency.call for dependency in route.dependant.dependencies}

    async def test_owner_can_upload_qr_for_their_academy(self):
        image = b"\x89PNG\r\n\x1a\nfake-image"

        result = await main.salvar_qr_academia(
            self.request(image), dono=self.user
        )

        self.assertEqual(result, {"salvo": True})
        self.assertEqual(len(self.calls), 1)
        self.assertIn("UPDATE academias SET qr_pagamento", self.calls[0][0])
        self.assertEqual(self.calls[0][1], (image, "image/png", self.academy_id))
        self.assertIn(
            main.somente_dono,
            self.route_dependency_calls("/academia/qr", "PUT"),
        )

    async def test_reception_cannot_upload_or_remove_qr(self):
        from fastapi import HTTPException

        self.user["papel"] = "recepcao"
        dependencies = self.route_dependency_calls("/academia/qr", "PUT")
        self.assertIn(main.somente_dono, dependencies)

        with self.assertRaises(HTTPException) as upload_denied:
            main.somente_dono(usuario=self.user)
        self.assertEqual(upload_denied.exception.status_code, 403)

        with self.assertRaises(HTTPException) as removal_denied:
            main.somente_dono(usuario=self.user)
        self.assertEqual(removal_denied.exception.status_code, 403)
        self.assertEqual(self.calls, [])

    async def test_upload_rejects_unsupported_mime_and_invalid_image(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as unsupported:
            await main.salvar_qr_academia(
                self.request(b"content", "image/svg+xml"), dono=self.user
            )
        with self.assertRaises(HTTPException) as invalid:
            await main.salvar_qr_academia(
                self.request(b"not-an-image"), dono=self.user
            )

        self.assertEqual(unsupported.exception.status_code, 415)
        self.assertEqual(invalid.exception.status_code, 400)
        self.assertEqual(self.calls, [])

    async def test_upload_rejects_image_over_two_megabytes(self):
        from fastapi import HTTPException

        image = b"\x89PNG\r\n\x1a\n" + b"x" * main.TAMANHO_MAXIMO_QR

        with self.assertRaises(HTTPException) as raised:
            await main.salvar_qr_academia(self.request(image), dono=self.user)

        self.assertEqual(raised.exception.status_code, 413)
        self.assertEqual(self.calls, [])

    async def test_upload_and_delete_are_disabled_in_read_only_sync_mirror(self):
        from fastapi import HTTPException

        os.environ["SYNC_MIRROR_READ_ONLY"] = "YES"
        image = b"\x89PNG\r\n\x1a\nfake-image"

        with self.assertRaises(HTTPException) as upload:
            await main.salvar_qr_academia(self.request(image), dono=self.user)
        with self.assertRaises(HTTPException) as removal:
            main.remover_qr_academia(dono=self.user)

        self.assertEqual(upload.exception.status_code, 403)
        self.assertEqual(removal.exception.status_code, 403)
        self.assertEqual(self.calls, [])

    async def test_authenticated_academy_user_can_view_qr_without_cache(self):
        image = b"\x89PNG\r\n\x1a\nfake-image"
        self.row = {"qr_pagamento": image, "qr_media_type": "image/png"}
        self.user["papel"] = "recepcao"

        response = main.obter_qr_academia(usuario=self.user)

        self.assertEqual(response.body, image)
        self.assertEqual(response.media_type, "image/png")
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(self.calls[0][1], (self.academy_id,))
        dependencies = self.route_dependency_calls("/academia/qr", "GET")
        self.assertIn(main.usuario_de_academia, dependencies)
        self.assertEqual(
            main.usuario_de_academia(usuario=self.user),
            self.user,
        )

    async def test_missing_qr_migration_has_actionable_service_error(self):
        from fastapi import HTTPException
        from psycopg import errors

        self.database_error = errors.UndefinedColumn("missing QR columns")

        with self.assertRaises(HTTPException) as raised:
            main.obter_qr_academia(usuario=self.user)

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "migracao_qr_pendente")

    async def test_delete_removes_only_the_current_academys_qr(self):
        result = main.remover_qr_academia(dono=self.user)

        self.assertEqual(result, {"removido": True})
        self.assertIn("qr_pagamento = NULL", self.calls[0][0])
        self.assertIn("WHERE id = %s", self.calls[0][0])
        self.assertEqual(self.calls[0][1], (self.academy_id,))


if __name__ == "__main__":
    unittest.main()
