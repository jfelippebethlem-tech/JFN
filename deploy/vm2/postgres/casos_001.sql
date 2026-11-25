-- casos_001.sql — CASOS (E14), CONTESTAÇÃO, TRILHA DE ACESSO e ENTREGAS (E16) no PG jfn_evidencias
-- (plano mestre v2 §3.2 E14/E16, §3.11 "RBAC e trilha", §8 "Contestação" e "Entrega honesta"; O7.4/O7.5).
--
-- Depende de achados_001.sql no MESMO esquema (achado, decisao_humana): `caso.aplicar_schema` aplica os dois, nesta
-- ordem. Padrão `sombra` (nenhuma rota do painel lê) até o ✅ do dono; os testes aplicam o MESMO arquivo num esquema
-- temporário e o apagam no fim.
--   psql:   psql "$JFN_EVIDENCIAS_DSN" -v esquema=sombra -f deploy/vm2/postgres/casos_001.sql
--   Python: python -m compliance_agent.aplicacao.estagios.caso schema aplicar
--
-- NADA SE APAGA (regra do plano: a contestação "revisa os derivados; nunca apaga"):
--   · acesso_log, contestacao, contestacao_desfecho, entrega e caso_achado são APPEND-ONLY — UPDATE, DELETE e
--     TRUNCATE levantam exceção no próprio banco (gatilho), não só no código;
--   · caso_versao só aceita UMA mudança: `vigente` true → false quando a versão n+1 a substitui (`supersedes`);
--   · a decisão que a contestação provoca vai a `decisao_humana` (achados_001, só INSERT pelo código), nunca altera
--     o achado da regra.
-- Revisor ≠ autor da contestação: conferido aqui por gatilho (CHECK não enxerga a outra tabela).
-- Dado pessoal: o anexo é guardado como veio (bytea) com o sha256; a classe do caso (§3.11) decide quem abre.
BEGIN;
SELECT pg_advisory_xact_lock(474751);        -- dois aplicadores ao mesmo tempo não disputam o DDL
CREATE SCHEMA IF NOT EXISTS :"esquema";
SET LOCAL search_path TO :"esquema";

