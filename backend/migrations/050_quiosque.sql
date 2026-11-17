-- Quiosque do tablet: aparelhos cadastrados, tickets curtos (somente leitura do treino do dia) e QR de uso único.
-- Nenhuma imagem é guardada. Migração aditiva.
BEGIN;

CREATE TABLE public.quiosques (
    id serial PRIMARY KEY,
    academia_id integer NOT NULL REFERENCES public.academias(id) ON DELETE CASCADE,
    nome text NOT NULL CHECK (char_length(nome) BETWEEN 2 AND 80),
    token_hash text NOT NULL UNIQUE,
    ativo boolean NOT NULL DEFAULT TRUE,
    criado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revogado_em timestamptz,
    ultimo_uso timestamptz
);
CREATE INDEX idx_quiosques_academia ON public.quiosques (academia_id) WHERE ativo;

CREATE TABLE public.quiosque_tickets (
    id bigserial PRIMARY KEY,
    quiosque_id integer NOT NULL REFERENCES public.quiosques(id) ON DELETE CASCADE,
    aluno_id integer NOT NULL REFERENCES public.alunos(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    metodo text NOT NULL CHECK (metodo IN ('facial', 'qr', 'email')),
    criado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expira_em timestamptz NOT NULL,
    encerrado_em timestamptz,
    leituras smallint NOT NULL DEFAULT 0
);
CREATE INDEX idx_quiosque_tickets_exp ON public.quiosque_tickets (expira_em);

CREATE TABLE public.aluno_qr_quiosque (
    id bigserial PRIMARY KEY,
    aluno_id integer NOT NULL REFERENCES public.alunos(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    criado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expira_em timestamptz NOT NULL,
    usado_em timestamptz
);

COMMIT;
