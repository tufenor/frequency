-- Índices de leitura para listas e histórico multiacademia.
-- Executar fora de uma transação em produção (CREATE INDEX CONCURRENTLY).
CREATE INDEX CONCURRENTLY IF NOT EXISTS alunos_academia_status_id_idx
    ON public.alunos (academia_id, status, id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS presencas_academia_id_data_idx
    ON public.presencas (academia_id, id DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS pagamentos_academia_status_vencimento_idx
    ON public.pagamentos (academia_id, status, vencimento, id);
