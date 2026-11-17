BEGIN;

ALTER TABLE public.academias
    ADD COLUMN idioma text NOT NULL DEFAULT 'pt-BR',
    ADD COLUMN moeda text NOT NULL DEFAULT 'BRL';

UPDATE public.academias
SET idioma = CASE
        WHEN lower(btrim(coalesce(pais, ''))) IN (
            'bolivia', 'bolívia', 'bo', 'estado plurinacional de bolivia',
            'estado plurinacional de bolívia'
        ) THEN 'es-BO'
        ELSE 'pt-BR'
    END,
    moeda = CASE
        WHEN lower(btrim(coalesce(pais, ''))) IN (
            'bolivia', 'bolívia', 'bo', 'estado plurinacional de bolivia',
            'estado plurinacional de bolívia'
        ) THEN 'BOB'
        ELSE 'BRL'
    END;

ALTER TABLE public.academias
    ADD CONSTRAINT academias_idioma_check
        CHECK (idioma IN ('pt-BR', 'es-BO')),
    ADD CONSTRAINT academias_moeda_check
        CHECK (moeda IN ('BRL', 'BOB'));

ALTER TABLE public.planos
    ADD COLUMN moeda text;

UPDATE public.planos p
SET moeda = a.moeda
FROM public.academias a
WHERE a.id = p.academia_id;

ALTER TABLE public.planos
    ALTER COLUMN moeda SET DEFAULT 'BRL',
    ALTER COLUMN moeda SET NOT NULL,
    ADD CONSTRAINT planos_moeda_check CHECK (moeda IN ('BRL', 'BOB'));

ALTER TABLE public.pagamentos
    ADD COLUMN moeda text;

UPDATE public.pagamentos p
SET moeda = a.moeda
FROM public.academias a
WHERE a.id = p.academia_id;

ALTER TABLE public.pagamentos
    ALTER COLUMN moeda SET DEFAULT 'BRL',
    ALTER COLUMN moeda SET NOT NULL,
    ADD CONSTRAINT pagamentos_moeda_check CHECK (moeda IN ('BRL', 'BOB'));

COMMENT ON COLUMN public.academias.idioma IS
    'Idioma padrão da interface para a academia: pt-BR ou es-BO.';
COMMENT ON COLUMN public.academias.moeda IS
    'Moeda padrão de novos planos e cobranças: BRL ou BOB.';
COMMENT ON COLUMN public.planos.moeda IS
    'Moeda usada pelo preço do plano.';
COMMENT ON COLUMN public.pagamentos.moeda IS
    'Moeda congelada para esta cobrança, independente de alteração posterior na academia.';

COMMIT;
