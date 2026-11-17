"""Regras puras da mensalidade e do QR de acesso assinado (sem banco)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import date, datetime, timezone

PREFIXO = "fqm_"
SEGUNDOS_QR = 120


def decidir_liberacao(status: str, plano_id: int | None, proximo_vencimento: date | None, alerta: str | None) -> tuple[bool, str | None]:
    """Mesma regra da catraca (processar_acesso): inativo, sem plano, sem cobrança em aberto e atrasado não entram."""
    if status != "ativo":
        return False, "aluno_inativo"
    if plano_id is None:
        return False, "plano_nao_cadastrado"
    if proximo_vencimento is None:
        return False, "sem_pagamento_em_aberto"
    if alerta == "atrasado":
        return False, "mensalidade_atrasada"
    return True, None


def situacao(proximo_vencimento: date | None, hoje: date) -> dict:
    if proximo_vencimento is None:
        return {"estado": "sem_cobranca", "dias": None}
    dias = (proximo_vencimento - hoje).days
    if dias < 0:
        return {"estado": "atrasada", "dias": -dias}
    return {"estado": "vence_em_breve" if dias <= 5 else "em_dia", "dias": dias}


def _assinar(segredo: str, corpo: str) -> str:
    return hmac.new(segredo.encode(), ("fqm1." + corpo).encode(), hashlib.sha256).hexdigest()[:32]


def gerar_qr(segredo: str, aluno_id: int, academia_id: int, agora: datetime) -> tuple[str, datetime]:
    exp = int(agora.timestamp()) + SEGUNDOS_QR
    corpo = base64.urlsafe_b64encode(json.dumps({"a": aluno_id, "g": academia_id, "e": exp, "n": secrets.token_hex(4)}, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{PREFIXO}{corpo}.{_assinar(segredo, corpo)}", datetime.fromtimestamp(exp, tz=timezone.utc)


def validar_qr(segredo: str, codigo: str, academia_id: int, agora: datetime) -> int | None:
    """Devolve o aluno_id se a assinatura, a academia e a validade conferem; senão None (sem dizer o porquê)."""
    try:
        if not codigo.startswith(PREFIXO) or len(codigo) > 400:
            return None
        corpo, assinatura = codigo[len(PREFIXO):].rsplit(".", 1)
        if not hmac.compare_digest(assinatura, _assinar(segredo, corpo)):
            return None
        dados = json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)))
        if dados["g"] != academia_id or int(dados["e"]) < int(agora.timestamp()):
            return None
        return int(dados["a"])
    except Exception:
        return None
