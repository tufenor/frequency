
import base64
import binascii
import hashlib
import hmac
import html
import io
import json
import os
import re
import secrets
import smtplib
import subprocess
import sys
import threading
import urllib.parse
import urllib.error
import urllib.request
import warnings
from email.message import EmailMessage
from email.utils import formataddr
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, RedirectResponse
from fastapi.security import APIKeyHeader, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from psycopg import errors
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, ValidationError, field_validator

from database import get_connection
from cobranca_saas import estado_assinatura_frequency
from face_engine import FaceError, MODEL_VERSION, embedding, enrollment_template, similarity
from pagamento_gateway import (
    GatewayIndisponivel,
    GatewayNaoConfigurado,
    criar_checkout_dlocal,
    hash_evento_webhook,
    status_dlocal_falhou,
    status_dlocal_pago,
    validar_notificacao_dlocal,
)
from captacao_osm import consultar_osm, geocodificar_regiao, lead_osm
from captacao_apify import buscar_apify, lead_apify
from captacao_contatos import buscar_contatos_publicos
from prospeccao import (
    TEMPLATE_WHATSAPP_PADRAO,
    TEMPLATE_EMAIL_ASSUNTO_PADRAO,
    TEMPLATE_EMAIL_CORPO_PADRAO,
    renderizar_template,
)
from rate_limiting import LoginRateLimiter
from recursos_premium import exigir_esquema as exigir_premium, recursos_da_academia, validar_plano
from regionalizacao import preferencias_iniciais_academia
import aluno_auth
import aluno_ficha
import aluno_treinos
import aluno_evolucao
import quiosque
import lutas
import aluno_mensalidade
import desafios
import aluno_gerador
import app_aluno_publicacao
import aluno_catalogo_painel
from seguranca import (
    SECRET_KEY,
    criar_token,
    gerar_hash,
    somente_admin_plataforma,
    somente_dono,
    usuario_de_academia,
    usuario_atual,
    verificar_senha,
)
from sincronizacao import enfileirar_evento, outbox_ativa, sync_id_academia
from sync_protocol import SyncEvent
from sync_receiver import receber_evento

app = FastAPI(title="Frequency")
app.include_router(aluno_auth.router)
app.include_router(aluno_auth.router_painel)
app.include_router(aluno_ficha.router)
app.include_router(aluno_treinos.router)
app.include_router(aluno_evolucao.router)
app.include_router(quiosque.router)
app.include_router(lutas.router)
app.include_router(aluno_mensalidade.router)
app.include_router(desafios.router)
app.include_router(aluno_gerador.router)
app.include_router(app_aluno_publicacao.router)
app.include_router(aluno_catalogo_painel.router)
login_rate_limiter = LoginRateLimiter(SECRET_KEY)
backup_process: subprocess.Popen | None = None
sync_worker_thread: threading.Thread | None = None
sync_worker_start_lock = threading.Lock()
PASTA_BACKEND = Path(__file__).resolve().parent
PASTA_FRONTEND_PUBLICA = PASTA_BACKEND.parent / "frontend" / "public"
PASTA_FRONTEND = Path(
    os.getenv("FREQUENCY_FRONTEND_DIR", str(PASTA_FRONTEND_PUBLICA))
).resolve()
app.mount(
    "/static",
    StaticFiles(directory=PASTA_FRONTEND / "static"),
    name="static",
)


GOOGLE_OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_OAUTH_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


def _email_verificacao_config():
    host = os.getenv("FREQUENCY_SMTP_HOST", "").strip()
    user = os.getenv("FREQUENCY_SMTP_USER", "").strip()
    password = os.getenv("FREQUENCY_SMTP_PASSWORD", "")
    remetente = os.getenv("FREQUENCY_SMTP_FROM", user).strip()
    if not host or not user or not password or not remetente:
        return None
    try:
        port = int(os.getenv("FREQUENCY_SMTP_PORT", "465"))
    except ValueError:
        return None
    return host, port, user, password, remetente


def _criar_token_verificacao():
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()


def _enviar_email_verificacao(email: str, nome: str, token: str):
    config = _email_verificacao_config()
    if config is None:
        return False
    base_url = os.getenv("FREQUENCY_PUBLIC_URL", "https://frequencygym.tech").rstrip("/")
    link = f"{base_url}/verificar-email?token={urllib.parse.quote(token)}"
    mensagem = EmailMessage()
    mensagem["Subject"] = "Confirme seu e-mail — Frequency Gym"
    mensagem["From"] = formataddr(("Frequency Gym", config[4]))
    mensagem["To"] = email
    mensagem.set_content(
        f"Olá, {nome}!\n\nConfirme seu e-mail para ativar sua conta do Frequency Gym:\n{link}\n\n"
        "Este link expira em 24 horas. Se você não criou esta conta, ignore esta mensagem."
    )
    try:
        with smtplib.SMTP_SSL(config[0], config[1], timeout=15) as servidor:
            servidor.login(config[2], config[3])
            servidor.send_message(mensagem)
        return True
    except (OSError, smtplib.SMTPException):
        return False


def _google_oauth_config():
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv(
        "GOOGLE_OAUTH_REDIRECT_URI", "https://frequencygym.tech/auth/google/callback"
    ).strip()
    if not client_id or not client_secret or not redirect_uri:
        return None
    return client_id, client_secret, redirect_uri


def _google_state(flow: str, usuario_id: int | None = None) -> str:
    # O fluxo faz parte da assinatura. Mantê-lo explícito evita que o callback
    # de Gmail seja confundido com login comum e rejeitado depois do consentimento.
    fluxos_validos = {"login", "signup", "gmail", "gmail_platform", "gmail_prospeccao"}
    payload = {
        "flow": flow if flow in fluxos_validos else "login",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp()),
        "nonce": secrets.token_urlsafe(24),
    }
    if usuario_id is not None:
        payload["usuario_id"] = int(usuario_id)
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    signature = hmac.new(
        SECRET_KEY.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{encoded}.{signature}"


def _read_google_state(value: str) -> dict:
    try:
        encoded, signature = value.split(".", 1)
        expected = hmac.new(
            SECRET_KEY.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("assinatura")
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
        )
        if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("expirado")
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="google_state_invalido") from exc


def _google_request(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="google_indisponivel") from exc


def _google_identity(token: str, client_id: str) -> dict:
    query = urllib.parse.urlencode({"id_token": token})
    request = urllib.request.Request(
        f"{GOOGLE_OAUTH_TOKENINFO_URL}?{query}", headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            identity = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="google_indisponivel") from exc
    if identity.get("aud") != client_id or identity.get("email_verified") != "true":
        raise HTTPException(status_code=401, detail="google_conta_nao_verificada")
    if not identity.get("sub") or not identity.get("email"):
        raise HTTPException(status_code=401, detail="google_identidade_invalida")
    return identity


def _google_userinfo(access_token: str) -> dict:
    request = urllib.request.Request(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            identity = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="google_indisponivel") from exc
    if not identity.get("email"):
        raise HTTPException(status_code=401, detail="google_identidade_invalida")
    return identity


def _gmail_oauth_config():
    config = _google_oauth_config()
    if config is None:
        return None
    client_id, client_secret, _redirect_uri = config
    redirect_uri = os.getenv(
        "GMAIL_OAUTH_REDIRECT_URI", "https://frequencygym.tech/auth/google/gmail/callback"
    ).strip()
    return client_id, client_secret, redirect_uri


def _gmail_crypto_key() -> str:
    # The database performs encryption; the application secret never leaves the
    # process and is required to decrypt a connection token.
    return SECRET_KEY


OAUTH_NONCE_COOKIE = "frequency_oauth_nonce"
OAUTH_FRIENDLY_ERRORS = {
    "google_state_invalido", "google_sessao_oauth_invalida", "google_callback_incompleto",
    "google_nao_configurado", "google_indisponivel", "google_conta_nao_verificada",
    "google_identidade_invalida", "gmail_autorizacao_incompleta", "sem_permissao",
}


def _oauth_cookie_secure(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def _bind_oauth_state(response: Response, request: Request, state: str) -> Response:
    """Tie the signed state to this browser so a link started by someone else
    cannot finish in the victim's browser (OAuth login/linking CSRF)."""
    encoded = state.split(".", 1)[0]
    payload = json.loads(base64.urlsafe_b64decode((encoded + "=" * (-len(encoded) % 4)).encode("ascii")))
    response.set_cookie(
        OAUTH_NONCE_COOKIE, payload["nonce"], max_age=600, path="/auth/google",
        httponly=True, secure=_oauth_cookie_secure(request), samesite="lax",
    )
    return response


def _check_oauth_browser(request: Request, state_data: dict) -> None:
    cookie = request.cookies.get(OAUTH_NONCE_COOKIE, "")
    if not cookie or not hmac.compare_digest(cookie, str(state_data.get("nonce", ""))):
        raise HTTPException(status_code=400, detail="google_sessao_oauth_invalida")


def _oauth_error_redirect(param: str, detail: object) -> RedirectResponse:
    code = detail if isinstance(detail, str) and detail in OAUTH_FRIENDLY_ERRORS else "google_falhou"
    response = RedirectResponse(f"/app?{param}={urllib.parse.quote(code)}")
    response.delete_cookie(OAUTH_NONCE_COOKIE, path="/auth/google")
    return response


@app.get("/auth/google/gmail/start")
def gmail_start(request: Request, format: str = Query(default="redirect"), alvo: str = Query(default="academia"), usuario=Depends(usuario_atual)):
    plataforma = alvo in {"plataforma", "prospeccao"}
    if plataforma:
        permitido = usuario["papel"] == "admin_plataforma"
    else:
        permitido = usuario["papel"] == "dono" and usuario.get("academia_id") is not None
    if not permitido:
        raise HTTPException(status_code=403, detail="sem_permissao")
    config = _gmail_oauth_config()
    if config is None:
        raise HTTPException(status_code=503, detail="google_nao_configurado")
    client_id, _client_secret, redirect_uri = config
    state = _google_state("gmail_prospeccao" if alvo == "prospeccao" else ("gmail_platform" if plataforma else "gmail"), usuario["id"])
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email https://www.googleapis.com/auth/gmail.send" if alvo == "prospeccao" else "openid email https://www.googleapis.com/auth/gmail.readonly",
        "state": state,
        "access_type": "offline",
        "prompt": "consent select_account",
    }
    url = f"{GOOGLE_OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    response = JSONResponse({"url": url}) if format == "json" else RedirectResponse(url)
    return _bind_oauth_state(response, request, state)


@app.get("/auth/google/gmail/callback")
def gmail_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        # Google returns short codes such as access_denied; never echo free text.
        return _oauth_error_redirect("gmail_error", "sem_permissao" if error == "access_denied" else "google_falhou")
    try:
        return _gmail_callback(request, code, state)
    except HTTPException as exc:
        return _oauth_error_redirect("gmail_error", exc.detail)


def _gmail_callback(request: Request, code: str | None, state: str | None) -> RedirectResponse:
    if not code or not state:
        raise HTTPException(status_code=400, detail="google_callback_incompleto")
    state_data = _read_google_state(state)
    _check_oauth_browser(request, state_data)
    usuario_id = state_data.get("usuario_id")
    if state_data.get("flow") not in {"gmail", "gmail_platform", "gmail_prospeccao"} or not usuario_id:
        raise HTTPException(status_code=400, detail="google_state_invalido")
    config = _gmail_oauth_config()
    if config is None:
        raise HTTPException(status_code=503, detail="google_nao_configurado")
    client_id, client_secret, redirect_uri = config
    token_data = _google_request(
        GOOGLE_OAUTH_TOKEN_URL,
        {"code": code, "client_id": client_id, "client_secret": client_secret,
         "redirect_uri": redirect_uri, "grant_type": "authorization_code"},
    )
    access_token = str(token_data.get("access_token") or "").strip()
    refresh_token = str(token_data.get("refresh_token") or "").strip()
    if not access_token or not refresh_token:
        raise HTTPException(status_code=502, detail="gmail_autorizacao_incompleta")
    identity = _google_identity(token_data.get("id_token", ""), client_id) if token_data.get("id_token") else _google_userinfo(access_token)
    expires_in = max(60, int(token_data.get("expires_in") or 3600))
    with get_connection() as conn:
        usuario = conn.execute(
            "SELECT id, academia_id, papel FROM public.usuarios WHERE id = %s AND ativo", (usuario_id,)
        ).fetchone()
        if usuario is None:
            raise HTTPException(status_code=403, detail="sem_permissao")
        if state_data.get("flow") in {"gmail_platform", "gmail_prospeccao"}:
            if usuario["papel"] != "admin_plataforma":
                raise HTTPException(status_code=403, detail="sem_permissao")
            conn.execute(
                "INSERT INTO public.gmail_plataforma_conexao "
                "(id, usuario_id, email, refresh_token, access_token, access_token_expira_em) "
                "VALUES (%s, %s, %s, pgp_sym_encrypt(%s, %s), pgp_sym_encrypt(%s, %s), CURRENT_TIMESTAMP + (%s * INTERVAL '1 second')) "
                "ON CONFLICT (id) DO UPDATE SET usuario_id = EXCLUDED.usuario_id, email = EXCLUDED.email, "
                "refresh_token = EXCLUDED.refresh_token, access_token = EXCLUDED.access_token, "
                "access_token_expira_em = EXCLUDED.access_token_expira_em, ativo = true, atualizado_em = CURRENT_TIMESTAMP",
                (2 if state_data.get("flow") == "gmail_prospeccao" else 1, usuario_id, identity["email"].strip().lower(), refresh_token, _gmail_crypto_key(), access_token, _gmail_crypto_key(), expires_in),
            )
        else:
            if usuario["papel"] != "dono" or usuario["academia_id"] is None:
                raise HTTPException(status_code=403, detail="sem_permissao")
            conn.execute(
                "INSERT INTO public.gmail_pagamento_conexoes "
                "(academia_id, usuario_id, email, refresh_token, access_token, access_token_expira_em) "
                "VALUES (%s, %s, %s, pgp_sym_encrypt(%s, %s), pgp_sym_encrypt(%s, %s), CURRENT_TIMESTAMP + (%s * INTERVAL '1 second')) "
                "ON CONFLICT (academia_id) DO UPDATE SET usuario_id = EXCLUDED.usuario_id, email = EXCLUDED.email, "
                "refresh_token = EXCLUDED.refresh_token, access_token = EXCLUDED.access_token, "
                "access_token_expira_em = EXCLUDED.access_token_expira_em, ativo = true, atualizado_em = CURRENT_TIMESTAMP",
                (usuario["academia_id"], usuario_id, identity["email"].strip().lower(), refresh_token, _gmail_crypto_key(), access_token, _gmail_crypto_key(), expires_in),
            )
    response = RedirectResponse("/app?gmail_connected=1")
    response.delete_cookie(OAUTH_NONCE_COOKIE, path="/auth/google")
    return response


@app.get("/auth/google/start")
def google_start(request: Request, flow: str = Query(default="login")):
    config = _google_oauth_config()
    if config is None:
        return _oauth_error_redirect("google_error", "google_nao_configurado")
    client_id, _client_secret, redirect_uri = config
    state = _google_state(flow)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "include_granted_scopes": "true",
        "prompt": "select_account",
    }
    return _bind_oauth_state(
        RedirectResponse(f"{GOOGLE_OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"), request, state
    )


@app.get("/auth/google/callback")
def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return _oauth_error_redirect("google_error", "sem_permissao" if error == "access_denied" else "google_falhou")
    try:
        return _google_callback(request, code, state)
    except HTTPException as exc:
        return _oauth_error_redirect("google_error", exc.detail)


def _google_callback(request: Request, code: str | None, state: str | None) -> RedirectResponse:
    if not code or not state:
        raise HTTPException(status_code=400, detail="google_callback_incompleto")
    state_data = _read_google_state(state)
    _check_oauth_browser(request, state_data)
    flow = state_data.get("flow", "login")
    config = _google_oauth_config()
    if config is None:
        raise HTTPException(status_code=503, detail="google_nao_configurado")
    client_id, client_secret, redirect_uri = config
    token_data = _google_request(
        GOOGLE_OAUTH_TOKEN_URL,
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    identity = _google_identity(token_data.get("id_token", ""), client_id)
    email = identity["email"].strip().lower()
    google_sub = identity["sub"]
    with get_connection() as conn:
        usuario = conn.execute(
            "SELECT u.id, u.nome, u.papel, u.academia_id FROM google_identities g "
            "JOIN usuarios u ON u.id = g.usuario_id WHERE g.google_sub = %s AND u.ativo",
            (google_sub,),
        ).fetchone()
        if usuario is None:
            usuario = conn.execute(
                "SELECT id, nome, papel, academia_id FROM usuarios WHERE lower(email) = %s AND ativo",
                (email,),
            ).fetchone()
            if usuario is not None:
                conn.execute(
                    "INSERT INTO google_identities (usuario_id, google_sub, email) VALUES (%s, %s, %s) "
                    "ON CONFLICT (usuario_id) DO UPDATE SET google_sub = EXCLUDED.google_sub, email = EXCLUDED.email",
                    (usuario["id"], google_sub, email),
                )
        if usuario is None:
            if flow == "signup":
                query = urllib.parse.urlencode(
                    {"cadastro": "1", "google_email": email, "google_name": identity.get("name", "")}
                )
                response = RedirectResponse(f"/app?{query}")
            else:
                response = RedirectResponse("/app?google_error=conta_nao_encontrada")
            response.delete_cookie(OAUTH_NONCE_COOKIE, path="/auth/google")
            return response
        token = criar_token(usuario)
    response = RedirectResponse(f"/app#google_token={urllib.parse.quote(token)}")
    response.delete_cookie(OAUTH_NONCE_COOKIE, path="/auth/google")
    return response


def esquema_de_moeda_disponivel(conn) -> bool:
    total = conn.execute(
        "SELECT count(*) AS total FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND "
        "((table_name = 'academias' AND column_name IN ('idioma', 'moeda')) "
        "OR (table_name IN ('planos', 'pagamentos') AND column_name = 'moeda'))"
    ).fetchone()["total"]
    return total == 4


@app.middleware("http")
async def headers_seguranca(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    if request.url.path in {"/integracoes", "/cameras", "/youtube"}:
        response.headers["Cache-Control"] = "no-store"
        # O player incorporado do YouTube exige um Referer para validar a
        # origem. Enviamos somente a origem (sem caminho ou dados da sessão).
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; form-action 'self'; "
            "frame-ancestors 'self'; object-src 'none'; "
            "style-src 'self'; connect-src 'self' https://www.googleapis.com; script-src 'self' https://www.youtube.com https://www.youtube-nocookie.com; frame-src https://www.youtube.com https://www.youtube-nocookie.com; "
            "img-src 'self' http: https:; media-src http: https:"
        )

    if request.url.path in {"/app", "/monitor", "/app-aluno/web", "/app-aluno/web/"} or request.url.path.startswith(("/static/", "/app-aluno/web/")):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'none'; object-src 'none'; script-src 'self'; "
            "style-src 'self'; connect-src 'self'; img-src 'self' data: blob:"
        )
    if request.url.path == "/app":
        # Meta Pixel: libera somente os domínios necessários na página /app.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'none'; object-src 'none'; "
            "script-src 'self' https://connect.facebook.net; "
            "style-src 'self'; connect-src 'self' https://www.facebook.com https://connect.facebook.net; "
            "img-src 'self' data: blob: https://www.facebook.com"
        )

    return response


chave_do_leitor = APIKeyHeader(
    name="X-Reader-Key",
    auto_error=False,
)
chave_do_monitor = APIKeyHeader(name="X-Monitor-Key", auto_error=False)
sessao_do_monitor = APIKeyHeader(name="X-Monitor-Session", auto_error=False)


def modo_somente_consulta() -> bool:
    return os.getenv("SYNC_MIRROR_READ_ONLY", "").strip().upper() == "YES"


def exigir_escrita_local() -> None:
    if modo_somente_consulta():
        raise HTTPException(status_code=403, detail="modo_somente_consulta")


def leitor_atual(chave: str | None = Depends(chave_do_leitor)):
    if not chave:
        raise HTTPException(
            status_code=401,
            detail="chave_do_leitor_ausente",
        )

    chave_hash = hashlib.sha256(
        chave.encode("utf-8")
    ).hexdigest()

    with get_connection() as conn:
        try:
            leitor = conn.execute(
                "SELECT l.id, l.academia_id, l.nome, l.tipo_integracao, l.endpoint_url, l.metodo_http, l.configuracao "
                "FROM leitores l JOIN academias a ON a.id = l.academia_id "
                "WHERE l.chave_hash = %s AND l.ativo AND a.ativa IS TRUE",
                (chave_hash,),
            ).fetchone()
        except errors.UndefinedColumn:
            leitor = None

    if leitor is None:
        raise HTTPException(
            status_code=401,
            detail="chave_do_leitor_invalida",
        )

    return leitor

class PedidoAcesso(BaseModel):
    id_biometria: int


class PedidoAcessoFacial(BaseModel):
    foto_base64: str = Field(min_length=1, max_length=1_000_000)
    
class StatusAcademia(BaseModel):
    ativa: bool


class ConfiguracaoBackup(BaseModel):
    destino: str = Field(min_length=1, max_length=500)


class CodigoVinculoSync(BaseModel):
    codigo: str = Field(min_length=8, max_length=32)


class ConclusaoVinculoSync(BaseModel):
    codigo: str = Field(min_length=8, max_length=32)
    source_academia_sync_id: UUID


class LocalizacaoAcademia(BaseModel):
    pais: str = Field(pattern=r"^(Brasil|Bolivia)$")
    cidade: str = Field(default="", max_length=120)
    estado: str = Field(default="", max_length=120)
    endereco: str = Field(default="", max_length=300)
    codigo_postal: str = Field(default="", max_length=30)


def exigir_localizacao(conn):
    presente = conn.execute(
        "SELECT count(*) = 4 AS presente FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'academias' "
        "AND column_name IN ('cidade', 'estado', 'endereco', 'codigo_postal')"
    ).fetchone()["presente"]
    if not presente:
        raise HTTPException(503, "migracao_localizacao_pendente")


@app.get("/academia/preferencias")
def ler_localizacao(dono=Depends(somente_dono)):
    with get_connection() as conn:
        exigir_localizacao(conn)
        return conn.execute(
            "SELECT pais, cidade, estado, endereco, codigo_postal, moeda FROM academias WHERE id = %s",
            (dono["academia_id"],),
        ).fetchone()


@app.patch("/academia/preferencias")
def salvar_localizacao(dados: LocalizacaoAcademia, dono=Depends(somente_dono)):
    exigir_escrita_local()
    idioma, moeda = preferencias_iniciais_academia(dados.pais)
    with get_connection() as conn:
        exigir_localizacao(conn)
        return conn.execute(
            "UPDATE academias SET pais = %s, cidade = %s, estado = %s, endereco = %s, "
            "codigo_postal = %s, idioma = %s, moeda = %s WHERE id = %s "
            "RETURNING pais, cidade, estado, endereco, codigo_postal, moeda",
            (dados.pais, dados.cidade.strip(), dados.estado.strip(), dados.endereco.strip(),
             dados.codigo_postal.strip(), idioma, moeda, dono["academia_id"]),
        ).fetchone()

class NovoRecepcionista(BaseModel):
    nome: str = Field(max_length=160)
    email: str = Field(max_length=254)
    senha: str = Field(max_length=256)


class AlteracaoSenha(BaseModel):
    senha_atual: str = Field(min_length=1, max_length=256)
    nova_senha: str = Field(min_length=8, max_length=256)


class StatusRecepcionista(BaseModel):
    ativo: bool

@app.get("/")
def raiz():
    return FileResponse(PASTA_FRONTEND / "site.html")


