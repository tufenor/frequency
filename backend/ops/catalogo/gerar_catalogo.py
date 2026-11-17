"""Gera catálogo base (JSON) a partir da biblioteca do app + extras. Saída: catalogo_base.json"""
import json, re, sys
from pathlib import Path

BIB = Path("/home/claude/work/frequency-aluno/src/biblioteca.ts").read_text(encoding="utf-8")
pat = re.compile(r"\{ id: '([^']+)', nome: '([^']+)', musculo: '([^']+)', nivel: '([^']+)', equip: '([^']+)', series: (\d+), reps: '([^']+)', tempo: (true|false), desc: (\d+) \}")
base = []
for m in pat.finditer(BIB):
    i, nome, g, nv, eq, s, r, t, d = m.groups()
    base.append(dict(id=i, nome=nome, grupo=g, nivel=nv, equip=eq, series=int(s), reps=r, tempo=t == "true", desc=int(d), foto=i))
assert len(base) == 80, len(base)

def ex(i, nome, g, nv, eq, tempo=False):
    ser, reps, desc = {"Iniciante": (3, "10-12", 60), "Intermediário": (4, "8-12", 75), "Avançado": (4, "6-10", 90)}[nv]
    if tempo:
        reps = "30-45"
    if g == "panturrilhas":
        reps = "12-20"
    return dict(id=i, nome=nome, grupo=g, nivel=nv, equip=eq, series=ser, reps=reps, tempo=tempo, desc=desc, foto=None)

