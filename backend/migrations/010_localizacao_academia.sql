BEGIN;
ALTER TABLE public.academias
    ADD COLUMN cidade varchar(120) NOT NULL DEFAULT '',
    ADD COLUMN estado varchar(120) NOT NULL DEFAULT '',
    ADD COLUMN endereco varchar(300) NOT NULL DEFAULT '',
    ADD COLUMN codigo_postal varchar(30) NOT NULL DEFAULT '';
COMMIT;
