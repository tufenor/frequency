BEGIN;

INSERT INTO public.planos_frequency
    (nome, descricao, valor, moeda, duracao_dias, nivel, cameras, youtube)
VALUES
    ('Essencial', 'Gestão essencial da academia.', 250.00, 'BOB', 30, 'essencial', FALSE, FALSE),
    ('Profissional', 'Gestão completa para academias em crescimento.', 350.00, 'BOB', 30, 'profissional', FALSE, FALSE),
    ('Premium', 'Gestão completa com recursos premium.', 500.00, 'BOB', 30, 'premium', TRUE, TRUE)
ON CONFLICT (nome) DO UPDATE
SET ativo = TRUE;

COMMIT;
