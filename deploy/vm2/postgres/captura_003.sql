-- captura_003.sql — RECAPTURA PEDIDA (27/11/2026; regra única #58 do mapa O1.2, ex-`sei_integra_fila`).
--
-- IDEMPOTENTE. O caminho antigo do CACHE (`sei_arquivar_do_cache`, origem "cache CDP") trazia só o TEXTO: relatório
-- fotográfico chegava sem foto e o processo "tinha texto", então a íntegra (a única que baixa as fotos) nunca era
-- pedida. Medido em 27/11: 175 processos / 252 relatórios fotográficos assim. A versão LEGADA (origem sei_arquivo)
-- de um documento listado aqui não conta como captura: o documento volta a faltar e o E3 o baixa pela íntegra.
-- Auto-limitante: a versão nova do E3 tem origem sei:e3 e passa a valer.
--   Python: compliance_agent/aplicacao/estagios/arvore.py `schema aplicar` · carga: tools/recaptura_fotos.py

BEGIN;
SELECT pg_advisory_xact_lock(474751);

SET LOCAL search_path TO :"esquema";

CREATE TABLE IF NOT EXISTS recaptura_pedida (
    processo   text NOT NULL,
    doc_id     text NOT NULL,
    motivo     text NOT NULL,
    pedida_em  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (processo, doc_id)
);

INSERT INTO migracoes(versao) VALUES ('captura_003') ON CONFLICT DO NOTHING;
COMMIT;