@app.post("/analytics/visit", include_in_schema=False)
def registrar_visita_site():
    """Count one privacy-preserving visit per browser session/day."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO public.site_visitas_diarias (dia, visitas, atualizado_em) "
            "VALUES (CURRENT_DATE, 1, CURRENT_TIMESTAMP) "
            "ON CONFLICT (dia) DO UPDATE SET visitas = site_visitas_diarias.visitas + 1, atualizado_em = CURRENT_TIMESTAMP"
        )
    return {"registrado": True}


@app.get("/admin/site-analytics")
def ler_analytics_site(admin=Depends(somente_admin_plataforma)):
    with get_connection() as conn:
        total = conn.execute("SELECT COALESCE(SUM(visitas), 0) AS total FROM public.site_visitas_diarias").fetchone()
        hoje = conn.execute("SELECT COALESCE(visitas, 0) AS visitas FROM public.site_visitas_diarias WHERE dia = CURRENT_DATE").fetchone()
        ultimos = conn.execute(
            "SELECT dia, visitas FROM public.site_visitas_diarias "
            "WHERE dia >= CURRENT_DATE - INTERVAL '29 days' ORDER BY dia"
        ).fetchall()
    return {"total": int(total["total"]), "hoje": int(hoje["visitas"] if hoje else 0), "ultimos_30_dias": ultimos}


@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    return FileResponse(PASTA_FRONTEND / "robots.txt", media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    return FileResponse(PASTA_FRONTEND / "sitemap.xml", media_type="application/xml")


@app.get("/privacidade", include_in_schema=False)
def pagina_privacidade():
    return FileResponse(PASTA_FRONTEND / "privacidade.html")

@app.get("/manual", include_in_schema=False)
def pagina_manual():
    return FileResponse(PASTA_FRONTEND / "manual.html")


@app.get("/termos", include_in_schema=False)
def pagina_termos():
    return FileResponse(PASTA_FRONTEND / "termos.html")


@app.get("/config")
def configuracao_publica():
    return {"somente_consulta": modo_somente_consulta()}


def _atualizar_env_local(nome: str, valor: str) -> None:
    """Update one local deployment setting without exposing other secrets."""
    env_path = PASTA_BACKEND / ".env"
    linhas = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    prefixo = f"{nome}="
    substituido = False
    resultado = []
    for linha in linhas:
        if linha.startswith(prefixo):
            resultado.append(f"{prefixo}{valor}")
            substituido = True
        else:
            resultado.append(linha)
    if not substituido:
        resultado.append(f"{prefixo}{valor}")
    temporario = env_path.with_suffix(".tmp")
    temporario.write_text("\n".join(resultado) + "\n", encoding="utf-8")
    temporario.replace(env_path)
    os.environ[nome] = valor


def _frequency_public_base_url() -> str:
    """Return the public HTTPS origin used by local pairing."""
    value = (
        os.getenv("FREQUENCY_PUBLIC_URL", "").strip()
        or os.getenv("PAYMENT_PUBLIC_BASE_URL", "").strip()
    ).rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(status_code=503, detail="url_publica_frequency_nao_configurada")
    return value


def _normalizar_codigo_vinculo(value: str) -> str:
    return "".join(value.upper().split()).replace("-", "")


def _iniciar_sync_worker_se_configurado() -> bool:
    """Start one in-process worker for a paired local installation."""
    global sync_worker_thread
    if os.getenv("SYNC_WORKER_ENABLED", "").strip().upper() != "YES":
        return False
    if os.getenv("SYNC_OUTBOX_ENABLED", "").strip().upper() != "YES":
        return False
    with sync_worker_start_lock:
        if sync_worker_thread is not None and sync_worker_thread.is_alive():
            return True

        def run_worker() -> None:
            try:
                from sync_worker import executar

                executar()
            except Exception:
                # The local API remains available when the network is down or
                # pairing is incomplete; the outbox keeps events for retry.
                return

        sync_worker_thread = threading.Thread(
            target=run_worker,
            name="frequency-sync-worker",
            daemon=True,
        )
        sync_worker_thread.start()
        return True


def _sync_worker_status() -> str:
    if os.getenv("SYNC_WORKER_ENABLED", "").strip().upper() != "YES":
        return "desativado"
    if sync_worker_thread is None:
        return "aguardando"
    return "enviando" if sync_worker_thread.is_alive() else "parado_com_retentativa"
@app.post("/sync/pairing/start")
def iniciar_vinculo_sync(dono=Depends(somente_dono)):
    if os.getenv("SYNC_RECEIVER_ENABLED", "").strip().upper() != "YES":
        raise HTTPException(503, "vinculo_nuvem_desabilitado")
    codigo = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(12))
    expira = datetime.now(timezone.utc) + timedelta(minutes=15)
    with get_connection() as conn:
        conn.execute("UPDATE sync_pairing_codes SET used_at = now() WHERE academia_id = %s AND used_at IS NULL", (dono["academia_id"],))
        conn.execute("INSERT INTO sync_pairing_codes (academia_id, code_hash, expires_at) VALUES (%s, %s, %s)", (dono["academia_id"], hashlib.sha256(codigo.encode()).hexdigest(), expira))
    return {"codigo": codigo, "expira_em": expira.isoformat(), "validade_minutos": 15}

@app.post("/sync/pairing/complete")
def concluir_vinculo_sync(dados: ConclusaoVinculoSync):
    if os.getenv("SYNC_RECEIVER_ENABLED", "").strip().upper() != "YES":
        raise HTTPException(503, "vinculo_nuvem_desabilitado")
    codigo = _normalizar_codigo_vinculo(dados.codigo)
    if not re.fullmatch(r"[A-Z2-9]{12}", codigo):
        raise HTTPException(400, "codigo_vinculo_invalido")
    remote_url = _frequency_public_base_url() + "/sync/receber"
    token = secrets.token_urlsafe(48)
    with get_connection() as conn:
        row = conn.execute("SELECT id, academia_id, expires_at, used_at FROM sync_pairing_codes WHERE code_hash = %s FOR UPDATE", (hashlib.sha256(codigo.encode()).hexdigest(),)).fetchone()
        if row is None or row["used_at"] is not None or row["expires_at"] <= datetime.now(timezone.utc):
            raise HTTPException(410, "codigo_vinculo_expirado_ou_invalido")
        if conn.execute("SELECT 1 FROM sync_credentials WHERE academia_id = %s OR source_academia_sync_id = %s LIMIT 1", (row["academia_id"], dados.source_academia_sync_id)).fetchone():
            raise HTTPException(409, "academia_ja_vinculada")
        conn.execute("INSERT INTO sync_credentials (academia_id, source_academia_sync_id, token_hash) VALUES (%s, %s, %s)", (row["academia_id"], dados.source_academia_sync_id, hashlib.sha256(token.encode()).hexdigest()))
        conn.execute("UPDATE sync_pairing_codes SET used_at = now() WHERE id = %s", (row["id"],))
    return {"token": token, "remote_url": remote_url, "academia_id": row["academia_id"]}

@app.post("/sync/conectar")
def conectar_instalacao_local(dados: CodigoVinculoSync, dono=Depends(somente_dono)):
    if os.getenv("FREQUENCY_INSTALLATION_MODE", "local").strip().lower() != "local":
        raise HTTPException(409, "instalacao_nao_local")
    base = (os.getenv("SYNC_CLOUD_BASE_URL", "").strip() or os.getenv("FREQUENCY_PUBLIC_URL", "").strip()).rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise HTTPException(503, "url_nuvem_frequency_nao_configurada")
    with get_connection() as conn:
        source_id = sync_id_academia(conn, dono["academia_id"])
        snapshot = conn.execute("SELECT 1 FROM sync_outbox WHERE academia_id = %s AND entity_type = 'snapshot' LIMIT 1", (dono["academia_id"],)).fetchone()
    if not snapshot:
        _atualizar_env_local("SYNC_OUTBOX_ENABLED", "YES")
        try:
            from criar_snapshot_sync import enfileirar_snapshot
            enfileirar_snapshot(dono["academia_id"])
        except Exception as exc:
            raise HTTPException(503, "snapshot_local_nao_preparado") from exc
    request = urllib.request.Request(base + "/sync/pairing/complete", data=json.dumps({"codigo": _normalizar_codigo_vinculo(dados.codigo), "source_academia_sync_id": str(source_id)}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            remoto = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise HTTPException(exc.code if exc.code in {409, 410} else 502, "vinculo_frequency_recusado") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(502, "nuvem_frequency_indisponivel") from exc
    if not remoto.get("token") or not remoto.get("remote_url"):
        raise HTTPException(502, "resposta_vinculo_invalida")
    _atualizar_env_local("SYNC_LOCAL_ACADEMY_ID", str(dono["academia_id"]))
    _atualizar_env_local("SYNC_REMOTE_URL", remoto["remote_url"])
    _atualizar_env_local("SYNC_REMOTE_TOKEN", remoto["token"])
    _atualizar_env_local("SYNC_WORKER_ENABLED", "YES")
    return {"vinculado": True, "snapshot_preparado": True, "worker": _iniciar_sync_worker_se_configurado()}



def _detectar_google_drive(user_root: str) -> Path | None:
    """Find a Google Drive for desktop mount without changing the local default."""
    configured = os.getenv("GOOGLE_DRIVE_DIR", "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())
    if user_root:
        home = Path(user_root)
        candidates.extend((home / "Google Drive", home / "Google Drive" / "My Drive", home / "Google Drive" / "Meu Drive"))
    if os.name == "nt":
        for code in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            candidates.extend((Path(f"{code}:/My Drive"), Path(f"{code}:/Meu Drive"), Path(f"{code}:/Google Drive")))
            # Google Drive for desktop can mount the drive root directly
            # (the marker is present even when the localized folder name differs).
            marker_root = Path(f"{code}:/")
            if (marker_root / ".shortcut-targets-by-id").is_dir():
                candidates.append(marker_root)
    for candidate in candidates:
        try:
            if candidate.is_dir():
                return candidate.resolve()
        except OSError:
            continue
    return None


def instalacao_local() -> bool:
    return os.getenv("FREQUENCY_INSTALLATION_MODE", "local").strip().lower() == "local"


def exigir_operador_da_instalacao(usuario: dict) -> None:
    """Backups and server paths belong to whoever operates this installation.

    On a local install the academy owner is the operator. On the shared cloud
    server the database holds every academy, so only the platform admin may
    configure, start or download a backup; an owner would otherwise receive a
    dump that also contains other academies.
    """
    if usuario["papel"] == "admin_plataforma":
        return
    if usuario["papel"] == "dono" and instalacao_local():
        return
    if usuario["papel"] == "dono":
        raise HTTPException(status_code=403, detail="backup_gerenciado_pela_plataforma")
    raise HTTPException(status_code=403, detail="sem_permissao")


@app.get("/operacao/backup-config")
def ler_configuracao_backup(usuario=Depends(usuario_atual)):
    exigir_operador_da_instalacao(usuario)
    user_root = os.getenv("USERPROFILE", "").strip()
    suggested = (Path(user_root) / "Frequency Backups") if user_root else None
    google_drive_path = _detectar_google_drive(user_root)
    configured = os.getenv("BACKUP_LOCAL_DIR", "").strip()
    return {
        "provedor": os.getenv("BACKUP_STORAGE_PROVIDER", "local").strip().lower(),
        "destino": configured or (str(suggested) if suggested else ""),
        "destino_configurado": bool(configured),
        "seletor_pasta_disponivel": os.name == "nt",
        "nuvem": {"google_drive": {"disponivel": bool(google_drive_path and google_drive_path.is_dir()), "configurado": bool(google_drive_path and google_drive_path.is_dir()), "destino": str(google_drive_path / "Frequency Backups") if google_drive_path else ""}},
    }


@app.put("/operacao/backup-config")
def salvar_configuracao_backup(dados: ConfiguracaoBackup, usuario=Depends(usuario_atual)):
    exigir_operador_da_instalacao(usuario)
    exigir_escrita_local()
    caminho = Path(dados.destino.strip()).expanduser()
    if not caminho.is_absolute():
        raise HTTPException(status_code=422, detail="destino_deve_ser_absoluto")
    try:
        caminho.mkdir(parents=True, exist_ok=True)
        teste = caminho / ".frequency-backup-write-check"
        teste.write_text("ok", encoding="utf-8")
        teste.unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=422, detail="destino_sem_permissao") from exc
    _atualizar_env_local("BACKUP_LOCAL_DIR", str(caminho))
    _atualizar_env_local("BACKUP_STORAGE_PROVIDER", "local")
    _atualizar_env_local("BACKUP_ENABLE", "YES")
    return {"salvo": True, "provedor": "local", "destino": str(caminho)}


@app.post("/operacao/backup-selecionar-pasta")
def selecionar_pasta_backup(usuario=Depends(usuario_atual)):
    """Open the native folder picker on the computer hosting Frequency."""
    exigir_operador_da_instalacao(usuario)
    if os.name != "nt":
        raise HTTPException(status_code=501, detail="seletor_de_pasta_indisponivel")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d=New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$d.Description='Escolha a pasta dos backups do Frequency'; "
        "$d.ShowNewFolderButton=$true; "
        "if($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){[Console]::Write($d.SelectedPath)}"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
            capture_output=True, text=True, timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=503, detail="seletor_de_pasta_indisponivel") from exc
    destino = result.stdout.strip()
    if not destino:
        return {"selecionado": False, "destino": ""}
    return {"selecionado": True, "destino": destino}


def _status_backup_operacao() -> dict[str, object]:
    """Read only the operator-safe fields written by the backup job."""
    enabled = os.getenv("BACKUP_ENABLE", "").strip().upper() == "YES"
    if not enabled:
        return {"ativado": False, "agendamento_diario": False, "provedor": "desativado", "status": "desativado", "ultima_execucao": None}
    em_execucao = bool(backup_process and backup_process.poll() is None)

    configured = os.getenv("BACKUP_STATUS_FILE", "").strip()
    status_path = Path(configured).expanduser().resolve() if configured else PASTA_BACKEND / ".backups" / "frequency-backup-status.json"
    try:
        value = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ativado": True, "agendamento_diario": True, "provedor": os.getenv("BACKUP_STORAGE_PROVIDER", "s3").strip().lower(), "em_execucao": em_execucao, "status": "nunca_executado", "ultima_execucao": None}
    if not isinstance(value, dict):
        return {"ativado": True, "agendamento_diario": True, "provedor": os.getenv("BACKUP_STORAGE_PROVIDER", "s3").strip().lower(), "em_execucao": em_execucao, "status": "indisponivel", "ultima_execucao": None}

    allowed = {"sucesso", "falha", "desativado"}
    status = value.get("status")
    if status not in allowed:
        status = "indisponivel"
    result: dict[str, object] = {
        "ativado": True,
        "agendamento_diario": True,
        "provedor": os.getenv("BACKUP_STORAGE_PROVIDER", "s3").strip().lower(),
        "em_execucao": em_execucao,
        "status": status,
        "ultima_execucao": value.get("finished_at") if isinstance(value.get("finished_at"), str) else None,
    }
    for source, target in (("uploaded", "arquivos_enviados"), ("pending", "arquivos_pendentes")):
        if isinstance(value.get(source), int) and value[source] >= 0:
            result[target] = value[source]
    if isinstance(value.get("message"), str):
        result["mensagem"] = value["message"][:240]
    return result


@app.get("/operacao/status")
def status_operacao(usuario=Depends(usuario_atual)):
    if usuario["papel"] not in {"admin_plataforma", "dono"}:
        raise HTTPException(status_code=403, detail="sem_permissao")
    if usuario["papel"] == "dono" and not instalacao_local():
        # The shared server's worker, receiver and backup files are platform
        # operations; an owner only needs to know that backups are managed.
        return {
            "banco": "conectado",
            "frontend": "disponivel",
            "sincronizacao": {"instalacao": "cloud", "envio_ativado": False},
            "backup": {"ativado": True, "provedor": "plataforma", "status": "gerenciado_pela_plataforma", "agendamento_diario": True, "ultima_execucao": None},
        }
    return {
        "banco": "conectado",
        "frontend": "disponivel" if all((PASTA_FRONTEND / page).is_file() for page in ("index.html", "monitor.html")) else "incompleto",
        "sincronizacao": {
            "fila_ativada": os.getenv("SYNC_OUTBOX_ENABLED", "").strip().upper() == "YES",
            "envio_ativado": os.getenv("SYNC_WORKER_ENABLED", "").strip().upper() == "YES",
            "instalacao": os.getenv("FREQUENCY_INSTALLATION_MODE", "local").strip().lower(),
            "worker": _sync_worker_status(),
            "receptor_ativado": os.getenv("SYNC_RECEIVER_ENABLED", "").strip().upper() == "YES",
        },
        "backup": _status_backup_operacao(),
    }


@app.post("/operacao/backup", status_code=202)
def iniciar_backup_manual(usuario=Depends(usuario_atual)):
    """Start the configured encrypted backup without blocking the web request."""
    global backup_process
    exigir_operador_da_instalacao(usuario)
    if os.getenv("BACKUP_ENABLE", "").strip().upper() != "YES":
        raise HTTPException(status_code=409, detail="backup_nao_configurado")
    if backup_process and backup_process.poll() is None:
        raise HTTPException(status_code=409, detail="backup_em_andamento")
    try:
        backup_process = subprocess.Popen(
            [sys.executable, "-m", "ops.backup_postgres"],
            cwd=PASTA_BACKEND,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        raise HTTPException(status_code=503, detail="backup_indisponivel") from exc
    return {"iniciado": True, "agendamento_diario": True}



def _latest_backup_archive() -> Path | None:
    """Find the newest encrypted archive without exposing backup configuration."""
    configured = os.getenv("BACKUP_LOCAL_DIR", "").strip()
    if configured:
        directory = Path(configured).expanduser().resolve()
    else:
        user_root = os.getenv("USERPROFILE", "").strip()
        directory = (Path(user_root) / "Frequency Backups").resolve() if user_root else PASTA_BACKEND / ".backups"
    try:
        candidates = [
            path for path in directory.glob("frequency_*.dump.age")
            if re.fullmatch(r"frequency_\d{8}T\d{6}Z\.dump\.age", path.name) and path.is_file()
        ]
        return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None
    except OSError:
        return None

@app.get("/operacao/backup/download")
def baixar_ultimo_backup(usuario=Depends(usuario_atual)):
    """Download the latest encrypted archive to any device using the browser."""
    exigir_operador_da_instalacao(usuario)
    archive = _latest_backup_archive()
    if archive is None:
        raise HTTPException(status_code=404, detail="backup_nao_encontrado")
    return FileResponse(
        archive,
        media_type="application/octet-stream",
        filename=archive.name,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )

@app.get("/app", include_in_schema=False)
def interface_web():
    return FileResponse(PASTA_FRONTEND / "index.html")


@app.get("/monitor", include_in_schema=False)
def tela_monitor():
    return FileResponse(PASTA_FRONTEND / "monitor.html")


@app.get("/frequency.webmanifest", include_in_schema=False)
def manifest_frequency():
    return FileResponse(PASTA_FRONTEND / "frequency.webmanifest", media_type="application/manifest+json")


@app.get("/monitor.webmanifest", include_in_schema=False)
def manifest_monitor():
    return FileResponse(PASTA_FRONTEND / "monitor.webmanifest", media_type="application/manifest+json")


@app.get("/service-worker.js", include_in_schema=False)
def service_worker():
    return FileResponse(PASTA_FRONTEND / "service-worker.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/offline.html", include_in_schema=False)
def interface_offline():
    return FileResponse(PASTA_FRONTEND / "offline.html")


INSTALLER_DOWNLOADS = {"FrequencyGym-1.0.001-Setup.exe", "FrequencyGym-1.0.001-Setup.zip"}
INSTALLER_TICKET_SECONDS = 300


def _installer_ticket(filename: str, expires: int) -> str:
    message = f"installer-download:{filename}:{expires}".encode("utf-8")
    return hmac.new(SECRET_KEY.encode("utf-8"), message, hashlib.sha256).hexdigest()


@app.post("/downloads/{filename}/link", include_in_schema=False)
def link_download_instalador(filename: str, usuario=Depends(usuario_atual)):
    """Short-lived signed link: a plain <a href> cannot send the Bearer token,
    so the browser downloads the large installer natively with this ticket."""
    if usuario["papel"] != "admin_plataforma":
        raise HTTPException(status_code=403, detail="sem_permissao")
    if filename not in INSTALLER_DOWNLOADS or not (PASTA_FRONTEND / "downloads" / filename).is_file():
        raise HTTPException(status_code=404, detail="arquivo_nao_encontrado")
    expires = int(datetime.now(timezone.utc).timestamp()) + INSTALLER_TICKET_SECONDS
    query = urllib.parse.urlencode({"expira": expires, "ticket": _installer_ticket(filename, expires)})
    return {"url": f"/downloads/{urllib.parse.quote(filename)}?{query}", "validade_segundos": INSTALLER_TICKET_SECONDS}


@app.get("/downloads/{filename}", include_in_schema=False)
def download_public_installer(
    filename: str,
    expira: int | None = Query(default=None),
    ticket: str | None = Query(default=None, max_length=128),
):
    """Serve the Windows installer only through a link signed for the platform admin."""
    if filename not in INSTALLER_DOWNLOADS:
        raise HTTPException(status_code=404, detail="arquivo_nao_encontrado")
    agora = int(datetime.now(timezone.utc).timestamp())
    if (
        expira is None or not ticket or expira < agora
        or expira > agora + INSTALLER_TICKET_SECONDS
        or not hmac.compare_digest(ticket, _installer_ticket(filename, expira))
    ):
        raise HTTPException(status_code=403, detail="link_download_expirado")
    path = PASTA_FRONTEND / "downloads" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="arquivo_nao_encontrado")
    media_type = "application/vnd.microsoft.portable-executable" if filename.endswith(".exe") else "application/zip"
    return FileResponse(path, media_type=media_type, filename=filename, headers={"Cache-Control": "private, no-store"})


@app.get("/integracoes", include_in_schema=False)
def tela_integracoes():
    return RedirectResponse("/cameras", status_code=307)


@app.get("/cameras", include_in_schema=False)
def tela_cameras():
    return FileResponse(PASTA_FRONTEND / "cameras.html")


@app.get("/youtube", include_in_schema=False)
def tela_youtube():
    return FileResponse(PASTA_FRONTEND / "youtube.html")


@app.get("/spotify", include_in_schema=False)
def redirecionar_spotify_antigo():
    return RedirectResponse("/youtube", status_code=307)


@app.get("/alunos/situacao")
def situacao_alunos(usuario=Depends(usuario_de_academia)):
    with get_connection() as conn:
        linhas = conn.execute(
            "SELECT s.nome, s.status_aluno, s.dias_restantes, s.alerta "
            "FROM situacao_alunos s "
            "JOIN alunos a ON a.id = s.aluno_id "
            "WHERE a.academia_id = %s "
            "ORDER BY s.aluno_id",
            (usuario["academia_id"],),
        ).fetchall()
    return linhas


def processar_acesso(
    id_biometria: int | None,
    leitor: dict,
    *,
    metodo: str,
    confianca: float | None = None,
    motivo_desconhecido: str = "digital_nao_cadastrada",
):
    exigir_escrita_local()
    academia_id = leitor["academia_id"]
    leitor_id = leitor.get("id")
    monitor_id = leitor.get("monitor_id")
    monitor_session_id = leitor.get("monitor_session_id")

    with get_connection() as conn:
        academia = conn.execute(
            "SELECT ativa FROM academias WHERE id = %s FOR SHARE",
            (academia_id,),
        ).fetchone()

        if academia is None or not academia["ativa"]:
            raise HTTPException(
                status_code=403,
                detail="academia_inativa",
            )

        estado_saas = estado_assinatura_frequency(conn, academia_id)

        if outbox_ativa():
            aluno = conn.execute(
                "SELECT a.id, a.sync_id AS aluno_sync_id, a.nome, a.status, a.plano_id, "
                "s.dias_restantes, s.proximo_vencimento, s.alerta "
                "FROM alunos a "
                "JOIN situacao_alunos s ON s.aluno_id = a.id "
                "WHERE a.academia_id = %s AND a.id_biometria = %s",
                (academia_id, id_biometria),
            ).fetchone()
        else:
            aluno = conn.execute(
                "SELECT a.id, a.nome, a.status, a.plano_id, "
                "s.dias_restantes, s.proximo_vencimento, s.alerta "
                "FROM alunos a "
                "JOIN situacao_alunos s ON s.aluno_id = a.id "
                "WHERE a.academia_id = %s AND a.id_biometria = %s",
                (academia_id, id_biometria),
            ).fetchone()

        if aluno is None:
            liberado, motivo = False, motivo_desconhecido
        elif aluno["status"] != "ativo":
            liberado, motivo = False, "aluno_inativo"
        elif aluno["plano_id"] is None:
            liberado, motivo = False, "plano_nao_cadastrado"
        elif aluno["proximo_vencimento"] is None:
            liberado, motivo = False, "sem_pagamento_em_aberto"
        elif aluno["alerta"] == "atrasado":
            liberado, motivo = False, "mensalidade_atrasada"
        else:
            liberado, motivo = True, None

        if estado_saas["bloqueada_frequency"]:
            liberado, motivo = False, "assinatura_frequency_bloqueada"

        repetido = False
        if metodo == "facial" and aluno is not None:
            repetido = conn.execute(
                "SELECT 1 FROM presencas "
                "WHERE academia_id = %s AND aluno_id = %s "
                "AND leitor_id IS NOT DISTINCT FROM %s "
                "AND monitor_id IS NOT DISTINCT FROM %s "
                "AND monitor_session_id IS NOT DISTINCT FROM %s "
                "AND metodo_identificacao = 'facial' "
                "AND data_hora >= now() - interval '10 seconds' LIMIT 1",
                (academia_id, aluno["id"], leitor_id, monitor_id, monitor_session_id),
            ).fetchone() is not None

        if outbox_ativa() and not repetido:
            presenca = conn.execute(
                "INSERT INTO presencas "
                "(academia_id, aluno_id, liberado, motivo, leitor_id, monitor_id, monitor_session_id, metodo_identificacao, confianca) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING sync_id, data_hora",
                (
                    academia_id,
                    aluno["id"] if aluno else None,
                    liberado,
                    motivo,
                    leitor_id,
                    monitor_id,
                    monitor_session_id,
                    metodo,
                    confianca,
                ),
            ).fetchone()
            enfileirar_evento(
                conn,
                academia_sync_id=sync_id_academia(conn, academia_id),
                entity_type="presenca",
                entity_sync_id=presenca["sync_id"],
                payload={
                    "id": str(presenca["sync_id"]),
                    "aluno_id": str(aluno["aluno_sync_id"]) if aluno else None,
                    "data_hora_local": presenca["data_hora"].isoformat(),
                    "liberado": liberado,
                    "motivo": motivo,
                },
            )
        elif not repetido:
            conn.execute(
                "INSERT INTO presencas "
                "(academia_id, aluno_id, liberado, motivo, leitor_id, monitor_id, monitor_session_id, metodo_identificacao, confianca) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    academia_id,
                    aluno["id"] if aluno else None,
                    liberado,
                    motivo,
                    leitor_id,
                    monitor_id,
                    monitor_session_id,
                    metodo,
                    confianca,
                ),
            )

    resultado = {
        "liberado": liberado,
        "motivo": motivo,
        "nome": aluno["nome"] if aluno else None,
        "dias_restantes": aluno["dias_restantes"] if aluno else None,
        "alerta": aluno["alerta"] if aluno else None,
        "repetido": repetido,
    }
    _notificar_adaptador_leitor(leitor, resultado)
    return resultado


def _notificar_adaptador_leitor(leitor: dict, resultado: dict) -> None:
    """Entrega a decisão ao adaptador do fabricante sem bloquear a autorização local.

    O leitor Frequency continua sendo a fonte de verdade. APIs de catraca podem
    receber o mesmo contrato JSON sem que o backend precise conhecer cada marca.
    Falhas de rede ficam registradas no log e não transformam uma entrada já
    autorizada em uma entrada inconsistente.
    """
    tipo = leitor.get("tipo_integracao")
    endpoint = leitor.get("endpoint_url")
    if tipo not in {"http_json", "webhook"} or not endpoint:
        return
    payload = json.dumps({
        "liberado": bool(resultado.get("liberado")),
        "motivo": resultado.get("motivo"),
        "nome": resultado.get("nome"),
        "dias_restantes": resultado.get("dias_restantes"),
    }).encode("utf-8")
    request = urllib.request.Request(endpoint, data=payload, method=leitor.get("metodo_http") or "POST")
    request.add_header("Content-Type", "application/json")
    configuracao = leitor.get("configuracao") or {}
    for nome, valor in (configuracao.get("headers") or {}).items():
        if isinstance(nome, str) and isinstance(valor, str) and nome.lower() not in {"host", "content-length"}:
            request.add_header(nome, valor)
    try:
        with urllib.request.urlopen(request, timeout=3):
            pass
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        warnings.warn(f"adaptador de leitor indisponível: {erro}", RuntimeWarning)


def origem_acesso_facial(
    chave_leitor: str | None = Depends(chave_do_leitor),
    chave_monitor: str | None = Depends(chave_do_monitor),
    sessao_monitor: str | None = Depends(sessao_do_monitor),
):
    if chave_leitor:
        return leitor_atual(chave_leitor)
    if chave_monitor:
        academia_monitor = monitor_atual(chave_monitor, sessao_monitor)
        chave_hash = hashlib.sha256(chave_monitor.encode("utf-8")).hexdigest()
        with get_connection() as conn:
            academia = {"id": academia_monitor["id"], "monitor_id": academia_monitor.get("monitor_id")}
            if academia is not None:
                leitor = conn.execute(
                    "SELECT id, academia_id, nome, tipo_integracao, endpoint_url, metodo_http, configuracao FROM leitores "
                    "WHERE academia_id = %s AND ativo IS TRUE ORDER BY id LIMIT 1",
                    (academia["id"],),
                ).fetchone()
                if leitor:
                    leitor["monitor_id"] = academia["monitor_id"]
                    leitor["monitor_session_id"] = academia_monitor.get("monitor_session_id")
                    return leitor
                return {
                    "id": None,
                    "academia_id": academia["id"],
                    "nome": "Câmera do monitor",
                    "monitor_id": academia["monitor_id"],
                    "monitor_session_id": academia_monitor.get("monitor_session_id"),
                }
        raise HTTPException(status_code=401, detail="chave_do_monitor_invalida")
    raise HTTPException(status_code=401, detail="chave_de_acesso_ausente")


@app.post("/acesso")
def verificar_acesso(
    pedido: PedidoAcesso,
    leitor=Depends(leitor_atual),
):
    return processar_acesso(pedido.id_biometria, leitor, metodo="biometria")


@app.post("/acesso/facial")
def verificar_acesso_facial(
    pedido: PedidoAcessoFacial,
    leitor=Depends(origem_acesso_facial),
):
    exigir_escrita_local()
    try:
        conteudo = base64.b64decode(pedido.foto_base64, validate=True)
        if len(conteudo) > 700_000:
            raise HTTPException(status_code=413, detail="foto_muito_grande")
        probe = embedding(conteudo)
    except (binascii.Error, ValueError) as erro:
        if isinstance(erro, FaceError):
            status = 503 if str(erro) in {
                "modelo_facial_nao_instalado", "modelo_facial_invalido",
                "motor_facial_nao_instalado",
            } else 422
            raise HTTPException(status_code=status, detail=str(erro)) from erro
        raise HTTPException(status_code=400, detail="foto_invalida") from erro

    with get_connection() as conn:
        perfis = conn.execute(
            "SELECT id_biometria, template FROM biometrias_faciais "
            "WHERE academia_id = %s AND modelo = %s",
            (leitor["academia_id"], MODEL_VERSION),
        ).fetchall()

    candidatos = sorted(
        (
            (similarity(bytes(perfil["template"]), probe), perfil["id_biometria"])
            for perfil in perfis
        ),
        reverse=True,
    )
    melhor = candidatos[0][0] if candidatos else 0.0
    segunda = candidatos[1][0] if len(candidatos) > 1 else 0.0
    try:
        limite = float(os.getenv("FREQUENCY_FACE_THRESHOLD", "0.45"))
    except ValueError:
        limite = 0.45
    if not 0.35 <= limite <= 0.80:
        limite = 0.45
    identificado = bool(candidatos and melhor >= limite and melhor - segunda >= 0.04)
    if not identificado:
        processar_acesso(
            None, leitor, metodo="facial",
            confianca=melhor if candidatos else None,
            motivo_desconhecido="rosto_nao_identificado",
        )
        return {
            "liberado": False,
            "motivo": "rosto_nao_identificado",
            "nome": None,
            "dias_restantes": None,
            "alerta": None,
            "repetido": False,
            "identificado": False,
            "confianca": round(melhor, 4) if candidatos else None,
        }
    resultado = processar_acesso(
        candidatos[0][1],
        leitor,
        metodo="facial",
        confianca=melhor if candidatos else None,
    )
    resultado.update({
        "identificado": identificado,
        "confianca": round(melhor, 4) if candidatos else None,
    })
    return resultado


class NovaAcademiaComDono(BaseModel):
    nome_academia: str = Field(max_length=160)
    pais: str = Field(max_length=80)
    plano_frequency_id: int | None = Field(default=None, gt=0)
    vencimento_frequency: date | None = None
    logo_monitor_base64: str | None = Field(default=None, max_length=7_000_000)
    logo_monitor_media_type: str | None = Field(default=None, max_length=50)
    nome_dono: str = Field(max_length=160)
    email_dono: str = Field(max_length=254)
    senha_dono: str = Field(max_length=256)
    # Optional for platform-created legacy academies; public signup still
    # requires a phone number through CadastroAcademiaPublico.
    telefone_dono: str = Field(default="", max_length=40)


class CadastroAcademiaPublico(BaseModel):
    nome_academia: str = Field(max_length=160)
    pais: str = Field(max_length=80)
    nome_dono: str = Field(max_length=160)
    email_dono: str = Field(max_length=254)
    senha_dono: str = Field(max_length=256)
    telefone_dono: str = Field(min_length=7, max_length=40)


def garantir_lead_cadastro_academia(
    conn,
    *,
    academia_id: int,
    nome_academia: str,
    pais: str,
    nome_dono: str,
    email: str,
    telefone: str,
) -> dict:
    """Create or refresh the commercial lead created by the public signup."""
    tabela = conn.execute(
        "SELECT to_regclass('public.leads_prospeccao') IS NOT NULL AS presente"
    ).fetchone()
    coluna = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'leads_prospeccao' "
        "AND column_name = 'academia_id'"
    ).fetchone()
    if not tabela or not tabela["presente"] or coluna is None:
        raise HTTPException(status_code=503, detail="migracao_lead_cadastro_pendente")

    lead = conn.execute(
        "SELECT id FROM public.leads_prospeccao "
        "WHERE academia_id = %s AND excluido_em IS NULL FOR UPDATE",
        (academia_id,),
    ).fetchone()
    observacoes = "Cadastro público da academia; experiência gratuita de 7 dias."
    if lead:
        return conn.execute(
            "UPDATE public.leads_prospeccao SET nome=%s, cidade=%s, telefone=%s, "
            "email=%s, observacoes=%s, atualizado_em=CURRENT_TIMESTAMP "
            "WHERE id=%s RETURNING id",
            (nome_academia, pais, telefone, email, observacoes, lead["id"]),
        ).fetchone()
    return conn.execute(
        "INSERT INTO public.leads_prospeccao "
        "(academia_id, nome, cidade, telefone, email, observacoes, prioridade, "
        "status_comercial, origem) VALUES (%s, %s, %s, %s, %s, %s, 'A', "
        "'interessado', 'cadastro_site') RETURNING id",
        (academia_id, nome_academia, pais, telefone, email, observacoes),
    ).fetchone()


class AtualizacaoAcademia(BaseModel):
    nome_academia: str | None = Field(default=None, min_length=1, max_length=160)
    pais: str | None = Field(default=None, min_length=1, max_length=80)
    cidade: str | None = Field(default=None, max_length=120)
    estado: str | None = Field(default=None, max_length=120)
    endereco: str | None = Field(default=None, max_length=300)
    codigo_postal: str | None = Field(default=None, max_length=30)
    telefone: str | None = Field(default=None, max_length=40)
    nome_dono: str | None = Field(default=None, min_length=1, max_length=160)
    email_dono: str | None = Field(default=None, min_length=3, max_length=254)

class NovoAluno(BaseModel):
    nome: str = Field(min_length=1, max_length=160)
    documento: str = Field(min_length=1, max_length=80)
    telefone: str | None = Field(default=None, max_length=40)
    bairro: str | None = Field(default=None, max_length=160)
    data_nascimento: date | None = None
    email: str | None = Field(default=None, max_length=254)
    plano_id: int | None = Field(default=None, gt=0)
    id_biometria: int | None = Field(default=None, gt=0)
    foto_base64: str | None = Field(default=None, max_length=7_000_000)
    foto_media_type: str | None = Field(default=None, max_length=50)
    fotos_rosto_base64: list[str] = Field(default_factory=list, max_length=5)
    consentimento_facial: bool = False

    @field_validator("fotos_rosto_base64")
    @classmethod
    def validar_amostras_faciais(cls, valores):
        if valores and not 3 <= len(valores) <= 5:
            raise ValueError("rosto_amostras_insuficientes")
        if any(not valor or len(valor) > 1_000_000 for valor in valores):
            raise ValueError("foto_muito_grande")
        return valores


class LogoMonitor(BaseModel):
    foto_base64: str = Field(min_length=1, max_length=7_000_000)
    foto_media_type: str = Field(min_length=1, max_length=50)


class AtualizacaoDadosAluno(BaseModel):
    documento: str | None = Field(default=None, max_length=80)
    telefone: str | None = Field(default=None, max_length=40)
    bairro: str | None = Field(default=None, max_length=160)
    data_nascimento: date | None = None
    foto_base64: str | None = Field(default=None, max_length=7_000_000)
    foto_media_type: str | None = Field(default=None, max_length=50)
    consentimento_foto: bool = False


class AtualizacaoPlanoAluno(BaseModel):
    plano_id: int = Field(gt=0)


class NovoPlano(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    valor: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    duracao_dias: int = Field(gt=0, le=3660)


class NovoPlanoFrequency(BaseModel):
    nome: str = Field(min_length=2, max_length=100)
    descricao: str = Field(default="", max_length=1000)
    valor: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    moeda: str = Field(pattern=r"^[A-Z]{3}$")
    duracao_dias: int = Field(gt=0, le=3660)
    nivel: str = Field(default="essencial", pattern=r"^(essencial|profissional|premium)$")
    cameras: bool = False
    youtube: bool = False
    max_monitores: int = Field(default=0, ge=0, le=1000)
    max_leitores: int = Field(default=0, ge=0, le=1000)
    max_alunos: int = Field(default=120, ge=1, le=1_000_000)


class AtualizacaoPlanoFrequency(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=100)
    descricao: str | None = Field(default=None, max_length=1000)
    valor: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    moeda: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    duracao_dias: int | None = Field(default=None, gt=0, le=3660)
    nivel: str | None = Field(default=None, pattern=r"^(essencial|profissional|premium)$")
    cameras: bool | None = None
    youtube: bool | None = None
    max_monitores: int | None = Field(default=None, ge=0, le=1000)
    max_leitores: int | None = Field(default=None, ge=0, le=1000)
    max_alunos: int | None = Field(default=None, ge=1, le=1_000_000)

    @field_validator("nome")
    @classmethod
    def validar_nome(cls, valor):
        if valor is None or len(valor.strip()) < 2:
            raise ValueError("nome_do_plano_obrigatorio")
        return valor.strip()


class NovaAssinaturaFrequency(BaseModel):
    academia_id: int = Field(gt=0)
    plano_id: int = Field(gt=0)
    vencimento: date


class ConfirmacaoFaturaFrequency(BaseModel):
    meio_pagamento: str = Field(min_length=2, max_length=80)
    referencia_pagamento: str | None = Field(default=None, max_length=160)
    observacao_admin: str = Field(default="", max_length=1000)


class CheckoutAssinaturaFrequency(BaseModel):
    """Dados mínimos do pagador exigidos pelo gateway boliviano."""

    documento: str = Field(min_length=5, max_length=20)

    @field_validator("documento")
    @classmethod
    def validar_documento(cls, valor):
        valor = valor.strip()
        if not valor:
            raise ValueError("documento_pagador_obrigatorio")
        return valor


class ConfiguracaoFrequency(BaseModel):
    contato_email: str | None = Field(default=None, max_length=254)
    contato_telefone: str | None = Field(default=None, max_length=40)


class ChaveMonitor(BaseModel):
    nome: str = Field(default="Monitor", min_length=1, max_length=120)
    renovar: bool = False


class ConfiguracaoLeitor(BaseModel):
    nome: str = Field(min_length=1, max_length=160)
    tipo_integracao: str = Field(default="api_key", pattern=r"^(api_key|http_json|webhook)$")
    endpoint_url: str | None = Field(default=None, max_length=500)
    metodo_http: str = Field(default="POST", pattern=r"^(POST|PUT|PATCH)$")
    configuracao: dict = Field(default_factory=dict)


class StatusPlanoFrequency(BaseModel):
    ativo: bool


class StatusAssinaturaFrequency(BaseModel):
    status: str = Field(pattern=r"^(ativa|suspensa|cancelada)$")


class AtualizacaoAssinaturaFrequency(BaseModel):
    plano_id: int | None = Field(default=None, gt=0)
    proximo_vencimento: date | None = None
    status: str | None = Field(default=None, pattern=r"^(ativa|suspensa|cancelada)$")


class CancelamentoFaturaFrequency(BaseModel):
    observacao_admin: str = Field(min_length=3, max_length=1000)


class NovoLeadProspeccao(BaseModel):
    nome: str = Field(min_length=2, max_length=160)
    cidade: str = Field(default="", max_length=120)
    endereco: str = Field(default="", max_length=300)
    telefone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=254)
    whatsapp_opt_in: bool = False
    site_instagram: str = Field(default="", max_length=500)
    avaliacao: Decimal | None = Field(default=None, ge=0, le=5, max_digits=2, decimal_places=1)
    observacoes: str = Field(default="", max_length=2000)
    prioridade: str = Field(default="C", pattern=r"^[ABC]$")
    status_comercial: str = Field(default="nao_contatado", pattern=r"^(nao_contatado|mensagem_enviada|respondeu|demonstracao|interessado|cliente|nao_interessado)$")
    ultimo_contato: date | None = None
    origem: str = Field(default="manual", pattern=r"^(manual|csv|osm|integracao_futura)$")

    @field_validator("nome")
    @classmethod
    def validar_nome_lead(cls, valor):
        valor = valor.strip()
        if len(valor) < 2:
            raise ValueError("nome_do_lead_obrigatorio")
        return valor


class AtualizacaoLeadProspeccao(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=160)
    cidade: str | None = Field(default=None, max_length=120)
    endereco: str | None = Field(default=None, max_length=300)
    telefone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=254)
    whatsapp_opt_in: bool | None = None
    site_instagram: str | None = Field(default=None, max_length=500)
    avaliacao: Decimal | None = Field(default=None, ge=0, le=5, max_digits=2, decimal_places=1)
    observacoes: str | None = Field(default=None, max_length=2000)
    prioridade: str | None = Field(default=None, pattern=r"^[ABC]$")
    status_comercial: str | None = Field(default=None, pattern=r"^(nao_contatado|mensagem_enviada|respondeu|demonstracao|interessado|cliente|nao_interessado)$")
    ultimo_contato: date | None = None


class ImportacaoLeadsProspeccao(BaseModel):
    leads: list[NovoLeadProspeccao] = Field(min_length=1, max_length=500)


class ConfiguracaoProspeccao(BaseModel):
    whatsapp_template: str | None = Field(default=None, min_length=10, max_length=2000)
    email_assunto_template: str | None = Field(default=None, min_length=3, max_length=200)
    email_corpo_template: str | None = Field(default=None, min_length=10, max_length=4000)


class RegiaoProspeccao(BaseModel):
    nome: str = Field(min_length=2, max_length=160)
    pais: str = Field(default="", max_length=120)
    cidade: str = Field(default="", max_length=120)
    bairro: str = Field(default="", max_length=120)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    raio_metros: int = Field(default=5000, ge=100, le=50000)
    ativa: bool = True

class StatusAluno(BaseModel):
    ativo: bool


class NovoRecursoAgendavel(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    tipo: Literal["aula", "area"]
    descricao: str = Field(default="", max_length=1000)
    capacidade: int = Field(ge=1, le=10000)


class AtualizacaoRecursoAgendavel(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=120)
    tipo: Literal["aula", "area"] | None = None
    descricao: str | None = Field(default=None, max_length=1000)
    capacidade: int | None = Field(default=None, ge=1, le=10000)
    ativo: bool | None = None


class NovaSessaoAgendada(BaseModel):
    recurso_id: int = Field(gt=0)
    inicio: datetime
    fim: datetime


class NovaReservaAgendada(BaseModel):
    aluno_id: int = Field(gt=0)


TAMANHO_MAXIMO_FOTO_ENTRADA = 5 * 1024 * 1024
TAMANHO_MAXIMO_FOTO_ARMAZENADA = 512 * 1024
TIPOS_FOTO_PERMITIDOS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
Image.MAX_IMAGE_PIXELS = 20_000_000


def normalizar_foto_aluno(tipo: str, conteudo: bytes) -> bytes:
    if tipo not in TIPOS_FOTO_PERMITIDOS:
        raise HTTPException(status_code=415, detail="formato_de_foto_nao_suportado")
    if not conteudo:
        raise HTTPException(status_code=400, detail="foto_invalida")
    if len(conteudo) > TAMANHO_MAXIMO_FOTO_ENTRADA:
        raise HTTPException(status_code=413, detail="foto_muito_grande")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(conteudo)) as original:
                if original.format != TIPOS_FOTO_PERMITIDOS[tipo]:
                    raise HTTPException(status_code=400, detail="foto_invalida")
                original.verify()
            with Image.open(io.BytesIO(conteudo)) as original:
                orientada = ImageOps.exif_transpose(original)
                orientada.thumbnail((512, 512), Image.Resampling.LANCZOS)
                imagem = orientada.convert("RGBA")
                limpa = Image.new("RGB", imagem.size, "white")
                limpa.paste(imagem, mask=imagem.getchannel("A"))

                for qualidade in (86, 76, 66, 56):
                    saida = io.BytesIO()
                    limpa.save(saida, format="JPEG", quality=qualidade, optimize=True)
                    foto = saida.getvalue()
                    if len(foto) <= TAMANHO_MAXIMO_FOTO_ARMAZENADA:
                        return foto
    except HTTPException:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        ValueError,
        UnidentifiedImageError,
    ) as erro:
        raise HTTPException(status_code=400, detail="foto_invalida") from erro

    raise HTTPException(status_code=413, detail="foto_muito_grande")


def monitor_atual(
    chave: str | None = Depends(chave_do_monitor),
    sessao: str | None = Depends(sessao_do_monitor),
):
    if not chave:
        raise HTTPException(status_code=401, detail="chave_do_monitor_ausente")
    # Normaliza o código compartilhado digitado em tablets e navegadores,
    # mantendo compatibilidade com chaves antigas que continham hífens.
    chave_original = chave.strip()
    chave = "".join(chave.split()).replace("-", "").upper()
    chave_hash = hashlib.sha256(chave.encode("utf-8")).hexdigest()
    chave_hash_legada = hashlib.sha256(chave_original.encode("utf-8")).hexdigest()
    hashes_chave = (chave_hash, chave_hash_legada)
    try:
        with get_connection() as conn:
            try:
                academia = conn.execute(
                    "SELECT a.id, a.nome, m.id AS monitor_id, m.nome AS monitor_nome FROM monitores m "
                    "JOIN academias a ON a.id = m.academia_id "
                        "WHERE m.chave_hash IN (%s, %s) AND m.ativo AND a.ativa IS TRUE",
                        hashes_chave,
                ).fetchone()
                if academia is None:
                    academia = conn.execute(
                        "SELECT id, nome, NULL::bigint AS monitor_id, 'Monitor principal' AS monitor_nome FROM academias "
                            "WHERE chave_monitor_hash IN (%s, %s) AND ativa IS TRUE",
                            hashes_chave,
                    ).fetchone()
            except errors.UndefinedTable:
                academia = conn.execute(
                    "SELECT id, nome, NULL::bigint AS monitor_id, 'Monitor principal' AS monitor_nome FROM academias "
                        "WHERE chave_monitor_hash IN (%s, %s) AND ativa IS TRUE",
                        hashes_chave,
                ).fetchone()
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_monitor_pendente") from erro
    if academia is None:
        raise HTTPException(status_code=401, detail="chave_do_monitor_invalida")
    if sessao and academia.get("monitor_id") is not None:
        if len(sessao) > 160:
            raise HTTPException(status_code=401, detail="sessao_do_monitor_invalida")
        sessao_hash = hashlib.sha256(sessao.encode("utf-8")).hexdigest()
        with get_connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (int(academia["id"]),))
            session_row = conn.execute(
                "SELECT id, numero FROM monitor_sessoes "
                "WHERE monitor_id = %s AND sessao_hash = %s",
                (academia["monitor_id"], sessao_hash),
            ).fetchone()
            if session_row is None:
                limite = recursos_da_academia(conn, academia["id"]).get("max_monitores", 0)
                ativos = conn.execute(
                    "SELECT count(*) AS total FROM monitor_sessoes s "
                    "JOIN monitores m ON m.id = s.monitor_id "
                    "WHERE m.academia_id = %s AND s.ativo "
                    "AND ultimo_sinal >= CURRENT_TIMESTAMP - INTERVAL '90 seconds'",
                    (academia["id"],),
                ).fetchone()["total"]
                if int(ativos) >= int(limite):
                    raise HTTPException(status_code=403, detail="limite_de_monitores_do_plano_atingido")
                usados = {
                    int(row["numero"])
                    for row in conn.execute(
                        "SELECT s.numero FROM monitor_sessoes s "
                        "JOIN monitores m ON m.id = s.monitor_id "
                        "WHERE m.academia_id = %s AND s.ativo "
                        "AND ultimo_sinal >= CURRENT_TIMESTAMP - INTERVAL '90 seconds'",
                        (academia["id"],),
                    ).fetchall()
                }
                numero = next((slot for slot in range(1, 51) if slot not in usados), None)
                if numero is None:
                    raise HTTPException(status_code=403, detail="limite_de_telas_atingido")
                # A tabela mantém uma linha por vaga por causa da chave única.
                # Reaproveite a linha inativa antes de inserir uma nova sessão.
                session_row = conn.execute(
                    "UPDATE monitor_sessoes SET sessao_hash = %s, ultimo_sinal = CURRENT_TIMESTAMP, criado_em = CURRENT_TIMESTAMP, ativo = true "
                    "WHERE monitor_id = %s AND numero = %s AND NOT ativo RETURNING id, numero",
                    (sessao_hash, academia["monitor_id"], numero),
                ).fetchone()
                if session_row is None:
                    session_row = conn.execute(
                        "INSERT INTO monitor_sessoes (monitor_id, sessao_hash, numero) "
                        "VALUES (%s, %s, %s) RETURNING id, numero",
                        (academia["monitor_id"], sessao_hash, numero),
                    ).fetchone()
            else:
                conn.execute(
                    "UPDATE monitor_sessoes SET ultimo_sinal = CURRENT_TIMESTAMP, ativo = true "
                    "WHERE id = %s",
                    (session_row["id"],),
                )
        academia["monitor_session_id"] = session_row["id"]
        academia["monitor_numero"] = session_row["numero"]
        with get_connection() as conn:
            limite = int(recursos_da_academia(conn, academia["id"]).get("max_monitores", 0))
            ativos = conn.execute(
                "SELECT count(*) AS total FROM monitor_sessoes s "
                "JOIN monitores m ON m.id = s.monitor_id "
                "WHERE m.academia_id = %s AND s.ativo "
                "AND s.ultimo_sinal >= CURRENT_TIMESTAMP - INTERVAL '90 seconds'",
                (academia["id"],),
            ).fetchone()["total"]
        academia["monitores_abertos"] = int(ativos)
        academia["monitores_limite"] = limite
    return academia


@app.delete("/monitor/sessao", include_in_schema=False)
def encerrar_sessao_monitor_publica(
    chave: str | None = Depends(chave_do_monitor),
    sessao: str | None = Depends(sessao_do_monitor),
):
    """Release the number assigned to a monitor window when it closes."""
    if not chave or not sessao or len(sessao) > 160:
        return {"encerrada": False}
    chave = "".join(chave.split()).replace("-", "").upper()
    chave_hash = hashlib.sha256(chave.encode("utf-8")).hexdigest()
    sessao_hash = hashlib.sha256(sessao.encode("utf-8")).hexdigest()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT s.id FROM monitor_sessoes s "
            "JOIN monitores m ON m.id = s.monitor_id "
            "WHERE m.chave_hash = %s AND s.sessao_hash = %s AND s.ativo",
            (chave_hash, sessao_hash),
        ).fetchone()
        if row is None:
            return {"encerrada": False}
        conn.execute("UPDATE monitor_sessoes SET ativo = false WHERE id = %s", (row["id"],))
    return {"encerrada": True}

def nome_curto_monitor(nome: str | None) -> str:
    if not nome:
        return "Cadastro não encontrado"
    partes = nome.strip().split()
    if len(partes) <= 1:
        return partes[0] if partes else "Aluno"
    return f"{partes[0]} {partes[-1][0].upper()}."


@app.get("/academia/tela-acesso")
def configuracao_tela_acesso(dono=Depends(somente_dono)):
    try:
        with get_connection() as conn:
            config = conn.execute(
                "SELECT (chave_monitor_hash IS NOT NULL OR EXISTS ("
                "SELECT 1 FROM monitores m WHERE m.academia_id = academias.id AND m.ativo"
                ")) AS chave_ativa, "
                "logo_monitor IS NOT NULL AS logo_cadastrada, "
                "(SELECT codigo_compartilhado FROM monitores WHERE academia_id = academias.id AND ativo AND codigo_compartilhado IS NOT NULL ORDER BY id LIMIT 1) AS codigo_compartilhado "
                "FROM academias WHERE id = %s",
                (dono["academia_id"],),
            ).fetchone()
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_monitor_pendente") from erro
    if config is None:
        raise HTTPException(status_code=404, detail="academia_nao_encontrada")
    return config


@app.post("/academia/tela-acesso/chave")
def gerar_chave_tela_acesso(dono=Depends(somente_dono)):
    exigir_escrita_local()
    return _gerar_chave_monitor(dono, None)


def _limites_hardware(conn, academia_id: int) -> dict:
    recursos = recursos_da_academia(conn, academia_id)
    monitores = conn.execute(
        "SELECT count(*) AS total FROM monitores WHERE academia_id = %s AND ativo",
        (academia_id,),
    ).fetchone()["total"]
    leitores = conn.execute(
        "SELECT count(*) AS total FROM leitores WHERE academia_id = %s AND ativo",
        (academia_id,),
    ).fetchone()["total"]
    return {
        "max_monitores": int(recursos.get("max_monitores", 0)),
        "max_leitores": int(recursos.get("max_leitores", 0)),
        "monitores_ativos": int(monitores),
        "leitores_ativos": int(leitores),
    }


def _gerar_chave_monitor(dono, dados: ChaveMonitor | None):
    # Short, typeable code shared by every screen of this gym. It remains valid
    # until the owner generates a replacement from the authenticated panel.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    chave = "".join(secrets.choice(alphabet) for _ in range(8))
    chave_hash = hashlib.sha256(chave.encode("utf-8")).hexdigest()
    nome = (dados.nome if dados else "Monitor").strip()
    with get_connection() as conn:
        existente = conn.execute(
            "SELECT codigo_compartilhado, nome FROM monitores WHERE academia_id = %s AND ativo AND codigo_compartilhado IS NOT NULL ORDER BY id LIMIT 1",
            (dono["academia_id"],),
        ).fetchone()
        limites = _limites_hardware(conn, dono["academia_id"])
        if existente and not (dados and dados.renovar):
            return {"chave": existente["codigo_compartilhado"], "nome": existente["nome"], "limites": limites}
        if existente and dados and dados.renovar:
            conn.execute(
                "UPDATE monitores SET chave_hash = %s, codigo_compartilhado = %s, nome = %s WHERE academia_id = %s AND ativo AND codigo_compartilhado IS NOT NULL",
                (chave_hash, chave, nome, dono["academia_id"]),
            )
            conn.execute(
                "UPDATE monitor_sessoes SET ativo = false WHERE monitor_id IN (SELECT id FROM monitores WHERE academia_id = %s AND ativo)",
                (dono["academia_id"],),
            )
            conn.execute(
                "UPDATE academias SET chave_monitor_hash = %s WHERE id = %s",
                (chave_hash, dono["academia_id"]),
            )
            return {"chave": chave, "nome": nome, "limites": limites, "renovada": True}
        if limites["max_monitores"] <= limites["monitores_ativos"]:
            raise HTTPException(status_code=403, detail="limite_de_monitores_do_plano_atingido")
        conn.execute(
            "INSERT INTO monitores (academia_id, nome, chave_hash, codigo_compartilhado) VALUES (%s, %s, %s, %s)",
            (dono["academia_id"], nome, chave_hash, chave),
        )
        # Mantém o campo legado sincronizado para instalações antigas e integrações existentes.
        conn.execute(
            "UPDATE academias SET chave_monitor_hash = COALESCE(chave_monitor_hash, %s) WHERE id = %s",
            (chave_hash, dono["academia_id"]),
        )
    return {"chave": chave, "nome": nome, "limites": {**limites, "monitores_ativos": limites["monitores_ativos"] + 1}}


@app.post("/academia/tela-acesso/chaves")
def gerar_chave_monitor_configurada(dados: ChaveMonitor, dono=Depends(somente_dono)):
    exigir_escrita_local()
    return _gerar_chave_monitor(dono, dados)


@app.get("/academia/monitores")
def listar_monitores(dono=Depends(somente_dono)):
    with get_connection() as conn:
        limites = _limites_hardware(conn, dono["academia_id"])
        monitores = conn.execute(
            "SELECT id, nome, ativo, criado_em FROM monitores "
            "WHERE academia_id = %s ORDER BY id",
            (dono["academia_id"],),
        ).fetchall()
        sessoes = conn.execute(
            "SELECT s.id, s.monitor_id, s.numero, s.criado_em, s.ultimo_sinal "
            "FROM monitor_sessoes s JOIN monitores m ON m.id = s.monitor_id "
            "WHERE m.academia_id = %s AND s.ativo "
            "AND s.ultimo_sinal >= CURRENT_TIMESTAMP - INTERVAL '90 seconds' "
            "ORDER BY s.numero",
            (dono["academia_id"],),
        ).fetchall()
    limites["telas_abertas"] = len(sessoes)
    return {"limites": limites, "monitores": monitores, "sessoes": sessoes}


@app.delete("/academia/monitor-sessoes/{sessao_id}")
def encerrar_sessao_monitor(sessao_id: int, dono=Depends(somente_dono)):
    exigir_escrita_local()
    with get_connection() as conn:
        sessao = conn.execute(
            "UPDATE monitor_sessoes s SET ativo = false "
            "FROM monitores m WHERE s.id = %s AND s.monitor_id = m.id "
            "AND m.academia_id = %s RETURNING s.id",
            (sessao_id, dono["academia_id"]),
        ).fetchone()
    if sessao is None:
        raise HTTPException(status_code=404, detail="sessao_monitor_nao_encontrada")
    return {"encerrada": True}


@app.delete("/academia/monitores/{monitor_id}")
def desativar_monitor(monitor_id: int, dono=Depends(somente_dono)):
    exigir_escrita_local()
    with get_connection() as conn:
        monitor = conn.execute(
            "UPDATE monitores SET ativo = false WHERE id = %s AND academia_id = %s AND ativo RETURNING id",
            (monitor_id, dono["academia_id"]),
        ).fetchone()
        if monitor is None:
            raise HTTPException(status_code=404, detail="monitor_nao_encontrado")
        conn.execute(
            "UPDATE monitor_sessoes SET ativo = false WHERE monitor_id = %s",
            (monitor_id,),
        )
        # Revogar o código também desativa o fallback legado da academia.
        conn.execute(
            "UPDATE academias SET chave_monitor_hash = NULL WHERE id = %s",
            (dono["academia_id"],),
        )
    return {"desconectado": True, "codigo_preservado": False}


@app.get("/academia/leitores")
def listar_leitores(dono=Depends(somente_dono)):
    with get_connection() as conn:
        limites = _limites_hardware(conn, dono["academia_id"])
        leitores = conn.execute(
            "SELECT id, nome, ativo, tipo_integracao, endpoint_url, metodo_http, configuracao, criado_em "
            "FROM leitores WHERE academia_id = %s ORDER BY id",
            (dono["academia_id"],),
        ).fetchall()
    return {"limites": limites, "leitores": leitores}


@app.post("/academia/leitores", status_code=201)
def criar_leitor_configurado(dados: ConfiguracaoLeitor, dono=Depends(somente_dono)):
    exigir_escrita_local()
    endpoint = dados.endpoint_url.strip() if dados.endpoint_url else None
    if dados.tipo_integracao in {"http_json", "webhook"}:
        parsed = urllib.parse.urlparse(endpoint or "")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=400, detail="endpoint_do_leitor_invalido")
    chave = secrets.token_urlsafe(32)
    chave_hash = hashlib.sha256(chave.encode("utf-8")).hexdigest()
    with get_connection() as conn:
        limites = _limites_hardware(conn, dono["academia_id"])
        if limites["max_leitores"] <= limites["leitores_ativos"]:
            raise HTTPException(status_code=403, detail="limite_de_leitores_do_plano_atingido")
        leitor = conn.execute(
            "INSERT INTO leitores (academia_id, nome, chave_hash, tipo_integracao, endpoint_url, metodo_http, configuracao) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id, nome, tipo_integracao, endpoint_url, metodo_http",
            (dono["academia_id"], dados.nome.strip(), chave_hash, dados.tipo_integracao, endpoint,
             dados.metodo_http, Jsonb(dados.configuracao)),
        ).fetchone()
    return {"leitor": leitor, "chave": chave, "limites": {**limites, "leitores_ativos": limites["leitores_ativos"] + 1},
            "aviso": "A chave é exibida uma única vez e deve ficar somente no equipamento da catraca."}


@app.patch("/academia/leitores/{leitor_id}")
def atualizar_leitor_configurado(leitor_id: int, dados: ConfiguracaoLeitor, dono=Depends(somente_dono)):
    exigir_escrita_local()
    endpoint = dados.endpoint_url.strip() if dados.endpoint_url else None
    if dados.tipo_integracao in {"http_json", "webhook"}:
        parsed = urllib.parse.urlparse(endpoint or "")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=400, detail="endpoint_do_leitor_invalido")
    with get_connection() as conn:
        leitor = conn.execute(
            "UPDATE leitores SET nome = %s, tipo_integracao = %s, endpoint_url = %s, metodo_http = %s, configuracao = %s "
            "WHERE id = %s AND academia_id = %s RETURNING id, nome, ativo, tipo_integracao, endpoint_url, metodo_http, configuracao",
            (dados.nome.strip(), dados.tipo_integracao, endpoint, dados.metodo_http, Jsonb(dados.configuracao), leitor_id, dono["academia_id"]),
        ).fetchone()
    if leitor is None:
        raise HTTPException(status_code=404, detail="leitor_nao_encontrado")
    return leitor


@app.delete("/academia/leitores/{leitor_id}")
def desativar_leitor_configurado(leitor_id: int, dono=Depends(somente_dono)):
    exigir_escrita_local()
    with get_connection() as conn:
        leitor = conn.execute(
            "UPDATE leitores SET ativo = false WHERE id = %s AND academia_id = %s RETURNING id",
            (leitor_id, dono["academia_id"]),
        ).fetchone()
    if leitor is None:
        raise HTTPException(status_code=404, detail="leitor_nao_encontrado")
    return {"desativado": True}


@app.get("/academia/leitores/adaptadores")
def adaptadores_leitores(dono=Depends(somente_dono)):
    """Contrato comum para catracas: a catraca chama /acesso; APIs HTTP recebem o mesmo resultado."""
    return {
        "adaptadores": [
            {"tipo": "api_key", "nome": "API Frequency", "descricao": "Equipamento chama /acesso com X-Reader-Key."},
            {"tipo": "http_json", "nome": "API HTTP JSON", "descricao": "Endpoint HTTP configurável para fabricantes que aceitam JSON."},
            {"tipo": "webhook", "nome": "Webhook", "descricao": "Endpoint do fabricante para eventos de liberação."},
        ],
        "contrato": {"headers": {"X-Reader-Key": "chave do equipamento"}, "resultado": ["liberado", "motivo", "nome", "dias_restantes"]},
    }


@app.put("/academia/tela-acesso/logo")
def salvar_logo_tela_acesso(logo: LogoMonitor, dono=Depends(somente_dono)):
    exigir_escrita_local()
    try:
        conteudo = base64.b64decode(logo.foto_base64, validate=True)
    except (binascii.Error, ValueError) as erro:
        raise HTTPException(status_code=400, detail="foto_invalida") from erro
    imagem = normalizar_foto_aluno(logo.foto_media_type, conteudo)
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE academias SET logo_monitor = %s, "
                "logo_monitor_media_type = 'image/jpeg' WHERE id = %s",
                (imagem, dono["academia_id"]),
            )
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_monitor_pendente") from erro
    return {"salva": True}


@app.delete("/academia/tela-acesso/logo")
def remover_logo_tela_acesso(dono=Depends(somente_dono)):
    exigir_escrita_local()
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE academias SET logo_monitor = NULL, "
                "logo_monitor_media_type = NULL WHERE id = %s",
                (dono["academia_id"],),
            )
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_monitor_pendente") from erro
    return {"removida": True}


@app.get("/academia/tela-acesso/logo")
def obter_logo_tela_acesso(dono=Depends(somente_dono)):
    try:
        with get_connection() as conn:
            logo = conn.execute(
                "SELECT logo_monitor, logo_monitor_media_type FROM academias "
                "WHERE id = %s",
                (dono["academia_id"],),
            ).fetchone()
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_monitor_pendente") from erro
    if logo is None or logo["logo_monitor"] is None:
        raise HTTPException(status_code=404, detail="logo_nao_cadastrada")
    return Response(
        content=bytes(logo["logo_monitor"]),
        media_type=logo["logo_monitor_media_type"],
        headers={"Cache-Control": "private, no-store"},
    )


@app.get("/monitor/estado")
def estado_monitor(academia=Depends(monitor_atual)):
    if academia.get("monitor_session_id") is not None:
        # A connected screen receives only its own session events. Keeping
        # legacy, unassigned events in this branch would broadcast an access
        # from another screen to every newly connected window.
        escopo_eventos = "p.monitor_session_id = %s"
        parametros_escopo = (academia["monitor_session_id"],)
    else:
        escopo_eventos = "(p.monitor_id = %s OR p.monitor_id IS NULL)"
        parametros_escopo = (academia.get("monitor_id"),)
    try:
        with get_connection() as conn:
            dados = conn.execute(
                "SELECT COALESCE(max(p.id), 0) AS ultimo_evento, "
                "logo_monitor IS NOT NULL AS logo_cadastrada "
                "FROM academias LEFT JOIN presencas p "
                "ON p.academia_id = academias.id "
                f"AND {escopo_eventos} "
                "WHERE academias.id = %s GROUP BY academias.id",
                (*parametros_escopo, academia["id"]),
            ).fetchone()
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_monitor_pendente") from erro
    if dados is None:
        raise HTTPException(status_code=404, detail="academia_nao_encontrada")
    return {
        "academia": academia["nome"],
        "monitor_id": academia.get("monitor_id"),
        "monitor_nome": academia.get("monitor_nome") or "Monitor principal",
        "monitor_numero": academia.get("monitor_numero"),
        "monitores_abertos": academia.get("monitores_abertos"),
        "monitores_limite": academia.get("monitores_limite"),
        "ultimo_evento": dados["ultimo_evento"],
        "logo_cadastrada": dados["logo_cadastrada"],
    }


@app.get("/monitor/logo")
def obter_logo_monitor(academia=Depends(monitor_atual)):
    try:
        with get_connection() as conn:
            logo = conn.execute(
                "SELECT logo_monitor, logo_monitor_media_type FROM academias "
                "WHERE id = %s",
                (academia["id"],),
            ).fetchone()
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_monitor_pendente") from erro
    if logo is None or logo["logo_monitor"] is None:
        raise HTTPException(status_code=404, detail="logo_nao_cadastrada")
    return Response(
        content=bytes(logo["logo_monitor"]),
        media_type=logo["logo_monitor_media_type"],
        headers={"Cache-Control": "private, no-store"},
    )


@app.get("/monitor/eventos")
def eventos_monitor(
    depois: int = Query(default=0, ge=0),
    academia=Depends(monitor_atual),
):
    if academia.get("monitor_session_id") is not None:
        escopo_eventos = "p.monitor_session_id = %s"
        parametros_escopo = (academia["monitor_session_id"],)
    else:
        escopo_eventos = "(p.monitor_id = %s OR p.monitor_id IS NULL)"
        parametros_escopo = (academia.get("monitor_id"),)
    try:
        with get_connection() as conn:
            eventos = conn.execute(
                "SELECT p.id, p.liberado, p.motivo, p.data_hora, a.nome AS nome_aluno, "
                "a.foto_perfil IS NOT NULL AS foto_disponivel "
                "FROM presencas p LEFT JOIN alunos a "
                "ON a.id = p.aluno_id AND a.academia_id = p.academia_id "
                "WHERE p.academia_id = %s AND p.id > %s "
                f"AND {escopo_eventos} "
                "AND p.data_hora >= CURRENT_TIMESTAMP - INTERVAL '15 seconds' "
                "ORDER BY p.id LIMIT 10",
                (academia["id"], depois, *parametros_escopo),
            ).fetchall()
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_foto_pendente") from erro
    return [
        {
            "id": evento["id"],
            "nome": nome_curto_monitor(evento["nome_aluno"]),
            "liberado": evento["liberado"],
            "motivo": evento["motivo"],
            "data_hora": evento["data_hora"],
            "foto_disponivel": evento["foto_disponivel"],
        }
        for evento in eventos
    ]


@app.get("/monitor/eventos/{evento_id}/foto")
def foto_evento_monitor(evento_id: int, academia=Depends(monitor_atual)):
    if academia.get("monitor_session_id") is not None:
        escopo_eventos = "p.monitor_session_id = %s"
        parametros_escopo = (academia["monitor_session_id"],)
    else:
        escopo_eventos = "(p.monitor_id = %s OR p.monitor_id IS NULL)"
        parametros_escopo = (academia.get("monitor_id"),)
    try:
        with get_connection() as conn:
            foto = conn.execute(
                "SELECT a.foto_perfil, a.foto_media_type FROM presencas p "
                "JOIN alunos a ON a.id = p.aluno_id AND a.academia_id = p.academia_id "
                "WHERE p.id = %s AND p.academia_id = %s "
                f"AND {escopo_eventos} "
                "AND p.data_hora >= CURRENT_TIMESTAMP - INTERVAL '15 seconds'",
                (evento_id, academia["id"], *parametros_escopo),
            ).fetchone()
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_foto_pendente") from erro
    if foto is None or foto["foto_perfil"] is None:
        raise HTTPException(status_code=404, detail="foto_nao_cadastrada")
    return Response(
        content=bytes(foto["foto_perfil"]),
        media_type=foto["foto_media_type"],
        headers={"Cache-Control": "private, no-store"},
    )


_COLUNAS_RESERVAS_OBRIGATORIAS = {
    "recursos_agendaveis": {
        "id", "academia_id", "nome", "tipo", "descricao", "capacidade", "ativo", "criado_em",
    },
    "sessoes_agendadas": {
        "id", "academia_id", "recurso_id", "inicio", "fim", "status", "criada_em",
    },
    "reservas_agendadas": {
        "id", "academia_id", "sessao_id", "aluno_id", "status", "criada_em", "cancelada_em",
    },
}
_CONSTRAINTS_RESERVAS_OBRIGATORIAS = {
    "recursos_agendaveis_nome_key",
    "recursos_agendaveis_academia_id_id_key",
    "sessoes_recurso_mesma_academia_fk",
    "sessoes_periodo_check",
    "sessoes_agendadas_academia_id_id_key",
    "reservas_sessao_mesma_academia_fk",
    "reservas_aluno_mesma_academia_fk",
    "reservas_cancelamento_check",
    "reservas_agendadas_academia_id_id_key",
}


def exigir_esquema_reservas(conn) -> None:
    colunas = conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name IN "
        "('recursos_agendaveis', 'sessoes_agendadas', 'reservas_agendadas')"
    ).fetchall()
    presentes_por_tabela: dict[str, set[str]] = {}
    for coluna in colunas:
        presentes_por_tabela.setdefault(coluna["table_name"], set()).add(coluna["column_name"])
    tabelas_completas = all(
        obrigatorias <= presentes_por_tabela.get(tabela, set())
        for tabela, obrigatorias in _COLUNAS_RESERVAS_OBRIGATORIAS.items()
    )
    constraints = {
        row["conname"]
        for row in conn.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE connamespace = 'public'::regnamespace"
        ).fetchall()
    }
    indice = conn.execute(
        "SELECT 1 AS presente FROM pg_indexes "
        "WHERE schemaname = 'public' AND indexname = 'reservas_ativas_sessao_aluno_uidx'"
    ).fetchone()
    if not tabelas_completas or not _CONSTRAINTS_RESERVAS_OBRIGATORIAS <= constraints or indice is None:
        raise HTTPException(status_code=503, detail="migracao_reservas_pendente")


def validar_periodo_agendado(inicio: datetime, fim: datetime) -> None:
    if inicio.tzinfo is None or inicio.utcoffset() is None or fim.tzinfo is None or fim.utcoffset() is None:
        raise HTTPException(status_code=422, detail="data_hora_com_fuso_obrigatorio")
    if inicio >= fim:
        raise HTTPException(status_code=422, detail="periodo_invalido")
    if inicio.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="sessao_no_passado")


@app.post("/recursos-agendaveis", status_code=201)
def criar_recurso_agendavel(dados: NovoRecursoAgendavel, dono=Depends(somente_dono)):
    exigir_escrita_local()
    nome = dados.nome.strip()
    if not nome:
        raise HTTPException(status_code=422, detail="nome_recurso_obrigatorio")
    with get_connection() as conn:
        exigir_esquema_reservas(conn)
        try:
            recurso = conn.execute(
                "INSERT INTO public.recursos_agendaveis "
                "(academia_id, nome, tipo, descricao, capacidade) "
                "VALUES (%s, %s, %s, %s, %s) "
                "RETURNING id, nome, tipo, descricao, capacidade, ativo, criado_em",
                (dono["academia_id"], nome, dados.tipo, dados.descricao.strip(), dados.capacidade),
            ).fetchone()
        except errors.UniqueViolation as erro:
            raise HTTPException(status_code=409, detail="recurso_agendavel_ja_cadastrado") from erro
    return dict(recurso)


@app.get("/recursos-agendaveis")
def listar_recursos_agendaveis(usuario=Depends(usuario_de_academia)):
    with get_connection() as conn:
        exigir_esquema_reservas(conn)
        return conn.execute(
            "SELECT id, nome, tipo, descricao, capacidade, ativo, criado_em "
            "FROM public.recursos_agendaveis WHERE academia_id = %s "
            "ORDER BY ativo DESC, nome, id",
            (usuario["academia_id"],),
        ).fetchall()


@app.patch("/recursos-agendaveis/{recurso_id}")
def atualizar_recurso_agendavel(
    recurso_id: int,
    dados: AtualizacaoRecursoAgendavel,
    dono=Depends(somente_dono),
):
    exigir_escrita_local()
    alteracoes = dados.model_dump(exclude_unset=True)
    if any(valor is None for valor in alteracoes.values()):
        raise HTTPException(status_code=422, detail="campos_nulos_nao_permitidos")
    if "nome" in alteracoes:
        alteracoes["nome"] = alteracoes["nome"].strip()
        if not alteracoes["nome"]:
            raise HTTPException(status_code=422, detail="nome_recurso_obrigatorio")
    if "descricao" in alteracoes:
        alteracoes["descricao"] = alteracoes["descricao"].strip()
    if not alteracoes:
        raise HTTPException(status_code=422, detail="nenhuma_alteracao_informada")
    colunas = [campo for campo in ("nome", "tipo", "descricao", "capacidade", "ativo") if campo in alteracoes]
    valores = [alteracoes[campo] for campo in colunas]
    set_sql = ", ".join(f"{campo} = %s" for campo in colunas)
    with get_connection() as conn:
        exigir_esquema_reservas(conn)
        recurso_atual = conn.execute(
            "SELECT id, capacidade FROM public.recursos_agendaveis "
            "WHERE id = %s AND academia_id = %s FOR UPDATE",
            (recurso_id, dono["academia_id"]),
        ).fetchone()
        if recurso_atual is None:
            raise HTTPException(status_code=404, detail="recurso_agendavel_nao_encontrado")
        if "capacidade" in alteracoes and alteracoes["capacidade"] < recurso_atual["capacidade"]:
            reservas_ativas = conn.execute(
                "SELECT count(*) AS total FROM public.reservas_agendadas b "
                "JOIN public.sessoes_agendadas s ON s.id = b.sessao_id "
                "AND s.academia_id = b.academia_id "
                "WHERE b.academia_id = %s AND s.recurso_id = %s "
                "AND b.status = 'reservada' AND s.status = 'agendada'",
                (dono["academia_id"], recurso_id),
            ).fetchone()["total"]
            if int(alteracoes["capacidade"]) < int(reservas_ativas):
                raise HTTPException(status_code=409, detail="capacidade_inferior_reservas_ativas")
        try:
            recurso = conn.execute(
                f"UPDATE public.recursos_agendaveis SET {set_sql} "
                "WHERE id = %s AND academia_id = %s "
                "RETURNING id, nome, tipo, descricao, capacidade, ativo, criado_em",
                (*valores, recurso_id, dono["academia_id"]),
            ).fetchone()
        except errors.UniqueViolation as erro:
            raise HTTPException(status_code=409, detail="recurso_agendavel_ja_cadastrado") from erro
    if recurso is None:
        raise HTTPException(status_code=404, detail="recurso_agendavel_nao_encontrado")
    return dict(recurso)


@app.delete("/recursos-agendaveis/{recurso_id}")
def desativar_recurso_agendavel(recurso_id: int, dono=Depends(somente_dono)):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_esquema_reservas(conn)
        recurso = conn.execute(
            "UPDATE public.recursos_agendaveis SET ativo = FALSE "
            "WHERE id = %s AND academia_id = %s RETURNING id, ativo",
            (recurso_id, dono["academia_id"]),
        ).fetchone()
    if recurso is None:
        raise HTTPException(status_code=404, detail="recurso_agendavel_nao_encontrado")
    return dict(recurso)


@app.post("/sessoes-agendadas", status_code=201)
def criar_sessao_agendada(dados: NovaSessaoAgendada, dono=Depends(somente_dono)):
    exigir_escrita_local()
    validar_periodo_agendado(dados.inicio, dados.fim)
    with get_connection() as conn:
        exigir_esquema_reservas(conn)
        recurso = conn.execute(
            "SELECT id FROM public.recursos_agendaveis "
            "WHERE id = %s AND academia_id = %s AND ativo IS TRUE FOR UPDATE",
            (dados.recurso_id, dono["academia_id"]),
        ).fetchone()
        if recurso is None:
            raise HTTPException(status_code=404, detail="recurso_agendavel_nao_encontrado")
        conflito = conn.execute(
            "SELECT id FROM public.sessoes_agendadas "
            "WHERE academia_id = %s AND recurso_id = %s AND status = 'agendada' "
            "AND inicio < %s AND fim > %s LIMIT 1",
            (dono["academia_id"], dados.recurso_id, dados.fim, dados.inicio),
        ).fetchone()
        if conflito is not None:
            raise HTTPException(status_code=409, detail="recurso_agendavel_ocupado")
        sessao = conn.execute(
            "INSERT INTO public.sessoes_agendadas "
            "(academia_id, recurso_id, inicio, fim) VALUES (%s, %s, %s, %s) "
            "RETURNING id, recurso_id, inicio, fim, status, criada_em",
            (dono["academia_id"], dados.recurso_id, dados.inicio, dados.fim),
        ).fetchone()
    return dict(sessao)


@app.get("/sessoes-agendadas")
def listar_sessoes_agendadas(
    inicio_de: datetime | None = Query(default=None),
    inicio_ate: datetime | None = Query(default=None),
    usuario=Depends(usuario_de_academia),
):
    for valor in (inicio_de, inicio_ate):
        if valor is not None and (valor.tzinfo is None or valor.utcoffset() is None):
            raise HTTPException(status_code=422, detail="data_hora_com_fuso_obrigatorio")
    if inicio_de is not None and inicio_ate is not None and inicio_de >= inicio_ate:
        raise HTTPException(status_code=422, detail="periodo_invalido")
    with get_connection() as conn:
        exigir_esquema_reservas(conn)
        return conn.execute(
            "SELECT s.id, s.recurso_id, r.nome AS recurso_nome, r.tipo AS recurso_tipo, "
            "r.capacidade, s.inicio, s.fim, s.status, s.criada_em, "
            "count(res.id) FILTER (WHERE res.status = 'reservada') AS reservas_ativas, "
            "r.capacidade - count(res.id) FILTER (WHERE res.status = 'reservada') AS vagas_disponiveis "
            "FROM public.sessoes_agendadas s "
            "JOIN public.recursos_agendaveis r ON r.id = s.recurso_id AND r.academia_id = s.academia_id "
            "LEFT JOIN public.reservas_agendadas res ON res.sessao_id = s.id AND res.academia_id = s.academia_id "
            "WHERE s.academia_id = %s AND (%s::timestamptz IS NULL OR s.inicio >= %s::timestamptz) "
            "AND (%s::timestamptz IS NULL OR s.inicio < %s::timestamptz) "
            "GROUP BY s.id, r.id ORDER BY s.inicio, s.id LIMIT 500",
            (usuario["academia_id"], inicio_de, inicio_de, inicio_ate, inicio_ate),
        ).fetchall()


@app.delete("/sessoes-agendadas/{sessao_id}")
def cancelar_sessao_agendada(sessao_id: int, dono=Depends(somente_dono)):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_esquema_reservas(conn)
        sessao = conn.execute(
            "UPDATE public.sessoes_agendadas SET status = 'cancelada' "
            "WHERE id = %s AND academia_id = %s AND status = 'agendada' "
            "RETURNING id, recurso_id, inicio, fim, status",
            (sessao_id, dono["academia_id"]),
        ).fetchone()
        if sessao is None:
            raise HTTPException(status_code=404, detail="sessao_agendada_nao_encontrada_ou_cancelada")
        conn.execute(
            "UPDATE public.reservas_agendadas SET status = 'cancelada', cancelada_em = CURRENT_TIMESTAMP "
            "WHERE sessao_id = %s AND academia_id = %s AND status = 'reservada'",
            (sessao_id, dono["academia_id"]),
        )
    return dict(sessao)


@app.post("/sessoes-agendadas/{sessao_id}/reservas", status_code=201)
def reservar_sessao_agendada(sessao_id: int, dados: NovaReservaAgendada, usuario=Depends(usuario_de_academia)):
    exigir_escrita_local()
    agora = datetime.now(timezone.utc)
    with get_connection() as conn:
        exigir_esquema_reservas(conn)
        sessao = conn.execute(
            "SELECT s.id, s.recurso_id, s.inicio, s.status, r.capacidade FROM public.sessoes_agendadas s "
            "JOIN public.recursos_agendaveis r ON r.id = s.recurso_id AND r.academia_id = s.academia_id "
            "WHERE s.id = %s AND s.academia_id = %s FOR UPDATE OF r, s",
            (sessao_id, usuario["academia_id"]),
        ).fetchone()
        if sessao is None:
            raise HTTPException(status_code=404, detail="sessao_agendada_nao_encontrada")
        if sessao["status"] != "agendada" or sessao["inicio"] <= agora:
            raise HTTPException(status_code=409, detail="sessao_indisponivel")
        aluno = conn.execute(
            "SELECT id, status FROM public.alunos WHERE id = %s AND academia_id = %s",
            (dados.aluno_id, usuario["academia_id"]),
        ).fetchone()
        if aluno is None:
            raise HTTPException(status_code=404, detail="aluno_nao_encontrado")
        if aluno["status"] != "ativo":
            raise HTTPException(status_code=409, detail="aluno_inativo")
        if conn.execute(
            "SELECT id FROM public.reservas_agendadas WHERE sessao_id = %s AND aluno_id = %s AND status = 'reservada'",
            (sessao_id, dados.aluno_id),
        ).fetchone() is not None:
            raise HTTPException(status_code=409, detail="reserva_duplicada")
        total = conn.execute(
            "SELECT count(*) AS total FROM public.reservas_agendadas WHERE sessao_id = %s AND status = 'reservada'",
            (sessao_id,),
        ).fetchone()["total"]
        if int(total) >= int(sessao["capacidade"]):
            raise HTTPException(status_code=409, detail="sessao_lotada")
        try:
            reserva = conn.execute(
                "INSERT INTO public.reservas_agendadas (academia_id, sessao_id, aluno_id) VALUES (%s, %s, %s) "
                "RETURNING id, sessao_id, aluno_id, status, criada_em",
                (usuario["academia_id"], sessao_id, dados.aluno_id),
            ).fetchone()
        except errors.UniqueViolation as erro:
            raise HTTPException(status_code=409, detail="reserva_duplicada") from erro
    return dict(reserva)


@app.get("/reservas-agendadas")
def listar_reservas_agendadas(
    sessao_id: int | None = Query(default=None, gt=0),
    aluno_id: int | None = Query(default=None, gt=0),
    usuario=Depends(usuario_de_academia),
):
    with get_connection() as conn:
        exigir_esquema_reservas(conn)
        return conn.execute(
            "SELECT b.id, b.sessao_id, b.aluno_id, a.nome AS aluno_nome, s.inicio, s.fim, "
            "r.nome AS recurso_nome, r.tipo AS recurso_tipo, b.status, b.criada_em, b.cancelada_em "
            "FROM public.reservas_agendadas b "
            "JOIN public.alunos a ON a.id = b.aluno_id AND a.academia_id = b.academia_id "
            "JOIN public.sessoes_agendadas s ON s.id = b.sessao_id AND s.academia_id = b.academia_id "
            "JOIN public.recursos_agendaveis r ON r.id = s.recurso_id AND r.academia_id = s.academia_id "
            "WHERE b.academia_id = %s AND (%s::bigint IS NULL OR b.sessao_id = %s::bigint) "
            "AND (%s::integer IS NULL OR b.aluno_id = %s::integer) ORDER BY s.inicio, b.id LIMIT 1000",
            (usuario["academia_id"], sessao_id, sessao_id, aluno_id, aluno_id),
        ).fetchall()


@app.delete("/reservas-agendadas/{reserva_id}")
def cancelar_reserva_agendada(reserva_id: int, usuario=Depends(usuario_de_academia)):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_esquema_reservas(conn)
        reserva = conn.execute(
            "UPDATE public.reservas_agendadas SET status = 'cancelada', cancelada_em = CURRENT_TIMESTAMP "
            "WHERE id = %s AND academia_id = %s AND status = 'reservada' "
            "RETURNING id, sessao_id, aluno_id, status, cancelada_em",
            (reserva_id, usuario["academia_id"]),
        ).fetchone()
    if reserva is None:
        raise HTTPException(status_code=404, detail="reserva_nao_encontrada_ou_cancelada")
    return dict(reserva)


@app.get("/planos")
def listar_planos(usuario=Depends(usuario_de_academia)):
    with get_connection() as conn:
        if esquema_de_moeda_disponivel(conn):
            planos = conn.execute(
                "SELECT id, nome, valor, moeda, duracao_dias "
                "FROM planos WHERE academia_id = %s ORDER BY id",
                (usuario["academia_id"],),
            ).fetchall()
        else:
            planos = conn.execute(
                "SELECT id, nome, valor, duracao_dias "
                "FROM planos WHERE academia_id = %s ORDER BY id",
                (usuario["academia_id"],),
            ).fetchall()
            planos = [{**plano, "moeda": usuario["moeda"]} for plano in planos]

    return planos


@app.post("/planos", status_code=201)
def criar_plano(
    novo: NovoPlano,
    dono=Depends(somente_dono),
):
    exigir_escrita_local()
    nome = novo.nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="nome_do_plano_obrigatorio")

    with get_connection() as conn:
        tem_moeda = esquema_de_moeda_disponivel(conn)
        if tem_moeda and outbox_ativa():
            plano = conn.execute(
                "INSERT INTO planos (academia_id, nome, valor, moeda, duracao_dias) "
                "VALUES (%s, %s, %s, %s, %s) "
                "RETURNING id, sync_id, nome, valor, moeda, duracao_dias",
                (dono["academia_id"], nome, novo.valor, dono["moeda"], novo.duracao_dias),
            ).fetchone()
            enfileirar_evento(
                conn,
                academia_sync_id=sync_id_academia(conn, dono["academia_id"]),
                entity_type="plano",
                entity_sync_id=plano["sync_id"],
                payload={
                    "id": str(plano["sync_id"]),
                    "nome": plano["nome"],
                    "valor": str(plano["valor"]),
                    "moeda": plano["moeda"],
                    "duracao_dias": plano["duracao_dias"],
                },
            )
        elif tem_moeda:
            plano = conn.execute(
                "INSERT INTO planos (academia_id, nome, valor, moeda, duracao_dias) "
                "VALUES (%s, %s, %s, %s, %s) "
                "RETURNING id, nome, valor, moeda, duracao_dias",
                (dono["academia_id"], nome, novo.valor, dono["moeda"], novo.duracao_dias),
            ).fetchone()
        elif outbox_ativa():
            plano = conn.execute(
                "INSERT INTO planos (academia_id, nome, valor, duracao_dias) "
                "VALUES (%s, %s, %s, %s) "
                "RETURNING id, sync_id, nome, valor, duracao_dias",
                (dono["academia_id"], nome, novo.valor, novo.duracao_dias),
            ).fetchone()
            plano = {**plano, "moeda": dono["moeda"]}
            enfileirar_evento(
                conn,
                academia_sync_id=sync_id_academia(conn, dono["academia_id"]),
                entity_type="plano",
                entity_sync_id=plano["sync_id"],
                payload={
                    "id": str(plano["sync_id"]),
                    "nome": plano["nome"],
                    "valor": str(plano["valor"]),
                    "moeda": plano["moeda"],
                    "duracao_dias": plano["duracao_dias"],
                },
            )
        else:
            plano = conn.execute(
                "INSERT INTO planos (academia_id, nome, valor, duracao_dias) "
                "VALUES (%s, %s, %s, %s) "
                "RETURNING id, nome, valor, duracao_dias",
                (dono["academia_id"], nome, novo.valor, novo.duracao_dias),
            ).fetchone()
            plano = {**plano, "moeda": dono["moeda"]}

    return {
        "id": plano["id"],
        "nome": plano["nome"],
        "valor": plano["valor"],
        "moeda": plano["moeda"],
        "duracao_dias": plano["duracao_dias"],
    }


@app.delete("/planos/{plano_id}", status_code=204)
def excluir_plano(plano_id: int, dono=Depends(somente_dono)):
    exigir_escrita_local()
    with get_connection() as conn:
        plano = conn.execute(
            "SELECT id, sync_id FROM planos WHERE id = %s AND academia_id = %s FOR UPDATE",
            (plano_id, dono["academia_id"]),
        ).fetchone()
        if plano is None:
            raise HTTPException(status_code=404, detail="plano_nao_encontrado")
        em_uso = conn.execute(
            "SELECT 1 FROM alunos WHERE academia_id = %s AND plano_id = %s LIMIT 1",
            (dono["academia_id"], plano_id),
        ).fetchone()
        if em_uso is not None:
            raise HTTPException(status_code=409, detail="plano_em_uso")
        if outbox_ativa():
            enfileirar_evento(
                conn,
                academia_sync_id=sync_id_academia(conn, dono["academia_id"]),
                entity_type="plano",
                entity_sync_id=plano["sync_id"],
                operation="delete",
                payload={"id": str(plano["sync_id"])},
            )
        conn.execute("DELETE FROM planos WHERE id = %s", (plano_id,))
    return Response(status_code=204)


def _exigir_vaga_de_aluno(conn, academia_id: int) -> None:
    """Bloqueia novo aluno ativo quando a assinatura já atingiu max_alunos."""
    recursos = recursos_da_academia(conn, academia_id)
    limite_alunos = int(recursos.get("max_alunos", 0) or 0)
    if limite_alunos <= 0:
        return
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (8_743_219 + int(academia_id),))
    ativos = conn.execute(
        "SELECT count(*) AS total FROM public.alunos WHERE academia_id = %s AND status = 'ativo'",
        (academia_id,),
    ).fetchone()["total"]
    if int(ativos) >= limite_alunos:
        raise HTTPException(status_code=403, detail="limite_de_alunos_do_plano_atingido")


@app.post("/alunos", status_code=201)
def criar_aluno(
    novo: NovoAluno,
    usuario=Depends(usuario_de_academia),
):
    exigir_escrita_local()
    academia_id = usuario["academia_id"]
    nome = novo.nome.strip()
    documento = novo.documento.strip()
    telefone = novo.telefone.strip() if novo.telefone else None
    bairro = novo.bairro.strip() if novo.bairro else None

    if not nome or not documento:
        raise HTTPException(status_code=400, detail="nome_e_documento_obrigatorios")

    if novo.data_nascimento is not None and novo.data_nascimento > date.today():
        raise HTTPException(status_code=400, detail="data_nascimento_invalida")

    email_aluno = aluno_auth.normalizar_email(novo.email) if novo.email else None
    if email_aluno is not None and not aluno_auth.email_valido(email_aluno):
        raise HTTPException(status_code=422, detail="email_invalido")

    foto_perfil = None
    if novo.foto_base64 is None:
        if novo.foto_media_type is not None:
            raise HTTPException(status_code=400, detail="foto_invalida")
    else:
        if novo.foto_media_type is None:
            raise HTTPException(status_code=400, detail="foto_invalida")
        try:
            conteudo_foto = base64.b64decode(novo.foto_base64, validate=True)
        except (binascii.Error, ValueError) as erro:
            raise HTTPException(status_code=400, detail="foto_invalida") from erro
        foto_perfil = normalizar_foto_aluno(novo.foto_media_type, conteudo_foto)

    template_facial = None
    if novo.fotos_rosto_base64:
        if usuario["papel"] != "dono":
            raise HTTPException(status_code=403, detail="permissao_insuficiente")
        if not novo.consentimento_facial:
            raise HTTPException(status_code=400, detail="consentimento_facial_obrigatorio")
        if novo.id_biometria is not None:
            raise HTTPException(status_code=400, detail="biometria_facial_gera_identificador")
        amostras = []
        try:
            for valor in novo.fotos_rosto_base64:
                conteudo = base64.b64decode(valor, validate=True)
                if len(conteudo) > 700_000:
                    raise HTTPException(status_code=413, detail="foto_muito_grande")
                amostras.append(conteudo)
            template_facial = enrollment_template(amostras)
        except (binascii.Error, ValueError) as erro:
            if isinstance(erro, FaceError):
                status = 503 if str(erro) in {
                    "modelo_facial_nao_instalado", "modelo_facial_invalido",
                    "motor_facial_nao_instalado",
                } else 422
                raise HTTPException(status_code=status, detail=str(erro)) from erro
            raise HTTPException(status_code=400, detail="foto_invalida") from erro

    with get_connection() as conn:
        _exigir_vaga_de_aluno(conn, academia_id)
        plano = None
        tem_moeda = esquema_de_moeda_disponivel(conn)
        id_biometria = novo.id_biometria
        if template_facial is not None:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"biometria-facial:{academia_id}",),
            )
            for _tentativa in range(20):
                candidato = secrets.randbelow(900_000_000) + 100_000_000
                existe = conn.execute(
                    "SELECT 1 FROM alunos WHERE academia_id = %s AND id_biometria = %s",
                    (academia_id, candidato),
                ).fetchone()
                if existe is None:
                    id_biometria = candidato
                    break
            else:
                raise HTTPException(status_code=503, detail="biometria_id_indisponivel")

        if novo.plano_id is not None:
            if outbox_ativa():
                if tem_moeda:
                    plano = conn.execute(
                        "SELECT valor, moeda, sync_id FROM planos "
                        "WHERE id = %s AND academia_id = %s",
                        (novo.plano_id, academia_id),
                    ).fetchone()
                else:
                    plano = conn.execute(
                        "SELECT valor, sync_id FROM planos "
                        "WHERE id = %s AND academia_id = %s",
                        (novo.plano_id, academia_id),
                    ).fetchone()
                    if plano is not None:
                        plano["moeda"] = usuario["moeda"]
            else:
                if tem_moeda:
                    plano = conn.execute(
                        "SELECT valor, moeda FROM planos "
                        "WHERE id = %s AND academia_id = %s",
                        (novo.plano_id, academia_id),
                    ).fetchone()
                else:
                    plano = conn.execute(
                        "SELECT valor FROM planos "
                        "WHERE id = %s AND academia_id = %s",
                        (novo.plano_id, academia_id),
                    ).fetchone()
                    if plano is not None:
                        plano["moeda"] = usuario["moeda"]

            if plano is None:
                raise HTTPException(
                    status_code=400,
                    detail="plano_invalido",
                )

        try:
            colunas = [
                "academia_id",
                "nome",
                "telefone",
                "bairro",
                "documento",
                "data_nascimento",
                "plano_id",
                "id_biometria",
            ]
            valores = [
                academia_id,
                nome,
                telefone,
                bairro,
                documento,
                novo.data_nascimento,
                novo.plano_id,
                id_biometria,
            ]
            if foto_perfil is not None:
                colunas.extend(("foto_perfil", "foto_media_type"))
                valores.extend((foto_perfil, "image/jpeg"))
            if email_aluno is not None:
                colunas.append("email")
                valores.append(email_aluno)

            placeholders = ", ".join("%s" for _ in valores)
            retorno = "id, sync_id, data_inicio" if outbox_ativa() else "id"
            aluno = conn.execute(
                "INSERT INTO alunos ("
                + ", ".join(colunas)
                + ") VALUES ("
                + placeholders
                + ") RETURNING "
                + retorno,
                valores,
            ).fetchone()
            if template_facial is not None:
                conn.execute(
                    "INSERT INTO biometrias_faciais "
                    "(academia_id, aluno_id, id_biometria, template, modelo, amostras, consentimento_em) "
                    "VALUES (%s, %s, %s, %s, %s, %s, now())",
                    (
                        academia_id, aluno["id"], id_biometria, template_facial,
                        MODEL_VERSION, len(novo.fotos_rosto_base64),
                    ),
                )
        except errors.UniqueViolation as erro:
            if getattr(erro.diag, "constraint_name", None) == "alunos_email_ativo_uidx":
                raise HTTPException(status_code=409, detail="email_ja_cadastrado")
            raise HTTPException(
                status_code=409,
                detail="documento_ou_biometria_ja_cadastrado",
            )
        except errors.ForeignKeyViolation:
            raise HTTPException(
                status_code=400,
                detail="academia_invalida",
            )
        except errors.UndefinedColumn as erro:
            if email_aluno is not None:
                raise HTTPException(status_code=503, detail="migracao_email_pendente") from erro
            if foto_perfil is not None:
                raise HTTPException(
                    status_code=503,
                    detail="migracao_foto_pendente",
                ) from erro
            raise

        if outbox_ativa():
            academia_uuid = sync_id_academia(conn, academia_id)
            enfileirar_evento(
                conn,
                academia_sync_id=academia_uuid,
                entity_type="aluno",
                entity_sync_id=aluno["sync_id"],
                payload={
                    "id": str(aluno["sync_id"]),
                    "nome": nome,
                    "bairro": bairro,
                    "status": "ativo",
                    "plano_id": str(plano["sync_id"]) if plano is not None else None,
                    "data_inicio": aluno["data_inicio"].isoformat(),
                },
            )

            if plano is not None:
                vencimento = date.today()
                if tem_moeda:
                    pagamento = conn.execute(
                        "INSERT INTO pagamentos "
                        "(academia_id, aluno_id, valor, moeda, vencimento) "
                        "VALUES (%s, %s, %s, %s, %s) "
                        "RETURNING sync_id, valor, moeda, vencimento, status",
                        (academia_id, aluno["id"], plano["valor"], plano["moeda"], vencimento),
                    ).fetchone()
                else:
                    pagamento = conn.execute(
                        "INSERT INTO pagamentos "
                        "(academia_id, aluno_id, valor, vencimento) "
                        "VALUES (%s, %s, %s, %s) "
                        "RETURNING sync_id, valor, vencimento, status",
                        (academia_id, aluno["id"], plano["valor"], vencimento),
                    ).fetchone()
                    pagamento["moeda"] = plano["moeda"]
                enfileirar_evento(
                    conn,
                    academia_sync_id=academia_uuid,
                    entity_type="pagamento",
                    entity_sync_id=pagamento["sync_id"],
                    payload={
                        "id": str(pagamento["sync_id"]),
                        "aluno_id": str(aluno["sync_id"]),
                        "valor": str(pagamento["valor"]),
                        "moeda": pagamento["moeda"],
                        "vencimento": pagamento["vencimento"].isoformat(),
                        "data_pagamento": None,
                        "status": pagamento["status"],
                    },
                )
        elif plano is not None:
            if tem_moeda:
                conn.execute(
                    "INSERT INTO pagamentos "
                    "(academia_id, aluno_id, valor, moeda, vencimento) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (academia_id, aluno["id"], plano["valor"], plano["moeda"], date.today()),
                )
            else:
                conn.execute(
                    "INSERT INTO pagamentos "
                    "(academia_id, aluno_id, valor, vencimento) "
                    "VALUES (%s, %s, %s, %s)",
                    (academia_id, aluno["id"], plano["valor"], date.today()),
                )

    return {"id": aluno["id"], "id_biometria": id_biometria}


@app.get("/alunos")
def listar_alunos(usuario=Depends(usuario_de_academia)):
    academia_id = usuario["academia_id"]

    with get_connection() as conn:
        linhas = conn.execute(
            "SELECT a.id, a.nome, "
            "CASE WHEN %s THEN '—' ELSE a.documento END AS documento, "
            "a.status, "
            "a.bairro, "
            "a.plano_id, pl.nome AS plano "
            "FROM alunos a "
            "LEFT JOIN planos pl ON pl.id = a.plano_id "
            "WHERE a.academia_id = %s "
            "ORDER BY a.id",
            (modo_somente_consulta(), academia_id),
        ).fetchall()

    return linhas


@app.get("/alunos/mapa-regiao")
def mapa_regiao_alunos(usuario=Depends(usuario_de_academia)):
    """Return active enrolled students grouped by neighborhood for the regional map."""
    with get_connection() as conn:
        bairros = conn.execute(
            "SELECT COALESCE(NULLIF(BTRIM(a.bairro), ''), 'Sem bairro informado') AS bairro, "
            "COUNT(*)::int AS total "
            "FROM alunos a WHERE a.academia_id = %s AND a.status = 'ativo' "
            "GROUP BY 1 ORDER BY total DESC, bairro",
            (usuario["academia_id"],),
        ).fetchall()
        regiao = conn.execute(
            "SELECT pais, cidade, estado FROM academias WHERE id = %s",
            (usuario["academia_id"],),
        ).fetchone() or {}
    total = sum(int(row["total"]) for row in bairros)
    return {"total_alunos": total, "bairros": bairros, "regiao": regiao}


@app.get("/alunos/{aluno_id}")
def obter_dados_aluno(
    aluno_id: int,
    incluir_bairro: bool = False,
    usuario=Depends(usuario_de_academia),
):
    if modo_somente_consulta():
        raise HTTPException(status_code=403, detail="modo_somente_consulta")

    with get_connection() as conn:
        aluno = conn.execute(
            "SELECT a.id, a.documento, a.telefone, a.bairro, a.data_nascimento "
            "FROM alunos a "
            "WHERE a.id = %s AND a.academia_id = %s",
            (aluno_id, usuario["academia_id"]),
        ).fetchone()

    if aluno is None:
        raise HTTPException(status_code=404, detail="aluno_nao_encontrado")
    resultado = dict(aluno)
    if not incluir_bairro:
        resultado.pop("bairro", None)
    return resultado


@app.get("/alunos/{aluno_id}/foto")
def obter_foto_aluno(
    aluno_id: int,
    usuario=Depends(usuario_de_academia),
):
    if modo_somente_consulta():
        raise HTTPException(status_code=403, detail="modo_somente_consulta")

    try:
        with get_connection() as conn:
            foto = conn.execute(
                "SELECT foto_perfil, foto_media_type FROM alunos "
                "WHERE id = %s AND academia_id = %s",
                (aluno_id, usuario["academia_id"]),
            ).fetchone()
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_foto_pendente") from erro

    if foto is None:
        raise HTTPException(status_code=404, detail="aluno_nao_encontrado")
    if foto["foto_perfil"] is None:
        raise HTTPException(status_code=404, detail="foto_nao_cadastrada")
    return Response(
        content=bytes(foto["foto_perfil"]),
        media_type=foto["foto_media_type"],
        headers={"Cache-Control": "private, no-store"},
    )


@app.delete("/alunos/{aluno_id}/foto")
def remover_foto_aluno(
    aluno_id: int,
    dono=Depends(somente_dono),
):
    exigir_escrita_local()
    try:
        with get_connection() as conn:
            aluno = conn.execute(
                "UPDATE alunos SET foto_perfil = NULL, foto_media_type = NULL "
                "WHERE id = %s AND academia_id = %s RETURNING id",
                (aluno_id, dono["academia_id"]),
            ).fetchone()
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_foto_pendente") from erro

    if aluno is None:
        raise HTTPException(status_code=404, detail="aluno_nao_encontrado")
    return {"removida": True}


@app.patch("/alunos/{aluno_id}")
def atualizar_dados_aluno(
    aluno_id: int,
    dados: AtualizacaoDadosAluno,
    usuario=Depends(usuario_de_academia),
):
    exigir_escrita_local()
    atualizacoes: dict[str, object] = {}

    if "documento" in dados.model_fields_set:
        documento = dados.documento.strip() if dados.documento else ""
        if not documento:
            raise HTTPException(status_code=400, detail="documento_obrigatorio")
        atualizacoes["documento"] = documento

    if "telefone" in dados.model_fields_set:
        telefone = dados.telefone.strip() if dados.telefone else ""
        atualizacoes["telefone"] = telefone or None

    if "bairro" in dados.model_fields_set:
        bairro = dados.bairro.strip() if dados.bairro else ""
        atualizacoes["bairro"] = bairro or None

    if "data_nascimento" in dados.model_fields_set:
        if dados.data_nascimento is not None and dados.data_nascimento > date.today():
            raise HTTPException(
                status_code=400,
                detail="data_nascimento_invalida",
            )
        atualizacoes["data_nascimento"] = dados.data_nascimento

    if dados.foto_base64 is not None:
        if not dados.consentimento_foto:
            raise HTTPException(status_code=400, detail="consentimento_foto_obrigatorio")
        if not dados.foto_media_type:
            raise HTTPException(status_code=400, detail="foto_invalida")
        try:
            conteudo = base64.b64decode(dados.foto_base64, validate=True)
        except (ValueError, binascii.Error) as erro:
            raise HTTPException(status_code=400, detail="foto_invalida") from erro
        atualizacoes["foto_perfil"] = normalizar_foto_aluno(dados.foto_media_type, conteudo)
        atualizacoes["foto_media_type"] = "image/jpeg"

    if not atualizacoes:
        raise HTTPException(status_code=400, detail="nenhum_campo_para_atualizar")

    campos = ("documento", "telefone", "bairro", "data_nascimento", "foto_perfil", "foto_media_type")
    nomes = [campo for campo in campos if campo in atualizacoes]
    atribuicoes = ", ".join(f"{campo} = %s" for campo in nomes)
    parametros = [atualizacoes[campo] for campo in nomes]
    parametros.extend((aluno_id, usuario["academia_id"]))

    try:
        with get_connection() as conn:
            aluno = conn.execute(
                "UPDATE alunos SET "
                + atribuicoes
                + " WHERE id = %s AND academia_id = %s "
                "RETURNING id, documento, telefone, data_nascimento, foto_perfil IS NOT NULL AS foto_disponivel",
                parametros,
            ).fetchone()
    except errors.UniqueViolation as erro:
        raise HTTPException(
            status_code=409,
            detail="documento_ja_cadastrado",
        ) from erro

    if aluno is None:
        raise HTTPException(status_code=404, detail="aluno_nao_encontrado")
    return aluno


@app.patch("/alunos/{aluno_id}/plano")
def atribuir_plano_aluno(
    aluno_id: int,
    dados: AtualizacaoPlanoAluno,
    usuario=Depends(usuario_de_academia),
):
    """Assign the first plan and open charge for an existing student.

    Students can be registered without a plan, but a charge must never be
    created or paid before the plan is explicitly selected.  The operation is
    kept in one transaction so the plan and its first charge cannot diverge.
    """
    exigir_escrita_local()
    academia_id = usuario["academia_id"]

    with get_connection() as conn:
        tem_moeda = esquema_de_moeda_disponivel(conn)
        sincronizacao = outbox_ativa()
        aluno_colunas = "id, nome, plano_id"
        if sincronizacao:
            aluno_colunas += ", sync_id, data_inicio"
        aluno = conn.execute(
            f"SELECT {aluno_colunas} FROM alunos "
            "WHERE id = %s AND academia_id = %s FOR UPDATE",
            (aluno_id, academia_id),
        ).fetchone()
        if aluno is None:
            raise HTTPException(status_code=404, detail="aluno_nao_encontrado")

        plano_colunas = "id, nome, valor"
        if tem_moeda:
            plano_colunas += ", moeda"
        if sincronizacao:
            plano_colunas += ", sync_id"
        plano = conn.execute(
            f"SELECT {plano_colunas} FROM planos "
            "WHERE id = %s AND academia_id = %s FOR SHARE",
            (dados.plano_id, academia_id),
        ).fetchone()
        if plano is None:
            raise HTTPException(status_code=400, detail="plano_invalido")

        if aluno["plano_id"] is not None:
            if aluno["plano_id"] != dados.plano_id:
                raise HTTPException(status_code=409, detail="plano_ja_atribuido")
            pagamento = conn.execute(
                "SELECT id FROM pagamentos WHERE academia_id = %s AND aluno_id = %s "
                "AND status = 'em_aberto' ORDER BY vencimento, id LIMIT 1",
                (academia_id, aluno_id),
            ).fetchone()
            return {
                "id": aluno["id"],
                "plano_id": plano["id"],
                "plano": plano["nome"],
                "pagamento_id": pagamento["id"] if pagamento else None,
                "criado": False,
            }

        atualizado = conn.execute(
            "UPDATE alunos SET plano_id = %s "
            "WHERE id = %s AND academia_id = %s "
            + ("RETURNING id, nome, plano_id, sync_id, data_inicio" if sincronizacao
               else "RETURNING id, nome, plano_id"),
            (dados.plano_id, aluno_id, academia_id),
        ).fetchone()
        if atualizado is None:
            raise HTTPException(status_code=404, detail="aluno_nao_encontrado")

        pagamento_colunas = "id, valor, vencimento, status"
        if tem_moeda:
            pagamento_colunas += ", moeda"
        if sincronizacao:
            pagamento_colunas += ", sync_id"
        pagamento = conn.execute(
            f"SELECT {pagamento_colunas} FROM pagamentos "
            "WHERE academia_id = %s AND aluno_id = %s AND status = 'em_aberto' "
            "ORDER BY vencimento, id LIMIT 1 FOR UPDATE",
            (academia_id, aluno_id),
        ).fetchone()
        moeda = plano["moeda"] if tem_moeda else usuario["moeda"]
        if pagamento is None:
            if tem_moeda and sincronizacao:
                pagamento = conn.execute(
                    "INSERT INTO pagamentos (academia_id, aluno_id, valor, moeda, vencimento) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "RETURNING id, valor, moeda, vencimento, status, sync_id",
                    (academia_id, aluno_id, plano["valor"], moeda, date.today()),
                ).fetchone()
            elif tem_moeda:
                pagamento = conn.execute(
                    "INSERT INTO pagamentos (academia_id, aluno_id, valor, moeda, vencimento) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id, valor, moeda, vencimento, status",
                    (academia_id, aluno_id, plano["valor"], moeda, date.today()),
                ).fetchone()
            elif sincronizacao:
                pagamento = conn.execute(
                    "INSERT INTO pagamentos (academia_id, aluno_id, valor, vencimento) "
                    "VALUES (%s, %s, %s, %s) "
                    "RETURNING id, valor, vencimento, status, sync_id",
                    (academia_id, aluno_id, plano["valor"], date.today()),
                ).fetchone()
                pagamento["moeda"] = moeda
            else:
                pagamento = conn.execute(
                    "INSERT INTO pagamentos (academia_id, aluno_id, valor, vencimento) "
                    "VALUES (%s, %s, %s, %s) RETURNING id, valor, vencimento, status",
                    (academia_id, aluno_id, plano["valor"], date.today()),
                ).fetchone()
                pagamento["moeda"] = moeda
        elif tem_moeda:
            pagamento = conn.execute(
                "UPDATE pagamentos SET valor = %s, moeda = %s WHERE id = %s "
                "RETURNING id, valor, moeda, vencimento, status" + (", sync_id" if sincronizacao else ""),
                (plano["valor"], moeda, pagamento["id"]),
            ).fetchone()
        else:
            pagamento = conn.execute(
                "UPDATE pagamentos SET valor = %s WHERE id = %s "
                "RETURNING id, valor, vencimento, status" + (", sync_id" if sincronizacao else ""),
                (plano["valor"], pagamento["id"]),
            ).fetchone()
            pagamento["moeda"] = moeda

        if sincronizacao:
            academia_uuid = sync_id_academia(conn, academia_id)
            enfileirar_evento(
                conn,
                academia_sync_id=academia_uuid,
                entity_type="aluno",
                entity_sync_id=atualizado["sync_id"],
                payload={
                    "id": str(atualizado["sync_id"]),
                    "nome": atualizado["nome"],
                    "status": "ativo",
                    "plano_id": str(plano["sync_id"]),
                    "data_inicio": atualizado["data_inicio"].isoformat(),
                },
            )
            enfileirar_evento(
                conn,
                academia_sync_id=academia_uuid,
                entity_type="pagamento",
                entity_sync_id=pagamento["sync_id"],
                payload={
                    "id": str(pagamento["sync_id"]),
                    "aluno_id": str(atualizado["sync_id"]),
                    "valor": str(pagamento["valor"]),
                    "moeda": pagamento["moeda"],
                    "vencimento": pagamento["vencimento"].isoformat(),
                    "data_pagamento": None,
                    "status": pagamento["status"],
                },
            )

    return {
        "id": atualizado["id"],
        "plano_id": plano["id"],
        "plano": plano["nome"],
        "pagamento_id": pagamento["id"],
        "criado": True,
    }


@app.patch("/alunos/{aluno_id}/status")
def mudar_status_aluno(
    aluno_id: int,
    status: StatusAluno,
    dono=Depends(somente_dono),
):
    exigir_escrita_local()
    status_texto = "ativo" if status.ativo else "inativo"

    with get_connection() as conn:
        if status.ativo:
            atual = conn.execute(
                "SELECT status FROM alunos WHERE id = %s AND academia_id = %s",
                (aluno_id, dono["academia_id"]),
            ).fetchone()
            if atual is not None and atual["status"] != "ativo":
                _exigir_vaga_de_aluno(conn, dono["academia_id"])
        if outbox_ativa():
            aluno = conn.execute(
                "UPDATE alunos "
                "SET status = %s "
                "WHERE id = %s AND academia_id = %s "
                "RETURNING id, sync_id, nome, bairro, status, plano_id, data_inicio",
                (status_texto, aluno_id, dono["academia_id"]),
            ).fetchone()
            if aluno is not None:
                plano_sync_id = None
                if aluno["plano_id"] is not None:
                    plano = conn.execute(
                        "SELECT sync_id FROM planos "
                        "WHERE id = %s AND academia_id = %s",
                        (aluno["plano_id"], dono["academia_id"]),
                    ).fetchone()
                    plano_sync_id = str(plano["sync_id"]) if plano else None
                enfileirar_evento(
                    conn,
                    academia_sync_id=sync_id_academia(conn, dono["academia_id"]),
                    entity_type="aluno",
                    entity_sync_id=aluno["sync_id"],
                    payload={
                        "id": str(aluno["sync_id"]),
                        "nome": aluno["nome"],
                        "bairro": aluno["bairro"],
                        "status": aluno["status"],
                        "plano_id": plano_sync_id,
                        "data_inicio": aluno["data_inicio"].isoformat(),
                    },
                )
        else:
            aluno = conn.execute(
                "UPDATE alunos "
                "SET status = %s "
                "WHERE id = %s AND academia_id = %s "
                "RETURNING id, nome, status",
                (status_texto, aluno_id, dono["academia_id"]),
            ).fetchone()

    if aluno is None:
        raise HTTPException(status_code=404, detail="aluno_nao_encontrado")

    return {"id": aluno["id"], "nome": aluno["nome"], "status": aluno["status"]}


@app.get("/presencas")
def listar_presencas(
    limite: int = Query(default=100, ge=1, le=500),
    depois: int | None = Query(default=None, ge=0),
    usuario=Depends(usuario_de_academia),
):
    if usuario["papel"] not in {"dono", "recepcao"}:
        raise HTTPException(status_code=403, detail="sem_permissao")

    with get_connection() as conn:
        linhas = conn.execute(
            "SELECT p.id, p.data_hora, p.liberado, p.motivo, "
            "p.aluno_id, p.metodo_identificacao, p.confianca, "
            "a.nome AS nome_aluno "
            "FROM presencas p "
            "LEFT JOIN alunos a "
            "ON a.id = p.aluno_id AND a.academia_id = p.academia_id "
            "WHERE p.academia_id = %s "
            + ("AND p.id > %s " if depois is not None else "")
            + ("ORDER BY p.id ASC " if depois is not None else "ORDER BY p.id DESC ")
            + "LIMIT %s",
            (usuario["academia_id"], depois, limite) if depois is not None
            else (usuario["academia_id"], limite),
        ).fetchall()

    return linhas


@app.get("/presencas/mapa-calor")
def mapa_calor_presencas(
    periodo: int = Query(default=90, ge=7, le=365),
    usuario=Depends(usuario_de_academia),
):
    """Return access intensity by weekday and hour for the academy dashboard."""
    if usuario["papel"] not in {"dono", "recepcao"}:
        raise HTTPException(status_code=403, detail="sem_permissao")
    with get_connection() as conn:
        pontos = conn.execute(
            "SELECT EXTRACT(DOW FROM p.data_hora)::int AS dia_semana, "
            "EXTRACT(HOUR FROM p.data_hora)::int AS hora, COUNT(*)::int AS total, "
            "COUNT(*) FILTER (WHERE p.liberado)::int AS liberados "
            "FROM presencas p WHERE p.academia_id = %s "
            "AND p.data_hora >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day') "
            "GROUP BY 1, 2 ORDER BY 1, 2",
            (usuario["academia_id"], periodo),
        ).fetchall()
        academia = conn.execute(
            "SELECT pais, cidade, estado FROM academias WHERE id = %s",
            (usuario["academia_id"],),
        ).fetchone()
    return {"periodo_dias": periodo, "pontos": pontos, "regiao": academia or {}}


@app.get("/pagamentos")
def listar_pagamentos(
    aluno_id: int | None = Query(default=None, gt=0),
    filtro: str = Query(default="todos"),
    usuario=Depends(usuario_de_academia),
):
    if filtro not in {"todos", "abertos", "atrasados", "pagos"}:
        raise HTTPException(status_code=400, detail="filtro_de_pagamentos_invalido")

    academia_id = usuario["academia_id"]
    condicoes = ["p.academia_id = %s"]
    parametros: list[object] = [academia_id]
    if aluno_id is not None:
        condicoes.append("p.aluno_id = %s")
        parametros.append(aluno_id)
    if filtro == "abertos":
        condicoes.append("p.status = 'em_aberto'")
    elif filtro == "atrasados":
        condicoes.append("p.status = 'em_aberto' AND p.vencimento < CURRENT_DATE")
    elif filtro == "pagos":
        condicoes.append("p.status = 'pago'")

    with get_connection() as conn:
        if esquema_de_moeda_disponivel(conn):
            linhas = conn.execute(
                "SELECT p.id, p.aluno_id, a.nome AS aluno_nome, a.plano_id AS aluno_plano_id, p.valor, p.moeda, "
                "p.vencimento, p.data_pagamento, p.status, "
                "(p.status = 'em_aberto' AND p.vencimento < CURRENT_DATE) AS atrasado "
                "FROM pagamentos p JOIN alunos a ON a.id = p.aluno_id "
                "WHERE " + " AND ".join(condicoes) + " "
                "ORDER BY (p.status = 'em_aberto') DESC, p.vencimento, p.id",
                parametros,
            ).fetchall()
        else:
            linhas = conn.execute(
                "SELECT p.id, p.aluno_id, a.nome AS aluno_nome, a.plano_id AS aluno_plano_id, p.valor, "
                "p.vencimento, p.data_pagamento, p.status, "
                "(p.status = 'em_aberto' AND p.vencimento < CURRENT_DATE) AS atrasado "
                "FROM pagamentos p JOIN alunos a ON a.id = p.aluno_id "
                "WHERE " + " AND ".join(condicoes) + " "
                "ORDER BY (p.status = 'em_aberto') DESC, p.vencimento, p.id",
                parametros,
            ).fetchall()
            linhas = [{**linha, "moeda": usuario["moeda"]} for linha in linhas]

    return linhas


TAMANHO_MAXIMO_QR = 2 * 1024 * 1024
TIPOS_QR_PERMITIDOS = {"image/png", "image/jpeg", "image/webp"}


def imagem_qr_valida(tipo: str, conteudo: bytes) -> bool:
    if tipo == "image/png":
        return conteudo.startswith(b"\x89PNG\r\n\x1a\n")
    if tipo == "image/jpeg":
        return conteudo.startswith(b"\xff\xd8\xff")
    if tipo == "image/webp":
        return (
            len(conteudo) >= 12
            and conteudo.startswith(b"RIFF")
            and conteudo[8:12] == b"WEBP"
        )
    return False


def exigir_migracao_frequency(conn) -> None:
    presente = conn.execute(
        "SELECT to_regclass('public.faturas_frequency') IS NOT NULL AS presente"
    ).fetchone()["presente"]
    if not presente:
        raise HTTPException(status_code=503, detail="migracao_frequency_pendente")


def auditar_frequency(conn, admin_id: int, acao: str, entidade: str, entidade_id, detalhes=None) -> None:
    conn.execute(
        "INSERT INTO public.auditoria_frequency "
        "(ator_id, acao, entidade, entidade_id, detalhes) "
        "VALUES (%s, %s, %s, %s, %s)",
        (admin_id, acao, entidade, str(entidade_id) if entidade_id is not None else None, Jsonb(detalhes or {})),
    )


def exigir_migracao_prospeccao(conn) -> None:
    presente = conn.execute(
        "SELECT to_regclass('public.leads_prospeccao') IS NOT NULL AS presente"
    ).fetchone()["presente"]
    if not presente:
        raise HTTPException(status_code=503, detail="migracao_prospeccao_pendente")


def exigir_configuracao_prospeccao(conn) -> None:
    presente = conn.execute(
        "SELECT to_regclass('public.configuracao_prospeccao') IS NOT NULL AS presente"
    ).fetchone()["presente"]
    if not presente:
        raise HTTPException(status_code=503, detail="migracao_configuracao_prospeccao_pendente")


def configuracao_prospeccao(conn) -> dict:
    config = conn.execute(
        "SELECT whatsapp_template, email_assunto_template, email_corpo_template "
        ", imagem IS NOT NULL AS imagem_cadastrada "
        "FROM public.configuracao_prospeccao WHERE id IS TRUE"
    ).fetchone()
    return dict(config) if config is not None else {
        "whatsapp_template": TEMPLATE_WHATSAPP_PADRAO,
        "email_assunto_template": TEMPLATE_EMAIL_ASSUNTO_PADRAO,
        "email_corpo_template": TEMPLATE_EMAIL_CORPO_PADRAO,
        "imagem_cadastrada": False,
    }


def serializar_lead_prospeccao(lead, templates: dict | None = None) -> dict:
    resultado = dict(lead)
    templates = templates or configuracao_padrao_prospeccao()
    resultado["email_assunto"] = renderizar_template(templates["email_assunto_template"], resultado["nome"], resultado["cidade"])
    resultado["email_corpo"] = renderizar_template(templates["email_corpo_template"], resultado["nome"], resultado["cidade"])
    resultado["whatsapp_mensagem"] = renderizar_template(templates["whatsapp_template"], resultado["nome"], resultado["cidade"])
    return resultado


def configuracao_padrao_prospeccao() -> dict:
    return {
        "whatsapp_template": TEMPLATE_WHATSAPP_PADRAO,
        "email_assunto_template": TEMPLATE_EMAIL_ASSUNTO_PADRAO,
        "email_corpo_template": TEMPLATE_EMAIL_CORPO_PADRAO,
    }


def normalizar_dados_lead(dados: dict) -> dict:
    for campo in ("nome", "cidade", "endereco", "telefone", "email", "site_instagram", "observacoes"):
        if campo in dados and isinstance(dados[campo], str):
            dados[campo] = dados[campo].strip()
    return dados


def inserir_lead_prospeccao(conn, dados: dict, admin_id: int):
    return conn.execute(
        "INSERT INTO public.leads_prospeccao "
        "(nome, cidade, endereco, telefone, email, whatsapp_opt_in, site_instagram, avaliacao, observacoes, prioridade, "
        "status_comercial, ultimo_contato, origem, criado_por, atualizado_por) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "RETURNING id, nome, cidade, endereco, telefone, email, site_instagram, avaliacao, observacoes, "
        "prioridade, status_comercial, ultimo_contato, origem, whatsapp_opt_in, criado_em, atualizado_em",
        (*[dados[chave] for chave in ("nome", "cidade", "endereco", "telefone", "email", "whatsapp_opt_in", "site_instagram", "avaliacao", "observacoes", "prioridade", "status_comercial", "ultimo_contato", "origem")], admin_id, admin_id),
    ).fetchone()


@app.get("/admin/prospeccao/configuracao")
def ler_configuracao_prospeccao(admin=Depends(somente_admin_plataforma)):
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        exigir_configuracao_prospeccao(conn)
        return configuracao_prospeccao(conn)


@app.get("/admin/prospeccao/imagem")
def ler_imagem_prospeccao(admin=Depends(somente_admin_plataforma)):
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        exigir_configuracao_prospeccao(conn)
        imagem = conn.execute(
            "SELECT imagem, imagem_media_type FROM public.configuracao_prospeccao WHERE id IS TRUE"
        ).fetchone()
    if imagem is None or imagem["imagem"] is None:
        raise HTTPException(status_code=404, detail="imagem_prospeccao_nao_cadastrada")
    return Response(
        imagem["imagem"], media_type=imagem["imagem_media_type"] or "image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.put("/admin/prospeccao/imagem")
async def salvar_imagem_prospeccao(request: Request, admin=Depends(somente_admin_plataforma)):
    exigir_escrita_local()
    tipo = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    imagem = normalizar_foto_aluno(tipo, await request.body())
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        exigir_configuracao_prospeccao(conn)
        conn.execute(
            "INSERT INTO public.configuracao_prospeccao (id, imagem, imagem_media_type, atualizado_por) "
            "VALUES (TRUE, %s, 'image/jpeg', %s) ON CONFLICT (id) DO UPDATE SET "
            "imagem = EXCLUDED.imagem, imagem_media_type = EXCLUDED.imagem_media_type, "
            "atualizado_em = CURRENT_TIMESTAMP, atualizado_por = EXCLUDED.atualizado_por",
            (imagem, admin["id"]),
        )
        auditar_frequency(conn, admin["id"], "imagem_prospeccao_atualizada", "configuracao_prospeccao", True, {})
    return {"imagem_cadastrada": True}


@app.patch("/admin/prospeccao/configuracao")
def salvar_configuracao_prospeccao(dados: ConfiguracaoProspeccao, admin=Depends(somente_admin_plataforma)):
    exigir_escrita_local()
    alteracoes = dados.model_dump(exclude_unset=True)
    if not alteracoes or any(not isinstance(valor, str) or not valor.strip() for valor in alteracoes.values()):
        raise HTTPException(status_code=400, detail="template_comercial_obrigatorio")
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        exigir_configuracao_prospeccao(conn)
        valores = {**configuracao_prospeccao(conn), **{chave: valor.strip() for chave, valor in alteracoes.items()}}
        config = conn.execute(
            "INSERT INTO public.configuracao_prospeccao "
            "(id, whatsapp_template, email_assunto_template, email_corpo_template, atualizado_por) "
            "VALUES (TRUE, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET "
            "whatsapp_template = EXCLUDED.whatsapp_template, "
            "email_assunto_template = EXCLUDED.email_assunto_template, "
            "email_corpo_template = EXCLUDED.email_corpo_template, "
            "atualizado_em = CURRENT_TIMESTAMP, atualizado_por = EXCLUDED.atualizado_por "
            "RETURNING whatsapp_template, email_assunto_template, email_corpo_template",
            (valores["whatsapp_template"], valores["email_assunto_template"], valores["email_corpo_template"], admin["id"]),
        ).fetchone()
        auditar_frequency(conn, admin["id"], "configuracao_prospeccao_atualizada", "configuracao_prospeccao", True, {})
    return config


@app.get("/admin/prospeccao/leads")
def listar_leads_prospeccao(
    prioridade: str | None = Query(default=None, pattern=r"^[ABC]$"),
    status: str | None = Query(default=None, pattern=r"^(nao_contatado|mensagem_enviada|respondeu|demonstracao|interessado|cliente|nao_interessado)$"),
    cidade: str | None = Query(default=None, max_length=120),
    admin=Depends(somente_admin_plataforma),
):
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        exigir_configuracao_prospeccao(conn)
        config = configuracao_prospeccao(conn)
        clausulas = ["excluido_em IS NULL"]
        valores = []
        if prioridade:
            clausulas.append("prioridade = %s")
            valores.append(prioridade)
        if status:
            clausulas.append("status_comercial = %s")
            valores.append(status)
        if cidade and cidade.strip():
            clausulas.append("cidade ILIKE %s")
            valores.append(f"%{cidade.strip()}%")
        leads = conn.execute(
            "SELECT id, nome, cidade, endereco, telefone, email, whatsapp_opt_in, site_instagram, avaliacao, observacoes, "
            "prioridade, status_comercial, ultimo_contato, origem, criado_em, atualizado_em "
            "FROM public.leads_prospeccao WHERE " + " AND ".join(clausulas) + " "
            "ORDER BY CASE prioridade WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END, nome, id",
            valores,
        ).fetchall()
        funil = conn.execute(
            "SELECT count(*) AS total, "
            "count(*) FILTER (WHERE prioridade = 'A') AS prioridade_a, "
            "count(*) FILTER (WHERE prioridade = 'B') AS prioridade_b, "
            "count(*) FILTER (WHERE prioridade = 'C') AS prioridade_c, "
            "count(*) FILTER (WHERE status_comercial = 'nao_contatado') AS nao_contatado, "
            "count(*) FILTER (WHERE status_comercial = 'mensagem_enviada') AS mensagem_enviada, "
            "count(*) FILTER (WHERE status_comercial = 'respondeu') AS respondeu, "
            "count(*) FILTER (WHERE status_comercial = 'demonstracao') AS demonstracao, "
            "count(*) FILTER (WHERE status_comercial = 'interessado') AS interessado, "
            "count(*) FILTER (WHERE status_comercial = 'cliente') AS cliente, "
            "count(*) FILTER (WHERE status_comercial = 'nao_interessado') AS nao_interessado "
            "FROM public.leads_prospeccao WHERE excluido_em IS NULL"
        ).fetchone()
    return {"leads": [serializar_lead_prospeccao(lead, config) for lead in leads], "funil": funil}


@app.post("/admin/prospeccao/leads", status_code=201)
def criar_lead_prospeccao(novo: NovoLeadProspeccao, admin=Depends(somente_admin_plataforma)):
    exigir_escrita_local()
    dados = normalizar_dados_lead(novo.model_dump())
    if dados["status_comercial"] != "nao_contatado" and dados["ultimo_contato"] is None:
        dados["ultimo_contato"] = date.today()
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        exigir_configuracao_prospeccao(conn)
        config = configuracao_prospeccao(conn)
        lead = inserir_lead_prospeccao(conn, dados, admin["id"])
        auditar_frequency(conn, admin["id"], "lead_prospeccao_criado", "lead_prospeccao", lead["id"], {"nome": lead["nome"]})
    return serializar_lead_prospeccao(lead, config)


@app.post("/admin/prospeccao/importar", status_code=201)
def importar_leads_prospeccao(importacao: ImportacaoLeadsProspeccao, admin=Depends(somente_admin_plataforma)):
    exigir_escrita_local()
    criados = []
    ignorados = 0
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        exigir_configuracao_prospeccao(conn)
        config = configuracao_prospeccao(conn)
        for item in importacao.leads:
            dados = normalizar_dados_lead(item.model_dump())
            dados["origem"] = "csv"
            existente = conn.execute(
                "SELECT id FROM public.leads_prospeccao WHERE excluido_em IS NULL "
                "AND lower(nome) = lower(%s) AND lower(cidade) = lower(%s)",
                (dados["nome"], dados["cidade"]),
            ).fetchone()
            if existente:
                ignorados += 1
                continue
            criados.append(inserir_lead_prospeccao(conn, dados, admin["id"]))
        if criados:
            auditar_frequency(conn, admin["id"], "leads_prospeccao_importados", "lead_prospeccao", None, {"criados": len(criados), "ignorados": ignorados})
    return {"criados": [serializar_lead_prospeccao(lead, config) for lead in criados], "ignorados": ignorados}


@app.patch("/admin/prospeccao/leads/{lead_id}")
def editar_lead_prospeccao(lead_id: int, atualizacao: AtualizacaoLeadProspeccao, admin=Depends(somente_admin_plataforma)):
    exigir_escrita_local()
    dados = atualizacao.model_dump(exclude_unset=True)
    if not dados or any(valor is None for valor in dados.values()):
        raise HTTPException(status_code=400, detail="campos_invalidos_para_atualizacao")
    dados = normalizar_dados_lead(dados)
    if dados.get("status_comercial") not in {None, "nao_contatado"} and "ultimo_contato" not in dados:
        dados["ultimo_contato"] = date.today()
    if dados.get("whatsapp_opt_in") is True:
        dados["whatsapp_opt_in_em"] = datetime.now(timezone.utc)
    campos = ("nome", "cidade", "endereco", "telefone", "email", "whatsapp_opt_in", "whatsapp_opt_in_em", "site_instagram", "avaliacao", "observacoes", "prioridade", "status_comercial", "ultimo_contato")
    alterados = [campo for campo in campos if campo in dados]
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        exigir_configuracao_prospeccao(conn)
        config = configuracao_prospeccao(conn)
        lead = conn.execute(
            "UPDATE public.leads_prospeccao SET " + ", ".join(f"{campo} = %s" for campo in alterados)
            + ", atualizado_em = CURRENT_TIMESTAMP, atualizado_por = %s "
            "WHERE id = %s AND excluido_em IS NULL "
            "RETURNING id, nome, cidade, endereco, telefone, email, whatsapp_opt_in, site_instagram, avaliacao, observacoes, "
            "prioridade, status_comercial, ultimo_contato, origem, criado_em, atualizado_em",
            (*[dados[campo] for campo in alterados], admin["id"], lead_id),
        ).fetchone()
        if lead is not None:
            auditar_frequency(conn, admin["id"], "lead_prospeccao_atualizado", "lead_prospeccao", lead_id, {"campos": alterados})
    if lead is None:
        raise HTTPException(status_code=404, detail="lead_prospeccao_nao_encontrado")
    return serializar_lead_prospeccao(lead, config)


@app.delete("/admin/prospeccao/leads/{lead_id}")
def excluir_lead_prospeccao(lead_id: int, admin=Depends(somente_admin_plataforma)):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        exigir_configuracao_prospeccao(conn)
        lead = conn.execute(
            "UPDATE public.leads_prospeccao SET excluido_em = CURRENT_TIMESTAMP, excluido_por = %s, "
            "atualizado_em = CURRENT_TIMESTAMP, atualizado_por = %s "
            "WHERE id = %s AND excluido_em IS NULL RETURNING id, nome",
            (admin["id"], admin["id"], lead_id),
        ).fetchone()
        if lead is not None:
            auditar_frequency(conn, admin["id"], "lead_prospeccao_excluido", "lead_prospeccao", lead_id, {"nome": lead["nome"]})
    if lead is None:
        raise HTTPException(status_code=404, detail="lead_prospeccao_nao_encontrado")
    return {"excluido": True, "id": lead_id}


@app.get("/admin/prospeccao/regioes")
def listar_regioes_prospeccao(admin=Depends(somente_admin_plataforma)):
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        return conn.execute("SELECT * FROM public.prospeccao_regioes ORDER BY ativa DESC, nome").fetchall()

@app.post("/admin/prospeccao/regioes", status_code=201)
def criar_regiao_prospeccao(regiao: RegiaoProspeccao, admin=Depends(somente_admin_plataforma)):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        return conn.execute("INSERT INTO public.prospeccao_regioes (nome,pais,cidade,bairro,latitude,longitude,raio_metros,ativa,criado_por) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *", (regiao.nome.strip(),regiao.pais.strip(),regiao.cidade.strip(),regiao.bairro.strip(),regiao.latitude,regiao.longitude,regiao.raio_metros,regiao.ativa,admin["id"])).fetchone()

@app.post("/admin/prospeccao/regioes/{regiao_id}/buscar")
def buscar_regiao_prospeccao(regiao_id: int, admin=Depends(somente_admin_plataforma)):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn); exigir_configuracao_prospeccao(conn)
        regiao=conn.execute("SELECT * FROM public.prospeccao_regioes WHERE id=%s AND ativa",(regiao_id,)).fetchone()
    if regiao is None: raise HTTPException(status_code=404, detail="regiao_prospeccao_nao_encontrada")
    latitude, longitude = regiao["latitude"], regiao["longitude"]
    if latitude is None or longitude is None:
        try: coordenadas = geocodificar_regiao(regiao["pais"], regiao["cidade"], regiao["bairro"])
        except Exception as exc: raise HTTPException(status_code=502, detail="geocodificacao_indisponivel") from exc
        if coordenadas is None: raise HTTPException(status_code=422, detail="regiao_sem_coordenadas")
        latitude, longitude = coordenadas
        with get_connection() as conn: conn.execute("UPDATE public.prospeccao_regioes SET latitude=%s, longitude=%s WHERE id=%s", (latitude, longitude, regiao_id))
    try: elementos=consultar_osm(float(latitude),float(longitude),regiao["raio_metros"])
    except Exception as exc: raise HTTPException(status_code=502, detail="fonte_osm_indisponivel") from exc
    criados=ignorados=0; vistos=set()
    with get_connection() as conn:
        for elemento in elementos[:500]:
            dados=lead_osm(elemento,regiao["cidade"],regiao["pais"]); chave=(dados["nome"].casefold(),dados["cidade"].casefold(),dados["endereco"].casefold())
            if chave in vistos or conn.execute("SELECT 1 FROM public.leads_prospeccao WHERE excluido_em IS NULL AND lower(nome)=lower(%s) AND lower(cidade)=lower(%s) AND lower(endereco)=lower(%s)",(dados["nome"],dados["cidade"],dados["endereco"])).fetchone(): ignorados+=1; continue
            vistos.add(chave); inserir_lead_prospeccao(conn,dados,admin["id"]); criados+=1
        conn.execute("UPDATE public.prospeccao_regioes SET ultima_busca=CURRENT_TIMESTAMP WHERE id=%s",(regiao_id,))
    return {"encontrados":len(elementos),"criados":criados,"ignorados":ignorados}

@app.post("/admin/prospeccao/regioes/{regiao_id}/buscar-apify")
def buscar_regiao_apify(regiao_id: int, admin=Depends(somente_admin_plataforma)):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn); exigir_configuracao_prospeccao(conn)
        regiao = conn.execute("SELECT * FROM public.prospeccao_regioes WHERE id=%s AND ativa", (regiao_id,)).fetchone()
    if regiao is None: raise HTTPException(status_code=404, detail="regiao_prospeccao_nao_encontrada")
    local = ", ".join(filter(None, [regiao["bairro"], regiao["cidade"], regiao["pais"]]))
    try: itens = buscar_apify(["academia", "gym", "fitness"], local, 1000)
    except Exception as exc: raise HTTPException(status_code=502, detail="apify_indisponivel") from exc
    criados = ignorados = 0
    with get_connection() as conn:
        for item in itens[:1000]:
            dados = lead_apify(item, regiao["pais"], regiao["cidade"])
            existente = conn.execute("SELECT id, telefone, email, site_instagram FROM public.leads_prospeccao WHERE excluido_em IS NULL AND lower(nome)=lower(%s) AND lower(cidade)=lower(%s) AND lower(endereco)=lower(%s)", (dados["nome"], dados["cidade"], dados["endereco"])).fetchone()
            if existente:
                alteracoes = {}
                if not existente["telefone"] and dados["telefone"]: alteracoes["telefone"] = dados["telefone"]
                if not existente["email"] and dados["email"]: alteracoes["email"] = dados["email"]
                if not existente["site_instagram"] and dados["site_instagram"]: alteracoes["site_instagram"] = dados["site_instagram"]
                if alteracoes:
                    conn.execute("UPDATE public.leads_prospeccao SET " + ", ".join(f"{campo}=%s" for campo in alteracoes) + ", atualizado_em=CURRENT_TIMESTAMP, atualizado_por=%s WHERE id=%s", (*alteracoes.values(), admin["id"], existente["id"]))
                    criados += 1
                else:
                    ignorados += 1
                continue
            inserir_lead_prospeccao(conn, dados, admin["id"]); criados += 1
        conn.execute("UPDATE public.prospeccao_regioes SET ultima_busca=CURRENT_TIMESTAMP WHERE id=%s", (regiao_id,))
    return {"encontrados": len(itens), "criados": criados, "ignorados": ignorados}

@app.post("/admin/prospeccao/enriquecer-contatos")
def enriquecer_contatos_prospeccao(
    limite: int = Query(default=3, ge=1, le=1000),
    ids: str | None = Query(default=None),
    admin=Depends(somente_admin_plataforma),
):
    """Tenta completar contatos em sites públicos sem depender de um provedor externo."""
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        selected_ids = []
        if ids:
            for raw_id in ids.split(","):
                try:
                    value = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if value > 0 and value not in selected_ids:
                    selected_ids.append(value)
            selected_ids = selected_ids[:limite]
        if selected_ids:
            placeholders = ", ".join(["%s"] * len(selected_ids))
            leads = conn.execute(
                "SELECT id, site_instagram, email, telefone FROM public.leads_prospeccao "
                f"WHERE excluido_em IS NULL AND id IN ({placeholders}) "
                "AND (email IS NULL OR trim(email)='' OR telefone IS NULL OR trim(telefone)='') "
                "ORDER BY id",
                tuple(selected_ids),
            ).fetchall()
        else:
            leads = conn.execute(
                "SELECT id, site_instagram, email, telefone FROM public.leads_prospeccao "
                "WHERE excluido_em IS NULL AND (email IS NULL OR trim(email)='' OR telefone IS NULL OR trim(telefone)='') "
                "ORDER BY id LIMIT %s", (limite,)
            ).fetchall()
        atualizados = 0
        tentados = 0
        for lead in leads:
            encontrados = buscar_contatos_publicos(lead["site_instagram"])
            campos = {}
            if not lead["email"] and encontrados["email"]:
                campos["email"] = encontrados["email"]
            if not lead["telefone"] and encontrados["telefone"]:
                campos["telefone"] = encontrados["telefone"]
            tentados += 1
            if campos:
                conn.execute("UPDATE public.leads_prospeccao SET " + ", ".join(f"{campo}=%s" for campo in campos) + ", atualizado_em=CURRENT_TIMESTAMP, atualizado_por=%s WHERE id=%s", (*campos.values(), admin["id"], lead["id"]))
                atualizados += 1
        return {"tentados": tentados, "atualizados": atualizados}

@app.post("/admin/prospeccao/confirmar-whatsapp-lote")
def confirmar_whatsapp_lote(admin=Depends(somente_admin_plataforma)):
    """Registra a confirmação administrativa única, sem fingir opt-in individual."""
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        resultado = conn.execute(
            "UPDATE public.leads_prospeccao SET whatsapp_autorizacao_admin_em=CURRENT_TIMESTAMP, whatsapp_autorizacao_admin_por=%s, atualizado_por=%s, atualizado_em=CURRENT_TIMESTAMP "
            "WHERE excluido_em IS NULL AND telefone IS NOT NULL AND trim(telefone) <> '' AND whatsapp_autorizacao_admin_em IS NULL "
            "RETURNING id", (admin["id"], admin["id"])
        ).fetchall()
        return {"confirmados": len(resultado), "criterio": "confirmacao_administrativa_em_lote"}

@app.get("/admin/frequency/resumo")
def resumo_frequency(admin=Depends(somente_admin_plataforma)):
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        receita = conn.execute(
            "SELECT to_char(date_trunc('month', data_pagamento), 'YYYY-MM') AS mes, "
            "moeda, count(*) AS faturas, sum(valor) AS recebido "
            "FROM public.faturas_frequency "
            "WHERE status = 'pago' AND data_pagamento >= "
            "date_trunc('month', CURRENT_DATE) - INTERVAL '11 months' "
            "GROUP BY 1, moeda ORDER BY 1, moeda"
        ).fetchall()
        abertas = conn.execute(
            "SELECT moeda, count(*) AS faturas, sum(valor) AS total, "
            "count(*) FILTER (WHERE vencimento < CURRENT_DATE) AS faturas_atrasadas, "
            "COALESCE(sum(valor) FILTER (WHERE vencimento < CURRENT_DATE), 0) AS total_atrasado "
            "FROM public.faturas_frequency WHERE status = 'em_aberto' "
            "GROUP BY moeda ORDER BY moeda"
        ).fetchall()
        academias = conn.execute(
            "SELECT count(*) AS total, "
            "count(*) FILTER (WHERE a.ativa) AS ativas "
            "FROM public.academias a"
        ).fetchone()
        assinantes = conn.execute(
            "SELECT count(*) FILTER (WHERE s.status = 'ativa') AS ativos, "
            "count(*) FILTER (WHERE s.status = 'suspensa') AS suspensos "
            "FROM public.assinaturas_frequency s"
        ).fetchone()
        vendas = conn.execute(
            "SELECT to_char(date_trunc('month', criada_em), 'YYYY-MM') AS mes, "
            "count(*) AS assinaturas FROM public.assinaturas_frequency "
            "WHERE criada_em >= date_trunc('month', CURRENT_DATE) - INTERVAL '11 months' "
            "GROUP BY 1 ORDER BY 1"
        ).fetchall()
        atraso = conn.execute(
            "SELECT count(*) FILTER (WHERE CURRENT_DATE - f.vencimento >= 2) AS em_atraso, "
            "count(*) FILTER (WHERE s.status IN ('suspensa', 'cancelada') "
            "OR CURRENT_DATE - f.vencimento >= 5) AS bloqueadas "
            "FROM public.academias a "
            "LEFT JOIN public.assinaturas_frequency s ON s.academia_id = a.id "
            "LEFT JOIN LATERAL (SELECT min(vencimento) AS vencimento "
            "FROM public.faturas_frequency WHERE academia_id = a.id AND status = 'em_aberto') f ON TRUE"
        ).fetchone()
    return {
        "academias": academias["total"],
        "academias_ativas": academias["ativas"],
        "assinaturas_ativas": assinantes["ativos"],
        "assinaturas_suspensas": assinantes["suspensos"],
        "faturas_em_atraso": atraso["em_atraso"],
        "academias_bloqueadas": atraso["bloqueadas"],
        "receita_mensal": receita,
        "vendas_mensais": vendas,
        "faturas_abertas_por_moeda": abertas,
    }


@app.get("/admin/frequency/planos")
def listar_planos_frequency(admin=Depends(somente_admin_plataforma)):
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        exigir_premium(conn)
        return conn.execute(
            "SELECT id, nome, descricao, valor, moeda, duracao_dias, ativo, nivel, cameras, youtube, max_monitores, max_leitores, max_alunos "
            "FROM public.planos_frequency ORDER BY id"
        ).fetchall()


@app.patch("/admin/frequency/planos/{plano_id}/status")
def mudar_status_plano_frequency(
    plano_id: int,
    status: StatusPlanoFrequency,
    admin=Depends(somente_admin_plataforma),
):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        exigir_premium(conn)
        conn.execute("SELECT pg_advisory_xact_lock(89430129)")
        atual = conn.execute("SELECT * FROM public.planos_frequency WHERE id = %s FOR UPDATE", (plano_id,)).fetchone()
        if atual:
            validar_plano(conn, {**atual, "ativo": status.ativo}, plano_id)
        plano = conn.execute(
            "UPDATE public.planos_frequency SET ativo = %s "
            "WHERE id = %s RETURNING id, ativo",
            (status.ativo, plano_id),
        ).fetchone()
        if plano is not None:
            auditar_frequency(conn, admin["id"], "plano_status_alterado", "plano", plano_id, {"ativo": status.ativo})
    if plano is None:
        raise HTTPException(status_code=404, detail="plano_frequency_nao_encontrado")
    return plano


@app.post("/admin/frequency/planos", status_code=201)
def criar_plano_frequency(
    novo: NovoPlanoFrequency,
    admin=Depends(somente_admin_plataforma),
):
    exigir_escrita_local()
    nome = novo.nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="nome_do_plano_obrigatorio")
    try:
        with get_connection() as conn:
            exigir_migracao_frequency(conn)
            validar_plano(conn, novo.model_dump())
            plano = conn.execute(
                "INSERT INTO public.planos_frequency "
                "(nome, descricao, valor, moeda, duracao_dias, nivel, cameras, youtube, max_monitores, max_leitores, max_alunos) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id, nome, descricao, valor, moeda, duracao_dias, ativo, nivel, cameras, youtube, max_monitores, max_leitores, max_alunos",
                (nome, novo.descricao.strip(), novo.valor, novo.moeda, novo.duracao_dias, novo.nivel, novo.cameras, novo.youtube, novo.max_monitores, novo.max_leitores, novo.max_alunos),
            ).fetchone()
            auditar_frequency(
                conn, admin["id"], "plano_criado", "plano", plano["id"],
                {"nome": plano["nome"], "valor": str(plano["valor"]), "moeda": plano["moeda"]},
            )
    except errors.UniqueViolation as erro:
        raise HTTPException(status_code=409, detail="plano_frequency_ja_cadastrado") from erro
    return plano


@app.patch("/admin/frequency/planos/{plano_id}")
def editar_plano_frequency(
    plano_id: int,
    dados: AtualizacaoPlanoFrequency,
    admin=Depends(somente_admin_plataforma),
):
    exigir_escrita_local()
    alteracoes = dados.model_dump(exclude_unset=True)
    if any(valor is None for valor in alteracoes.values()):
        raise HTTPException(status_code=400, detail="campos_nulos_nao_permitidos")
    if not alteracoes:
        raise HTTPException(status_code=400, detail="nenhuma_alteracao_informada")
    if "nome" in alteracoes:
        alteracoes["nome"] = alteracoes["nome"].strip()
        if not alteracoes["nome"]:
            raise HTTPException(status_code=400, detail="nome_do_plano_obrigatorio")
    if "descricao" in alteracoes and alteracoes["descricao"] is not None:
        alteracoes["descricao"] = alteracoes["descricao"].strip()

    try:
        with get_connection() as conn:
            exigir_migracao_frequency(conn)
            exigir_premium(conn)
            conn.execute("SELECT pg_advisory_xact_lock(89430129)")
            atual = conn.execute("SELECT * FROM public.planos_frequency WHERE id = %s FOR UPDATE", (plano_id,)).fetchone()
            if atual is None:
                raise HTTPException(404, "plano_frequency_nao_encontrado")
            validar_plano(conn, {**atual, **alteracoes}, plano_id)
            plano = conn.execute(
                "UPDATE public.planos_frequency SET "
                "nome = COALESCE(%s, nome), descricao = COALESCE(%s, descricao), "
                "valor = COALESCE(%s, valor), moeda = COALESCE(%s, moeda), "
                "duracao_dias = COALESCE(%s, duracao_dias), nivel = COALESCE(%s, nivel), "
                "cameras = COALESCE(%s, cameras), youtube = COALESCE(%s, youtube), "
                "max_monitores = COALESCE(%s, max_monitores), max_leitores = COALESCE(%s, max_leitores), max_alunos = COALESCE(%s, max_alunos) "
                "WHERE id = %s "
                "RETURNING id, nome, descricao, valor, moeda, duracao_dias, ativo, nivel, cameras, youtube, max_monitores, max_leitores, max_alunos",
                (
                    alteracoes.get("nome"), alteracoes.get("descricao"),
                    alteracoes.get("valor"), alteracoes.get("moeda"),
                    alteracoes.get("duracao_dias"), alteracoes.get("nivel"),
                    alteracoes.get("cameras"), alteracoes.get("youtube"),
                    alteracoes.get("max_monitores"), alteracoes.get("max_leitores"), alteracoes.get("max_alunos"), plano_id,
                ),
            ).fetchone()
            if plano is not None:
                auditar_frequency(
                    conn, admin["id"], "plano_atualizado", "plano", plano_id,
                    {"campos": sorted(alteracoes.keys())},
                )
    except errors.UniqueViolation as erro:
        raise HTTPException(status_code=409, detail="plano_frequency_ja_cadastrado") from erro
    if plano is None:
        raise HTTPException(status_code=404, detail="plano_frequency_nao_encontrado")
    return plano


@app.get("/admin/frequency/academias")
def listar_assinantes_frequency(admin=Depends(somente_admin_plataforma)):
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        return conn.execute(
            "SELECT a.id AS academia_id, a.nome AS academia, a.pais, "
            "a.ativa AS academia_ativa, u.nome AS nome_dono, u.email AS email_dono, "
            "s.id AS assinatura_id, s.status AS assinatura_status, s.inicio AS inicio_assinatura, "
            "s.proximo_vencimento, pl.id AS plano_id, pl.nome AS plano, "
            "f.id AS fatura_id, f.referencia, f.valor, f.moeda, f.vencimento, "
            "f.status AS fatura_status, f.data_pagamento, "
            "pg.data_pagamento AS ultimo_pagamento, pg.valor AS ultimo_valor_pago, "
            "pg.moeda AS moeda_ultimo_pagamento, "
            "CASE WHEN f.status = 'em_aberto' THEN "
            "GREATEST(CURRENT_DATE - f.vencimento, 0) ELSE 0 END AS dias_atraso, "
            "CASE WHEN f.status = 'em_aberto' "
            "AND CURRENT_DATE - f.vencimento >= 2 THEN TRUE ELSE FALSE END AS aviso, "
            "CASE WHEN s.status IN ('suspensa', 'cancelada') OR (f.status = 'em_aberto' "
            "AND CURRENT_DATE - f.vencimento >= 5) THEN TRUE ELSE FALSE END AS bloqueada "
            "FROM public.academias a "
            "LEFT JOIN public.usuarios u ON u.academia_id = a.id AND u.papel = 'dono' "
            "LEFT JOIN public.assinaturas_frequency s ON s.academia_id = a.id "
            "LEFT JOIN public.planos_frequency pl ON pl.id = s.plano_id "
            "LEFT JOIN LATERAL (SELECT i.* FROM public.faturas_frequency i "
            "WHERE i.academia_id = a.id AND i.status = 'em_aberto' "
            "ORDER BY i.vencimento, i.id LIMIT 1) f ON TRUE "
            "LEFT JOIN LATERAL (SELECT i.data_pagamento, i.valor, i.moeda "
            "FROM public.faturas_frequency i WHERE i.academia_id = a.id AND i.status = 'pago' "
            "ORDER BY i.data_pagamento DESC, i.id DESC LIMIT 1) pg ON TRUE "
            "ORDER BY a.nome, a.id"
        ).fetchall()


@app.patch("/admin/academias/{academia_id}")
def editar_academia_frequency(
    academia_id: int,
    dados: AtualizacaoAcademia,
    admin=Depends(somente_admin_plataforma),
):
    exigir_escrita_local()
    alteracoes = dados.model_dump(exclude_unset=True)
    if any(valor is None for valor in alteracoes.values()):
        raise HTTPException(status_code=400, detail="campos_nulos_nao_permitidos")
    if not alteracoes:
        raise HTTPException(status_code=400, detail="nenhuma_alteracao_informada")

    nome = alteracoes.get("nome_academia")
    pais = alteracoes.get("pais")
    cidade = alteracoes.get("cidade")
    estado = alteracoes.get("estado")
    endereco = alteracoes.get("endereco")
    codigo_postal = alteracoes.get("codigo_postal")
    telefone = alteracoes.get("telefone")
    nome_dono = alteracoes.get("nome_dono")
    email_dono = alteracoes.get("email_dono")
    if nome is not None:
        nome = nome.strip()
        if not nome:
            raise HTTPException(status_code=400, detail="nome_da_academia_obrigatorio")
    if pais is not None:
        pais = pais.strip()
        if not pais:
            raise HTTPException(status_code=400, detail="pais_obrigatorio")
    cidade = cidade.strip() if cidade is not None else None
    estado = estado.strip() if estado is not None else None
    endereco = endereco.strip() if endereco is not None else None
    codigo_postal = codigo_postal.strip() if codigo_postal is not None else None
    telefone = telefone.strip() if telefone is not None else None
    if nome_dono is not None:
        nome_dono = nome_dono.strip()
        if not nome_dono:
            raise HTTPException(status_code=400, detail="nome_do_dono_obrigatorio")
    if email_dono is not None:
        email_dono = email_dono.strip().lower()
        if not email_dono:
            raise HTTPException(status_code=400, detail="email_do_dono_obrigatorio")

    try:
        with get_connection() as conn:
            academia = conn.execute(
                "SELECT id, nome, pais, ativa FROM public.academias WHERE id = %s FOR UPDATE",
                (academia_id,),
            ).fetchone()
            if academia is None:
                raise HTTPException(status_code=404, detail="academia_nao_encontrada")
            exigir_migracao_frequency(conn)

            if any(campo in alteracoes for campo in ("nome_academia", "pais", "cidade", "estado", "endereco", "codigo_postal", "telefone")):
                novo_nome = nome if nome is not None else academia["nome"]
                novo_pais = pais if pais is not None else academia["pais"]
                if pais is not None and esquema_de_moeda_disponivel(conn):
                    idioma, moeda = preferencias_iniciais_academia(novo_pais)
                    conn.execute(
                        "UPDATE public.academias SET nome = %s, pais = %s, cidade = COALESCE(%s, cidade), "
                        "estado = COALESCE(%s, estado), endereco = COALESCE(%s, endereco), "
                        "codigo_postal = COALESCE(%s, codigo_postal), telefone = COALESCE(%s, telefone), "
                        "idioma = %s, moeda = %s "
                        "WHERE id = %s",
                        (novo_nome, novo_pais, cidade, estado, endereco, codigo_postal, telefone, idioma, moeda, academia_id),
                    )
                else:
                    conn.execute(
                        "UPDATE public.academias SET nome = %s, pais = %s, cidade = COALESCE(%s, cidade), "
                        "estado = COALESCE(%s, estado), endereco = COALESCE(%s, endereco), "
                        "codigo_postal = COALESCE(%s, codigo_postal), telefone = COALESCE(%s, telefone) "
                        "WHERE id = %s",
                        (novo_nome, novo_pais, cidade, estado, endereco, codigo_postal, telefone, academia_id),
                    )

            if nome_dono is not None or email_dono is not None:
                dono = conn.execute(
                    "SELECT id FROM public.usuarios "
                    "WHERE academia_id = %s AND papel = 'dono' FOR UPDATE",
                    (academia_id,),
                ).fetchone()
                if dono is None:
                    raise HTTPException(status_code=404, detail="dono_da_academia_nao_encontrado")
                conn.execute(
                    "UPDATE public.usuarios SET nome = COALESCE(%s, nome), "
                    "email = COALESCE(%s, email) WHERE id = %s",
                    (nome_dono, email_dono, dono["id"]),
                )

            atualizado = conn.execute(
                "SELECT a.id AS academia_id, a.nome AS academia, a.pais, a.ativa AS academia_ativa, "
                "a.cidade, a.estado, a.endereco, a.codigo_postal, a.telefone, "
                "u.id AS dono_id, u.nome AS nome_dono, u.email AS email_dono "
                "FROM public.academias a LEFT JOIN public.usuarios u "
                "ON u.academia_id = a.id AND u.papel = 'dono' WHERE a.id = %s",
                (academia_id,),
            ).fetchone()
            auditar_frequency(
                conn, admin["id"], "academia_atualizada", "academia", academia_id,
                {"campos": sorted(alteracoes.keys())},
            )
    except errors.UniqueViolation as erro:
        raise HTTPException(status_code=409, detail="email_ja_cadastrado") from erro
    return atualizado


@app.patch("/admin/frequency/assinaturas/{assinatura_id}/status")
def mudar_status_assinatura_frequency(
    assinatura_id: int,
    status: StatusAssinaturaFrequency,
    admin=Depends(somente_admin_plataforma),
):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        assinatura = conn.execute(
            "UPDATE public.assinaturas_frequency SET status = %s, "
            "atualizada_em = CURRENT_TIMESTAMP WHERE id = %s "
            "RETURNING id, academia_id, status",
            (status.status, assinatura_id),
        ).fetchone()
        if assinatura is not None:
            auditar_frequency(
                conn, admin["id"], "assinatura_status_alterado", "assinatura", assinatura_id,
                {"academia_id": assinatura["academia_id"], "status": status.status},
            )
    if assinatura is None:
        raise HTTPException(status_code=404, detail="assinatura_frequency_nao_encontrada")
    return assinatura


@app.patch("/admin/frequency/assinaturas/{assinatura_id}")
def editar_assinatura_frequency(
    assinatura_id: int,
    dados: AtualizacaoAssinaturaFrequency,
    admin=Depends(somente_admin_plataforma),
):
    exigir_escrita_local()
    alteracoes = dados.model_dump(exclude_unset=True)
    if any(valor is None for valor in alteracoes.values()):
        raise HTTPException(status_code=400, detail="campos_nulos_nao_permitidos")
    if not alteracoes:
        raise HTTPException(status_code=400, detail="nenhuma_alteracao_informada")
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        assinatura = conn.execute(
            "SELECT id, academia_id FROM public.assinaturas_frequency "
            "WHERE id = %s FOR UPDATE",
            (assinatura_id,),
        ).fetchone()
        if assinatura is None:
            raise HTTPException(status_code=404, detail="assinatura_frequency_nao_encontrada")
        novo_plano = None
        if "plano_id" in alteracoes and alteracoes["plano_id"] is not None:
            plano = conn.execute(
                "SELECT id, nome, valor, moeda FROM public.planos_frequency WHERE id = %s AND ativo IS TRUE",
                (alteracoes["plano_id"],),
            ).fetchone()
            if plano is None:
                raise HTTPException(status_code=404, detail="plano_frequency_nao_encontrado")
            novo_plano = plano
        fatura_reagendada = None
        if "proximo_vencimento" in alteracoes or novo_plano is not None:
            fatura_reagendada = conn.execute(
                "SELECT id, vencimento FROM public.faturas_frequency "
                "WHERE assinatura_id = %s AND status = 'em_aberto' "
                "ORDER BY vencimento, id LIMIT 1 FOR UPDATE",
                (assinatura_id,),
            ).fetchone()
            if fatura_reagendada is None:
                raise HTTPException(status_code=409, detail="fatura_frequency_em_aberto_nao_encontrada")
            if "proximo_vencimento" in alteracoes:
                conn.execute(
                    "UPDATE public.faturas_frequency SET vencimento = %s WHERE id = %s",
                    (alteracoes["proximo_vencimento"], fatura_reagendada["id"]),
                )
            if novo_plano is not None:
                conn.execute(
                    "UPDATE public.faturas_frequency SET valor = %s, moeda = %s, referencia = %s "
                    "WHERE id = %s",
                    (novo_plano["valor"], novo_plano["moeda"], f"Frequency · {novo_plano['nome']}", fatura_reagendada["id"]),
                )
        atualizada = conn.execute(
            "UPDATE public.assinaturas_frequency SET "
            "plano_id = COALESCE(%s, plano_id), "
            "proximo_vencimento = COALESCE(%s, proximo_vencimento), "
            "status = COALESCE(%s, status), atualizada_em = CURRENT_TIMESTAMP "
            "WHERE id = %s RETURNING id, academia_id, plano_id, proximo_vencimento, status",
            (
                alteracoes.get("plano_id"), alteracoes.get("proximo_vencimento"),
                alteracoes.get("status"), assinatura_id,
            ),
        ).fetchone()
        auditar_frequency(
            conn, admin["id"], "assinatura_atualizada", "assinatura", assinatura_id,
            {
                "academia_id": assinatura["academia_id"], "campos": sorted(alteracoes.keys()),
                "fatura_id": fatura_reagendada["id"] if fatura_reagendada else None,
                "vencimento_anterior": fatura_reagendada["vencimento"].isoformat() if fatura_reagendada else None,
        "vencimento_novo": (
            alteracoes.get("proximo_vencimento").isoformat()
            if fatura_reagendada and alteracoes.get("proximo_vencimento") is not None
            else None
        ),
            },
        )
    return atualizada


@app.get("/admin/frequency/faturas")
def listar_faturas_frequency(
    status: str = Query(default="todas"),
    admin=Depends(somente_admin_plataforma),
):
    if status not in {"todas", "em_aberto", "atrasadas", "pago", "cancelado", "estornado"}:
        raise HTTPException(status_code=400, detail="status_de_fatura_invalido")
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        if status == "atrasadas":
            return conn.execute(
                "SELECT f.id, f.academia_id, a.nome AS academia, f.referencia, "
                "f.periodo_inicio, f.periodo_fim, f.valor, f.moeda, f.vencimento, "
                "f.status, f.data_pagamento, f.meio_pagamento, "
                "f.referencia_pagamento, f.observacao_admin, "
                "CURRENT_DATE - f.vencimento AS dias_atraso, "
                "(CURRENT_DATE - f.vencimento >= 2) AS aviso, "
                "(CURRENT_DATE - f.vencimento >= 5) AS bloqueada "
                "FROM public.faturas_frequency f JOIN public.academias a "
                "ON a.id = f.academia_id WHERE f.status = 'em_aberto' "
                "AND f.vencimento < CURRENT_DATE "
                "ORDER BY f.vencimento, a.nome, f.id LIMIT 500"
            ).fetchall()
        if status == "todas":
            return conn.execute(
                "SELECT f.id, f.academia_id, a.nome AS academia, f.referencia, "
                "f.periodo_inicio, f.periodo_fim, f.valor, f.moeda, f.vencimento, "
                "f.status, f.data_pagamento, f.meio_pagamento, "
                "f.referencia_pagamento, f.observacao_admin "
                "FROM public.faturas_frequency f JOIN public.academias a "
                "ON a.id = f.academia_id ORDER BY f.vencimento DESC, f.id DESC LIMIT 500"
            ).fetchall()
        return conn.execute(
            "SELECT f.id, f.academia_id, a.nome AS academia, f.referencia, "
            "f.periodo_inicio, f.periodo_fim, f.valor, f.moeda, f.vencimento, "
            "f.status, f.data_pagamento, f.meio_pagamento, "
            "f.referencia_pagamento, f.observacao_admin "
            "FROM public.faturas_frequency f JOIN public.academias a "
            "ON a.id = f.academia_id WHERE f.status = %s "
            "ORDER BY f.vencimento DESC, f.id DESC LIMIT 500",
            (status,),
        ).fetchall()


@app.post("/admin/frequency/assinaturas", status_code=201)
def criar_assinatura_frequency(
    dados: NovaAssinaturaFrequency,
    admin=Depends(somente_admin_plataforma),
):
    exigir_escrita_local()
    try:
        with get_connection() as conn:
            exigir_migracao_frequency(conn)
            academia = conn.execute(
                "SELECT id, nome FROM public.academias WHERE id = %s",
                (dados.academia_id,),
            ).fetchone()
            plano = conn.execute(
                "SELECT id, nome, valor, moeda, duracao_dias "
                "FROM public.planos_frequency WHERE id = %s AND ativo IS TRUE",
                (dados.plano_id,),
            ).fetchone()
            if academia is None:
                raise HTTPException(status_code=404, detail="academia_nao_encontrada")
            if plano is None:
                raise HTTPException(status_code=404, detail="plano_frequency_nao_encontrado")
            inicio = date.today()
            fim = inicio + timedelta(days=plano["duracao_dias"] - 1)
            assinatura = conn.execute(
                "INSERT INTO public.assinaturas_frequency "
                "(academia_id, plano_id, inicio, proximo_vencimento, criada_por) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (academia["id"], plano["id"], inicio, dados.vencimento, admin["id"]),
            ).fetchone()
            fatura = conn.execute(
                "INSERT INTO public.faturas_frequency "
                "(academia_id, assinatura_id, referencia, periodo_inicio, periodo_fim, "
                "valor, moeda, vencimento, criada_por) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, status",
                (
                    academia["id"], assinatura["id"],
                    f"Frequency · {plano['nome']}", inicio, fim, plano["valor"],
                    plano["moeda"], dados.vencimento, admin["id"],
                ),
            ).fetchone()
            auditar_frequency(
                conn, admin["id"], "assinatura_criada", "assinatura", assinatura["id"],
                {"academia_id": academia["id"], "plano_id": plano["id"], "fatura_id": fatura["id"]},
            )
    except errors.UniqueViolation as erro:
        raise HTTPException(status_code=409, detail="assinatura_frequency_ja_cadastrada") from erro
    return {
        "assinatura_id": assinatura["id"],
        "fatura_id": fatura["id"],
        "academia": academia["nome"],
        "status": fatura["status"],
    }


def bloquear_assinatura_da_fatura(conn, fatura_id):
    """Serialize billing mutations: always lock subscription before invoice."""
    return conn.execute(
        "SELECT s.id, s.status FROM public.assinaturas_frequency s "
        "JOIN public.faturas_frequency f ON f.assinatura_id = s.id "
        "WHERE f.id = %s FOR UPDATE OF s",
        (fatura_id,),
    ).fetchone()


def _liquidar_fatura_frequency(
    conn,
    fatura_id: int,
    *,
    meio_pagamento: str,
    referencia_pagamento: str | None,
    observacao: str,
    ator_id: int | None,
    acao_auditoria: str,
):
    """Baixa uma fatura e agenda a próxima, de forma idempotente."""
    bloquear_assinatura_da_fatura(conn, fatura_id)
    fatura = conn.execute(
        "SELECT id, academia_id, assinatura_id, status, periodo_fim "
        "FROM public.faturas_frequency WHERE id = %s FOR UPDATE",
        (fatura_id,),
    ).fetchone()
    if fatura is None:
        raise HTTPException(status_code=404, detail="fatura_frequency_nao_encontrada")
    if fatura["status"] != "em_aberto":
        return {"id": fatura_id, "pago": False, "ja_finalizada": True, "proxima_fatura_id": None}

    conn.execute(
        "UPDATE public.faturas_frequency SET status = 'pago', "
        "data_pagamento = CURRENT_TIMESTAMP, meio_pagamento = %s, "
        "referencia_pagamento = %s, observacao_admin = %s, confirmada_por = %s "
        "WHERE id = %s",
        (meio_pagamento, referencia_pagamento, observacao, ator_id, fatura_id),
    )
    auditar_frequency(
        conn, ator_id, acao_auditoria, "fatura", fatura_id,
        {"meio_pagamento": meio_pagamento, "proxima_fatura": bool(fatura["assinatura_id"])},
    )
    proxima_fatura = None
    if fatura["assinatura_id"] is not None:
        plano = conn.execute(
            "SELECT s.plano_id, p.nome, p.valor, p.moeda, p.duracao_dias "
            "FROM public.assinaturas_frequency s "
            "JOIN public.planos_frequency p ON p.id = s.plano_id "
            "WHERE s.id = %s AND s.status = 'ativa'",
            (fatura["assinatura_id"],),
        ).fetchone()
        if plano is not None:
            inicio = max(fatura["periodo_fim"] + timedelta(days=1), date.today())
            fim = inicio + timedelta(days=plano["duracao_dias"] - 1)
            proxima_fatura = conn.execute(
                "INSERT INTO public.faturas_frequency "
                "(academia_id, assinatura_id, referencia, periodo_inicio, periodo_fim, "
                "valor, moeda, vencimento, criada_por) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id, vencimento",
                (
                    fatura["academia_id"], fatura["assinatura_id"],
                    f"Frequency · {plano['nome']}", inicio, fim, plano["valor"],
                    plano["moeda"], inicio, ator_id,
                ),
            ).fetchone()
            conn.execute(
                "UPDATE public.assinaturas_frequency "
                "SET proximo_vencimento = %s, atualizada_em = CURRENT_TIMESTAMP "
                "WHERE id = %s",
                (inicio, fatura["assinatura_id"]),
            )
            auditar_frequency(
                conn, ator_id, "fatura_recorrente_criada", "fatura", proxima_fatura["id"],
                {"assinatura_id": fatura["assinatura_id"], "vencimento": proxima_fatura["vencimento"].isoformat()},
            )
    return {
        "id": fatura_id,
        "pago": True,
        "proxima_fatura_id": proxima_fatura["id"] if proxima_fatura else None,
    }


@app.patch("/admin/frequency/faturas/{fatura_id}/pagar")
def confirmar_fatura_frequency(
    fatura_id: int,
    confirmacao: ConfirmacaoFaturaFrequency,
    admin=Depends(somente_admin_plataforma),
):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        resultado = _liquidar_fatura_frequency(
            conn,
            fatura_id,
            meio_pagamento=confirmacao.meio_pagamento.strip(),
            referencia_pagamento=(
                confirmacao.referencia_pagamento.strip()
                if confirmacao.referencia_pagamento else None
            ),
            observacao=confirmacao.observacao_admin.strip(),
            ator_id=admin["id"],
            acao_auditoria="fatura_paga",
        )
    if not resultado["pago"]:
        raise HTTPException(status_code=409, detail="fatura_frequency_ja_finalizada")
    return resultado


@app.post("/webhooks/dlocal")
async def receber_webhook_dlocal(
    request: Request,
    x_date: str | None = Header(default=None, alias="X-Date"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    signature: str | None = Header(default=None, alias="Signature"),
):
    """Receive signed dLocal notifications and settle only exact invoices."""
    allow_local_http = (
        os.getenv("PAYMENT_ALLOW_HTTP_STAGING", "").strip().upper() == "YES"
        and (request.client.host if request.client else "") in {"127.0.0.1", "::1", "localhost", "testclient"}
    )
    if request.url.scheme != "https" and not allow_local_http:
        raise HTTPException(status_code=426, detail="pagamento_webhook_exige_https")
    body = await request.body()
    # dLocal envia a assinatura no Authorization. Signature fica aceito apenas
    # para manter compatibilidade com integrações antigas/homologações locais.
    if not validar_notificacao_dlocal(body, x_date, authorization or signature):
        raise HTTPException(status_code=401, detail="assinatura_webhook_invalida")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as erro:
        raise HTTPException(status_code=400, detail="payload_webhook_invalido") from erro
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload_webhook_invalido")

    event_key = hash_evento_webhook(body)
    payment_id = str(payload.get("id") or "").strip() or None
    order_id = str(payload.get("order_id") or "").strip() or None
    external_status = str(payload.get("status") or "").strip().upper() or "UNKNOWN"
    amount_raw = payload.get("amount")
    currency = str(payload.get("currency") or "").strip().upper() or None
    try:
        amount = Decimal(str(amount_raw)) if amount_raw is not None else None
    except (ArithmeticError, ValueError):
        amount = None

    try:
        with get_connection() as conn:
            evento = conn.execute(
                "INSERT INTO public.pagamentos_webhook_eventos "
                "(provedor, chave_evento, pagamento_id_externo, pedido_pagamento_externo, "
                "status_externo, valor, moeda, payload_hash) "
                "VALUES ('dlocal', %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (provedor, chave_evento) DO NOTHING RETURNING id",
                (event_key, payment_id, order_id, external_status, amount, currency, event_key),
            ).fetchone()
            if evento is None:
                return {"aceito": True, "duplicado": True}

            fatura = conn.execute(
                "SELECT id, valor, moeda, status FROM public.faturas_frequency "
                "WHERE provedor_pagamento = 'dlocal' AND ("
                "pagamento_id_externo = %s OR pedido_pagamento_externo = %s) "
                "ORDER BY id LIMIT 1",
                (payment_id, order_id),
            ).fetchone()
            if fatura is None:
                conn.execute(
                    "UPDATE public.pagamentos_webhook_eventos SET estado = 'ignorado', "
                    "motivo = 'fatura_nao_encontrada', processado_em = CURRENT_TIMESTAMP WHERE id = %s",
                    (evento["id"],),
                )
                return {"aceito": True, "ignorado": True}

            if status_dlocal_pago(external_status):
                valor_confere = amount is not None and amount == Decimal(str(fatura["valor"]))
                moeda_confere = currency == str(fatura["moeda"]).upper()
                if not valor_confere or not moeda_confere:
                    conn.execute(
                        "UPDATE public.faturas_frequency SET status_pagamento_externo = 'erro', "
                        "pagamento_atualizado_em = CURRENT_TIMESTAMP WHERE id = %s",
                        (fatura["id"],),
                    )
                    conn.execute(
                        "UPDATE public.pagamentos_webhook_eventos SET estado = 'rejeitado', "
                        "motivo = 'valor_ou_moeda_nao_confere', processado_em = CURRENT_TIMESTAMP WHERE id = %s",
                        (evento["id"],),
                    )
                    return {"aceito": True, "pago": False, "rejeitado": True}
                resultado = _liquidar_fatura_frequency(
                    conn,
                    fatura["id"],
                    meio_pagamento="dlocal",
                    referencia_pagamento=payment_id or order_id,
                    observacao="Confirmado automaticamente por webhook dLocal.",
                    ator_id=None,
                    acao_auditoria="fatura_paga_automaticamente",
                )
                conn.execute(
                    "UPDATE public.faturas_frequency SET status_pagamento_externo = 'pago', "
                    "pagamento_atualizado_em = CURRENT_TIMESTAMP WHERE id = %s",
                    (fatura["id"],),
                )
                conn.execute(
                    "UPDATE public.pagamentos_webhook_eventos SET estado = 'processado', "
                    "processado_em = CURRENT_TIMESTAMP WHERE id = %s",
                    (evento["id"],),
                )
                return {"aceito": True, "pago": resultado["pago"], "fatura_id": fatura["id"]}

            bloquear_assinatura_da_fatura(conn, fatura["id"])
            estado = "recusado" if status_dlocal_falhou(external_status) else "recebido"
            conn.execute(
                "UPDATE public.faturas_frequency SET status_pagamento_externo = %s, "
                "pagamento_atualizado_em = CURRENT_TIMESTAMP WHERE id = %s AND status = 'em_aberto'",
                (estado, fatura["id"]),
            )
            conn.execute(
                "UPDATE public.pagamentos_webhook_eventos SET estado = 'processado', "
                "processado_em = CURRENT_TIMESTAMP WHERE id = %s",
                (evento["id"],),
            )
            return {"aceito": True, "pago": False, "status": external_status}
    except errors.UndefinedTable as erro:
        raise HTTPException(status_code=503, detail="migracao_pagamento_online_pendente") from erro
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_pagamento_online_pendente") from erro


@app.patch("/admin/frequency/faturas/{fatura_id}/cancelar")
def cancelar_fatura_frequency(
    fatura_id: int,
    dados: CancelamentoFaturaFrequency,
    admin=Depends(somente_admin_plataforma),
):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        assinatura = bloquear_assinatura_da_fatura(conn, fatura_id)
        if assinatura and assinatura["status"] == "ativa":
            aberta = conn.execute(
                "SELECT id FROM public.faturas_frequency "
                "WHERE id = %s AND status = 'em_aberto'",
                (fatura_id,),
            ).fetchone()
            outra = conn.execute(
                "SELECT id FROM public.faturas_frequency WHERE assinatura_id = %s "
                "AND status = 'em_aberto' AND id <> %s LIMIT 1",
                (assinatura["id"], fatura_id),
            ).fetchone()
            if aberta and outra is None:
                raise HTTPException(status_code=409, detail="fatura_necessaria_para_assinatura_ativa")
        fatura = conn.execute(
            "UPDATE public.faturas_frequency SET status = 'cancelado', "
            "observacao_admin = %s WHERE id = %s AND status = 'em_aberto' "
            "RETURNING id, academia_id",
            (dados.observacao_admin.strip(), fatura_id),
        ).fetchone()
        if fatura is not None:
            auditar_frequency(
                conn, admin["id"], "fatura_cancelada", "fatura", fatura_id,
                {"academia_id": fatura["academia_id"], "motivo": dados.observacao_admin.strip()},
            )
    if fatura is None:
        raise HTTPException(status_code=404, detail="fatura_frequency_em_aberto_nao_encontrada")
    return {"cancelada": True}


@app.get("/admin/frequency/auditoria")
def listar_auditoria_frequency(
    limite: int = Query(default=100, ge=1, le=500),
    admin=Depends(somente_admin_plataforma),
):
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        return conn.execute(
            "SELECT l.id, l.criado_em, l.ator_id, u.nome AS administrador, "
            "l.acao, l.entidade, l.entidade_id, l.detalhes "
            "FROM public.auditoria_frequency l "
            "LEFT JOIN public.usuarios u ON u.id = l.ator_id "
            "ORDER BY l.criado_em DESC, l.id DESC LIMIT %s",
            (limite,),
        ).fetchall()


@app.put("/admin/frequency/qr/{moeda}")
async def salvar_qr_frequency(
    moeda: str,
    request: Request,
    admin=Depends(somente_admin_plataforma),
):
    exigir_escrita_local()
    moeda = moeda.upper()
    if len(moeda) != 3 or not moeda.isalpha() or not moeda.isascii():
        raise HTTPException(status_code=400, detail="moeda_invalida")
    tipo = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    conteudo = await request.body()
    if len(conteudo) > TAMANHO_MAXIMO_QR:
        raise HTTPException(status_code=413, detail="imagem_de_qr_muito_grande")
    if tipo not in TIPOS_QR_PERMITIDOS:
        raise HTTPException(status_code=415, detail="formato_de_qr_nao_suportado")
    if not imagem_qr_valida(tipo, conteudo):
        raise HTTPException(status_code=400, detail="imagem_de_qr_invalida")
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        conn.execute(
            "INSERT INTO public.plataforma_qrs (moeda, imagem, media_type, atualizado_por) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (moeda) DO UPDATE SET "
            "imagem = EXCLUDED.imagem, media_type = EXCLUDED.media_type, "
            "atualizado_por = EXCLUDED.atualizado_por, atualizado_em = CURRENT_TIMESTAMP",
            (moeda, conteudo, tipo, admin["id"]),
        )
        auditar_frequency(
            conn, admin["id"], "qr_atualizado", "qr", moeda,
            {"tipo": tipo, "tamanho": len(conteudo)},
        )
    return {"salvo": True, "moeda": moeda}


@app.get("/admin/frequency/qr/{moeda}")
def obter_qr_frequency_admin(moeda: str, admin=Depends(somente_admin_plataforma)):
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        qr = conn.execute(
            "SELECT imagem, media_type FROM public.plataforma_qrs WHERE moeda = %s",
            (moeda.upper(),),
        ).fetchone()
    if qr is None:
        raise HTTPException(status_code=404, detail="qr_frequency_nao_cadastrado")
    return Response(
        content=bytes(qr["imagem"]), media_type=qr["media_type"],
        headers={"Cache-Control": "private, no-store"},
    )


@app.delete("/admin/frequency/qr/{moeda}")
def remover_qr_frequency(moeda: str, admin=Depends(somente_admin_plataforma)):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        qr = conn.execute(
            "DELETE FROM public.plataforma_qrs WHERE moeda = %s RETURNING moeda",
            (moeda.upper(),),
        ).fetchone()
        if qr is not None:
            auditar_frequency(conn, admin["id"], "qr_removido", "qr", moeda.upper())
    if qr is None:
        raise HTTPException(status_code=404, detail="qr_frequency_nao_cadastrado")
    return {"removido": True}


@app.get("/admin/frequency/configuracao")
def obter_configuracao_frequency(admin=Depends(somente_admin_plataforma)):
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        configuracao = conn.execute(
            "SELECT contato_email, contato_telefone FROM public.configuracao_frequency "
            "WHERE id = 1"
        ).fetchone()
    return {
        "contato_email": configuracao["contato_email"] or os.getenv("FREQUENCY_ADMIN_EMAIL", "frequencygym@gmail.com"),
        "contato_telefone": configuracao["contato_telefone"] or os.getenv("FREQUENCY_ADMIN_PHONE", "+591 75443696"),
    }


@app.put("/admin/frequency/configuracao")
def salvar_configuracao_frequency(
    dados: ConfiguracaoFrequency,
    admin=Depends(somente_admin_plataforma),
):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        configuracao = conn.execute(
            "UPDATE public.configuracao_frequency SET contato_email = %s, "
            "contato_telefone = %s, atualizada_em = CURRENT_TIMESTAMP "
            "WHERE id = 1 RETURNING contato_email, contato_telefone",
            (
                dados.contato_email.strip().lower() if dados.contato_email else None,
                dados.contato_telefone.strip() if dados.contato_telefone else None,
            ),
        ).fetchone()
        auditar_frequency(conn, admin["id"], "contato_atualizado", "configuracao", 1)
    return configuracao


@app.get("/assinatura-frequency")
def minha_assinatura_frequency(usuario=Depends(usuario_atual)):
    if usuario["papel"] != "dono" or usuario["academia_id"] is None:
        raise HTTPException(status_code=403, detail="sem_permissao")
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        estado = estado_assinatura_frequency(conn, usuario["academia_id"])
        assinatura = conn.execute(
            "SELECT s.id, s.status, s.inicio, s.proximo_vencimento, p.nome AS plano "
            "FROM public.assinaturas_frequency s "
            "JOIN public.planos_frequency p ON p.id = s.plano_id "
            "WHERE s.academia_id = %s",
            (usuario["academia_id"],),
        ).fetchone()
        faturas = conn.execute(
            "SELECT id, referencia, periodo_inicio, periodo_fim, valor, moeda, "
            "vencimento, status, data_pagamento "
            "FROM public.faturas_frequency WHERE academia_id = %s "
            "ORDER BY vencimento DESC, id DESC LIMIT 12",
            (usuario["academia_id"],),
        ).fetchall()
        contato = conn.execute(
            "SELECT contato_email, contato_telefone "
            "FROM public.configuracao_frequency WHERE id = 1"
        ).fetchone()
    # Keep the regularization path usable even before the platform owner fills
    # the optional settings form. These are the official Frequency contacts;
    # deployments may override them with environment variables.
    if contato is None:
        contato = {"contato_email": None, "contato_telefone": None}
    contato = {
        "contato_email": contato["contato_email"] or os.getenv("FREQUENCY_ADMIN_EMAIL", "frequencygym@gmail.com"),
        "contato_telefone": contato["contato_telefone"] or os.getenv("FREQUENCY_ADMIN_PHONE", "+591 75443696"),
    }
    return {
        **{key: value for key, value in estado.items() if key != "fatura_frequency"},
        "assinatura": assinatura,
        "faturas": faturas,
        "contato": contato,
        "fatura_atual": estado["fatura_frequency"],
    }


def _callback_pagamento_frequency(fatura_id: int) -> str:
    base = os.getenv("PAYMENT_PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base.startswith("https://"):
        raise GatewayNaoConfigurado("pagamento_exige_url_https")
    return f"{base}/app?pagamento=retorno&fatura={fatura_id}"


def _gmail_request(access_token: str, path: str, params: dict | None = None) -> dict:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(
        f"{GMAIL_API_BASE_URL}/{path.lstrip('/')}{query}",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise HTTPException(status_code=502, detail="gmail_autorizacao_expirada") from exc
        raise HTTPException(status_code=502, detail="gmail_indisponivel") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="gmail_indisponivel") from exc


def _gmail_header(payload: dict, name: str) -> str:
    for header in payload.get("headers", []):
        if str(header.get("name", "")).lower() == name.lower():
            return str(header.get("value", ""))
    return ""


def _gmail_amount(text: str) -> Decimal | None:
    match = re.search(r"(?:BOB|Bs\.?|R\$|USD|US\$|\$)\s*([0-9][0-9.,]*)", text, re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).replace(".", "").replace(",", ".")
    try:
        return Decimal(value).quantize(Decimal("0.01"))
    except Exception:
        return None


def _gmail_access_token(conn, connection: dict) -> str:
    if connection.get("access_token") and connection.get("access_token_expira_em"):
        if connection["access_token_expira_em"] > datetime.now(timezone.utc) + timedelta(seconds=30):
            return connection["access_token"]
    refresh = conn.execute(
        "SELECT pgp_sym_decrypt(refresh_token, %s)::text AS token FROM public.gmail_pagamento_conexoes WHERE academia_id = %s AND ativo",
        (_gmail_crypto_key(), connection["academia_id"]),
    ).fetchone()
    if not refresh or not refresh["token"]:
        raise HTTPException(status_code=502, detail="gmail_autorizacao_expirada")
    config = _gmail_oauth_config()
    if config is None:
        raise HTTPException(status_code=503, detail="google_nao_configurado")
    client_id, client_secret, _redirect_uri = config
    token_data = _google_request(
        GOOGLE_OAUTH_TOKEN_URL,
        {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh["token"], "grant_type": "refresh_token"},
    )
    access = str(token_data.get("access_token") or "").strip()
    if not access:
        raise HTTPException(status_code=502, detail="gmail_autorizacao_expirada")
    expires_in = max(60, int(token_data.get("expires_in") or 3600))
    conn.execute(
        "UPDATE public.gmail_pagamento_conexoes SET access_token = pgp_sym_encrypt(%s, %s), access_token_expira_em = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'), atualizado_em = CURRENT_TIMESTAMP WHERE academia_id = %s",
        (access, _gmail_crypto_key(), expires_in, connection["academia_id"]),
    )
    return access


@app.get("/assinatura-frequency/gmail")
def listar_comprovantes_gmail(usuario=Depends(usuario_atual)):
    if usuario["papel"] != "dono" or usuario["academia_id"] is None:
        raise HTTPException(status_code=403, detail="sem_permissao")
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        connection = conn.execute(
            "SELECT academia_id, email, access_token_expira_em, ultima_verificacao FROM public.gmail_pagamento_conexoes WHERE academia_id = %s AND ativo",
            (usuario["academia_id"],),
        ).fetchone()
        if not connection:
            return {"conectado": False, "email": None, "comprovantes": []}
        encrypted = conn.execute(
            "SELECT pgp_sym_decrypt(access_token, %s)::text AS access_token FROM public.gmail_pagamento_conexoes WHERE academia_id = %s",
            (_gmail_crypto_key(), usuario["academia_id"]),
        ).fetchone()
        connection["access_token"] = encrypted["access_token"] if encrypted else None
        access_token = _gmail_access_token(conn, connection)
        result = _gmail_request(access_token, "messages", {"q": "newer_than:30d (comprovante OR pagamento OR transferência OR deposito OR recibo)", "maxResults": 20})
        messages = []
        for item in result.get("messages", []):
            detail = _gmail_request(access_token, f"messages/{item['id']}", {"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]})
            payload = detail.get("payload", {})
            sender = _gmail_header(payload, "From")
            subject = _gmail_header(payload, "Subject")
            received = _gmail_header(payload, "Date")
            snippet = str(detail.get("snippet", ""))[:1000]
            text = f"{subject} {snippet}"
            amount = _gmail_amount(text)
            invoice = conn.execute(
                "SELECT id, valor, moeda FROM public.faturas_frequency WHERE academia_id = %s AND status = 'em_aberto' ORDER BY vencimento, id LIMIT 1",
                (usuario["academia_id"],),
            ).fetchone()
            matched = bool(invoice and amount is not None and amount == Decimal(str(invoice["valor"])))
            row = conn.execute(
                "INSERT INTO public.gmail_comprovantes (academia_id, fatura_id, gmail_message_id, remetente, assunto, resumo, dados_extraidos) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (academia_id, gmail_message_id) DO UPDATE SET remetente = EXCLUDED.remetente, assunto = EXCLUDED.assunto, resumo = EXCLUDED.resumo, dados_extraidos = EXCLUDED.dados_extraidos, atualizado_em = CURRENT_TIMESTAMP RETURNING id, fatura_id, gmail_message_id, remetente, assunto, resumo, dados_extraidos, status",
                (usuario["academia_id"], invoice["id"] if matched else None, item["id"], sender[:300], subject[:500], snippet, Jsonb({"valor": str(amount) if amount is not None else None, "valor_confere": matched, "data_email": received})),
            ).fetchone()
            messages.append(dict(row))
        conn.execute("UPDATE public.gmail_pagamento_conexoes SET ultima_verificacao = CURRENT_TIMESTAMP WHERE academia_id = %s", (usuario["academia_id"],))
        return {"conectado": True, "email": connection["email"], "comprovantes": messages}


@app.delete("/assinatura-frequency/gmail")
def desconectar_gmail(usuario=Depends(usuario_atual)):
    if usuario["papel"] != "dono" or usuario["academia_id"] is None:
        raise HTTPException(status_code=403, detail="sem_permissao")
    with get_connection() as conn:
        conn.execute("UPDATE public.gmail_pagamento_conexoes SET ativo = false, atualizado_em = CURRENT_TIMESTAMP WHERE academia_id = %s", (usuario["academia_id"],))
    return {"conectado": False}


@app.get("/admin/frequency/gmail")
def estado_gmail_plataforma(admin=Depends(somente_admin_plataforma)):
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        row = conn.execute(
            "SELECT email, ativo, ultima_verificacao FROM public.gmail_plataforma_conexao WHERE id = 1"
        ).fetchone()
    return {"conectado": bool(row and row["ativo"]), "email": row["email"] if row else None, "ultima_verificacao": row["ultima_verificacao"] if row else None}


@app.get("/admin/prospeccao/gmail")
def estado_gmail_prospeccao(admin=Depends(somente_admin_plataforma)):
    with get_connection() as conn:
        row = conn.execute("SELECT email, ativo FROM public.gmail_plataforma_conexao WHERE id = 2").fetchone()
    return {"conectado": bool(row and row["ativo"]), "email": row["email"] if row else None}

@app.delete("/admin/frequency/gmail")
def desconectar_gmail_plataforma(admin=Depends(somente_admin_plataforma)):
    exigir_escrita_local()
    with get_connection() as conn:
        conn.execute("UPDATE public.gmail_plataforma_conexao SET ativo = false, atualizado_em = CURRENT_TIMESTAMP WHERE id = 1")
        auditar_frequency(conn, admin["id"], "gmail_plataforma_desconectado", "gmail", 1)
    return {"conectado": False}


@app.post("/assinatura-frequency/checkout")
def iniciar_checkout_assinatura_frequency(
    dados: CheckoutAssinaturaFrequency,
    usuario=Depends(usuario_atual),
):
    """Create or reuse a hosted payment for the owner's open invoice."""
    if usuario["papel"] != "dono" or usuario["academia_id"] is None:
        raise HTTPException(status_code=403, detail="sem_permissao")
    exigir_escrita_local()

    try:
        with get_connection() as conn:
            exigir_migracao_frequency(conn)
            dono = conn.execute(
                "SELECT nome, email FROM public.usuarios WHERE id = %s",
                (usuario["id"],),
            ).fetchone()
            fatura = conn.execute(
                "SELECT f.id, f.valor, f.moeda, f.vencimento, f.status, "
                "f.provedor_pagamento, f.pagamento_id_externo, "
                "f.pedido_pagamento_externo, f.checkout_url, f.status_pagamento_externo, "
                "(f.status_pagamento_externo = 'criando' AND "
                "f.pagamento_atualizado_em > CURRENT_TIMESTAMP - INTERVAL '10 minutes') "
                "AS pagamento_em_criacao_recente "
                "FROM public.faturas_frequency f "
                "WHERE f.academia_id = %s AND f.status = 'em_aberto' "
                "ORDER BY f.vencimento, f.id LIMIT 1 FOR UPDATE",
                (usuario["academia_id"],),
            ).fetchone()
            if dono is None:
                raise HTTPException(status_code=404, detail="dono_da_academia_nao_encontrado")
            if fatura is None:
                raise HTTPException(status_code=404, detail="fatura_frequency_nao_encontrada")
            if (
                fatura["provedor_pagamento"] == "dlocal"
                and fatura["checkout_url"]
                and fatura["status_pagamento_externo"] in {"criando", "pendente"}
            ):
                return {
                    "provedor": "dlocal",
                    "fatura_id": fatura["id"],
                    "pedido_id": fatura["pedido_pagamento_externo"],
                    "pagamento_id": fatura["pagamento_id_externo"],
                    "checkout_url": fatura["checkout_url"],
                    "status": fatura["status_pagamento_externo"],
                    "reutilizado": True,
                }
            if fatura["status_pagamento_externo"] == "criando" and fatura["pagamento_em_criacao_recente"]:
                raise HTTPException(status_code=409, detail="pagamento_em_criacao")

            pedido_id = f"frequency-fatura-{fatura['id']}-{uuid4().hex}"
            conn.execute(
                "UPDATE public.faturas_frequency SET provedor_pagamento = 'dlocal', "
                "pedido_pagamento_externo = %s, pagamento_id_externo = NULL, "
                "checkout_url = NULL, status_pagamento_externo = 'criando', "
                "pagamento_atualizado_em = CURRENT_TIMESTAMP WHERE id = %s",
                (pedido_id, fatura["id"]),
            )
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_pagamento_online_pendente") from erro

    try:
        checkout = criar_checkout_dlocal(
            order_id=pedido_id,
            amount=Decimal(str(fatura["valor"])),
            currency=str(fatura["moeda"]),
            payer_name=str(dono["nome"]),
            payer_email=str(dono["email"]),
            payer_document=dados.documento,
            description=f"Frequency · fatura {fatura['id']}",
            callback_url=_callback_pagamento_frequency(fatura["id"]),
        )
    except GatewayNaoConfigurado as erro:
        with get_connection() as conn:
            conn.execute(
                "UPDATE public.faturas_frequency SET status_pagamento_externo = 'erro', "
                "pagamento_atualizado_em = CURRENT_TIMESTAMP WHERE id = %s AND status = 'em_aberto'",
                (fatura["id"],),
            )
        raise HTTPException(status_code=503, detail=str(erro)) from erro
    except GatewayIndisponivel as erro:
        with get_connection() as conn:
            conn.execute(
                "UPDATE public.faturas_frequency SET status_pagamento_externo = 'erro', "
                "pagamento_atualizado_em = CURRENT_TIMESTAMP WHERE id = %s AND status = 'em_aberto'",
                (fatura["id"],),
            )
        raise HTTPException(status_code=502, detail="gateway_pagamento_indisponivel") from erro

    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE public.faturas_frequency SET pagamento_id_externo = %s, "
                "checkout_url = %s, status_pagamento_externo = CASE "
                "WHEN status = 'pago' THEN 'pago' "
                "WHEN status = 'em_aberto' THEN 'pendente' "
                "ELSE status_pagamento_externo END, "
                "pagamento_atualizado_em = CURRENT_TIMESTAMP "
                "WHERE id = %s",
                (checkout.pagamento_id, checkout.checkout_url, fatura["id"]),
            )
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_pagamento_online_pendente") from erro
    return {
        "provedor": checkout.provedor,
        "fatura_id": fatura["id"],
        "pedido_id": checkout.order_id,
        "pagamento_id": checkout.pagamento_id,
        "checkout_url": checkout.checkout_url,
        "status": checkout.status.lower(),
        "reutilizado": False,
    }


