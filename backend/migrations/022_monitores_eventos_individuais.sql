BEGIN;

ALTER TABLE public.presencas
    ADD COLUMN monitor_id bigint;

ALTER TABLE public.presencas
    ADD CONSTRAINT presencas_monitor_fk
        FOREIGN KEY (monitor_id)
        REFERENCES public.monitores (id) ON DELETE SET NULL;

CREATE INDEX presencas_monitor_cursor_idx
    ON public.presencas (academia_id, monitor_id, id);

COMMENT ON COLUMN public.presencas.monitor_id IS
    'Tela de aluno que originou o reconhecimento facial; nulo para acessos de leitores físicos.';

COMMIT;
