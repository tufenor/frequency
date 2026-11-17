import unittest
import os
from datetime import date, timedelta
from unittest.mock import patch

from backend import cobranca_saas


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, *rows):
        self._rows = iter(rows)

    def execute(self, *_args):
        return _Result(next(self._rows))


class SubscriptionGateTests(unittest.TestCase):
    def setUp(self):
        self.billing_mode = patch.dict(os.environ, {"FREQUENCY_BILLING_REQUIRED": "YES"})
        self.billing_mode.start()
        self.clock = patch.object(
            cobranca_saas,
            "estado_relogio_local",
            return_value={"data_referencia": date.today(), "relogio_recuou": False},
        )
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.billing_mode.stop()

    def test_legacy_active_academy_without_subscription_is_blocked(self):
        state = cobranca_saas.estado_assinatura_frequency(
            _Connection(
                {"presente": True},
                {
                    "status": None,
                    "status_comercial": "ativa",
                    "trial_inicio": None,
                    "trial_fim": None,
                },
                None,
            ),
            1,
        )
        self.assertTrue(state["bloqueada_frequency"])
        self.assertEqual(state["motivo_bloqueio_frequency"], "sem_assinatura")

    def test_explicit_active_trial_remains_available(self):
        state = cobranca_saas.estado_assinatura_frequency(
            _Connection(
                {"presente": True},
                {
                    "status": None,
                    "status_comercial": "ativa",
                    "trial_inicio": date.today(),
                    "trial_fim": date.today() + timedelta(days=7),
                },
                None,
            ),
            1,
        )
        self.assertFalse(state["bloqueada_frequency"])
        self.assertTrue(state["experiencia_ativa"])

    def test_missing_billing_schema_fails_closed(self):
        state = cobranca_saas.estado_assinatura_frequency(
            _Connection({"presente": False}, None),
            1,
        )
        self.assertTrue(state["bloqueada_frequency"])
        self.assertEqual(
            state["motivo_bloqueio_frequency"],
            "migracao_frequency_pendente",
        )

    def test_local_mode_preserves_legacy_installation(self):
        with patch.dict(os.environ, {"FREQUENCY_BILLING_REQUIRED": "NO"}):
            state = cobranca_saas.estado_assinatura_frequency(
                _Connection(
                    {"presente": False},
                    None,
                ),
                1,
            )
        self.assertFalse(state["bloqueada_frequency"])


if __name__ == "__main__":
    unittest.main()
