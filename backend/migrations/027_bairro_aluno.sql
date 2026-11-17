BEGIN;
ALTER TABLE public.alunos
    ADD COLUMN bairro varchar(160);
COMMIT;
