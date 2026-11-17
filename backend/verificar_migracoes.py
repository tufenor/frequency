"""Read-only check of Frequency migration structures in the configured database."""

from __future__ import annotations

import sys

import psycopg


REQUIRED_OBJECTS: dict[str, set[tuple[str, str]]] = {
    "001_initial_schema.sql": {
        *(('table', name) for name in (
            "academias", "alunos", "leitores", "pagamentos", "planos",
            "presencas", "usuarios",
        )),
        ("view", "situacao_alunos"),
    },
    "002_tenant_integrity.sql": {
        *(('constraint', name) for name in (
            "planos_academia_id_id_key",
            "alunos_academia_id_id_key",
            "alunos_plano_mesma_academia_fkey",
            "pagamentos_aluno_mesma_academia_fkey",
            "presencas_aluno_mesma_academia_fkey",
        )),
    },
    "003_sync_outbox.sql": {
        *(('table', name) for name in (
            "sync_revision_counters", "sync_outbox", "sync_inbox",
            "sync_credentials", "sync_receive_state", "sync_snapshot_runs",
        )),
        *(('column', f"{table}.{column}") for table, column in (
            ("academias", "sync_id"), ("planos", "sync_id"),
            ("alunos", "sync_id"), ("pagamentos", "sync_id"),
            ("presencas", "sync_id"),
        )),
        ("constraint", "sync_outbox_academia_revision_key"),
        ("constraint", "sync_inbox_source_revision_key"),
    },
    "004_qr_cobranca_academia.sql": {
        ("column", "academias.qr_pagamento"),
        ("column", "academias.qr_media_type"),
        *(('constraint', name) for name in (
            "academias_qr_media_type_check",
            "academias_qr_imagem_tamanho_check",
            "academias_qr_pares_check",
        )),
    },
    "005_idioma_moeda.sql": {
        *(('column', f"{table}.{column}") for table, column in (
            ("academias", "idioma"), ("academias", "moeda"),
            ("planos", "moeda"), ("pagamentos", "moeda"),
        )),
        *(('constraint', name) for name in (
            "academias_idioma_check", "academias_moeda_check",
            "planos_moeda_check", "pagamentos_moeda_check",
        )),
    },
    "006_foto_alunos.sql": {
        *(('column', f"alunos.{column}") for column in (
            "foto_perfil", "foto_media_type",
        )),
        ("constraint", "alunos_foto_media_type_check"),
    },
    "007_tela_aluno.sql": {
        *(('column', f"academias.{column}") for column in (
            "chave_monitor_hash", "logo_monitor", "logo_monitor_media_type",
        )),
        *(('constraint', name) for name in (
            "academias_chave_monitor_hash_check",
            "academias_logo_monitor_media_type_check",
            "academias_logo_monitor_tamanho_check",
            "academias_logo_monitor_pares_check",
            "academias_chave_monitor_hash_key",
        )),
    },
    "008_cobranca_frequency.sql": {
        *(('table', name) for name in (
            "planos_frequency", "assinaturas_frequency", "faturas_frequency",
            "plataforma_qrs", "configuracao_frequency", "auditoria_frequency",
        )),
    },
    "009_recursos_premium.sql": {
        *(('column', f"planos_frequency.{column}") for column in (
            "nivel", "cameras",
        )),
        *(('constraint', name) for name in (
            "planos_frequency_nivel_check",
        )),
    },
    "010_localizacao_academia.sql": {
        *(('column', f"academias.{column}") for column in ("cidade", "estado", "endereco", "codigo_postal")),
    },
    "011_biometria_facial.sql": {
        ("table", "biometrias_faciais"),
        *(('constraint', name) for name in (
            "biometrias_faciais_aluno_key",
            "biometrias_faciais_biometria_key",
            "biometrias_faciais_aluno_fk",
        )),
    },
    "012_origem_acesso.sql": {
        *(('column', f"presencas.{column}") for column in (
            "leitor_id", "metodo_identificacao", "confianca",
        )),
        *(('constraint', name) for name in (
            "leitores_id_academia_id_key",
            "presencas_leitor_fk",
            "presencas_metodo_identificacao_check",
            "presencas_confianca_check",
        )),
    },
    "013_youtube_premium.sql": {
        ("column", "planos_frequency.youtube"),
        ("constraint", "planos_frequency_recursos_check"),
    },
    "015_pagamentos_online.sql": {
        *(('column', f"faturas_frequency.{column}") for column in (
            "provedor_pagamento", "pagamento_id_externo", "pedido_pagamento_externo",
            "checkout_url", "status_pagamento_externo", "pagamento_atualizado_em",
        )),
        ("table", "pagamentos_webhook_eventos"),
        *(('constraint', name) for name in (
            "faturas_frequency_status_pagamento_check",
        )),
    },
    "016_google_identities.sql": {
        ("table", "google_identities"),
        ("constraint", "google_identities_usuario_key"),
    },
    "018_gmail_comprovantes.sql": {
        *(('table', name) for name in ("gmail_pagamento_conexoes", "gmail_comprovantes")),
    },
    "019_gmail_plataforma.sql": {
        ('table', 'gmail_plataforma_conexao'),
    },
    "020_precos_publicos_frequency.sql": {
        ("column", "configuracao_frequency.public_pricing"),
    },
    "021_hardware_frequency.sql": {
        *(('column', f"planos_frequency.{column}") for column in ("max_monitores", "max_leitores")),
        *(('constraint', name) for name in (
            "planos_frequency_max_monitores_check", "planos_frequency_max_leitores_check",
            "leitores_tipo_integracao_check", "leitores_metodo_http_check",
        )),
        ("table", "monitores"),
    },
    "022_monitores_eventos_individuais.sql": {
        ("column", "presencas.monitor_id"),
        ("constraint", "presencas_monitor_fk"),
    },
    "023_sessoes_telas_acesso.sql": {
        ("table", "monitor_sessoes"),
        ("column", "presencas.monitor_session_id"),
        ("constraint", "presencas_monitor_session_fk"),
    },
    "024_relogio_local.sql": {
        ("table", "relogio_local"),
    },
    "025_codigo_monitor_persistente.sql": {
        ("column", "monitores.codigo_compartilhado"),
    },
    "026_status_comercial_academia.sql": {
        ("column", "academias.status_comercial"),
        ("constraint", "academias_status_comercial_check"),
    },
    "027_bairro_aluno.sql": {("column", "alunos.bairro")},
    "028_experiencia_7_dias.sql": {
        ("column", "academias.trial_inicio"),
        ("column", "academias.trial_fim"),
    },
    "029_prospeccao_comercial.sql": {
        ("table", "leads_prospeccao"),
        ("constraint", "leads_prospeccao_prioridade_check"),
        ("constraint", "leads_prospeccao_status_check"),
    },
    "030_configuracao_prospeccao.sql": {
        ("table", "configuracao_prospeccao"),
        ("column", "configuracao_prospeccao.whatsapp_template"),
        ("column", "configuracao_prospeccao.email_corpo_template"),
    },
    "031_prospeccao_osm.sql": {
        ("table", "prospeccao_regioes"),
        ("constraint", "leads_prospeccao_origem_check"),
    },
    "032_prospeccao_regiao_sem_coordenadas.sql": {("table", "prospeccao_regioes")},
    "033_gmail_prospeccao.sql": {("constraint", "gmail_plataforma_conexao_id_check")},
    "034_prospeccao_envios.sql": {
        ("table", "prospeccao_envios"),
        ("column", "leads_prospeccao.whatsapp_opt_in"),
    },
    "035_prospeccao_autorizacao_admin.sql": {
        ("column", "leads_prospeccao.whatsapp_autorizacao_admin_em"),
    },
    "036_email_verificacao.sql": {
        ("column", "usuarios.email_verificado_em"),
        ("column", "usuarios.email_verificacao_token_hash"),
        ("column", "usuarios.email_verificacao_expira_em"),
    },
    "037_limite_alunos_planos.sql": {
        ("column", "planos_frequency.max_alunos"),
        ("constraint", "planos_frequency_max_alunos_check"),
    },
    "038_site_analytics.sql": {("table", "site_visitas_diarias")},
    "041_reservas_aulas_areas.sql": {
        *(('table', name) for name in (
            "recursos_agendaveis", "sessoes_agendadas", "reservas_agendadas",
        )),
        *(('constraint', name) for name in (
            "sessoes_recurso_mesma_academia_fk",
            "reservas_sessao_mesma_academia_fk",
            "reservas_aluno_mesma_academia_fk",
            "reservas_cancelamento_check",
        )),
    },
    "042_vinculo_frequency_local.sql": {
        ("table", "sync_pairing_codes"),
        ("constraint", "sync_pairing_codes_code_hash_key"),
    },
}

