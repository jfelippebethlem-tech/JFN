-- Fase 4 do segundo cérebro (19/11/2026) — só ACRESCENTA tabela, coluna e índice. Idempotente.
-- Reverter: DROP TABLE entidade_mencao, entidade; DROP INDEX mem_chave_ativa; as colunas novas de memories podem ficar.
CREATE TABLE IF NOT EXISTS entidade(
  tipo text NOT NULL, chave text NOT NULL, nome text, cor text, PRIMARY KEY (tipo, chave));
CREATE TABLE IF NOT EXISTS entidade_mencao(
  tipo text NOT NULL, chave text NOT NULL,
  origem_ref text NOT NULL,            -- 'nota:<caminho>' (vault) | 'nota:<fonte>:<caminho>' | 'mem:<id>'
  papel text NOT NULL DEFAULT 'citada', -- 'caso' = nota de ~/vault/casos; o resto é só citação
  trecho text,                          -- onde o identificador aparece (prova da menção)
  registrado_em timestamptz DEFAULT now(),
  PRIMARY KEY (tipo, chave, origem_ref));
CREATE INDEX IF NOT EXISTS em_origem ON entidade_mencao(origem_ref);
-- fato em duas linhas de tempo: quando VALEU (valeu_de/valeu_ate) × quando o cérebro o TEVE (created_at/substituida_em)
ALTER TABLE memories ADD COLUMN IF NOT EXISTS chave text;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS valeu_de timestamptz;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS valeu_ate timestamptz;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS substituida_em timestamptz;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS prova_doc text;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS prova_trecho text;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS prova_hash text;
UPDATE memories SET substituida_em = valid_to WHERE substituida_em IS NULL AND valid_to IS NOT NULL;
-- uma só versão ATIVA por chave (o equivalente, no PG 16, à exclusão por período de registro)
CREATE UNIQUE INDEX IF NOT EXISTS mem_chave_ativa ON memories(chave) WHERE status='ativa' AND chave IS NOT NULL;
