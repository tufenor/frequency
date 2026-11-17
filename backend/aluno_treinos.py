"""Treinos editáveis do aluno (dia → blocos → itens), catálogo efetivo e exercícios próprios.

Regra do catálogo: global − ocultos pela academia + exercícios da academia + os do próprio aluno.
Um exercício ocultado depois de entrar num treino continua nele (marcado `removido_pela_academia`).
Tudo é isolado por `aluno_id` / `academia_id`; nada aqui escreve em log.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import aluno_auth

GRUPOS = ("peito", "costas", "ombros", "biceps", "triceps", "antebraco", "abdomen", "lombar",
          "quadriceps", "posteriores", "gluteos", "panturrilhas")
GRUPOS_LIVRES = ("aquecimento", "cardio", "alongamento")
MAX_TREINOS = 30
MAX_BLOCOS = 12
MAX_ITENS = 30

router = APIRouter(prefix="/aluno", tags=["aluno-treinos"])


# --------------------------------------------------------------------------- modelos de entrada

class ItemEntrada(BaseModel):
    id: int | None = None
    ref: str | None = Field(default=None, pattern=r"^[cx]:[A-Za-z0-9_]{1,80}$")
    nome_livre: str | None = Field(default=None, min_length=1, max_length=120)
    series: int = Field(default=3, ge=1, le=30)
    reps: str = Field(default="10", min_length=1, max_length=20)
    tempo: bool = False
    carga: float | None = Field(default=None, ge=0, le=1000)
    descanso_s: int = Field(default=60, ge=0, le=900)
    observacao: str | None = Field(default=None, max_length=500)


class BlocoEntrada(BaseModel):
    id: int | None = None
    grupo: str
    nome: str = Field(min_length=1, max_length=80)
    itens: list[ItemEntrada] = Field(default_factory=list, max_length=MAX_ITENS)


class TreinoEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    letra: str | None = Field(default=None, min_length=1, max_length=3)
    dias_semana: list[int] = Field(default_factory=list, max_length=7)
    blocos: list[BlocoEntrada] = Field(default_factory=list, max_length=MAX_BLOCOS)
    versao: int | None = None
    modelo_id: int | None = None


class ExercicioPropriaEntrada(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    grupo: str
    equipamento: str = Field(default="", max_length=80)
    tempo: bool = False


class MoverBlocoEntrada(BaseModel):
    treino_id: int


class OrdemEntrada(BaseModel):
    ids: list[int] = Field(max_length=MAX_TREINOS)


def _erro(status: int, codigo: str) -> HTTPException:
    return HTTPException(status, codigo)


def _validar_dias(dias: list[int]) -> list[int]:
    if len(set(dias)) != len(dias) or any(d < 0 or d > 6 for d in dias):
        raise _erro(422, "dias_semana_invalidos")
    return sorted(dias)


def _validar_grupo(grupo: str, permitir_livre: bool = True) -> None:
    if grupo not in GRUPOS and not (permitir_livre and grupo in GRUPOS_LIVRES):
        raise _erro(422, "grupo_invalido")


# --------------------------------------------------------------------------- catálogo

def _reps_numero(valor) -> str:
    return str(valor)


def catalogo_efetivo(conn, academia_id: int, aluno_id: int) -> list[dict]:
    itens: list[dict] = []
    for l in conn.execute(
        "SELECT c.id, c.nome, c.grupo, c.equipamento, c.nivel, c.series_sugeridas, c.reps_sugeridas, "
        "       c.tempo, c.descanso_s, c.foto_chave "
        "FROM public.exercicios_catalogo c "
        "WHERE c.ativo AND NOT EXISTS (SELECT 1 FROM public.academia_exercicios_visibilidade v "
        "      WHERE v.academia_id = %s AND v.exercicio_id = c.id AND v.oculto) "
        "ORDER BY c.grupo, c.nivel, c.nome", (academia_id,)).fetchall():
        itens.append({"ref": "c:" + l["id"], "origem": "catalogo", "nome": l["nome"], "grupo": l["grupo"],
                      "equipamento": l["equipamento"], "nivel": l["nivel"], "series": l["series_sugeridas"],
                      "reps": l["reps_sugeridas"], "tempo": l["tempo"], "descanso_s": l["descanso_s"],
                      "foto_chave": l["foto_chave"]})
    for l in conn.execute(
        "SELECT id, escopo, nome, grupo, equipamento, tempo FROM public.exercicios_custom "
        "WHERE ativo AND academia_id = %s AND (escopo = 'academia' OR (escopo = 'aluno' AND aluno_id = %s)) "
        "ORDER BY grupo, nome", (academia_id, aluno_id)).fetchall():
        itens.append({"ref": f"x:{l['id']}", "origem": l["escopo"], "nome": l["nome"], "grupo": l["grupo"],
                      "equipamento": l["equipamento"], "nivel": None, "series": 3,
                      "reps": "30-45" if l["tempo"] else "10-12", "tempo": l["tempo"], "descanso_s": 60,
                      "foto_chave": None})
    return itens


def _refs_validas(conn, aluno: dict) -> set[str]:
    return {i["ref"] for i in catalogo_efetivo(conn, aluno["academia_id"], aluno["id"])}


# --------------------------------------------------------------------------- leitura de treinos

def _num(v):
    return float(v) if isinstance(v, Decimal) else v


def _montar(conn, aluno: dict, linhas_treino: list[dict]) -> list[dict]:
    if not linhas_treino:
        return []
    ids = [t["id"] for t in linhas_treino]
    blocos = conn.execute(
        "SELECT id, treino_id, grupo, nome, ordem, concluido_em FROM public.treino_blocos "
        "WHERE treino_id = ANY(%s) ORDER BY treino_id, ordem, id", (ids,)).fetchall()
    bids = [b["id"] for b in blocos]
    itens = conn.execute(
        "SELECT i.id, i.bloco_id, i.catalogo_id, i.custom_id, i.nome_livre, i.series, i.reps, i.tempo, i.carga, "
        "       i.descanso_s, i.observacao, i.ordem, c.nome AS cat_nome, c.grupo AS cat_grupo, "
        "       x.nome AS custom_nome, x.grupo AS custom_grupo, x.ativo AS custom_ativo, "
        "       COALESCE(v.oculto, FALSE) AS oculto "
        "FROM public.treino_itens i "
        "LEFT JOIN public.exercicios_catalogo c ON c.id = i.catalogo_id "
        "LEFT JOIN public.exercicios_custom x ON x.id = i.custom_id "
        "LEFT JOIN public.academia_exercicios_visibilidade v "
        "       ON v.exercicio_id = i.catalogo_id AND v.academia_id = %s "
        "WHERE i.bloco_id = ANY(%s) ORDER BY i.bloco_id, i.ordem, i.id", (aluno["academia_id"], bids)).fetchall()
    por_bloco: dict[int, list[dict]] = {}
    for i in itens:
        if i["catalogo_id"]:
            ref, nome, grupo = "c:" + i["catalogo_id"], i["cat_nome"], i["cat_grupo"]
            removido = bool(i["oculto"])
        elif i["custom_id"]:
            ref, nome, grupo = f"x:{i['custom_id']}", i["custom_nome"], i["custom_grupo"]
            removido = not i["custom_ativo"]
        else:
            ref, nome, grupo, removido = None, i["nome_livre"], None, False
        por_bloco.setdefault(i["bloco_id"], []).append({
            "id": i["id"], "ref": ref, "nome": nome, "grupo": grupo, "nome_livre": i["nome_livre"],
            "series": i["series"], "reps": i["reps"], "tempo": i["tempo"], "carga": _num(i["carga"]),
            "descanso_s": i["descanso_s"], "observacao": i["observacao"], "ordem": i["ordem"],
            "removido_pela_academia": removido})
    blocos_do_treino: dict[int, list[dict]] = {}
    for b in blocos:
        blocos_do_treino.setdefault(b["treino_id"], []).append({
            "id": b["id"], "grupo": b["grupo"], "nome": b["nome"], "ordem": b["ordem"],
            "concluido_em": b["concluido_em"].isoformat() if b["concluido_em"] else None,
            "itens": por_bloco.get(b["id"], [])})
    return [{"id": t["id"], "nome": t["nome"], "letra": t["letra"], "dias_semana": list(t["dias_semana"]),
             "ordem": t["ordem"], "versao": t["versao"], "modelo_origem_id": t["modelo_origem_id"],
             "blocos": blocos_do_treino.get(t["id"], [])} for t in linhas_treino]


def listar_treinos(conn, aluno: dict) -> list[dict]:
    linhas = conn.execute(
        "SELECT id, nome, letra, dias_semana, ordem, versao, modelo_origem_id FROM public.treinos "
        "WHERE aluno_id = %s ORDER BY ordem, id", (aluno["id"],)).fetchall()
    return _montar(conn, aluno, linhas)


def _treino_do_aluno(conn, aluno: dict, treino_id: int, travar: bool = False) -> dict:
    sufixo = " FOR UPDATE" if travar else ""
    linha = conn.execute(
        "SELECT id, nome, letra, dias_semana, ordem, versao, modelo_origem_id FROM public.treinos "
        "WHERE id = %s AND aluno_id = %s" + sufixo, (treino_id, aluno["id"])).fetchone()
    if linha is None:
        raise _erro(404, "treino_nao_encontrado")
    return linha


def obter_treino(conn, aluno: dict, treino_id: int) -> dict:
    return _montar(conn, aluno, [_treino_do_aluno(conn, aluno, treino_id)])[0]


# --------------------------------------------------------------------------- escrita

def _resolver_item(item: ItemEntrada, validas: set[str], ja_no_treino: set[str], aluno: dict, conn) -> tuple:
    """Devolve (catalogo_id, custom_id, nome_livre) ou lança 422."""
    if item.ref and item.nome_livre:
        raise _erro(422, "item_ambiguo")
    if item.nome_livre:
        return None, None, item.nome_livre.strip()
    if not item.ref:
        raise _erro(422, "item_sem_exercicio")
    if item.ref not in validas and item.ref not in ja_no_treino:
        raise _erro(422, "exercicio_indisponivel")
    tipo, _, chave = item.ref.partition(":")
    if tipo == "c":
        return chave, None, None
    return None, int(chave), None


def _refs_do_treino(conn, treino_id: int) -> set[str]:
    refs = set()
    for l in conn.execute(
        "SELECT i.catalogo_id, i.custom_id FROM public.treino_itens i "
        "JOIN public.treino_blocos b ON b.id = i.bloco_id WHERE b.treino_id = %s", (treino_id,)).fetchall():
        refs.add("c:" + l["catalogo_id"] if l["catalogo_id"] else f"x:{l['custom_id']}")
    return refs


def _gravar_blocos(conn, aluno: dict, treino_id: int, blocos: list[BlocoEntrada]) -> None:
    validas = _refs_validas(conn, aluno)
    ja = _refs_do_treino(conn, treino_id)
    existentes = {b["id"] for b in conn.execute(
        "SELECT id FROM public.treino_blocos WHERE treino_id = %s", (treino_id,)).fetchall()}
    mantidos = {b.id for b in blocos if b.id is not None}
    if not mantidos <= existentes:
        raise _erro(422, "bloco_invalido")
    conn.execute("DELETE FROM public.treino_blocos WHERE treino_id = %s AND id <> ALL(%s)",
                 (treino_id, list(mantidos) or [0]))
    for ordem, b in enumerate(blocos):
        _validar_grupo(b.grupo)
        if b.id is None:
            bid = conn.execute(
                "INSERT INTO public.treino_blocos (treino_id, grupo, nome, ordem) VALUES (%s,%s,%s,%s) RETURNING id",
                (treino_id, b.grupo, b.nome.strip(), ordem)).fetchone()["id"]
            itens_existentes: set[int] = set()
        else:
            bid = b.id
            conn.execute("UPDATE public.treino_blocos SET grupo = %s, nome = %s, ordem = %s WHERE id = %s",
                         (b.grupo, b.nome.strip(), ordem, bid))
            itens_existentes = {i["id"] for i in conn.execute(
                "SELECT id FROM public.treino_itens WHERE bloco_id = %s", (bid,)).fetchall()}
        manter_itens = {i.id for i in b.itens if i.id is not None}
        if not manter_itens <= itens_existentes:
            raise _erro(422, "item_invalido")
        conn.execute("DELETE FROM public.treino_itens WHERE bloco_id = %s AND id <> ALL(%s)",
                     (bid, list(manter_itens) or [0]))
        for pos, item in enumerate(b.itens):
            cat, cus, livre = _resolver_item(item, validas, ja, aluno, conn)
            if cus is not None:
                dono = conn.execute(
                    "SELECT 1 FROM public.exercicios_custom WHERE id = %s AND academia_id = %s "
                    "AND (escopo = 'academia' OR aluno_id = %s)", (cus, aluno["academia_id"], aluno["id"])).fetchone()
                if dono is None:
                    raise _erro(422, "exercicio_indisponivel")
            valores = (cat, cus, livre, item.series, item.reps.strip(), item.tempo, item.carga,
                       item.descanso_s, (item.observacao or "").strip() or None, pos)
            if item.id is None:
                conn.execute(
                    "INSERT INTO public.treino_itens (bloco_id, catalogo_id, custom_id, nome_livre, series, reps, "
                    "tempo, carga, descanso_s, observacao, ordem) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (bid,) + valores)
            else:
                conn.execute(
                    "UPDATE public.treino_itens SET catalogo_id=%s, custom_id=%s, nome_livre=%s, series=%s, reps=%s, "
                    "tempo=%s, carga=%s, descanso_s=%s, observacao=%s, ordem=%s WHERE id=%s",
                    valores + (item.id,))


def _contar(conn, aluno: dict) -> int:
    return conn.execute("SELECT count(*) AS n FROM public.treinos WHERE aluno_id = %s", (aluno["id"],)).fetchone()["n"]


def criar_treino(conn, aluno: dict, dados: TreinoEntrada, modelo_origem_id: int | None = None) -> dict:
    if _contar(conn, aluno) >= MAX_TREINOS:
        raise _erro(422, "limite_de_treinos")
    dias = _validar_dias(dados.dias_semana)
    ordem = conn.execute("SELECT COALESCE(max(ordem) + 1, 0) AS o FROM public.treinos WHERE aluno_id = %s",
                         (aluno["id"],)).fetchone()["o"]
    tid = conn.execute(
        "INSERT INTO public.treinos (aluno_id, nome, letra, dias_semana, ordem, modelo_origem_id) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (aluno["id"], dados.nome.strip(), (dados.letra or "").strip() or None, dias, ordem, modelo_origem_id)
    ).fetchone()["id"]
    _gravar_blocos(conn, aluno, tid, dados.blocos)
    conn.commit()
    return obter_treino(conn, aluno, tid)


def gravar_treino(conn, aluno: dict, treino_id: int, dados: TreinoEntrada) -> dict:
    atual = _treino_do_aluno(conn, aluno, treino_id, travar=True)
    if dados.versao is None or dados.versao != atual["versao"]:
        conn.rollback()
        raise _erro(409, "versao_desatualizada")
    dias = _validar_dias(dados.dias_semana)
    conn.execute(
        "UPDATE public.treinos SET nome = %s, letra = %s, dias_semana = %s, versao = versao + 1, "
        "atualizado_em = CURRENT_TIMESTAMP WHERE id = %s",
        (dados.nome.strip(), (dados.letra or "").strip() or None, dias, treino_id))
    try:
        _gravar_blocos(conn, aluno, treino_id, dados.blocos)
    except HTTPException:
        conn.rollback()
        raise
    conn.commit()
    return obter_treino(conn, aluno, treino_id)


def apagar_treino(conn, aluno: dict, treino_id: int) -> None:
    _treino_do_aluno(conn, aluno, treino_id)
    conn.execute("DELETE FROM public.treinos WHERE id = %s AND aluno_id = %s", (treino_id, aluno["id"]))
    conn.commit()


def duplicar_treino(conn, aluno: dict, treino_id: int) -> dict:
    if _contar(conn, aluno) >= MAX_TREINOS:
        raise _erro(422, "limite_de_treinos")
    origem = obter_treino(conn, aluno, treino_id)
    entrada = TreinoEntrada(
        nome=(origem["nome"] + " (cópia)")[:80], letra=None, dias_semana=[],
        blocos=[BlocoEntrada(grupo=b["grupo"], nome=b["nome"], itens=[
            ItemEntrada(ref=i["ref"], nome_livre=i["nome_livre"], series=i["series"], reps=i["reps"], tempo=i["tempo"],
                        carga=i["carga"], descanso_s=i["descanso_s"], observacao=i["observacao"])
            for i in b["itens"]]) for b in origem["blocos"]])
    return criar_treino(conn, aluno, entrada, modelo_origem_id=origem["modelo_origem_id"])


def mover_bloco(conn, aluno: dict, bloco_id: int, destino_id: int) -> dict:
    bloco = conn.execute(
        "SELECT b.id, b.treino_id FROM public.treino_blocos b JOIN public.treinos t ON t.id = b.treino_id "
        "WHERE b.id = %s AND t.aluno_id = %s", (bloco_id, aluno["id"])).fetchone()
    if bloco is None:
        raise _erro(404, "bloco_nao_encontrado")
    _treino_do_aluno(conn, aluno, destino_id)
    qtd = conn.execute("SELECT count(*) AS n FROM public.treino_blocos WHERE treino_id = %s", (destino_id,)).fetchone()["n"]
    if bloco["treino_id"] != destino_id and qtd >= MAX_BLOCOS:
        raise _erro(422, "limite_de_blocos")
    conn.execute(
        "UPDATE public.treino_blocos SET treino_id = %s, "
        "ordem = (SELECT COALESCE(max(ordem) + 1, 0) FROM public.treino_blocos WHERE treino_id = %s) WHERE id = %s",
        (destino_id, destino_id, bloco_id))
    conn.execute("UPDATE public.treinos SET versao = versao + 1, atualizado_em = CURRENT_TIMESTAMP WHERE id = ANY(%s)",
                 ([bloco["treino_id"], destino_id],))
    conn.commit()
    return obter_treino(conn, aluno, destino_id)


def reordenar_treinos(conn, aluno: dict, ids: list[int]) -> list[dict]:
    meus = {t["id"] for t in conn.execute("SELECT id FROM public.treinos WHERE aluno_id = %s", (aluno["id"],)).fetchall()}
    if set(ids) != meus or len(set(ids)) != len(ids):
        raise _erro(422, "ordem_invalida")
    for pos, tid in enumerate(ids):
        conn.execute("UPDATE public.treinos SET ordem = %s WHERE id = %s AND aluno_id = %s", (pos, tid, aluno["id"]))
    conn.commit()
    return listar_treinos(conn, aluno)


# --------------------------------------------------------------------------- modelos

def listar_modelos(conn) -> list[dict]:
    return [{"id": m["id"], "nome": m["nome"], "descricao": m["descricao"], "nivel": m["nivel"], "dias": m["dias"]}
            for m in conn.execute("SELECT id, nome, descricao, nivel, dias FROM public.treinos_modelo ORDER BY ordem").fetchall()]


def copiar_modelo(conn, aluno: dict, modelo_id: int) -> list[dict]:
    modelo = conn.execute("SELECT id, nome, conteudo FROM public.treinos_modelo WHERE id = %s", (modelo_id,)).fetchone()
    if modelo is None:
        raise _erro(404, "modelo_nao_encontrado")
    dias = modelo["conteudo"]["dias"]
    if _contar(conn, aluno) + len(dias) > MAX_TREINOS:
        raise _erro(422, "limite_de_treinos")
    nomes_grupo = {"aquecimento": "Aquecimento", "cardio": "Cardio", "alongamento": "Alongamento"}
    nomes_grupo.update({g: g.capitalize() for g in GRUPOS})
    nomes_grupo.update({"biceps": "Bíceps", "triceps": "Tríceps", "abdomen": "Abdômen", "quadriceps": "Quadríceps",
                        "gluteos": "Glúteos", "antebraco": "Antebraço"})
    criados = []
    for d in dias:
        blocos = []
        for b in d["blocos"]:
            itens = [ItemEntrada(ref="c:" + e) for e in b.get("exercicios", [])]
            itens += [ItemEntrada(nome_livre=l["nome"], tempo=l.get("tempo", False), reps=str(l.get("reps", "10")),
                                  series=l.get("series", 1)) for l in b.get("livres", [])]
            blocos.append(BlocoEntrada(grupo=b["grupo"], nome=nomes_grupo.get(b["grupo"], b["grupo"]), itens=itens))
        criados.append(criar_treino(conn, aluno, TreinoEntrada(nome=d["nome"], blocos=blocos), modelo_origem_id=modelo_id))
    return criados


# --------------------------------------------------------------------------- exercícios do aluno

def criar_exercicio_aluno(conn, aluno: dict, dados: ExercicioPropriaEntrada) -> dict:
    _validar_grupo(dados.grupo, permitir_livre=False)
    total = conn.execute("SELECT count(*) AS n FROM public.exercicios_custom WHERE aluno_id = %s AND ativo",
                         (aluno["id"],)).fetchone()["n"]
    if total >= 100:
        raise _erro(422, "limite_de_exercicios")
    nova = conn.execute(
        "INSERT INTO public.exercicios_custom (escopo, academia_id, aluno_id, nome, grupo, equipamento, tempo) "
        "VALUES ('aluno', %s, %s, %s, %s, %s, %s) RETURNING id",
        (aluno["academia_id"], aluno["id"], dados.nome.strip(), dados.grupo, dados.equipamento.strip(), dados.tempo)
    ).fetchone()["id"]
    conn.commit()
    return next(i for i in catalogo_efetivo(conn, aluno["academia_id"], aluno["id"]) if i["ref"] == f"x:{nova}")


def apagar_exercicio_aluno(conn, aluno: dict, exercicio_id: int) -> None:
    n = conn.execute(
        "UPDATE public.exercicios_custom SET ativo = FALSE WHERE id = %s AND aluno_id = %s AND escopo = 'aluno' AND ativo",
        (exercicio_id, aluno["id"])).rowcount
    if n == 0:
        raise _erro(404, "exercicio_nao_encontrado")
    conn.commit()


# --------------------------------------------------------------------------- rotas

@router.get("/catalogo")
def rota_catalogo(aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return {"grupos": list(GRUPOS), "grupos_livres": list(GRUPOS_LIVRES),
            "exercicios": catalogo_efetivo(conn, aluno["academia_id"], aluno["id"])}


@router.post("/exercicios", status_code=201)
def rota_criar_exercicio(dados: ExercicioPropriaEntrada, aluno: dict = Depends(aluno_auth.aluno_atual),
                         conn=Depends(aluno_auth.conexao)):
    return criar_exercicio_aluno(conn, aluno, dados)


@router.delete("/exercicios/{exercicio_id}", status_code=204)
def rota_apagar_exercicio(exercicio_id: int, aluno: dict = Depends(aluno_auth.aluno_atual),
                          conn=Depends(aluno_auth.conexao)):
    apagar_exercicio_aluno(conn, aluno, exercicio_id)


@router.get("/modelos")
def rota_modelos(aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return {"modelos": listar_modelos(conn)}


@router.post("/modelos/{modelo_id}/copiar", status_code=201)
def rota_copiar_modelo(modelo_id: int, aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return {"treinos": copiar_modelo(conn, aluno, modelo_id)}


@router.get("/treinos")
def rota_treinos(aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return {"treinos": listar_treinos(conn, aluno)}


@router.put("/treinos/ordem")
def rota_ordem(dados: OrdemEntrada, aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return {"treinos": reordenar_treinos(conn, aluno, dados.ids)}


@router.post("/treinos", status_code=201)
def rota_criar_treino(dados: TreinoEntrada, aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return criar_treino(conn, aluno, dados)


@router.get("/treinos/{treino_id}")
def rota_treino(treino_id: int, aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return obter_treino(conn, aluno, treino_id)


@router.put("/treinos/{treino_id}")
def rota_gravar_treino(treino_id: int, dados: TreinoEntrada, aluno: dict = Depends(aluno_auth.aluno_atual),
                       conn=Depends(aluno_auth.conexao)):
    return gravar_treino(conn, aluno, treino_id, dados)


@router.delete("/treinos/{treino_id}", status_code=204)
def rota_apagar_treino(treino_id: int, aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    apagar_treino(conn, aluno, treino_id)


@router.post("/treinos/{treino_id}/duplicar", status_code=201)
def rota_duplicar(treino_id: int, aluno: dict = Depends(aluno_auth.aluno_atual), conn=Depends(aluno_auth.conexao)):
    return duplicar_treino(conn, aluno, treino_id)


@router.post("/treinos/blocos/{bloco_id}/mover")
def rota_mover_bloco(bloco_id: int, dados: MoverBlocoEntrada, aluno: dict = Depends(aluno_auth.aluno_atual),
                     conn=Depends(aluno_auth.conexao)):
    return mover_bloco(conn, aluno, bloco_id, dados.treino_id)