# Migration 013 replaces the Spotify column from 009 with YouTube. Both
# schemas are valid evidence that 009 was applied before/after that upgrade.
MIGRATION_ALTERNATIVES: dict[str, tuple[set[tuple[str, str]], ...]] = {
    "009_recursos_premium.sql": (
        {("column", "planos_frequency.spotify"), ("constraint", "planos_frequency_recursos_check")},
        {("column", "planos_frequency.youtube"), ("constraint", "planos_frequency_recursos_check")},
    ),
}


def classify_migrations(
    tables: set[str],
    views: set[str],
    columns: set[str],
    constraints: set[str],
) -> dict[str, str]:
    present = {
        *(('table', name) for name in tables),
        *(('view', name) for name in views),
        *(('column', name) for name in columns),
        *(('constraint', name) for name in constraints),
    }
    states = {}
    for migration, required in REQUIRED_OBJECTS.items():
        count = len(required & present)
        alternatives = MIGRATION_ALTERNATIVES.get(migration, ())
        if alternatives:
            alternative_present = set().union(*alternatives)
            complete = count == len(required) and any(choice <= present for choice in alternatives)
            expected_found = count + len(alternative_present & present)
            expected_total = len(required) + len(alternative_present)
            states[migration] = (
                "todos os objetos esperados presentes" if complete
                else "nenhum objeto esperado encontrado" if expected_found == 0
                else "parcial — não reaplicar sem revisão"
            )
            continue
        states[migration] = (
            "todos os objetos esperados presentes" if count == len(required)
            else "nenhum objeto esperado encontrado" if count == 0
            else "parcial — não reaplicar sem revisão"
        )
    return states


