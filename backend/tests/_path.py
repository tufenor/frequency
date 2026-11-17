"""Garante que os módulos do backend (import 'main', 'seguranca'…) sejam importáveis nos testes."""
import os
import sys
from pathlib import Path

BACKEND = str(Path(__file__).resolve().parents[1])
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
os.environ.setdefault("SECRET_KEY", "synthetic-integration-secret-not-for-use-0123456789")
