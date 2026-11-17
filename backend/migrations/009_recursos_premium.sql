BEGIN;
ALTER TABLE public.planos_frequency
    ADD COLUMN nivel text NOT NULL DEFAULT 'essencial',
    ADD COLUMN cameras boolean NOT NULL DEFAULT false,
    ADD COLUMN spotify boolean NOT NULL DEFAULT false,
    ADD CONSTRAINT planos_frequency_nivel_check CHECK (nivel IN ('essencial', 'profissional', 'premium')),
    ADD CONSTRAINT planos_frequency_recursos_check CHECK (nivel = 'premium' OR (NOT cameras AND NOT spotify));
COMMENT ON COLUMN public.planos_frequency.nivel IS 'Categoria comercial explícita; não inferida do nome ou da moeda.';
COMMIT;
