"""Imprime apenas metadados do esquema do banco Frequency, sem dados de usuários."""

from database import get_connection


with get_connection() as conn:
    tabelas = conn.execute(
        "SELECT table_name, table_type "
        "FROM information_schema.tables "
        "WHERE table_schema = current_schema() "
        "ORDER BY table_name"
    ).fetchall()

    print("== Tabelas e views ==")
    for linha in tabelas:
        print(f"{linha['table_type']}: {linha['table_name']}")

    colunas = conn.execute(
        "SELECT table_name, column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema = current_schema() "
        "ORDER BY table_name, ordinal_position"
    ).fetchall()

    print("\n== Colunas ==")
    for linha in colunas:
        print(
            f"{linha['table_name']}.{linha['column_name']}: "
            f"{linha['data_type']}; nulo={linha['is_nullable']}; "
            f"padrão={linha['column_default']}"
        )

    restricoes = conn.execute(
        "SELECT conrelid::regclass::text AS tabela, conname, "
        "pg_get_constraintdef(oid) AS definicao "
        "FROM pg_constraint "
        "WHERE connamespace = current_schema()::regnamespace "
        "ORDER BY conrelid::regclass::text, conname"
    ).fetchall()

    print("\n== Restrições ==")
    for linha in restricoes:
        print(f"{linha['tabela']}.{linha['conname']}: {linha['definicao']}")

    views = conn.execute(
        "SELECT table_name, view_definition "
        "FROM information_schema.views "
        "WHERE table_schema = current_schema() "
        "ORDER BY table_name"
    ).fetchall()

    print("\n== Definições das views ==")
    for linha in views:
        print(f"{linha['table_name']}: {linha['view_definition']}")
