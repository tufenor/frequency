"""Gera backend/migrations/048_treinos_catalogo.sql a partir de catalogo_base.json (rodar uma vez; resultado versionado)."""
import json
from pathlib import Path

AQUI = Path(__file__).resolve().parent
dados = json.loads((AQUI / "catalogo_base.json").read_text(encoding="utf-8"))
q = lambda s: "'" + s.replace("'", "''") + "'"
grupos = ", ".join(q(g) for g in dados["grupos"])
livres = ", ".join(q(g) for g in ["aquecimento", "cardio", "alongamento"])
linhas = []
for e in dados["exercicios"]:
    foto = q(e["foto"]) if e.get("foto") else "NULL"
    linhas.append(f"({q(e['id'])}, {q(e['nome'])}, {q(e['grupo'])}, {q(e['equip'])}, {q(e['nivel'])}, {e['series']}, {q(e['reps'])}, {'TRUE' if e['tempo'] else 'FALSE'}, {e['desc']}, {foto})")
seed_ex = ",\n".join(linhas)
seed_mod = ",\n".join(
    f"({q(m['nome'])}, {q(m['descricao'])}, {q(m['nivel'])}, {len(m['dias'])}, {i + 1}, $json${json.dumps({'dias': m['dias']}, ensure_ascii=False)}$json$::jsonb)"
    for i, m in enumerate(dados["modelos"]))
