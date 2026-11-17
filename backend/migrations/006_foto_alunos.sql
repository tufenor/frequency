BEGIN;

ALTER TABLE alunos
    ADD COLUMN foto_perfil BYTEA,
    ADD COLUMN foto_media_type TEXT,
    ADD CONSTRAINT alunos_foto_media_type_check CHECK (
        (foto_perfil IS NULL AND foto_media_type IS NULL)
        OR (foto_perfil IS NOT NULL AND foto_media_type = 'image/jpeg')
    );

COMMIT;