CREATE TABLE IF NOT EXISTS migracoes(versao text PRIMARY KEY, aplicada_em timestamptz NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS caso(
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  chave      text NOT NULL UNIQUE,                    -- 'processo:UUUUUU/NNNNNN/AAAA' | 'cnpj:<14>' | 'ug:<6>' | 'lista:<ids>'
  tipo       text NOT NULL CHECK (tipo IN ('processo','cnpj','ug','lista')),
  valor      text NOT NULL,
  titulo     text NOT NULL DEFAULT '',
  classe     text NOT NULL DEFAULT 'interno' CHECK (classe IN ('publico','interno','pessoal','restrito','segredo')),
  criado_por text NOT NULL CHECK (btrim(criado_por) <> ''),
  criado_em  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS caso_achado(
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  caso_id     bigint NOT NULL REFERENCES caso(id),
  achado_id   bigint NOT NULL REFERENCES achado(id),
  criterio    text   NOT NULL,                        -- por que o achado é do caso (processo, cnpj, ug, lista)
  incluido_em timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT caso_achado_unico UNIQUE (caso_id, achado_id)
);

CREATE TABLE IF NOT EXISTS caso_versao(
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  caso_id    bigint  NOT NULL REFERENCES caso(id),
  versao     integer NOT NULL CHECK (versao >= 1),
  chave      char(64) NOT NULL CHECK (chave ~ '^[0-9a-f]{64}$'),   -- sha256 do derivado canônico
  supersedes bigint REFERENCES caso_versao(id),
  vigente    boolean NOT NULL DEFAULT true,
  motivo     text    NOT NULL,                        -- 'montagem', 'contestacao:<id>', 'desfecho:<id>', …
  derivado   jsonb   NOT NULL,                        -- achados com status efetivo, hipóteses, lacunas, contestações…
  criado_em  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT caso_versao_unica UNIQUE (caso_id, versao)
);
CREATE UNIQUE INDEX IF NOT EXISTS caso_versao_uma_vigente ON caso_versao (caso_id) WHERE vigente;

CREATE TABLE IF NOT EXISTS contestacao(
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  caso_id       bigint NOT NULL REFERENCES caso(id),
  achado_id     bigint REFERENCES achado(id),         -- NULL = contesta o caso inteiro (escopo, método)
  argumento     text   NOT NULL CHECK (btrim(argumento) <> ''),
  anexo_nome    text,
  anexo_sha256  char(64) CHECK (anexo_sha256 IS NULL OR anexo_sha256 ~ '^[0-9a-f]{64}$'),
  anexo         bytea,
  autor         text   NOT NULL CHECK (btrim(autor) <> ''),
  papel         text   NOT NULL CHECK (papel IN ('dono','analista','leitura','servico')),
  registrada_em timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT contestacao_anexo_inteiro CHECK ((anexo IS NULL) = (anexo_sha256 IS NULL))
);

CREATE TABLE IF NOT EXISTS contestacao_desfecho(
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  contestacao_id    bigint NOT NULL UNIQUE REFERENCES contestacao(id),    -- um desfecho por contestação
  revisor           text   NOT NULL CHECK (btrim(revisor) <> ''),
  papel             text   NOT NULL CHECK (papel IN ('dono','analista')),
  desfecho          text   NOT NULL CHECK (desfecho IN ('acolhida','parcialmente_acolhida','rejeitada')),
  fundamentacao     text   NOT NULL CHECK (btrim(fundamentacao) <> ''),
  decisao_humana_id bigint REFERENCES decisao_humana(id),
  decidido_em       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS acesso_log(
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  em            timestamptz NOT NULL DEFAULT now(),
  principal     text    NOT NULL CHECK (btrim(principal) <> ''),
  papel         text    NOT NULL CHECK (papel IN ('dono','analista','leitura','servico')),
  acao          text    NOT NULL,
  recurso       text    NOT NULL,
  classe        text,
  justificativa text    NOT NULL DEFAULT '',
  permitido     boolean NOT NULL,
  motivo        text    NOT NULL DEFAULT '',
  detalhe       jsonb   NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS acesso_log_recurso_ix ON acesso_log (recurso, em);

CREATE TABLE IF NOT EXISTS entrega(
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  produto          text    NOT NULL,
  chave            text    NOT NULL,                  -- chave do job `entregar:<produto>` (produto + filtro)
  manifesto_sha256 char(64) NOT NULL CHECK (manifesto_sha256 ~ '^[0-9a-f]{64}$'),
  pdf_sha256       char(64) CHECK (pdf_sha256 IS NULL OR pdf_sha256 ~ '^[0-9a-f]{64}$'),
  pdf_caminho      text,
  paginas          integer,
  destino          text    NOT NULL,                  -- 'arquivo' | 'telegram'
  ok               boolean NOT NULL,
  message_id       bigint,
  motivo           text    NOT NULL DEFAULT '',
  em               timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT entrega_telegram_tem_message_id CHECK (destino <> 'telegram' OR NOT ok OR message_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS entrega_chave_ix ON entrega (chave, em);

-- ── append-only no banco ───────────────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION so_acrescenta() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  RAISE EXCEPTION 'tabela % é só de acréscimo (append-only): % recusado', TG_TABLE_NAME, TG_OP;
END $f$;

CREATE OR REPLACE FUNCTION caso_versao_so_desvigora() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  IF TG_OP <> 'UPDATE' THEN
    RAISE EXCEPTION 'caso_versao não se apaga: % recusado', TG_OP;
  END IF;
  IF NOT (OLD.vigente AND NOT NEW.vigente)
     OR (to_jsonb(NEW) - 'vigente') IS DISTINCT FROM (to_jsonb(OLD) - 'vigente') THEN
    RAISE EXCEPTION 'caso_versao só aceita vigente true → false (a versão nova substitui; nada se reescreve)';
  END IF;
  RETURN NEW;
END $f$;

CREATE OR REPLACE FUNCTION desfecho_revisor_nao_e_autor() RETURNS trigger LANGUAGE plpgsql AS $f$
DECLARE a text;
BEGIN
  EXECUTE format('SELECT autor FROM %I.contestacao WHERE id = $1', TG_TABLE_SCHEMA) INTO a USING NEW.contestacao_id;
  IF a IS NOT NULL AND btrim(lower(a)) = btrim(lower(NEW.revisor)) THEN
    RAISE EXCEPTION 'o revisor da contestação não pode ser o autor dela (%)', a;
  END IF;
  RETURN NEW;
END $f$;

CREATE OR REPLACE TRIGGER acesso_log_so_acrescenta BEFORE UPDATE OR DELETE ON acesso_log
  FOR EACH ROW EXECUTE FUNCTION so_acrescenta();
CREATE OR REPLACE TRIGGER acesso_log_sem_truncate BEFORE TRUNCATE ON acesso_log
  FOR EACH STATEMENT EXECUTE FUNCTION so_acrescenta();
CREATE OR REPLACE TRIGGER contestacao_so_acrescenta BEFORE UPDATE OR DELETE ON contestacao
  FOR EACH ROW EXECUTE FUNCTION so_acrescenta();
CREATE OR REPLACE TRIGGER contestacao_sem_truncate BEFORE TRUNCATE ON contestacao
  FOR EACH STATEMENT EXECUTE FUNCTION so_acrescenta();
CREATE OR REPLACE TRIGGER desfecho_so_acrescenta BEFORE UPDATE OR DELETE ON contestacao_desfecho
  FOR EACH ROW EXECUTE FUNCTION so_acrescenta();
CREATE OR REPLACE TRIGGER desfecho_sem_truncate BEFORE TRUNCATE ON contestacao_desfecho
  FOR EACH STATEMENT EXECUTE FUNCTION so_acrescenta();
CREATE OR REPLACE TRIGGER desfecho_revisor BEFORE INSERT ON contestacao_desfecho
  FOR EACH ROW EXECUTE FUNCTION desfecho_revisor_nao_e_autor();
CREATE OR REPLACE TRIGGER caso_achado_so_acrescenta BEFORE UPDATE OR DELETE ON caso_achado
  FOR EACH ROW EXECUTE FUNCTION so_acrescenta();
CREATE OR REPLACE TRIGGER caso_achado_sem_truncate BEFORE TRUNCATE ON caso_achado
  FOR EACH STATEMENT EXECUTE FUNCTION so_acrescenta();
CREATE OR REPLACE TRIGGER entrega_so_acrescenta BEFORE UPDATE OR DELETE ON entrega
  FOR EACH ROW EXECUTE FUNCTION so_acrescenta();
CREATE OR REPLACE TRIGGER entrega_sem_truncate BEFORE TRUNCATE ON entrega
  FOR EACH STATEMENT EXECUTE FUNCTION so_acrescenta();
CREATE OR REPLACE TRIGGER caso_versao_imutavel BEFORE UPDATE OR DELETE ON caso_versao
  FOR EACH ROW EXECUTE FUNCTION caso_versao_so_desvigora();
CREATE OR REPLACE TRIGGER caso_versao_sem_truncate BEFORE TRUNCATE ON caso_versao
  FOR EACH STATEMENT EXECUTE FUNCTION so_acrescenta();

INSERT INTO migracoes(versao) VALUES ('casos_001') ON CONFLICT DO NOTHING;
COMMIT;
