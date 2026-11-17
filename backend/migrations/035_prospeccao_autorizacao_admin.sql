ALTER TABLE public.leads_prospeccao
    ADD COLUMN IF NOT EXISTS whatsapp_autorizacao_admin_em timestamp with time zone,
    ADD COLUMN IF NOT EXISTS whatsapp_autorizacao_admin_por integer REFERENCES public.usuarios(id);
