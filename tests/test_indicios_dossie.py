# -*- coding: utf-8 -*-
"""Indícios lidos do dossiê — e as duas inflações que a primeira versão produziu.

O número de manchete deste indício saiu, em três medições sucessivas sobre o MESMO dossiê:

    R$ 3.995.001,04   somando todo valor da linha que mencionasse "multa"
    R$    86.961,77   somando só o valor adjacente ao termo
    R$    65.681,99   deduplicando o lançamento descrito em dois itens

Os dois erros são da mesma família das manchetes superestimadas do painel: o número parece
medido, tem casas decimais, e está errado por uma ordem de grandeza. Cada teste abaixo trava
uma das correções com o trecho REAL que a produziu.
"""
from __future__ import annotations

import pytest

from compliance_agent.sei.indicios_dossie import (
    i_direta_sem_justificativa, i_execucao_sem_fiscal, i_juros_multa, resumo_md, varrer,
)

# Trecho real do processo 030001_004946_2026: quatro valores na linha, um só é multa.
_LINHA_FATURA = ("- Abril/2026 agrupamento 9928: Bruto R$ 314.366,12; IR R$ 6.455,96; "
                 "multa R$ 9.288,31; líquido R$ 314.366,12. [doc 074_planilha.txt]")

# O mesmo lançamento descrito em dois itens diferentes do dossiê.
_DUPLICADO = ("- Juros e multa (julho/2026): R$ 7.093,26 [doc 000_planilha.txt]\n"
              "- Cobrança de juros e multa (R$ 7.093,26) por pagamento extemporâneo, onerando "
              "o erário [doc 008_despacho.txt]")


def test_soma_apenas_o_valor_adjacente_ao_termo():
    """Bruto e líquido não são multa por estarem na mesma linha que ela."""
    ind = i_juros_multa(_LINHA_FATURA)
    assert ind.valores["total"] == 9288.31


def test_nao_conta_o_mesmo_lancamento_duas_vezes():
    """'Juros e multa' é UMA expressão; e o mesmo valor descrito em dois itens é um lançamento."""
    ind = i_juros_multa(_DUPLICADO)
    assert ind.valores["n_lancamentos"] == 1
    assert ind.valores["total"] == 7093.26


def test_juros_e_multa_nao_casa_como_duas_ocorrencias():
    ind = i_juros_multa("- Juros e multa: R$ 1.000,00 [doc a.txt]")
    assert ind.valores["total"] == 1000.00


def test_mencao_sem_valor_declara_indisponivel_e_nao_zero():
    """INDISPONÍVEL ≠ 0 — o invariante da casa, aqui também."""
    ind = i_juros_multa("- Houve cobrança de juros por atraso [doc a.txt]")
    assert ind.grau == "informativo"
    assert "INDISPONÍVEL, não zero" in ind.motivo
    assert "total" not in ind.valores


def test_sem_mencao_nenhuma_nao_inventa_indicio():
    assert i_juros_multa("- Objeto: fornecimento de energia [doc a.txt]") is None


def test_grau_escala_com_o_valor():
    assert i_juros_multa("- multa R$ 100,00 [doc a.txt]").grau == "informativo"
    assert i_juros_multa("- multa R$ 10.000,00 [doc a.txt]").grau == "atencao"
    assert i_juros_multa("- multa R$ 90.000,00 [doc a.txt]").grau == "prioritario"


# ── os demais indícios ─────────────────────────────────────────────────────────────────────

def test_contratacao_direta_com_justificativa_nao_vira_indicio():
    texto = ("- Inexigibilidade de licitação [doc a.txt]\n"
             "- Justificativa de preço juntada aos autos [doc b.txt]")
    assert i_direta_sem_justificativa(texto) is None


def test_contratacao_direta_sem_justificativa_declara_a_duvida_de_captura():
    ind = i_direta_sem_justificativa("- Inexigibilidade de licitação [doc a.txt]")
    assert ind is not None
    assert "CAPTURA" in ind.motivo, "tem de distinguir lacuna de captura de lacuna de instrução"


def test_execucao_com_fiscal_identificado_nao_vira_indicio():
    texto = "- Atestado de realização [doc a.txt]\n- Fiscal do contrato: Fulano [doc b.txt]"
    assert i_execucao_sem_fiscal(texto) is None


def test_execucao_sem_fiscal_cita_o_art_117():
    ind = i_execucao_sem_fiscal("- Atestado de realização de serviços [doc a.txt]")
    assert ind and "117" in ind.motivo


# ── honestidade da apresentação ────────────────────────────────────────────────────────────

def test_ausencia_de_indicio_nao_e_declarada_como_ausencia_de_problema():
    md = resumo_md([])
    assert "NÃO significa ausência de problema" in md


def test_resumo_declara_que_indicio_nao_e_acusacao():
    md = resumo_md(varrer(_LINHA_FATURA))
    assert "hipótese a verificar" in md
    assert "não afirmação de irregularidade" in md


def test_indicios_saem_do_mais_prioritario_para_o_menos():
    texto = _LINHA_FATURA + "\n- Inexigibilidade de licitação [doc c.txt]\n" + \
        "- multa R$ 90.000,00 [doc d.txt]"
    graus = [i.grau for i in varrer(texto)]
    assert graus == sorted(graus, key=lambda g: -["informativo", "atencao",
                                                  "prioritario"].index(g))


