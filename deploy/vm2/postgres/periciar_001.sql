-- periciar_001.sql — LAUDOS v2 do estágio E11 `periciar` (plano mestre v2 §3.2 E11, §6 "Perícia única"; O6.4; ADR-001
-- linha D3: "laudos v2" no PG, escritor = E11).
--
-- VERSIONADO: uma linha por (processo, versão). Chave nova (texto, fatos, eixos, prompt, modelo ou versão do estágio
-- mudaram) ⇒ versão n+1 com `supersedes` = id da anterior, que fica com `vigente = false` (nada é apagado). Mesma chave ⇒
-- nada é gravado (idempotente). `laudo_fatias` guarda a resposta VALIDADA de cada fatia (pela chave da fatia): a
-- retomada depois de "sem cota" não paga de novo o que já leu.
--
-- IDEMPOTENTE (IF NOT EXISTS). O esquema vem da variável `esquema` — padrão `sombra` (nenhuma rota lê) até o ✅ do dono;
-- os testes aplicam o MESMO arquivo num esquema temporário e o apagam no fim.
--   psql:   psql "$JFN_EVIDENCIAS_DSN" -v esquema=sombra -f deploy/vm2/postgres/periciar_001.sql
--   Python: python -m compliance_agent.aplicacao.estagios.periciar schema aplicar
--
-- Dado pessoal: a citação é texto dos autos; o que sai da VM para o modelo vai MASCARADO (dominio/mascara, estrito) e o
-- mapa da máscara nunca é gravado aqui.
BEGIN;
CREATE SCHEMA IF NOT EXISTS :"esquema";
SET search_path TO :"esquema";

CREATE TABLE IF NOT EXISTS laudos_v2(
  id BIGSERIAL PRIMARY KEY,
  processo TEXT NOT NULL,                 -- chave canônica do processo (dominio/processo_id)
  versao INTEGER NOT NULL CHECK (versao >= 1),
  chave TEXT NOT NULL,                    -- sha256(processo|fatias|fatos|eixos|prompt|modelo|versão do estágio)
  supersedes BIGINT REFERENCES laudos_v2(id),
  vigente BOOLEAN NOT NULL DEFAULT true,
  estagio_versao TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  modelo TEXT NOT NULL,
  release_ia TEXT NOT NULL,               -- id do release (régua §3.10); o detalhe está em laudo->'release_ia'
  grau_global SMALLINT CHECK (grau_global IS NULL OR grau_global IN (0, 1, 2)),
  estado_global TEXT NOT NULL,            -- PROPOSTA | INCERTO
  cobertura JSONB NOT NULL,
  pecas_nao_lidas JSONB NOT NULL,         -- [{doc_id, motivo}]
  laudo JSONB NOT NULL,                   -- eixos (grau, estado, pontos, achados ancorados, descartados, lacunas)
  criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (processo, versao),
  UNIQUE (processo, chave));
CREATE UNIQUE INDEX IF NOT EXISTS ux_laudos_v2_vigente ON laudos_v2(processo) WHERE vigente;

CREATE TABLE IF NOT EXISTS laudo_fatias(
  chave TEXT PRIMARY KEY,                 -- sha256(processo|documentos da fatia|fatos|eixos|prompt|modelo|versão)
  processo TEXT NOT NULL,
  laudo_chave TEXT NOT NULL,
  idx INTEGER NOT NULL,
  resposta JSONB NOT NULL,                -- contribuição VALIDADA por eixo (nunca a resposta crua do modelo)
  motor TEXT NOT NULL,
  em TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS ix_laudo_fatias_processo ON laudo_fatias(processo);

COMMIT;
