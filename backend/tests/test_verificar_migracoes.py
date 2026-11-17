import unittest

from backend.verificar_migracoes import MIGRATION_ALTERNATIVES, REQUIRED_OBJECTS, classify_migrations


class MigrationStatusTests(unittest.TestCase):
    def test_empty_schema_reports_all_migrations_pending(self):
        states = classify_migrations(set(), set(), set(), set())
        self.assertTrue(
            all(status == "nenhum objeto esperado encontrado" for status in states.values())
        )

    def test_complete_required_objects_are_reported_without_claiming_execution_history(self):
        objects = set().union(
            *REQUIRED_OBJECTS.values(),
            *MIGRATION_ALTERNATIVES["009_recursos_premium.sql"],
        )
        tables = {name for kind, name in objects if kind == "table"}
        views = {name for kind, name in objects if kind == "view"}
        columns = {name for kind, name in objects if kind == "column"}
        constraints = {name for kind, name in objects if kind == "constraint"}

        states = classify_migrations(tables, views, columns, constraints)
        self.assertTrue(
            all(status == "todos os objetos esperados presentes" for status in states.values())
        )

    def test_partially_present_qr_migration_is_not_marked_safe_to_rerun(self):
        states = classify_migrations(
            tables={"academias"},
            views=set(),
            columns={"academias.qr_pagamento"},
            constraints=set(),
        )
        self.assertEqual(
            states["004_qr_cobranca_academia.sql"],
            "parcial — não reaplicar sem revisão",
        )

    def test_partially_present_monitor_migration_requires_review(self):
        states = classify_migrations(
            tables={"academias"},
            views=set(),
            columns={"academias.chave_monitor_hash"},
            constraints=set(),
        )
        self.assertEqual(
            states["007_tela_aluno.sql"],
            "parcial — não reaplicar sem revisão",
        )

    def test_partially_present_premium_migration_requires_review(self):
        states = classify_migrations(
            tables={"planos_frequency"},
            views=set(),
            columns={"planos_frequency.nivel", "planos_frequency.cameras"},
            constraints={"planos_frequency_nivel_check"},
        )
        self.assertEqual(
            states["009_recursos_premium.sql"],
            "parcial — não reaplicar sem revisão",
        )

    def test_partially_present_location_migration_requires_review(self):
        states = classify_migrations(
            tables={"academias"},
            views=set(),
            columns={"academias.cidade", "academias.estado"},
            constraints=set(),
        )
        self.assertEqual(
            states["010_localizacao_academia.sql"],
            "parcial — não reaplicar sem revisão",
        )


if __name__ == "__main__":
    unittest.main()
