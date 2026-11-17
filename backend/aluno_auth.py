"""Autenticação do aluno no app: e-mail + código de primeiro acesso, senha, sessão e Google.

Funções puras no topo (sem banco); serviços e rotas abaixo. Nada aqui registra código,
token ou senha em log.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


def _segredo() -> bytes:
    import seguranca  # import tardio: evita ciclo e permite testar o núcleo isolado

    return seguranca.SECRET_KEY.encode("utf-8")


def normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


def gerar_codigo() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_codigo(codigo: str, aluno_id: int) -> str:
    mensagem = f"{aluno_id}:{codigo}".encode("utf-8")
    return hmac.new(_segredo(), mensagem, hashlib.sha256).hexdigest()


def codigo_valido(codigo_informado: str, aluno_id: int, hash_guardado: str) -> bool:
    return hmac.compare_digest(hash_codigo(codigo_informado or "", aluno_id), hash_guardado or "")


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def novo_token_sessao() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


# ---------------------------------------------------------------------------
# Serviços (usam conexão psycopg com dict_row; quem chama controla o commit)
# ---------------------------------------------------------------------------
import logging
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr

_log = logging.getLogger("frequency.aluno_auth")

MINUTOS_CODIGO = 10
MAX_TENTATIVAS_CODIGO = 5
SEGUNDOS_ENTRE_ENVIOS = 60
MAX_ENVIOS_POR_HORA = 5
RECURSO_LOGIN = "app_aluno_login"


def enviar_email_texto(destino: str, assunto: str, corpo: str) -> bool:
    """Envia e-mail simples com as variáveis FREQUENCY_SMTP_*. Retorna False se não configurado/falhar."""
    host = os.getenv("FREQUENCY_SMTP_HOST", "").strip()
    user = os.getenv("FREQUENCY_SMTP_USER", "").strip()
    senha = os.getenv("FREQUENCY_SMTP_PASSWORD", "")
    remetente = os.getenv("FREQUENCY_SMTP_FROM", user).strip()
    if not (host and user and senha and remetente):
        return False
    try:
        porta = int(os.getenv("FREQUENCY_SMTP_PORT", "465"))
    except ValueError:
        return False
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = formataddr(("Frequency Gym", remetente))
    msg["To"] = destino
    msg.set_content(corpo)
    # Porta 587 (ou FREQUENCY_SMTP_SECURITY=starttls) usa STARTTLS; as demais usam SSL direto (465).
    starttls = os.getenv("FREQUENCY_SMTP_SECURITY", "").strip().lower() == "starttls" or porta == 587
    try:
        if starttls:
            with smtplib.SMTP(host, porta, timeout=15) as servidor:
                servidor.starttls()
                servidor.login(user, senha)
                servidor.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, porta, timeout=15) as servidor:
                servidor.login(user, senha)
                servidor.send_message(msg)
        return True
    except (OSError, smtplib.SMTPException) as erro:
        # Só o tipo do erro: nunca o texto (pode ter e-mail/usuário) nem credenciais.
        _log.warning("falha ao enviar e-mail de acesso: %s (porta %s, %s)", type(erro).__name__, porta, "starttls" if starttls else "ssl")
        return False


def recurso_ligado(conn, academia_id: int, recurso: str) -> bool:
    linha = conn.execute(
        "SELECT ligado FROM public.academia_recursos WHERE academia_id = %s AND recurso = %s",
        (academia_id, recurso),
    ).fetchone()
    return bool(linha and linha["ligado"])


def _assinatura_em_dia(conn, academia_id: int) -> bool:
    from cobranca_saas import estado_assinatura_frequency

    return not estado_assinatura_frequency(conn, academia_id).get("bloqueada_frequency")


def alunos_elegiveis(conn, email: str, assinatura_ok=_assinatura_em_dia, aluno_id: int | None = None) -> list[dict]:
    """Alunos ativos com esse e-mail, em academias ativas, com o recurso ligado e assinatura em dia."""
    linhas = conn.execute(
        "SELECT a.id, a.nome, a.academia_id, ac.nome AS academia_nome, ac.pais, ac.idioma "
        "FROM public.alunos a JOIN public.academias ac ON ac.id = a.academia_id "
        "WHERE lower(a.email) = %s AND a.status = 'ativo' AND ac.ativa "
        "AND (%s::int IS NULL OR a.id = %s::int) ORDER BY a.id",
        (normalizar_email(email), aluno_id, aluno_id),
    ).fetchall()
    return [
        l for l in linhas
        if recurso_ligado(conn, l["academia_id"], RECURSO_LOGIN) and assinatura_ok(conn, l["academia_id"])
    ]


def _texto_codigo(aluno: dict, codigo: str) -> tuple[str, str]:
    es = (aluno.get("idioma") or "").lower().startswith("es")
    if es:
        return (
            "Tu código de acceso — Frequency Gym",
            f"Hola, {aluno['nome']}!\n\nTu código para entrar a la app de {aluno['academia_nome']} es: {codigo}\n\n"
            f"Vale por {MINUTOS_CODIGO} minutos. Si no lo pediste, ignora este mensaje.",
        )
    return (
        "Seu código de acesso — Frequency Gym",
        f"Olá, {aluno['nome']}!\n\nSeu código para entrar no app da {aluno['academia_nome']} é: {codigo}\n\n"
        f"Ele vale por {MINUTOS_CODIGO} minutos. Se você não pediu, ignore esta mensagem.",
    )


def iniciar_acesso(conn, email: str, ip: str | None = None, *, enviar=enviar_email_texto,
                   assinatura_ok=_assinatura_em_dia, agora: datetime | None = None,
                   aluno_id: int | None = None) -> int:
    """Envia o código de primeiro acesso se (e só se) o e-mail for de aluno elegível.

    Rota pública ignora o retorno (nunca revela se o e-mail existe); o painel usa a contagem de envios.
    """
    agora = agora or datetime.now(timezone.utc)
    enviados = 0
    for aluno in alunos_elegiveis(conn, email, assinatura_ok, aluno_id):
        recentes = conn.execute(
            "SELECT count(*) FILTER (WHERE criado_em > %s) AS ultimo_minuto, "
            "       count(*) FILTER (WHERE criado_em > %s) AS ultima_hora "
            "FROM public.aluno_codigos WHERE aluno_id = %s",
            (agora - timedelta(seconds=SEGUNDOS_ENTRE_ENVIOS), agora - timedelta(hours=1), aluno["id"]),
        ).fetchone()
        if recentes["ultimo_minuto"] > 0 or recentes["ultima_hora"] >= MAX_ENVIOS_POR_HORA:
            continue
        conn.execute(
            "UPDATE public.aluno_codigos SET usado_em = %s WHERE aluno_id = %s AND usado_em IS NULL",
            (agora, aluno["id"]),
        )
        codigo = gerar_codigo()
        conn.execute(
            "INSERT INTO public.aluno_codigos (aluno_id, codigo_hash, criado_em, expira_em) "
            "VALUES (%s, %s, %s, %s)",
            (aluno["id"], hash_codigo(codigo, aluno["id"]), agora, agora + timedelta(minutes=MINUTOS_CODIGO)),
        )
        assunto, corpo = _texto_codigo(aluno, codigo)
        if enviar(normalizar_email(email), assunto, corpo):
            enviados += 1
    return enviados


DIAS_SESSAO = 30
MINUTOS_TICKET = 10
SENHA_MINIMA = 8


def verificar_codigo(conn, email: str, codigo: str, *, assinatura_ok=_assinatura_em_dia,
                     agora: datetime | None = None) -> str | None:
    """Confere o código de primeiro acesso. Retorna um ticket (uso único, 10 min) ou None.

    Tentativas erradas são contadas; na 5ª o código é invalidado. Quem chama deve dar commit
    mesmo quando o retorno for None (para persistir o contador).
    """
    agora = agora or datetime.now(timezone.utc)
    for aluno in alunos_elegiveis(conn, email, assinatura_ok):
        linha = conn.execute(
            "SELECT id, codigo_hash, tentativas FROM public.aluno_codigos "
            "WHERE aluno_id = %s AND usado_em IS NULL AND expira_em > %s "
            "ORDER BY id DESC LIMIT 1 FOR UPDATE",
            (aluno["id"], agora),
        ).fetchone()
        if linha is None:
            continue
        if codigo_valido(codigo, aluno["id"], linha["codigo_hash"]):
            ticket = secrets.token_urlsafe(32)
            conn.execute(
                "UPDATE public.aluno_codigos SET usado_em = %s, ticket_hash = %s, ticket_expira_em = %s WHERE id = %s",
                (agora, hash_token(ticket), agora + timedelta(minutes=MINUTOS_TICKET), linha["id"]),
            )
            return ticket
        tentativas = linha["tentativas"] + 1
        conn.execute(
            "UPDATE public.aluno_codigos SET tentativas = %s, usado_em = CASE WHEN %s >= %s THEN %s ELSE usado_em END "
            "WHERE id = %s",
            (tentativas, tentativas, MAX_TENTATIVAS_CODIGO, agora, linha["id"]),
        )
    return None


def criar_sessao(conn, aluno: dict, aparelho: str = "", agora: datetime | None = None) -> dict:
    agora = agora or datetime.now(timezone.utc)
    token, h = novo_token_sessao()
    expira = agora + timedelta(days=DIAS_SESSAO)
    conn.execute(
        "INSERT INTO public.aluno_sessoes (aluno_id, token_hash, aparelho, criado_em, expira_em) "
        "VALUES (%s, %s, %s, %s, %s)",
        (aluno["id"], h, (aparelho or "")[:120], agora, expira),
    )
    return {
        "token": token,
        "expira_em": expira.isoformat(),
        "aluno": {"id": aluno["id"], "nome": aluno["nome"], "academia_id": aluno["academia_id"]},
    }


def definir_senha(conn, ticket: str, senha: str, aparelho: str = "", *, agora: datetime | None = None) -> dict:
    """Consome o ticket, grava a senha (Argon2) e abre a sessão. ValueError: senha_curta | ticket_invalido."""
    agora = agora or datetime.now(timezone.utc)
    if len(senha or "") < SENHA_MINIMA:
        raise ValueError("senha_curta")
    linha = conn.execute(
        "SELECT c.id, c.aluno_id FROM public.aluno_codigos c "
        "WHERE c.ticket_hash = %s AND c.ticket_usado_em IS NULL AND c.ticket_expira_em > %s FOR UPDATE",
        (hash_token(ticket or ""), agora),
    ).fetchone()
    if linha is None:
        raise ValueError("ticket_invalido")
    aluno = conn.execute(
        "SELECT id, nome, academia_id FROM public.alunos WHERE id = %s AND status = 'ativo'", (linha["aluno_id"],)
    ).fetchone()
    if aluno is None:
        raise ValueError("ticket_invalido")
    from seguranca import gerar_hash

    conn.execute("UPDATE public.aluno_codigos SET ticket_usado_em = %s WHERE id = %s", (agora, linha["id"]))
    conn.execute(
        "INSERT INTO public.aluno_credenciais (aluno_id, senha_hash, definida_em) VALUES (%s, %s, %s) "
        "ON CONFLICT (aluno_id) DO UPDATE SET senha_hash = EXCLUDED.senha_hash, definida_em = EXCLUDED.definida_em",
        (aluno["id"], gerar_hash(senha), agora),
    )
    return criar_sessao(conn, aluno, aparelho, agora)


def entrar_com_senha(conn, email: str, senha: str, aparelho: str = "", *, assinatura_ok=_assinatura_em_dia,
                     agora: datetime | None = None) -> dict | None:
    """Login por e-mail+senha. Retorna a sessão ou None (mesmo tempo aproximado em todos os casos de falha)."""
    from seguranca import verificar_senha

    agora = agora or datetime.now(timezone.utc)
    verificou = False
    for aluno in alunos_elegiveis(conn, email, assinatura_ok):
        cred = conn.execute(
            "SELECT senha_hash FROM public.aluno_credenciais WHERE aluno_id = %s", (aluno["id"],)
        ).fetchone()
        if cred and cred["senha_hash"]:
            verificou = True
            if verificar_senha(senha, cred["senha_hash"]):
                return criar_sessao(conn, aluno, aparelho, agora)
    if not verificou:
        verificar_senha(senha, None)  # iguala o custo (um Argon2) quando não havia credencial
    return None


def sessao_do_token(conn, token: str, *, assinatura_ok=_assinatura_em_dia, agora: datetime | None = None) -> dict | None:
    """Aluno dono do token, se a sessão está válida e o aluno/academia seguem habilitados."""
    agora = agora or datetime.now(timezone.utc)
    linha = conn.execute(
        "SELECT s.id AS sessao_id, a.id, a.nome, a.email, a.academia_id, a.plano_id, a.status, "
        "       ac.nome AS academia_nome, ac.pais, ac.moeda, ac.idioma "
        "FROM public.aluno_sessoes s "
        "JOIN public.alunos a ON a.id = s.aluno_id "
        "JOIN public.academias ac ON ac.id = a.academia_id "
        "WHERE s.token_hash = %s AND s.revogada_em IS NULL AND s.expira_em > %s "
        "      AND a.status = 'ativo' AND ac.ativa",
        (hash_token(token or ""), agora),
    ).fetchone()
    if linha is None:
        return None
    if not recurso_ligado(conn, linha["academia_id"], RECURSO_LOGIN) or not assinatura_ok(conn, linha["academia_id"]):
        return None
    return linha


def revogar_sessao(conn, sessao_id: int, agora: datetime | None = None) -> None:
    conn.execute("UPDATE public.aluno_sessoes SET revogada_em = %s WHERE id = %s AND revogada_em IS NULL",
                 (agora or datetime.now(timezone.utc), sessao_id))


def perfil_do_aluno(conn, sessao: dict) -> dict:
    plano = None
    if sessao["plano_id"]:
        p = conn.execute("SELECT id, nome FROM public.planos WHERE id = %s", (sessao["plano_id"],)).fetchone()
        if p:
            plano = {"id": p["id"], "nome": p["nome"], "modalidades": []}
    return {
        "id": sessao["id"],
        "nome": sessao["nome"],
        "email": sessao["email"],
        "status": sessao["status"],
        "academia": {"id": sessao["academia_id"], "nome": sessao["academia_nome"],
                     "pais": sessao["pais"], "moeda": sessao["moeda"]},
        "plano": plano,
    }


GOOGLE_EMISSORES = ["https://accounts.google.com", "accounts.google.com"]
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_jwks_cache: dict = {"quando": 0.0, "dados": None}


def _buscar_jwks() -> dict:
    import json
    import time
    import urllib.request

    if _jwks_cache["dados"] and time.monotonic() - _jwks_cache["quando"] < 3600:
        return _jwks_cache["dados"]
    with urllib.request.urlopen(GOOGLE_JWKS_URL, timeout=10) as resposta:  # noqa: S310 (URL fixa https)
        dados = json.loads(resposta.read().decode("utf-8"))
    _jwks_cache.update(quando=time.monotonic(), dados=dados)
    return dados


def audiencias_google() -> list[str]:
    """Client IDs aceitos como `aud`: os do app (GOOGLE_ALUNO_CLIENT_IDS) e o client web já usado no painel."""
    ids = [c.strip() for c in os.getenv("GOOGLE_ALUNO_CLIENT_IDS", "").split(",") if c.strip()]
    web = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    if web and web not in ids:
        ids.append(web)
    return ids


def validar_id_token_google(id_token: str, audiencias: list[str], jwks_fetch=None) -> dict:
    """Valida assinatura RS256, emissor, audiência e expiração. ValueError('token_google_invalido') se falhar."""
    import jwt

    try:
        jwks = (jwks_fetch or _buscar_jwks)()
        kid = jwt.get_unverified_header(id_token).get("kid")
        chave = next((jwt.PyJWK(k).key for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if chave is None or not audiencias:
            raise ValueError("token_google_invalido")
        claims = jwt.decode(
            id_token, chave, algorithms=["RS256"], audience=audiencias, issuer=GOOGLE_EMISSORES,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except (jwt.PyJWTError, OSError, KeyError, ValueError, AttributeError) as erro:
        raise ValueError("token_google_invalido") from erro
    if not claims.get("email") or claims.get("email_verified") is not True:
        raise ValueError("token_google_invalido")
    return claims


def entrar_com_google(conn, id_token: str, aparelho: str = "", *, audiencias: list[str] | None = None,
                      jwks_fetch=None, assinatura_ok=_assinatura_em_dia,
                      agora: datetime | None = None) -> dict | None:
    """Login com Google: só para e-mail já cadastrado na academia. Vincula o `sub` no primeiro uso."""
    agora = agora or datetime.now(timezone.utc)
    try:
        claims = validar_id_token_google(id_token, audiencias if audiencias is not None else audiencias_google(), jwks_fetch)
    except ValueError:
        return None
    sub = claims["sub"]
    for aluno in alunos_elegiveis(conn, claims["email"], assinatura_ok):
        cred = conn.execute(
            "SELECT google_sub FROM public.aluno_credenciais WHERE aluno_id = %s FOR UPDATE", (aluno["id"],)
        ).fetchone()
        if cred and cred["google_sub"] and cred["google_sub"] != sub:
            continue
        if cred is None:
            conn.execute("INSERT INTO public.aluno_credenciais (aluno_id, google_sub, definida_em) VALUES (%s, %s, %s)",
                         (aluno["id"], sub, agora))
        elif not cred["google_sub"]:
            conn.execute("UPDATE public.aluno_credenciais SET google_sub = %s WHERE aluno_id = %s", (sub, aluno["id"]))
        return criar_sessao(conn, aluno, aparelho, agora)
    return None


import re as _re

_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def email_valido(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or ""))


def estado_acesso(conn, academia_id: int, aluno_id: int) -> dict | None:
    """Estado do acesso ao app para a ficha do aluno (None se o aluno não é da academia)."""
    linha = conn.execute(
        "SELECT a.id, a.email, EXISTS (SELECT 1 FROM public.aluno_credenciais c WHERE c.aluno_id = a.id) AS tem_cred "
        "FROM public.alunos a WHERE a.id = %s AND a.academia_id = %s",
        (aluno_id, academia_id),
    ).fetchone()
    if linha is None:
        return None
    acesso = "sem_email" if not linha["email"] else ("ativo" if linha["tem_cred"] else "convidado")
    return {"email": linha["email"], "acesso_app": acesso}


def definir_email(conn, academia_id: int, aluno_id: int, email: str | None) -> bool:
    """Grava o e-mail do aluno. ValueError: email_invalido | email_ja_cadastrado. False se aluno inexistente."""
    from psycopg import errors

    novo = normalizar_email(email) if email else None
    if novo is not None and not _EMAIL_RE.match(novo):
        raise ValueError("email_invalido")
    try:
        with conn.transaction():  # savepoint: uma violação não aborta a transação inteira
            antes = conn.execute("SELECT email FROM public.alunos WHERE id = %s AND academia_id = %s",
                                 (aluno_id, academia_id)).fetchone()
            r = conn.execute("UPDATE public.alunos SET email = %s WHERE id = %s AND academia_id = %s RETURNING id",
                             (novo, aluno_id, academia_id)).fetchone()
            if r is not None and antes and (antes["email"] or None) != novo and antes["email"]:
                # o e-mail é a identidade do acesso: trocar encerra sessões e senha anteriores
                redefinir_acesso(conn, academia_id, aluno_id)
    except errors.UniqueViolation as erro:
        raise ValueError("email_ja_cadastrado") from erro
    except errors.UndefinedColumn as erro:
        raise ValueError("migracao_email_pendente") from erro
    return r is not None


def redefinir_acesso(conn, academia_id: int, aluno_id: int, agora: datetime | None = None) -> bool:
    agora = agora or datetime.now(timezone.utc)
    if estado_acesso(conn, academia_id, aluno_id) is None:
        return False
    conn.execute("UPDATE public.aluno_sessoes SET revogada_em = %s WHERE aluno_id = %s AND revogada_em IS NULL",
                 (agora, aluno_id))
    conn.execute("DELETE FROM public.aluno_credenciais WHERE aluno_id = %s", (aluno_id,))
    conn.execute("UPDATE public.aluno_codigos SET usado_em = %s WHERE aluno_id = %s AND usado_em IS NULL",
                 (agora, aluno_id))
    return True


# ---------------------------------------------------------------------------
# Rotas HTTP
# ---------------------------------------------------------------------------
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/aluno", tags=["aluno"])
_limitador = None
# pontos de substituição para testes (envio de e-mail e checagem de assinatura)
ENVIAR_EMAIL = enviar_email_texto
ASSINATURA_OK = _assinatura_em_dia


def limitador():
    global _limitador
    if _limitador is None:
        from rate_limiting import LoginRateLimiter

        _limitador = LoginRateLimiter(_segredo().decode("utf-8"))
    return _limitador


def conexao():
    from database import get_connection

    with get_connection() as conn:
        yield conn


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _limitar(chave: str, request: Request) -> None:
    espera = limitador().retry_after(chave, _ip(request))
    if espera:
        raise HTTPException(429, "muitas_tentativas", headers={"Retry-After": str(espera)})


class IniciarEntrada(BaseModel):
    email: str


@router.post("/auth/iniciar")
def rota_iniciar(dados: IniciarEntrada, request: Request, conn=Depends(conexao)):
    email = normalizar_email(dados.email)
    _limitar("iniciar:" + email, request)
    limitador().record_failure("iniciar:" + email, _ip(request))
    iniciar_acesso(conn, email, _ip(request), enviar=ENVIAR_EMAIL, assinatura_ok=ASSINATURA_OK)
    return {"enviado": True}


class CodigoEntrada(BaseModel):
    email: str
    codigo: str


class DefinirSenhaEntrada(BaseModel):
    ticket: str
    senha: str
    aparelho: str = ""


@router.post("/auth/codigo")
def rota_codigo(dados: CodigoEntrada, request: Request, conn=Depends(conexao)):
    email = normalizar_email(dados.email)
    _limitar("codigo:" + email, request)
    ticket = verificar_codigo(conn, email, dados.codigo.strip(), assinatura_ok=ASSINATURA_OK)
    conn.commit()  # persiste o contador de tentativas mesmo em caso de erro
    if ticket is None:
        limitador().record_failure("codigo:" + email, _ip(request))
        raise HTTPException(400, "codigo_invalido")
    return {"ticket": ticket}


@router.post("/auth/definir-senha")
def rota_definir_senha(dados: DefinirSenhaEntrada, conn=Depends(conexao)):
    try:
        return definir_senha(conn, dados.ticket, dados.senha, dados.aparelho)
    except ValueError as erro:
        if str(erro) == "senha_curta":
            raise HTTPException(422, "senha_curta")
        raise HTTPException(400, "ticket_invalido")


class EntrarEntrada(BaseModel):
    email: str
    senha: str
    aparelho: str = ""


@router.post("/auth/entrar")
def rota_entrar(dados: EntrarEntrada, request: Request, conn=Depends(conexao)):
    email = normalizar_email(dados.email)
    _limitar("entrar:" + email, request)
    sessao = entrar_com_senha(conn, email, dados.senha, dados.aparelho, assinatura_ok=ASSINATURA_OK)
    conn.commit()
    if sessao is None:
        limitador().record_failure("entrar:" + email, _ip(request))
        raise HTTPException(401, "credenciais_invalidas")
    limitador().clear("entrar:" + email, _ip(request))
    return sessao


from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


def aluno_atual(credenciais: HTTPAuthorizationCredentials | None = Depends(_bearer), conn=Depends(conexao)) -> dict:
    """Dependência para rotas do app: devolve a linha do aluno da sessão ou responde 401 token_invalido."""
    sessao = sessao_do_token(conn, credenciais.credentials if credenciais else "", assinatura_ok=ASSINATURA_OK)
    if sessao is None:
        raise HTTPException(401, "token_invalido")
    return sessao


@router.post("/auth/sair", status_code=204)
def rota_sair(sessao: dict = Depends(aluno_atual), conn=Depends(conexao)):
    revogar_sessao(conn, sessao["sessao_id"])


@router.get("/eu")
def rota_eu(sessao: dict = Depends(aluno_atual), conn=Depends(conexao)):
    return perfil_do_aluno(conn, sessao)


class GoogleEntrada(BaseModel):
    id_token: str
    aparelho: str = ""


@router.post("/auth/google")
def rota_google(dados: GoogleEntrada, request: Request, conn=Depends(conexao)):
    if not audiencias_google():
        raise HTTPException(503, "google_nao_configurado")
    _limitar("google", request)
    sessao = entrar_com_google(conn, dados.id_token, dados.aparelho, assinatura_ok=ASSINATURA_OK)
    conn.commit()
    if sessao is None:
        limitador().record_failure("google", _ip(request))
        raise HTTPException(401, "credenciais_invalidas")
    return sessao


# ---- Painel da academia (dono/recepção) -----------------------------------
from seguranca import usuario_de_academia  # noqa: E402

router_painel = APIRouter(tags=["alunos-acesso-app"])


def _escrita_local() -> None:
    if os.getenv("SYNC_MIRROR_READ_ONLY", "").strip().upper() == "YES":
        raise HTTPException(403, "modo_somente_consulta")


class EmailAlunoEntrada(BaseModel):
    email: str | None = None


@router_painel.get("/alunos/{aluno_id}/acesso-app")
def rota_acesso_app(aluno_id: int, usuario=Depends(usuario_de_academia), conn=Depends(conexao)):
    try:
        estado = estado_acesso(conn, usuario["academia_id"], aluno_id)
    except Exception as erro:  # coluna ausente antes da migração 043
        if "email" in str(erro) or "aluno_credenciais" in str(erro):
            raise HTTPException(503, "migracao_email_pendente") from erro
        raise
    if estado is None:
        raise HTTPException(404, "aluno_nao_encontrado")
    estado["app_ligado"] = recurso_ligado(conn, usuario["academia_id"], RECURSO_LOGIN)
    return estado


@router_painel.put("/alunos/{aluno_id}/email")
def rota_definir_email(aluno_id: int, dados: EmailAlunoEntrada, usuario=Depends(usuario_de_academia),
                       conn=Depends(conexao)):
    _escrita_local()
    if usuario["papel"] != "dono":  # recepção só cadastra o primeiro e-mail; trocar é do dono
        atual = conn.execute("SELECT email FROM public.alunos WHERE id = %s AND academia_id = %s",
                             (aluno_id, usuario["academia_id"])).fetchone()
        if atual and atual["email"]:
            raise HTTPException(403, "sem_permissao")
    try:
        achou = definir_email(conn, usuario["academia_id"], aluno_id, dados.email)
    except ValueError as erro:
        codigo = str(erro)
        raise HTTPException({"email_invalido": 422, "email_ja_cadastrado": 409}.get(codigo, 503), codigo) from erro
    if not achou:
        raise HTTPException(404, "aluno_nao_encontrado")
    return {"ok": True}


@router_painel.post("/alunos/{aluno_id}/convite")
def rota_convite(aluno_id: int, usuario=Depends(usuario_de_academia), conn=Depends(conexao)):
    _escrita_local()
    estado = estado_acesso(conn, usuario["academia_id"], aluno_id)
    if estado is None:
        raise HTTPException(404, "aluno_nao_encontrado")
    if not estado["email"]:
        raise HTTPException(409, "aluno_sem_email")
    if not recurso_ligado(conn, usuario["academia_id"], RECURSO_LOGIN):
        raise HTTPException(409, "recurso_desligado")
    enviados = iniciar_acesso(conn, estado["email"], enviar=ENVIAR_EMAIL, assinatura_ok=ASSINATURA_OK, aluno_id=aluno_id)
    conn.commit()
    if not enviados:
        raise HTTPException(409, "convite_nao_enviado")
    return {"enviado": True}


@router_painel.post("/alunos/{aluno_id}/redefinir-acesso")
def rota_redefinir_acesso(aluno_id: int, usuario=Depends(usuario_de_academia), conn=Depends(conexao)):
    _escrita_local()
    if usuario["papel"] != "dono":
        raise HTTPException(403, "sem_permissao")
    if not redefinir_acesso(conn, usuario["academia_id"], aluno_id):
        raise HTTPException(404, "aluno_nao_encontrado")
    return {"ok": True}
