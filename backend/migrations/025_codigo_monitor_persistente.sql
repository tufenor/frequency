BEGIN;
ALTER TABLE public.monitores ADD COLUMN IF NOT EXISTS codigo_compartilhado text;
CREATE UNIQUE INDEX IF NOT EXISTS monitores_codigo_compartilhado_unq ON public.monitores (academia_id) WHERE ativo AND codigo_compartilhado IS NOT NULL;
COMMENT ON COLUMN public.monitores.codigo_compartilhado IS 'Código compartilhado visível ao dono e reutilizado em todas as telas até ser substituído.';
COMMIT;
