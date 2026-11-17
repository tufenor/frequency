"""Small, dependency-free MCP stdio server for the Frequency project.

The server intentionally exposes only safe project inspection and test tools.
It never receives or prints credentials and cannot deploy, migrate, delete, or
send messages.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def response(request_id, result=None, error=None):
    payload = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def text_result(text: str):
    return {"content": [{"type": "text", "text": text}]}


def project_status():
    files = ["README.md", "PROJECT_STATUS.md", "API_CONTRACT.md", "ARCHITECTURE.md"]
    out = []
    for name in files:
        path = ROOT / name
        if path.exists():
            out.append(f"## {name}\n{path.read_text(encoding='utf-8', errors='replace')[:12000]}")
    return "\n\n".join(out)


def pending_tasks():
    status = ROOT / "PROJECT_STATUS.md"
    if not status.exists():
        return "PROJECT_STATUS.md não encontrado."
    lines = status.read_text(encoding="utf-8", errors="replace").splitlines()
    wanted = {"TODO:", "IN PROGRESS:", "BLOCKED:"}
    sections, current, items = [], None, []
    for line in lines:
        heading = line.strip().upper()
        if heading in wanted:
            if current and items: sections.append(f"{current}\n" + "\n".join(items))
            current, items = heading, []
        elif current and (line.startswith("## ") or heading in {"DONE:", "DECISION:", "RISKS:"}):
            if items: sections.append(f"{current}\n" + "\n".join(items))
            current, items = None, []
        elif current and line.strip().startswith(("- ", "* ")):
            items.append(line.strip())
    if current and items: sections.append(f"{current}\n" + "\n".join(items))
    return "\n\n".join(sections) or "Nenhuma seção TODO, IN PROGRESS ou BLOCKED encontrada."


def manager_commands():
    path = ROOT / "docs" / "CLAUDE_COMMANDS.md"
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else "docs/CLAUDE_COMMANDS.md não encontrado."


def run_tests():
    python = ROOT / "backend" / "venv" / "Scripts" / "python.exe"
    command = [str(python), "-m", "unittest", "discover", "-s", "backend/tests", "-v"]
    env = {"PATH": __import__("os").environ.get("PATH", ""), "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    output = (completed.stdout + "\n" + completed.stderr).strip()
    return f"exit_code={completed.returncode}\n{output[-12000:]}"


TOOLS = [
    {"name": "frequency_status", "description": "Lê o status e os contratos principais do Frequency.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "frequency_pending_tasks", "description": "Lista pendências explícitas registradas no projeto.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "frequency_manager_commands", "description": "Lê as instruções de coordenação aprovadas para o Claude.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "frequency_run_tests", "description": "Executa unittest discover na venv local; não altera produção.", "inputSchema": {"type": "object", "properties": {}}},
]


for line in sys.stdin:
    try:
        request = json.loads(line)
        request_id = request.get("id")
        method = request.get("method")
        if method == "initialize":
            response(request_id, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "frequency-local", "version": "1.0.0"}})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            response(request_id, {"tools": TOOLS})
        elif method == "tools/call":
            name = request.get("params", {}).get("name")
            if name == "frequency_status":
                response(request_id, text_result(project_status()))
            elif name == "frequency_pending_tasks":
                response(request_id, text_result(pending_tasks()))
            elif name == "frequency_manager_commands":
                response(request_id, text_result(manager_commands()))
            elif name == "frequency_run_tests":
                response(request_id, text_result(run_tests()))
            else:
                response(request_id, error={"code": -32601, "message": "Ferramenta não permitida"})
        else:
            response(request_id, error={"code": -32601, "message": "Método não suportado"})
    except Exception as exc:
        response(None, error={"code": -32603, "message": str(exc)})
