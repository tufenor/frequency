import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.ops import local_server


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _sql):
        return None


class LocalServerReadinessTests(unittest.TestCase):
    def test_tls_requires_a_matching_certificate_and_private_key(self):
        with tempfile.TemporaryDirectory(prefix="frequency-tls-") as temporary:
            cert = Path(temporary) / "cert.pem"
            key = Path(temporary) / "key.pem"
            cert.write_text("certificate", encoding="utf-8")
            key.write_text("private key", encoding="utf-8")
            self.assertEqual(local_server.tls_files(None, None), (None, None))
            with self.assertRaises(ValueError):
                local_server.tls_files(str(cert), None)
            self.assertEqual(local_server.tls_files(str(cert), str(key)), (str(cert), str(key)))

    def test_ready_report_requires_pages_database_and_complete_migrations(self):
        with tempfile.TemporaryDirectory(prefix="frequency-local-server-") as temporary:
            frontend = Path(temporary)
            for page in local_server.REQUIRED_PAGES:
                (frontend / page).write_text("<!doctype html>", encoding="utf-8")
            database = types.SimpleNamespace(get_connection=lambda: _Connection())
            migrations = types.SimpleNamespace(
                inspect=lambda: {name: "todos os objetos esperados presentes" for name in ("001", "010")}
            )
            with (
                patch.object(local_server, "FRONTEND_DIR", frontend),
                patch.dict(os.environ, {"SECRET_KEY": "x" * 32}, clear=False),
                patch.dict(sys.modules, {"database": database, "verificar_migracoes": migrations}),
            ):
                report = local_server.readiness()
            self.assertTrue(report["pronto"])
            self.assertEqual(report["banco"], "disponivel")
            self.assertEqual(report["migracoes"], "completas")

    def test_partial_migrations_prevent_start(self):
        with tempfile.TemporaryDirectory(prefix="frequency-local-server-") as temporary:
            frontend = Path(temporary)
            for page in local_server.REQUIRED_PAGES:
                (frontend / page).write_text("<!doctype html>", encoding="utf-8")
            database = types.SimpleNamespace(get_connection=lambda: _Connection())
            migrations = types.SimpleNamespace(inspect=lambda: {"010": "parcial — não reaplicar sem revisão"})
            with (
                patch.object(local_server, "FRONTEND_DIR", frontend),
                patch.dict(os.environ, {"SECRET_KEY": "x" * 32}, clear=False),
                patch.dict(sys.modules, {"database": database, "verificar_migracoes": migrations}),
            ):
                report = local_server.readiness()
            self.assertFalse(report["pronto"])
            self.assertIn("migrações pendentes ou parciais", report["problemas"])


if __name__ == "__main__":
    unittest.main()
