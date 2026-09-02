"""
Eixo D do plano de benchmarks — REGRESSÃO FACTUAL.

Congela os números canônicos que alimentam os relatórios. Se um refactor (ou uma
ingestão acidental) mudar esses totais SEM querer, este teste grita ANTES de o dono
ver número errado no /relatorio. Quando a base for legitimamente atualizada, os
valores aqui são revisados DE PROPÓSITO (e o commit documenta a mudança).

Fonte: data/compliance.db (tabela ordens_bancarias). Conferido contra os artefatos
reais gerados em 2026-06-09 (data/baseline_2026-06-09/).
Ver docs/PLANO-BENCHMARKS-E-CODIFICACAO-2026-06-09.md.
"""
import sqlite3
from pathlib import Path

import pytest

DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"

# existir o arquivo não basta: no runner ele nasce VAZIO (criado por testes que escrevem) e o
# teste morria com "no such table" — falha de ambiente lida como regressão (2026-08-02).
from helpers_ambiente import base_utilizavel  # noqa: E402

pytestmark = pytest.mark.skipif(not base_utilizavel(DB),
                                reason="compliance.db ausente ou sem tabelas neste ambiente")


def _con():
    return sqlite3.connect(str(DB))


def _norm(col: str) -> str:
    return f"replace(replace(replace({col},'.',''),'/',''),'-','')"


# Números canônicos (2026-06-09). Tolerância 0 nos congelados; a base é estável
# (gestão 2019-2026 já ingerida). Atualizar conscientemente após nova ingestão.
#
# total_obs revisado 2026-06-13: 1121307 -> 1121301. NÃO houve perda de dado real.
# O valor de 06-09 estava INFLADO por poluição de teste: o antigo test_offline gravava
# OBs sintéticas na compliance.db de PRODUÇÃO. A limpeza (commit ccc1f6a, "Limpei a
# poluição já gravada (14 OBs + 3 memórias de teste)") removeu essas linhas falsas,
# encolhendo a contagem de propósito. 1121301 é o piso REAL (produção sem a OB sintética
# remanescente 2026OB99001/'EMPRESA TESTE LTDA', ainda na base — exclusão de data/ é do
# dono). MGS (1127) e ITERJ (2457) permanecem intactos: a perda foi 100% lixo de teste.
_TEST_OB = "2026OB99001"  # OB sintética de poluição (test_offline antigo) — não é dado real.
GOLDEN = {
    # 2026-08-03: 1173 → 1239 (+66 OBs, +R$ 8.683.519,17). Auditado ANTES de revisar: as 66 são
    # todas de 02/07 a 31/07/2026, distribuídas dia a dia — assinatura de coleta incremental do
    # cron do SIAFE, não de reprocessamento. Prova de que nada do histórico se mexeu: a janela
    # até 01/07/2026 continua EXATAMENTE (1173, R$ 143.257.999,30), o valor congelado anterior.
    # 2026-08-12: 1239 → 1238 (−R$ 85.653,26). NÃO é a corrupção do banco (essa foi reparada e a
    # recoleta devolveu tudo): é DESPUBLICAÇÃO da fonte. A conta fecha na casa dos centavos —
    # 151.941.518,47 − 151.855.865,21 = 85.653,26, exatamente a `2022OB00184` (UG 133100), que o
    # TFE deixou de publicar e está preservada em `ob_retirada` desde 10/08. A segunda OB retirada
    # da MGS (`2026OB08146`, R$ 244.897,92) foi publicada DEPOIS deste golden, então não o afeta.
    # 2026-09-01: 1238 → 1239 (+R$ 85.653,26). A `2022OB00184` VOLTOU. É a mesma OB que o
    # comentário acima registra como despublicada em 12/08 — a fonte a republicou, e o
    # mecanismo `ob_retirada` da casa prova os dois movimentos: retirada em 2026-08-10T09:01:58
    # e ausente das retiradas posteriores. A conta fecha no centavo: 151.941.518,47 −
    # 151.855.865,21 = 85.653,26, exatamente o valor dela. Republicação da fonte, não coleta
    # nova nem reprocessamento.
    "mgs_clean": {"cnpj": "19088605000104", "obs": 1239, "total": 151941518.47},
    # 2026-07-20: total revisado DE PROPÓSITO 295.179.659,72 → 295.301.277,60 (+121.617,88).
    # Mesmas 2.524 OBs e 197 fornecedores — o sweep SIAFE atualizou VALORES de OBs in place
    # (correção da fonte). Drift auditado antes da revisão (contagem e fornecedores intactos).
    # 2026-07-28: 2524 → 2526 (+R$ 140.256,42). Conferido antes de revisar, porque golden que
    # se atualiza sozinho não é golden: as duas OBs novas são da EFATA COMERCIO & SERVIÇOS,
    # pagas em 2026-07-01, e o número de fornecedores distintos NÃO mudou (197) — assinatura
    # de coleta incremental, não de reprocessamento que reescreve histórico.
    # 2026-08-03: 2526 → 2572 (+46 OBs de 02/07 a 31/07/2026, coleta incremental) e 197 → 198
    # fornecedores. A janela histórica (até 01/07/2026) caiu de 2526 para 2525, −R$ 138.093,99, e
    # eu registrei aqui a hipótese de DEDUPLICAÇÃO. **Estava errada** — corrigido em 2026-08-04
    # com o backup off-box de 02/08: a linha que sumiu é a `2023OB00455` (13/07/2023, LOCTECH,
    # R$ 138.093,99), OB ÚNICA e distinta das outras quatro de mesmo valor. Não foi dedup: foi a
    # FONTE. Comparando a base inteira com o backup, **140 OBs de sete exercícios, somando
    # R$ 30.001.367,60, deixaram de ser publicadas pelo TFE-RJ**, e nenhuma delas está no zip
    # baixado em 03/08 06:00 — o `jfn-tfe-ob.service` apaga o exercício e reinsere, fielmente e em
    # silêncio. Elas ficam preservadas em `ob_retirada` (ver `collectors/tfe_ob`), porque
    # pagamento publicado e depois DESPUBLICADO é fato de interesse fiscalizatório.
    # A lição de método: esta guarda funcionou — foi ela que puxou o fio. O que falhou foi eu ter
    # fechado a hipótese sem a prova que o backup dava.
    # 2026-08-12: total 298.259.935,31 → 298.312.376,04 (+52.440,73) com a MESMA contagem (2.572)
    # e os mesmos 198 fornecedores. Auditado antes de revisar: comparei a UG inteira contra a
    # salvação pré-recoleta e o resultado foi 89 linhas RECUPERADAS (as que a corrupção comeu,
    # R$ 4.819.771,34) e **zero mudança de valor**. Ou seja, o delta contra o golden já existia
    # antes da corrupção — está medido no dia 11/08 às 20:00, no banco ainda quebrado. É revisão
    # de valor pela fonte. NÃO identifiquei qual OB mudou: não há snapshot anterior ao drift, e
    # dizer qual seria chute.
    # 2026-09-01: 2572 → 2571 e total 298.312.376,04 → 298.390.655,78. O saldo de −1 OB é
    # LÍQUIDO e cada parcela está em `ob_retirada`: saíram a `2022OB00085` (R$ 340,10) e a
    # `2022OB00289` (R$ 295,50), ambas retiradas em 2026-08-31T09:01:17, e voltou a
    # `2022OB00184` (R$ 85.653,26) — 2572 − 2 + 1 = 2571. Fornecedores seguem 198, assinatura de
    # movimento na publicação da fonte e não de reprocessamento. O total SOBE apesar de a
    # contagem CAIR porque a OB que voltou vale mais que as duas que saíram somadas.
    "iterj_ug": {"ug": "133100", "obs": 2571, "total": 298390655.78, "fornecedores": 198},
    # 2026-08-12: piso 1.121.301 → 1.178.076 e pct_cnpj_min 76 → 75.
    # O piso sobe porque a recoleta de 2024-2026 (reparo da corrupção) trouxe a base de 1.142.056
    # para 1.178.076. O `pct_cnpj_min` cai por COMPOSIÇÃO, não por perda: o percentual de OBs com
    # CNPJ no favorecido é 83,9% em 2020 e 73,4% em 2025 / 74,3% em 2026 — exercício recente paga
    # mais a CPF e a credor genérico. Trazer 36.020 linhas de 2024-2026 puxou a média do acervo
    # para 75,23%. A guarda que de fato pega PERDA de dado é o `total >= total_obs` acima; esta
    # aqui vigia a qualidade do campo, e o piso tem de acompanhar a composição real do acervo.
    # ATENÇÃO ao piso: despublicação faz a contagem CAIR legitimamente (346 OBs já registradas em
    # `ob_retirada`). Se este teste falhar por encolhimento, o primeiro lugar a olhar é essa tabela
    # — não presumir perda de dado antes de descontar o que a fonte retirou.
    "cobertura": {"total_obs": 1178076, "pct_cnpj_min": 75},
}


