"""Mensalidade do aluno + QR de acesso assinado (flag `mensalidade_qr`). O pagamento online fica pronto e desligado."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import aluno_auth
import mensalidade_regras as regras
import seguranca

RECURSO = "mensalidade_qr"
router = APIRouter(tags=["mensalidade"])


def AGORA() -> datetime:
    return datetime.now(timezone.utc)


def _erro(status: int, codigo: str) -> HTTPException:
    return HTTPException(status_code=status, detail=codigo)


def _exigir(conn, academia_id: int) -> None:
    if not aluno_auth.recurso_ligado(conn, academia_id, RECURSO):
        raise _erro(403, "mensalidade_desligada")


def _linha_situacao(conn, aluno_id: int) -> dict | None:
    return conn.execute(
        "SELECT s.status_aluno, s.proximo_vencimento, s.alerta, a.plano_id, p.nome AS plano_nome, p.valor, ac.moeda "
        "FROM public.situacao_alunos s JOIN public.alunos a ON a.id = s.aluno_id JOIN public.academias ac ON ac.id = a.academia_id "
        "LEFT JOIN public.planos p ON p.id = a.plano_id WHERE s.aluno_id = %s", (aluno_id,)).fetchone()


@router.get("/aluno/mensalidade")
def minha_mensalidade(aluno=Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    _exigir(conn, aluno["academia_id"])
    l = _linha_situacao(conn, aluno["id"])
    if l is None:
        raise _erro(404, "aluno_nao_encontrado")
    hoje = AGORA().date()
    liberado, motivo = regras.decidir_liberacao(l["status_aluno"], l["plano_id"], l["proximo_vencimento"], l["alerta"])
    aberto = conn.execute("SELECT valor FROM public.pagamentos WHERE aluno_id = %s AND status = 'em_aberto' ORDER BY vencimento LIMIT 1", (aluno["id"],)).fetchone()
    return {"plano": l["plano_nome"], "proximo_vencimento": l["proximo_vencimento"].isoformat() if l["proximo_vencimento"] else None,
            "valor_em_aberto": float(aberto["valor"]) if aberto else None, "moeda": l["moeda"],
            **regras.situacao(l["proximo_vencimento"], hoje), "liberado": liberado, "motivo": motivo,
            "pagamento_online": False}


@router.post("/aluno/mensalidade/qr")
def gerar_meu_qr(request: Request, aluno=Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    _exigir(conn, aluno["academia_id"])
    aluno_auth._limitar(f"mensalidade-qr-gerar:{aluno['id']}", request)
    aluno_auth.limitador().record_failure(f"mensalidade-qr-gerar:{aluno['id']}", aluno_auth._ip(request))  # cada geração conta: evita rajada
    codigo, expira = regras.gerar_qr(seguranca.SECRET_KEY, aluno["id"], aluno["academia_id"], AGORA())
    return {"codigo": codigo, "expira_em": expira.isoformat(), "segundos": regras.SEGUNDOS_QR}


@router.post("/aluno/mensalidade/pagar")
def pagar_online(aluno=Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    """Rota pronta e desligada: depende das credenciais de pagamento do dono (dLocal). Nada é cobrado."""
    _exigir(conn, aluno["academia_id"])
    raise _erro(503, "pagamento_online_desligado")


class ConferirQr(BaseModel):
    codigo: str = Field(min_length=8, max_length=400)


@router.post("/academia/acesso/qr")
def conferir_qr(dados: ConferirQr, request: Request, usuario=Depends(seguranca.usuario_de_academia), conn=Depends(aluno_auth.conexao)):
    """Recepção confere o QR do aluno. Só consulta: não registra presença e não guarda o código."""
    _exigir(conn, usuario["academia_id"])
    chave = f"mensalidade-qr-conferir:{usuario['id']}"
    aluno_auth._limitar(chave, request)
    aluno_id = regras.validar_qr(seguranca.SECRET_KEY, dados.codigo, usuario["academia_id"], AGORA())
    if aluno_id is None:
        aluno_auth.limitador().record_failure(chave, aluno_auth._ip(request))
        raise _erro(400, "qr_invalido")
    a = conn.execute("SELECT a.nome FROM public.alunos a WHERE a.id = %s AND a.academia_id = %s", (aluno_id, usuario["academia_id"])).fetchone()
    l = _linha_situacao(conn, aluno_id)
    if a is None or l is None:
        raise _erro(400, "qr_invalido")
    liberado, motivo = regras.decidir_liberacao(l["status_aluno"], l["plano_id"], l["proximo_vencimento"], l["alerta"])
    dias = (l["proximo_vencimento"] - AGORA().date()).days if l["proximo_vencimento"] else None
    return {"nome": a["nome"], "liberado": liberado, "motivo": motivo, "dias_restantes": dias}
