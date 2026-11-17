from __future__ import annotations


def estado_relogio_local(conn, academia_id: int) -> dict[str, object]:
    """Persist the furthest local calendar date seen for an academy.

    The database clock is the authority used by the local membership views.
    Once a later date has been observed, moving the computer clock backwards
    leaves the academy blocked instead of reactivating an expired plan.
    """
    presente = conn.execute(
        "SELECT to_regclass('public.relogio_local') IS NOT NULL AS presente"
    ).fetchone()["presente"]
    if not presente:
        return {
            "relogio_recuou": False,
            "motivo_bloqueio": None,
            "data_referencia": None,
        }

    agora = conn.execute(
        "SELECT CURRENT_DATE AS hoje, CURRENT_TIMESTAMP AS agora"
    ).fetchone()
    registro = conn.execute(
        "SELECT maior_data, relogio_recuou FROM public.relogio_local "
        "WHERE academia_id = %s FOR UPDATE",
        (academia_id,),
    ).fetchone()

    if registro is None:
        conn.execute(
            "INSERT INTO public.relogio_local "
            "(academia_id, maior_data, ultima_observacao) VALUES (%s, %s, %s)",
            (academia_id, agora["hoje"], agora["agora"]),
        )
        return {
            "relogio_recuou": False,
            "motivo_bloqueio": None,
            "data_referencia": agora["hoje"],
        }

    if registro["relogio_recuou"] or agora["hoje"] < registro["maior_data"]:
        conn.execute(
            "UPDATE public.relogio_local SET relogio_recuou = TRUE, "
            "relogio_recuou_em = COALESCE(relogio_recuou_em, %s), "
            "ultima_observacao = %s WHERE academia_id = %s",
            (agora["agora"], agora["agora"], academia_id),
        )
        return {
            "relogio_recuou": True,
            "motivo_bloqueio": "relogio_local_recuou",
            "data_referencia": agora["hoje"],
        }

    conn.execute(
        "UPDATE public.relogio_local SET maior_data = %s, "
        "ultima_observacao = %s WHERE academia_id = %s",
        (max(registro["maior_data"], agora["hoje"]), agora["agora"], academia_id),
    )
    return {
        "relogio_recuou": False,
        "motivo_bloqueio": None,
        "data_referencia": agora["hoje"],
    }
