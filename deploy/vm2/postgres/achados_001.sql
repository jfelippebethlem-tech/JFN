-- achados_001.sql — contrato único do achado no PG jfn_evidencias (plano mestre v2 O5.2; doc 2 §17.2 e §35.1).
--
-- IDEMPOTENTE: rodar de novo não muda nada (IF NOT EXISTS / ON CONFLICT).
-- O nome do schema vem da variável `esquema` (o MESMO arquivo serve a produção e ao esquema temporário dos testes):
--   psql:   psql "$JFN_EVIDENCIAS_DSN" -v esquema=achados -f deploy/vm2/postgres/achados_001.sql
--   Python: compliance_agent.adaptadores.achados.aplicar_schema (troca :"esquema" com fluxo.schema.renderizar)
--
-- Três camadas que não se misturam (doc 2 §17.2: "não misturar essas três camadas em uma única tabela de alertas"):
--   execucao_regra   resultado técnico reproduzível: regra + versão + sha256 das entradas + resultado
--   achado           hipótese de auditoria nos planos observação / inferência / qualificação (doc 2 §35.1), com o
--                    estado de saída de §3.10 (AUSENTE, INDISPONIVEL, INCERTO, INDICIO, CONCLUSAO_REVISADA, ABSTEVE)
--   achado_evidencia os fatos que sustentam, contradizem ou contextualizam (papel). A tabela `fato` do doc 2 §17.1
--                    ainda não existe: o fato vai inteiro em `fato` (jsonb); `fato_id` fica para quando existir.
--   decisao_humana   o que a instituição decide — tabela própria, com autor e justificativa obrigatórios.
-- Diferenças conscientes do DDL do doc 2: `processo` é texto e opcional (a identidade canônica é texto em
-- evidencias.processos, e há regras sem processo — folha, cadastro); `origem` diz de onde a execução foi lida
-- (`alertas:<id>`, `achado_certame:…`), e a unicidade (origem, regra, versão, entradas) torna a carga idempotente.

BEGIN;
SELECT pg_advisory_xact_lock(474750);        -- dois aplicadores ao mesmo tempo não disputam o DDL

SET LOCAL search_path TO :"esquema";

CREATE TABLE IF NOT EXISTS migracoes(versao text PRIMARY KEY, aplicada_em timestamptz NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS execucao_regra(
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  regra_id       text        NOT NULL,                  -- id em config/qualidade_detectores.yaml
  regra_versao   text        NOT NULL,
  processo       text,
  entradas_hash  char(64)    NOT NULL CHECK (entradas_hash ~ '^[0-9a-f]{64}$'),
  resultado      jsonb       NOT NULL,
  origem         text        NOT NULL,
  executado_em   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT execucao_regra_unica UNIQUE (origem, regra_id, regra_versao, entradas_hash)
);
CREATE INDEX IF NOT EXISTS execucao_regra_regra_ix ON execucao_regra (regra_id);
CREATE INDEX IF NOT EXISTS execucao_regra_processo_ix ON execucao_regra (processo);

CREATE TABLE IF NOT EXISTS achado(
  id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  execucao_regra_id      bigint NOT NULL UNIQUE REFERENCES execucao_regra(id),
  status                 text   NOT NULL CHECK (status IN ('triagem','em_revisao','confirmado','refutado','arquivado')),
  estado                 text   NOT NULL CHECK (estado IN ('AUSENTE','INDISPONIVEL','INCERTO','INDICIO',
                                                            'CONCLUSAO_REVISADA','ABSTEVE')),
  motivo_estado          text   NOT NULL DEFAULT '',
  observacao             text   NOT NULL,
  inferencia             text   NOT NULL,
  qualificacao           text,
  hipotese               text   NOT NULL,
  hipoteses_alternativas jsonb  NOT NULL DEFAULT '[]'::jsonb,
  criado_em              timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT achado_absteve_com_motivo CHECK (estado <> 'ABSTEVE' OR btrim(motivo_estado) <> ''),
  CONSTRAINT achado_so_pessoa_conclui CHECK ((estado = 'CONCLUSAO_REVISADA') = (status IN ('confirmado','refutado')))
);
CREATE INDEX IF NOT EXISTS achado_status_ix ON achado (status, estado);

CREATE TABLE IF NOT EXISTS achado_evidencia(
  id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  achado_id bigint  NOT NULL REFERENCES achado(id) ON DELETE CASCADE,
  ordem     integer NOT NULL,
  papel     text    NOT NULL CHECK (papel IN ('suporte','contradicao','contexto')),
  fato      jsonb   NOT NULL,
  fato_id   bigint,                                     -- doc 2 §17.1 `fato(id)` quando a tabela existir
  CONSTRAINT achado_evidencia_unica UNIQUE (achado_id, ordem)
);

CREATE TABLE IF NOT EXISTS decisao_humana(
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  achado_id      bigint      NOT NULL REFERENCES achado(id),
  autor          text        NOT NULL CHECK (btrim(autor) <> ''),
  status         text        NOT NULL CHECK (status IN ('em_revisao','confirmado','refutado','arquivado')),
  justificativa  text        NOT NULL CHECK (btrim(justificativa) <> ''),
  encaminhamento text,
  decidido_em    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS decisao_humana_achado_ix ON decisao_humana (achado_id, decidido_em);

INSERT INTO migracoes(versao) VALUES ('achados_001') ON CONFLICT DO NOTHING;
COMMIT;
