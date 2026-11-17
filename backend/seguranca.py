import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash

from database import get_connection
from cobranca_saas import estado_assinatura_frequency
from regionalizacao import preferencias_iniciais_academia

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError(
        "Configure SECRET_KEY com pelo menos 32 caracteres no arquivo .env."
    )

ALGORITMO = "HS256"
MINUTOS_TOKEN = 480  # o crachá vale 8 horas

hasher = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = hasher.hash(secrets.token_urlsafe(32))
oauth2 = OAuth2PasswordBearer(tokenUrl="login")


def gerar_hash(senha: str) -> str:
    return hasher.hash(senha)


def verificar_senha(senha: str, senha_hash: str | None) -> bool:
    if senha_hash is None:
        hasher.verify(senha, DUMMY_PASSWORD_HASH)
        return False
    return hasher.verify(senha, senha_hash)


def criar_token(usuario) -> str:
    expira = datetime.now(timezone.utc) + timedelta(minutes=MINUTOS_TOKEN)
    dados = {"sub": str(usuario["id"]), "exp": expira}
    return jwt.encode(dados, SECRET_KEY, algorithm=ALGORITMO)


def usuario_atual(token: str = Depends(oauth2)):
    try:
        dados = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITMO])
        usuario_id = int(dados["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="token_invalido")

    with get_connection() as conn:
        usuario = conn.execute(
            "SELECT u.id, u.academia_id, u.nome, u.papel, a.pais "
            "FROM usuarios u "
            "LEFT JOIN academias a ON a.id = u.academia_id "
            "WHERE u.id = %s AND u.ativo AND ("
            "(u.papel = 'admin_plataforma' AND u.academia_id IS NULL) "
            "OR (u.academia_id IS NOT NULL AND a.ativa IS TRUE)"
            ")",
            (usuario_id,),
        ).fetchone()
        if usuario is not None and usuario["academia_id"] is not None:
            estado = estado_assinatura_frequency(conn, usuario["academia_id"])
            usuario.update({key: value for key, value in estado.items() if key != "fatura_frequency"})

    if usuario is None:
        raise HTTPException(status_code=401, detail="usuario_invalido")

    idioma, moeda = preferencias_iniciais_academia(usuario["pais"])
    usuario["idioma"] = idioma
    usuario["moeda"] = moeda
    return usuario


def usuario_de_academia(usuario=Depends(usuario_atual)):
    if usuario["papel"] not in {"dono", "recepcao"} or not usuario["academia_id"]:
        raise HTTPException(status_code=403, detail="sem_permissao")
    if usuario.get("bloqueada_frequency"):
        raise HTTPException(status_code=402, detail="assinatura_frequency_bloqueada")
    return usuario


def somente_dono(usuario=Depends(usuario_atual)):
    if usuario["papel"] != "dono" or usuario["academia_id"] is None:
        raise HTTPException(status_code=403, detail="sem_permissao")
    if usuario.get("bloqueada_frequency"):
        raise HTTPException(status_code=402, detail="assinatura_frequency_bloqueada")
    return usuario
def somente_admin_plataforma(usuario=Depends(usuario_atual)):
    if usuario["papel"] != "admin_plataforma":
        raise HTTPException(status_code=403, detail="sem_permissao")
    return usuario
