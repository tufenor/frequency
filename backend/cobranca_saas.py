from __future__ import annotations

import os
from datetime import date

from relogio_local import estado_relogio_local


def cobranca_obrigatoria() -> bool:
    """Require a Frequency subscription in hosted/commercial mode only."""
    return os.getenv("FREQUENCY_BILLING_REQUIRED", "NO").strip().upper() == "YES"


def estado_assinatura_frequency(conn, academia_id: int) -> dict[str, object]:
    """Compute the same service state for users, readers and the billing screen.

    Suspended/cancelled subscriptions require an administrator to reactivate
    service. Paying an invoice never silently reactivates a manual suspension.
    In hosted/commercial mode, an academy without a subscription is blocked
    unless it has an active explicitly recorded trial. Local installations
    remain compatible with legacy ``ativa`` rows and can be governed by the
    operator rather than the hosted subscription service.

    The local clock guard is persistent and monotonic when migration 024 is
    present. A clock rollback remains blocked until an operator reviews the
    installation; it cannot reactivate an expired subscription.
    """
    migrated = conn.execute(
        "SELECT to_regclass('public.faturas_frequency') IS NOT NULL AS presente"
    ).fetchone()["presente"]
    if not migrated:
        return {
            "dias_atraso_frequency": 0,
            "aviso_frequency": False,
            "bloqueada_frequency": cobranca_obrigatoria(),
            "fatura_frequency": None,
            "status_assinatura_frequency": None,
            "status_comercial_frequency": None,
            "motivo_bloqueio_frequency": (
                "migracao_frequency_pendente" if cobranca_obrigatoria() else None
            ),
            "relogio_recuou": False,
        }

    relogio = estado_relogio_local(conn, academia_id)
    data_referencia = relogio.get("data_referencia") or date.today()
    assinatura = conn.execute(
        "SELECT s.status, a.status_comercial, a.trial_inicio, a.trial_fim "
        "FROM public.academias a "
        "LEFT JOIN public.assinaturas_frequency s ON s.academia_id = a.id "
        "WHERE a.id = %s",
        (academia_id,),
    ).fetchone()
    status = assinatura["status"] if assinatura and assinatura["status"] else None
    status_comercial = (
        assinatura["status_comercial"] if assinatura and assinatura["status_comercial"]
        else "aguardando_plano"
    )
    trial_inicio = assinatura["trial_inicio"] if assinatura else None
    trial_fim = assinatura["trial_fim"] if assinatura else None
    experiencia_ativa = bool(
        status is None
        and status_comercial == "ativa"
        and trial_fim is not None
        and data_referencia < trial_fim
    )
    dias_experiencia_restantes = (
        max(0, (trial_fim - data_referencia).days)
        if experiencia_ativa and trial_fim is not None
        else 0
    )
    fatura = conn.execute(
        "SELECT f.id, f.valor, f.moeda, f.vencimento, f.status "
        "FROM public.faturas_frequency f "
        "WHERE f.academia_id = %s AND f.status = 'em_aberto' "
        "ORDER BY f.vencimento, f.id LIMIT 1",
        (academia_id,),
    ).fetchone()
    atraso = max(0, (data_referencia - fatura["vencimento"]).days) if fatura else 0
    if status_comercial == "bloqueada":
        motivo = "academia_comercial_bloqueada"
    elif status is None and cobranca_obrigatoria():
        # Only an active trial is a valid entitlement without a paid
        # subscription. The commercial flag alone is not an entitlement.
        motivo = None if experiencia_ativa else (
            "experiencia_expirada" if trial_fim is not None else "sem_assinatura"
        )
    elif status_comercial == "aguardando_plano":
        motivo = "sem_assinatura"
    elif status is None and trial_fim is not None and data_referencia >= trial_fim:
        motivo = "experiencia_expirada"
    else:
        motivo = status if status in {"suspensa", "cancelada"} else ("atraso" if atraso >= 5 else None)
    if relogio.get("relogio_recuou"):
        motivo = str(relogio.get("motivo_bloqueio") or "relogio_local_recuou")
    return {
        "dias_atraso_frequency": atraso,
        "aviso_frequency": atraso >= 2,
        "bloqueada_frequency": motivo is not None,
        "fatura_frequency": fatura,
        "status_assinatura_frequency": status,
        "status_comercial_frequency": status_comercial,
        "motivo_bloqueio_frequency": motivo,
        "relogio_recuou": bool(relogio.get("relogio_recuou")),
        "trial_inicio": trial_inicio,
        "trial_fim": trial_fim,
        "experiencia_ativa": experiencia_ativa,
        "dias_experiencia_restantes": dias_experiencia_restantes,
    }
