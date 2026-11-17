-- Módulo Lutas (Plano 7). Tudo atrás da flag `lutas` por academia. Migração aditiva:
-- só cria tabelas novas e AMPLIA a lista de papéis de usuario ('professor').
BEGIN;

ALTER TABLE public.usuarios DROP CONSTRAINT IF EXISTS usuarios_papel_check;
ALTER TABLE public.usuarios ADD CONSTRAINT usuarios_papel_check
    CHECK (papel = ANY (ARRAY['dono'::text, 'recepcao'::text, 'admin_plataforma'::text, 'professor'::text]));

-- Local da academia (para "dentro/fora do raio") e fuso dos horários das turmas.
CREATE TABLE public.academia_local (
    academia_id integer PRIMARY KEY REFERENCES public.academias(id) ON DELETE CASCADE,
    latitude double precision CHECK (latitude BETWEEN -90 AND 90),
    longitude double precision CHECK (longitude BETWEEN -180 AND 180),
    raio_m integer NOT NULL DEFAULT 150 CHECK (raio_m BETWEEN 20 AND 2000),
    fuso text NOT NULL DEFAULT 'America/Sao_Paulo' CHECK (char_length(fuso) BETWEEN 3 AND 64),
    atualizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.modalidades (
    id serial PRIMARY KEY,
    academia_id integer NOT NULL REFERENCES public.academias(id) ON DELETE CASCADE,
    nome text NOT NULL CHECK (char_length(nome) BETWEEN 2 AND 60),
    -- 'luta' usa a flag `lutas`; 'aula' (yoga, spinning…) usa a flag `agenda_aulas` (Plano 8)
    categoria text NOT NULL DEFAULT 'luta' CHECK (categoria IN ('luta', 'aula')),
    ativa boolean NOT NULL DEFAULT TRUE,
    criada_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX uq_modalidades_nome ON public.modalidades (academia_id, lower(nome));

-- Um plano pode incluir várias modalidades (combo). Sem linhas = o plano não dá acesso a luta.
CREATE TABLE public.plano_modalidades (
    plano_id integer NOT NULL REFERENCES public.planos(id) ON DELETE CASCADE,
    modalidade_id integer NOT NULL REFERENCES public.modalidades(id) ON DELETE CASCADE,
    PRIMARY KEY (plano_id, modalidade_id)
);

CREATE TABLE public.professores (
    id serial PRIMARY KEY,
    academia_id integer NOT NULL REFERENCES public.academias(id) ON DELETE CASCADE,
    nome text NOT NULL CHECK (char_length(nome) BETWEEN 2 AND 80),
    usuario_id integer UNIQUE REFERENCES public.usuarios(id) ON DELETE SET NULL,
    ativo boolean NOT NULL DEFAULT TRUE
);

CREATE TABLE public.turmas (
    id serial PRIMARY KEY,
    academia_id integer NOT NULL REFERENCES public.academias(id) ON DELETE CASCADE,
    modalidade_id integer NOT NULL REFERENCES public.modalidades(id) ON DELETE RESTRICT,
    professor_id integer REFERENCES public.professores(id) ON DELETE SET NULL,
    nome text NOT NULL CHECK (char_length(nome) BETWEEN 2 AND 80),
    capacidade integer NOT NULL DEFAULT 30 CHECK (capacidade BETWEEN 1 AND 500),
    exige_reserva boolean NOT NULL DEFAULT FALSE,
    ativa boolean NOT NULL DEFAULT TRUE
);
CREATE INDEX idx_turmas_prof ON public.turmas (professor_id);

CREATE TABLE public.turma_horarios (
    id serial PRIMARY KEY,
    turma_id integer NOT NULL REFERENCES public.turmas(id) ON DELETE CASCADE,
    dia_semana smallint NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),   -- 0 = domingo
    inicio time NOT NULL,
    fim time NOT NULL,
    CHECK (fim > inicio),
    UNIQUE (turma_id, dia_semana, inicio)
);

-- Reserva fixa na turma; `espera` já prepara a fila do Plano 8.
CREATE TABLE public.reservas_turma (
    id bigserial PRIMARY KEY,
    turma_id integer NOT NULL REFERENCES public.turmas(id) ON DELETE CASCADE,
    aluno_id integer NOT NULL REFERENCES public.alunos(id) ON DELETE CASCADE,
    estado text NOT NULL DEFAULT 'ativa' CHECK (estado IN ('ativa', 'espera')),
    criada_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (turma_id, aluno_id)
);

CREATE TABLE public.faixas (
    id serial PRIMARY KEY,
    academia_id integer NOT NULL REFERENCES public.academias(id) ON DELETE CASCADE,
    modalidade_id integer NOT NULL REFERENCES public.modalidades(id) ON DELETE CASCADE,
    nome text NOT NULL CHECK (char_length(nome) BETWEEN 1 AND 40),
    ordem smallint NOT NULL CHECK (ordem BETWEEN 0 AND 50),
    aulas_minimas integer NOT NULL DEFAULT 0 CHECK (aulas_minimas BETWEEN 0 AND 5000),
    UNIQUE (modalidade_id, ordem)
);

CREATE TABLE public.aluno_graduacoes (
    id bigserial PRIMARY KEY,
    aluno_id integer NOT NULL REFERENCES public.alunos(id) ON DELETE CASCADE,
    modalidade_id integer NOT NULL REFERENCES public.modalidades(id) ON DELETE CASCADE,
    faixa_id integer NOT NULL REFERENCES public.faixas(id) ON DELETE RESTRICT,
    concedida_em date NOT NULL DEFAULT CURRENT_DATE,
    concedida_por integer REFERENCES public.usuarios(id) ON DELETE SET NULL
);
CREATE INDEX idx_graduacoes_aluno ON public.aluno_graduacoes (aluno_id, modalidade_id, id DESC);

-- Uma aula realizada = uma ocorrência (turma, horário, data). Criada na primeira confirmação/chamada.
CREATE TABLE public.aulas_realizadas (
    id bigserial PRIMARY KEY,
    academia_id integer NOT NULL REFERENCES public.academias(id) ON DELETE CASCADE,
    turma_id integer NOT NULL REFERENCES public.turmas(id) ON DELETE CASCADE,
    horario_id integer REFERENCES public.turma_horarios(id) ON DELETE SET NULL,
    professor_id integer REFERENCES public.professores(id) ON DELETE SET NULL,
    inicio timestamptz NOT NULL,
    fim timestamptz NOT NULL,
    CHECK (fim > inicio),
    UNIQUE (turma_id, inicio)
);

-- confirmada (aluno tocou/QR) → validada (professor) ou ausente. Só `validada` conta.
CREATE TABLE public.presencas_aula (
    id bigserial PRIMARY KEY,
    aula_id bigint NOT NULL REFERENCES public.aulas_realizadas(id) ON DELETE CASCADE,
    aluno_id integer NOT NULL REFERENCES public.alunos(id) ON DELETE CASCADE,
    estado text NOT NULL CHECK (estado IN ('confirmada', 'validada', 'ausente')),
    metodo text NOT NULL CHECK (metodo IN ('toque', 'qr', 'professor')),
    dentro_do_raio boolean,              -- só "dentro/fora"; a coordenada nunca é guardada
    confirmada_em timestamptz,
    validada_em timestamptz,
    validada_por integer REFERENCES public.usuarios(id) ON DELETE SET NULL,
    UNIQUE (aula_id, aluno_id)
);
CREATE INDEX idx_presencas_aluno ON public.presencas_aula (aluno_id, estado);

CREATE TABLE public.atestados_aluno (
    id bigserial PRIMARY KEY,
    aluno_id integer NOT NULL REFERENCES public.alunos(id) ON DELETE CASCADE,
    valido_ate date NOT NULL,
    observacao text NOT NULL DEFAULT '' CHECK (char_length(observacao) <= 200),
    registrado_por integer REFERENCES public.usuarios(id) ON DELETE SET NULL,
    registrado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_atestados_aluno ON public.atestados_aluno (aluno_id, valido_ate DESC);

COMMIT;
