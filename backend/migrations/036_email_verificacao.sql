-- Verificação de e-mail para novos donos de academia.
ALTER TABLE public.usuarios
  ADD COLUMN IF NOT EXISTS email_verificado_em timestamptz,
  ADD COLUMN IF NOT EXISTS email_verificacao_token_hash text,
  ADD COLUMN IF NOT EXISTS email_verificacao_expira_em timestamptz,
  ADD COLUMN IF NOT EXISTS email_verificacao_enviado_em timestamptz;

CREATE INDEX IF NOT EXISTS usuarios_email_verificacao_token_idx
  ON public.usuarios (email_verificacao_token_hash)
  WHERE email_verificacao_token_hash IS NOT NULL;
