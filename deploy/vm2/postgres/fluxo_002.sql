-- fluxo_002.sql — O2.3 (plano mestre v2 §1.1 religação, §3.3; relatório da sombra §8.7).
--
-- IDEMPOTENTE, mesmo esquema de variável do fluxo_001 (:"esquema"; produção `fluxo`, testes num temporário).
--   1. `liberacao` — estágio liberado pela religação (O9.0). O supervisor só reserva job de estágio liberado
--      (fila.reservar, liberacao=True): o job de estágio ainda não liberado ESPERA na fila, nada se perde.
--   2. histórico de eventos SEM poda por contagem: `eventos_arquivo` + `arquivar_eventos(dias)`, que recusa
--      menos de 7 dias e só move evento JÁ processado (a próxima sombra cobre a janela inteira — §6 item 9).
--   3. índice da reserva com a fila cheia: o conjunto "tipos a montante que seguram" (fila elegível há < 30 min)
--      lê só a faixa recente de `disponivel_em`.
-- A reserva NÃO ganhou coluna de fonte/provedor: a medida de 24/11 (10 mil jobs, VM-2) mostrou que o custo era a
-- subconsulta POR LINHA (montante e teto), não o jsonb — com os conjuntos calculados uma vez por reserva (CTE em
-- fila._SQL_RESERVAR) o p95 caiu abaixo de 50 ms sem mudar o formato do job.

BEGIN;
SELECT pg_advisory_xact_lock(474748);

CREATE SCHEMA IF NOT EXISTS :"esquema";
SET LOCAL search_path TO :"esquema";

CREATE TABLE IF NOT EXISTS liberacao(
  estagio     text        PRIMARY KEY,                    -- E1..E18
  liberado_em timestamptz NOT NULL DEFAULT now(),
  por         text,                                       -- quem liberou (tools/religar_o90.py)
  nota        text
);

CREATE TABLE IF NOT EXISTS eventos_arquivo (LIKE eventos INCLUDING DEFAULTS);
CREATE INDEX IF NOT EXISTS eventos_quando_ix ON eventos (quando);
CREATE OR REPLACE FUNCTION arquivar_eventos(dias integer DEFAULT 30) RETURNS bigint
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE n bigint;
BEGIN
  IF dias IS NULL OR dias < 7 THEN
    RAISE EXCEPTION 'retenção mínima do histórico de eventos é 7 dias (pedido: %)', dias;
  END IF;
  WITH m AS (DELETE FROM eventos WHERE processado_em IS NOT NULL
               AND quando < now() - make_interval(days => dias) RETURNING *)
  INSERT INTO eventos_arquivo SELECT * FROM m;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $$;

CREATE INDEX IF NOT EXISTS jobs_fila_disp_ix ON jobs (disponivel_em) INCLUDE (tipo) WHERE estado = 'fila';

INSERT INTO migracoes(versao) VALUES ('fluxo_002') ON CONFLICT DO NOTHING;
COMMIT;
