-- dominio_001.sql — tabela de ELEGIBILIDADE do estágio E9 (plano mestre v2 §3.10 invariante 3, §4 item 4; O4.7).
--
-- ⚖️ SOMBRA: nenhum detector lê isto até o ✅ do dono no lote jurídico (O4.10). Escritor ÚNICO: o estágio E9
-- `elegibilidade` (compliance_agent/aplicacao/estagios/elegibilidade.py) — ADR-001 linha D9.
--
-- IDEMPOTENTE (IF NOT EXISTS / CREATE OR REPLACE / ON CONFLICT). O nome do schema vem da variável `esquema` —
-- produção é `dominio`; os testes aplicam o MESMO arquivo num esquema temporário e o apagam no fim.
--   psql:   psql "$JFN_EVIDENCIAS_DSN" -v esquema=dominio -f deploy/vm2/postgres/dominio_001.sql
--   Python: python -m compliance_agent.aplicacao.estagios.elegibilidade schema aplicar
--
-- Sem dado pessoal: o credor pessoa física NÃO é gravado (só a classe `PF`); do credor PJ fica a raiz do CNPJ
-- (8 dígitos, dado público do cadastro da Receita).

BEGIN;
SELECT pg_advisory_xact_lock(474749);

CREATE SCHEMA IF NOT EXISTS :"esquema";
SET LOCAL search_path TO :"esquema";

CREATE TABLE IF NOT EXISTS migracoes(versao text PRIMARY KEY, aplicada_em timestamptz NOT NULL DEFAULT now());

-- Textos de "fonte da decisão" (dispositivo + regra). São poucas centenas, repetidos em milhões de linhas: a linha
-- guarda o id (md5 do texto em bigint — o mesmo texto dá o mesmo id em qualquer máquina, sem sequência).
CREATE TABLE IF NOT EXISTS elegibilidade_fonte(
  fonte_id  bigint PRIMARY KEY,
  texto     text   NOT NULL
);

-- UMA linha por item (OB ou contratação) na chave natural; `exiges` = exigência → código do veredito:
--   'E'           elegível
--   'I:<MOTIVO>'  inelegível (TRANSFERENCIA, SERVICO_CONTINUO, DEA, ENTE_PUBLICO, FOLHA_BENEFICIO, …)
--   '?:<MOTIVO>'  indeterminado (SEM_NE, REGIME_INDETERMINADO, TFE_SEM_PAR_SIAFE, …) — nunca lido como elegível
CREATE TABLE IF NOT EXISTS elegibilidade(
  unidade                 text        NOT NULL,   -- ob_siafe · ob_tfe · contrato_tcerj · compra_direta_tcerj · contrato_siga · contrato_pcrj · contrato_rules
  chave                   text        NOT NULL,   -- OB: 'ug|numero_ob|exercicio'; contratação: chave natural da fonte
  ug                      text,
  numero_ob               text,
  exercicio               integer,
  contrato_id             text,                   -- dominio.contrato_id quando resolvível ('orgao|N/AAAA|ano')
  data_fato               date,
  valor                   numeric(18, 2),
  paga                    boolean,                -- OB: predicado canônico _ob_paga (invariante 1); contratação: NULL
  credor_classe           text,                   -- ENTE_PUBLICO · UG_PROPRIA · OS_OSC · PJ_PRIVADA · PJ_SEM_CADASTRO · PF · INSCRICAO_GENERICA · SEM_DOC
  credor_raiz             text,                   -- 8 dígitos (só PJ)
  natureza_juridica       text,
  natureza_despesa        text,                   -- C.G.MM.EE da NE ligada à OB (cadeia OB → NL → NE)
  vinculo_contrato        boolean,
  natureza_pagamento      text,
  nao_e_contratacao_nova  boolean,
  credor_e_fornecedor     boolean,
  natureza_fonte          bigint,
  origem_exercicio        text,
  exercicio_origem        integer,
  origem_fonte            bigint,
  regime                  text,
  regime_fonte            bigint,
  dispensa_valor          boolean,
  teto                    numeric(18, 2),
  teto_fonte              bigint,
  motivo_legado           bigint,                 -- o que a régua de HOJE (classificador_credor) diz: só comparação
  exiges                  jsonb       NOT NULL,
  versao                  text        NOT NULL,
  entrada_hash            text        NOT NULL,   -- hash do que foi decidido: reexecução igual = 0 linha alterada
  calculado_em            timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (unidade, chave)
);
CREATE INDEX IF NOT EXISTS elegibilidade_escopo_ix ON elegibilidade (unidade, exercicio, versao);

-- detector → (unidade, exigência): o registro do que cada detector precisa para ler um item (sincronizado do
-- DETECTORES do módulo a cada materialização; o conjunto vem de config/qualidade_detectores.yaml).
CREATE TABLE IF NOT EXISTS elegibilidade_detector(
  detector    text NOT NULL,
  unidade     text NOT NULL,
  exige       text NOT NULL,
  janela_de   date,
  janela_ate  date,
  versao      text NOT NULL,
  PRIMARY KEY (detector, unidade)
);

-- `elegivel_<detector>` + motivo, linha a linha (o que o E10 vai ler depois do ✅): NULL = indeterminado.
CREATE OR REPLACE VIEW v_elegibilidade_detector AS
SELECT d.detector, e.unidade, e.chave, e.exercicio, e.data_fato, e.valor,
       CASE left(e.exiges ->> d.exige, 1) WHEN 'E' THEN true WHEN 'I' THEN false END AS elegivel,
       CASE WHEN e.exiges ->> d.exige = 'E' THEN NULL ELSE split_part(e.exiges ->> d.exige, ':', 2) END AS motivo,
       d.exige, e.versao
  FROM elegibilidade_detector d
  JOIN elegibilidade e ON e.unidade = d.unidade;

INSERT INTO migracoes(versao) VALUES ('dominio_001') ON CONFLICT DO NOTHING;
COMMIT;
