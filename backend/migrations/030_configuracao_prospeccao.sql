BEGIN;

CREATE TABLE IF NOT EXISTS public.configuracao_prospeccao (
    id boolean PRIMARY KEY DEFAULT TRUE CHECK (id),
    whatsapp_template text NOT NULL DEFAULT 'Hola {academia} de {cidade}, quería presentarte Frequency. ¿Te gustaría ver una demostración breve?',
    email_assunto_template text NOT NULL DEFAULT 'Frequency para la gestión de tu gimnasio',
    email_corpo_template text NOT NULL DEFAULT 'Hola, ¿qué tal? Vi {academia} en {cidade} y quería presentarte Frequency.\n\nEs una plataforma para gestionar alumnos, pagos y accesos de tu gimnasio. ¿Te gustaría ver una demostración breve?\n\nSi prefieres no recibir más información, responde a este correo indicando que no deseas continuar.',
    imagem bytea,
    imagem_media_type text,
    atualizado_em timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_por integer REFERENCES public.usuarios(id) ON DELETE SET NULL
);

COMMENT ON TABLE public.configuracao_prospeccao IS
    'Configuração global da mensagem pré-preenchida no WhatsApp; não envia mensagens.';

COMMIT;