def inspect() -> dict[str, str]:
    from database import get_connection

    with get_connection() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        relations = conn.execute(
            "SELECT table_name, table_type "
            "FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        ).fetchall()
        columns = conn.execute(
            "SELECT table_name, column_name "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        ).fetchall()
        constraints = conn.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE connamespace = 'public'::regnamespace"
        ).fetchall()

    tables = {row["table_name"] for row in relations if row["table_type"] == "BASE TABLE"}
    views = {row["table_name"] for row in relations if row["table_type"] == "VIEW"}
    column_names = {f"{row['table_name']}.{row['column_name']}" for row in columns}
    constraint_names = {row["conname"] for row in constraints}
    return classify_migrations(tables, views, column_names, constraint_names)


def main() -> int:
    try:
        states = inspect()
    except psycopg.Error:
        print("Não foi possível consultar a estrutura do banco configurado.", file=sys.stderr)
        print("Nenhum dado foi alterado. Confira a conexão no computador local.", file=sys.stderr)
        return 2

    print("Objetos estruturais das migrações Frequency (consulta somente leitura):")
    for migration, status in states.items():
        print(f"  {migration}: {status}")
    print(
        "Este resultado verifica objetos do esquema, não um histórico de execução. "
        "Se alguma migração aparecer parcial, faça backup e peça revisão antes de aplicar SQL."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