@app.get("/assinatura-frequency/qr")
def obter_qr_assinatura_frequency(usuario=Depends(usuario_atual)):
    if usuario["papel"] != "dono" or usuario["academia_id"] is None:
        raise HTTPException(status_code=403, detail="sem_permissao")
    with get_connection() as conn:
        exigir_migracao_frequency(conn)
        estado = estado_assinatura_frequency(conn, usuario["academia_id"])
        fatura = estado["fatura_frequency"]
        if fatura is None:
            raise HTTPException(status_code=404, detail="fatura_frequency_nao_encontrada")
        qr = conn.execute(
            "SELECT imagem, media_type FROM public.plataforma_qrs WHERE moeda = %s",
            (fatura["moeda"],),
        ).fetchone()
    if qr is None:
        raise HTTPException(status_code=404, detail="qr_frequency_nao_cadastrado")
    return Response(
        content=bytes(qr["imagem"]), media_type=qr["media_type"],
        headers={"Cache-Control": "private, no-store"},
    )


@app.get("/academia/qr")
def obter_qr_academia(usuario=Depends(usuario_de_academia)):
    try:
        with get_connection() as conn:
            qr = conn.execute(
                "SELECT qr_pagamento, qr_media_type FROM academias WHERE id = %s",
                (usuario["academia_id"],),
            ).fetchone()
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_qr_pendente") from erro

    if qr is None or qr["qr_pagamento"] is None:
        raise HTTPException(status_code=404, detail="qr_nao_cadastrado")

    return Response(
        content=bytes(qr["qr_pagamento"]),
        media_type=qr["qr_media_type"],
        headers={"Cache-Control": "private, no-store"},
    )


