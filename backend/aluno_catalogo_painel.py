"""Painel da academia: ativar/ocultar exercícios do catálogo global e manter exercícios próprios da academia.

Leitura: dono e recepção. Escrita: somente dono. Sempre isolado pela academia do usuário logado.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import aluno_auth
import aluno_treinos
from seguranca import somente_dono, usuario_de_academia

router = APIRouter(tags=["academia-exercicios"])
MINIMO_ATIVOS_POR_GRUPO = 10


class VisibilidadeEntrada(BaseModel):
    oculto: bool


class ExercicioAcademiaEntrada(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    grupo: str
    equipamento: str = Field(default="", max_length=80)
    tempo: bool = False


class ExercicioAcademiaAjuste(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=120)
    grupo: str | None = None
    equipamento: str | None = Field(default=None, max_length=80)
    tempo: bool | None = None
    ativo: bool | None = None


def _mesma_academia(usuario: dict, academia_id: int) -> None:
    if usuario["academia_id"] != academia_id:
        raise HTTPException(403, "sem_permissao")


def _escrita_local() -> None:
    if os.getenv("SYNC_MIRROR_READ_ONLY", "").strip().upper() == "YES":
        raise HTTPException(403, "modo_somente_consulta")


def visao_da_academia(conn, academia_id: int) -> dict:
    exercicios = []
    for l in conn.execute(
        "SELECT c.id, c.nome, c.grupo, c.equipamento, c.nivel, COALESCE(v.oculto, FALSE) AS oculto "
        "FROM public.exercicios_catalogo c LEFT JOIN public.academia_exercicios_visibilidade v "
        "  ON v.exercicio_id = c.id AND v.academia_id = %s WHERE c.ativo ORDER BY c.grupo, c.nivel, c.nome",
        (academia_id,)).fetchall():
        exercicios.append({"ref": "c:" + l["id"], "origem": "catalogo", "nome": l["nome"], "grupo": l["grupo"],
                           "equipamento": l["equipamento"], "nivel": l["nivel"], "oculto": l["oculto"]})
    for l in conn.execute(
        "SELECT id, nome, grupo, equipamento, tempo, ativo FROM public.exercicios_custom "
        "WHERE academia_id = %s AND escopo = 'academia' ORDER BY grupo, nome", (academia_id,)).fetchall():
        exercicios.append({"ref": f"x:{l['id']}", "origem": "academia", "nome": l["nome"], "grupo": l["grupo"],
                           "equipamento": l["equipamento"], "nivel": None, "oculto": not l["ativo"]})
    resumo = {g: {"grupo": g, "ativos": 0, "total": 0} for g in aluno_treinos.GRUPOS}
    for e in exercicios:
        r = resumo[e["grupo"]]
        r["total"] += 1
        if not e["oculto"]:
            r["ativos"] += 1
    grupos = []
    for g in aluno_treinos.GRUPOS:
        r = resumo[g]
        r["aviso"] = r["ativos"] < MINIMO_ATIVOS_POR_GRUPO
        grupos.append(r)
    return {"grupos": grupos, "exercicios": exercicios}


@router.get("/academias/{academia_id}/exercicios")
def rota_listar(academia_id: int, usuario=Depends(usuario_de_academia), conn=Depends(aluno_auth.conexao)):
    _mesma_academia(usuario, academia_id)
    return visao_da_academia(conn, academia_id)


@router.put("/academias/{academia_id}/exercicios/{exercicio_id}/visibilidade")
def rota_visibilidade(academia_id: int, exercicio_id: str, dados: VisibilidadeEntrada,
                      usuario=Depends(somente_dono), conn=Depends(aluno_auth.conexao)):
    _mesma_academia(usuario, academia_id)
    _escrita_local()
    existe = conn.execute("SELECT 1 FROM public.exercicios_catalogo WHERE id = %s AND ativo", (exercicio_id,)).fetchone()
    if existe is None:
        raise HTTPException(404, "exercicio_nao_encontrado")
    conn.execute(
        "INSERT INTO public.academia_exercicios_visibilidade (academia_id, exercicio_id, oculto) VALUES (%s,%s,%s) "
        "ON CONFLICT (academia_id, exercicio_id) DO UPDATE SET oculto = EXCLUDED.oculto, atualizado_em = CURRENT_TIMESTAMP",
        (academia_id, exercicio_id, dados.oculto))
    conn.commit()
    return {"ref": "c:" + exercicio_id, "oculto": dados.oculto}


@router.post("/academias/{academia_id}/exercicios", status_code=201)
def rota_criar(academia_id: int, dados: ExercicioAcademiaEntrada, usuario=Depends(somente_dono),
               conn=Depends(aluno_auth.conexao)):
    _mesma_academia(usuario, academia_id)
    _escrita_local()
    if dados.grupo not in aluno_treinos.GRUPOS:
        raise HTTPException(422, "grupo_invalido")
    novo = conn.execute(
        "INSERT INTO public.exercicios_custom (escopo, academia_id, nome, grupo, equipamento, tempo) "
        "VALUES ('academia', %s, %s, %s, %s, %s) RETURNING id",
        (academia_id, dados.nome.strip(), dados.grupo, dados.equipamento.strip(), dados.tempo)).fetchone()["id"]
    conn.commit()
    return {"ref": f"x:{novo}", "nome": dados.nome.strip(), "grupo": dados.grupo}


@router.patch("/academias/{academia_id}/exercicios/{exercicio_id}")
def rota_ajustar(academia_id: int, exercicio_id: int, dados: ExercicioAcademiaAjuste,
                 usuario=Depends(somente_dono), conn=Depends(aluno_auth.conexao)):
    _mesma_academia(usuario, academia_id)
    _escrita_local()
    if dados.grupo is not None and dados.grupo not in aluno_treinos.GRUPOS:
        raise HTTPException(422, "grupo_invalido")
    atual = conn.execute(
        "SELECT id FROM public.exercicios_custom WHERE id = %s AND academia_id = %s AND escopo = 'academia'",
        (exercicio_id, academia_id)).fetchone()
    if atual is None:
        raise HTTPException(404, "exercicio_nao_encontrado")
    campos = {k: v for k, v in dados.model_dump().items() if v is not None}
    if "nome" in campos:
        campos["nome"] = campos["nome"].strip()
    if campos:
        sets = ", ".join(f"{k} = %s" for k in campos)
        conn.execute(f"UPDATE public.exercicios_custom SET {sets} WHERE id = %s", (*campos.values(), exercicio_id))
        conn.commit()
    return {"ref": f"x:{exercicio_id}", **campos}


@router.delete("/academias/{academia_id}/exercicios/{exercicio_id}", status_code=204)
def rota_remover(academia_id: int, exercicio_id: int, usuario=Depends(somente_dono), conn=Depends(aluno_auth.conexao)):
    _mesma_academia(usuario, academia_id)
    _escrita_local()
    n = conn.execute(
        "UPDATE public.exercicios_custom SET ativo = FALSE WHERE id = %s AND academia_id = %s AND escopo = 'academia'",
        (exercicio_id, academia_id)).rowcount
    if n == 0:
        raise HTTPException(404, "exercicio_nao_encontrado")
    conn.commit()


# Atalhos usados pelo painel web: a academia é a do usuário logado (sem precisar do id na URL).

@router.get("/academia/exercicios")
def atalho_listar(usuario=Depends(usuario_de_academia), conn=Depends(aluno_auth.conexao)):
    return visao_da_academia(conn, usuario["academia_id"])


@router.put("/academia/exercicios/{exercicio_id}/visibilidade")
def atalho_visibilidade(exercicio_id: str, dados: VisibilidadeEntrada, usuario=Depends(somente_dono),
                        conn=Depends(aluno_auth.conexao)):
    return rota_visibilidade(usuario["academia_id"], exercicio_id, dados, usuario, conn)


@router.post("/academia/exercicios", status_code=201)
def atalho_criar(dados: ExercicioAcademiaEntrada, usuario=Depends(somente_dono), conn=Depends(aluno_auth.conexao)):
    return rota_criar(usuario["academia_id"], dados, usuario, conn)


@router.patch("/academia/exercicios/{exercicio_id}")
def atalho_ajustar(exercicio_id: int, dados: ExercicioAcademiaAjuste, usuario=Depends(somente_dono),
                   conn=Depends(aluno_auth.conexao)):
    return rota_ajustar(usuario["academia_id"], exercicio_id, dados, usuario, conn)


@router.delete("/academia/exercicios/{exercicio_id}", status_code=204)
def atalho_remover(exercicio_id: int, usuario=Depends(somente_dono), conn=Depends(aluno_auth.conexao)):
    rota_remover(usuario["academia_id"], exercicio_id, usuario, conn)
