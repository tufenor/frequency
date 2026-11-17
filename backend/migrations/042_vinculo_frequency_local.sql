-- One-time pairing codes for connecting a local installation to its cloud mirror.
-- The plaintext code is never persisted; only its SHA-256 digest is stored.

BEGIN;

CREATE TABLE public.sync_pairing_codes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    academia_id integer NOT NULL REFERENCES public.academias(id) ON DELETE CASCADE,
    code_hash text NOT NULL UNIQUE CHECK (code_hash ~ '^[0-9a-f]{64}$'),
    expires_at timestamptz NOT NULL,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0 AND attempts <= 10),
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX sync_pairing_codes_active_idx
    ON public.sync_pairing_codes (academia_id, expires_at)
    WHERE used_at IS NULL;

COMMENT ON TABLE public.sync_pairing_codes IS
    'Short-lived one-time codes used to pair a local Frequency installation with its cloud academy.';
COMMENT ON COLUMN public.sync_pairing_codes.code_hash IS
    'SHA-256 digest of the one-time code; plaintext is shown only to the authenticated owner.';

COMMIT;
