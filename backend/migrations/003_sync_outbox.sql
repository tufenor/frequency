-- Stable IDs and transactional outbox for the proposed local-first sync.
-- Apply after 001_initial_schema.sql and 002_tenant_integrity.sql.
-- PostgreSQL 13+ provides gen_random_uuid() in core.
-- Do not apply to production until a tested backup and staging migration exist.

DO $$
BEGIN
    IF current_setting('server_version_num')::integer < 130000 THEN
        RAISE EXCEPTION 'Frequency sync migration requires PostgreSQL 13 or newer';
    END IF;
END
$$;

BEGIN;

ALTER TABLE public.academias
    ADD COLUMN sync_id uuid NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE public.academias
    ADD CONSTRAINT academias_sync_id_key UNIQUE (sync_id);

ALTER TABLE public.planos
    ADD COLUMN sync_id uuid NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE public.planos
    ADD CONSTRAINT planos_sync_id_key UNIQUE (sync_id);

ALTER TABLE public.alunos
    ADD COLUMN sync_id uuid NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE public.alunos
    ADD CONSTRAINT alunos_sync_id_key UNIQUE (sync_id);

ALTER TABLE public.pagamentos
    ADD COLUMN sync_id uuid NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE public.pagamentos
    ADD CONSTRAINT pagamentos_sync_id_key UNIQUE (sync_id);

ALTER TABLE public.presencas
    ADD COLUMN sync_id uuid NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE public.presencas
    ADD CONSTRAINT presencas_sync_id_key UNIQUE (sync_id);

CREATE TABLE public.sync_revision_counters (
    academia_sync_id uuid PRIMARY KEY
        REFERENCES public.academias (sync_id),
    last_revision bigint NOT NULL DEFAULT 0
        CHECK (last_revision >= 0)
);

INSERT INTO public.sync_revision_counters (academia_sync_id)
SELECT sync_id FROM public.academias;

CREATE TABLE public.sync_outbox (
    event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    academia_sync_id uuid NOT NULL
        REFERENCES public.academias (sync_id),
    revision bigint NOT NULL CHECK (revision > 0),
    entity_type text NOT NULL
        CHECK (entity_type IN ('plano', 'aluno', 'pagamento', 'presenca')),
    entity_sync_id uuid NOT NULL,
    operation text NOT NULL DEFAULT 'upsert'
        CHECK (operation IN ('upsert', 'delete')),
    schema_version smallint NOT NULL DEFAULT 1
        CHECK (schema_version > 0),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    attempt_count integer NOT NULL DEFAULT 0
        CHECK (attempt_count >= 0),
    next_attempt_at timestamptz NOT NULL DEFAULT now(),
    lease_until timestamptz,
    delivered_at timestamptz,
    last_error_code text,
    CONSTRAINT sync_outbox_academia_revision_key
        UNIQUE (academia_sync_id, revision)
);

CREATE INDEX sync_outbox_pending_idx
    ON public.sync_outbox (academia_sync_id, next_attempt_at, revision)
    WHERE delivered_at IS NULL;

CREATE TABLE public.sync_inbox (
    event_id uuid PRIMARY KEY,
    academia_id integer NOT NULL REFERENCES public.academias (id),
    source_academia_sync_id uuid NOT NULL,
    revision bigint NOT NULL CHECK (revision > 0),
    entity_type text NOT NULL
        CHECK (entity_type IN ('plano', 'aluno', 'pagamento', 'presenca')),
    entity_sync_id uuid NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT sync_inbox_source_revision_key
        UNIQUE (source_academia_sync_id, revision)
);

CREATE TABLE public.sync_credentials (
    source_academia_sync_id uuid PRIMARY KEY,
    academia_id integer NOT NULL UNIQUE REFERENCES public.academias (id),
    token_hash text NOT NULL UNIQUE
        CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    rotated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.sync_receive_state (
    source_academia_sync_id uuid PRIMARY KEY,
    academia_id integer NOT NULL UNIQUE REFERENCES public.academias (id),
    last_revision bigint NOT NULL DEFAULT 0
        CHECK (last_revision >= 0),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.sync_snapshot_runs (
    academia_sync_id uuid PRIMARY KEY,
    event_count bigint NOT NULL CHECK (event_count >= 0),
    generated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.sync_outbox IS
    'Locally committed, privacy-minimized events awaiting remote delivery.';
COMMENT ON TABLE public.sync_inbox IS
    'Event IDs already applied by a receiving replica, for idempotent delivery.';
COMMENT ON TABLE public.sync_credentials IS
    'One high-entropy inbound sync credential per cloud academy; only its SHA-256 digest is stored.';
COMMENT ON TABLE public.sync_receive_state IS
    'Last atomically applied source revision for each local academy replica.';
COMMENT ON TABLE public.sync_revision_counters IS
    'Per-academy transaction-locked revision counter that preserves committed event order.';
COMMENT ON TABLE public.sync_snapshot_runs IS
    'One-time record that the existing local records were queued as a baseline snapshot.';
COMMENT ON COLUMN public.sync_outbox.payload IS
    'Projection payload. Never include passwords, reader keys, biometric IDs, or biometric templates.';

COMMIT;
