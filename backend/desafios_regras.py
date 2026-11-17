"""Regras puras dos desafios e do ranking (sem banco)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

MIN_SERIES_POR_DIA = 3          # um dia só conta como treino com pelo menos 3 séries concluídas
TETO_VOLUME_SERIE = 10_000.0    # kg·reps por série; trava valores absurdos
TETO_SERIES_POR_DIA = 150


def _dia_local(instante: datetime, fuso: str) -> date:
    return instante.astimezone(ZoneInfo(fuso)).date()


def pontuar(series: list[dict], metrica: str, inicio: date, fim: date, entrou_em: datetime, fuso: str) -> float:
    """series: [{registrada_em: datetime, carga, reps, concluida}]. Conta só do maior entre início e entrada, até o fim."""
    de = max(inicio, _dia_local(entrou_em, fuso))
    por_dia: dict[date, list[dict]] = {}
    for s in series:
        if not s["concluida"]:
            continue
        d = _dia_local(s["registrada_em"], fuso)
        if de <= d <= fim:
            por_dia.setdefault(d, []).append(s)
    if metrica == "treinos":
        return float(sum(1 for v in por_dia.values() if len(v) >= MIN_SERIES_POR_DIA))
    total = 0.0
    for v in por_dia.values():
        for s in v[:TETO_SERIES_POR_DIA]:
            total += min(float(s["carga"]) * float(s["reps"]), TETO_VOLUME_SERIE)
    return round(total, 1)


def nome_publico(nome: str) -> str:
    """'Ana Souza Lima' → 'Ana L.' (o ranking nunca mostra sobrenome completo)."""
    p = nome.strip().split()
    if not p:
        return "Aluno"
    return p[0] if len(p) == 1 else f"{p[0]} {p[-1][0].upper()}."


def classificar(participantes: list[dict]) -> list[dict]:
    """participantes: [{aluno_id, nome, valor}]. Empate divide a posição (1,1,3); quem tem valor 0 fica sem posição."""
    ordem = sorted(participantes, key=lambda p: (-p["valor"], p["nome"].lower(), p["aluno_id"]))
    out, pos, anterior = [], 0, None
    for i, p in enumerate(ordem, start=1):
        if p["valor"] <= 0:
            out.append({**p, "posicao": None})
            continue
        if p["valor"] != anterior:
            pos, anterior = i, p["valor"]
        out.append({**p, "posicao": pos})
    return out


def situacao_do_desafio(inicio: date, fim: date, ativo: bool, hoje: date) -> str:
    if not ativo:
        return "encerrado"
    if hoje < inicio:
        return "em_breve"
    return "em_andamento" if hoje <= fim else "encerrado"
