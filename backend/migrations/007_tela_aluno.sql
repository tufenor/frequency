BEGIN;

ALTER TABLE public.academias
    ADD COLUMN chave_monitor_hash text,
    ADD COLUMN logo_monitor bytea,
    ADD COLUMN logo_monitor_media_type text,
    ADD CONSTRAINT academias_chave_monitor_hash_check CHECK (
        chave_monitor_hash IS NULL OR chave_monitor_hash ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT academias_logo_monitor_media_type_check CHECK (
        logo_monitor_media_type IS NULL OR logo_monitor_media_type = 'image/jpeg'
    ),
    ADD CONSTRAINT academias_logo_monitor_tamanho_check CHECK (
        logo_monitor IS NULL OR octet_length(logo_monitor) <= 524288
    ),
    ADD CONSTRAINT academias_logo_monitor_pares_check CHECK (
        (logo_monitor IS NULL) = (logo_monitor_media_type IS NULL)
    ),
    ADD CONSTRAINT academias_chave_monitor_hash_key UNIQUE (chave_monitor_hash);

COMMENT ON COLUMN public.academias.chave_monitor_hash IS
    'SHA-256 de uma chave aleatória restrita à tela pública de resultado de acesso.';
COMMENT ON COLUMN public.academias.logo_monitor IS
    'Logo opcional otimizada para a tela de resultado da academia.';

COMMIT;
