import hashlib
import json
import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from backend.pagamento_gateway import (
    GatewayNaoConfigurado,
    criar_checkout_dlocal,
    dlocal_assinatura,
    validar_notificacao_dlocal,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class PagamentoGatewayTests(unittest.TestCase):
    def setUp(self):
        self.original = {key: os.environ.get(key) for key in (
            "DLOCAL_X_LOGIN", "DLOCAL_X_TRANS_KEY", "DLOCAL_SECRET_KEY",
            "PAYMENT_PUBLIC_BASE_URL", "DLOCAL_API_BASE_URL",
        )}
        os.environ.update({
            "DLOCAL_X_LOGIN": "login-test",
            "DLOCAL_X_TRANS_KEY": "trans-test",
            "DLOCAL_SECRET_KEY": "secret-test",
            "PAYMENT_PUBLIC_BASE_URL": "https://frequency.example",
            "DLOCAL_API_BASE_URL": "https://sandbox.example",
        })

    def tearDown(self):
        for key, value in self.original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_notification_signature_uses_login_date_and_body(self):
        body = b'{"id":"D-1","status":"PAID"}'
        data = "2026-10-01T12:00:00.000Z"
        signature = dlocal_assinatura("login-test", data, "secret-test", body)
        self.assertTrue(validar_notificacao_dlocal(body, data, signature))
        self.assertTrue(validar_notificacao_dlocal(body, data, f"V2-HMAC-SHA256, Signature: {signature}"))
        self.assertFalse(validar_notificacao_dlocal(body, data, hashlib.sha256(body).hexdigest()))

    @patch("backend.pagamento_gateway.urllib.request.urlopen")
    def test_create_checkout_sends_signed_json_and_returns_redirect(self, urlopen):
        urlopen.return_value = FakeResponse({"id": "D-1", "status": "PENDING", "redirect_url": "https://pay.example/D-1"})
        checkout = criar_checkout_dlocal(
            order_id="frequency-fatura-1-test",
            amount=Decimal("250.00"),
            currency="BOB",
            payer_name="Academia Teste",
            payer_email="owner@example.com",
            payer_document="1234567",
            description="Frequency mensalidade",
            callback_url="https://frequency.example/app?pagamento=retorno",
        )
        self.assertEqual(checkout.pagamento_id, "D-1")
        request = urlopen.call_args.args[0]
        body = request.data
        self.assertEqual(json.loads(body)["order_id"], "frequency-fatura-1-test")
        headers = {key.lower(): value for key, value in request.headers.items()}
        self.assertEqual(headers["x-login"], "login-test")
        self.assertIn("V2-HMAC-SHA256", headers["authorization"])

    def test_checkout_requires_public_https_url(self):
        os.environ["PAYMENT_PUBLIC_BASE_URL"] = "http://localhost:8000"
        with self.assertRaises(GatewayNaoConfigurado):
            criar_checkout_dlocal(
                order_id="frequency-fatura-1-test",
                amount=Decimal("250.00"),
                currency="BOB",
                payer_name="Academia Teste",
                payer_email="owner@example.com",
                payer_document="1234567",
                description="Frequency mensalidade",
                callback_url="http://localhost:8000/app",
            )


if __name__ == "__main__":
    unittest.main()