def test_golden_mgs_clean():
    g = GOLDEN["mgs_clean"]
    with _con() as c:
        obs, total = c.execute(
            f"SELECT COUNT(*), ROUND(SUM(valor),2) FROM ordens_bancarias "
            f"WHERE {_norm('favorecido_cpf')}=?",
            (g["cnpj"],),
        ).fetchone()
    assert obs == g["obs"], f"MGS OBs drift: {obs} != {g['obs']}"
    assert total == g["total"], f"MGS total drift: {total} != {g['total']}"


def test_golden_iterj_ug133100():
    g = GOLDEN["iterj_ug"]
    with _con() as c:
        obs, total, forn = c.execute(
            "SELECT COUNT(*), ROUND(SUM(valor),2), COUNT(DISTINCT favorecido_cpf) "
            "FROM ordens_bancarias WHERE ug_codigo=?",
            (g["ug"],),
        ).fetchone()
    assert obs == g["obs"], f"ITERJ OBs drift: {obs} != {g['obs']}"
    assert total == g["total"], f"ITERJ total drift: {total} != {g['total']}"
    assert forn == g["fornecedores"], f"ITERJ fornecedores drift: {forn} != {g['fornecedores']}"


def test_golden_cobertura():
    g = GOLDEN["cobertura"]
    # Exclui OBs sintéticas de poluição de teste para medir só dado REAL de produção.
    with _con() as c:
        total, com_cnpj = c.execute(
            f"SELECT COUNT(*), SUM(CASE WHEN length({_norm('favorecido_cpf')})=14 "
            f"THEN 1 ELSE 0 END) FROM ordens_bancarias WHERE numero_ob != ?",
            (_TEST_OB,),
        ).fetchone()
    # Cobertura só cresce (nova ingestão); falha se ENCOLHER (perda de dado real).
    assert total >= g["total_obs"], f"Cobertura encolheu: {total} < {g['total_obs']}"
    pct = 100 * com_cnpj / total
    assert pct >= g["pct_cnpj_min"], f"% CNPJ caiu: {pct:.0f}% < {g['pct_cnpj_min']}%"
