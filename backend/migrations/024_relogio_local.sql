BEGIN;

CREATE TABLE public.relogio_local (
    academia_id integer PRIMARY KEY REFERENCES public.academias(id) ON DELETE CASCADE,
    maior_data date NOT NULL,
    ultima_observacao timestamp without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    relogio_recuou boolean NOT NULL DEFAULT FALSE,
    relogio_recuou_em timestamp without time zone
);

COMMIT;