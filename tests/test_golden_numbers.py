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
    "mgs_clean": {"cnpj": "19088605000104", "obs": 1239, "total": 151941518.47},
    # 2026-07-20: total revisado DE PROPÓSITO 295.179.659,72 → 295.301.277,60 (+121.617,88).
    # Mesmas 2.524 OBs e 197 fornecedores — o sweep SIAFE atualizou VALORES de OBs in place
    # (correção da fonte). Drift auditado antes da revisão (contagem e fornecedores intactos).
    # 2026-07-28: 2524 → 2526 (+R$ 140.256,42). Conferido antes de revisar, porque golden que
    # se atualiza sozinho não é golden: as duas OBs novas são da EFATA COMERCIO & SERVIÇOS,
    # pagas em 2026-07-01, e o número de fornecedores distintos NÃO mudou (197) — assinatura
    # de coleta incremental, não de reprocessamento que reescreve histórico.
    # 2026-08-03: 2526 → 2572 (+46 OBs de 02/07 a 31/07/2026, coleta incremental) e 197 → 198
    # fornecedores (um novo). ⚠️ MAS a auditoria achou um movimento que NÃO é ingestão: a janela
    # histórica (até 01/07/2026) caiu de 2526 para **2525** linhas, −R$ 138.093,99. Não há
    # evidência de perda de OB única: sobram QUATRO OBs de exatamente R$ 138.093,99 da LOCTECH em
    # 2023 (pagamento recorrente mensal), cada uma com `numero_ob` próprio, e hoje o ITERJ não tem
    # nenhuma duplicata por `numero_ob`. A assinatura é de DEDUPLICAÇÃO de uma linha repetida —
    # a chave canônica da casa é numero_ob+ug+exercício. Registrado aqui porque a guarda serviu
    # exatamente para isto, e porque "consistente com dedup" não é "provado": se o número cair de
    # novo sem ingestão, é aqui que a investigação recomeça.
    "iterj_ug": {"ug": "133100", "obs": 2572, "total": 298259935.31, "fornecedores": 198},
    "cobertura": {"total_obs": 1121301, "pct_cnpj_min": 76},
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
