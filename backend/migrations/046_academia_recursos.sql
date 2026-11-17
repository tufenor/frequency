-- Recursos (flags) ligados por academia: login do aluno, lutas, quiosque etc. Migração aditiva.
-- Tudo nasce desligado; a academia de demonstração é ligada manualmente pelo dono.
BEGIN;

CREATE TABLE public.academia_recursos (
    academia_id integer NOT NULL REFERENCES public.academias(id) ON DELETE CASCADE,
    recurso text NOT NULL CHECK (recurso ~ '^[a-z][a-z0-9_]{2,40}$'),
    ligado boolean NOT NULL DEFAULT FALSE,
    atualizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (academia_id, recurso)
);

COMMIT;