@app.put("/academia/qr")
async def salvar_qr_academia(
    request: Request,
    dono=Depends(somente_dono),
):
    exigir_escrita_local()
    tipo = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if tipo not in TIPOS_QR_PERMITIDOS:
        raise HTTPException(status_code=415, detail="formato_de_qr_nao_suportado")

    partes: list[bytes] = []
    tamanho = 0
    async for parte in request.stream():
        tamanho += len(parte)
        if tamanho > TAMANHO_MAXIMO_QR:
            raise HTTPException(status_code=413, detail="imagem_de_qr_muito_grande")
        partes.append(parte)
    conteudo = b"".join(partes)
    if not conteudo or not imagem_qr_valida(tipo, conteudo):
        raise HTTPException(status_code=400, detail="imagem_de_qr_invalida")

    try:
        with get_connection() as conn:
            academia = conn.execute(
                "UPDATE academias SET qr_pagamento = %s, qr_media_type = %s "
                "WHERE id = %s RETURNING id",
                (conteudo, tipo, dono["academia_id"]),
            ).fetchone()
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_qr_pendente") from erro

    if academia is None:
        raise HTTPException(status_code=404, detail="academia_nao_encontrada")
    return {"salvo": True}


@app.delete("/academia/qr")
def remover_qr_academia(dono=Depends(somente_dono)):
    exigir_escrita_local()
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE academias SET qr_pagamento = NULL, qr_media_type = NULL "
                "WHERE id = %s",
                (dono["academia_id"],),
            )
    except errors.UndefinedColumn as erro:
        raise HTTPException(status_code=503, detail="migracao_qr_pendente") from erro
    return {"removido": True}


