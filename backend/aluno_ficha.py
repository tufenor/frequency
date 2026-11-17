"""Ficha complementar do aluno, preenchida pela recepção/dono no painel.

Dados de saúde são sensíveis: só são lidos/gravados pelo painel autenticado da própria academia
e nunca entram em log.
"""

from __future__ import annotations

import os
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import aluno_auth
from seguranca import usuario_de_academia

router = APIRouter(tags=["alunos-ficha"])

_TEXTOS = ("contato_emergencia_nome", "contato_emergencia_telefone", "endereco_rua", "endereco_numero",
           "endereco_cidade", "objetivo", "restricoes_saude")
_CAMPOS = _TEXTOS + ("atestado_medico", "sexo", "peso_kg", "altura_cm")


class FichaEntrada(BaseModel):
    contato_emergencia_nome: str | None = Field(default=None, max_length=160)
    contato_emergencia_telefone: str | None = Field(default=None, max_length=40)
    endereco_rua: str | None = Field(default=None, max_length=200)
    endereco_numero: str | None = Field(default=None, max_length=20)
    endereco_cidade: str | None = Field(default=None, max_length=120)
    objetivo: str | None = Field(default=None, max_length=200)
    restricoes_saude: str | None = Field(default=None, max_length=1000)
    atestado_medico: bool | None = None
    sexo: str | None = Field(default=None, pattern="^(feminino|masculino|outro|nao_informar)$")
    peso_kg: Decimal | None = Field(default=None, ge=20, le=400, decimal_places=1)
    altura_cm: int | None = Field(default=None, ge=80, le=250)


def _aluno_existe(conn, academia_id: int, aluno_id: int) -> bool:
    return conn.execute("SELECT 1 FROM public.alunos WHERE id = %s AND academia_id = %s",
                        (aluno_id, academia_id)).fetchone() is not None


def _formatar(linha: dict | None) -> dict:
    base = {campo: None for campo in _CAMPOS}
    base["atestado_medico"] = False
    if linha:
        for campo in _CAMPOS:
            valor = linha.get(campo)
            base[campo] = float(valor) if isinstance(valor, Decimal) else valor
    return base


@router.get("/alunos/{aluno_id}/ficha")
def ler_ficha(aluno_id: int, usuario=Depends(usuario_de_academia), conn=Depends(aluno_auth.conexao)):
    if not _aluno_existe(conn, usuario["academia_id"], aluno_id):
        raise HTTPException(404, "aluno_nao_encontrado")
    linha = conn.execute("SELECT * FROM public.aluno_ficha WHERE aluno_id = %s", (aluno_id,)).fetchone()
    return _formatar(linha)


@router.put("/alunos/{aluno_id}/ficha")
def gravar_ficha(aluno_id: int, dados: FichaEntrada, usuario=Depends(usuario_de_academia),
                 conn=Depends(aluno_auth.conexao)):
    if os.getenv("SYNC_MIRROR_READ_ONLY", "").strip().upper() == "YES":
        raise HTTPException(403, "modo_somente_consulta")
    if not _aluno_existe(conn, usuario["academia_id"], aluno_id):
        raise HTTPException(404, "aluno_nao_encontrado")
    valores = {}
    for campo in _CAMPOS:
        v = getattr(dados, campo)
        if isinstance(v, str):
            v = v.strip() or None
        valores[campo] = v
    valores["atestado_medico"] = bool(valores["atestado_medico"])
    colunas = ", ".join(_CAMPOS)
    marcas = ", ".join(["%s"] * len(_CAMPOS))
    atualizar = ", ".join(f"{c} = EXCLUDED.{c}" for c in _CAMPOS)
    conn.execute(
        f"INSERT INTO public.aluno_ficha (aluno_id, {colunas}) VALUES (%s, {marcas}) "
        f"ON CONFLICT (aluno_id) DO UPDATE SET {atualizar}, atualizado_em = CURRENT_TIMESTAMP",
        (aluno_id, *[valores[c] for c in _CAMPOS]),
    )
    conn.commit()
    return {"ok": True}
