"""Gerador de treino por regras (objetivo, nível, dias por semana, aparelhos disponíveis). Puro: sem banco.

Devolve treinos no mesmo formato de TreinoEntrada (blocos/itens com `ref` do catálogo efetivo), prontos para
o aluno revisar e salvar. Determinístico: o mesmo pedido gera o mesmo treino; `variacao` troca os exercícios.
"""

from __future__ import annotations

OBJETIVOS = ("hipertrofia", "forca", "emagrecimento", "condicionamento")
NIVEIS = ("Iniciante", "Intermediário", "Avançado")
_ORDEM_NIVEL = {n: i for i, n in enumerate(NIVEIS)}

EMPURRAR = ["peito", "ombros", "triceps"]
PUXAR = ["costas", "biceps", "antebraco"]
PERNAS = ["quadriceps", "posteriores", "gluteos", "panturrilhas"]

# dias → lista de (letra, nome, grupos)
DIVISOES: dict[int, list[tuple[str, str, list[str]]]] = {
    2: [("A", "Corpo todo A", ["peito", "costas", "quadriceps", "ombros", "abdomen"]),
        ("B", "Corpo todo B", ["costas", "peito", "posteriores", "gluteos", "biceps", "triceps"])],
    3: [("A", "Empurrar", EMPURRAR), ("B", "Puxar", PUXAR + ["abdomen"]), ("C", "Pernas", PERNAS)],
    4: [("A", "Superiores A", ["peito", "costas", "ombros", "triceps"]), ("B", "Inferiores A", ["quadriceps", "posteriores", "panturrilhas", "abdomen"]),
        ("C", "Superiores B", ["costas", "peito", "ombros", "biceps"]), ("D", "Inferiores B", ["gluteos", "quadriceps", "posteriores", "lombar"])],
    5: [("A", "Peito e tríceps", ["peito", "triceps"]), ("B", "Costas e bíceps", ["costas", "biceps", "antebraco"]), ("C", "Pernas", PERNAS),
        ("D", "Ombros e abdômen", ["ombros", "abdomen", "lombar"]), ("E", "Corpo todo", ["peito", "costas", "quadriceps", "gluteos"])],
    6: [("A", "Empurrar A", EMPURRAR), ("B", "Puxar A", PUXAR), ("C", "Pernas A", PERNAS),
        ("D", "Empurrar B", EMPURRAR), ("E", "Puxar B", PUXAR + ["abdomen"]), ("F", "Pernas B", PERNAS)],
}
DIAS_SUGERIDOS = {2: [1, 4], 3: [1, 3, 5], 4: [1, 2, 4, 5], 5: [1, 2, 3, 4, 5], 6: [1, 2, 3, 4, 5, 6]}
PEQUENOS = {"biceps", "triceps", "antebraco", "panturrilhas", "abdomen", "lombar"}
NOME_GRUPO = {"peito": "Peito", "costas": "Costas", "ombros": "Ombros", "biceps": "Bíceps", "triceps": "Tríceps", "antebraco": "Antebraço",
              "abdomen": "Abdômen", "lombar": "Lombar", "quadriceps": "Quadríceps", "posteriores": "Posteriores", "gluteos": "Glúteos", "panturrilhas": "Panturrilhas"}
# compostos primeiro: barra e máquina/polia antes de halteres e peso do corpo
_PRIORIDADE_EQUIP = {"Barra": 0, "Máquina": 1, "Polia": 2, "Halteres": 3, "Peso do corpo": 4}

PARAMETROS = {
    "hipertrofia": {"series": 3, "series_nivel": {"Intermediário": 4, "Avançado": 4}, "reps": "8-12", "descanso": 75, "cardio": 0},
    "forca": {"series": 4, "series_nivel": {"Avançado": 5}, "reps": "4-6", "descanso": 120, "cardio": 0},
    "emagrecimento": {"series": 3, "series_nivel": {}, "reps": "12-15", "descanso": 45, "cardio": 20},
    "condicionamento": {"series": 3, "series_nivel": {}, "reps": "15", "descanso": 30, "cardio": 15},
}