# ── O checklist do catálogo é respondido quase todo NEGATIVAMENTE ──────────────────────────
# A moldura jurídica entrega ao modelo os 42 vícios canônicos, e ele os percorre um a um. A 1ª
# versão deste indício procurava negação para descartar e apontou 27 vícios "afirmados" num
# processo onde as respostas eram "não.", "normal", "não é contratação". Listar formas de negar
# é perder sempre; o default tem de ser NÃO ser achado — a mesma presunção de legitimidade que
# rege o resto da casa.

_CHECKLIST_NEGATIVO = """- - `subcontratacao_cruzada`: não.
- - `vigencia_excessiva`: ARP 12 meses, normal.
- - `publicidade_prazos_minimizados`: pregão eletrônico com prazo normal (28/09 a 16/10).
- - `contratacao_direta_indevida`: adesão a ARP é permitida legalmente. Não é contratação direta.
- - `cotacoes_combinadas`: não há indício de cotações combinadas (apenas uma proposta).
"""


def test_checklist_respondido_negativamente_nao_vira_achado():
    from compliance_agent.sei.indicios_dossie import i_vicio_afirmado
    assert i_vicio_afirmado(_CHECKLIST_NEGATIVO) is None


def test_resposta_telegrafica_nao_e_confundida_com_afirmacao():
    from compliance_agent.sei.indicios_dossie import i_vicio_afirmado
    assert i_vicio_afirmado("- `fracionamento_despesa`: não.") is None
    assert i_vicio_afirmado("- `lote_pacote`: normal.") is None


def test_vicio_realmente_afirmado_e_apontado():
    from compliance_agent.sei.indicios_dossie import i_vicio_afirmado
    ind = i_vicio_afirmado(
        "- `especificacao_dirigida`: verifica-se marca sem 'ou equivalente' [doc 001_tr.txt]")
    assert ind is not None
    assert ind.valores["vicios"] == ["especificacao_dirigida"]
    assert ind.grau == "prioritario"


def test_proponente_unico_e_apontado_com_a_explicacao_inocente():
    from compliance_agent.sei.indicios_dossie import i_licitante_unico
    ind = i_licitante_unico("- Houve apenas uma proposta no certame [doc 004_ata.txt]")
    assert ind is not None
    assert "nicho" in ind.motivo, "tem de trazer a explicação inocente mais comum"


# ── DV: detectar a PERGUNTA em vez da resposta ─────────────────────────────────────────────
# A 1ª versão disparou em 70% dos 72 processos analisados. A causa era minha: o roteiro de
# extração PEDE "inconsistências entre documentos do próprio lote" como item, e o modelo
# responde "não consta". Eu contava o rótulo do roteiro como achado. Mesma lição do checklist
# de vícios, que eu já tinha aprendido e não apliquei aqui.

_REAIS_NEGATIVAS = [
    "- - Inconsistências entre documentos do próprio lote: não consta [doc 001.txt]",
    "- - inconsistências entre documentos do próprio lote: não consta [doc 002.txt]",
    "- **Inconsistências entre documentos** — nenhuma identificada [doc 003.txt]",
]

_REAIS_POSITIVAS = [
    "- - Inconsistência: valor total empenhado (R$ 76.392.525,00) difere da nota "
    "(R$ 76.000.000,00) [doc 004.txt]",
    "- **Inconsistências** — Divergência de competência: a NL cita 03/2025 enquanto a OB "
    "cita 04/2025 [doc 005.txt]",
]


@pytest.mark.parametrize("linha", _REAIS_NEGATIVAS)
def test_rotulo_do_roteiro_nao_e_achado(linha):
    from compliance_agent.sei.indicios_dossie import i_divergencia_declarada
    assert i_divergencia_declarada(linha) is None


@pytest.mark.parametrize("linha", _REAIS_POSITIVAS)
def test_divergencia_concreta_e_apontada(linha):
    from compliance_agent.sei.indicios_dossie import i_divergencia_declarada
    ind = i_divergencia_declarada(linha)
    assert ind is not None and ind.codigo == "DV"


def test_divergencia_exige_nomear_o_que_difere():
    """"Há inconsistências" sem dizer QUAIS não é achado — é anúncio de achado."""
    from compliance_agent.sei.indicios_dossie import i_divergencia_declarada
    assert i_divergencia_declarada(
        "- Foram observadas inconsistências no processo [doc 006.txt]") is None


def test_regua_quebrada_APARECE_no_log_em_vez_de_sumir(caplog):
    """O `except Exception` do `varrer` engoliu um NameError e o indício deixou de existir —
    sem erro, sem log, sem nada. Silêncio é pior que a falha: a fila fica limpa por engano."""
    import logging

    from compliance_agent.sei import indicios_dossie as I

    def _quebrada(_dossie):
        raise RuntimeError("régua com defeito")

    original = I.DETECTORES
    I.DETECTORES = (_quebrada,)
    try:
        with caplog.at_level(logging.ERROR):
            assert I.varrer("qualquer texto") == []
    finally:
        I.DETECTORES = original
    assert any("PULADO" in r.message or "PULADO" in r.getMessage() for r in caplog.records), \
        "a régua quebrada tem de aparecer no log"
