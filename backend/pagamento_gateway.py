"""Gateway de pagamentos online usado pelo Frequency.

O módulo mantém a integração externa pequena e isolada da regra de negócio.
Segredos nunca são aceitos no corpo das requisições; ficam somente em variáveis
de ambiente do servidor.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


class GatewayNaoConfigurado(RuntimeError):
    """As credenciais ou a URL pública do gateway ainda não foram configuradas."""


class GatewayIndisponivel(RuntimeError):
    """O gateway recusou a requisição ou respondeu em formato inválido."""


@dataclass(frozen=True)
class CheckoutCriado:
    provedor: str
    order_id: str
    pagamento_id: str
    checkout_url: str
    status: str


def _config_dlocal() -> dict[str, str]:
    return {
        "base_url": os.getenv("DLOCAL_API_BASE_URL", "https://api.dlocal.com").strip().rstrip("/"),
        "login": os.getenv("DLOCAL_X_LOGIN", "").strip(),
        "trans_key": os.getenv("DLOCAL_X_TRANS_KEY", "").strip(),
        "secret_key": os.getenv("DLOCAL_SECRET_KEY", "").strip(),
        "country": os.getenv("DLOCAL_COUNTRY", "BO").strip().upper(),
        "payment_method_id": os.getenv("DLOCAL_PAYMENT_METHOD_ID", "QR").strip().upper(),
        "payment_flow": os.getenv("DLOCAL_PAYMENT_FLOW", "REDIRECT").strip().upper(),
        "public_base_url": os.getenv("PAYMENT_PUBLIC_BASE_URL", "").strip().rstrip("/"),
    }


def dlocal_configurado() -> bool:
    config = _config_dlocal()
    return all(
        config[key]
        for key in ("login", "trans_key", "secret_key", "public_base_url")
    )


def dlocal_assinatura(login: str, data: str, secret_key: str, body: bytes) -> str:
    """Calcula a assinatura HMAC exigida pelo dLocal Payins."""
    mensagem = login.encode("utf-8") + data.encode("utf-8") + body
    return hmac.new(secret_key.encode("utf-8"), mensagem, hashlib.sha256).hexdigest()


def _json_body(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _requisitar_dlocal(path: str, payload: dict[str, object]) -> dict[str, object]:
    config = _config_dlocal()
    if not dlocal_configurado():
        raise GatewayNaoConfigurado("dlocal_nao_configurado")

    body = _json_body(payload)
    data = _agora_iso()
    request = urllib.request.Request(
        f"{config['base_url']}{path}",
        data=body,
        method="POST",
        headers={
            "X-Date": data,
            "X-Login": config["login"],
            "X-Trans-Key": config["trans_key"],
            "X-Version": "2.1",
            "User-Agent": "Frequency/1.0",
            "Content-Type": "application/json",
            "Authorization": (
                "V2-HMAC-SHA256, Signature: "
                + dlocal_assinatura(config["login"], data, config["secret_key"], body)
            ),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read(1200).decode("utf-8", errors="replace")
        raise GatewayIndisponivel(f"dlocal_http_{error.code}:{detail[:400]}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise GatewayIndisponivel("dlocal_sem_resposta") from error

    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GatewayIndisponivel("dlocal_resposta_invalida") from error
    if not isinstance(result, dict):
        raise GatewayIndisponivel("dlocal_resposta_invalida")
    return result


def criar_checkout_dlocal(
    *,
    order_id: str,
    amount: Decimal,
    currency: str,
    payer_name: str,
    payer_email: str,
    payer_document: str,
    description: str,
    callback_url: str,
) -> CheckoutCriado:
    """Cria um checkout dLocal sem expor credenciais ao navegador."""
    config = _config_dlocal()
    if not dlocal_configurado():
        raise GatewayNaoConfigurado("dlocal_nao_configurado")
    if not callback_url.startswith("https://"):
        raise GatewayNaoConfigurado("pagamento_exige_url_https")

    payload: dict[str, object] = {
        "amount": float(amount),
        "currency": currency.upper(),
        "country": config["country"],
        "payment_method_id": config["payment_method_id"],
        "payment_method_flow": config["payment_flow"],
        "payer": {
            "name": payer_name,
            "email": payer_email,
            "document": payer_document,
        },
        "order_id": order_id,
        "description": description[:200],
        "notification_url": f"{config['public_base_url']}/webhooks/dlocal",
        "callback_url": callback_url,
    }
    result = _requisitar_dlocal("/payments", payload)
    payment_id = str(result.get("id") or "").strip()
    checkout_url = str(result.get("redirect_url") or "").strip()
    if not checkout_url:
        ticket = result.get("ticket")
        if isinstance(ticket, dict):
            checkout_url = str(ticket.get("image_url") or "").strip()
    if not payment_id or not checkout_url:
        raise GatewayIndisponivel("dlocal_checkout_sem_url")
    return CheckoutCriado(
        provedor="dlocal",
        order_id=order_id,
        pagamento_id=payment_id,
        checkout_url=checkout_url,
        status=str(result.get("status") or "PENDING").upper(),
    )


def validar_notificacao_dlocal(body: bytes, data: str | None, signature: str | None) -> bool:
    """Valida a assinatura do webhook antes de interpretar o conteúdo."""
    config = _config_dlocal()
    if not config["login"] or not config["secret_key"] or not data or not signature:
        return False
    expected = dlocal_assinatura(config["login"], data, config["secret_key"], body)
    received = signature.strip()
    if received.lower().startswith("v2-hmac-sha256"):
        received = received.rsplit(":", 1)[-1].strip()
    return hmac.compare_digest(expected.lower(), received.lower())


def status_dlocal_pago(status: object) -> bool:
    return str(status or "").strip().upper() in {"PAID", "COMPLETED", "APPROVED"}


def status_dlocal_falhou(status: object) -> bool:
    return str(status or "").strip().upper() in {
        "REJECTED",
        "CANCELLED",
        "CANCELED",
        "EXPIRED",
        "FAILED",
    }


def hash_evento_webhook(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()
