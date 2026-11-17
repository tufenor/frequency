"""Cálculos puros da evolução (sem banco). O app tem a mesma lógica em src/evolucao/calculos.ts
e os dois lados rodam os mesmos casos de teste.

Série = dict com: registrada_em (datetime), exercicio_ref, grupo, carga (número), reps (int), concluida (bool).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

PASSO_CARGA = 2.5


def volume(series) -> float:
    """Soma carga × reps das séries concluídas."""
    return round(sum(float(s["carga"]) * int(s["reps"]) for s in series if s.get("concluida", True)), 2)


def recordes(series) -> dict[str, dict]:
    """Maior carga por exercício (empate: mais reps; depois a mais antiga). Ignora séries não concluídas e carga 0."""
    melhores: dict[str, dict] = {}
    for s in sorted(series, key=lambda x: x["registrada_em"]):
        if not s.get("concluida", True) or float(s["carga"]) <= 0 or int(s["reps"]) <= 0:
            continue
        atual = melhores.get(s["exercicio_ref"])
        chave = (float(s["carga"]), int(s["reps"]))
        if atual is None or chave > (atual["carga"], atual["reps"]):
            melhores[s["exercicio_ref"]] = {"exercicio_ref": s["exercicio_ref"], "nome": s.get("exercicio_nome", ""),
                                            "carga": float(s["carga"]), "reps": int(s["reps"]),
                                            "data": s["registrada_em"].date().isoformat()}
    return melhores


def sequencia_semanal(dias: set[date], hoje: date, meta_por_semana: int = 1) -> int:
    """Semanas consecutivas (seg–dom) até a atual com pelo menos `meta_por_semana` dias de treino.
    A semana atual ainda em andamento não quebra a sequência."""
    def inicio(d: date) -> date:
        return d - timedelta(days=d.weekday())
    por_semana: dict[date, int] = {}
    for d in dias:
        por_semana[inicio(d)] = por_semana.get(inicio(d), 0) + 1
    semana = inicio(hoje)
    contador = 0
    if por_semana.get(semana, 0) >= meta_por_semana:
        contador += 1
    semana -= timedelta(days=7)
    while por_semana.get(semana, 0) >= meta_por_semana:
        contador += 1
        semana -= timedelta(days=7)
    return contador


def mapa_do_corpo(series, hoje: datetime, dias: int = 7) -> dict[str, int]:
    """Séries concluídas por grupo muscular nos últimos `dias` dias."""
    corte = hoje - timedelta(days=dias)
    mapa: dict[str, int] = {}
    for s in series:
        if s.get("concluida", True) and s["registrada_em"] > corte:
            mapa[s["grupo"]] = mapa.get(s["grupo"], 0) + 1
    return mapa


def pulso_semanal(series, hoje: date) -> list[int]:
    """Séries concluídas por dia, de segunda a domingo da semana de `hoje` (forma de onda)."""
    segunda = hoje - timedelta(days=hoje.weekday())
    valores = [0] * 7
    for s in series:
        if not s.get("concluida", True):
            continue
        idx = (s["registrada_em"].date() - segunda).days
        if 0 <= idx < 7:
            valores[idx] += 1
    return valores


def sugerir_carga(ultimas, passo: float = PASSO_CARGA) -> dict:
    """Sugestão para a próxima sessão a partir das séries da última sessão do exercício.
    Completou todas as séries planejadas (reps >= meta) → sobe o passo; falhou em alguma → mantém.
    Cada item: {carga, reps, meta_reps (opcional), concluida}. Sem dados → sem sugestão."""
    if not ultimas:
        return {"carga": None, "motivo": "sem_historico"}
    carga = max(float(s["carga"]) for s in ultimas)
    if carga <= 0:
        return {"carga": None, "motivo": "peso_do_corpo"}
    for s in ultimas:
        meta = s.get("meta_reps")
        if not s.get("concluida", True) or (meta is not None and int(s["reps"]) < int(meta)):
            return {"carga": carga, "motivo": "manter"}
    return {"carga": round(carga + passo, 2), "motivo": "subir"}


def resumo_semanal(series, hoje: date) -> dict:
    """Totais da semana (seg–dom) de `hoje` e comparação com a anterior."""
    segunda = hoje - timedelta(days=hoje.weekday())
    anterior = segunda - timedelta(days=7)
    atual = [s for s in series if segunda <= s["registrada_em"].date() < segunda + timedelta(days=7)]
    antes = [s for s in series if anterior <= s["registrada_em"].date() < segunda]
    def dias(lista):
        return len({s["registrada_em"].date() for s in lista if s.get("concluida", True)})
    return {"treinos": dias(atual), "series": sum(1 for s in atual if s.get("concluida", True)),
            "volume": volume(atual), "volume_anterior": volume(antes), "treinos_anterior": dias(antes)}
