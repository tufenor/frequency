"""Safe local launcher and readiness check for a Frequency installation.

The launcher deliberately does not apply migrations or create accounts. It
only starts the API after confirming that the configured database and static
application are available. That makes it suitable for a future Windows
shortcut or packaged executable without hiding an incomplete installation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")
FRONTEND_DIR = Path(
    os.getenv("FREQUENCY_FRONTEND_DIR", str(BACKEND_DIR.parent / "frontend" / "public"))
).resolve()
REQUIRED_PAGES = ("index.html", "monitor.html", "cameras.html", "youtube.html")
CORE_V1_MIGRATIONS = frozenset({
    "001_initial_schema.sql",
    "002_tenant_integrity.sql",
    "003_sync_outbox.sql",
    "004_qr_cobranca_academia.sql",
    "005_idioma_moeda.sql",
    "006_foto_alunos.sql",
    "007_tela_aluno.sql",
    "008_cobranca_frequency.sql",
    "009_recursos_premium.sql",
    "010_localizacao_academia.sql",
    "021_hardware_frequency.sql",
    "022_monitores_eventos_individuais.sql",
    "023_sessoes_telas_acesso.sql",
    "024_relogio_local.sql",
    "025_codigo_monitor_persistente.sql",
    "026_status_comercial_academia.sql",
    "027_bairro_aluno.sql",
    "028_experiencia_7_dias.sql",
    "042_vinculo_frequency_local.sql",
})


def readiness() -> dict[str, object]:
    """Return a non-sensitive readiness report for the local operator."""
    report: dict[str, object] = {
        "banco": "indisponivel",
        "migracoes": "indisponivel",
        "frontend": "indisponivel",
        "pronto": False,
        "problemas": [],
    }
    problems: list[str] = report["problemas"]  # type: ignore[assignment]

    if not os.getenv("SECRET_KEY", "").strip() or len(os.getenv("SECRET_KEY", "")) < 32:
        problems.append("SECRET_KEY ausente ou curta")

    missing_pages = [page for page in REQUIRED_PAGES if not (FRONTEND_DIR / page).is_file()]
    if missing_pages:
        problems.append("frontend incompleto")
    else:
        report["frontend"] = "disponivel"

    try:
        sys.path.insert(0, str(BACKEND_DIR))
        from database import get_connection
        from verificar_migracoes import inspect

        with get_connection() as conn:
            conn.execute("SELECT 1")
        report["banco"] = "disponivel"
        states = inspect()
        incomplete = [
            name for name, state in states.items()
            if "parcial" in state
            or (name in CORE_V1_MIGRATIONS and state != "todos os objetos esperados presentes")
        ]
        if incomplete:
            report["migracoes"] = "incompletas"
            problems.append("migrações pendentes ou parciais")
        else:
            report["migracoes"] = "completas"
    except Exception:
        # Do not return driver details, connection strings, or traceback to a
        # person starting the local service.
        problems.append("não foi possível verificar o banco e as migrações")

    report["pronto"] = not problems
    return report


def tls_files(certfile: str | None, keyfile: str | None) -> tuple[str | None, str | None]:
    if bool(certfile) != bool(keyfile):
        raise ValueError("Configure o certificado TLS e a chave privada juntos.")
    if not certfile:
        return None, None
    cert_path = Path(certfile).expanduser().resolve()
    key_path = Path(keyfile).expanduser().resolve()
    if not cert_path.is_file() or not key_path.is_file():
        raise ValueError("Os arquivos do certificado TLS não foram encontrados.")
    return str(cert_path), str(key_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Iniciador local do Frequency")
    parser.add_argument("--check", action="store_true", help="somente verificar a instalação")
    parser.add_argument("--host", default=os.getenv("FREQUENCY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FREQUENCY_PORT", "8000")))
    parser.add_argument("--tls-certfile", default=os.getenv("FREQUENCY_TLS_CERTFILE"))
    parser.add_argument("--tls-keyfile", default=os.getenv("FREQUENCY_TLS_KEYFILE"))
    arguments = parser.parse_args()
    try:
        certfile, keyfile = tls_files(arguments.tls_certfile, arguments.tls_keyfile)
    except ValueError as error:
        print(json.dumps({"pronto": False, "problemas": [str(error)]}, ensure_ascii=False))
        return 2
    report = readiness()
    print(json.dumps(report, ensure_ascii=False))
    if not report["pronto"]:
        return 1
    if arguments.check:
        return 0

    sys.path.insert(0, str(BACKEND_DIR))
    import uvicorn
    import main as frequency_app

    uvicorn.run(
        frequency_app.app,
        host=arguments.host,
        port=arguments.port,
        reload=False,
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
