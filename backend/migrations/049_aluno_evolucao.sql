-- Evolução do aluno: séries registradas (idempotentes), medidas, meta de peso e consentimento. Migração aditiva.
-- Fotos de progresso NÃO sobem ao servidor (ficam só no aparelho).
BEGIN;

CREATE TABLE public.aluno_series_registradas (
    id bigserial PRIMARY KEY,
    aluno_id integer NOT NULL REFERENCES public.alunos(id) ON DELETE CASCADE,
    client_id text NOT NULL CHECK (char_length(client_id) BETWEEN 8 AND 64),
    registrada_em timestamptz NOT NULL,
    treino_uid text CHECK (treino_uid IS NULL OR char_length(treino_uid) <= 64),
    exercicio_ref text NOT NULL CHECK (char_length(exercicio_ref) BETWEEN 1 AND 64),
    exercicio_nome text NOT NULL CHECK (char_length(exercicio_nome) BETWEEN 1 AND 120),
    grupo text NOT NULL CHECK (char_length(grupo) BETWEEN 1 AND 30),
    serie_numero smallint NOT NULL CHECK (serie_numero BETWEEN 1 AND 50),
    carga numeric(6,2) NOT NULL CHECK (carga >= 0 AND carga <= 1000),
    reps smallint NOT NULL CHECK (reps >= 0 AND reps <= 500),
    concluida boolean NOT NULL DEFAULT TRUE,
    criado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (aluno_id, client_id)
);
CREATE INDEX idx_series_aluno_data ON public.aluno_series_registradas (aluno_id, registrada_em DESC);
CREATE INDEX idx_series_aluno_exercicio ON public.aluno_series_registradas (aluno_id, exercicio_ref);

CREATE TABLE public.aluno_medidas (
    id serial PRIMARY KEY,
    aluno_id integer NOT NULL REFERENCES public.alunos(id) ON DELETE CASCADE,
    data date NOT NULL,
    tipo text NOT NULL CHECK (tipo IN ('peso', 'gordura', 'cintura', 'quadril', 'peito', 'braco', 'coxa', 'panturrilha')),
    valor numeric(7,2) NOT NULL CHECK (valor > 0 AND valor < 1000),
    criado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (aluno_id, data, tipo)
);
CREATE INDEX idx_medidas_aluno ON public.aluno_medidas (aluno_id, tipo, data DESC);

CREATE TABLE public.aluno_metas (
    aluno_id integer PRIMARY KEY REFERENCES public.alunos(id) ON DELETE CASCADE,
    peso_alvo numeric(6,2) CHECK (peso_alvo IS NULL OR (peso_alvo > 20 AND peso_alvo < 500)),
    atualizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.aluno_consentimentos (
    aluno_id integer PRIMARY KEY REFERENCES public.alunos(id) ON DELETE CASCADE,
    compartilhar_com_academia boolean NOT NULL DEFAULT FALSE,
    atualizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMIT;
