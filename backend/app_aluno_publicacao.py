"""Publicação do app do aluno: versao.json + APK (atualizador) e servidor OTA no protocolo de atualizações do Expo.

Os arquivos vêm de pastas montadas no servidor (o Codex publica; o app nunca escreve aqui):
  FREQUENCY_APP_ALUNO_DIR  → versao.json e frequency-<versão>.apk
  FREQUENCY_OTA_DIR        → saída de `expo export` + ota.json {"runtimeVersion": "0.4.0"}
Nada aqui exige login: são arquivos públicos do app. O app confere o SHA-256 do APK antes de instalar.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

router = APIRouter(tags=["app-aluno-publicacao"])

NOME_APK = re.compile(r"^frequency-\d{1,4}\.\d{1,4}\.\d{1,4}\.apk$")
TIPOS = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp", "ttf": "font/ttf",
         "otf": "font/otf", "mp4": "video/mp4", "json": "application/json", "svg": "image/svg+xml", "mp3": "audio/mpeg", "wav": "audio/wav"}


def _pasta(env: str, padrao: str) -> Path:
    return Path(os.getenv(env) or padrao)


def pasta_app_aluno() -> Path:
    return _pasta("FREQUENCY_APP_ALUNO_DIR", str(Path(__file__).resolve().parent.parent / "app-aluno-publicado"))


def pasta_ota() -> Path:
    return _pasta("FREQUENCY_OTA_DIR", str(Path(__file__).resolve().parent.parent / "ota-publicado"))


def pasta_web_aluno() -> Path:
    """Diretório somente leitura do portal web exportado pelo Expo."""
    return _pasta(
        "FREQUENCY_APP_ALUNO_WEB_DIR",
        str(Path(__file__).resolve().parent.parent / "frontend" / "public" / "app-aluno-web"),
    )


def url_publica() -> str:
    return (os.getenv("FREQUENCY_PUBLIC_URL") or "https://frequencygym.tech").rstrip("/")


# --------------------------------------------------------------------------- portal web do aluno

@router.get("/app-aluno", include_in_schema=False)
def redirecionar_portal_aluno():
    return RedirectResponse("/app-aluno/web/", status_code=307)


@router.get("/app-aluno/", include_in_schema=False)
def redirecionar_portal_aluno_com_barra():
    return RedirectResponse("/app-aluno/web/", status_code=307)


@router.get("/app-aluno/web", include_in_schema=False)
def redirecionar_portal_aluno_web():
    return RedirectResponse("/app-aluno/web/", status_code=307)


@router.get("/app-aluno/web/", include_in_schema=False)
def portal_aluno_index():
    arq = pasta_web_aluno() / "index.html"
    if not arq.is_file():
        raise HTTPException(404, "portal_aluno_nao_publicado")
    return FileResponse(arq, media_type="text/html", headers={"Cache-Control": "no-cache"})


@router.get("/app-aluno/web/{caminho:path}", include_in_schema=False)
def portal_aluno_arquivo(caminho: str):
    raiz = pasta_web_aluno().resolve()
    arq = (raiz / caminho).resolve()
    if raiz not in arq.parents or not arq.is_file():
        raise HTTPException(404, "arquivo_nao_encontrado")
    return FileResponse(arq, media_type=mimetypes.guess_type(arq.name)[0] or "application/octet-stream",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


# --------------------------------------------------------------------------- atualizador (APK)

@router.get("/app-aluno/versao.json", include_in_schema=False)
def rota_versao():
    arq = pasta_app_aluno() / "versao.json"
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(404, "versao_nao_publicada")
    if not isinstance(dados, dict) or not {"versao", "versao_minima", "url", "sha256"} <= set(dados):
        raise HTTPException(404, "versao_nao_publicada")
    return JSONResponse(dados, headers={"Cache-Control": "no-cache"})


@router.get("/app-aluno/{nome}", include_in_schema=False)
def rota_apk(nome: str):
    if not NOME_APK.match(nome):
        raise HTTPException(404, "arquivo_nao_encontrado")
    arq = pasta_app_aluno() / nome
    if not arq.is_file():
        raise HTTPException(404, "arquivo_nao_encontrado")
    return FileResponse(arq, media_type="application/vnd.android.package-archive", filename=nome)


# --------------------------------------------------------------------------- OTA (Expo Updates protocol v1)

def _b64url_sha256(dados: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(dados).digest()).decode().rstrip("=")


def _ext(caminho: str) -> str:
    return caminho.rsplit(".", 1)[-1].lower() if "." in caminho.rsplit("/", 1)[-1] else ""


def carregar_pacote(pasta: Path, plataforma: str) -> dict | None:
    """Lê a saída de `expo export` e devolve {runtime, bundle, assets, arquivos{chave: Path}} ou None."""
    try:
        meta = json.loads((pasta / "metadata.json").read_text(encoding="utf-8"))
        ota = json.loads((pasta / "ota.json").read_text(encoding="utf-8"))
        info = meta["fileMetadata"][plataforma]
    except (OSError, ValueError, KeyError):
        return None
    raiz = pasta.resolve()
    arquivos: dict[str, Path] = {}

    def registrar(rel: str) -> tuple[str, str] | None:
        # O `expo export` executado no Windows registra separadores `\\` no
        # metadata.json. O pacote pode ser servido no Linux, então normalize o
        # caminho antes de resolvê-lo, sem permitir sair da pasta publicada.
        rel = rel.replace("\\\\", "/")
        p = (pasta / rel).resolve()
        if raiz not in p.parents or not p.is_file():  # nunca sai da pasta do pacote
            return None
        dados = p.read_bytes()
        chave = hashlib.md5(dados).hexdigest()
        arquivos[chave] = p
        return chave, _b64url_sha256(dados)

    lancamento = registrar(info["bundle"])
    if lancamento is None:
        return None
    assets = []
    for a in info.get("assets", []):
        r = registrar(a["path"])
        if r:
            assets.append({"chave": r[0], "hash": r[1], "ext": a.get("ext") or _ext(a["path"])})
    return {"runtime": str(ota.get("runtimeVersion", "")), "bundle": {"chave": lancamento[0], "hash": lancamento[1]},
            "assets": assets, "arquivos": arquivos, "criado_em": ota.get("createdAt")}


def montar_manifesto(pacote: dict, plataforma: str, base: str) -> dict:
    def url(chave: str) -> str:
        return f"{base}/ota/assets/{chave}?platform={plataforma}"
    b = pacote["bundle"]
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"frequency-ota:{pacote['runtime']}:{b['hash']}")),
        "createdAt": pacote.get("criado_em") or datetime.now(timezone.utc).isoformat(),
        "runtimeVersion": pacote["runtime"],
        "launchAsset": {"hash": b["hash"], "key": b["chave"], "contentType": "application/javascript", "fileExtension": ".bundle", "url": url(b["chave"])},
        "assets": [{"hash": a["hash"], "key": a["chave"], "contentType": TIPOS.get(a["ext"], "application/octet-stream"),
                    "fileExtension": f".{a['ext']}" if a["ext"] else "", "url": url(a["chave"])} for a in pacote["assets"]],
        "metadata": {},
        "extra": {},
    }


def _multipart(nome: str, corpo: dict) -> Response:
    limite = uuid.uuid4().hex
    texto = (f"--{limite}\r\nContent-Disposition: form-data; name=\"{nome}\"\r\nContent-Type: application/json\r\n\r\n"
             f"{json.dumps(corpo, separators=(',', ':'))}\r\n--{limite}--\r\n")
    return Response(texto, media_type=f"multipart/mixed; boundary={limite}",
                    headers={"expo-protocol-version": "1", "expo-sfv-version": "0", "cache-control": "private, max-age=0"})


@router.get("/ota/manifest", include_in_schema=False)
def rota_manifesto(request: Request):
    plataforma = (request.headers.get("expo-platform") or "").lower()
    if plataforma not in {"android", "ios"}:
        raise HTTPException(400, "plataforma_invalida")
    runtime = request.headers.get("expo-runtime-version") or ""
    atual = request.headers.get("expo-current-update-id") or ""
    pacote = carregar_pacote(pasta_ota(), plataforma)
    if pacote is None or pacote["runtime"] != runtime:
        return _multipart("directive", {"type": "noUpdateAvailable"})
    manifesto = montar_manifesto(pacote, plataforma, url_publica())
    if manifesto["id"] == atual:
        return _multipart("directive", {"type": "noUpdateAvailable"})
    return _multipart("manifest", manifesto)


@router.get("/ota/assets/{chave}", include_in_schema=False)
def rota_asset(chave: str, platform: str = "android"):
    if not re.fullmatch(r"[0-9a-f]{32}", chave) or platform not in {"android", "ios"}:
        raise HTTPException(404, "arquivo_nao_encontrado")
    pacote = carregar_pacote(pasta_ota(), platform)
    arq = pacote["arquivos"].get(chave) if pacote else None
    if arq is None:
        raise HTTPException(404, "arquivo_nao_encontrado")
    tipo = "application/javascript" if chave == pacote["bundle"]["chave"] else (mimetypes.guess_type(arq.name)[0] or TIPOS.get(_ext(arq.name), "application/octet-stream"))
    return FileResponse(arq, media_type=tipo, headers={"Cache-Control": "public, max-age=31536000, immutable"})
