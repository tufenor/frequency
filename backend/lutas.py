"""Módulo Lutas (e aulas coletivas): modalidades, turmas, professores, faixas, chamada com validação e presença do aluno.

Tudo atrás da flag `lutas` (modalidades de categoria 'luta') ou `agenda_aulas` (categoria 'aula') em academia_recursos.
Só presença `validada` pelo professor conta para frequência e faixa. A coordenada do aluno é lida uma vez
e só "dentro/fora do raio" é guardado.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import aluno_auth
import lutas_regras as regras
import seguranca

router = APIRouter(tags=["lutas"])

RECURSO_LUTA = "lutas"
RECURSO_AULA = "agenda_aulas"
FUSO_PADRAO = "America/Sao_Paulo"


def AGORA() -> datetime:  # substituível nos testes
    return datetime.now(timezone.utc)


def _erro(status: int, codigo: str) -> HTTPException:
    return HTTPException(status_code=status, detail=codigo)


# --------------------------------------------------------------------------- acesso

def _recursos(conn, academia_id: int) -> set[str]:
    return {r["recurso"] for r in conn.execute(
        "SELECT recurso FROM public.academia_recursos WHERE academia_id = %s AND ligado AND recurso IN ('lutas','agenda_aulas')",
        (academia_id,)).fetchall()}


def _categorias_ligadas(conn, academia_id: int) -> list[str]:
    r = _recursos(conn, academia_id)
    return [c for c, f in (("luta", RECURSO_LUTA), ("aula", RECURSO_AULA)) if f in r]


def gestao_ou_professor(usuario=Depends(seguranca.usuario_atual)):
    if usuario["papel"] not in {"dono", "recepcao", "professor"} or not usuario["academia_id"]:
        raise _erro(403, "sem_permissao")
    if usuario.get("bloqueada_frequency"):
        raise _erro(402, "assinatura_frequency_bloqueada")
    return usuario


def gestao(usuario=Depends(seguranca.usuario_atual)):
    if usuario["papel"] not in {"dono", "recepcao"} or not usuario["academia_id"]:
        raise _erro(403, "sem_permissao")
    if usuario.get("bloqueada_frequency"):
        raise _erro(402, "assinatura_frequency_bloqueada")
    return usuario


def _exigir_recurso(conn, usuario: dict) -> list[str]:
    cats = _categorias_ligadas(conn, usuario["academia_id"])
    if not cats:
        raise _erro(403, "lutas_desligado")
    return cats


def _professor_do_usuario(conn, usuario: dict) -> dict | None:
    if usuario["papel"] != "professor":
        return None
    p = conn.execute("SELECT id FROM public.professores WHERE usuario_id = %s AND academia_id = %s AND ativo",
                     (usuario["id"], usuario["academia_id"])).fetchone()
    if p is None:
        raise _erro(403, "professor_nao_cadastrado")
    return p


def _turma_visivel(conn, usuario: dict, turma_id: int) -> dict:
    """Turma da academia; professor só enxerga as suas (404 para não revelar as outras)."""
    t = conn.execute(
        "SELECT t.*, m.categoria, m.nome AS modalidade FROM public.turmas t JOIN public.modalidades m ON m.id = t.modalidade_id "
        "WHERE t.id = %s AND t.academia_id = %s", (turma_id, usuario["academia_id"])).fetchone()
    if t is None:
        raise _erro(404, "turma_nao_encontrada")
    prof = _professor_do_usuario(conn, usuario)
    if prof is not None and t["professor_id"] != prof["id"]:
        raise _erro(404, "turma_nao_encontrada")
    if t["categoria"] not in _categorias_ligadas(conn, usuario["academia_id"]):
        raise _erro(403, "lutas_desligado")
    return t


def _fuso(conn, academia_id: int) -> str:
    l = conn.execute("SELECT fuso FROM public.academia_local WHERE academia_id = %s", (academia_id,)).fetchone()
    return l["fuso"] if l else FUSO_PADRAO


# --------------------------------------------------------------------------- local da academia

class LocalEntrada(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    raio_m: int = Field(default=150, ge=20, le=2000)
    fuso: str = FUSO_PADRAO


@router.get("/lutas/local")
def ver_local(usuario=Depends(gestao_ou_professor), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    l = conn.execute("SELECT latitude, longitude, raio_m, fuso FROM public.academia_local WHERE academia_id = %s",
                     (usuario["academia_id"],)).fetchone()
    return l or {"latitude": None, "longitude": None, "raio_m": 150, "fuso": FUSO_PADRAO}


@router.put("/lutas/local")
def definir_local(dados: LocalEntrada, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    if not regras.coordenada_valida(dados.latitude, dados.longitude):
        raise _erro(422, "coordenada_invalida")
    try:
        ZoneInfo(dados.fuso)
    except Exception:
        raise _erro(422, "fuso_invalido")
    conn.execute(
        "INSERT INTO public.academia_local (academia_id, latitude, longitude, raio_m, fuso) VALUES (%s,%s,%s,%s,%s) "
        "ON CONFLICT (academia_id) DO UPDATE SET latitude=EXCLUDED.latitude, longitude=EXCLUDED.longitude, "
        "raio_m=EXCLUDED.raio_m, fuso=EXCLUDED.fuso, atualizado_em=CURRENT_TIMESTAMP",
        (usuario["academia_id"], dados.latitude, dados.longitude, dados.raio_m, dados.fuso))
    conn.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- modalidades e planos

class ModalidadeEntrada(BaseModel):
    nome: str = Field(min_length=2, max_length=60)
    categoria: str = Field(default="luta", pattern="^(luta|aula)$")


class ModalidadeAjuste(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=60)
    ativa: bool | None = None


@router.get("/lutas/modalidades")
def listar_modalidades(usuario=Depends(gestao_ou_professor), conn=Depends(aluno_auth.conexao)):
    cats = _exigir_recurso(conn, usuario)
    linhas = conn.execute("SELECT id, nome, categoria, ativa FROM public.modalidades WHERE academia_id = %s AND categoria = ANY(%s) ORDER BY nome",
                          (usuario["academia_id"], cats)).fetchall()
    return {"modalidades": [dict(l) for l in linhas]}


@router.post("/lutas/modalidades", status_code=201)
def criar_modalidade(dados: ModalidadeEntrada, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    cats = _exigir_recurso(conn, usuario)
    if dados.categoria not in cats:
        raise _erro(403, "lutas_desligado")
    try:
        l = conn.execute("INSERT INTO public.modalidades (academia_id, nome, categoria) VALUES (%s,%s,%s) RETURNING id, nome, categoria, ativa",
                         (usuario["academia_id"], dados.nome.strip(), dados.categoria)).fetchone()
    except Exception as e:
        conn.rollback()
        if "uq_modalidades_nome" in str(e):
            raise _erro(409, "modalidade_ja_existe")
        raise
    conn.commit()
    return dict(l)


@router.patch("/lutas/modalidades/{mid}")
def ajustar_modalidade(mid: int, dados: ModalidadeAjuste, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    l = conn.execute(
        "UPDATE public.modalidades SET nome = COALESCE(%s, nome), ativa = COALESCE(%s, ativa) WHERE id = %s AND academia_id = %s "
        "RETURNING id, nome, categoria, ativa", (dados.nome and dados.nome.strip(), dados.ativa, mid, usuario["academia_id"])).fetchone()
    if l is None:
        raise _erro(404, "modalidade_nao_encontrada")
    conn.commit()
    return dict(l)


class PlanoModalidades(BaseModel):
    modalidade_ids: list[int] = Field(max_length=30)


@router.get("/lutas/planos")
def listar_planos(usuario=Depends(gestao), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    ac = usuario["academia_id"]
    planos = conn.execute("SELECT id, nome FROM public.planos WHERE academia_id = %s ORDER BY nome", (ac,)).fetchall()
    ligas = conn.execute("SELECT pm.plano_id, pm.modalidade_id FROM public.plano_modalidades pm JOIN public.planos p ON p.id = pm.plano_id "
                         "WHERE p.academia_id = %s", (ac,)).fetchall()
    por: dict[int, list[int]] = {}
    for l in ligas:
        por.setdefault(l["plano_id"], []).append(l["modalidade_id"])
    return {"planos": [{"id": p["id"], "nome": p["nome"], "modalidade_ids": sorted(por.get(p["id"], []))} for p in planos]}


@router.put("/lutas/planos/{plano_id}/modalidades")
def definir_modalidades_do_plano(plano_id: int, dados: PlanoModalidades, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    ac = usuario["academia_id"]
    if conn.execute("SELECT 1 FROM public.planos WHERE id = %s AND academia_id = %s", (plano_id, ac)).fetchone() is None:
        raise _erro(404, "plano_nao_encontrado")
    ids = sorted(set(dados.modalidade_ids))
    if ids:
        n = conn.execute("SELECT count(*) AS n FROM public.modalidades WHERE academia_id = %s AND id = ANY(%s)", (ac, ids)).fetchone()["n"]
        if n != len(ids):
            raise _erro(422, "modalidade_invalida")
    conn.execute("DELETE FROM public.plano_modalidades WHERE plano_id = %s", (plano_id,))
    for m in ids:
        conn.execute("INSERT INTO public.plano_modalidades (plano_id, modalidade_id) VALUES (%s,%s)", (plano_id, m))
    conn.commit()
    return {"plano_id": plano_id, "modalidade_ids": ids}


# --------------------------------------------------------------------------- professores

class ProfessorEntrada(BaseModel):
    nome: str = Field(min_length=2, max_length=80)
    email: str | None = Field(default=None, max_length=120)
    senha: str | None = Field(default=None, min_length=10, max_length=128)


@router.get("/lutas/professores")
def listar_professores(usuario=Depends(gestao), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    ls = conn.execute("SELECT p.id, p.nome, p.ativo, u.email FROM public.professores p LEFT JOIN public.usuarios u ON u.id = p.usuario_id "
                      "WHERE p.academia_id = %s ORDER BY p.nome", (usuario["academia_id"],)).fetchall()
    return {"professores": [dict(l) for l in ls]}


@router.post("/lutas/professores", status_code=201)
def criar_professor(dados: ProfessorEntrada, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    if bool(dados.email) != bool(dados.senha):
        raise _erro(422, "email_e_senha_juntos")
    uid = None
    try:
        if dados.email:
            email = dados.email.strip().lower()
            if "@" not in email:
                raise _erro(422, "email_invalido")
            uid = conn.execute(
                "INSERT INTO public.usuarios (academia_id, nome, email, senha_hash, papel) VALUES (%s,%s,%s,%s,'professor') RETURNING id",
                (usuario["academia_id"], dados.nome.strip(), email, seguranca.gerar_hash(dados.senha))).fetchone()["id"]
        p = conn.execute("INSERT INTO public.professores (academia_id, nome, usuario_id) VALUES (%s,%s,%s) RETURNING id, nome, ativo",
                         (usuario["academia_id"], dados.nome.strip(), uid)).fetchone()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        if "usuarios_email_key" in str(e):
            raise _erro(409, "email_em_uso")
        raise
    conn.commit()
    return {**dict(p), "tem_login": uid is not None}


@router.delete("/lutas/professores/{pid}", status_code=204)
def desativar_professor(pid: int, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    p = conn.execute("UPDATE public.professores SET ativo = FALSE WHERE id = %s AND academia_id = %s RETURNING usuario_id",
                     (pid, usuario["academia_id"])).fetchone()
    if p is None:
        raise _erro(404, "professor_nao_encontrado")
    if p["usuario_id"]:
        conn.execute("UPDATE public.usuarios SET ativo = FALSE WHERE id = %s AND papel = 'professor' AND academia_id = %s",
                     (p["usuario_id"], usuario["academia_id"]))
    conn.commit()


# --------------------------------------------------------------------------- turmas e horários

class TurmaEntrada(BaseModel):
    modalidade_id: int
    professor_id: int | None = None
    nome: str = Field(min_length=2, max_length=80)
    capacidade: int = Field(default=30, ge=1, le=500)
    exige_reserva: bool = False


class TurmaAjuste(BaseModel):
    professor_id: int | None = None
    nome: str | None = Field(default=None, min_length=2, max_length=80)
    capacidade: int | None = Field(default=None, ge=1, le=500)
    exige_reserva: bool | None = None
    ativa: bool | None = None


class HorarioEntrada(BaseModel):
    dia_semana: int = Field(ge=0, le=6)
    inicio: str = Field(pattern=r"^\d{2}:\d{2}$")
    fim: str = Field(pattern=r"^\d{2}:\d{2}$")


def _validar_prof(conn, academia_id: int, professor_id: int | None) -> None:
    if professor_id is not None and conn.execute(
            "SELECT 1 FROM public.professores WHERE id = %s AND academia_id = %s AND ativo", (professor_id, academia_id)).fetchone() is None:
        raise _erro(422, "professor_invalido")


def _turma_json(conn, t: dict) -> dict:
    hs = conn.execute("SELECT id, dia_semana, to_char(inicio,'HH24:MI') AS inicio, to_char(fim,'HH24:MI') AS fim FROM public.turma_horarios "
                      "WHERE turma_id = %s ORDER BY dia_semana, inicio", (t["id"],)).fetchall()
    ocup = conn.execute("SELECT count(*) FILTER (WHERE estado='ativa') AS ativas, count(*) FILTER (WHERE estado='espera') AS espera "
                        "FROM public.reservas_turma WHERE turma_id = %s", (t["id"],)).fetchone()
    return {"id": t["id"], "nome": t["nome"], "modalidade_id": t["modalidade_id"], "professor_id": t["professor_id"],
            "capacidade": t["capacidade"], "exige_reserva": t["exige_reserva"], "ativa": t["ativa"],
            "horarios": [dict(h) for h in hs], "reservas": ocup["ativas"], "espera": ocup["espera"]}


@router.get("/lutas/turmas")
def listar_turmas(usuario=Depends(gestao_ou_professor), conn=Depends(aluno_auth.conexao)):
    cats = _exigir_recurso(conn, usuario)
    prof = _professor_do_usuario(conn, usuario)
    sql = ("SELECT t.* FROM public.turmas t JOIN public.modalidades m ON m.id = t.modalidade_id "
           "WHERE t.academia_id = %s AND m.categoria = ANY(%s)")
    args: list = [usuario["academia_id"], cats]
    if prof is not None:
        sql += " AND t.professor_id = %s"
        args.append(prof["id"])
    ts = conn.execute(sql + " ORDER BY t.nome", args).fetchall()
    return {"turmas": [_turma_json(conn, t) for t in ts]}


@router.post("/lutas/turmas", status_code=201)
def criar_turma(dados: TurmaEntrada, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    cats = _exigir_recurso(conn, usuario)
    ac = usuario["academia_id"]
    m = conn.execute("SELECT categoria FROM public.modalidades WHERE id = %s AND academia_id = %s AND ativa", (dados.modalidade_id, ac)).fetchone()
    if m is None or m["categoria"] not in cats:
        raise _erro(422, "modalidade_invalida")
    _validar_prof(conn, ac, dados.professor_id)
    t = conn.execute("INSERT INTO public.turmas (academia_id, modalidade_id, professor_id, nome, capacidade, exige_reserva) "
                     "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                     (ac, dados.modalidade_id, dados.professor_id, dados.nome.strip(), dados.capacidade, dados.exige_reserva)).fetchone()
    conn.commit()
    return _turma_json(conn, t)


@router.patch("/lutas/turmas/{tid}")
def ajustar_turma(tid: int, dados: TurmaAjuste, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    ac = usuario["academia_id"]
    atual = conn.execute("SELECT * FROM public.turmas WHERE id = %s AND academia_id = %s", (tid, ac)).fetchone()
    if atual is None:
        raise _erro(404, "turma_nao_encontrada")
    campos = dados.model_dump(exclude_unset=True)
    if "professor_id" in campos:
        _validar_prof(conn, ac, campos["professor_id"])
    novo = {**atual, **{k: (v.strip() if isinstance(v, str) else v) for k, v in campos.items() if v is not None or k == "professor_id"}}
    t = conn.execute("UPDATE public.turmas SET professor_id=%s, nome=%s, capacidade=%s, exige_reserva=%s, ativa=%s WHERE id=%s RETURNING *",
                     (novo["professor_id"], novo["nome"], novo["capacidade"], novo["exige_reserva"], novo["ativa"], tid)).fetchone()
    _promover_espera(conn, tid)
    conn.commit()
    return _turma_json(conn, t)


@router.post("/lutas/turmas/{tid}/horarios", status_code=201)
def adicionar_horario(tid: int, dados: HorarioEntrada, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    if conn.execute("SELECT 1 FROM public.turmas WHERE id = %s AND academia_id = %s", (tid, usuario["academia_id"])).fetchone() is None:
        raise _erro(404, "turma_nao_encontrada")
    if dados.fim <= dados.inicio or not _hora_ok(dados.inicio) or not _hora_ok(dados.fim):
        raise _erro(422, "horario_invalido")
    try:
        h = conn.execute("INSERT INTO public.turma_horarios (turma_id, dia_semana, inicio, fim) VALUES (%s,%s,%s,%s) RETURNING id",
                         (tid, dados.dia_semana, dados.inicio, dados.fim)).fetchone()
    except Exception:
        conn.rollback()
        raise _erro(409, "horario_ja_existe")
    conn.commit()
    return {"id": h["id"]}


def _hora_ok(h: str) -> bool:
    hh, mm = int(h[:2]), int(h[3:])
    return 0 <= hh <= 23 and 0 <= mm <= 59


@router.delete("/lutas/turmas/{tid}/horarios/{hid}", status_code=204)
def remover_horario(tid: int, hid: int, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    r = conn.execute("DELETE FROM public.turma_horarios h USING public.turmas t WHERE h.id = %s AND h.turma_id = %s AND t.id = h.turma_id AND t.academia_id = %s RETURNING h.id",
                     (hid, tid, usuario["academia_id"])).fetchone()
    if r is None:
        raise _erro(404, "horario_nao_encontrado")
    conn.commit()


@router.get("/lutas/turmas/{tid}/alunos")
def alunos_da_turma(tid: int, usuario=Depends(gestao_ou_professor), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    _turma_visivel(conn, usuario, tid)
    ls = conn.execute("SELECT a.id, a.nome, r.estado FROM public.reservas_turma r JOIN public.alunos a ON a.id = r.aluno_id "
                      "WHERE r.turma_id = %s ORDER BY r.estado, r.criada_em", (tid,)).fetchall()
    return {"alunos": [dict(l) for l in ls]}


# --------------------------------------------------------------------------- reservas (vaga e fila de espera)

def _ocupacao(conn, turma_id: int) -> int:
    return conn.execute("SELECT count(*) AS n FROM public.reservas_turma WHERE turma_id = %s AND estado = 'ativa'", (turma_id,)).fetchone()["n"]


def _promover_espera(conn, turma_id: int) -> list[int]:
    """Promove, na ordem de chegada, quem está na espera enquanto houver vaga. Devolve os alunos promovidos."""
    t = conn.execute("SELECT capacidade, ativa FROM public.turmas WHERE id = %s", (turma_id,)).fetchone()
    promovidos: list[int] = []
    if t is None or not t["ativa"]:
        return promovidos
    while regras.vagas(t["capacidade"], _ocupacao(conn, turma_id)) > 0:
        p = conn.execute("UPDATE public.reservas_turma SET estado = 'ativa' WHERE id = (SELECT id FROM public.reservas_turma "
                         "WHERE turma_id = %s AND estado = 'espera' ORDER BY criada_em, id LIMIT 1) RETURNING aluno_id", (turma_id,)).fetchone()
        if p is None:
            break
        promovidos.append(p["aluno_id"])
    return promovidos


def _modalidades_do_aluno(conn, aluno: dict, categorias: list[str]) -> set[int]:
    if not aluno["plano_id"]:
        return set()
    return {r["modalidade_id"] for r in conn.execute(
        "SELECT pm.modalidade_id FROM public.plano_modalidades pm JOIN public.modalidades m ON m.id = pm.modalidade_id "
        "WHERE pm.plano_id = %s AND m.ativa AND m.academia_id = %s AND m.categoria = ANY(%s)",
        (aluno["plano_id"], aluno["academia_id"], categorias)).fetchall()}


class ReservaEntrada(BaseModel):
    entrar_na_espera: bool = False


def _turma_do_aluno(conn, aluno: dict, turma_id: int) -> dict:
    cats = _categorias_ligadas(conn, aluno["academia_id"])
    if not cats:
        raise _erro(403, "lutas_desligado")
    t = conn.execute(
        "SELECT t.*, m.categoria FROM public.turmas t JOIN public.modalidades m ON m.id = t.modalidade_id "
        "WHERE t.id = %s AND t.academia_id = %s AND t.ativa AND m.ativa", (turma_id, aluno["academia_id"])).fetchone()
    if t is None or t["categoria"] not in cats:
        raise _erro(404, "turma_nao_encontrada")
    if not regras.elegivel(_modalidades_do_aluno(conn, aluno, cats), t["modalidade_id"]):
        raise _erro(403, "plano_sem_modalidade")
    return t


@router.post("/aluno/lutas/turmas/{turma_id}/reservar")
def reservar(turma_id: int, dados: ReservaEntrada | None = None, request: Request = None,
             aluno=Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    aluno_auth._limitar(f"lutas-reserva:{aluno['id']}", request)
    t = _turma_do_aluno(conn, aluno, turma_id)
    ja = conn.execute("SELECT estado FROM public.reservas_turma WHERE turma_id = %s AND aluno_id = %s", (turma_id, aluno["id"])).fetchone()
    if ja:
        return {"estado": ja["estado"], "ja_reservada": True}
    cheia = regras.vagas(t["capacidade"], _ocupacao(conn, turma_id)) == 0
    if cheia and not (dados and dados.entrar_na_espera):
        raise _erro(409, "turma_cheia")
    estado = "espera" if cheia else "ativa"
    conn.execute("INSERT INTO public.reservas_turma (turma_id, aluno_id, estado) VALUES (%s,%s,%s)", (turma_id, aluno["id"], estado))
    conn.commit()
    return {"estado": estado, "ja_reservada": False}


@router.delete("/aluno/lutas/turmas/{turma_id}/reservar", status_code=204)
def cancelar_reserva(turma_id: int, aluno=Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    conn.execute("DELETE FROM public.reservas_turma r USING public.turmas t WHERE r.turma_id = %s AND r.aluno_id = %s "
                 "AND t.id = r.turma_id AND t.academia_id = %s", (turma_id, aluno["id"], aluno["academia_id"]))
    _promover_espera(conn, turma_id)
    conn.commit()


# --------------------------------------------------------------------------- aula (ocorrência) e QR

def _codigo_aula(turma_id: int, inicio: datetime) -> str:
    msg = f"aula:{turma_id}:{int(inicio.timestamp())}".encode()
    return "fa_" + hmac.new(seguranca.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()[:20]


def _ocorrencias_do_dia(conn, turma: dict, dia: date) -> list[dict]:
    fuso = _fuso(conn, turma["academia_id"])
    hs = conn.execute("SELECT id, inicio, fim FROM public.turma_horarios WHERE turma_id = %s AND dia_semana = %s ORDER BY inicio",
                      (turma["id"], regras.dia_da_semana(dia))).fetchall()
    out = []
    for h in hs:
        a, b = regras.ocorrencia(dia, h["inicio"], h["fim"], fuso)
        out.append({"horario_id": h["id"], "inicio": a, "fim": b})
    return out


def _obter_aula(conn, turma: dict, oc: dict) -> dict:
    conn.execute(
        "INSERT INTO public.aulas_realizadas (academia_id, turma_id, horario_id, professor_id, inicio, fim) VALUES (%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (turma_id, inicio) DO NOTHING",
        (turma["academia_id"], turma["id"], oc["horario_id"], turma["professor_id"], oc["inicio"], oc["fim"]))
    return conn.execute("SELECT * FROM public.aulas_realizadas WHERE turma_id = %s AND inicio = %s", (turma["id"], oc["inicio"])).fetchone()


class PresencaEntrada(BaseModel):
    turma_id: int
    horario_id: int | None = None
    metodo: str = Field(default="toque", pattern="^(toque|qr)$")
    codigo: str | None = Field(default=None, max_length=60)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


@router.post("/aluno/lutas/presenca")
def confirmar_presenca(dados: PresencaEntrada, request: Request, aluno=Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    chave = f"lutas-presenca:{aluno['id']}"
    aluno_auth._limitar(chave, request)
    try:
        return _confirmar_presenca(dados, aluno, conn)
    except HTTPException:
        conn.rollback()
        aluno_auth.limitador().record_failure(chave, aluno_auth._ip(request))  # tentativas fora da regra esgotam o limite
        raise


def _confirmar_presenca(dados: PresencaEntrada, aluno: dict, conn) -> dict:
    t = _turma_do_aluno(conn, aluno, dados.turma_id)
    agora = AGORA()
    fuso = _fuso(conn, aluno["academia_id"])
    hoje = agora.astimezone(ZoneInfo(fuso)).date()
    # a janela pode cruzar a meia-noite local: testa hoje e ontem/amanhã
    candidatas = [oc for d in (hoje - timedelta(days=1), hoje, hoje + timedelta(days=1)) for oc in _ocorrencias_do_dia(conn, t, d)
                  if regras.na_janela(agora, oc["inicio"]) and (dados.horario_id is None or oc["horario_id"] == dados.horario_id)]
    if not candidatas:
        raise _erro(422, "fora_da_janela")
    oc = min(candidatas, key=lambda o: abs((o["inicio"] - agora).total_seconds()))
    if t["exige_reserva"] and conn.execute("SELECT 1 FROM public.reservas_turma WHERE turma_id=%s AND aluno_id=%s AND estado='ativa'",
                                           (t["id"], aluno["id"])).fetchone() is None:
        raise _erro(403, "sem_reserva")
    if dados.metodo == "qr" and not (dados.codigo and hmac.compare_digest(dados.codigo, _codigo_aula(t["id"], oc["inicio"]))):
        raise _erro(422, "codigo_invalido")
    dentro = None
    if dados.latitude is not None and dados.longitude is not None and regras.coordenada_valida(dados.latitude, dados.longitude):
        loc = conn.execute("SELECT latitude, longitude, raio_m FROM public.academia_local WHERE academia_id = %s AND latitude IS NOT NULL",
                           (aluno["academia_id"],)).fetchone()
        if loc:
            dentro = regras.dentro_do_raio(dados.latitude, dados.longitude, loc["latitude"], loc["longitude"], loc["raio_m"])
    aula = _obter_aula(conn, t, oc)
    atual = conn.execute("SELECT estado FROM public.presencas_aula WHERE aula_id = %s AND aluno_id = %s", (aula["id"], aluno["id"])).fetchone()
    if atual:
        conn.commit()
        return {"estado": atual["estado"], "ja_confirmada": True, "dentro_do_raio": None}
    conn.execute("INSERT INTO public.presencas_aula (aula_id, aluno_id, estado, metodo, dentro_do_raio, confirmada_em) VALUES (%s,%s,'confirmada',%s,%s,%s)",
                 (aula["id"], aluno["id"], dados.metodo, dentro, agora))
    conn.commit()
    return {"estado": regras.transicao(None, "confirmar"), "ja_confirmada": False, "dentro_do_raio": dentro}


# --------------------------------------------------------------------------- app do aluno: grade

def _aulas_validadas(conn, aluno_id: int, modalidade_id: int) -> int:
    return conn.execute(
        "SELECT count(*) AS n FROM public.presencas_aula p JOIN public.aulas_realizadas r ON r.id = p.aula_id "
        "JOIN public.turmas t ON t.id = r.turma_id WHERE p.aluno_id = %s AND t.modalidade_id = %s AND p.estado = 'validada'",
        (aluno_id, modalidade_id)).fetchone()["n"]


@router.get("/aluno/lutas")
def minha_grade(aluno=Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    cats = _categorias_ligadas(conn, aluno["academia_id"])
    mods = _modalidades_do_aluno(conn, aluno, cats) if cats else set()
    if not mods:
        return {"disponivel": False}
    ts = conn.execute("SELECT t.*, m.nome AS modalidade, m.categoria FROM public.turmas t JOIN public.modalidades m ON m.id = t.modalidade_id "
                      "WHERE t.academia_id = %s AND t.ativa AND m.ativa AND t.modalidade_id = ANY(%s) ORDER BY m.nome, t.nome",
                      (aluno["academia_id"], sorted(mods))).fetchall()
    minhas = {r["turma_id"]: r["estado"] for r in conn.execute(
        "SELECT turma_id, estado FROM public.reservas_turma WHERE aluno_id = %s", (aluno["id"],)).fetchall()}
    grade = []
    for t in ts:
        j = _turma_json(conn, t)
        grade.append({"id": t["id"], "nome": t["nome"], "modalidade": t["modalidade"], "modalidade_id": t["modalidade_id"], "categoria": t["categoria"],
                      "horarios": j["horarios"], "vagas": regras.vagas(t["capacidade"], j["reservas"]), "espera": j["espera"],
                      "exige_reserva": t["exige_reserva"], "minha_reserva": minhas.get(t["id"])})
    faixas = []
    for m in conn.execute("SELECT id, nome FROM public.modalidades WHERE id = ANY(%s) AND categoria = 'luta' ORDER BY nome", (sorted(mods),)).fetchall():
        fx = [dict(f) for f in conn.execute("SELECT nome, ordem, aulas_minimas FROM public.faixas WHERE modalidade_id = %s ORDER BY ordem", (m["id"],)).fetchall()]
        if not fx:
            continue
        g = conn.execute("SELECT f.ordem FROM public.aluno_graduacoes g JOIN public.faixas f ON f.id = g.faixa_id "
                         "WHERE g.aluno_id = %s AND g.modalidade_id = %s ORDER BY g.id DESC LIMIT 1", (aluno["id"], m["id"])).fetchone()
        n = _aulas_validadas(conn, aluno["id"], m["id"])
        faixas.append({"modalidade": m["nome"], "aulas_validadas": n, **regras.progresso_faixa(n, fx, g["ordem"] if g else None)})
    at = conn.execute("SELECT max(valido_ate) AS ate FROM public.atestados_aluno WHERE aluno_id = %s", (aluno["id"],)).fetchone()
    hoje = AGORA().astimezone(ZoneInfo(_fuso(conn, aluno["academia_id"]))).date()
    return {"disponivel": True, "grade": grade, "faixas": faixas,
            "atestado": {"valido_ate": at["ate"].isoformat() if at["ate"] else None, "em_dia": regras.atestado_ok(at["ate"], hoje)},
            "janela": {"antes_min": regras.ANTES_MIN, "depois_min": regras.DEPOIS_MIN}}


# --------------------------------------------------------------------------- chamada (professor / gestão)

def _linha_chamada(conn, aula_id: int, turma_id: int) -> list[dict]:
    ls = conn.execute(
        "SELECT a.id AS aluno_id, a.nome, p.estado, p.metodo, p.dentro_do_raio, (r.estado IS NOT NULL) AS reservado "
        "FROM public.alunos a "
        "LEFT JOIN public.presencas_aula p ON p.aluno_id = a.id AND p.aula_id = %s "
        "LEFT JOIN public.reservas_turma r ON r.aluno_id = a.id AND r.turma_id = %s AND r.estado = 'ativa' "
        "WHERE p.id IS NOT NULL OR r.id IS NOT NULL ORDER BY a.nome", (aula_id, turma_id)).fetchall()
    return [dict(l) for l in ls]


@router.get("/lutas/chamada")
def chamada(turma_id: int, data: date, horario_id: int | None = None,
            usuario=Depends(gestao_ou_professor), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    t = _turma_visivel(conn, usuario, turma_id)
    ocs = [o for o in _ocorrencias_do_dia(conn, t, data) if horario_id is None or o["horario_id"] == horario_id]
    if not ocs:
        raise _erro(404, "sem_aula_neste_dia")
    if len(ocs) > 1:
        return {"escolher_horario": [{"horario_id": o["horario_id"], "inicio": o["inicio"].isoformat()} for o in ocs]}
    oc = ocs[0]
    if oc["inicio"] > AGORA() + timedelta(hours=regras.ANTES_MIN // 60 + 1):
        raise _erro(422, "aula_no_futuro")
    aula = _obter_aula(conn, t, oc)
    conn.commit()
    return {"aula_id": aula["id"], "turma": t["nome"], "inicio": oc["inicio"].isoformat(), "fim": oc["fim"].isoformat(),
            "codigo_qr": _codigo_aula(t["id"], oc["inicio"]), "ajustavel": regras.pode_ajustar(AGORA(), oc["fim"]),
            "alunos": _linha_chamada(conn, aula["id"], t["id"])}


class AcaoChamada(BaseModel):
    acao: str = Field(pattern="^(validar|ausentar)$")


@router.put("/lutas/chamada/{aula_id}/alunos/{aluno_id}")
def marcar(aula_id: int, aluno_id: int, dados: AcaoChamada, usuario=Depends(gestao_ou_professor), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    aula = conn.execute("SELECT * FROM public.aulas_realizadas WHERE id = %s AND academia_id = %s", (aula_id, usuario["academia_id"])).fetchone()
    if aula is None:
        raise _erro(404, "aula_nao_encontrada")
    t = _turma_visivel(conn, usuario, aula["turma_id"])
    if not regras.pode_ajustar(AGORA(), aula["fim"]):
        raise _erro(409, "fora_do_prazo_de_ajuste")
    aluno = conn.execute("SELECT id, plano_id, academia_id FROM public.alunos WHERE id = %s AND academia_id = %s AND status = 'ativo'",
                         (aluno_id, usuario["academia_id"])).fetchone()
    if aluno is None:
        raise _erro(404, "aluno_nao_encontrado")
    if dados.acao == "validar" and not regras.elegivel(_modalidades_do_aluno(conn, aluno, ["luta", "aula"]), t["modalidade_id"]):
        raise _erro(422, "plano_sem_modalidade")
    atual = conn.execute("SELECT estado FROM public.presencas_aula WHERE aula_id = %s AND aluno_id = %s", (aula_id, aluno_id)).fetchone()
    novo = regras.transicao(atual["estado"] if atual else None, dados.acao)
    agora = AGORA()
    conn.execute(
        "INSERT INTO public.presencas_aula (aula_id, aluno_id, estado, metodo, validada_em, validada_por) VALUES (%s,%s,%s,'professor',%s,%s) "
        "ON CONFLICT (aula_id, aluno_id) DO UPDATE SET estado = EXCLUDED.estado, validada_em = EXCLUDED.validada_em, validada_por = EXCLUDED.validada_por",
        (aula_id, aluno_id, novo, agora, usuario["id"]))
    conn.commit()
    return {"aula_id": aula_id, "aluno_id": aluno_id, "estado": novo}


# --------------------------------------------------------------------------- faixas, graduação, atestado

class FaixaEntrada(BaseModel):
    modalidade_id: int
    nome: str = Field(min_length=1, max_length=40)
    ordem: int = Field(ge=0, le=50)
    aulas_minimas: int = Field(default=0, ge=0, le=5000)


@router.get("/lutas/faixas")
def listar_faixas(modalidade_id: int | None = None, usuario=Depends(gestao_ou_professor), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    ls = conn.execute("SELECT id, modalidade_id, nome, ordem, aulas_minimas FROM public.faixas WHERE academia_id = %s "
                      "AND (%s::int IS NULL OR modalidade_id = %s) ORDER BY modalidade_id, ordem",
                      (usuario["academia_id"], modalidade_id, modalidade_id)).fetchall()
    return {"faixas": [dict(l) for l in ls]}


@router.post("/lutas/faixas", status_code=201)
def criar_faixa(dados: FaixaEntrada, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    if conn.execute("SELECT 1 FROM public.modalidades WHERE id = %s AND academia_id = %s", (dados.modalidade_id, usuario["academia_id"])).fetchone() is None:
        raise _erro(422, "modalidade_invalida")
    try:
        f = conn.execute("INSERT INTO public.faixas (academia_id, modalidade_id, nome, ordem, aulas_minimas) VALUES (%s,%s,%s,%s,%s) "
                         "RETURNING id, modalidade_id, nome, ordem, aulas_minimas",
                         (usuario["academia_id"], dados.modalidade_id, dados.nome.strip(), dados.ordem, dados.aulas_minimas)).fetchone()
    except Exception:
        conn.rollback()
        raise _erro(409, "ordem_ja_existe")
    conn.commit()
    return dict(f)


@router.delete("/lutas/faixas/{fid}", status_code=204)
def apagar_faixa(fid: int, usuario=Depends(seguranca.somente_dono), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    try:
        r = conn.execute("DELETE FROM public.faixas WHERE id = %s AND academia_id = %s RETURNING id", (fid, usuario["academia_id"])).fetchone()
    except Exception:
        conn.rollback()
        raise _erro(409, "faixa_em_uso")
    if r is None:
        raise _erro(404, "faixa_nao_encontrada")
    conn.commit()


class GraduacaoEntrada(BaseModel):
    faixa_id: int


def _aluno_da_academia(conn, usuario: dict, aluno_id: int) -> dict:
    a = conn.execute("SELECT id, plano_id, academia_id FROM public.alunos WHERE id = %s AND academia_id = %s", (aluno_id, usuario["academia_id"])).fetchone()
    if a is None:
        raise _erro(404, "aluno_nao_encontrado")
    return a


@router.post("/lutas/alunos/{aluno_id}/graduacao", status_code=201)
def graduar(aluno_id: int, dados: GraduacaoEntrada, usuario=Depends(gestao_ou_professor), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    aluno = _aluno_da_academia(conn, usuario, aluno_id)
    f = conn.execute("SELECT id, modalidade_id FROM public.faixas WHERE id = %s AND academia_id = %s", (dados.faixa_id, usuario["academia_id"])).fetchone()
    if f is None:
        raise _erro(422, "faixa_invalida")
    if not regras.elegivel(_modalidades_do_aluno(conn, aluno, ["luta"]), f["modalidade_id"]):
        raise _erro(422, "plano_sem_modalidade")
    prof = _professor_do_usuario(conn, usuario)
    if prof is not None and conn.execute(
            "SELECT 1 FROM public.reservas_turma r JOIN public.turmas t ON t.id = r.turma_id "
            "WHERE r.aluno_id = %s AND t.professor_id = %s AND t.modalidade_id = %s LIMIT 1", (aluno_id, prof["id"], f["modalidade_id"])).fetchone() is None:
        raise _erro(404, "aluno_nao_encontrado")
    conn.execute("INSERT INTO public.aluno_graduacoes (aluno_id, modalidade_id, faixa_id, concedida_por) VALUES (%s,%s,%s,%s)",
                 (aluno_id, f["modalidade_id"], f["id"], usuario["id"]))
    conn.commit()
    return {"aluno_id": aluno_id, "faixa_id": f["id"]}


class AtestadoEntrada(BaseModel):
    valido_ate: date
    observacao: str = Field(default="", max_length=200)


@router.post("/lutas/alunos/{aluno_id}/atestado", status_code=201)
def registrar_atestado(aluno_id: int, dados: AtestadoEntrada, usuario=Depends(gestao), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    _aluno_da_academia(conn, usuario, aluno_id)
    conn.execute("INSERT INTO public.atestados_aluno (aluno_id, valido_ate, observacao, registrado_por) VALUES (%s,%s,%s,%s)",
                 (aluno_id, dados.valido_ate, dados.observacao.strip(), usuario["id"]))
    conn.commit()
    return {"aluno_id": aluno_id, "valido_ate": dados.valido_ate.isoformat()}


# --------------------------------------------------------------------------- relatórios

@router.get("/lutas/relatorios/frequencia")
def relatorio_frequencia(turma_id: int, de: date, ate: date, usuario=Depends(gestao_ou_professor), conn=Depends(aluno_auth.conexao)):
    _exigir_recurso(conn, usuario)
    _turma_visivel(conn, usuario, turma_id)
    if ate < de or (ate - de).days > 366:
        raise _erro(422, "periodo_invalido")
    fuso = _fuso(conn, usuario["academia_id"])
    ini = datetime.combine(de, datetime.min.time(), tzinfo=ZoneInfo(fuso)).astimezone(timezone.utc)
    fim = datetime.combine(ate + timedelta(days=1), datetime.min.time(), tzinfo=ZoneInfo(fuso)).astimezone(timezone.utc)
    aulas = conn.execute("SELECT count(*) AS n FROM public.aulas_realizadas WHERE turma_id = %s AND inicio >= %s AND inicio < %s", (turma_id, ini, fim)).fetchone()["n"]
    ls = conn.execute(
        "SELECT a.id AS aluno_id, a.nome, count(*) FILTER (WHERE p.estado='validada') AS validadas, "
        "       count(*) FILTER (WHERE p.estado='ausente') AS ausencias, count(*) FILTER (WHERE p.estado='confirmada') AS pendentes "
        "FROM public.presencas_aula p JOIN public.aulas_realizadas r ON r.id = p.aula_id JOIN public.alunos a ON a.id = p.aluno_id "
        "WHERE r.turma_id = %s AND r.inicio >= %s AND r.inicio < %s GROUP BY a.id, a.nome ORDER BY validadas DESC, a.nome", (turma_id, ini, fim)).fetchall()
    return {"aulas_no_periodo": aulas, "alunos": [dict(l) for l in ls]}


@router.get("/lutas/relatorios/ocupacao")
def relatorio_ocupacao(usuario=Depends(gestao_ou_professor), conn=Depends(aluno_auth.conexao)):
    cats = _exigir_recurso(conn, usuario)
    prof = _professor_do_usuario(conn, usuario)
    sql = ("SELECT t.id, t.nome, t.capacidade, "
           "  (SELECT count(*) FROM public.reservas_turma r WHERE r.turma_id = t.id AND r.estado='ativa') AS reservas, "
           "  (SELECT count(*) FROM public.reservas_turma r WHERE r.turma_id = t.id AND r.estado='espera') AS espera, "
           "  (SELECT COALESCE(round(avg(c)::numeric, 1), 0) FROM (SELECT count(*) FILTER (WHERE p.estado='validada') AS c "
           "     FROM public.aulas_realizadas a LEFT JOIN public.presencas_aula p ON p.aula_id = a.id WHERE a.turma_id = t.id GROUP BY a.id) x) AS media_presentes "
           "FROM public.turmas t JOIN public.modalidades m ON m.id = t.modalidade_id WHERE t.academia_id = %s AND t.ativa AND m.categoria = ANY(%s)")
    args: list = [usuario["academia_id"], cats]
    if prof is not None:
        sql += " AND t.professor_id = %s"
        args.append(prof["id"])
    ls = conn.execute(sql + " ORDER BY t.nome", args).fetchall()
    return {"turmas": [{**dict(l), "media_presentes": float(l["media_presentes"]),
                        "ocupacao_pct": int(100 * l["reservas"] / l["capacidade"])} for l in ls]}
