# -*- coding: utf-8 -*-
"""X11 — aditar até virar outra contratação, e a armadilha de medir isso por texto.

O art. 126 é curto e direto: "as alterações unilaterais ... não poderão transfigurar o objeto da
contratação". Não há percentual — uma alteração pode caber folgadamente nos 25% do art. 125 e
ainda assim ser ilícita, porque o que se contratou deixou de ser o que se executa. O art. 125
protege o equilíbrio econômico; o art. 126 protege a LICITAÇÃO.

A armadilha, e é ela que estes testes existem para travar: **termo aditivo descreve o DELTA, não
o objeto inteiro**. Dissimilaridade textual é ESPERADA em alteração perfeitamente regular. Um
detector que transforme distância de vocabulário em achado produz falso positivo em série — a
casa já pagou por isso. Daí a exigência de convergência: sinal isolado fraco não confirma.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores import REGISTRO
from compliance_agent.detectores.x11_objeto_descaracterizado import categoria, similaridade

X11 = REGISTRO["X11"]

_OBRA = ("Execução de obra de construção da unidade escolar municipal, incluindo fundação, "
         "estrutura, alvenaria, cobertura e instalações prediais")
_SERVICO = ("Prestação de serviços contínuos de vigilância patrimonial desarmada com "
            "monitoramento eletrônico e controle de acesso, com dedicação de mão de obra")


def _ctx(objeto, aditivos, **kw):
    base = {"processo": "P-1", "objeto_contrato": objeto,
            "aditivos": [{"descricao_objeto": a} for a in aditivos]}
    base.update(kw)
    return base


# ───────────────────────── honestidade ────────────────────────────────────────────────────────

def test_sem_objeto_do_contrato_e_nao_avaliavel():
    r = X11.avaliar({"processo": "P-1", "aditivos": [{"descricao_objeto": "x"}]})
    assert r.status == "nao_avaliavel"


def test_sem_descricao_no_termo_e_nao_avaliavel():
    r = X11.avaliar(_ctx(_OBRA, []))
    assert r.status == "nao_avaliavel"
    assert "não está aqui" in r.motivo_refutacao


# ───────────────────────── a armadilha: delta ≠ transfiguração ────────────────────────────────

def test_dissimilaridade_SOZINHA_nao_confirma():
    """O termo descreve o que muda; diferença de vocabulário é esperada."""
    r = X11.avaliar(_ctx(_OBRA, ["Acréscimo de 120 m² de piso vinílico no pavimento superior"]))
    assert r.status == "descartado"
    assert "sinal isolado não confirma" in r.motivo_refutacao.lower()


def test_detalhamento_do_mesmo_objeto_nao_dispara():
    r = X11.avaliar(_ctx(_OBRA, ["Ajuste da estrutura e da cobertura da unidade escolar, com "
                                 "revisão das instalações prediais"]))
    assert r.status == "descartado"


# ───────────────────────── T2 · mudança de natureza ───────────────────────────────────────────

def test_mudanca_de_CATEGORIA_confirma_sozinha():
    """Objetivo: não depende de limiar, depende de o texto dizer outra coisa."""
    r = X11.avaliar(_ctx(_OBRA, ["Prestação de serviços contínuos de vigilância patrimonial "
                                 "com dedicação de mão de obra"]))
    assert r.status == "confirmado" and r.score >= 0.85
    assert any("CATEGORIA DIFERENTE" in e["trecho"] for e in r.evidencia)


def test_locacao_dentro_de_contrato_de_aquisicao():
    r = X11.avaliar(_ctx("Aquisição de 40 veículos utilitários para a frota municipal",
                         ["Locação de veículos tipo van para transporte de idosos"]))
    assert r.status == "confirmado"
    assert r.valores["categoria_contrato"] == "aquisicao"
    assert "locacao" in r.valores["categorias_aditadas"]


@pytest.mark.parametrize("texto,esperado", [
    (_OBRA, "obra"),
    (_SERVICO, "servico_continuado"),
    ("Aquisição de medicamentos para a rede básica", "aquisicao"),
    ("Locação de veículos utilitários", "locacao"),
    ("texto sem categoria reconhecivel", None),
])
def test_classificacao_de_categoria(texto, esperado):
    assert categoria(texto) == esperado


def test_mao_de_obra_NAO_e_obra():
    """`\bobra\b` casava dentro de "mão de obra" e transformava serviço continuado em obra —
    o efeito era ANULAR o achado, porque a categoria do aditivo passava a igualar a do contrato."""
    assert categoria("serviços com dedicação de mão de obra") == "servico_continuado"


def test_SETOR_diferente_com_a_mesma_natureza_nao_transfigura():
    """Compra de medicamento → compra de material de escritório muda o setor, não a natureza."""
    r = X11.avaliar(_ctx("Aquisição de medicamentos para a rede básica de saúde",
                         ["Aquisição de material de escritório para as unidades"]))
    assert r.status == "descartado", "mudança de setor virou transfiguração"


# ───────────────────────── T3 · item sem correspondente ───────────────────────────────────────

def test_item_novo_mais_dissimilaridade_confirma():
    r = X11.avaliar(_ctx(_OBRA, ["Inclusão de sistema de climatização e automação predial"],
                         itens_contrato=["fundação", "alvenaria", "cobertura"],
                         itens_aditados=["chiller", "automação"]))
    assert r.status == "confirmado"
    assert r.valores["itens_sem_correspondente"] == 2


def test_item_ja_previsto_na_planilha_nao_conta():
    r = X11.avaliar(_ctx(_OBRA, ["Acréscimo de alvenaria"],
                         itens_contrato=["fundação", "alvenaria"], itens_aditados=["alvenaria"]))
    assert r.valores["itens_sem_correspondente"] == 0


def test_sem_planilha_original_o_T3_nao_e_aferido():
    r = X11.avaliar(_ctx(_OBRA, ["Inclusão de climatização"], itens_aditados=["chiller"]))
    assert r.valores["itens_sem_correspondente"] == 0


# ───────────────────────── T4 · rubrica ───────────────────────────────────────────────────────

def test_rubrica_de_objeto_novo_confirma():
    aditado = "Inclusão de serviço de operação e manutenção do sistema instalado"
    r = X11.avaliar(_ctx(_OBRA, [aditado], _rubrica_pertinencia={
        "nivel": "objeto_novo_disfarcado", "trecho": "operação e manutenção do sistema"}))
    assert r.status == "confirmado" and r.score >= 0.85


def test_rubrica_de_mesmo_objeto_nao_confirma():
    aditado = "Ajuste de quantitativo da alvenaria da unidade escolar"
    r = X11.avaliar(_ctx(_OBRA, [aditado], _rubrica_pertinencia={
        "nivel": "mesmo_objeto_detalhado", "trecho": "quantitativo da alvenaria"}))
    assert r.status == "descartado"


def test_rubrica_com_citacao_inventada_e_descartada():
    """Grounding conferido contra o objeto aditado."""
    r = X11.avaliar(_ctx(_OBRA, ["Ajuste de quantitativo"], _rubrica_pertinencia={
        "nivel": "objeto_novo_disfarcado", "trecho": "o gestor admitiu contratar outra coisa"}))
    assert r.status == "descartado"


def test_llm_que_estoura_nao_derruba_o_card():
    def explode(*_a, **_k):
        raise RuntimeError("fora do ar")

    r = X11.avaliar(_ctx(_OBRA, ["Prestação de serviços contínuos de vigilância"], gerar=explode))
    assert r.status == "confirmado"          # o T2 objetivo sobrevive
    assert r.valores["sem_rubrica"] is True


# ───────────────────────── medida de similaridade ─────────────────────────────────────────────

def test_similaridade_ignora_burocratês():
    """'Constitui objeto do presente instrumento' aparece em tudo e não informa nada."""
    a = "Constitui objeto do presente instrumento a execução de obra de pavimentação"
    b = "Constitui objeto do presente termo aditivo o fornecimento de medicamentos"
    assert similaridade(a, b) < 0.2


def test_similaridade_reconhece_o_mesmo_objeto():
    assert similaridade(_OBRA, _OBRA) == pytest.approx(1.0)


def test_similaridade_com_texto_vazio_e_zero():
    assert similaridade("", _OBRA) == 0.0


# ───────────────────────── contrato de saída ──────────────────────────────────────────────────

def test_explicacao_inocente_explica_o_delta():
    r = X11.avaliar(_ctx(_OBRA, ["Prestação de serviços contínuos de vigilância"]))
    assert "descreve o DELTA" in r.explicacao_inocente
    assert "planilha comparada" in r.explicacao_inocente


def test_evidencia_tem_hash_e_fonte():
    r = X11.avaliar(_ctx(_OBRA, ["Prestação de serviços contínuos de vigilância"]))
    for e in r.evidencia:
        assert e["hash"] and e["fonte"] and e["capturado_em"]
