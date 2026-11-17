BEGIN;

CREATE TABLE IF NOT EXISTS public.google_identities (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuario_id integer NOT NULL REFERENCES public.usuarios(id) ON DELETE CASCADE,
    google_sub text NOT NULL UNIQUE,
    email text NOT NULL,
    criado_em timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT google_identities_usuario_key UNIQUE (usuario_id)
);

CREATE INDEX IF NOT EXISTS google_identities_email_idx
    ON public.google_identities (lower(email));

COMMIT;