@app.post("/pagamentos/{pagamento_id}/pagar")
def pagar(
    pagamento_id: int,
    usuario=Depends(usuario_de_academia),
):
    exigir_escrita_local()
    academia_id = usuario["academia_id"]

    with get_connection() as conn:
        tem_moeda = esquema_de_moeda_disponivel(conn)
        if tem_moeda and outbox_ativa():
            pagamento = conn.execute(
                "SELECT id, academia_id, aluno_id, valor, moeda, vencimento, status, sync_id "
                "FROM pagamentos "
                "WHERE id = %s AND academia_id = %s "
                "FOR UPDATE",
                (pagamento_id, academia_id),
            ).fetchone()
        elif tem_moeda:
            pagamento = conn.execute(
                "SELECT id, academia_id, aluno_id, valor, moeda, vencimento, status "
                "FROM pagamentos "
                "WHERE id = %s AND academia_id = %s "
                "FOR UPDATE",
                (pagamento_id, academia_id),
            ).fetchone()
        elif outbox_ativa():
            pagamento = conn.execute(
                "SELECT id, academia_id, aluno_id, valor, vencimento, status, sync_id "
                "FROM pagamentos WHERE id = %s AND academia_id = %s FOR UPDATE",
                (pagamento_id, academia_id),
            ).fetchone()
        else:
            pagamento = conn.execute(
                "SELECT id, academia_id, aluno_id, valor, vencimento, status "
                "FROM pagamentos WHERE id = %s AND academia_id = %s FOR UPDATE",
                (pagamento_id, academia_id),
            ).fetchone()

        if pagamento is not None and not tem_moeda:
            pagamento["moeda"] = usuario["moeda"]

        if pagamento is None:
            raise HTTPException(
                status_code=404,
                detail="pagamento_nao_encontrado",
            )

        if pagamento["status"] == "pago":
            raise HTTPException(
                status_code=409,
                detail="pagamento_ja_pago",
            )

        aluno = conn.execute(
            "SELECT plano_id FROM alunos "
            "WHERE id = %s AND academia_id = %s FOR SHARE",
            (pagamento["aluno_id"], academia_id),
        ).fetchone()
        if aluno is None:
            raise HTTPException(status_code=404, detail="pagamento_nao_encontrado")
        if aluno["plano_id"] is None:
            raise HTTPException(status_code=409, detail="aluno_sem_plano")

        atualizado = conn.execute(
            "UPDATE pagamentos "
            "SET status = 'pago', data_pagamento = %s "
            "WHERE id = %s AND academia_id = %s "
            "RETURNING status, data_pagamento",
            (date.today(), pagamento_id, academia_id),
        ).fetchone()

        academia_uuid = None
        aluno_uuid = None
        if outbox_ativa():
            academia_uuid = sync_id_academia(conn, academia_id)
            aluno = conn.execute(
                "SELECT sync_id FROM alunos "
                "WHERE id = %s AND academia_id = %s",
                (pagamento["aluno_id"], academia_id),
            ).fetchone()
            aluno_uuid = aluno["sync_id"] if aluno else None
            enfileirar_evento(
                conn,
                academia_sync_id=academia_uuid,
                entity_type="pagamento",
                entity_sync_id=pagamento["sync_id"],
                payload={
                    "id": str(pagamento["sync_id"]),
                    "aluno_id": str(aluno_uuid) if aluno_uuid else None,
                    "valor": str(pagamento["valor"]),
                    "moeda": pagamento["moeda"],
                    "vencimento": pagamento["vencimento"].isoformat(),
                    "data_pagamento": atualizado["data_pagamento"].isoformat(),
                    "status": atualizado["status"],
                },
            )

        if tem_moeda:
            plano = conn.execute(
                "SELECT pl.valor, pl.moeda, pl.duracao_dias "
                "FROM alunos a JOIN planos pl ON pl.id = a.plano_id "
                "WHERE a.id = %s AND a.academia_id = %s",
                (pagamento["aluno_id"], academia_id),
            ).fetchone()
        else:
            plano = conn.execute(
                "SELECT pl.valor, pl.duracao_dias "
                "FROM alunos a JOIN planos pl ON pl.id = a.plano_id "
                "WHERE a.id = %s AND a.academia_id = %s",
                (pagamento["aluno_id"], academia_id),
            ).fetchone()
            if plano is not None:
                plano["moeda"] = pagamento["moeda"]

        proximo_vencimento = None

        if plano is not None:
            data_base = max(pagamento["vencimento"], date.today())
            proximo_vencimento = data_base + timedelta(
                days=plano["duracao_dias"]
            )

            if tem_moeda and outbox_ativa():
                novo_pagamento = conn.execute(
                    "INSERT INTO pagamentos "
                    "(academia_id, aluno_id, valor, moeda, vencimento) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "RETURNING sync_id, valor, moeda, vencimento, status",
                    (
                        academia_id,
                        pagamento["aluno_id"],
                        plano["valor"],
                        plano["moeda"],
                        proximo_vencimento,
                    ),
                ).fetchone()
            elif tem_moeda:
                conn.execute(
                    "INSERT INTO pagamentos "
                    "(academia_id, aluno_id, valor, moeda, vencimento) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (academia_id, pagamento["aluno_id"], plano["valor"], plano["moeda"], proximo_vencimento),
                )
                novo_pagamento = None
            elif outbox_ativa():
                novo_pagamento = conn.execute(
                    "INSERT INTO pagamentos "
                    "(academia_id, aluno_id, valor, vencimento) "
                    "VALUES (%s, %s, %s, %s) "
                    "RETURNING sync_id, valor, vencimento, status",
                    (academia_id, pagamento["aluno_id"], plano["valor"], proximo_vencimento),
                ).fetchone()
                novo_pagamento["moeda"] = plano["moeda"]
            else:
                conn.execute(
                    "INSERT INTO pagamentos "
                    "(academia_id, aluno_id, valor, vencimento) "
                    "VALUES (%s, %s, %s, %s)",
                    (academia_id, pagamento["aluno_id"], plano["valor"], proximo_vencimento),
                )
                novo_pagamento = None

            if outbox_ativa():
                enfileirar_evento(
                    conn,
                    academia_sync_id=academia_uuid,
                    entity_type="pagamento",
                    entity_sync_id=novo_pagamento["sync_id"],
                    payload={
                        "id": str(novo_pagamento["sync_id"]),
                        "aluno_id": str(aluno_uuid) if aluno_uuid else None,
                        "valor": str(novo_pagamento["valor"]),
                        "moeda": novo_pagamento["moeda"],
                        "vencimento": novo_pagamento["vencimento"].isoformat(),
                        "data_pagamento": None,
                        "status": novo_pagamento["status"],
                    },
                )

    return {
        "pago": True,
        "proximo_vencimento": proximo_vencimento,
    }


