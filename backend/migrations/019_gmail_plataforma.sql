BEGIN;

CREATE TABLE IF NOT EXISTS public.gmail_plataforma_conexao (
    id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    usuario_id bigint REFERENCES public.usuarios(id) ON DELETE SET NULL,
    email text NOT NULL,
    refresh_token bytea NOT NULL,
    access_token bytea,
    access_token_expira_em timestamptz,
    ativo boolean NOT NULL DEFAULT true,
    ultima_verificacao timestamptz,
    criado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMIT;
