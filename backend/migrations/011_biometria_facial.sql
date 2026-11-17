BEGIN;

CREATE TABLE public.biometrias_faciais (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    academia_id integer NOT NULL,
    aluno_id integer NOT NULL,
    id_biometria integer NOT NULL,
    template bytea NOT NULL CHECK (octet_length(template) = 512),
    modelo text NOT NULL CHECK (length(modelo) BETWEEN 1 AND 80),
    amostras smallint NOT NULL CHECK (amostras BETWEEN 3 AND 5),
    consentimento_em timestamptz NOT NULL,
    criado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT biometrias_faciais_aluno_key UNIQUE (academia_id, aluno_id),
    CONSTRAINT biometrias_faciais_biometria_key UNIQUE (academia_id, id_biometria),
    CONSTRAINT biometrias_faciais_aluno_fk
        FOREIGN KEY (aluno_id, academia_id)
        REFERENCES public.alunos (id, academia_id) ON DELETE CASCADE
);

COMMENT ON TABLE public.biometrias_faciais IS
    'Templates faciais locais; imagens brutas de cadastro não são armazenadas aqui.';

COMMIT;