I, M, A = "Iniciante", "Intermediário", "Avançado"
extras = [
 ex("supino_declinado_barra", "Supino declinado com barra", "peito", M, "Barra"),
 ex("crucifixo_reto_halteres", "Crucifixo reto com halteres", "peito", I, "Halteres"),
 ex("pullover_halter", "Pullover com halter", "peito", M, "Halteres"),
 ex("supino_smith", "Supino reto no Smith", "peito", I, "Máquina"),
 ex("remada_cavalinho", "Remada cavalinho", "costas", M, "Barra"),
 ex("remada_maquina", "Remada na máquina", "costas", I, "Máquina"),
 ex("pulldown_braco_reto", "Pulldown com braço estendido", "costas", M, "Polia"),
 ex("barra_fixa_neutra", "Barra fixa pegada neutra", "costas", M, "Peso do corpo"),
 ex("desenvolvimento_smith", "Desenvolvimento no Smith", "ombros", M, "Máquina"),
 ex("elevacao_lateral_polia", "Elevação lateral na polia", "ombros", M, "Polia"),
 ex("remada_alta_barra", "Remada alta com barra", "ombros", M, "Barra"),
 ex("encolhimento_halteres", "Encolhimento com halteres", "ombros", I, "Halteres"),
 ex("rosca_inclinada_halteres", "Rosca inclinada com halteres", "biceps", M, "Halteres"),
 ex("rosca_polia_baixa", "Rosca na polia baixa", "biceps", I, "Polia"),
 ex("rosca_21", "Rosca 21", "biceps", A, "Barra"),
 ex("rosca_scott_barra_w", "Rosca scott com barra W", "biceps", M, "Barra W"),
 ex("triceps_frances_halter", "Tríceps francês com halter", "triceps", M, "Halteres"),
 ex("triceps_coice", "Tríceps coice", "triceps", I, "Halteres"),
 ex("mergulho_maquina", "Mergulho na máquina", "triceps", I, "Máquina"),
 ex("flexao_diamante", "Flexão diamante", "triceps", A, "Peso do corpo"),
 ex("prancha_lateral", "Prancha lateral", "abdomen", I, "Peso do corpo", True),
 ex("abdominal_bicicleta", "Abdominal bicicleta", "abdomen", I, "Peso do corpo"),
 ex("abdominal_infra_solo", "Abdominal infra no solo", "abdomen", I, "Peso do corpo"),
 ex("rotacao_russa", "Rotação russa", "abdomen", M, "Peso do corpo"),
 ex("agachamento_hack", "Agachamento hack", "quadriceps", M, "Máquina"),
 ex("agachamento_bulgaro", "Agachamento búlgaro", "quadriceps", A, "Halteres"),
 ex("agachamento_smith", "Agachamento no Smith", "quadriceps", I, "Máquina"),
 ex("step_up_banco", "Step-up no banco", "quadriceps", I, "Halteres"),
 ex("flexora_polia_unilateral", "Flexora unilateral na polia", "posteriores", M, "Polia"),
 ex("stiff_barra", "Stiff com barra", "posteriores", M, "Barra"),
 ex("stiff_unilateral_halter", "Stiff unilateral com halter", "posteriores", A, "Halteres"),
 ex("flexora_nordica", "Flexora nórdica", "posteriores", A, "Peso do corpo"),
 ex("abducao_quadril_maquina", "Abdução de quadril na máquina", "gluteos", I, "Máquina"),
 ex("agachamento_sumo_halter", "Agachamento sumô com halter", "gluteos", I, "Halteres"),
 ex("hip_thrust_maquina", "Hip thrust na máquina", "gluteos", M, "Máquina"),
 ex("afundo_reverso", "Afundo reverso", "gluteos", M, "Halteres"),
 ex("panturrilha_degrau", "Panturrilha no degrau", "panturrilhas", I, "Peso do corpo"),
 ex("panturrilha_burrinho", "Panturrilha burrinho", "panturrilhas", M, "Máquina"),
 ex("panturrilha_hack", "Panturrilha no hack", "panturrilhas", M, "Máquina"),
 ex("panturrilha_unilateral_em_pe", "Panturrilha unilateral em pé", "panturrilhas", M, "Peso do corpo"),
 # antebraço (12)
 ex("rosca_punho_barra", "Rosca de punho com barra", "antebraco", I, "Barra"),
 ex("rosca_punho_inversa", "Rosca de punho inversa", "antebraco", I, "Barra"),
 ex("rosca_inversa_barra", "Rosca inversa com barra", "antebraco", M, "Barra"),
 ex("rosca_martelo_corda", "Rosca martelo na corda", "antebraco", I, "Polia"),
 ex("flexao_punho_halter", "Flexão de punho com halter", "antebraco", I, "Halteres"),
 ex("extensao_punho_halter", "Extensão de punho com halter", "antebraco", I, "Halteres"),
 ex("suspensao_barra", "Suspensão na barra", "antebraco", M, "Peso do corpo", True),
 ex("caminhada_fazendeiro", "Caminhada do fazendeiro", "antebraco", M, "Halteres", True),
 ex("pinca_anilha", "Pinça com anilha", "antebraco", A, "Anilha", True),
 ex("rosca_punho_polia", "Rosca de punho na polia", "antebraco", M, "Polia"),
 ex("rolo_de_punho", "Rolo de punho", "antebraco", A, "Barra"),
 ex("rosca_inversa_halteres", "Rosca inversa com halteres", "antebraco", I, "Halteres"),
 # lombar (12)
 ex("hiperextensao_banco", "Hiperextensão no banco", "lombar", I, "Peso do corpo"),
 ex("hiperextensao_45", "Hiperextensão 45°", "lombar", M, "Peso do corpo"),
 ex("extensao_lombar_maquina", "Extensão lombar na máquina", "lombar", I, "Máquina"),
 ex("superman", "Superman", "lombar", I, "Peso do corpo", True),
 ex("bird_dog", "Bird dog", "lombar", I, "Peso do corpo", True),
 ex("extensao_lombar_chao", "Extensão lombar no chão", "lombar", I, "Peso do corpo"),
 ex("hiperextensao_anilha", "Hiperextensão com anilha", "lombar", M, "Anilha"),
 ex("bom_dia_halter", "Bom dia com halter", "lombar", M, "Halteres"),
 ex("elevacao_tronco_bola", "Elevação de tronco na bola suíça", "lombar", M, "Bola suíça"),
 ex("prancha_elevacao_perna", "Prancha com elevação de perna", "lombar", M, "Peso do corpo", True),
 ex("terra_sumo", "Levantamento terra sumô", "lombar", A, "Barra"),
 ex("terra_hexagonal", "Terra com barra hexagonal", "lombar", A, "Barra"),
]
cat = base + extras
ids = [c["id"] for c in cat]
assert len(ids) == len(set(ids)), "ids repetidos"
from collections import Counter
cont = Counter(c["grupo"] for c in cat)
GRUPOS = ["peito", "costas", "ombros", "biceps", "triceps", "antebraco", "abdomen", "lombar", "quadriceps", "posteriores", "gluteos", "panturrilhas"]
assert all(cont[g] >= 12 for g in GRUPOS), cont
print(cont, len(cat), file=sys.stderr)

