import unittest

from backend.ops.aplicar_migracoes import COMPLETE, EMPTY, NOT_RERUNNABLE, plan
from backend.verificar_migracoes import REQUIRED_OBJECTS


class MigrationPlanTests(unittest.TestCase):
    files = [
        "001_initial_schema.sql",
        "004_qr_cobranca_academia.sql",
        "014_telefone_academia.sql",
        "033_gmail_prospeccao.sql",
    ]

    def test_fresh_database_applies_everything(self):
        steps = plan(self.files, set(), {}, existing_schema=False)
        self.assertEqual({action for _, action in steps}, {"apply"})

    def test_recorded_migrations_are_skipped(self):
        steps = dict(plan(self.files, set(self.files), {}, existing_schema=False))
        self.assertEqual(set(steps.values()), {"skip"})

    def test_legacy_install_detects_only_non_rerunnable_complete_migrations(self):
        states = {name: COMPLETE for name in REQUIRED_OBJECTS}
        steps = dict(plan(self.files, set(), states, existing_schema=True))
        self.assertEqual(steps["001_initial_schema.sql"], "detect")
        self.assertEqual(steps["004_qr_cobranca_academia.sql"], "detect")
        # 033 widens a constraint created by 019 under the same name, so its
        # fingerprint looks complete; it is idempotent and must run again.
        self.assertEqual(steps["033_gmail_prospeccao.sql"], "apply")
        self.assertEqual(steps["014_telefone_academia.sql"], "apply")

    def test_partial_non_rerunnable_migration_blocks_the_update(self):
        states = {name: COMPLETE for name in REQUIRED_OBJECTS}
        states["004_qr_cobranca_academia.sql"] = "parcial — não reaplicar sem revisão"
        steps = dict(plan(self.files, set(), states, existing_schema=True))
        self.assertEqual(steps["004_qr_cobranca_academia.sql"], "partial")

    def test_missing_non_rerunnable_migration_is_applied(self):
        states = {name: COMPLETE for name in REQUIRED_OBJECTS}
        states["004_qr_cobranca_academia.sql"] = EMPTY
        steps = dict(plan(self.files, set(), states, existing_schema=True))
        self.assertEqual(steps["004_qr_cobranca_academia.sql"], "apply")

    def test_every_non_rerunnable_migration_has_a_fingerprint(self):
        self.assertLessEqual(NOT_RERUNNABLE, set(REQUIRED_OBJECTS))


if __name__ == "__main__":
    unittest.main()
