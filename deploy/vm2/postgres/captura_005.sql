-- captura_005.sql — PARES da Conferência de Autenticidade do SEI-RJ (O3.8 rota d, 27/11/2026).
--
-- IDEMPOTENTE. verificador + CRC do rodapé de documentos de OUTRO processo, colhidos do acervo
-- (tools/sei_rj_crc_pares.py). O E2/E3 pela pesquisa pública usa o par para baixar o ORIGINAL do documento que a
-- árvore pública lista SEM link (sei/conferencia_autenticidade). Lido pelos workers (o acervo mora na VM-1).
--   Python: compliance_agent/aplicacao/estagios/arvore.py `schema aplicar`

BEGIN;
SELECT pg_advisory_xact_lock(474751);

SET LOCAL search_path TO :"esquema";

CREATE TABLE IF NOT EXISTS crc_par (
    verificador text PRIMARY KEY,
    crc         text NOT NULL,
    processo    text NOT NULL,
    restrito    boolean NOT NULL DEFAULT false,
    achado_em   text,
    colhido_em  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS crc_par_processo ON crc_par (processo);

INSERT INTO migracoes(versao) VALUES ('captura_005') ON CONFLICT DO NOTHING;
COMMIT;
