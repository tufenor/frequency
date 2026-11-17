"""Create or rotate one per-academy inbound sync token on the cloud server."""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
from uuid import UUID

from database import get_connection


def configurar_credencial(academia_id: int, source_id: UUID, *, rotate: bool) -> str:
    if os.getenv("SYNC_RECEIVER_ENABLED", "").strip().upper() != "YES":
        raise RuntimeError("Habilite o receptor somente depois de configurar HTTPS.")

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()

    with get_connection() as conn:
        academia = conn.execute(
            "SELECT id FROM academias WHERE id = %s FOR UPDATE",
            (academia_id,),
        ).fetchone()
        if academia is None:
            raise ValueError("Academia de destino não encontrada no servidor.")

        current = conn.execute(
            "SELECT source_academia_sync_id, academia_id "
            "FROM sync_credentials "
            "WHERE source_academia_sync_id = %s OR academia_id = %s "
            "FOR UPDATE",
            (source_id, academia_id),
        ).fetchall()

        if current:
            same_pair = (
                len(current) == 1
                and current[0]["source_academia_sync_id"] == source_id
                and current[0]["academia_id"] == academia_id
            )
            if not same_pair:
                raise ValueError(
                    "Este identificador local ou academia já está vinculado a outro par."
                )
            if not rotate:
                raise ValueError(
                    "A credencial já existe. Use --rotacionar para substituir a chave."
                )
            conn.execute(
                "UPDATE sync_credentials SET token_hash = %s, enabled = true, "
                "rotated_at = now() WHERE source_academia_sync_id = %s "
                "AND academia_id = %s",
                (token_hash, source_id, academia_id),
            )
        else:
            conn.execute(
                "INSERT INTO sync_credentials "
                "(source_academia_sync_id, academia_id, token_hash) "
                "VALUES (%s, %s, %s)",
                (source_id, academia_id, token_hash),
            )

    return token


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Vincula uma instalação local a uma academia na nuvem e mostra "
            "uma chave de envio uma única vez. Execute apenas no servidor HTTPS."
        )
    )
    parser.add_argument("academia_id", type=int, help="ID da academia na nuvem")
    parser.add_argument(
        "source_academia_sync_id",
        type=UUID,
        help="UUID local informado por /sync/estado-local",
    )
    parser.add_argument(
        "--rotacionar",
        action="store_true",
        help="substitui a chave do mesmo vínculo e invalida a anterior",
    )
    args = parser.parse_args()

    try:
        token = configurar_credencial(
            args.academia_id,
            args.source_academia_sync_id,
            rotate=args.rotacionar,
        )
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))

    print("Credencial criada. Copie-a diretamente para a configuração local protegida:")
    print(token)
    print("Não compartilhe essa chave por mensagens nem a coloque no Git.")


if __name__ == "__main__":
    main()
