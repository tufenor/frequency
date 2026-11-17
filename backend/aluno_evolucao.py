"""Evolução do aluno: séries registradas (lote idempotente), medidas, meta de peso, consentimento e resumo.

Tudo é isolado por aluno_id. `client_id` repetido nunca duplica. Fotos de progresso não passam por aqui.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import aluno_auth
import aluno_evolucao_calc as calc

MAX_LOTE = 200
TIPOS_MEDIDA = ("peso", "gordura", "cintura", "quadril", "peito", "braco", "coxa", "panturrilha")

router = APIRouter(prefix="/aluno", tags=["aluno-evolucao"])


class SerieEntrada(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)
    registrada_em: datetime
    treino_uid: str | None = Field(default=None, max_length=64)
    exercicio_ref: str = Field(min_length=1, max_length=64)
    exercicio_nome: str = Field(min_length=1, max_length=120)
    grupo: str = Field(min_length=1, max_length=30)
    serie_numero: int = Field(ge=1, le=50)
    carga: float = Field(ge=0, le=1000)
    reps: int = Field(ge=0, le=500)
    concluida: bool = True


class LoteEntrada(BaseModel):
    series: list[SerieEntrada]


class MedidaEntrada(BaseModel):
    data: date
    tipo: str
    valor: float = Field(gt=0, lt=1000)


class MetaEntrada(BaseModel):
    peso_alvo: float | None = Field(default=None, gt=20, lt=500)


class ConsentimentoEntrada(BaseModel):
    compartilhar_com_academia: bool


def _erro(status: int, codigo: str) -> HTTPException:
    return HTTPException(status_code=status, detail=codigo)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def gravar_lote(conn, aluno: dict, lote: LoteEntrada) -> dict:
    if len(lote.series) > MAX_LOTE:
        raise _erro(413, "lote_grande_demais")
    futuro = _agora() + timedelta(days=1)
    for s in lote.series:
        reg = s.registrada_em if s.registrada_em.tzinfo else s.registrada_em.replace(tzinfo=timezone.utc)
        if reg > futuro:
            raise _erro(422, "data_no_futuro")
    novas = 0
    confirmadas = []
    for s in lote.series:
        cur = conn.execute(
            """INSERT INTO aluno_series_registradas
               (aluno_id, client_id, registrada_em, treino_uid, exercicio_ref, exercicio_nome, grupo,
                serie_numero, carga, reps, concluida)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (aluno_id, client_id) DO NOTHING""",
            (aluno["id"], s.client_id, s.registrada_em, s.treino_uid, s.exercicio_ref, s.exercicio_nome,
             s.grupo, s.serie_numero, s.carga, s.reps, s.concluida))
        novas += cur.rowcount
        confirmadas.append(s.client_id)
    conn.commit()
    return {"confirmadas": confirmadas, "novas": novas}


def listar_series(conn, aluno: dict, desde: datetime | None, limite: int) -> list[dict]:
    limite = max(1, min(limite, 1000))
    linhas = conn.execute(
        """SELECT client_id, registrada_em, treino_uid, exercicio_ref, exercicio_nome, grupo, serie_numero,
                  carga, reps, concluida
           FROM aluno_series_registradas
           WHERE aluno_id = %s AND (%s::timestamptz IS NULL OR registrada_em >= %s)
           ORDER BY registrada_em DESC, id DESC LIMIT %s""",
        (aluno["id"], desde, desde, limite)).fetchall()
    return [{**l, "carga": float(l["carga"])} for l in linhas]


def apagar_serie(conn, aluno: dict, client_id: str) -> None:
    """Idempotente: apagar uma série que não existe também é sucesso (a fila do app pode reenviar)."""
    conn.execute("DELETE FROM aluno_series_registradas WHERE aluno_id = %s AND client_id = %s", (aluno["id"], client_id))
    conn.commit()


def listar_medidas(conn, aluno: dict, tipo: str | None) -> list[dict]:
    if tipo is not None and tipo not in TIPOS_MEDIDA:
        raise _erro(422, "tipo_invalido")
    linhas = conn.execute(
        """SELECT id, data, tipo, valor FROM aluno_medidas
           WHERE aluno_id = %s AND (%s::text IS NULL OR tipo = %s) ORDER BY data DESC, id DESC LIMIT 1000""",
        (aluno["id"], tipo, tipo)).fetchall()
    return [{"id": l["id"], "data": l["data"].isoformat(), "tipo": l["tipo"], "valor": float(l["valor"])} for l in linhas]


def gravar_medida(conn, aluno: dict, m: MedidaEntrada) -> dict:
    if m.tipo not in TIPOS_MEDIDA:
        raise _erro(422, "tipo_invalido")
    if m.data > _agora().date() + timedelta(days=1):
        raise _erro(422, "data_no_futuro")
    l = conn.execute(
        """INSERT INTO aluno_medidas (aluno_id, data, tipo, valor) VALUES (%s,%s,%s,%s)
           ON CONFLICT (aluno_id, data, tipo) DO UPDATE SET valor = EXCLUDED.valor
           RETURNING id, data, tipo, valor""",
        (aluno["id"], m.data, m.tipo, m.valor)).fetchone()
    conn.commit()
    return {"id": l["id"], "data": l["data"].isoformat(), "tipo": l["tipo"], "valor": float(l["valor"])}


def apagar_medida(conn, aluno: dict, medida_id: int) -> None:
    cur = conn.execute("DELETE FROM aluno_medidas WHERE id = %s AND aluno_id = %s", (medida_id, aluno["id"]))
    if cur.rowcount == 0:
        conn.rollback()
        raise _erro(404, "medida_nao_encontrada")
    conn.commit()


def definir_meta(conn, aluno: dict, peso_alvo: float | None) -> dict:
    conn.execute(
        """INSERT INTO aluno_metas (aluno_id, peso_alvo) VALUES (%s,%s)
           ON CONFLICT (aluno_id) DO UPDATE SET peso_alvo = EXCLUDED.peso_alvo, atualizado_em = CURRENT_TIMESTAMP""",
        (aluno["id"], peso_alvo))
    conn.commit()
    return {"peso_alvo": peso_alvo}


def obter_consentimento(conn, aluno: dict) -> dict:
    l = conn.execute("SELECT compartilhar_com_academia FROM aluno_consentimentos WHERE aluno_id = %s",
                     (aluno["id"],)).fetchone()
    return {"compartilhar_com_academia": bool(l and l["compartilhar_com_academia"])}


def definir_consentimento(conn, aluno: dict, valor: bool) -> dict:
    conn.execute(
        """INSERT INTO aluno_consentimentos (aluno_id, compartilhar_com_academia) VALUES (%s,%s)
           ON CONFLICT (aluno_id) DO UPDATE SET compartilhar_com_academia = EXCLUDED.compartilhar_com_academia,
                                                atualizado_em = CURRENT_TIMESTAMP""",
        (aluno["id"], valor))
    conn.commit()
    return {"compartilhar_com_academia": valor}


def evolucao(conn, aluno: dict, agora: datetime | None = None) -> dict:
    agora = agora or _agora()
    hoje = agora.date()
    series = conn.execute(
        """SELECT registrada_em, exercicio_ref, exercicio_nome, grupo, carga, reps, concluida
           FROM aluno_series_registradas WHERE aluno_id = %s AND registrada_em >= %s""",
        (aluno["id"], agora - timedelta(days=400))).fetchall()
    checkins = conn.execute(
        "SELECT DISTINCT data_hora::date AS d FROM presencas WHERE aluno_id = %s AND liberado AND data_hora >= %s",
        (aluno["id"], agora - timedelta(days=400))).fetchall()
    dias = {s["registrada_em"].date() for s in series if s["concluida"]} | {c["d"] for c in checkins}
    peso = conn.execute(
        "SELECT data, valor FROM aluno_medidas WHERE aluno_id = %s AND tipo = 'peso' ORDER BY data DESC LIMIT 60",
        (aluno["id"],)).fetchall()
    meta = conn.execute("SELECT peso_alvo FROM aluno_metas WHERE aluno_id = %s", (aluno["id"],)).fetchone()
    top = sorted(calc.recordes(series).values(), key=lambda r: -r["carga"])[:10]
    return {
        "semana": calc.resumo_semanal(series, hoje),
        "pulso": calc.pulso_semanal(series, hoje),
        "sequencia_semanas": calc.sequencia_semanal(dias, hoje),
        "mapa_7_dias": calc.mapa_do_corpo(series, agora),
        "recordes": top,
        "peso": [{"data": p["data"].isoformat(), "valor": float(p["valor"])} for p in reversed(peso)],
        "peso_alvo": float(meta["peso_alvo"]) if meta and meta["peso_alvo"] is not None else None,
    }


# --------------------------------------------------------------------------- rotas

@router.post("/series")
def rota_series(lote: LoteEntrada, aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return gravar_lote(conn, aluno, lote)


@router.get("/series")
def rota_listar_series(desde: datetime | None = None, limite: int = 200,
                       aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return {"series": listar_series(conn, aluno, desde, limite)}


@router.delete("/series/{client_id}", status_code=204)
def rota_apagar_serie(client_id: str, aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    apagar_serie(conn, aluno, client_id)


@router.get("/medidas")
def rota_medidas(tipo: str | None = None, aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return {"medidas": listar_medidas(conn, aluno, tipo)}


@router.post("/medidas", status_code=201)
def rota_gravar_medida(m: MedidaEntrada, aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return gravar_medida(conn, aluno, m)


@router.delete("/medidas/{medida_id}", status_code=204)
def rota_apagar_medida(medida_id: int, aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    apagar_medida(conn, aluno, medida_id)


@router.put("/meta-peso")
def rota_meta(m: MetaEntrada, aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return definir_meta(conn, aluno, m.peso_alvo)


@router.get("/consentimento")
def rota_consentimento(aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return obter_consentimento(conn, aluno)


@router.put("/consentimento")
def rota_definir_consentimento(c: ConsentimentoEntrada, aluno: dict = Depends(aluno_auth.aluno_atual),
                               conn=Depends(aluno_auth.conexao)):
    return definir_consentimento(conn, aluno, c.compartilhar_com_academia)


@router.get("/evolucao")
def rota_evolucao(aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return evolucao(conn, aluno)
