-- Onda 1B (Plano 8): desafios com ranking e aparelhos disponíveis para o gerador de treino.
-- Mensalidade/QR usa a view situacao_alunos e agenda de aulas usa as tabelas da 051: nada novo para elas.
-- Cada recurso tem a própria flag em academia_recursos: mensalidade_qr, desafios, agenda_aulas, gerador_treino.
-- Migração aditiva.
BEGIN;

CREATE TABLE public.academia_equipamentos (
    academia_id integer NOT NULL REFERENCES public.academias(id) ON DELETE CASCADE,
    equipamento text NOT NULL CHECK (char_length(equipamento) BETWEEN 1 AND 80),
    disponivel boolean NOT NULL DEFAULT TRUE,
    atualizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (academia_id, equipamento)
);

CREATE TABLE public.desafios (
    id serial PRIMARY KEY,
    academia_id integer NOT NULL REFERENCES public.academias(id) ON DELETE CASCADE,
    nome text NOT NULL CHECK (char_length(nome) BETWEEN 2 AND 80),
    metrica text NOT NULL CHECK (metrica IN ('treinos', 'volume')),
    inicio date NOT NULL,
    fim date NOT NULL,
    ativo boolean NOT NULL DEFAULT TRUE,
    tv_token_hash text UNIQUE,                    -- página de ranking para TV (somente leitura); só o hash fica no banco
    criado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (fim >= inicio AND fim - inicio <= 366)
);
CREATE INDEX idx_desafios_academia ON public.desafios (academia_id, ativo);

CREATE TABLE public.desafios_participacao (
    desafio_id integer NOT NULL REFERENCES public.desafios(id) ON DELETE CASCADE,
    aluno_id integer NOT NULL REFERENCES public.alunos(id) ON DELETE CASCADE,
    entrou_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (desafio_id, aluno_id)
);
CREATE INDEX idx_desafios_part_aluno ON public.desafios_participacao (aluno_id);

COMMIT;
