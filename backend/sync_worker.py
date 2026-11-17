"""Deliver the local outbox to the configured HTTPS Frequency replica.

The worker is opt-in. It sends one revision at a time, never logs credentials
or event bodies, and keeps failed events in order for an idempotent retry.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

from database import get_connection
from sincronizacao import outbox_ativa, sync_id_academia


LOGGER = logging.getLogger("frequency.sync")
MAX_EVENT_BYTES = 128 * 1024
LEASE_SECONDS = 120
REQUEST_TIMEOUT_SECONDS = 20
MAX_BACKOFF_SECONDS = 60 * 60


class SyncConfigurationError(RuntimeError):
    """Safe-to-log setup error; messages never contain secret values."""


def _configurar() -> tuple[int, str, str, int]:
    if os.getenv("SYNC_WORKER_ENABLED", "").strip().upper() != "YES":
        raise SyncConfigurationError("SYNC_WORKER_ENABLED precisa ser YES para iniciar o envio.")
    if not outbox_ativa():
        raise SyncConfigurationError("SYNC_OUTBOX_ENABLED precisa ser YES para iniciar o envio.")

    local_id_text = os.getenv("SYNC_LOCAL_ACADEMY_ID", "").strip()
    if not local_id_text.isdecimal() or int(local_id_text) < 1:
        raise SyncConfigurationError("Configure o ID numérico local em SYNC_LOCAL_ACADEMY_ID.")
    local_id = int(local_id_text)

    remote_url = os.getenv("SYNC_REMOTE_URL", "").strip()
    parsed = urlsplit(remote_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/sync/receber"
    ):
        raise SyncConfigurationError(
            "SYNC_REMOTE_URL deve ser o endereço HTTPS completo terminado em /sync/receber."
        )

    token = os.getenv("SYNC_REMOTE_TOKEN", "").strip()
    try:
        token_length = len(token.encode("ascii"))
    except UnicodeEncodeError as error:
        raise SyncConfigurationError("SYNC_REMOTE_TOKEN tem formato inválido.") from error
    if not 40 <= token_length <= 256:
        raise SyncConfigurationError("Configure a credencial remota em SYNC_REMOTE_TOKEN.")

    poll_text = os.getenv("SYNC_WORKER_POLL_SECONDS", "10").strip()
    if not poll_text.isdecimal() or not 2 <= int(poll_text) <= 60:
        raise SyncConfigurationError("SYNC_WORKER_POLL_SECONDS deve ficar entre 2 e 60.")

    return local_id, remote_url, token, int(poll_text)


def _identificar_academia(conn, local_id: int) -> UUID:
    source_id = UUID(str(sync_id_academia(conn, local_id)))
    snapshot = conn.execute(
        "SELECT 1 FROM sync_snapshot_runs WHERE academia_sync_id = %s",
        (source_id,),
    ).fetchone()
    if snapshot is None:
        raise SyncConfigurationError(
            "Enfileire o snapshot inicial da academia antes de iniciar a sincronização."
        )
    return source_id


def _revisao_mais_antiga(conn, source_id: UUID) -> dict | None:
    with conn.transaction():
        row = conn.execute(
            "SELECT event_id, academia_sync_id, revision, entity_type, "
            "entity_sync_id, operation, schema_version, payload, "
            "attempt_count, next_attempt_at, lease_until "
            "FROM sync_outbox "
            "WHERE academia_sync_id = %s AND delivered_at IS NULL "
            "ORDER BY revision LIMIT 1",
            (source_id,),
        ).fetchone()
        if row is None:
            return None

        now = datetime.now(timezone.utc)
        if row["next_attempt_at"] > now:
            return {"wait_seconds": min(15, max(1, (row["next_attempt_at"] - now).total_seconds()))}
        if row["lease_until"] is not None and row["lease_until"] > now:
            return {"wait_seconds": min(15, max(1, (row["lease_until"] - now).total_seconds()))}

        claimed = conn.execute(
            "UPDATE sync_outbox SET lease_until = now() + (%s * interval '1 second'), "
            "attempt_count = attempt_count + 1 "
            "WHERE event_id = %s AND delivered_at IS NULL "
            "RETURNING attempt_count",
            (LEASE_SECONDS, row["event_id"]),
        ).fetchone()
        if claimed is None:
            return {"wait_seconds": 1}

        event = {
            "event_id": str(row["event_id"]),
            "academia_sync_id": str(row["academia_sync_id"]),
            "revision": row["revision"],
            "entity_type": row["entity_type"],
            "entity_sync_id": str(row["entity_sync_id"]),
            "operation": row["operation"],
            "schema_version": row["schema_version"],
            "payload": row["payload"],
        }
        return {
            "event": event,
            "event_id": row["event_id"],
            "revision": row["revision"],
            "attempt_count": claimed["attempt_count"],
        }


def _enviar(remote_url: str, token: str, source_id: UUID, event: dict) -> None:
    try:
        body = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        raise RuntimeError("invalid_event") from None
    if len(body) > MAX_EVENT_BYTES:
        raise ValueError("event_too_large")

    request = Request(
        remote_url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Frequency-Academy-ID": str(source_id),
        },
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RuntimeError(f"http_{response.status}")
            raw = response.read(4097)
    except HTTPError as error:
        raise RuntimeError(f"http_{error.code}") from None
    except URLError as error:
        reason = error.reason
        if isinstance(reason, TimeoutError):
            raise RuntimeError("network_timeout") from None
        raise RuntimeError("network_error") from None
    except TimeoutError:
        raise RuntimeError("network_timeout") from None
    except OSError:
        raise RuntimeError("network_error") from None

    if len(raw) > 4096:
        raise RuntimeError("invalid_ack")
    try:
        ack = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("invalid_ack") from None
    if not isinstance(ack, dict) or (
        ack.get("received") is not True
        or ack.get("event_id") != event["event_id"]
        or ack.get("revision") != event["revision"]
    ):
        raise RuntimeError("invalid_ack")


def _confirmar(conn, event_id, revision: int) -> None:
    with conn.transaction():
        row = conn.execute(
            "UPDATE sync_outbox SET delivered_at = now(), lease_until = NULL, "
            "last_error_code = NULL "
            "WHERE event_id = %s AND revision = %s AND delivered_at IS NULL "
            "RETURNING event_id",
            (event_id, revision),
        ).fetchone()
        if row is None:
            raise RuntimeError("ack_state_mismatch")


def _reprogramar(conn, event_id, revision: int, attempts: int, code: str) -> None:
    delay = min(MAX_BACKOFF_SECONDS, 5 * (2 ** min(max(attempts - 1, 0), 10)))
    with conn.transaction():
        conn.execute(
            "UPDATE sync_outbox SET lease_until = NULL, next_attempt_at = "
            "now() + (%s * interval '1 second'), last_error_code = %s "
            "WHERE event_id = %s AND revision = %s AND delivered_at IS NULL",
            (delay, code[:40], event_id, revision),
        )


def executar() -> None:
    local_id, remote_url, token, poll_seconds = _configurar()

    with get_connection() as conn:
        conn.autocommit = True
        source_id = _identificar_academia(conn, local_id)
        lock = conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS acquired",
            (str(source_id),),
        ).fetchone()
        if not lock or not lock["acquired"]:
            raise RuntimeError("Já existe um processo de envio para esta academia.")

        LOGGER.info("Sincronização local iniciada; o conteúdo dos eventos não é registrado.")
        try:
            while True:
                item = _revisao_mais_antiga(conn, source_id)
                if item is None:
                    time.sleep(poll_seconds)
                    continue
                if "wait_seconds" in item:
                    time.sleep(item["wait_seconds"])
                    continue

                try:
                    _enviar(remote_url, token, source_id, item["event"])
                    _confirmar(conn, item["event_id"], item["revision"])
                    LOGGER.info("Revisão %s enviada e confirmada.", item["revision"])
                except (RuntimeError, ValueError) as error:
                    raw_code = str(error)
                    if raw_code in {
                        "event_too_large",
                        "invalid_event",
                        "invalid_ack",
                        "ack_state_mismatch",
                        "network_timeout",
                        "network_error",
                    }:
                        code = raw_code
                    elif raw_code.startswith("http_") and raw_code[5:].isdecimal():
                        code = raw_code
                    else:
                        code = "network_error"
                    _reprogramar(
                        conn,
                        item["event_id"],
                        item["revision"],
                        item["attempt_count"],
                        code,
                    )
                    LOGGER.warning("Revisão %s não confirmada (%s).", item["revision"], code)
        finally:
            conn.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                (str(source_id),),
            )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        executar()
    except KeyboardInterrupt:
        LOGGER.info("Sincronização local encerrada.")
    except SyncConfigurationError as error:
        LOGGER.error("Configuração do envio: %s", error)
        raise SystemExit(2) from None
    except Exception as error:
        # Do not include exception text: driver and HTTP errors can contain URLs.
        LOGGER.error("Sincronização não iniciada ou interrompida (%s).", type(error).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