def pick(g, n, nivel=None):
    L = [c["id"] for c in cat if c["grupo"] == g and (nivel is None or c["nivel"] in nivel)]
    return L[:n]

def bloco(g, n=3, nivel=None):
    return {"grupo": g, "exercicios": pick(g, n, nivel)}

def livre(g, nome, tempo=True, reps="10", series=1):
    return {"grupo": g, "exercicios": [], "livres": [{"nome": nome, "tempo": tempo, "reps": reps, "series": series}]}

INI = ["Iniciante"]
modelos = []
def modelo(nome, desc, nivel, dias):
    modelos.append(dict(nome=nome, descricao=desc, nivel=nivel, dias=dias))

modelo("ABC clássico", "Peito e tríceps, costas e bíceps, pernas e ombros.", "Intermediário", [
  {"nome": "Peito e tríceps", "blocos": [bloco("peito", 4), bloco("triceps", 3)]},
  {"nome": "Costas e bíceps", "blocos": [bloco("costas", 4), bloco("biceps", 3)]},
  {"nome": "Pernas e ombros", "blocos": [bloco("quadriceps", 3), bloco("posteriores", 2), bloco("ombros", 3)]}])
modelo("ABCD", "Quatro dias: peito/tríceps, costas/bíceps, pernas, ombros/abdômen.", "Intermediário", [
  {"nome": "Peito e tríceps", "blocos": [bloco("peito", 4), bloco("triceps", 3)]},
  {"nome": "Costas e bíceps", "blocos": [bloco("costas", 4), bloco("biceps", 3)]},
  {"nome": "Pernas", "blocos": [bloco("quadriceps", 3), bloco("posteriores", 3), bloco("panturrilhas", 2)]},
  {"nome": "Ombros e abdômen", "blocos": [bloco("ombros", 4), bloco("abdomen", 3)]}])
modelo("ABCDE", "Um grupo principal por dia.", "Avançado", [
  {"nome": "Peito", "blocos": [bloco("peito", 5)]},
  {"nome": "Costas", "blocos": [bloco("costas", 5)]},
  {"nome": "Pernas", "blocos": [bloco("quadriceps", 3), bloco("posteriores", 3), bloco("gluteos", 2)]},
  {"nome": "Ombros", "blocos": [bloco("ombros", 5)]},
  {"nome": "Braços", "blocos": [bloco("biceps", 3), bloco("triceps", 3), bloco("antebraco", 2)]}])
modelo("Full body 3x", "Corpo inteiro em cada treino, três vezes por semana.", "Iniciante", [
  {"nome": "Corpo inteiro %s" % n, "blocos": [bloco("peito", 1, INI), bloco("costas", 1, INI), bloco("quadriceps", 1, INI), bloco("ombros", 1, INI), bloco("abdomen", 1, INI)]} for n in "ABC"])
modelo("Push / Pull / Legs", "Empurrar, puxar e pernas.", "Intermediário", [
  {"nome": "Push", "blocos": [bloco("peito", 3), bloco("ombros", 3), bloco("triceps", 3)]},
  {"nome": "Pull", "blocos": [bloco("costas", 4), bloco("biceps", 3), bloco("antebraco", 1)]},
  {"nome": "Legs", "blocos": [bloco("quadriceps", 3), bloco("posteriores", 3), bloco("gluteos", 2), bloco("panturrilhas", 2)]}])
modelo("Superior / Inferior", "Dois dias alternados.", "Intermediário", [
  {"nome": "Superior", "blocos": [bloco("peito", 2), bloco("costas", 2), bloco("ombros", 2), bloco("biceps", 1), bloco("triceps", 1)]},
  {"nome": "Inferior", "blocos": [bloco("quadriceps", 3), bloco("posteriores", 2), bloco("gluteos", 2), bloco("panturrilhas", 2)]}])
