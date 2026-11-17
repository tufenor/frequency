BEGIN;
ALTER TABLE public.gmail_plataforma_conexao DROP CONSTRAINT IF EXISTS gmail_plataforma_conexao_id_check;
ALTER TABLE public.gmail_plataforma_conexao ADD CONSTRAINT gmail_plataforma_conexao_id_check CHECK (id IN (1,2));
COMMIT;
