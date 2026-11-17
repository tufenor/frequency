"""Gerador de treino (flag `gerador_treino`) e aparelhos disponíveis da academia."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import aluno_auth
import aluno_treinos
import gerador_treino as gerador
import seguranca

RECURSO = "gerador_treino"
router = APIRouter(tags=["gerador-treino"])


def _erro(status: int, codigo: str) -> HTTPException:
    return HTTPException(status_code=status, detail=codigo)


def _exigir(conn, academia_id: int) -> None:
    if not aluno_auth.recurso_ligado(conn, academia_id, RECURSO):
        raise _erro(403, "gerador_desligado")


def equipamentos_do_catalogo(conn, academia_id: int) -> list[dict]:
    todos = [r["equipamento"] for r in conn.execute("SELECT DISTINCT equipamento FROM public.exercicios_catalogo WHERE ativo ORDER BY 1").fetchall()]
    off = {r["equipamento"] for r in conn.execute("SELECT equipamento FROM public.academia_equipamentos WHERE academia_id = %s AND NOT disponivel", (academia_id,)).fetchall()}
    return [{"equipamento": e, "disponivel": e not in off} for e in todos]


def indisponiveis(conn, academia_id: int) -> set[str]:
    return {r["equipamento"] for r in conn.execute("SELECT equipamento FROM public.academia_equipamentos WHERE academia_id = %s AND NOT disponivel", (academia_id,)).fetchall()}


# --------------------------------------------------------------------------- painel

class EquipamentosEntrada(BaseModel):
    indisponiveis: list[str] = Field(max_length=40)


@router.get("/academia/equipamentos")
def painel_equipamentos(usuario=Depends(seguranca.usuario_de_academia), conn=Depends(aluno_auth.conexao)):
    _exigir(conn, usuario["academia_id"])
    return {"equipamentos": equipamentos_do_catalogo(conn, usuario["academia_id"])}


@router.put("/academia/equipamentos")
def painel_definir_equipamentos(dados: EquipamentosEntrada, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir(conn, usuario["academia_id"])
    validos = {e["equipamento"] for e in equipamentos_do_catalogo(conn, usuario["academia_id"])}
    off = set(dados.indisponiveis)
    if not off <= validos:
        raise _erro(422, "equipamento_invalido")
    if validos <= off:
        raise _erro(422, "pelo_menos_um_equipamento")
    conn.execute("DELETE FROM public.academia_equipamentos WHERE academia_id = %s", (usuario["academia_id"],))
    for e in sorted(off):
        conn.execute("INSERT INTO public.academia_equipamentos (academia_id, equipamento, disponivel) VALUES (%s,%s,FALSE)", (usuario["academia_id"], e))
    conn.commit()
    return {"equipamentos": equipamentos_do_catalogo(conn, usuario["academia_id"])}


# --------------------------------------------------------------------------- aluno

class GerarEntrada(BaseModel):
    objetivo: str
    nivel: str
    dias: int = Field(ge=2, le=6)
    variacao: int = Field(default=0, ge=0, le=50)
    salvar: bool = False


@router.post("/aluno/treinos/gerar")
def gerar_treino(dados: GerarEntrada, aluno=Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    """Sem `salvar`, devolve só a proposta para o aluno revisar. Com `salvar`, cria os treinos pelas mesmas regras do editor."""
    _exigir(conn, aluno["academia_id"])
    catalogo = aluno_treinos.catalogo_efetivo(conn, aluno["academia_id"], aluno["id"])
    try:
        proposta = gerador.gerar(catalogo, dados.objetivo, dados.nivel, dados.dias, indisponiveis(conn, aluno["academia_id"]), dados.variacao)
    except gerador.PedidoInvalido as e:
        raise _erro(422, str(e))
    if not dados.salvar:
        return proposta
    atuais = conn.execute("SELECT count(*) AS n FROM public.treinos WHERE aluno_id = %s", (aluno["id"],)).fetchone()["n"]
    if atuais + len(proposta["treinos"]) > aluno_treinos.MAX_TREINOS:
        raise _erro(422, "limite_de_treinos")
    criados = []
    for t in proposta["treinos"]:
        criados.append(aluno_treinos.criar_treino(conn, aluno, aluno_treinos.TreinoEntrada(**t)))
    return {**proposta, "criados": criados}
