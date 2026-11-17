BEGIN;

ALTER TABLE public.academias
    ADD COLUMN IF NOT EXISTS trial_inicio date,
    ADD COLUMN IF NOT EXISTS trial_fim date;

CREATE INDEX IF NOT EXISTS academias_trial_fim_idx
    ON public.academias (trial_fim)
    WHERE trial_fim IS NOT NULL;

COMMENT ON COLUMN public.academias.trial_inicio IS
    'Data de início da experiência gratuita criada no cadastro público.';

COMMENT ON COLUMN public.academias.trial_fim IS
    'Primeiro dia em que a experiência deixa de permitir acesso; a experiência dura sete dias completos.';

COMMIT;
