-- captura_002.sql — a VERSÃO guarda a identidade com que foi capturada (item O3.5, lacunas de identidade do E2).
--
-- IDEMPOTENTE (IF NOT EXISTS / ON CONFLICT). Pré-requisito: captura_001.sql no esquema. Só ACRESCENTA colunas
-- (nulas no legado O3.1, que não sabia o id_documento):
--   versoes.id_documento  o id do SEI do documento NO INSTANTE da captura (E3; da url do nó);
--   versoes.titulo        o título NO INSTANTE da captura.
-- O E2 compara a árvore viva com esta identidade (e não com `documentos`, que ele mesmo regrava): id_documento ou
-- título diferente do capturado ⇒ o documento volta a faltar ⇒ `documento_novo` ⇒ o E3 o rebaixa (retificado).
--   Python: compliance_agent/aplicacao/estagios/arvore.py `schema aplicar`

BEGIN;
SELECT pg_advisory_xact_lock(474751);

SET LOCAL search_path TO :"esquema";

ALTER TABLE versoes ADD COLUMN IF NOT EXISTS id_documento text;
ALTER TABLE versoes ADD COLUMN IF NOT EXISTS titulo text;

INSERT INTO migracoes(versao) VALUES ('captura_002') ON CONFLICT DO NOTHING;
COMMIT;
