"""Server-side entitlements. Unconfigured installations never grant extras."""
from fastapi import HTTPException


def esquema_disponivel(conn):
    # A consulta retorna somente um booleano; isso evita materializar linhas de
    # information_schema em cada endpoint que valida recursos premium.
    return conn.execute(
        "SELECT EXISTS ("
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'planos_frequency' "
        "AND column_name IN ('nivel', 'cameras', 'youtube', 'max_monitores', 'max_leitores', 'max_alunos') "
        "GROUP BY table_schema, table_name HAVING count(*) = 6"
        ") AS presente"
    ).fetchone()["presente"]


def exigir_esquema(conn):
    if not esquema_disponivel(conn):
        raise HTTPException(503, "migracao_premium_pendente")


def recursos_da_academia(conn, academia_id):
    empty = {
        "nivel": None,
        "cameras": False,
        "youtube": False,
        "max_monitores": 0,
        "max_leitores": 0,
        "max_alunos": 0,
    }
    if not esquema_disponivel(conn):
        return empty
    plan = conn.execute(
        "SELECT p.nivel, p.cameras, p.youtube, p.max_monitores, p.max_leitores, p.max_alunos FROM public.assinaturas_frequency s "
        "JOIN public.planos_frequency p ON p.id = s.plano_id "
        "WHERE s.academia_id = %s AND s.status = 'ativa' "
        "ORDER BY s.id DESC LIMIT 1", (academia_id,)
    ).fetchone()
    if not plan:
        return empty
    return {
        "nivel": plan["nivel"],
        "cameras": plan["nivel"] == "premium" and plan["cameras"],
        "youtube": plan["nivel"] == "premium" and plan["youtube"],
        "max_monitores": plan["max_monitores"],
        "max_leitores": plan["max_leitores"],
        "max_alunos": plan["max_alunos"],
    }


def validar_plano(conn, data, plano_id=None):
    """Compare daily prices only within the same currency; serialize changes."""
    exigir_esquema(conn)
    conn.execute("SELECT pg_advisory_xact_lock(89430129)")
    if data["nivel"] != "premium" and (data["cameras"] or data["youtube"]):
        raise HTTPException(400, "recursos_exclusivos_premium")
    if not data.get("ativo", True):
        return
    # A comparação fica no banco para não trazer todos os planos para Python.
    # O produto cruzado preserva a precisão de Decimal sem divisão por zero.
    conflito = conn.execute(
        "SELECT EXISTS ("
        "SELECT 1 FROM public.planos_frequency "
        "WHERE moeda = %s AND ativo AND (%s::bigint IS NULL OR id <> %s) "
        "AND ((%s = 'premium' AND nivel <> 'premium' "
        "      AND %s * duracao_dias <= valor * %s) "
        "  OR (%s <> 'premium' AND nivel = 'premium' "
        "      AND %s * duracao_dias >= valor * %s))"
        ") AS presente",
        (
            data["moeda"], plano_id, plano_id,
            data["nivel"], data["valor"], data["duracao_dias"],
            data["nivel"], data["valor"], data["duracao_dias"],
        ),
    ).fetchone()["presente"]
    if conflito:
        raise HTTPException(400, "premium_deve_ser_mais_caro")
