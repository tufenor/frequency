-- Prevent cross-academy relationships even if a future API route is incorrect.
-- Apply after 001_initial_schema.sql. Take a backup before applying to a
-- database that already contains real data.

BEGIN;

ALTER TABLE public.planos
    ADD CONSTRAINT planos_academia_id_id_key
    UNIQUE (academia_id, id);

ALTER TABLE public.alunos
    ADD CONSTRAINT alunos_academia_id_id_key
    UNIQUE (academia_id, id);

ALTER TABLE public.alunos
    ADD CONSTRAINT alunos_plano_mesma_academia_fkey
    FOREIGN KEY (academia_id, plano_id)
    REFERENCES public.planos (academia_id, id);

ALTER TABLE public.pagamentos
    ADD CONSTRAINT pagamentos_aluno_mesma_academia_fkey
    FOREIGN KEY (academia_id, aluno_id)
    REFERENCES public.alunos (academia_id, id);

ALTER TABLE public.presencas
    ADD CONSTRAINT presencas_aluno_mesma_academia_fkey
    FOREIGN KEY (academia_id, aluno_id)
    REFERENCES public.alunos (academia_id, id);

COMMIT;
