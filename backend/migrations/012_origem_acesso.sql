BEGIN;

ALTER TABLE public.presencas
    ADD COLUMN leitor_id integer,
    ADD COLUMN metodo_identificacao text NOT NULL DEFAULT 'biometria',
    ADD COLUMN confianca numeric(5,4);

ALTER TABLE public.leitores
    ADD CONSTRAINT leitores_id_academia_id_key UNIQUE (id, academia_id);

ALTER TABLE public.presencas
    ADD CONSTRAINT presencas_leitor_fk
        FOREIGN KEY (leitor_id, academia_id)
        REFERENCES public.leitores (id, academia_id) ON DELETE SET NULL (leitor_id),
    ADD CONSTRAINT presencas_metodo_identificacao_check
        CHECK (metodo_identificacao IN ('biometria', 'facial', 'manual', 'sincronizado')),
    ADD CONSTRAINT presencas_confianca_check
        CHECK (confianca IS NULL OR (confianca >= 0 AND confianca <= 1));

CREATE INDEX presencas_cooldown_facial_idx
    ON public.presencas (academia_id, aluno_id, leitor_id, data_hora DESC)
    WHERE metodo_identificacao = 'facial';

COMMIT;
