"""Queue a one-time, privacy-minimized baseline for one local academy.

Run only after migration 003 has been applied to a disposable/staging database
and a tested backup exists. The outbox flag must be explicitly enabled.
This command writes only to the local PostgreSQL database; it does not contact
the cloud.
"""

from __future__ import annotations

import argparse
from datetime import date
from database import get_connection
from sincronizacao import (
    enfileirar_evento,
    outbox_ativa,
    sync_id_academia,
)


def enfileirar_snapshot(academia_id: int) -> int:
    if not outbox_ativa():
        raise RuntimeError(
            "Fila desativada. Aplique e valide a migração 003 antes de habilitá-la."
        )

    with get_connection() as conn:
        academia = conn.execute(
            "SELECT id FROM academias WHERE id = %s",
            (academia_id,),
        ).fetchone()
        if academia is None:
            raise ValueError("Academia não encontrada.")

        academia_uuid = sync_id_academia(conn, academia_id)
        conn.execute(
            "INSERT INTO sync_revision_counters (academia_sync_id) "
            "VALUES (%s) ON CONFLICT (academia_sync_id) DO NOTHING",
            (academia_uuid,),
        )
        conn.execute(
            "SELECT last_revision FROM sync_revision_counters "
            "WHERE academia_sync_id = %s FOR UPDATE",
            (academia_uuid,),
        ).fetchone()

        ja_gerado = conn.execute(
            "SELECT 1 FROM sync_snapshot_runs WHERE academia_sync_id = %s",
            (academia_uuid,),
        ).fetchone()
        if ja_gerado is not None:
            raise ValueError(
                "O snapshot inicial desta academia já foi enfileirado."
            )

        evento_count = 0

        planos = conn.execute(
            "SELECT sync_id, nome, valor, moeda, duracao_dias "
            "FROM planos WHERE academia_id = %s ORDER BY id",
            (academia_id,),
        ).fetchall()
        for plano in planos:
            enfileirar_evento(
                conn,
                academia_sync_id=academia_uuid,
                entity_type="plano",
                entity_sync_id=plano["sync_id"],
                payload={
                    "id": str(plano["sync_id"]),
                    "nome": plano["nome"],
                    "valor": str(plano["valor"]),
                    "moeda": plano["moeda"],
                    "duracao_dias": plano["duracao_dias"],
                },
            )
            evento_count += 1

        alunos = conn.execute(
            "SELECT a.sync_id, a.nome, a.status, a.data_inicio, "
            "pl.sync_id AS plano_sync_id "
            "FROM alunos a "
            "LEFT JOIN planos pl "
            "ON pl.id = a.plano_id AND pl.academia_id = a.academia_id "
            "WHERE a.academia_id = %s ORDER BY a.id",
            (academia_id,),
        ).fetchall()
        for aluno in alunos:
            enfileirar_evento(
                conn,
                academia_sync_id=academia_uuid,
                entity_type="aluno",
                entity_sync_id=aluno["sync_id"],
                payload={
                    "id": str(aluno["sync_id"]),
                    "nome": aluno["nome"],
                    "status": aluno["status"],
                    "plano_id": (
                        str(aluno["plano_sync_id"])
                        if aluno["plano_sync_id"] is not None
                        else None
                    ),
                    "data_inicio": aluno["data_inicio"].isoformat(),
                },
            )
            evento_count += 1

        pagamentos = conn.execute(
            "SELECT p.sync_id, a.sync_id AS aluno_sync_id, p.valor, p.moeda, "
            "p.vencimento, p.data_pagamento, p.status "
            "FROM pagamentos p "
            "JOIN alunos a ON a.id = p.aluno_id "
            "AND a.academia_id = p.academia_id "
            "WHERE p.academia_id = %s ORDER BY p.id",
            (academia_id,),
        ).fetchall()
        for pagamento in pagamentos:
            data_pagamento: date | None = pagamento["data_pagamento"]
            enfileirar_evento(
                conn,
                academia_sync_id=academia_uuid,
                entity_type="pagamento",
                entity_sync_id=pagamento["sync_id"],
                payload={
                    "id": str(pagamento["sync_id"]),
                    "aluno_id": str(pagamento["aluno_sync_id"]),
                    "valor": str(pagamento["valor"]),
                    "moeda": pagamento["moeda"],
                    "vencimento": pagamento["vencimento"].isoformat(),
                    "data_pagamento": (
                        data_pagamento.isoformat() if data_pagamento else None
                    ),
                    "status": pagamento["status"],
                },
            )
            evento_count += 1

        presencas = conn.execute(
            "SELECT p.sync_id, a.sync_id AS aluno_sync_id, p.data_hora, "
            "p.liberado, p.motivo "
            "FROM presencas p "
            "LEFT JOIN alunos a ON a.id = p.aluno_id "
            "AND a.academia_id = p.academia_id "
            "WHERE p.academia_id = %s ORDER BY p.id",
            (academia_id,),
        ).fetchall()
        for presenca in presencas:
            aluno_sync_id = presenca["aluno_sync_id"]
            enfileirar_evento(
                conn,
                academia_sync_id=academia_uuid,
                entity_type="presenca",
                entity_sync_id=presenca["sync_id"],
                payload={
                    "id": str(presenca["sync_id"]),
                    "aluno_id": str(aluno_sync_id) if aluno_sync_id else None,
                    "data_hora_local": presenca["data_hora"].isoformat(),
                    "liberado": presenca["liberado"],
                    "motivo": presenca["motivo"],
                },
            )
            evento_count += 1

        conn.execute(
            "INSERT INTO sync_snapshot_runs (academia_sync_id, event_count) "
            "VALUES (%s, %s)",
            (academia_uuid, evento_count),
        )

    return evento_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Enfileira uma única fotografia inicial dos dados da academia "
            "na fila local; não envia informações pela internet."
        )
    )
    parser.add_argument("academia_id", type=int, help="ID numérico da academia")
    args = parser.parse_args()

    try:
        total = enfileirar_snapshot(args.academia_id)
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))

    print(f"Snapshot local enfileirado: {total} eventos.")
    print("Nenhum dado foi enviado a um servidor remoto.")


if __name__ == "__main__":
    main()
