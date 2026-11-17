-- Ficha complementar do aluno (contato de emergência, endereço, saúde/objetivo, medidas). Migração aditiva.
BEGIN;

CREATE TABLE public.aluno_ficha (
    aluno_id integer PRIMARY KEY REFERENCES public.alunos(id) ON DELETE CASCADE,
    contato_emergencia_nome text,
    contato_emergencia_telefone text,
    endereco_rua text,
    endereco_numero text,
    endereco_cidade text,
    objetivo text,
    restricoes_saude text,
    atestado_medico boolean NOT NULL DEFAULT FALSE,
    sexo text CHECK (sexo IS NULL OR sexo IN ('feminino', 'masculino', 'outro', 'nao_informar')),
    peso_kg numeric(5,1) CHECK (peso_kg IS NULL OR (peso_kg >= 20 AND peso_kg <= 400)),
    altura_cm integer CHECK (altura_cm IS NULL OR (altura_cm >= 80 AND altura_cm <= 250)),
    atualizado_em timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMIT;
