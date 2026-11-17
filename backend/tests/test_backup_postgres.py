import base64
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from backend.ops import backup_postgres


class RemoteChecksumTests(unittest.TestCase):
    def setUp(self):
        self.payload = b"encrypted synthetic backup"
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def test_accepts_full_object_sha256(self):
        checksum = base64.b64encode(bytes.fromhex(self.digest)).decode("ascii")
        self.assertTrue(
            backup_postgres.remote_sha256_valid(checksum, "FULL_OBJECT", self.digest)
        )

    def test_rejects_mismatched_full_object_sha256(self):
        checksum = base64.b64encode(b"x" * 32).decode("ascii")
        self.assertFalse(
            backup_postgres.remote_sha256_valid(checksum, "FULL_OBJECT", self.digest)
        )

    def test_accepts_well_formed_multipart_composite_sha256(self):
        checksum = base64.b64encode(b"c" * 32).decode("ascii") + "-3"
        self.assertTrue(
            backup_postgres.remote_sha256_valid(checksum, "COMPOSITE", self.digest)
        )

    def test_rejects_metadata_digest_as_a_remote_checksum(self):
        self.assertFalse(
            backup_postgres.remote_sha256_valid("metadata-only", "COMPOSITE", self.digest)
        )

    def test_status_file_is_atomic_and_contains_no_connection_settings(self):
        with tempfile.TemporaryDirectory(prefix="frequency-backup-status-") as temporary:
            destination = Path(temporary) / "status.json"
            with patch.dict("os.environ", {"BACKUP_STATUS_FILE": str(destination)}, clear=False):
                backup_postgres.write_status(
                    "falha",
                    uploaded=0,
                    pending=2,
                    message="cópias criptografadas aguardam envio",
                )
            status = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "falha")
            self.assertEqual(status["pending"], 2)
            self.assertNotIn("DB_PASSWORD", status)
            self.assertFalse(list(Path(temporary).glob("*.tmp")))


class RemoteRetentionTests(unittest.TestCase):
    def test_removes_only_expired_archives_for_this_node_and_keeps_newest(self):
        now = datetime(2026, 9, 28, tzinfo=timezone.utc)
        expired = "frequency/backups/unidade-principal/frequency_20200101T000000Z.dump.age"
        newest = "frequency/backups/unidade-principal/frequency_20260927T000000Z.dump.age"
        other_node = "frequency/backups/outra-unidade/frequency_20200101T000000Z.dump.age"
        unrelated = "frequency/backups/unidade-principal/README.txt"
        objects = {
            expired: {"size": 100, "last_modified": "2020-01-01T00:00:00+00:00"},
            newest: {"size": 250, "last_modified": "2026-09-27T00:00:00+00:00"},
            other_node: {"size": 500, "last_modified": "2020-01-01T00:00:00+00:00"},
            unrelated: {"size": 25, "last_modified": "2020-01-01T00:00:00+00:00"},
        }
        remaining = {key: value for key, value in objects.items() if key != expired}

        with (
            patch.object(backup_postgres, "delete_remote_object") as delete,
            patch.object(backup_postgres, "list_remote_objects", return_value=remaining),
        ):
            result = backup_postgres.prune_expired_remote_backups(
                "aws",
                "bucket-test",
                "frequency/backups",
                "unidade-principal",
                objects,
                30,
                now,
            )

        self.assertEqual([call.args[-1] for call in delete.call_args_list], [expired])
        self.assertIn(newest, result)
        self.assertIn(other_node, result)
        self.assertIn(unrelated, result)
        self.assertNotIn(expired, result)

    def test_preserves_last_remote_archive_even_when_expired(self):
        archive = "frequency/backups/unidade-principal/frequency_20200101T000000Z.dump.age"
        objects = {archive: {"size": 10, "last_modified": "2020-01-01T00:00:00+00:00"}}

        with patch.object(backup_postgres, "delete_remote_object") as delete:
            result = backup_postgres.prune_expired_remote_backups(
                "aws",
                "bucket-test",
                "frequency/backups",
                "unidade-principal",
                objects,
                30,
                datetime(2026, 9, 28, tzinfo=timezone.utc),
            )

        delete.assert_not_called()
        self.assertIn(archive, result)


class RemoteUploadVerificationTests(unittest.TestCase):
    def setUp(self):
        self.payload = b"encrypted synthetic backup"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.checksum = base64.b64encode(bytes.fromhex(self.digest)).decode("ascii")

    def _head_response(self, checksum):
        return json.dumps(
            {
                "size": len(self.payload),
                "metadata_digest": self.digest,
                "checksum": checksum,
                "checksum_type": "FULL_OBJECT",
            }
        )

    def test_requests_stored_checksum_and_marks_only_verified_upload(self):
        with tempfile.TemporaryDirectory(prefix="frequency-backup-test-") as temporary:
            archive = Path(temporary) / "frequency_20260928T120000Z.dump.age"
            archive.write_bytes(self.payload)
            responses = [
                CompletedProcess([], 0, "", ""),
                CompletedProcess([], 0, self._head_response(self.checksum), ""),
            ]

            with patch.object(backup_postgres.subprocess, "run", side_effect=responses) as run:
                backup_postgres.upload_and_verify("aws", "bucket-test", "test/key", archive)

            head_command = run.call_args_list[1].args[0]
            self.assertIn("--checksum-mode", head_command)
            self.assertIn("ENABLED", head_command)
            marker = archive.with_name(archive.name + ".uploaded")
            self.assertEqual(marker.read_text(encoding="utf-8"), "test/key")

    def test_does_not_mark_upload_when_stored_checksum_mismatches(self):
        wrong_checksum = base64.b64encode(b"x" * 32).decode("ascii")
        with tempfile.TemporaryDirectory(prefix="frequency-backup-test-") as temporary:
            archive = Path(temporary) / "frequency_20260928T120000Z.dump.age"
            archive.write_bytes(self.payload)
            responses = [
                CompletedProcess([], 0, "", ""),
                CompletedProcess([], 0, self._head_response(wrong_checksum), ""),
            ]

            with patch.object(backup_postgres.subprocess, "run", side_effect=responses):
                with self.assertRaises(backup_postgres.BackupError):
                    backup_postgres.upload_and_verify(
                        "aws", "bucket-test", "test/key", archive
                    )

            self.assertFalse(archive.with_name(archive.name + ".uploaded").exists())


if __name__ == "__main__":
    unittest.main()