modelo("Iniciante ABC", "Poucos exercícios por grupo, sem equipamento complexo.", "Iniciante", [
  {"nome": "A – Empurrar", "blocos": [bloco("peito", 2, INI), bloco("ombros", 2, INI), bloco("triceps", 2, INI)]},
  {"nome": "B – Puxar", "blocos": [bloco("costas", 3, INI), bloco("biceps", 2, INI)]},
  {"nome": "C – Pernas", "blocos": [bloco("quadriceps", 3, INI), bloco("posteriores", 2, INI), bloco("abdomen", 2, INI)]}])
modelo("Iniciante 2x por semana", "Dois treinos curtos para começar.", "Iniciante", [
  {"nome": "Dia 1", "blocos": [bloco("peito", 1, INI), bloco("costas", 1, INI), bloco("quadriceps", 2, INI)]},
  {"nome": "Dia 2", "blocos": [bloco("ombros", 1, INI), bloco("posteriores", 1, INI), bloco("abdomen", 2, INI)]}])
modelo("Emagrecimento (circuito)", "Aquecimento, circuito de força e cardio.", "Iniciante", [
  {"nome": "Circuito A", "blocos": [livre("aquecimento", "Esteira leve", True, "300"), bloco("quadriceps", 2, INI), bloco("peito", 1, INI), bloco("costas", 1, INI), livre("cardio", "Bicicleta", True, "900")]},
  {"nome": "Circuito B", "blocos": [livre("aquecimento", "Elíptico leve", True, "300"), bloco("gluteos", 2, INI), bloco("ombros", 1, INI), bloco("abdomen", 2, INI), livre("cardio", "Esteira", True, "900")]}])
modelo("Hipertrofia ABCD", "Volume maior por grupo.", "Avançado", [
  {"nome": "Peito e tríceps", "blocos": [bloco("peito", 5), bloco("triceps", 4)]},
  {"nome": "Costas e bíceps", "blocos": [bloco("costas", 5), bloco("biceps", 4)]},
  {"nome": "Pernas", "blocos": [bloco("quadriceps", 4), bloco("posteriores", 3), bloco("panturrilhas", 3)]},
  {"nome": "Ombros e core", "blocos": [bloco("ombros", 5), bloco("abdomen", 3)]}])
modelo("Em casa, sem equipamento", "Só peso do corpo.", "Iniciante", [
  {"nome": "Casa A", "blocos": [{"grupo": "peito", "exercicios": ["pushups", "flexao_diamante"]}, {"grupo": "quadriceps", "exercicios": ["bodyweight_squat", "step_up_banco"]}, {"grupo": "abdomen", "exercicios": ["plank", "crunches"]}]},
  {"nome": "Casa B", "blocos": [{"grupo": "gluteos", "exercicios": ["butt_lift_bridge", "glute_kickback"]}, {"grupo": "lombar", "exercicios": ["superman", "bird_dog"]}, {"grupo": "abdomen", "exercicios": ["abdominal_bicicleta", "prancha_lateral"]}]}])
modelo("Só halteres", "Para quem tem apenas halteres.", "Intermediário", [
  {"nome": "Superior", "blocos": [{"grupo": "peito", "exercicios": ["dumbbell_bench_press", "incline_dumbbell_flyes"]}, {"grupo": "costas", "exercicios": ["one_arm_dumbbell_row", "dumbbell_incline_row"]}, {"grupo": "ombros", "exercicios": ["dumbbell_shoulder_press", "side_lateral_raise"]}]},
  {"nome": "Inferior e braços", "blocos": [{"grupo": "quadriceps", "exercicios": ["dumbbell_lunges", "agachamento_bulgaro"]}, {"grupo": "posteriores", "exercicios": ["stiff_legged_dumbbell_deadlift"]}, {"grupo": "biceps", "exercicios": ["alternate_hammer_curl", "concentration_curls"]}, {"grupo": "triceps", "exercicios": ["dumbbell_one_arm_triceps_extension", "triceps_coice"]}]}])
modelo("Foco em glúteos", "Glúteos duas vezes por semana.", "Intermediário", [
  {"nome": "Glúteos A", "blocos": [bloco("gluteos", 4), bloco("posteriores", 2)]},
  {"nome": "Pernas e core", "blocos": [bloco("quadriceps", 3), bloco("gluteos", 2), bloco("abdomen", 2)]},
  {"nome": "Glúteos B", "blocos": [bloco("gluteos", 4), bloco("panturrilhas", 2)]}])
