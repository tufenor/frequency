-- E-mail do aluno para acesso ao app. Migração aditiva: restauração de backup é a reversão.
BEGIN;

ALTER TABLE public.alunos ADD COLUMN IF NOT EXISTS email text;

ALTER TABLE public.alunos
    ADD CONSTRAINT alunos_email_formato_check
    CHECK (email IS NULL OR (email = btrim(email) AND position('@' IN email) > 1));

CREATE UNIQUE INDEX IF NOT EXISTS alunos_email_ativo_uidx
    ON public.alunos (academia_id, lower(email))
    WHERE status = 'ativo' AND email IS NOT NULL;

COMMIT;
