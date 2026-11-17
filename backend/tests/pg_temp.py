"""PostgreSQL descartável para testes de integração (não toca em banco real)."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _find_bin() -> Path | None:
    configured = os.environ.get("POSTGRES_BIN_DIR")
    candidates = [Path(configured)] if configured else []
    if os.name == "nt":
        candidates.extend(sorted(Path("C:/Program Files/PostgreSQL").glob("*/bin"), reverse=True))
    else:
        found = shutil.which("initdb")
        if found:
            candidates.append(Path(found).parent)
    ext = ".exe" if os.name == "nt" else ""
    for c in candidates:
        if all((c / f"{n}{ext}").is_file() for n in ("initdb", "pg_ctl", "psql")):
            return c
    return None


class TempPostgres:
    """Sobe um PostgreSQL temporário; `dsn` aponta para o banco `frequency_test`."""

    def __init__(self) -> None:
        self._bin = _find_bin()
        if self._bin is None:
            raise unittest.SkipTest("PostgreSQL não encontrado; defina POSTGRES_BIN_DIR.")
        self._tmp = tempfile.TemporaryDirectory(prefix="frequency_pg_")
        self._data = Path(self._tmp.name) / "data"
        self._log = Path(self._tmp.name) / "pg.log"
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.dsn = (
            f"host=127.0.0.1 port={self.port} dbname=frequency_test "
            "user=frequency_test connect_timeout=3"
        )
        self._running = False

    def _exe(self, name: str) -> str:
        ext = ".exe" if os.name == "nt" else ""
        return str(self._bin / f"{name}{ext}")

    def _run(self, cmd: list[str], timeout: int = 120) -> None:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        if r.returncode:
            raise RuntimeError(f"Comando falhou ({r.returncode}): {r.stdout}\n{r.stderr}")

    def start(self, migrations: list[Path] | None = None) -> "TempPostgres":
        try:
            self._run([self._exe("initdb"), "-D", str(self._data), "--username=frequency_test",
                       "--encoding=UTF8", "--auth-local=trust", "--auth-host=trust",
                       "--no-instructions", "--no-sync"])
            subprocess.run([self._exe("pg_ctl"), "-D", str(self._data), "-o",
                            f"-h 127.0.0.1 -p {self.port}", "-l", str(self._log), "-w", "start"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=120, check=True)
            self._running = True
            base = [self._exe("psql"), "-h", "127.0.0.1", "-p", str(self.port),
                    "-U", "frequency_test", "-v", "ON_ERROR_STOP=1"]
            self._run(base + ["-d", "postgres", "-c", "CREATE DATABASE frequency_test"])
            for m in migrations if migrations is not None else sorted(MIGRATIONS.glob("*.sql")):
                self._run(base + ["-d", "frequency_test", "-f", str(m)], timeout=60)
        except Exception:
            self.stop()
            raise
        return self

    def stop(self) -> None:
        if self._running:
            subprocess.run([self._exe("pg_ctl"), "-D", str(self._data), "-m", "fast", "-w", "stop"],
                           capture_output=True, timeout=30, check=False)
            self._running = False
        self._tmp.cleanup()
