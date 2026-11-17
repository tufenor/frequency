import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request


os.environ.setdefault("SECRET_KEY", "local-test-secret-key-32-characters-minimum")
os.environ["PAYMENT_ALLOW_HTTP_STAGING"] = "YES"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402


class PagamentoWebhookTests(unittest.IsolatedAsyncioTestCase):
    async def test_usa_authorization_do_dlocal_para_validar_assinatura(self):
        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/webhooks/dlocal",
            "raw_path": b"/webhooks/dlocal",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 123),
            "server": ("testserver", 80),
        }
        request = Request(scope, receive)

        with patch.object(main, "validar_notificacao_dlocal", return_value=False) as validar:
            with self.assertRaises(HTTPException) as erro:
                await main.receber_webhook_dlocal(
                    request,
                    "2026-10-01T12:00:00.000Z",
                    "V2-HMAC-SHA256, Signature: test",
                    None,
                )

        self.assertEqual(erro.exception.status_code, 401)
        validar.assert_called_once_with(
            b"{}",
            "2026-10-01T12:00:00.000Z",
            "V2-HMAC-SHA256, Signature: test",
        )


if __name__ == "__main__":
    unittest.main()
