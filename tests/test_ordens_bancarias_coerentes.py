"""`ordens_bancarias` só pode conter ORDEM BANCÁRIA — e hoje não é o caso.

Medido em 01/09/2026, varrendo a suíte em lotes atrás de regressões: **17.893 das 1.178.076
linhas (1,52%) têm `ug_codigo` que não é código de unidade gestora**. O somatório da coluna
`valor` vai a **R$ 154.007.269.947.462.624,00** — cento e cinquenta e quatro quatrilhões — contra
**R$ 136.896.021.781,50** somando apenas as linhas com UG de seis dígitos.

Três famílias, todas visíveis a olho:

    ug_codigo = 'Contabilizado' / 'Anulado' / 'Excluído'   11.900 linhas
        Deslocamento de uma coluna: o STATUS caiu no lugar da UG. Nessas linhas
        `valor` guarda coisas como 'CG0006029' e `tipo_ob` guarda 'AUXILIO SAUDE'.

    ug_codigo com ponto decimal ('373983.96')               5.974 linhas
        Texto de análise gravado na tabela errada: `numero_ob` traz frases inteiras
        ("Não há objeto de contrat…"), `favorecido_cpf` traz 'baixo'/'medio' e
        `status` traz listas JSON de datas. É saída de perícia, não pagamento.

    `numero_ob` que é timestamp ISO                              1 linha

POR QUE ISTO É UM TESTE, E NÃO UMA LIMPEZA
------------------------------------------
Apagar linha de banco de produção é decisão do dono, não minha — e a origem da escrita ainda
não está identificada (`coletar_obs_sessao.py` e `collectors/tfe_ob.py` são os dois que inserem
aqui). O teste FIXA o tamanho do problema para que ele não cresça em silêncio, do mesmo jeito que
as catracas de `except-pass` e de achados fazem.

A guarda de deslocamento que já existia (`reporting/cobertura_siafe`) olha **outra tabela**:
`ob_orcamentaria_siafe`, que está limpa (1.184.007 linhas, ZERO UG inválida). O espelho TFE nunca
teve guarda equivalente — e é onde a corrupção mora.

Relacionado: a casa já perdeu ~13 horas com esta mesma tabela corrompida em 12/08/2026, e 19
processos foram reavaliados com dado quebrado (ver `test_guardiao_sonda_integridade`). Aquele
vigia checa a INTEGRIDADE DO ARQUIVO; este checa a COERÊNCIA DO CONTEÚDO. São perguntas
diferentes: um banco íntegro pode estar cheio de linha errada.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

DB = Path(__file__).resolve().parents[1] / "data" / "compliance.db"

# Teto medido em 01/09/2026. Só pode DESCER — cada queda exige dizer no commit o que foi limpo e
# por quê. Se subir, alguém voltou a escrever registro alheio na tabela de pagamento.
TETO_UG_INVALIDA = 17_893


def _con():
    if not DB.exists():
        pytest.skip("compliance.db ausente nesta máquina")
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def test_ug_invalida_nao_cresce():
    """UG é código numérico de seis dígitos. Qualquer outra coisa ali é linha que não é OB."""
    with _con() as c:
        n = c.execute("SELECT count(*) FROM ordens_bancarias "
                      "WHERE ug_codigo GLOB '*[^0-9]*'").fetchone()[0]
    assert n <= TETO_UG_INVALIDA, (
        f"linhas com ug_codigo não numérico em `ordens_bancarias`: {n} > teto {TETO_UG_INVALIDA}. "
        "Alguém voltou a gravar registro alheio na tabela de pagamento — veja "
        "`coletar_obs_sessao.py` e `collectors/tfe_ob.py`, que são os dois que inserem aqui.")


def test_o_status_nao_pode_estar_na_coluna_da_UG():
    """Deslocamento de uma coluna: 'Contabilizado' é status de OB, não unidade gestora."""
    with _con() as c:
        n = c.execute(
            "SELECT count(*) FROM ordens_bancarias WHERE ug_codigo IN "
            "('Contabilizado','Anulado','Excluído','Não contabilizado','Nao contabilizado')"
        ).fetchone()[0]
    assert n <= 11_900, f"linhas com STATUS na coluna UG subiram para {n}"


def test_a_soma_de_valor_so_e_confiavel_com_o_filtro_de_UG():
    """O número que este teste protege: somar `valor` SEM filtrar dá cento e cinquenta e quatro
    QUATRILHÕES. Quem publicar total de OB sem o filtro publica um número impossível."""
    with _con() as c:
        bruto = c.execute("SELECT round(sum(valor),2) FROM ordens_bancarias").fetchone()[0] or 0
        limpo = c.execute("SELECT round(sum(valor),2) FROM ordens_bancarias "
                          "WHERE ug_codigo GLOB '[0-9][0-9][0-9][0-9][0-9][0-9]'").fetchone()[0] or 0
    assert limpo < 1e12, f"soma filtrada implausível: R$ {limpo:,.2f}"
    assert bruto > limpo * 100, (
        "a soma bruta deixou de estar contaminada — se a limpeza aconteceu, ABAIXE o teto de "
        "`test_ug_invalida_nao_cresce` e diga no commit o que foi removido")


def test_a_tabela_do_siafe_continua_limpa():
    """Controle: `ob_orcamentaria_siafe` é a outra face do mesmo dado e NÃO tem o problema.
    Se um dia tiver, a causa é comum às duas e o diagnóstico muda."""
    with _con() as c:
        try:
            n = c.execute("SELECT count(*) FROM ob_orcamentaria_siafe "
                          "WHERE ug_emitente GLOB '*[^0-9]*'").fetchone()[0]
        except sqlite3.OperationalError:
            pytest.skip("ob_orcamentaria_siafe ausente")
    assert n == 0, f"a tabela do SIAFE também corrompeu: {n} linhas com UG inválida"
