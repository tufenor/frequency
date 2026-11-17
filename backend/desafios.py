"""Desafios com ranking (flag `desafios`). Pontuação calculada das séries registradas; ranking mostra só 'Nome I.'."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

import aluno_auth
import desafios_regras as regras
import lutas
import seguranca

RECURSO = "desafios"
MAX_ATIVOS = 10
MAX_PARTICIPANTES = 500
TOP_RANKING = 20
router = APIRouter(tags=["desafios"])


def AGORA() -> datetime:
    return datetime.now(timezone.utc)


def _erro(status: int, codigo: str) -> HTTPException:
    return HTTPException(status_code=status, detail=codigo)


def _exigir(conn, academia_id: int) -> None:
    if not aluno_auth.recurso_ligado(conn, academia_id, RECURSO):
        raise _erro(403, "desafios_desligado")


def _hash(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def _desafio(conn, academia_id: int, did: int) -> dict:
    d = conn.execute("SELECT * FROM public.desafios WHERE id = %s AND academia_id = %s", (did, academia_id)).fetchone()
    if d is None:
        raise _erro(404, "desafio_nao_encontrado")
    return d


def ranking_do_desafio(conn, d: dict) -> list[dict]:
    fuso = lutas._fuso(conn, d["academia_id"])
    parts = conn.execute(
        "SELECT p.aluno_id, p.entrou_em, a.nome FROM public.desafios_participacao p JOIN public.alunos a ON a.id = p.aluno_id "
        "WHERE p.desafio_id = %s AND a.academia_id = %s AND a.status = 'ativo' LIMIT %s", (d["id"], d["academia_id"], MAX_PARTICIPANTES)).fetchall()
    ids = [p["aluno_id"] for p in parts]
    por: dict[int, list[dict]] = {i: [] for i in ids}
    if ids:
        for s in conn.execute(
                "SELECT aluno_id, registrada_em, carga, reps, concluida FROM public.aluno_series_registradas "
                "WHERE aluno_id = ANY(%s) AND concluida AND registrada_em >= %s::date - 1 AND registrada_em < %s::date + 2",
                (ids, d["inicio"], d["fim"])).fetchall():
            por[s["aluno_id"]].append(s)
    linhas = [{"aluno_id": p["aluno_id"], "nome": p["nome"],
               "valor": regras.pontuar(por[p["aluno_id"]], d["metrica"], d["inicio"], d["fim"], p["entrou_em"], fuso)} for p in parts]
    return regras.classificar(linhas)


def _publico(linhas: list[dict], d: dict, limite: int = TOP_RANKING) -> list[dict]:
    return [{"posicao": l["posicao"], "nome": regras.nome_publico(l["nome"]), "valor": l["valor"]} for l in linhas if l["posicao"] is not None][:limite]


def _json_desafio(d: dict, hoje: date, participantes: int | None = None) -> dict:
    return {"id": d["id"], "nome": d["nome"], "metrica": d["metrica"], "inicio": d["inicio"].isoformat(), "fim": d["fim"].isoformat(),
            "situacao": regras.situacao_do_desafio(d["inicio"], d["fim"], d["ativo"], hoje),
            **({"participantes": participantes} if participantes is not None else {})}


# --------------------------------------------------------------------------- painel

class DesafioEntrada(BaseModel):
    nome: str = Field(min_length=2, max_length=80)
    metrica: str = Field(pattern="^(treinos|volume)$")
    inicio: date
    fim: date


class DesafioAjuste(BaseModel):
    ativo: bool


@router.get("/academia/desafios")
def painel_listar(usuario=Depends(seguranca.usuario_de_academia), conn=Depends(aluno_auth.conexao)):
    _exigir(conn, usuario["academia_id"])
    hoje = AGORA().date()
    ls = conn.execute("SELECT d.*, (SELECT count(*) FROM public.desafios_participacao p WHERE p.desafio_id = d.id) AS n, (d.tv_token_hash IS NOT NULL) AS tem_tv "
                      "FROM public.desafios d WHERE d.academia_id = %s ORDER BY d.fim DESC, d.id DESC LIMIT 100", (usuario["academia_id"],)).fetchall()
    return {"desafios": [{**_json_desafio(d, hoje, d["n"]), "tv_ativa": d["tem_tv"]} for d in ls]}


@router.post("/academia/desafios", status_code=201)
def painel_criar(dados: DesafioEntrada, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir(conn, usuario["academia_id"])
    if dados.fim < dados.inicio or (dados.fim - dados.inicio).days > 366:
        raise _erro(422, "periodo_invalido")
    n = conn.execute("SELECT count(*) AS n FROM public.desafios WHERE academia_id = %s AND ativo AND fim >= CURRENT_DATE", (usuario["academia_id"],)).fetchone()["n"]
    if n >= MAX_ATIVOS:
        raise _erro(409, "limite_de_desafios")
    d = conn.execute("INSERT INTO public.desafios (academia_id, nome, metrica, inicio, fim) VALUES (%s,%s,%s,%s,%s) RETURNING *",
                     (usuario["academia_id"], dados.nome.strip(), dados.metrica, dados.inicio, dados.fim)).fetchone()
    conn.commit()
    return _json_desafio(d, AGORA().date(), 0)


@router.patch("/academia/desafios/{did}")
def painel_ajustar(did: int, dados: DesafioAjuste, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir(conn, usuario["academia_id"])
    _desafio(conn, usuario["academia_id"], did)
    d = conn.execute("UPDATE public.desafios SET ativo = %s, tv_token_hash = CASE WHEN %s THEN tv_token_hash ELSE NULL END WHERE id = %s RETURNING *",
                     (dados.ativo, dados.ativo, did)).fetchone()
    conn.commit()
    return _json_desafio(d, AGORA().date())


@router.get("/academia/desafios/{did}/ranking")
def painel_ranking(did: int, usuario=Depends(seguranca.usuario_de_academia), conn=Depends(aluno_auth.conexao)):
    _exigir(conn, usuario["academia_id"])
    d = _desafio(conn, usuario["academia_id"], did)
    return {"desafio": _json_desafio(d, AGORA().date()), "ranking": _publico(ranking_do_desafio(conn, d), d, 100)}


@router.post("/academia/desafios/{did}/tv")
def painel_gerar_tv(did: int, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    """Gera (ou troca) o endereço da TV. O token aparece só nesta resposta; o anterior deixa de valer."""
    _exigir(conn, usuario["academia_id"])
    d = _desafio(conn, usuario["academia_id"], did)
    if not d["ativo"]:
        raise _erro(409, "desafio_encerrado")
    token = "frk_" + secrets.token_urlsafe(24)
    conn.execute("UPDATE public.desafios SET tv_token_hash = %s WHERE id = %s", (_hash(token), did))
    conn.commit()
    return {"token": token, "caminho": f"/painel/ranking/{token}"}


@router.delete("/academia/desafios/{did}/tv", status_code=204)
def painel_revogar_tv(did: int, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir(conn, usuario["academia_id"])
    _desafio(conn, usuario["academia_id"], did)
    conn.execute("UPDATE public.desafios SET tv_token_hash = NULL WHERE id = %s", (did,))
    conn.commit()


# --------------------------------------------------------------------------- TV (somente leitura, sem login)

@router.get("/painel/ranking/{token}/dados")
def tv_dados(token: str, request: Request, conn=Depends(aluno_auth.conexao)):
    chave = "ranking-tv"
    aluno_auth._limitar(chave, request)
    d = conn.execute("SELECT d.*, a.nome AS academia FROM public.desafios d JOIN public.academias a ON a.id = d.academia_id "
                     "WHERE d.tv_token_hash = %s AND d.ativo AND a.ativa", (_hash(token[:80]),)).fetchone() if token.startswith("frk_") else None
    if d is None:
        aluno_auth.limitador().record_failure(chave, aluno_auth._ip(request))
        raise _erro(404, "ranking_nao_encontrado")
    if not aluno_auth.recurso_ligado(conn, d["academia_id"], RECURSO):
        raise _erro(404, "ranking_nao_encontrado")
    resp = JSONResponse({"academia": d["academia"], "desafio": _json_desafio(d, AGORA().date()), "ranking": _publico(ranking_do_desafio(conn, d), d, 10)})
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def _pasta_frontend() -> Path:
    padrao = Path(__file__).resolve().parent.parent / "frontend" / "public"
    return Path(os.getenv("FREQUENCY_FRONTEND_DIR", str(padrao))).resolve()


@router.get("/painel/ranking/{token}")
def tv_pagina(token: str):
    resp = FileResponse(_pasta_frontend() / "ranking.html")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                                              "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    return resp


# --------------------------------------------------------------------------- aluno

@router.get("/aluno/desafios")
def aluno_listar(aluno=Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    _exigir(conn, aluno["academia_id"])
    hoje = AGORA().date()
    ds = conn.execute("SELECT d.*, (SELECT count(*) FROM public.desafios_participacao p WHERE p.desafio_id = d.id) AS n, "
                      "EXISTS (SELECT 1 FROM public.desafios_participacao p WHERE p.desafio_id = d.id AND p.aluno_id = %s) AS participo "
                      "FROM public.desafios d WHERE d.academia_id = %s AND d.ativo AND d.fim >= %s - 30 ORDER BY d.fim DESC LIMIT 30",
                      (aluno["id"], aluno["academia_id"], hoje)).fetchall()
    out = []
    for d in ds:
        item = {**_json_desafio(d, hoje, d["n"]), "participo": d["participo"]}
        if d["participo"]:
            r = ranking_do_desafio(conn, d)
            eu = next((l for l in r if l["aluno_id"] == aluno["id"]), None)
            item["minha_posicao"], item["meu_valor"] = (eu["posicao"], eu["valor"]) if eu else (None, 0)
        out.append(item)
    return {"desafios": out}


@router.post("/aluno/desafios/{did}/participar")
def aluno_participar(did: int, aluno=Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    _exigir(conn, aluno["academia_id"])
    d = _desafio(conn, aluno["academia_id"], did)
    if regras.situacao_do_desafio(d["inicio"], d["fim"], d["ativo"], AGORA().date()) == "encerrado":
        raise _erro(409, "desafio_encerrado")
    n = conn.execute("SELECT count(*) AS n FROM public.desafios_participacao WHERE desafio_id = %s", (did,)).fetchone()["n"]
    if n >= MAX_PARTICIPANTES:
        raise _erro(409, "desafio_lotado")
    conn.execute("INSERT INTO public.desafios_participacao (desafio_id, aluno_id, entrou_em) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (did, aluno["id"], AGORA()))
    conn.commit()
    return {"participo": True}


@router.delete("/aluno/desafios/{did}/participar", status_code=204)
def aluno_sair(did: int, aluno=Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    _exigir(conn, aluno["academia_id"])
    _desafio(conn, aluno["academia_id"], did)
    conn.execute("DELETE FROM public.desafios_participacao WHERE desafio_id = %s AND aluno_id = %s", (did, aluno["id"]))
    conn.commit()


@router.get("/aluno/desafios/{did}/ranking")
def aluno_ranking(did: int, aluno=Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    _exigir(conn, aluno["academia_id"])
    d = _desafio(conn, aluno["academia_id"], did)
    r = ranking_do_desafio(conn, d)
    eu = next((l for l in r if l["aluno_id"] == aluno["id"]), None)
    return {"desafio": _json_desafio(d, AGORA().date()), "ranking": _publico(r, d), "eu": {"posicao": eu["posicao"], "valor": eu["valor"]} if eu else None}