class PedidoInvalido(ValueError):
    pass


def _por_exercicio(ex: dict, nivel: str, variacao: int) -> tuple:
    mais_alto = _ORDEM_NIVEL.get(ex.get("nivel") or "Iniciante", 0) > _ORDEM_NIVEL[nivel]
    # nível igual ao do aluno vem antes do mais fácil; `variacao` gira a lista dentro do mesmo grau de prioridade
    return (mais_alto, _PRIORIDADE_EQUIP.get(ex["equipamento"], 5), -_ORDEM_NIVEL.get(ex.get("nivel") or "Iniciante", 0), ex["nome"])


def _escolher(catalogo: list[dict], grupo: str, quantidade: int, nivel: str, indisponiveis: set[str], variacao: int) -> list[dict]:
    teto = _ORDEM_NIVEL[nivel]
    cand = [e for e in catalogo if e["grupo"] == grupo and e["equipamento"] not in indisponiveis
            and _ORDEM_NIVEL.get(e.get("nivel") or "Iniciante", 0) <= teto]
    cand.sort(key=lambda e: _por_exercicio(e, nivel, variacao))
    if not cand:
        return []
    # mantém o primeiro (composto principal) e gira os demais conforme a variação
    if variacao and len(cand) > quantidade:
        resto = cand[1:]
        k = variacao % len(resto)
        cand = [cand[0]] + resto[k:] + resto[:k]
    return cand[:quantidade]


def gerar(catalogo: list[dict], objetivo: str, nivel: str, dias: int, indisponiveis: set[str] | None = None, variacao: int = 0) -> dict:
    if objetivo not in OBJETIVOS:
        raise PedidoInvalido("objetivo_invalido")
    if nivel not in NIVEIS:
        raise PedidoInvalido("nivel_invalido")
    if dias not in DIVISOES:
        raise PedidoInvalido("dias_invalidos")
    indisponiveis = indisponiveis or set()
    p = PARAMETROS[objetivo]
    series = p["series_nivel"].get(nivel, p["series"])
    treinos, avisos = [], []
    for ordem, (letra, nome, grupos) in enumerate(DIVISOES[dias]):
        blocos = [{"grupo": "aquecimento", "nome": "Aquecimento",
                   "itens": [{"nome_livre": "Aquecimento geral (esteira, bicicleta ou remo)", "series": 1, "reps": "300", "tempo": True, "descanso_s": 0}]}]
        for g in grupos:
            qtd = 2 if g in PEQUENOS or nivel == "Iniciante" else 3
            if len(grupos) <= 2:
                qtd += 1
            escolhidos = _escolher(catalogo, g, qtd, nivel, indisponiveis, variacao + ordem)
            if not escolhidos:
                avisos.append(f"Sem exercícios disponíveis para {NOME_GRUPO.get(g, g)} com os aparelhos desta academia.")
                continue
            itens = [{"ref": e["ref"], "series": min(series, 6) if not e["tempo"] else 3,
                      "reps": ("30-45" if e["tempo"] else p["reps"]), "tempo": bool(e["tempo"]), "descanso_s": p["descanso"]} for e in escolhidos]
            blocos.append({"grupo": g, "nome": NOME_GRUPO.get(g, g), "itens": itens})
        if p["cardio"]:
            blocos.append({"grupo": "cardio", "nome": "Cardio final",
                           "itens": [{"nome_livre": f"Cardio contínuo em ritmo moderado ({p['cardio']} min)", "series": 1, "reps": str(p["cardio"] * 60), "tempo": True, "descanso_s": 0}]})
        treinos.append({"nome": nome, "letra": letra, "dias_semana": [DIAS_SUGERIDOS[dias][ordem]], "blocos": blocos})
    return {"treinos": treinos, "avisos": sorted(set(avisos)), "objetivo": objetivo, "nivel": nivel, "dias": dias}
