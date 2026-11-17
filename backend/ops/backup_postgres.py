"""Create an encrypted PostgreSQL backup and copy it to S3-compatible storage.

This command is intentionally disabled unless BACKUP_ENABLE=YES is set.
It keeps encrypted local archives when the remote upload is unavailable and
retries those archives on the next scheduled run.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_DIR = BACKEND_DIR / ".backups"
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SAFE_PREFIX = re.compile(r"^(?:[A-Za-z0-9_-]{1,64}(?:/[A-Za-z0-9_-]{1,64})*)?$")
SAFE_ARCHIVE_NAME = re.compile(r"^frequency_\d{8}T\d{6}Z\.dump\.age$")
STATUS_FILENAME = "frequency-backup-status.json"


class BackupError(Exception):
    """A safe-to-display backup failure without command output or secrets."""


def status_file() -> Path:
    """Return the local status path without exposing configuration values."""
    configured = os.getenv("BACKUP_STATUS_FILE", "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_BACKUP_DIR / STATUS_FILENAME


def write_status(
    status: str,
    *,
    uploaded: int = 0,
    pending: int | None = None,
    message: str | None = None,
) -> None:
    """Atomically publish a small, non-sensitive status document for operators."""
    if status not in {"sucesso", "falha", "desativado"}:
        raise ValueError("status de backup inválido")
    payload: dict[str, object] = {
        "schema": 1,
        "status": status,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "uploaded": max(0, int(uploaded)),
    }
    if pending is not None:
        payload["pending"] = max(0, int(pending))
    if message:
        payload["message"] = str(message)[:240]

    destination = status_file()
    temporary_name: str | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, ensure_ascii=False, separators=(",", ":"))
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
    except OSError as exc:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise BackupError("Não foi possível registrar o estado do backup.") from exc


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise BackupError(f"Configuração ausente: {name}.")
    return value


def command_path(variable: str, default: str) -> str:
    configured = os.getenv(variable, "").strip()
    resolved = configured or shutil.which(default)
    if not resolved:
        raise BackupError(f"Programa necessário não encontrado: {default}.")
    return resolved


def backup_directory() -> Path:
    configured = os.getenv("BACKUP_LOCAL_DIR", "").strip()
    if configured:
        raw_path = configured
    else:
        user_root = os.getenv("USERPROFILE", "").strip()
        # The implicit destination is always local. Cloud folders are used
        # only after the administrator explicitly selects them in the UI.
        raw_path = str(Path(user_root) / "Frequency Backups") if user_root else str(DEFAULT_BACKUP_DIR)
    path = Path(raw_path).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    try:
        probe = path / ".frequency-backup-write-check"
        with probe.open("xb"):
            pass
        probe.unlink()
    except OSError as exc:
        raise BackupError("A pasta configurada para backups não permite gravação.") from exc
    return path


def libpq_environment() -> dict[str, str]:
    settings = {
        "PGHOST": required("DB_HOST"),
        "PGPORT": os.getenv("DB_PORT", "5432").strip() or "5432",
        "PGDATABASE": required("DB_NAME"),
        "PGUSER": required("DB_USER"),
        "PGCONNECT_TIMEOUT": os.getenv("BACKUP_CONNECT_TIMEOUT", "10").strip() or "10",
        "PGSSLMODE": os.getenv("DB_SSLMODE", "prefer").strip() or "prefer",
    }
    password = os.getenv("DB_PASSWORD")
    environment = dict(os.environ)
    # Do not inherit an unrelated password from the scheduler's environment.
    environment.pop("PGPASSWORD", None)
    if password:
        settings["PGPASSWORD"] = password
    return {**environment, **settings}


def create_encrypted_dump(
    pg_dump: str,
    age: str,
    recipient: str,
    destination: Path,
    db_environment: dict[str, str],
) -> None:
    command = [
        pg_dump,
        "--format=custom",
        "--no-password",
        "--no-owner",
        "--no-acl",
    ]
    age_command = [age, "--encrypt", "--recipient", recipient]

    try:
        with destination.open("xb") as encrypted_file:
            dump_process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=db_environment,
            )
            assert dump_process.stdout is not None
            try:
                encrypt_process = subprocess.Popen(
                    age_command,
                    stdin=dump_process.stdout,
                    stdout=encrypted_file,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                dump_process.stdout.close()
                dump_process.terminate()
                dump_process.wait()
                raise

            dump_process.stdout.close()
            encrypt_status = encrypt_process.wait()
            dump_status = dump_process.wait()
            encrypted_file.flush()
            os.fsync(encrypted_file.fileno())
    except FileExistsError as exc:
        raise BackupError("Já existe um arquivo de backup com esse nome.") from exc
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise BackupError("Não foi possível iniciar o dump ou a criptografia.") from exc

    if encrypt_status != 0 or dump_status != 0 or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise BackupError("O dump do PostgreSQL ou a criptografia falhou.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as content:
        for block in iter(lambda: content.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def aws_base_command(aws: str, include_s3_endpoint: bool = True) -> list[str]:
    command = [aws, "--no-cli-pager"]
    region = os.getenv("AWS_REGION", "").strip()
    if region:
        command.extend(["--region", region])
    endpoint = os.getenv("BACKUP_S3_ENDPOINT_URL", "").strip() if include_s3_endpoint else ""
    if endpoint:
        command.extend(["--endpoint-url", endpoint])
    return command


def remote_sha256_valid(checksum: object, checksum_type: object, local_digest: str) -> bool:
    """Validate S3's stored SHA-256, accounting for multipart composite checksums."""
    if not isinstance(checksum, str):
        return False
    if checksum_type == "FULL_OBJECT":
        expected = base64.b64encode(bytes.fromhex(local_digest)).decode("ascii")
        return checksum == expected
    if checksum_type != "COMPOSITE":
        return False

    encoded, separator, part_count = checksum.rpartition("-")
    if not separator or not part_count.isdecimal() or int(part_count) < 1:
        return False
    try:
        part_digest = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return False
    return len(part_digest) == hashlib.sha256().digest_size