@app.delete("/pagamentos/{pagamento_id}", status_code=204)
def excluir_pagamento(pagamento_id: int, dono=Depends(somente_dono)):
    """Remove um pagamento já quitado; somente o proprietário pode apagar histórico."""
    exigir_escrita_local()
    academia_id = dono["academia_id"]
    with get_connection() as conn:
        if outbox_ativa():
            pagamento = conn.execute(
                "SELECT id, status, sync_id FROM pagamentos "
                "WHERE id = %s AND academia_id = %s FOR UPDATE",
                (pagamento_id, academia_id),
            ).fetchone()
        else:
            pagamento = conn.execute(
                "SELECT id, status FROM pagamentos "
                "WHERE id = %s AND academia_id = %s FOR UPDATE",
                (pagamento_id, academia_id),
            ).fetchone()
        if pagamento is None:
            raise HTTPException(status_code=404, detail="pagamento_nao_encontrado")
        if pagamento["status"] != "pago":
            raise HTTPException(status_code=409, detail="pagamento_nao_pago_para_excluir")
        if outbox_ativa():
            enfileirar_evento(
                conn,
                academia_sync_id=sync_id_academia(conn, academia_id),
                entity_type="pagamento",
                entity_sync_id=pagamento["sync_id"],
                operation="delete",
                payload={"id": str(pagamento["sync_id"])},
            )
        conn.execute(
            "DELETE FROM pagamentos WHERE id = %s AND academia_id = %s",
            (pagamento_id, academia_id),
        )
    return Response(status_code=204)


