"""Transactional outbox primitives for local-to-cloud synchronization.

The outbox stays disabled by default. When enabled, callers must use the same
database connection and transaction as the local write they are recording.
Per-academy revisions are allocated under a row lock so committed transactions
cannot be delivered out of order.
"""

from __future__ import annotations

import os
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb


def outbox_ativa() -> bool:
    return os.getenv("SYNC_OUTBOX_ENABLED", "").strip().upper() == "YES"


def sync_id_academia(conn: Connection[Any], academia_id: int):
    academia = conn.execute(
        "SELECT sync_id FROM academias WHERE id = %s",
        (academia_id,),
    ).fetchone()
    if academia is None:
        raise RuntimeError("Academia local sem identificador de sincronização.")
    return academia["sync_id"]


def reservar_revisao(conn: Connection[Any], academia_sync_id) -> int:
    conn.execute(
        "INSERT INTO sync_revision_counters (academia_sync_id) "
        "VALUES (%s) ON CONFLICT (academia_sync_id) DO NOTHING",
        (academia_sync_id,),
    )
    counter = conn.execute(
        "UPDATE sync_revision_counters "
        "SET last_revision = last_revision + 1 "
        "WHERE academia_sync_id = %s "
        "RETURNING last_revision",
        (academia_sync_id,),
    ).fetchone()
    if counter is None:
        raise RuntimeError("Não foi possível reservar a revisão de sincronização.")
    return counter["last_revision"]


def enfileirar_evento(
    conn: Connection[Any],
    *,
    academia_sync_id,
    entity_type: str,
    entity_sync_id,
    payload: dict[str, Any],
    operation: str = "upsert",
) -> None:
    if not outbox_ativa():
        return

    revision = reservar_revisao(conn, academia_sync_id)

    conn.execute(
        "INSERT INTO sync_outbox "
        "(academia_sync_id, revision, entity_type, entity_sync_id, "
        "operation, schema_version, payload) "
        "VALUES (%s, %s, %s, %s, %s, 1, %s)",
        (
            academia_sync_id,
            revision,
            entity_type,
            entity_sync_id,
            operation,
            Jsonb(payload),
        ),
    )
