BEGIN;
ALTER TABLE public.prospeccao_regioes ALTER COLUMN latitude DROP NOT NULL;
ALTER TABLE public.prospeccao_regioes ALTER COLUMN longitude DROP NOT NULL;
COMMIT;