@app.post("/sync/receber")
async def receber_sync(
    request: Request,
    authorization: str | None = Header(default=None),
    x_frequency_academy_id: UUID | None = Header(default=None),
):
    if os.getenv("SYNC_RECEIVER_ENABLED", "").strip().upper() != "YES":
        raise HTTPException(status_code=404, detail="sync_receptor_desabilitado")

    allow_local_http = (
        os.getenv("SYNC_RECEIVER_ALLOW_HTTP_STAGING", "").strip().upper() == "YES"
        and (request.client.host if request.client else "")
        in {"127.0.0.1", "::1", "localhost", "testclient"}
    )
    if request.url.scheme != "https" and not allow_local_http:
        raise HTTPException(status_code=426, detail="sync_exige_https")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="sync_json_obrigatorio")
    if x_frequency_academy_id is None:
        raise HTTPException(status_code=401, detail="sync_credencial_invalida")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="sync_credencial_invalida")
    token = authorization[7:].strip()
    if not 40 <= len(token) <= 256:
        raise HTTPException(status_code=401, detail="sync_credencial_invalida")
    try:
        token_bytes = token.encode("ascii")
    except UnicodeEncodeError as error:
        raise HTTPException(status_code=401, detail="sync_credencial_invalida") from error

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 131072:
                raise HTTPException(status_code=413, detail="sync_evento_muito_grande")
        except ValueError as error:
            raise HTTPException(status_code=400, detail="sync_requisicao_invalida") from error

    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > 131072:
            raise HTTPException(status_code=413, detail="sync_evento_muito_grande")
        chunks.extend(chunk)
    try:
        evento = SyncEvent.model_validate(json.loads(chunks.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        raise HTTPException(status_code=422, detail="sync_evento_invalido") from error

    token_hash = hashlib.sha256(token_bytes).hexdigest()
    with get_connection() as conn:
        credencial = conn.execute(
            "SELECT academia_id, token_hash "
            "FROM sync_credentials "
            "WHERE source_academia_sync_id = %s AND enabled IS TRUE "
            "FOR SHARE",
            (x_frequency_academy_id,),
        ).fetchone()
        if credencial is None or not hmac.compare_digest(
            token_hash,
            credencial["token_hash"] if credencial else "0" * 64,
        ):
            raise HTTPException(status_code=401, detail="sync_credencial_invalida")

        duplicado = receber_evento(
            conn,
            academia_id=credencial["academia_id"],
            source_academia_sync_id=x_frequency_academy_id,
            evento=evento,
        )

    return {
        "event_id": str(evento.event_id),
        "revision": evento.revision,
        "received": True,
        "duplicate": duplicado,
    }


@app.get("/sync/estado-local")
def estado_fila_local(usuario=Depends(usuario_de_academia)):
    if not outbox_ativa():
        return {
            "fila_habilitada": False,
            "envio_automatico_implementado": True,
            "academia_sync_id": None,
            "snapshot_inicial_enfileirado": False,
            "revisao_local": None,
            "pendentes": None,
            "evento_pendente_mais_antigo": None,
            "erro_evento_pendente_mais_antigo": None,
            "proxima_tentativa": None,
            "ultimo_envio": None,
        }

    with get_connection() as conn:
        academia_uuid = sync_id_academia(conn, usuario["academia_id"])
        fila = conn.execute(
            "SELECT "
            "count(*) FILTER (WHERE delivered_at IS NULL) AS pendentes, "
            "min(created_at) FILTER (WHERE delivered_at IS NULL) "
            "AS evento_pendente_mais_antigo, "
            "max(delivered_at) AS ultimo_envio "
            "FROM sync_outbox WHERE academia_sync_id = %s",
            (academia_uuid,),
        ).fetchone()
        snapshot = conn.execute(
            "SELECT event_count FROM sync_snapshot_runs "
            "WHERE academia_sync_id = %s",
            (academia_uuid,),
        ).fetchone()
        revisao = conn.execute(
            "SELECT last_revision FROM sync_revision_counters "
            "WHERE academia_sync_id = %s",
            (academia_uuid,),
        ).fetchone()
        proximo_evento = conn.execute(
            "SELECT last_error_code, next_attempt_at FROM sync_outbox "
            "WHERE academia_sync_id = %s AND delivered_at IS NULL "
            "ORDER BY revision LIMIT 1",
            (academia_uuid,),
        ).fetchone()

    return {
        "fila_habilitada": True,
        "envio_automatico_implementado": True,
        "academia_sync_id": str(academia_uuid),
        "snapshot_inicial_enfileirado": snapshot is not None,
        "eventos_snapshot_inicial": snapshot["event_count"] if snapshot else None,
        "revisao_local": revisao["last_revision"] if revisao else 0,
        "pendentes": fila["pendentes"],
        "evento_pendente_mais_antigo": fila["evento_pendente_mais_antigo"],
        "erro_evento_pendente_mais_antigo": (
            proximo_evento["last_error_code"] if proximo_evento else None
        ),
        "proxima_tentativa": (
            proximo_evento["next_attempt_at"] if proximo_evento else None
        ),
        "ultimo_envio": fila["ultimo_envio"],
    }

@app.post("/cadastro-academia", status_code=201)
def cadastrar_academia_publica(novo: CadastroAcademiaPublico):
    """Create an academy account in pending-plan state."""
    exigir_escrita_local()
    nome_academia = novo.nome_academia.strip()
    pais = novo.pais.strip()
    nome_dono = novo.nome_dono.strip()
    email = novo.email_dono.strip().lower()
    telefone = novo.telefone_dono.strip()
    if not nome_academia or not pais or not nome_dono or not email or len(re.sub(r"\D", "", telefone)) < 7:
        raise HTTPException(status_code=400, detail="preencha_todos_os_campos")
    if len(novo.senha_dono) < 8:
        raise HTTPException(status_code=400, detail="a_senha_precisa_ter_pelo_menos_8_caracteres")
    try:
        with get_connection() as conn:
            if conn.execute("SELECT 1 FROM usuarios WHERE lower(email) = %s", (email,)).fetchone():
                raise HTTPException(status_code=409, detail="cliente_ja_cadastrado")
            idioma, moeda = preferencias_iniciais_academia(pais)
            trial_inicio = date.today()
            trial_fim = trial_inicio + timedelta(days=7)
            colunas = ["nome", "pais", "ativa", "status_comercial", "trial_inicio", "trial_fim"]
            valores: list[object] = [nome_academia, pais, True, "ativa", trial_inicio, trial_fim]
            telefone_disponivel = conn.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'academias' AND column_name = 'telefone'"
            ).fetchone()
            if telefone_disponivel:
                colunas.append("telefone")
                valores.append(telefone)
            if esquema_de_moeda_disponivel(conn):
                colunas.extend(("idioma", "moeda"))
                valores.extend((idioma, moeda))
            academia = conn.execute(
                "INSERT INTO academias (" + ", ".join(colunas) + ") VALUES (" + ", ".join("%s" for _ in valores) + ") RETURNING id",
                valores,
            ).fetchone()
            token, token_hash = _criar_token_verificacao()
            expira = datetime.now(timezone.utc) + timedelta(hours=24)
            conn.execute(
                "INSERT INTO usuarios (academia_id, nome, email, senha_hash, papel, ativo, email_verificacao_token_hash, email_verificacao_expira_em) "
                "VALUES (%s, %s, %s, %s, 'dono', TRUE, %s, %s)",
                (academia["id"], nome_dono, email, gerar_hash(novo.senha_dono), token_hash, expira),
            )
            garantir_lead_cadastro_academia(
                conn,
                academia_id=academia["id"],
                nome_academia=nome_academia,
                pais=pais,
                nome_dono=nome_dono,
                email=email,
                telefone=telefone,
            )
    except errors.UniqueViolation as erro:
        raise HTTPException(status_code=409, detail="cliente_ja_cadastrado") from erro
    email_enviado = _enviar_email_verificacao(email, nome_dono, token)
    return {
        "criado": True,
        "status": "experiencia_7_dias",
        "trial_inicio": trial_inicio,
        "trial_fim": trial_fim,
        "dias_experiencia": 7,
        "mensagem": "academia_criada_com_experiencia_7_dias",
        "email_verificacao_enviado": email_enviado,
        "email_verificacao_pendente": True,
    }


def imagem_campanha_email(conn) -> tuple[bytes | None, str | None]:
    """Use the configured campaign image, with the Frequency cover as a safe fallback."""
    row = conn.execute(
        "SELECT imagem, imagem_media_type FROM public.configuracao_prospeccao WHERE id IS TRUE"
    ).fetchone()
    if row and row["imagem"]:
        return bytes(row["imagem"]), row["imagem_media_type"] or "image/jpeg"
    fallback = PASTA_FRONTEND / "static" / "frequency-cover-whatsapp.png"
    try:
        return fallback.read_bytes(), "image/png"
    except OSError:
        return None, None


@app.get("/verificar-email")
def verificar_email(token: str = Query(..., min_length=20, max_length=200)):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with get_connection() as conn:
        usuario = conn.execute(
            "SELECT id, email_verificacao_expira_em FROM public.usuarios "
            "WHERE email_verificacao_token_hash = %s AND email_verificado_em IS NULL",
            (token_hash,),
        ).fetchone()
        if usuario is None:
            raise HTTPException(status_code=400, detail="token_verificacao_invalido")
        if usuario["email_verificacao_expira_em"] and usuario["email_verificacao_expira_em"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="token_verificacao_expirado")
        conn.execute(
            "UPDATE public.usuarios SET email_verificado_em = now(), email_verificacao_token_hash = NULL, email_verificacao_expira_em = NULL "
            "WHERE id = %s",
            (usuario["id"],),
        )
    return {"verificado": True, "mensagem": "email_verificado_com_sucesso"}


@app.post("/auth/verificacao/reenviar")
def reenviar_verificacao(email: str = Query(..., min_length=3, max_length=254)):
    email = email.strip().lower()
    with get_connection() as conn:
        usuario = conn.execute(
            "SELECT id, nome, email_verificado_em FROM public.usuarios WHERE lower(email) = %s AND papel = 'dono'",
            (email,),
        ).fetchone()
        if usuario is None or usuario["email_verificado_em"] is not None:
            return {"enviado": True}
        token, token_hash = _criar_token_verificacao()
        conn.execute(
            "UPDATE public.usuarios SET email_verificacao_token_hash = %s, email_verificacao_expira_em = now() + interval '24 hours', email_verificacao_enviado_em = now() WHERE id = %s",
            (token_hash, usuario["id"]),
        )
    return {"enviado": _enviar_email_verificacao(email, usuario["nome"], token)}


@app.post("/login")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    email = form.username.strip().lower()
    client_ip = request.client.host if request.client else None
    retry_after = login_rate_limiter.retry_after(email, client_ip)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="login_temporariamente_limitado",
            headers={"Retry-After": str(retry_after)},
        )

    if len(email) > 254 or len(form.password) > 256:
        login_rate_limiter.record_failure(email, client_ip)
        raise HTTPException(
            status_code=401,
            detail="email_ou_senha_incorretos",
        )

    with get_connection() as conn:
        usuario = conn.execute(
            "SELECT u.id, u.nome, u.senha_hash, u.papel, u.email_verificado_em, u.email_verificacao_token_hash "
            "FROM usuarios u "
            "LEFT JOIN academias a ON a.id = u.academia_id "
            "WHERE u.email = %s AND u.ativo AND ("
            "(u.papel = 'admin_plataforma' AND u.academia_id IS NULL) "
            "OR (u.academia_id IS NOT NULL AND a.ativa IS TRUE)"
            ")",
            (email,),
        ).fetchone()

    senha_valida = verificar_senha(
        form.password,
        usuario["senha_hash"] if usuario is not None else None,
    )
    if usuario is None or not senha_valida:
        login_rate_limiter.record_failure(email, client_ip)
        raise HTTPException(
            status_code=401,
            detail="email_ou_senha_incorretos",
        )

    if usuario["papel"] == "dono" and usuario.get("email_verificacao_token_hash") and usuario.get("email_verificado_em") is None:
        raise HTTPException(status_code=403, detail="email_nao_verificado")

    login_rate_limiter.clear(email, client_ip)
    return {
        "access_token": criar_token(usuario),
        "token_type": "bearer",
        "nome": usuario["nome"],
        "papel": usuario["papel"],
    }

