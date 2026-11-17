BEGIN;

ALTER TABLE public.planos_frequency
    DROP CONSTRAINT planos_frequency_recursos_check;

ALTER TABLE public.planos_frequency
    RENAME COLUMN spotify TO youtube;

ALTER TABLE public.planos_frequency
    ADD CONSTRAINT planos_frequency_recursos_check
        CHECK (nivel = 'premium' OR (NOT cameras AND NOT youtube));

COMMIT;
