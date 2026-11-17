BEGIN;

ALTER TABLE public.academias
    ADD COLUMN qr_pagamento bytea,
    ADD COLUMN qr_media_type text,
    ADD CONSTRAINT academias_qr_media_type_check
        CHECK (qr_media_type IS NULL OR qr_media_type IN (
            'image/png', 'image/jpeg', 'image/webp'
        )),
    ADD CONSTRAINT academias_qr_imagem_tamanho_check
        CHECK (qr_pagamento IS NULL OR octet_length(qr_pagamento) <= 2097152),
    ADD CONSTRAINT academias_qr_pares_check
        CHECK ((qr_pagamento IS NULL) = (qr_media_type IS NULL));

COMMENT ON COLUMN public.academias.qr_pagamento IS
    'Imagem estática do QR informada pelo dono da academia; não comprova liquidação de pagamento.';

COMMIT;