@app.patch("/minha-senha")
def alterar_minha_senha(dados: AlteracaoSenha, usuario=Depends(usuario_atual)):
    exigir_escrita_local()
    with get_connection() as conn:
        atual = conn.execute("SELECT senha_hash FROM public.usuarios WHERE id = %s AND ativo FOR UPDATE", (usuario["id"],)).fetchone()
        if atual is None or not verificar_senha(dados.senha_atual, atual["senha_hash"]):
            raise HTTPException(status_code=400, detail="senha_atual_incorreta")
        conn.execute("UPDATE public.usuarios SET senha_hash = %s WHERE id = %s", (gerar_hash(dados.nova_senha), usuario["id"]))
    return {"alterada": True}


@app.get("/eu")
def eu(usuario=Depends(usuario_atual)):
    recursos = {"nivel": None, "cameras": False, "youtube": False}
    if usuario["papel"] == "dono" and not usuario.get("bloqueada_frequency"):
        with get_connection() as conn:
            recursos = recursos_da_academia(conn, usuario["academia_id"])
    return {**usuario, "recursos_frequency": recursos}


@app.get("/academia/integracoes/{recurso}")
def autorizar_integracao(recurso: str, dono=Depends(somente_dono)):
    if recurso not in {"cameras", "youtube"}:
        raise HTTPException(404, "recurso_nao_encontrado")
    if modo_somente_consulta():
        raise HTTPException(403, "modo_somente_consulta")
    with get_connection() as conn:
        recursos = recursos_da_academia(conn, dono["academia_id"])
        if not recursos[recurso]:
            raise HTTPException(403, "recurso_exclusivo_plano_premium")
    return {"permitido": True, "recurso": recurso}


@app.get("/academia/integracoes/youtube/search")
def pesquisar_youtube(
    q: str = Query(..., min_length=2, max_length=120),
    dono=Depends(somente_dono),
):
    """Busca vídeos públicos para seleção dentro do player Premium."""
    if modo_somente_consulta():
        raise HTTPException(403, "modo_somente_consulta")
    with get_connection() as conn:
        recursos = recursos_da_academia(conn, dono["academia_id"])
        if not recursos["youtube"]:
            raise HTTPException(403, "recurso_exclusivo_plano_premium")
    termo = " ".join(q.split())
    if len(termo) < 2:
        raise HTTPException(400, "busca_muito_curta")
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(termo)
    pedido = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Frequency; YouTube search)"},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=8) as resposta:
            pagina = resposta.read().decode("utf-8", "replace")
    except Exception as erro:
        raise HTTPException(502, "youtube_indisponivel") from erro
    resultados = []
    vistos = set()
    padroes = [
        re.compile(
            r'"videoRenderer":\{.*?"videoId":"([A-Za-z0-9_-]{11})".*?'
            r'"title":\{"runs":\[\{"text":"(.*?)"',
            re.DOTALL,
        ),
        re.compile(
            r'videoId\\x22:\\x22([A-Za-z0-9_-]{11}).{0,3000}?'
            r'title\\x22:\\x7b\\x22runs\\x22:\\x5b\\x7b\\x22text\\x22:\\x22(.*?)\\x22',
            re.DOTALL,
        ),
    ]
    encontrados = []
    for padrao in padroes:
        encontrados.extend(padrao.findall(pagina))
    for video_id, titulo_bruto in encontrados:
        if video_id in vistos:
            continue
        try:
            titulo = json.loads('"' + titulo_bruto + '"')
        except json.JSONDecodeError:
            titulo = titulo_bruto.replace("\\\"", '"')
        vistos.add(video_id)
        resultados.append({
            "id": video_id,
            "titulo": titulo,
            "miniatura": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        })
        if len(resultados) >= 8:
            break
    return {"resultados": resultados, "termo": termo}

@app.get("/academia/integracoes/youtube/check")
def verificar_video_youtube(
    video_id: str = Query(..., min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]{11}$"),
    dono=Depends(somente_dono),
):
    """Confirma que o vídeo existe antes de abrir um iframe vazio."""
    if modo_somente_consulta():
        raise HTTPException(403, "modo_somente_consulta")
    with get_connection() as conn:
        recursos = recursos_da_academia(conn, dono["academia_id"])
        if not recursos["youtube"]:
            raise HTTPException(403, "recurso_exclusivo_plano_premium")
    url = "https://www.youtube.com/oembed?url=" + urllib.parse.quote(
        f"https://www.youtube.com/watch?v={video_id}", safe=""
    ) + "&format=json"
    pedido = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Frequency; YouTube check)"})
    try:
        with urllib.request.urlopen(pedido, timeout=4) as resposta:
            return {"disponivel": resposta.status == 200}
    except Exception:
        return {"disponivel": False}

@app.post("/admin/academias", status_code=201)
def criar_academia(
    nova: NovaAcademiaComDono,
    admin=Depends(somente_admin_plataforma),
):
    exigir_escrita_local()
    nome_academia = nova.nome_academia.strip()
    pais = nova.pais.strip()
    nome_dono = nova.nome_dono.strip()
    email_dono = nova.email_dono.strip().lower()
    telefone_dono = nova.telefone_dono.strip()

    logo_monitor = None
    if nova.logo_monitor_base64 is None:
        if nova.logo_monitor_media_type is not None:
            raise HTTPException(status_code=400, detail="foto_invalida")
    else:
        if nova.logo_monitor_media_type is None:
            raise HTTPException(status_code=400, detail="foto_invalida")
        try:
            conteudo_logo = base64.b64decode(nova.logo_monitor_base64, validate=True)
        except (binascii.Error, ValueError) as erro:
            raise HTTPException(status_code=400, detail="foto_invalida") from erro
        logo_monitor = normalizar_foto_aluno(nova.logo_monitor_media_type, conteudo_logo)

    if not nome_academia or not pais or not nome_dono or not email_dono or (
        telefone_dono and len(re.sub(r"\D", "", telefone_dono)) < 7
    ):
        raise HTTPException(
            status_code=400,
            detail="preencha_todos_os_campos",
        )

    if len(nova.senha_dono) < 8:
        raise HTTPException(
            status_code=400,
            detail="a_senha_precisa_ter_pelo_menos_8_caracteres",
        )

    if (nova.plano_frequency_id is None) != (nova.vencimento_frequency is None):
        raise HTTPException(status_code=400, detail="plano_e_vencimento_devem_ser_informados_juntos")
    if nova.vencimento_frequency is not None and nova.vencimento_frequency < date.today():
        raise HTTPException(status_code=400, detail="vencimento_frequency_nao_pode_ser_passado")

    try:
        with get_connection() as conn:
            plano_frequency = None
            if nova.plano_frequency_id is not None:
                exigir_migracao_frequency(conn)
                plano_frequency = conn.execute(
                    "SELECT id, nome, valor, moeda, duracao_dias "
                    "FROM public.planos_frequency WHERE id = %s AND ativo IS TRUE",
                    (nova.plano_frequency_id,),
                ).fetchone()
                if plano_frequency is None:
                    raise HTTPException(status_code=404, detail="plano_frequency_nao_encontrado")

            existente = conn.execute(
                "SELECT id FROM usuarios WHERE email = %s",
                (email_dono,),
            ).fetchone()

            if existente is not None:
                raise HTTPException(
                    status_code=409,
                    detail="email_ja_cadastrado",
                )

            idioma, moeda = preferencias_iniciais_academia(pais)
            status_comercial = "ativa" if nova.plano_frequency_id is not None else "aguardando_plano"
            colunas = ["nome", "pais", "ativa", "status_comercial"]
            valores: list[object] = [nome_academia, pais, True, status_comercial]
            if esquema_de_moeda_disponivel(conn):
                colunas.extend(("idioma", "moeda"))
                valores.extend((idioma, moeda))
            telefone_disponivel = conn.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'academias' AND column_name = 'telefone'"
            ).fetchone()
            if telefone_disponivel:
                colunas.append("telefone")
                valores.append(telefone_dono)
            if logo_monitor is not None:
                colunas.extend(("logo_monitor", "logo_monitor_media_type"))
                valores.extend((logo_monitor, "image/jpeg"))
            placeholders = ", ".join("%s" for _ in valores)
            academia = conn.execute(
                "INSERT INTO academias (" + ", ".join(colunas) + ") "
                "VALUES (" + placeholders + ") RETURNING id",
                valores,
            ).fetchone()

            dono = conn.execute(
                "INSERT INTO usuarios "
                "(academia_id, nome, email, senha_hash, papel, ativo, email_verificado_em) "
                "VALUES (%s, %s, %s, %s, 'dono', TRUE, now()) RETURNING id",
                (
                    academia["id"],
                    nome_dono,
                    email_dono,
                    gerar_hash(nova.senha_dono),
                ),
            ).fetchone()

            fatura_frequency = None
            if plano_frequency is not None:
                inicio = date.today()
                fim = inicio + timedelta(days=plano_frequency["duracao_dias"] - 1)
                assinatura = conn.execute(
                    "INSERT INTO public.assinaturas_frequency "
                    "(academia_id, plano_id, inicio, proximo_vencimento, criada_por) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (
                        academia["id"], plano_frequency["id"], inicio,
                        nova.vencimento_frequency, admin["id"],
                    ),
                ).fetchone()
                fatura_frequency = conn.execute(
                    "INSERT INTO public.faturas_frequency "
                    "(academia_id, assinatura_id, referencia, periodo_inicio, periodo_fim, "
                    "valor, moeda, vencimento, criada_por) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        academia["id"], assinatura["id"],
                        f"Frequency · {plano_frequency['nome']}", inicio, fim,
                        plano_frequency["valor"], plano_frequency["moeda"],
                        nova.vencimento_frequency, admin["id"],
                    ),
                ).fetchone()
            auditoria_disponivel = conn.execute(
                "SELECT to_regclass('public.auditoria_frequency') IS NOT NULL AS presente"
            ).fetchone()["presente"]
            if auditoria_disponivel:
                auditar_frequency(
                    conn, admin["id"],
                    "cliente_cadastrado_com_assinatura" if fatura_frequency else "academia_cadastrada",
                    "academia", academia["id"],
                    {
                        "dono_id": dono["id"],
                        "plano_id": plano_frequency["id"] if plano_frequency else None,
                        "fatura_id": fatura_frequency["id"] if fatura_frequency else None,
                    },
                )

    except errors.UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail="academia_ou_email_ja_cadastrado",
        )
    except errors.UndefinedColumn as erro:
        if logo_monitor is not None:
            raise HTTPException(status_code=503, detail="migracao_monitor_pendente") from erro
        raise

    return {
        "academia_id": academia["id"],
        "dono_id": dono["id"],
        "email_dono": email_dono,
        "assinatura_frequency_criada": fatura_frequency is not None,
        "email_verificacao_enviado": False,
        "email_verificacao_pendente": False,
        "fatura_frequency_id": fatura_frequency["id"] if fatura_frequency else None,
    }

@app.get("/admin/academias")
def listar_academias(admin=Depends(somente_admin_plataforma)):
    with get_connection() as conn:
        academias = conn.execute(
            "SELECT a.id, a.nome, a.pais, a.ativa, "
            "a.cidade, a.estado, a.endereco, a.codigo_postal, a.telefone, "
            "u.nome AS nome_dono, u.email AS email_dono "
            "FROM academias a "
            "LEFT JOIN usuarios u ON u.academia_id = a.id AND u.papel = 'dono' "
            "ORDER BY a.id"
        ).fetchall()

    return academias


@app.patch("/admin/academias/{academia_id}/status")
def mudar_status_academia(
    academia_id: int,
    status: StatusAcademia,
    admin=Depends(somente_admin_plataforma),
):
    exigir_escrita_local()
    with get_connection() as conn:
        academia = conn.execute(
            "UPDATE academias "
            "SET ativa = %s "
            "WHERE id = %s "
            "RETURNING id, nome, pais, ativa",
            (status.ativa, academia_id),
        ).fetchone()
        auditoria_disponivel = conn.execute(
            "SELECT to_regclass('public.auditoria_frequency') IS NOT NULL AS presente"
        ).fetchone()["presente"]
        if academia is not None and auditoria_disponivel:
            auditar_frequency(
                conn, admin["id"], "academia_status_alterado", "academia", academia_id,
                {"ativa": status.ativa},
            )

    if academia is None:
        raise HTTPException(
            status_code=404,
            detail="academia_nao_encontrada",
        )

    return academia

@app.post("/usuarios/recepcao", status_code=201)
def criar_recepcionista(
    novo: NovoRecepcionista,
    dono=Depends(somente_dono),
):
    exigir_escrita_local()
    nome = novo.nome.strip()
    email = novo.email.strip().lower()

    if not nome or not email:
        raise HTTPException(
            status_code=400,
            detail="preencha_nome_e_email",
        )

    if len(novo.senha) < 8:
        raise HTTPException(
            status_code=400,
            detail="a_senha_precisa_ter_pelo_menos_8_caracteres",
        )

    try:
        with get_connection() as conn:
            existente = conn.execute(
                "SELECT id FROM usuarios WHERE email = %s",
                (email,),
            ).fetchone()

            if existente is not None:
                raise HTTPException(
                    status_code=409,
                    detail="email_ja_cadastrado",
                )

            recepcionista = conn.execute(
                "INSERT INTO usuarios "
                "(academia_id, nome, email, senha_hash, papel, ativo) "
                "VALUES (%s, %s, %s, %s, 'recepcao', TRUE) "
                "RETURNING id",
                (
                    dono["academia_id"],
                    nome,
                    email,
                    gerar_hash(novo.senha),
                ),
            ).fetchone()

    except errors.UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail="email_ja_cadastrado",
        )

    return {
        "id": recepcionista["id"],
        "nome": nome,
        "email": email,
        "papel": "recepcao",
    }
@app.get("/usuarios/recepcao")
def listar_recepcionistas(dono=Depends(somente_dono)):
    with get_connection() as conn:
        recepcionistas = conn.execute(
            "SELECT id, nome, email, ativo "
            "FROM usuarios "
            "WHERE academia_id = %s AND papel = 'recepcao' "
            "ORDER BY nome, id",
            (dono["academia_id"],),
        ).fetchall()

    return recepcionistas


@app.patch("/usuarios/recepcao/{usuario_id}/status")
def mudar_status_recepcionista(
    usuario_id: int,
    status: StatusRecepcionista,
    dono=Depends(somente_dono),
):
    exigir_escrita_local()
    with get_connection() as conn:
        recepcionista = conn.execute(
            "UPDATE usuarios "
            "SET ativo = %s "
            "WHERE id = %s AND academia_id = %s AND papel = 'recepcao' "
            "RETURNING id, nome, email, ativo",
            (status.ativo, usuario_id, dono["academia_id"]),
        ).fetchone()

    if recepcionista is None:
        raise HTTPException(
            status_code=404,
            detail="recepcionista_nao_encontrado",
        )

    return recepcionista






class EnvioEmailsProspeccao(BaseModel):
    lead_ids: list[int] = Field(min_length=1, max_length=500)


class EnvioFilaProspeccao(BaseModel):
    lead_ids: list[int] = Field(min_length=1, max_length=500)
    canal: str = Field(default="email", pattern="^(email|whatsapp)$")


def _html_email_prospeccao(body: str, nome: str, cidade: str, image_cid: str | None = None) -> str:
    """Render the editable campaign copy inside a consistent Frequency layout."""
    paragraphs = "".join(
        f'<p style="margin:0 0 18px;line-height:1.65;color:#33483c">{html.escape(paragraph).replace(chr(10), "<br>")}</p>'
        for paragraph in body.strip().split("\n\n") if paragraph.strip()
    )
    image = (
        f'<img src="cid:{html.escape(image_cid or "")}" alt="Frequency Gym" '
        'style="display:block;width:100%;max-width:640px;height:auto;border:0;border-radius:14px;margin:0 0 24px">'
        if image_cid else ""
    )
    safe_name = html.escape(nome or "academia")
    safe_city = html.escape(cidade or "")
    return f'''<!doctype html>
<html lang="es"><body style="margin:0;background:#f2f6f0;font-family:Arial,Helvetica,sans-serif;color:#10221b">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">Gestiona tu gimnasio con más claridad. Prueba Frequency Gym gratis durante 7 días.</div>
<div style="padding:24px 10px;background:#f2f6f0"><div style="max-width:640px;margin:0 auto;background:#fff;border:1px solid #d8e5d8;border-radius:22px;overflow:hidden;box-shadow:0 8px 26px rgba(16,37,27,.08)">
<div style="padding:26px 30px;background:#10251b;color:#fff"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td><div style="font-size:23px;font-weight:800;letter-spacing:-.03em">Frequency <span style="color:#c7f36a">Gym</span></div><div style="margin-top:7px;color:#b9c9bf;font-size:12px;letter-spacing:.02em">TECNOLOGÍA PARA TU EVOLUCIÓN</div></td><td align="right" style="font-size:22px;color:#c7f36a">⌁</td></tr></table></div>
<div style="padding:30px 30px 8px"><p style="margin:0 0 10px;color:#6b8c38;font-size:11px;font-weight:800;letter-spacing:.16em;text-transform:uppercase">Una gestión más inteligente</p><h1 style="margin:0 0 12px;font-size:30px;line-height:1.1;letter-spacing:-.04em;color:#10221b">Tu gimnasio, más simple de administrar.</h1><p style="margin:0 0 22px;color:#65736c;font-size:15px;line-height:1.55">Para {safe_name}{f' · {safe_city}' if safe_city else ''}</p>{image}</div>
<div style="padding:4px 30px 12px">{paragraphs}</div>
<div style="padding:4px 30px 26px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td width="33%" style="padding-right:8px;vertical-align:top"><div style="font-size:20px;color:#6eaa42">◉</div><div style="margin-top:7px;font-size:12px;font-weight:700;color:#254633">Más control</div><div style="margin-top:4px;font-size:11px;line-height:1.4;color:#718078">Alumnos y planes en un solo lugar.</div></td><td width="33%" style="padding:0 4px;vertical-align:top"><div style="font-size:20px;color:#6eaa42">↗</div><div style="margin-top:7px;font-size:12px;font-weight:700;color:#254633">Más tiempo</div><div style="margin-top:4px;font-size:11px;line-height:1.4;color:#718078">Pagos y accesos sin planillas.</div></td><td width="33%" style="padding-left:8px;vertical-align:top"><div style="font-size:20px;color:#6eaa42">✓</div><div style="margin-top:7px;font-size:12px;font-weight:700;color:#254633">Más claridad</div><div style="margin-top:4px;font-size:11px;line-height:1.4;color:#718078">Información para decidir mejor.</div></td></tr></table></div>
<div style="padding:0 30px 32px;text-align:center"><a href="https://frequencygym.tech/app?cadastro=1" style="display:inline-block;padding:15px 24px;border-radius:10px;background:#c7f36a;color:#10251b;font-size:14px;font-weight:800;text-decoration:none">Probar 7 días gratis&nbsp; →</a><p style="margin:12px 0 0;color:#7a887f;font-size:11px">Sin compromiso · Configuración sencilla · Acceso desde cualquier dispositivo</p></div>
<div style="margin:0 30px;padding:18px 0;border-top:1px solid #e5ece2;color:#65736c;font-size:11px;line-height:1.55">Recibiste este correo porque tu negocio fue identificado como posible interesado en Frequency Gym. Si no deseas recibir más información, responde “BAJA” y no volveremos a contactar.</div>
<div style="padding:18px 30px;background:#f7f9f4;color:#65736c;font-size:11px;line-height:1.5">Frequency Gym · Gestión para gimnasios<br><a href="https://frequencygym.tech" style="color:#3f6d32;text-decoration:none;font-weight:700">frequencygym.tech</a></div></div></div></body></html>'''


def _gmail_send_prospeccao(
    access_token: str,
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    image: bytes | None = None,
    image_media_type: str | None = None,
    nome: str = "",
    cidade: str = "",
) -> str:
    message = EmailMessage()
    message["From"] = formataddr(("Frequency Gym", sender))
    message["To"] = recipient
    message["Subject"] = subject
    message["Reply-To"] = sender
    message.set_content(body)
    cid = "frequency-campanha"
    html_body = _html_email_prospeccao(body, nome, cidade, cid if image else None)
    message.add_alternative(html_body, subtype="html")
    if image:
        media_type = (image_media_type or "image/jpeg").lower()
        maintype, subtype = media_type.split("/", 1) if "/" in media_type else ("image", "jpeg")
        message.get_payload()[-1].add_related(image, maintype=maintype, subtype=subtype, cid=f"<{cid}>")
    request = urllib.request.Request(
        f"{GMAIL_API_BASE_URL}/messages/send",
        data=json.dumps({"raw": base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip('=')}).encode(),
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return str(json.loads(response.read().decode()).get("id") or "")
    except urllib.error.HTTPError as exc:
        raise HTTPException(502, "gmail_envio_nao_autorizado" if exc.code in {401,403} else "gmail_envio_indisponivel") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(502, "gmail_envio_indisponivel") from exc


def _gmail_platform_access_token(conn, connection: dict) -> str:
    if connection.get("access_token") and connection.get("access_token_expira_em") and connection["access_token_expira_em"] > datetime.now(timezone.utc) + timedelta(seconds=30):
        return connection["access_token"]
    refresh = conn.execute("SELECT pgp_sym_decrypt(refresh_token, %s)::text AS token FROM public.gmail_plataforma_conexao WHERE id = 2 AND ativo", (_gmail_crypto_key(),)).fetchone()
    config = _gmail_oauth_config()
    if not refresh or not refresh["token"] or not config:
        raise HTTPException(409, "gmail_autorizacao_expirada")
    client_id, client_secret, _ = config
    token_data = _google_request(GOOGLE_OAUTH_TOKEN_URL, {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh["token"], "grant_type": "refresh_token"})
    access = str(token_data.get("access_token") or "").strip()
    if not access:
        raise HTTPException(409, "gmail_autorizacao_expirada")
    expires = max(60, int(token_data.get("expires_in") or 3600))
    conn.execute("UPDATE public.gmail_plataforma_conexao SET access_token = pgp_sym_encrypt(%s, %s), access_token_expira_em = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'), atualizado_em = CURRENT_TIMESTAMP WHERE id = 2", (access, _gmail_crypto_key(), expires))
    return access


def _whatsapp_send_prospeccao(recipient: str, message: str) -> str:
    token = os.getenv("WHATSAPP_CLOUD_API_TOKEN", "").strip()
    phone_number_id = os.getenv("WHATSAPP_CLOUD_PHONE_NUMBER_ID", "").strip()
    version = os.getenv("WHATSAPP_CLOUD_API_VERSION", "v23.0").strip()
    template_name = os.getenv("WHATSAPP_CLOUD_TEMPLATE_NAME", "").strip()
    template_language = os.getenv("WHATSAPP_CLOUD_TEMPLATE_LANGUAGE", "es").strip() or "es"
    if not token or not phone_number_id:
        raise HTTPException(503, "whatsapp_api_nao_configurada")
    if not template_name:
        raise HTTPException(503, "whatsapp_template_nao_configurado")
    phone = re.sub(r"\D", "", recipient or "")
    if not phone:
        raise HTTPException(422, "telefone_whatsapp_invalido")
    payload = {"messaging_product": "whatsapp", "to": phone, "type": "template", "template": {"name": template_name, "language": {"code": template_language}, "components": [{"type": "body", "parameters": [{"type": "text", "text": message}]}]}}
    request = urllib.request.Request(
        f"https://graph.facebook.com/{version}/{phone_number_id}/messages",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode())
            return str((data.get("messages") or [{}])[0].get("id") or "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise HTTPException(502, f"whatsapp_envio_nao_autorizado:{detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(502, "whatsapp_envio_indisponivel") from exc


@app.post("/admin/prospeccao/enviar")
def enviar_fila_prospeccao(dados: EnvioFilaProspeccao, admin=Depends(somente_admin_plataforma)):
    """Send selected leads sequentially through one official channel, without opening browser tabs."""
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        exigir_configuracao_prospeccao(conn)
        if not conn.execute("SELECT to_regclass('public.prospeccao_envios') IS NOT NULL AS presente").fetchone()["presente"]:
            raise HTTPException(503, "migracao_prospeccao_envios_pendente")
        config = configuracao_prospeccao(conn)
        imagem_email, imagem_email_media_type = imagem_campanha_email(conn)
        if dados.canal == "email":
            connection = conn.execute("SELECT email, access_token_expira_em, pgp_sym_decrypt(access_token, %s)::text AS access_token FROM public.gmail_plataforma_conexao WHERE id = 2 AND ativo", (_gmail_crypto_key(),)).fetchone()
            if not connection:
                raise HTTPException(409, "gmail_prospeccao_nao_conectado")
            sender, access = connection["email"], _gmail_platform_access_token(conn, connection)
        else:
            sender, access = None, None
        leads = conn.execute(
            "SELECT id, nome, cidade, email, telefone, whatsapp_opt_in, whatsapp_autorizacao_admin_em FROM public.leads_prospeccao "
            "WHERE id = ANY(%s) AND excluido_em IS NULL ORDER BY prioridade, id", (dados.lead_ids,)
        ).fetchall()
        enviados, falhas, ignorados = [], [], []
        for ordem, lead in enumerate(leads, 1):
            if dados.canal == "email" and not lead["email"]:
                ignorados.append({"id": lead["id"], "motivo": "sem_email"}); continue
            if dados.canal == "whatsapp" and (not lead["telefone"] or (not lead["whatsapp_opt_in"] and not lead["whatsapp_autorizacao_admin_em"])):
                ignorados.append({"id": lead["id"], "motivo": "sem_telefone_ou_optin"}); continue
            fila = conn.execute(
                "INSERT INTO public.prospeccao_envios (lead_id, ordem, canal, status, iniciado_em) VALUES (%s,%s,%s,'enviando',CURRENT_TIMESTAMP) "
                "ON CONFLICT (lead_id, canal) DO UPDATE SET ordem=EXCLUDED.ordem, status='enviando', erro=NULL, iniciado_em=CURRENT_TIMESTAMP RETURNING id",
                (lead["id"], ordem, dados.canal),
            ).fetchone()
            try:
                if dados.canal == "email":
                    provider_id = _gmail_send_prospeccao(access, sender, lead["email"], renderizar_template(config["email_assunto_template"], lead["nome"], lead["cidade"]), renderizar_template(config["email_corpo_template"], lead["nome"], lead["cidade"]), imagem_email, imagem_email_media_type, lead["nome"], lead["cidade"])
                else:
                    provider_id = _whatsapp_send_prospeccao(lead["telefone"], renderizar_template(config["whatsapp_template"], lead["nome"], lead["cidade"]))
                conn.execute("UPDATE public.prospeccao_envios SET status='enviado', provider_id=%s, concluido_em=CURRENT_TIMESTAMP WHERE id=%s", (provider_id, fila["id"]))
                conn.execute("UPDATE public.leads_prospeccao SET status_comercial='mensagem_enviada', ultimo_contato=CURRENT_DATE, ultimo_canal_contato=%s, atualizado_por=%s, atualizado_em=CURRENT_TIMESTAMP WHERE id=%s", (dados.canal, admin["id"], lead["id"]))
                enviados.append({"id": lead["id"], "provider_id": provider_id})
            except HTTPException as exc:
                conn.execute("UPDATE public.prospeccao_envios SET status='falhou', erro=%s, concluido_em=CURRENT_TIMESTAMP WHERE id=%s", (str(exc.detail)[:1000], fila["id"]))
                falhas.append({"id": lead["id"], "erro": exc.detail})
        return {"canal": dados.canal, "enviados": enviados, "falhas": falhas, "ignorados": ignorados, "total": len(leads)}


@app.post("/admin/prospeccao/enviar-email")
def enviar_emails_prospeccao(dados: EnvioEmailsProspeccao, admin=Depends(somente_admin_plataforma)):
    exigir_escrita_local()
    with get_connection() as conn:
        exigir_migracao_prospeccao(conn)
        exigir_configuracao_prospeccao(conn)
        connection = conn.execute(
            "SELECT email, access_token_expira_em, pgp_sym_decrypt(access_token, %s)::text AS access_token "
            "FROM public.gmail_plataforma_conexao WHERE id = 2 AND ativo",
            (_gmail_crypto_key(),),
        ).fetchone()
        if not connection:
            raise HTTPException(409, "gmail_prospeccao_nao_conectado")
        access = _gmail_platform_access_token(conn, connection)
        config = configuracao_prospeccao(conn)
        imagem_email, imagem_email_media_type = imagem_campanha_email(conn)
        leads = conn.execute("SELECT id, nome, cidade, email FROM public.leads_prospeccao WHERE id = ANY(%s) AND excluido_em IS NULL AND email <> '' ORDER BY id", (dados.lead_ids,)).fetchall()
        enviados, falhas = [], []
        for lead in leads:
            try:
                message_id = _gmail_send_prospeccao(access, connection["email"], lead["email"], renderizar_template(config["email_assunto_template"], lead["nome"], lead["cidade"]), renderizar_template(config["email_corpo_template"], lead["nome"], lead["cidade"]), imagem_email, imagem_email_media_type, lead["nome"], lead["cidade"])
                conn.execute("UPDATE public.leads_prospeccao SET status_comercial='mensagem_enviada', ultimo_contato=CURRENT_DATE, atualizado_por=%s, atualizado_em=CURRENT_TIMESTAMP WHERE id=%s", (admin["id"], lead["id"]))
                enviados.append({"id": lead["id"], "gmail_message_id": message_id})
            except HTTPException as exc:
                falhas.append({"id": lead["id"], "erro": exc.detail})
        return {"enviados": enviados, "falhas": falhas, "total": len(leads)}
