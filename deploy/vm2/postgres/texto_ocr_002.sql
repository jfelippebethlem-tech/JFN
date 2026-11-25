-- texto_ocr_002.sql — a chave de `transformacao` ganha a VERSÃO DO ESTÁGIO (O8.5, frente A; decisão do coordenador).
--
-- Por quê: a transformação é HISTÓRICO. Reprocessar o mesmo binário com uma versão nova da lógica do estágio (E5
-- e5-2 → e5-3: a bbox do Tesseract passou a sair da mesma imagem do texto) e o MESMO motor@versão e texto dava
-- conflito em `transformacao_unica` ⇒ DO NOTHING ⇒ ficava a linha velha com o `lateral_sha` velho ⇒ a conferência do
-- efeito falhava para sempre. Agora a versão do estágio entra na chave: o reprocessamento grava UMA LINHA NOVA e a
-- conferência compara com a linha da MESMA versão. Leitura única segue por (sha256, estágio, versão).
--
-- IDEMPOTENTE e ADITIVA: coluna nova (NULL nas linhas existentes = "antes da coluna"); a restrição é recriada com a
-- coluna a mais SÓ se ainda não a tem. Chave mais larga ⇒ toda linha existente continua única: nenhuma linha é
-- apagada nem alterada. Quem não informa a versão grava NULL e se comporta como antes (E4 e E5 informam).
--   Python: compliance_agent/aplicacao/estagios/texto.py `aplicar_schema` (depois do texto_ocr_001)
BEGIN;
SELECT pg_advisory_xact_lock(474752);

SET LOCAL search_path TO :"esquema";

CREATE TABLE IF NOT EXISTS migracoes(versao text PRIMARY KEY, aplicada_em timestamptz NOT NULL DEFAULT now());

ALTER TABLE transformacao ADD COLUMN IF NOT EXISTS versao_estagio text;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conname = 'transformacao_unica'
                 AND c.conrelid = 'transformacao'::regclass
                 AND pg_get_constraintdef(c.oid) LIKE '%versao_estagio%') THEN
    ALTER TABLE transformacao DROP CONSTRAINT IF EXISTS transformacao_unica;
    ALTER TABLE transformacao ADD CONSTRAINT transformacao_unica UNIQUE NULLS NOT DISTINCT
      (processo, doc_id, tipo, entrada_sha, saida_sha, motor, versao_motor, versao_estagio);
  END IF;
END $$;

INSERT INTO migracoes(versao) VALUES ('texto_ocr_002') ON CONFLICT DO NOTHING;
COMMIT;