sql = f"""-- Treinos editáveis em blocos, catálogo de exercícios (>= 12 por grupo) e modelos prontos. Migração aditiva.
BEGIN;

CREATE TABLE public.exercicios_catalogo (
    id text PRIMARY KEY,
    nome text NOT NULL,
    grupo text NOT NULL CHECK (grupo IN ({grupos})),
    equipamento text NOT NULL,
    nivel text NOT NULL CHECK (nivel IN ('Iniciante', 'Intermediário', 'Avançado')),
    series_sugeridas smallint NOT NULL CHECK (series_sugeridas BETWEEN 1 AND 20),
    reps_sugeridas text NOT NULL,
    tempo boolean NOT NULL DEFAULT FALSE,
    descanso_s smallint NOT NULL DEFAULT 60 CHECK (descanso_s BETWEEN 0 AND 600),
    foto_chave text,
    ativo boolean NOT NULL DEFAULT TRUE
);
CREATE INDEX idx_exercicios_catalogo_grupo ON public.exercicios_catalogo (grupo) WHERE ativo;

CREATE TABLE public.academia_exercicios_visibilidade (
    academia_id integer NOT NULL REFERENCES public.academias(id) ON DELETE CASCADE,
    exercicio_id text NOT NULL REFERENCES public.exercicios_catalogo(id) ON DELETE CASCADE,
    oculto boolean NOT NULL DEFAULT TRUE,
    atualizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (academia_id, exercicio_id)
);

CREATE TABLE public.exercicios_custom (
    id serial PRIMARY KEY,
    escopo text NOT NULL CHECK (escopo IN ('aluno', 'academia')),
    academia_id integer NOT NULL REFERENCES public.academias(id) ON DELETE CASCADE,
    aluno_id integer REFERENCES public.alunos(id) ON DELETE CASCADE,
    nome text NOT NULL CHECK (char_length(nome) BETWEEN 2 AND 120),
    grupo text NOT NULL CHECK (grupo IN ({grupos})),
    equipamento text NOT NULL DEFAULT '' CHECK (char_length(equipamento) <= 80),
    tempo boolean NOT NULL DEFAULT FALSE,
    ativo boolean NOT NULL DEFAULT TRUE,
    criado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((escopo = 'aluno' AND aluno_id IS NOT NULL) OR (escopo = 'academia' AND aluno_id IS NULL))
);
CREATE INDEX idx_exercicios_custom_academia ON public.exercicios_custom (academia_id, escopo) WHERE ativo;
CREATE INDEX idx_exercicios_custom_aluno ON public.exercicios_custom (aluno_id) WHERE aluno_id IS NOT NULL;

CREATE TABLE public.treinos_modelo (
    id serial PRIMARY KEY,
    nome text NOT NULL,
    descricao text NOT NULL DEFAULT '',
    nivel text NOT NULL CHECK (nivel IN ('Iniciante', 'Intermediário', 'Avançado')),
    dias smallint NOT NULL,
    ordem smallint NOT NULL,
    conteudo jsonb NOT NULL
);

CREATE TABLE public.treinos (
    id serial PRIMARY KEY,
    aluno_id integer NOT NULL REFERENCES public.alunos(id) ON DELETE CASCADE,
    nome text NOT NULL CHECK (char_length(nome) BETWEEN 1 AND 80),
    letra text CHECK (letra IS NULL OR char_length(letra) BETWEEN 1 AND 3),
    dias_semana smallint[] NOT NULL DEFAULT '{{}}',
    ordem integer NOT NULL DEFAULT 0,
    modelo_origem_id integer REFERENCES public.treinos_modelo(id) ON DELETE SET NULL,
    versao integer NOT NULL DEFAULT 1,
    criado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (dias_semana <@ ARRAY[0,1,2,3,4,5,6]::smallint[])
);
CREATE INDEX idx_treinos_aluno ON public.treinos (aluno_id, ordem);

CREATE TABLE public.treino_blocos (
    id serial PRIMARY KEY,
    treino_id integer NOT NULL REFERENCES public.treinos(id) ON DELETE CASCADE,
    grupo text NOT NULL CHECK (grupo IN ({grupos}, {livres})),
    nome text NOT NULL CHECK (char_length(nome) BETWEEN 1 AND 80),
    ordem integer NOT NULL DEFAULT 0,
    concluido_em timestamptz
);
CREATE INDEX idx_treino_blocos_treino ON public.treino_blocos (treino_id, ordem);

CREATE TABLE public.treino_itens (
    id serial PRIMARY KEY,
    bloco_id integer NOT NULL REFERENCES public.treino_blocos(id) ON DELETE CASCADE,
    catalogo_id text REFERENCES public.exercicios_catalogo(id),
    custom_id integer REFERENCES public.exercicios_custom(id) ON DELETE SET NULL,
    nome_livre text CHECK (nome_livre IS NULL OR char_length(nome_livre) BETWEEN 1 AND 120),
    series smallint NOT NULL DEFAULT 3 CHECK (series BETWEEN 1 AND 30),
    reps text NOT NULL DEFAULT '10' CHECK (char_length(reps) BETWEEN 1 AND 20),
    tempo boolean NOT NULL DEFAULT FALSE,
    carga numeric(6,1) CHECK (carga IS NULL OR (carga >= 0 AND carga <= 1000)),
    descanso_s smallint NOT NULL DEFAULT 60 CHECK (descanso_s BETWEEN 0 AND 900),
    observacao text CHECK (observacao IS NULL OR char_length(observacao) <= 500),
    ordem integer NOT NULL DEFAULT 0,
    CHECK ((catalogo_id IS NOT NULL)::int + (custom_id IS NOT NULL)::int + (nome_livre IS NOT NULL)::int = 1)
);
CREATE INDEX idx_treino_itens_bloco ON public.treino_itens (bloco_id, ordem);

INSERT INTO public.exercicios_catalogo (id, nome, grupo, equipamento, nivel, series_sugeridas, reps_sugeridas, tempo, descanso_s, foto_chave) VALUES
{seed_ex};

INSERT INTO public.treinos_modelo (nome, descricao, nivel, dias, ordem, conteudo) VALUES
{seed_mod};

COMMIT;
"""
saida = AQUI.parents[1] / "migrations" / "048_treinos_catalogo.sql"
saida.write_text(sql, encoding="utf-8")
print("gerado", saida, len(sql))