def s3_key_for(path: Path, node_id: str, prefix: str) -> str:
    pieces = [piece for piece in (prefix.strip("/"), node_id) if piece]
    return "/".join([*pieces, path.name])


def upload_and_verify(
    aws: str,
    bucket: str,
    key: str,
    path: Path,
) -> None:
    digest = sha256_file(path)
    base = aws_base_command(aws)
    source = str(path)
    destination = f"s3://{bucket}/{key}"
    upload = [
        *base,
        "s3",
        "cp",
        source,
        destination,
        "--only-show-errors",
        "--checksum-algorithm",
        "SHA256",
        "--metadata",
        f"sha256={digest}",
    ]
    try:
        subprocess.run(upload, check=True, capture_output=True, text=True)
        verify = [
            *base,
            "s3api",
            "head-object",
            "--bucket",
            bucket,
            "--key",
            key,
            "--checksum-mode",
            "ENABLED",
            "--query",
            "{size:ContentLength,metadata_digest:Metadata.sha256,checksum:ChecksumSHA256,checksum_type:ChecksumType}",
            "--output",
            "json",
        ]
        result = subprocess.run(
            verify,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BackupError("O envio ou a conferência do backup remoto falhou.") from exc

    try:
        remote_metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BackupError("A resposta do armazenamento remoto não pôde ser conferida.") from exc
    if not isinstance(remote_metadata, dict):
        raise BackupError("A resposta do armazenamento remoto não pôde ser conferida.")
    if (
        remote_metadata.get("size") != path.stat().st_size
        or str(remote_metadata.get("metadata_digest", "")).lower() != digest
        or not remote_sha256_valid(
            remote_metadata.get("checksum"),
            remote_metadata.get("checksum_type"),
            digest,
        )
    ):
        raise BackupError("O backup remoto não passou na conferência SHA-256.")

    marker = path.with_name(path.name + ".uploaded")
    try:
        marker.write_text(key, encoding="utf-8")
    except OSError as exc:
        raise BackupError("O backup foi enviado, mas não foi possível registrar o envio local.") from exc


def remote_prefix(prefix: str) -> str:
    return prefix.strip("/")


def node_key_prefix(prefix: str, node_id: str) -> str:
    pieces = [piece for piece in (remote_prefix(prefix), node_id) if piece]
    return "/".join(pieces) + "/"


def list_remote_objects(aws: str, bucket: str, prefix: str) -> dict[str, dict[str, object]]:
    root = remote_prefix(prefix)
    list_prefix = root + "/" if root else ""
    command = [
        *aws_base_command(aws),
        "s3api",
        "list-objects-v2",
        "--bucket",
        bucket,
        "--prefix",
        list_prefix,
        "--output",
        "json",
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BackupError("Não foi possível conferir os arquivos no armazenamento remoto.") from exc

    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BackupError("A lista do armazenamento remoto não pôde ser conferida.") from exc
    if not isinstance(response, dict) or response.get("IsTruncated") is True:
        raise BackupError("A lista do armazenamento remoto está incompleta.")

    contents = response.get("Contents", [])
    if not isinstance(contents, list):
        raise BackupError("A lista do armazenamento remoto não pôde ser conferida.")

    objects: dict[str, dict[str, object]] = {}
    for item in contents:
        if not isinstance(item, dict):
            raise BackupError("A lista do armazenamento remoto não pôde ser conferida.")
        key = item.get("Key")
        size = item.get("Size")
        if not isinstance(key, str) or not isinstance(size, int) or size < 0:
            raise BackupError("A lista do armazenamento remoto não pôde ser conferida.")
        objects[key] = {"size": size, "last_modified": item.get("LastModified")}
    return objects


def ensure_bucket_unversioned(aws: str, bucket: str, provider: str) -> None:
    if provider == "lightsail":
        command = [
            *aws_base_command(aws, include_s3_endpoint=False),
            "lightsail",
            "get-buckets",
            "--bucket-name",
            bucket,
            "--query",
            "buckets[0].objectVersioning",
            "--output",
            "text",
        ]
    else:
        command = [
            *aws_base_command(aws),
            "s3api",
            "get-bucket-versioning",
            "--bucket",
            bucket,
            "--output",
            "json",
        ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        response = json.loads(result.stdout) if provider == "s3" else result.stdout.strip()
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise BackupError("Não foi possível conferir se o bucket usa versões de objetos.") from exc
    if provider == "s3":
        unversioned = isinstance(response, dict) and response.get("Status") in (None, "Disabled")
    else:
        unversioned = response == "NeverEnabled"
    if not unversioned:
        raise BackupError(
            "O bucket precisa estar sem versionamento para que a retenção e o limite de espaço funcionem."
        )


def remote_modified(value: object) -> datetime:
    if not isinstance(value, str):
        raise BackupError("A data de um backup remoto não pôde ser conferida.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BackupError("A data de um backup remoto não pôde ser conferida.") from exc
    if parsed.tzinfo is None:
        raise BackupError("A data de um backup remoto não pôde ser conferida.")
    return parsed.astimezone(timezone.utc)


def delete_remote_object(aws: str, bucket: str, key: str) -> None:
    command = [
        *aws_base_command(aws),
        "s3api",
        "delete-object",
        "--bucket",
        bucket,
        "--key",
        key,
        "--output",
        "json",
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BackupError("Não foi possível remover um backup remoto vencido.") from exc


def prune_expired_remote_backups(
    aws: str,
    bucket: str,
    prefix: str,
    node_id: str,
    objects: dict[str, dict[str, object]],
    retention_days: int,
    now: datetime,
) -> dict[str, dict[str, object]]:
    node_prefix = node_key_prefix(prefix, node_id)
    node_archives: list[tuple[str, datetime]] = []
    for key, metadata in objects.items():
        if not key.startswith(node_prefix):
            continue
        name = key[len(node_prefix) :]
        if "/" in name or not SAFE_ARCHIVE_NAME.fullmatch(name):
            continue
        node_archives.append((key, remote_modified(metadata.get("last_modified"))))

    if not node_archives:
        return objects

    # Never allow retention to remove the last known remote copy for this node.
    newest_key = max(node_archives, key=lambda item: item[1])[0]
    cutoff = now - timedelta(days=retention_days)
    expired = [
        key
        for key, modified in node_archives
        if key != newest_key and modified < cutoff
    ]
    for key in expired:
        delete_remote_object(aws, bucket, key)

    if expired:
        remaining = list_remote_objects(aws, bucket, prefix)
        still_present = [key for key in expired if key in remaining]
        if still_present:
            raise BackupError("A remoção de backups remotos vencidos não pôde ser confirmada.")
        return remaining
    return objects


def remote_prefix_size(objects: dict[str, dict[str, object]]) -> int:
    total = 0
    for metadata in objects.values():
        size = metadata.get("size")
        if not isinstance(size, int) or size < 0:
            raise BackupError("O espaço usado no armazenamento remoto não pôde ser calculado.")
        total += size
    return total


def remove_expired_uploaded_files(directory: Path, retention_days: int) -> None:
    """Keep the first and last archive of every ISO week and calendar month."""
    archives: list[tuple[datetime, Path, Path]] = []
    for archive in directory.glob("frequency_*.dump.age"):
        marker = archive.with_name(archive.name + ".uploaded")
        if not marker.exists():
            continue
        match = re.match(r"frequency_(\d{8}T\d{6})Z\.dump\.age$", archive.name)
        if not match:
            continue
        try:
            timestamp = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        archives.append((timestamp, archive, marker))
    keep: set[Path] = set()
    for key in (lambda value: (value[0].isocalendar().year, value[0].isocalendar().week), lambda value: (value[0].year, value[0].month)):
        groups: dict[object, list[tuple[datetime, Path, Path]]] = {}
        for item in archives:
            groups.setdefault(key(item), []).append(item)
        for items in groups.values():
            items.sort(key=lambda item: item[0])
            keep.add(items[0][1])
            keep.add(items[-1][1])
    for _, archive, marker in archives:
        if archive not in keep:
            archive.unlink(missing_ok=True)
            marker.unlink(missing_ok=True)


def run() -> int:
    load_dotenv(BACKEND_DIR / ".env")
    if os.getenv("BACKUP_ENABLE", "").strip().upper() != "YES":
        raise BackupError("Backup desativado. Configure BACKUP_ENABLE=YES para ativá-lo.")

    age_recipient = required("BACKUP_AGE_RECIPIENT")
    if not age_recipient.startswith("age1"):
        raise BackupError("BACKUP_AGE_RECIPIENT não parece ser uma chave pública age.")

    storage_provider = os.getenv("BACKUP_STORAGE_PROVIDER", "s3").strip().lower()
    if storage_provider not in {"s3", "lightsail", "local"}:
        raise BackupError("BACKUP_STORAGE_PROVIDER deve ser s3, lightsail ou local.")

    bucket = ""
    if storage_provider != "local":
        bucket = required("BACKUP_S3_BUCKET")
        if "/" in bucket:
            raise BackupError("BACKUP_S3_BUCKET deve conter somente o nome do bucket.")

    node_id = os.getenv("BACKUP_NODE_ID", "local").strip() or "local"
    if storage_provider != "local" and not SAFE_SEGMENT.fullmatch(node_id):
        raise BackupError("BACKUP_NODE_ID aceita apenas letras, números, hífen e sublinhado.")

    prefix = os.getenv("BACKUP_S3_PREFIX", "frequency").strip().strip("/")
    if len(prefix) > 200 or not SAFE_PREFIX.fullmatch(prefix):
        raise BackupError("BACKUP_S3_PREFIX contém caracteres não permitidos.")

    try:
        retention_days = int(os.getenv("BACKUP_LOCAL_RETENTION_DAYS", "7"))
    except ValueError as exc:
        raise BackupError("BACKUP_LOCAL_RETENTION_DAYS deve ser um número inteiro.") from exc
    if not 1 <= retention_days <= 365:
        raise BackupError("BACKUP_LOCAL_RETENTION_DAYS deve estar entre 1 e 365.")

    remote_retention_days = 0
    if storage_provider != "local":
        try:
            remote_retention_days = int(required("BACKUP_REMOTE_RETENTION_DAYS"))
        except ValueError as exc:
            raise BackupError("BACKUP_REMOTE_RETENTION_DAYS deve ser um número inteiro.") from exc
        if not 1 <= remote_retention_days <= 3650:
            raise BackupError("BACKUP_REMOTE_RETENTION_DAYS deve estar entre 1 e 3650.")

    try:
        remote_limit_gb = int(os.getenv("BACKUP_S3_MAX_GB", "90"))
    except ValueError as exc:
        raise BackupError("BACKUP_S3_MAX_GB deve ser um número inteiro.") from exc
    if not 1 <= remote_limit_gb <= 100000:
        raise BackupError("BACKUP_S3_MAX_GB deve estar entre 1 e 100000.")

    pg_dump = command_path("PG_DUMP_BIN", "pg_dump")
    age = command_path("AGE_BIN", "age")
    aws = command_path("AWS_BIN", "aws") if storage_provider != "local" else ""
    directory = backup_directory()
    db_environment = libpq_environment()
    now = datetime.now(timezone.utc)
    new_archive = directory / f"frequency_{now:%Y%m%dT%H%M%SZ}.dump.age"

    dump_failed = False
    try:
        create_encrypted_dump(
            pg_dump,
            age,
            age_recipient,
            new_archive,
            db_environment,
        )
    except BackupError:
        dump_failed = True

    pending = sorted(
        archive
        for archive in directory.glob("frequency_*.dump.age")
        if not archive.with_name(archive.name + ".uploaded").exists()
    )

    # A local backup is complete as soon as the encrypted archive is safely
    # written to BACKUP_LOCAL_DIR. It can point at a normal folder or a local
    # OneDrive folder without requiring a central cloud account.
    if storage_provider == "local":
        if dump_failed:
            raise BackupError("não foi possível gerar o backup de hoje")
        for archive in pending:
            archive.with_name(archive.name + ".uploaded").touch(exist_ok=True)
        remove_expired_uploaded_files(directory, retention_days)
        write_status("sucesso", uploaded=len(pending), pending=0)
        print(f"Backup local concluído. Arquivos gravados: {len(pending)}.")
        return 0

    # Retry only archives not already marked as uploaded. This also lets the
    # command deliver older queued archives if the database is temporarily down.
    failures = 0
    uploaded = 0
    capacity_failures = 0
    remote_check_failed = False
    if pending:
        try:
            ensure_bucket_unversioned(aws, bucket, storage_provider)
            objects = list_remote_objects(aws, bucket, prefix)
            objects = prune_expired_remote_backups(
                aws,
                bucket,
                prefix,
                node_id,
                objects,
                remote_retention_days,
                datetime.now(timezone.utc),
            )
            used_bytes = remote_prefix_size(objects)
        except BackupError:
            remote_check_failed = True
            failures += len(pending)

        if not remote_check_failed:
            # Send the newest queued archive first so a full bucket does not
            # prevent today's recovery point from taking priority.
            ordered_pending = sorted(pending, reverse=True)
            for index, archive in enumerate(ordered_pending):
                key = s3_key_for(archive, node_id, prefix)
                old_size = int(objects[key]["size"]) if key in objects else 0
                projected_bytes = used_bytes - old_size + archive.stat().st_size
                if projected_bytes > remote_limit_gb * 1_000_000_000:
                    failures += 1
                    capacity_failures += 1
                    continue
                try:
                    upload_and_verify(aws, bucket, key, archive)
                except BackupError:
                    # A remote upload may have completed even if its response
                    # was lost. Stop here; the next run will list it again.
                    failures += len(ordered_pending) - index
                    break
                uploaded += 1
                used_bytes = projected_bytes
                objects[key] = {
                    "size": archive.stat().st_size,
                    "last_modified": datetime.now(timezone.utc).isoformat(),
                }

    remove_expired_uploaded_files(directory, retention_days)
    if failures or dump_failed:
        problems = []
        if dump_failed:
            problems.append("não foi possível gerar o backup de hoje")
        if failures:
            problems.append(f"{failures} arquivo(s) aguardam envio")
        if capacity_failures:
            problems.append(
                f"o limite de {remote_limit_gb} GB configurado para o prefixo remoto foi atingido"
            )
        if remote_check_failed:
            problems.append("não foi possível conferir a retenção e o espaço remoto")
        raise BackupError(
            "; ".join(problems) + ". As cópias criptografadas foram mantidas localmente."
        )

    write_status("sucesso", uploaded=uploaded, pending=0)
    print(f"Backup e conferência remota concluídos. Arquivos enviados: {uploaded}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except BackupError as error:
        load_dotenv(BACKEND_DIR / ".env")
        enabled = os.getenv("BACKUP_ENABLE", "").strip().upper() == "YES"
        try:
            write_status(
                "falha" if enabled else "desativado",
                message=str(error),
            )
        except BackupError:
            # The original failure is more useful to the scheduler than a
            # secondary error while writing the operator status file.
            pass
        print(f"FALHA NO BACKUP: {error}", file=sys.stderr)
        raise SystemExit(1)
