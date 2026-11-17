BEGIN;

CREATE TABLE IF NOT EXISTS public.site_visitas_diarias (
    dia date PRIMARY KEY,
    visitas bigint NOT NULL DEFAULT 0 CHECK (visitas >= 0),
    atualizado_em timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMIT;