modelo("Mobilidade e alongamento", "Sessão leve de recuperação.", "Iniciante", [
  {"nome": "Mobilidade", "blocos": [livre("aquecimento", "Caminhada leve", True, "300"), livre("alongamento", "Alongamento geral", True, "600"), {"grupo": "lombar", "exercicios": ["bird_dog", "superman"]}]}])
modelo("Peito e costas", "Dois grupos grandes juntos.", "Intermediário", [
  {"nome": "Peito e costas", "blocos": [bloco("peito", 4), bloco("costas", 4)]},
  {"nome": "Braços e ombros", "blocos": [bloco("ombros", 3), bloco("biceps", 3), bloco("triceps", 3)]}])
modelo("Braços e ombros", "Dia dedicado a braços.", "Intermediário", [
  {"nome": "Braços e ombros", "blocos": [bloco("ombros", 3), bloco("biceps", 3), bloco("triceps", 3), bloco("antebraco", 2)]}])
modelo("Pernas completas", "Quadríceps, posteriores, glúteos e panturrilhas.", "Intermediário", [
  {"nome": "Pernas completas", "blocos": [bloco("quadriceps", 4), bloco("posteriores", 3), bloco("gluteos", 2), bloco("panturrilhas", 3)]}])
modelo("Core e lombar", "Abdômen e lombar.", "Iniciante", [
  {"nome": "Core e lombar", "blocos": [bloco("abdomen", 4), bloco("lombar", 4)]}])
modelo("Feminino: pernas e glúteos", "Ênfase em membros inferiores.", "Iniciante", [
  {"nome": "Pernas e glúteos", "blocos": [bloco("gluteos", 3, INI), bloco("quadriceps", 3, INI), bloco("posteriores", 2, INI)]},
  {"nome": "Superior leve", "blocos": [bloco("costas", 2, INI), bloco("ombros", 2, INI), bloco("abdomen", 2, INI)]}])
modelo("Força (básicos)", "Foco nos movimentos básicos.", "Avançado", [
  {"nome": "Força A", "blocos": [{"grupo": "quadriceps", "exercicios": ["barbell_squat"]}, {"grupo": "peito", "exercicios": ["barbell_bench_press_medium_grip"]}, {"grupo": "costas", "exercicios": ["bent_over_barbell_row"]}]},
  {"nome": "Força B", "blocos": [{"grupo": "costas", "exercicios": ["barbell_deadlift"]}, {"grupo": "ombros", "exercicios": ["barbell_shoulder_press"]}, {"grupo": "quadriceps", "exercicios": ["front_barbell_squat"]}]}])
modelo("Treino rápido 30 minutos", "Poucos exercícios, intervalos curtos.", "Iniciante", [
  {"nome": "Rápido", "blocos": [bloco("peito", 1, INI), bloco("costas", 1, INI), bloco("quadriceps", 1, INI), bloco("abdomen", 1, INI), livre("cardio", "Cardio leve", True, "300")]}])
modelo("Costas e ombros (postura)", "Fortalecer a parte de trás do corpo.", "Intermediário", [
  {"nome": "Postura", "blocos": [bloco("costas", 4), bloco("ombros", 3), bloco("lombar", 3)]}])
modelo("Cardio e abdômen", "Aquecimento, cardio e core.", "Iniciante", [
  {"nome": "Cardio e core", "blocos": [livre("aquecimento", "Esteira leve", True, "300"), livre("cardio", "Bicicleta", True, "1200"), bloco("abdomen", 4)]}])
assert len(modelos) >= 20, len(modelos)
for m in modelos:
    for d in m["dias"]:
        for b in d["blocos"]:
            for e in b["exercicios"]:
                assert e in ids, (m["nome"], e)
            if b["grupo"] in GRUPOS:
                assert b["exercicios"] or b.get("livres"), (m["nome"], b)
Path(sys.argv[1]).write_text(json.dumps({"grupos": GRUPOS, "exercicios": cat, "modelos": modelos}, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok", len(cat), len(modelos), file=sys.stderr)
