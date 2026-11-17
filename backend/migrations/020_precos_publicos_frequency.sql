BEGIN;

ALTER TABLE public.configuracao_frequency
    ADD COLUMN public_pricing jsonb NOT NULL DEFAULT '{"principal":"BOB","percentual":35,"modo":{"BRL":"conversao","USD":"conversao"},"manual":{"BRL":{},"USD":{}}}'::jsonb;

COMMIT;
