"""Apply one validated local event to the read-only cloud replica."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import HTTPException
from psycopg import Connection, errors

from sync_protocol import (
    AlunoPayload,
    PagamentoPayload,
    PlanoPayload,
    PresencaPayload,
    SyncEvent,
    validar_payload,
)


def _aplicar_entidade(
    conn: Connection[Any],
    academia_id: int,
    evento: SyncEvent,
    payload: Any,
) -> None:
    academia = conn.execute(
        "SELECT moeda FROM academias WHERE id = %s",
        (academia_id,),
    ).fetchone()
    if academia is None:
        raise HTTPException(status_code=409, detail="sync_academia_nao_encontrada")
    moeda_padrao = academia["moeda"]

    if isinstance(payload, PlanoPayload):
        moeda = payload.moeda or moeda_padrao
        linha = conn.execute(
            "INSERT INTO planos "
            "(academia_id, nome, valor, moeda, duracao_dias, sync_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (sync_id) DO UPDATE SET "
            "nome = EXCLUDED.nome, valor = EXCLUDED.valor, moeda = EXCLUDED.moeda, "
            "duracao_dias = EXCLUDED.duracao_dias "
            "WHERE planos.academia_id = EXCLUDED.academia_id "
            "RETURNING id",
            (
                academia_id,
                payload.nome,
                payload.valor,
                moeda,
                payload.duracao_dias,
                payload.id,
            ),
        ).fetchone()
        if linha is None:
            raise HTTPException(status_code=409, detail="sync_entidade_incompativel")
        return

    if isinstance(payload, AlunoPayload):
        plano_id = None
        if payload.plano_id is not None:
            plano = conn.execute(
                "SELECT id FROM planos "
                "WHERE sync_id = %s AND academia_id = %s",
                (payload.plano_id, academia_id),
            ).fetchone()
            if plano is None:
                raise HTTPException(status_code=409, detail="sync_dependencia_ausente")
            plano_id = plano["id"]

        marcador_documento = f"SYNC:{payload.id}"
        linha = conn.execute(
            "INSERT INTO alunos "
            "(academia_id, nome, telefone, documento, data_nascimento, "
            "data_inicio, plano_id, id_biometria, status, sync_id) "
            "VALUES (%s, %s, NULL, %s, NULL, %s, %s, NULL, %s, %s) "
            "ON CONFLICT (sync_id) DO UPDATE SET "
            "nome = EXCLUDED.nome, telefone = NULL, "
            "documento = EXCLUDED.documento, data_nascimento = NULL, "
            "data_inicio = COALESCE(%s, alunos.data_inicio), "
            "plano_id = EXCLUDED.plano_id, id_biometria = NULL, "
            "status = EXCLUDED.status "
            "WHERE alunos.academia_id = EXCLUDED.academia_id "
            "RETURNING id",
            (
                academia_id,
                payload.nome,
                marcador_documento,
                payload.data_inicio or date.today(),
                plano_id,
                payload.status,
                payload.id,
                payload.data_inicio,
            ),
        ).fetchone()
        if linha is None:
            raise HTTPException(status_code=409, detail="sync_entidade_incompativel")
        return

    if isinstance(payload, PagamentoPayload):
        moeda = payload.moeda or moeda_padrao
        aluno = conn.execute(
            "SELECT id FROM alunos "
            "WHERE sync_id = %s AND academia_id = %s",
            (payload.aluno_id, academia_id),
        ).fetchone()
        if aluno is None:
            raise HTTPException(status_code=409, detail="sync_dependencia_ausente")

        linha = conn.execute(
            "INSERT INTO pagamentos "
            "(academia_id, aluno_id, valor, moeda, vencimento, data_pagamento, status, sync_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (sync_id) DO UPDATE SET "
            "aluno_id = EXCLUDED.aluno_id, valor = EXCLUDED.valor, moeda = EXCLUDED.moeda, "
            "vencimento = EXCLUDED.vencimento, "
            "data_pagamento = EXCLUDED.data_pagamento, status = EXCLUDED.status "
            "WHERE pagamentos.academia_id = EXCLUDED.academia_id "
            "RETURNING id",
            (
                academia_id,
                aluno["id"],
                payload.valor,
                moeda,
                payload.vencimento,
                payload.data_pagamento,
                payload.status,
                payload.id,
            ),
        ).fetchone()
        if linha is None:
            raise HTTPException(status_code=409, detail="sync_entidade_incompativel")
        return

    if isinstance(payload, PresencaPayload):
        aluno_id = None
        if payload.aluno_id is not None:
            aluno = conn.execute(
                "SELECT id FROM alunos "
                "WHERE sync_id = %s AND academia_id = %s",
                (payload.aluno_id, academia_id),
            ).fetchone()
            if aluno is None:
                raise HTTPException(status_code=409, detail="sync_dependencia_ausente")
            aluno_id = aluno["id"]

        linha = conn.execute(
            "INSERT INTO presencas "
            "(academia_id, aluno_id, data_hora, liberado, motivo, sync_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (sync_id) DO UPDATE SET "
            "aluno_id = EXCLUDED.aluno_id, data_hora = EXCLUDED.data_hora, "
            "liberado = EXCLUDED.liberado, motivo = EXCLUDED.motivo "
            "WHERE presencas.academia_id = EXCLUDED.academia_id "
            "RETURNING id",
            (
                academia_id,
                aluno_id,
                payload.data_hora_local,
                payload.liberado,
                payload.motivo,
                payload.id,
            ),
        ).fetchone()
        if linha is None:
            raise HTTPException(status_code=409, detail="sync_entidade_incompativel")
        return

    raise HTTPException(status_code=422, detail="sync_tipo_nao_suportado")


def receber_evento(
    conn: Connection[Any],
    *,
    academia_id: int,
    source_academia_sync_id,
    evento: SyncEvent,
) -> bool:
    if evento.academia_sync_id != source_academia_sync_id:
        raise HTTPException(status_code=403, detail="sync_origem_invalida")

    try:
        payload = validar_payload(evento)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="sync_evento_invalido") from error

    conn.execute(
        "INSERT INTO sync_receive_state "
        "(source_academia_sync_id, academia_id) VALUES (%s, %s) "
        "ON CONFLICT (source_academia_sync_id) DO NOTHING",
        (source_academia_sync_id, academia_id),
    )
    state = conn.execute(
        "SELECT academia_id, last_revision FROM sync_receive_state "
        "WHERE source_academia_sync_id = %s FOR UPDATE",
        (source_academia_sync_id,),
    ).fetchone()
    if state is None or state["academia_id"] != academia_id:
        raise HTTPException(status_code=409, detail="sync_vinculo_incompativel")

    old_event = conn.execute(
        "SELECT source_academia_sync_id, revision FROM sync_inbox "
        "WHERE event_id = %s",
        (evento.event_id,),
    ).fetchone()
    if old_event is not None:
        if (
            old_event["source_academia_sync_id"] == source_academia_sync_id
            and old_event["revision"] == evento.revision
        ):
            return True
        raise HTTPException(status_code=409, detail="sync_evento_reutilizado")

    if evento.revision <= state["last_revision"]:
        prior_revision = conn.execute(
            "SELECT event_id FROM sync_inbox "
            "WHERE source_academia_sync_id = %s AND revision = %s",
            (source_academia_sync_id, evento.revision),
        ).fetchone()
        if prior_revision and prior_revision["event_id"] == evento.event_id:
            return True
        raise HTTPException(status_code=409, detail="sync_revisao_duplicada")

    if evento.revision != state["last_revision"] + 1:
        raise HTTPException(status_code=409, detail="sync_revisao_fora_de_ordem")

    try:
        if evento.operation == "delete":
            if evento.entity_type == "plano":
                tabela = "planos"
            elif evento.entity_type == "pagamento":
                tabela = "pagamentos"
            else:
                raise HTTPException(status_code=422, detail="sync_exclusao_nao_suportada")
            conn.execute(
                f"DELETE FROM {tabela} WHERE academia_id = %s AND sync_id = %s",
                (academia_id, evento.entity_sync_id),
            )
        else:
            _aplicar_entidade(conn, academia_id, evento, payload)
        conn.execute(
            "INSERT INTO sync_inbox "
            "(event_id, academia_id, source_academia_sync_id, revision, "
            "entity_type, entity_sync_id) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                evento.event_id,
                academia_id,
                source_academia_sync_id,
                evento.revision,
                evento.entity_type,
                evento.entity_sync_id,
            ),
        )
        conn.execute(
            "UPDATE sync_receive_state SET last_revision = %s, updated_at = now() "
            "WHERE source_academia_sync_id = %s",
            (evento.revision, source_academia_sync_id),
        )
    except (errors.UniqueViolation, errors.ForeignKeyViolation) as error:
        raise HTTPException(status_code=409, detail="sync_referencia_incompativel") from error

    return False
