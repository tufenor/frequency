BEGIN;

ALTER TABLE public.leads_prospeccao
    ADD COLUMN IF NOT EXISTS academia_id bigint
    REFERENCES public.academias(id) ON DELETE SET NULL;

DROP INDEX IF EXISTS leads_prospeccao_academia_unico_idx;
CREATE UNIQUE INDEX leads_prospeccao_academia_unico_idx
    ON public.leads_prospeccao (academia_id)
    WHERE academia_id IS NOT NULL AND excluido_em IS NULL;

ALTER TABLE public.leads_prospeccao
    DROP CONSTRAINT IF EXISTS leads_prospeccao_origem_check;
ALTER TABLE public.leads_prospeccao
    ADD CONSTRAINT leads_prospeccao_origem_check CHECK (origem IN (
        'manual', 'csv', 'osm', 'apify', 'integracao_futura', 'cadastro_site'
    ));

COMMENT ON COLUMN public.leads_prospeccao.academia_id IS
    'Academia criada pelo cadastro público que originou este lead.';

COMMIT;
