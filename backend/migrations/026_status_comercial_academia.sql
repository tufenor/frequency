BEGIN;

ALTER TABLE public.academias
    ADD COLUMN IF NOT EXISTS status_comercial text NOT NULL DEFAULT 'ativa';

ALTER TABLE public.academias
    DROP CONSTRAINT IF EXISTS academias_status_comercial_check;

ALTER TABLE public.academias
    ADD CONSTRAINT academias_status_comercial_check
    CHECK (status_comercial IN ('ativa', 'aguardando_plano', 'bloqueada'));

COMMENT ON COLUMN public.academias.status_comercial IS
    'Estado comercial explícito; separa academias legadas ativas de cadastros que aguardam plano.';

COMMIT;
