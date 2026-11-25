-- texto_ocr_001.sql — E4 `texto`, E5 `ocr`, E6 `confirmar_ocr` e E7 `arquivar` (plano mestre v2 §3.2 E4–E7, item O3.4).
--
-- IDEMPOTENTE (IF NOT EXISTS / ON CONFLICT). Pré-requisito: evidencias.py + evidencias_001.sql (aquisicao,
-- transformacao, versoes.hash_de) + captura_001.sql no esquema. Só ACRESCENTA: nada renomeado, nada apagado.
-- O nome do schema vem da variável `esquema` (produção `public`; os testes aplicam o MESMO arquivo num esquema
-- temporário e o apagam no fim).
--   Python: compliance_agent/aplicacao/estagios/texto.py `schema aplicar` (troca :"esquema" com fluxo.schema.renderizar)
--
-- E4 e E5 NÃO ganham tabela própria: gravam em `transformacao` (tipo 'texto_nativo' / 'ocr', entrada → saída por
-- sha256, motor e versão, perfil por página e bbox no arquivo lateral cujo sha256 vai em `parametros`) e em `versoes`
-- (hash_de 'texto'). Aqui só o que não cabe lá:
-- ocr_numero    E6: UM número crítico (CNPJ, valor, data, processo, contrato, ata, NF) lido pelo OCR por IA num
--               texto (texto_sha), com o estado (confirmado | divergente | a_conferir), a FONTE que o confirmou e o
--               NÍVEL ('A' = SIAFE, código de barras ou leitura independente; nada abaixo de A confirma).
-- ocr_conferencia  E6: o estado do DOCUMENTO naquele texto (confirmado só com todo número em nível A).
-- arquivamento  E7: o original (sha256 da versão binária) guardado pela porta única, com md5 conferido, a chave no
--               índice do armazenamento, as cópias e se o local foi apagado (só depois do hash).

BEGIN;
SELECT pg_advisory_xact_lock(474752);        -- dois aplicadores ao mesmo tempo não disputam o DDL

SET LOCAL search_path TO :"esquema";

CREATE TABLE IF NOT EXISTS migracoes(versao text PRIMARY KEY, aplicada_em timestamptz NOT NULL DEFAULT now());

CREATE INDEX IF NOT EXISTS transformacao_doc_ix ON transformacao (processo, doc_id, tipo);

CREATE TABLE IF NOT EXISTS ocr_numero(
  processo    text        NOT NULL,
  doc_id      text        NOT NULL,
  texto_sha   text        NOT NULL,                  -- versão de texto (saída do E5) de onde o número saiu
  tipo        text        NOT NULL,
  norma       text        NOT NULL,                  -- forma canônica (ocr_ia_prova.normalizar)
  literal     text,
  pagina      integer,
  estado      text        NOT NULL,
  fonte       text,                                  -- siafe_ob | siafe_ne | barras | leitura:<motor> | NULL
  nivel       text,                                  -- 'A' só quando confirmado
  leitura_2   text,                                  -- divergente: o número que a 2ª leitura trouxe
  job_chave   text        NOT NULL,
  ficha       bigint      NOT NULL,
  em          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ocr_numero_pk PRIMARY KEY (processo, doc_id, texto_sha, tipo, norma),
  CONSTRAINT ocr_numero_estado CHECK (estado IN ('confirmado', 'divergente', 'a_conferir')),
  CONSTRAINT ocr_numero_nivel CHECK ((estado = 'confirmado') = (coalesce(nivel, '') = 'A' AND fonte IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS ocr_conferencia(
  processo    text        NOT NULL,
  doc_id      text        NOT NULL,
  texto_sha   text        NOT NULL,
  estado      text        NOT NULL,                  -- confirmado | a_conferir
  numeros     integer     NOT NULL,
  a_conferir  integer     NOT NULL,
  fontes      jsonb       NOT NULL DEFAULT '{}',     -- fonte → disponível? (barras/SIAFE/leitura) e o porquê
  job_chave   text        NOT NULL,
  ficha       bigint      NOT NULL,
  em          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ocr_conferencia_pk PRIMARY KEY (processo, doc_id, texto_sha),
  CONSTRAINT ocr_conferencia_estado CHECK (estado IN ('confirmado', 'a_conferir')),
  CONSTRAINT ocr_conferencia_coerente CHECK ((estado = 'confirmado') = (a_conferir = 0))
);

CREATE TABLE IF NOT EXISTS arquivamento(
  processo     text        NOT NULL,
  doc_id       text        NOT NULL,
  sha256       text        NOT NULL,                 -- versão binária (versoes.hash_de = 'binario')
  md5          text        NOT NULL,                 -- conferido no destino antes de apagar
  bytes        bigint      NOT NULL,
  destino      text        NOT NULL,                 -- 'porta_unica' (compliance_agent/armazenamento) | teste
  chave        text        NOT NULL,                 -- chave da unidade no índice do armazenamento
  copias       jsonb       NOT NULL DEFAULT '{}',
  origem       text        NOT NULL,                 -- caminho local antes de sair
  apagado      boolean     NOT NULL DEFAULT false,
  job_chave    text        NOT NULL,
  ficha        bigint      NOT NULL,
  em           timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT arquivamento_pk PRIMARY KEY (processo, doc_id, sha256, destino)
);

INSERT INTO migracoes(versao) VALUES ('texto_ocr_001') ON CONFLICT DO NOTHING;
COMMIT;
