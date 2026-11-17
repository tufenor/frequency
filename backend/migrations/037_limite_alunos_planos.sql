BEGIN;

ALTER TABLE public.planos_frequency
    ADD COLUMN IF NOT EXISTS max_alunos integer NOT NULL DEFAULT 120;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'planos_frequency_max_alunos_check'
          AND conrelid = 'public.planos_frequency'::regclass
    ) THEN
        ALTER TABLE public.planos_frequency
            ADD CONSTRAINT planos_frequency_max_alunos_check CHECK (max_alunos >= 1);
    END IF;
END $$;

UPDATE public.planos_frequency
SET max_alunos = CASE nivel
    WHEN 'essencial' THEN 120
    WHEN 'profissional' THEN 500
    WHEN 'premium' THEN 2000
    ELSE 120
END
WHERE max_alunos IS NULL OR max_alunos = 120;

COMMENT ON COLUMN public.planos_frequency.max_alunos IS
    'Quantidade máxima de alunos ativos incluídos na assinatura.';

COMMIT;
