"""Quiosque do tablet: identifica o aluno (rosto, QR ou e-mail + código) e libera, por poucos minutos,
a leitura do treino do dia e das últimas cargas. O ticket do quiosque NÃO edita nada nem mostra dados sensíveis.

Nenhuma imagem é gravada. O reconhecimento facial reaproveita o mesmo motor e limiares do /acesso/facial.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

import aluno_auth
import aluno_treinos
from seguranca import somente_dono

RECURSO = "quiosque"
MINUTOS_TICKET = 5
SEGUNDOS_QR = 90
MAX_LEITURAS_TICKET = 60
MAX_FOTO_BYTES = 700_000
MAX_QUIOSQUES = 10

router = APIRouter(tags=["quiosque"])


def _erro(status: int, codigo: str) -> HTTPException:
    return HTTPException(status_code=status, detail=codigo)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def _escrita_local() -> None:
    if os.getenv("SYNC_MIRROR_READ_ONLY", "").strip().upper() == "YES":
        raise _erro(403, "modo_somente_consulta")


# --------------------------------------------------------------------------- motor facial (substituível nos testes)

def _motor():
    from face_engine import FaceError, MODEL_VERSION, embedding, similarity
    return {"embedding": embedding, "similarity": similarity, "modelo": MODEL_VERSION, "FaceError": FaceError}


MOTOR = _motor  # callable que devolve o dict acima; os testes trocam por um simulado


def _limiar() -> float:
    try:
        v = float(os.getenv("FREQUENCY_FACE_THRESHOLD", "0.45"))
    except ValueError:
        return 0.45
    return v if 0.35 <= v <= 0.80 else 0.45


def identificar_rosto(conn, academia_id: int, foto_base64: str) -> tuple[int | None, float | None]:
    """Devolve (aluno_id, confiança) do melhor candidato se passar nos limiares; senão (None, melhor_confiança)."""
    try:
        conteudo = base64.b64decode(foto_base64, validate=True)
    except (binascii.Error, ValueError):
        raise _erro(400, "foto_invalida")
    if len(conteudo) > MAX_FOTO_BYTES:
        raise _erro(413, "foto_muito_grande")
    motor = MOTOR()
    try:
        sonda = motor["embedding"](conteudo)
    except motor["FaceError"] as e:
        raise _erro(503 if str(e) in {"modelo_facial_nao_instalado", "modelo_facial_invalido", "motor_facial_nao_instalado"} else 422, str(e))
    perfis = conn.execute(
        "SELECT aluno_id, template FROM public.biometrias_faciais WHERE academia_id = %s AND modelo = %s",
        (academia_id, motor["modelo"])).fetchall()
    cand = sorted(((motor["similarity"](bytes(p["template"]), sonda), p["aluno_id"]) for p in perfis), reverse=True)
    if not cand:
        return None, None
    melhor = cand[0][0]
    segunda = cand[1][0] if len(cand) > 1 else 0.0
    if melhor >= _limiar() and melhor - segunda >= 0.04:
        return cand[0][1], melhor
    return None, melhor


# --------------------------------------------------------------------------- aparelho (quiosque) e ticket

def novo_token_quiosque() -> str:
    return "fq_" + secrets.token_urlsafe(32)


def quiosque_do_token(conn, token: str | None) -> dict:
    if not token:
        raise _erro(401, "quiosque_invalido")
    q = conn.execute(
        "SELECT q.id, q.academia_id, q.nome FROM public.quiosques q JOIN public.academias a ON a.id = q.academia_id "
        "WHERE q.token_hash = %s AND q.ativo AND a.ativa", (_hash(token),)).fetchone()
    if q is None:
        raise _erro(401, "quiosque_invalido")
    if not aluno_auth.recurso_ligado(conn, q["academia_id"], RECURSO) or not aluno_auth.ASSINATURA_OK(conn, q["academia_id"]):
        raise _erro(403, "quiosque_indisponivel")
    conn.execute("UPDATE public.quiosques SET ultimo_uso = CURRENT_TIMESTAMP WHERE id = %s", (q["id"],))
    return q


def elegibilidade(conn, quiosque: dict, aluno_id: int) -> tuple[dict | None, str | None]:
    """(aluno, None) se pode usar o quiosque; (None, motivo) caso contrário. Sempre dentro da academia do quiosque."""
    a = conn.execute(
        "SELECT id, nome, academia_id, status FROM public.alunos WHERE id = %s AND academia_id = %s",
        (aluno_id, quiosque["academia_id"])).fetchone()
    if a is None:
        return None, "aluno_nao_encontrado"
    if a["status"] != "ativo":
        return None, "aluno_inativo"
    return a, None


def emitir_ticket(conn, quiosque: dict, aluno: dict, metodo: str, agora: datetime | None = None) -> dict:
    agora = agora or _agora()
    token = "fqt_" + secrets.token_urlsafe(32)
    expira = agora + timedelta(minutes=MINUTOS_TICKET)
    conn.execute(
        "INSERT INTO public.quiosque_tickets (quiosque_id, aluno_id, token_hash, metodo, criado_em, expira_em) VALUES (%s,%s,%s,%s,%s,%s)",
        (quiosque["id"], aluno["id"], _hash(token), metodo, agora, expira))
    return {"ticket": token, "expira_em": expira.isoformat(), "nome": aluno["nome"].split()[0] if aluno["nome"] else ""}


def aluno_do_ticket(conn, quiosque: dict, ticket: str | None, agora: datetime | None = None, contar: bool = True) -> dict:
    agora = agora or _agora()
    if not ticket:
        raise _erro(401, "ticket_invalido")
    t = conn.execute(
        "SELECT t.id, t.aluno_id, t.leituras FROM public.quiosque_tickets t WHERE t.token_hash = %s AND t.quiosque_id = %s "
        "AND t.encerrado_em IS NULL AND t.expira_em > %s FOR UPDATE", (_hash(ticket), quiosque["id"], agora)).fetchone()
    if t is None:
        raise _erro(401, "ticket_invalido")
    if t["leituras"] >= MAX_LEITURAS_TICKET:
        raise _erro(429, "ticket_esgotado")
    a, motivo = elegibilidade(conn, quiosque, t["aluno_id"])
    if a is None:
        raise _erro(401, "ticket_invalido")
    if contar:
        conn.execute("UPDATE public.quiosque_tickets SET leituras = leituras + 1 WHERE id = %s", (t["id"],))
    return {**a, "ticket_id": t["id"]}


def _resposta_identificado(conn, quiosque: dict, aluno_id: int | None, metodo: str, confianca: float | None = None) -> dict:
    if aluno_id is None:
        return {"identificado": False, "liberado": False, "motivo": "rosto_nao_identificado", "ticket": None}
    aluno, motivo = elegibilidade(conn, quiosque, aluno_id)
    if aluno is None:
        return {"identificado": True, "liberado": False, "motivo": motivo, "ticket": None}
    emitido = emitir_ticket(conn, quiosque, aluno, metodo)
    return {"identificado": True, "liberado": True, "motivo": None, **emitido}


# --------------------------------------------------------------------------- treino do dia (somente leitura)

def treino_do_dia(conn, aluno: dict, dia: int | None) -> dict:
    if dia is None:
        dia = int(conn.execute("SELECT EXTRACT(DOW FROM CURRENT_DATE)::int AS d").fetchone()["d"])
    if not 0 <= dia <= 6:
        raise _erro(422, "dia_invalido")
    todos = aluno_treinos.listar_treinos(conn, {"id": aluno["id"], "academia_id": aluno["academia_id"]})
    hoje = [t for t in todos if dia in (t.get("dias_semana") or [])]
    refs = sorted({i["ref"] for t in hoje for b in t["blocos"] for i in b["itens"] if i.get("ref")})
    cargas = {}
    if refs:
        for l in conn.execute(
            "SELECT DISTINCT ON (exercicio_ref) exercicio_ref, carga, reps, registrada_em FROM public.aluno_series_registradas "
            "WHERE aluno_id = %s AND exercicio_ref = ANY(%s) AND concluida AND carga > 0 "
            "ORDER BY exercicio_ref, registrada_em DESC", (aluno["id"], refs)).fetchall():
            cargas[l["exercicio_ref"]] = {"carga": float(l["carga"]), "reps": l["reps"], "data": l["registrada_em"].date().isoformat()}
    return {
        "dia": dia,
        "treinos": hoje,
        "outros": [{"id": t["id"], "nome": t["nome"]} for t in todos if t not in hoje],
        "ultimas_cargas": cargas,
    }


# --------------------------------------------------------------------------- QR do aluno

def criar_qr(conn, aluno: dict, agora: datetime | None = None) -> dict:
    agora = agora or _agora()
    conn.execute("UPDATE public.aluno_qr_quiosque SET usado_em = %s WHERE aluno_id = %s AND usado_em IS NULL", (agora, aluno["id"]))
    token = "fqr_" + secrets.token_urlsafe(24)
    expira = agora + timedelta(seconds=SEGUNDOS_QR)
    conn.execute("INSERT INTO public.aluno_qr_quiosque (aluno_id, token_hash, criado_em, expira_em) VALUES (%s,%s,%s,%s)",
                 (aluno["id"], _hash(token), agora, expira))
    return {"codigo": token, "expira_em": expira.isoformat()}


def consumir_qr(conn, quiosque: dict, codigo: str, agora: datetime | None = None) -> int | None:
    agora = agora or _agora()
    l = conn.execute(
        "UPDATE public.aluno_qr_quiosque q SET usado_em = %s FROM public.alunos a "
        "WHERE q.token_hash = %s AND q.usado_em IS NULL AND q.expira_em > %s AND a.id = q.aluno_id AND a.academia_id = %s "
        "RETURNING q.aluno_id", (agora, _hash(codigo or ""), agora, quiosque["academia_id"])).fetchone()
    return l["aluno_id"] if l else None


# --------------------------------------------------------------------------- painel (dono)

def criar_quiosque(conn, academia_id: int, nome: str) -> dict:
    n = conn.execute("SELECT count(*) AS n FROM public.quiosques WHERE academia_id = %s AND ativo", (academia_id,)).fetchone()["n"]
    if n >= MAX_QUIOSQUES:
        raise _erro(409, "limite_de_quiosques")
    token = novo_token_quiosque()
    l = conn.execute("INSERT INTO public.quiosques (academia_id, nome, token_hash) VALUES (%s,%s,%s) RETURNING id, nome, criado_em",
                     (academia_id, nome.strip(), _hash(token))).fetchone()
    conn.commit()
    return {"id": l["id"], "nome": l["nome"], "token": token, "criado_em": l["criado_em"].isoformat(),
            "aviso": "Guarde este código agora: ele não será mostrado de novo."}


def listar_quiosques(conn, academia_id: int) -> list[dict]:
    return [{"id": l["id"], "nome": l["nome"], "ativo": l["ativo"], "criado_em": l["criado_em"].isoformat(),
             "ultimo_uso": l["ultimo_uso"].isoformat() if l["ultimo_uso"] else None}
            for l in conn.execute("SELECT id, nome, ativo, criado_em, ultimo_uso FROM public.quiosques WHERE academia_id = %s ORDER BY id", (academia_id,)).fetchall()]


def revogar_quiosque(conn, academia_id: int, quiosque_id: int) -> None:
    l = conn.execute("UPDATE public.quiosques SET ativo = FALSE, revogado_em = CURRENT_TIMESTAMP WHERE id = %s AND academia_id = %s AND ativo RETURNING id",
                     (quiosque_id, academia_id)).fetchone()
    if l is None:
        conn.rollback()
        raise _erro(404, "quiosque_nao_encontrado")
    conn.execute("UPDATE public.quiosque_tickets SET encerrado_em = CURRENT_TIMESTAMP WHERE quiosque_id = %s AND encerrado_em IS NULL", (quiosque_id,))
    conn.commit()


# --------------------------------------------------------------------------- rotas

class FotoEntrada(BaseModel):
    foto_base64: str = Field(min_length=4, max_length=1_000_000)


class QrEntrada(BaseModel):
    codigo: str = Field(min_length=8, max_length=80)


class EmailPedido(BaseModel):
    email: str = Field(max_length=254)


class EmailCodigo(BaseModel):
    email: str = Field(max_length=254)
    codigo: str = Field(min_length=4, max_length=12)


class QuiosqueEntrada(BaseModel):
    nome: str = Field(min_length=2, max_length=80)


def _quiosque(x_quiosque_token: str | None = Header(default=None), conn=Depends(aluno_auth.conexao)) -> dict:
    return quiosque_do_token(conn, x_quiosque_token)


@router.post("/quiosque/identificar")
def rota_identificar(dados: FotoEntrada, request: Request, q: dict = Depends(_quiosque), conn=Depends(aluno_auth.conexao)):
    _escrita_local()
    chave = f"quiosque:{q['id']}"
    aluno_auth._limitar(chave, request)
    aluno_id, conf = identificar_rosto(conn, q["academia_id"], dados.foto_base64)
    if aluno_id is None:
        aluno_auth.limitador().record_failure(chave, aluno_auth._ip(request))
    r = _resposta_identificado(conn, q, aluno_id, "facial", conf)
    conn.commit()
    return r


@router.post("/quiosque/qr")
def rota_qr(dados: QrEntrada, request: Request, q: dict = Depends(_quiosque), conn=Depends(aluno_auth.conexao)):
    _escrita_local()
    chave = f"quiosque-qr:{q['id']}"
    aluno_auth._limitar(chave, request)
    aluno_id = consumir_qr(conn, q, dados.codigo)
    if aluno_id is None:
        conn.commit()
        aluno_auth.limitador().record_failure(chave, aluno_auth._ip(request))
        raise _erro(400, "qr_invalido")
    r = _resposta_identificado(conn, q, aluno_id, "qr")
    conn.commit()
    return r


@router.post("/quiosque/email/pedir")
def rota_email_pedir(dados: EmailPedido, request: Request, q: dict = Depends(_quiosque), conn=Depends(aluno_auth.conexao)):
    _escrita_local()
    email = aluno_auth.normalizar_email(dados.email)
    aluno_auth._limitar("quiosque-email:" + email, request)
    aluno_auth.limitador().record_failure("quiosque-email:" + email, aluno_auth._ip(request))
    aluno_auth.iniciar_acesso(conn, email, aluno_auth._ip(request), enviar=aluno_auth.ENVIAR_EMAIL, assinatura_ok=aluno_auth.ASSINATURA_OK)
    conn.commit()
    return {"enviado": True}  # nunca revela se o e-mail existe


@router.post("/quiosque/email/confirmar")
def rota_email_confirmar(dados: EmailCodigo, request: Request, q: dict = Depends(_quiosque), conn=Depends(aluno_auth.conexao)):
    _escrita_local()
    email = aluno_auth.normalizar_email(dados.email)
    chave = "quiosque-codigo:" + email
    aluno_auth._limitar(chave, request)
    # só vale para aluno desta academia
    elegiveis = [a for a in aluno_auth.alunos_elegiveis(conn, email, aluno_auth.ASSINATURA_OK) if a["academia_id"] == q["academia_id"]]
    ok = bool(elegiveis) and aluno_auth.verificar_codigo(conn, email, dados.codigo.strip(), assinatura_ok=aluno_auth.ASSINATURA_OK) is not None
    conn.commit()
    if not ok:
        aluno_auth.limitador().record_failure(chave, aluno_auth._ip(request))
        raise _erro(400, "codigo_invalido")
    r = _resposta_identificado(conn, q, elegiveis[0]["id"], "email")
    conn.commit()
    return r


@router.get("/quiosque/treino-do-dia")
def rota_treino(dia: int | None = None, x_quiosque_ticket: str | None = Header(default=None),
                q: dict = Depends(_quiosque), conn=Depends(aluno_auth.conexao)):
    aluno = aluno_do_ticket(conn, q, x_quiosque_ticket)
    r = treino_do_dia(conn, aluno, dia)
    conn.commit()
    return {"aluno": {"nome": aluno["nome"].split()[0] if aluno["nome"] else ""}, **r}


@router.post("/quiosque/encerrar", status_code=204)
def rota_encerrar(x_quiosque_ticket: str | None = Header(default=None), q: dict = Depends(_quiosque), conn=Depends(aluno_auth.conexao)):
    if x_quiosque_ticket:
        conn.execute("UPDATE public.quiosque_tickets SET encerrado_em = CURRENT_TIMESTAMP WHERE token_hash = %s AND quiosque_id = %s",
                     (_hash(x_quiosque_ticket), q["id"]))
    conn.commit()


@router.post("/aluno/quiosque/qr")
def rota_gerar_qr(aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    _escrita_local()
    if not aluno_auth.recurso_ligado(conn, aluno["academia_id"], RECURSO):
        raise _erro(403, "quiosque_indisponivel")
    r = criar_qr(conn, aluno)
    conn.commit()
    return r


@router.get("/academia/quiosques")
def rota_listar(usuario: dict = Depends(somente_dono), conn=Depends(aluno_auth.conexao)):
    return {"quiosques": listar_quiosques(conn, usuario["academia_id"]),
            "recurso_ligado": aluno_auth.recurso_ligado(conn, usuario["academia_id"], RECURSO)}


@router.post("/academia/quiosques", status_code=201)
def rota_criar(dados: QuiosqueEntrada, usuario: dict = Depends(somente_dono), conn=Depends(aluno_auth.conexao)):
    _escrita_local()
    if not aluno_auth.recurso_ligado(conn, usuario["academia_id"], RECURSO):
        raise _erro(403, "recurso_desligado")
    return criar_quiosque(conn, usuario["academia_id"], dados.nome)


@router.delete("/academia/quiosques/{quiosque_id}", status_code=204)
def rota_revogar(quiosque_id: int, usuario: dict = Depends(somente_dono), conn=Depends(aluno_auth.conexao)):
    _escrita_local()
    revogar_quiosque(conn, usuario["academia_id"], quiosque_id)
