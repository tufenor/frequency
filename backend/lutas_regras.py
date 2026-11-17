"""Regras puras do módulo Lutas (sem banco, sem rede). Testadas em tests/test_lutas_regras.py."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ANTES_MIN = 30      # a confirmação abre 30 min antes do início
DEPOIS_MIN = 15     # e fecha 15 min depois
AJUSTE_RETROATIVO_H = 24

ESTADOS = ("confirmada", "validada", "ausente")


def ocorrencia(dia: date, inicio: time, fim: time, fuso: str) -> tuple[datetime, datetime]:
    """Horário de parede da turma (no fuso da academia) → instantes UTC."""
    tz = ZoneInfo(fuso)
    a = datetime.combine(dia, inicio, tzinfo=tz).astimezone(timezone.utc)
    b = datetime.combine(dia, fim, tzinfo=tz).astimezone(timezone.utc)
    return a, b


def janela_confirmacao(inicio: datetime) -> tuple[datetime, datetime]:
    return inicio - timedelta(minutes=ANTES_MIN), inicio + timedelta(minutes=DEPOIS_MIN)


def na_janela(agora: datetime, inicio: datetime) -> bool:
    a, b = janela_confirmacao(inicio)
    return a <= agora <= b


def dia_da_semana(dia: date) -> int:
    """0 = domingo … 6 = sábado (igual ao banco)."""
    return (dia.weekday() + 1) % 7


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def dentro_do_raio(lat: float, lon: float, centro_lat: float, centro_lon: float, raio_m: int) -> bool:
    return haversine_m(lat, lon, centro_lat, centro_lon) <= raio_m


def coordenada_valida(lat, lon) -> bool:
    try:
        return -90 <= float(lat) <= 90 and -180 <= float(lon) <= 180 and not (float(lat) == 0 and float(lon) == 0)
    except (TypeError, ValueError):
        return False


def transicao(atual: str | None, acao: str) -> str:
    """confirmar: nada → confirmada (idempotente). validar/ausentar: só o professor.
    Presença já validada não volta a 'confirmada' por ação do aluno."""
    if acao == "confirmar":
        if atual in ("validada", "ausente"):
            return atual
        return "confirmada"
    if acao == "validar":
        return "validada"
    if acao == "ausentar":
        return "ausente"
    raise ValueError("acao_invalida")


def pode_ajustar(agora: datetime, fim_aula: datetime) -> bool:
    """O professor corrige a chamada até 24 h depois do fim da aula; antes do fim também vale."""
    return agora <= fim_aula + timedelta(hours=AJUSTE_RETROATIVO_H)


def elegivel(modalidades_do_plano: set[int], modalidade_id: int) -> bool:
    return modalidade_id in modalidades_do_plano


def atestado_ok(valido_ate: date | None, hoje: date) -> bool:
    return valido_ate is not None and valido_ate >= hoje


def vagas(capacidade: int, ocupadas: int) -> int:
    return max(0, capacidade - ocupadas)


def progresso_faixa(aulas_validadas: int, faixas: list[dict], faixa_atual_ordem: int | None) -> dict:
    """faixas: [{nome, ordem, aulas_minimas}]. Devolve a faixa atual, a próxima e o quanto falta (aulas desde a graduação
    não são rastreadas aqui: usa o total validado, como o spec define)."""
    ord_ = sorted(faixas, key=lambda f: f["ordem"])
    atual = next((f for f in ord_ if f["ordem"] == faixa_atual_ordem), None)
    prox = next((f for f in ord_ if faixa_atual_ordem is None or f["ordem"] > faixa_atual_ordem), None)
    if prox is None:
        return {"atual": atual and atual["nome"], "proxima": None, "faltam": 0, "percentual": 100}
    meta = max(1, prox["aulas_minimas"])
    base = atual["aulas_minimas"] if atual else 0
    span = max(1, meta - base)
    feito = max(0, aulas_validadas - base)
    return {"atual": atual and atual["nome"], "proxima": prox["nome"],
            "faltam": max(0, meta - aulas_validadas), "percentual": min(100, int(100 * feito / span))}
