"""INDISPONIVEL != irregular, agora em codigo e travado por teste.

Medido no acervo: 59% das red flags do sweep SEI eram queixa de CAPTURA ("ausencia de
informacao sobre a modalidade"), nao vicio do processo — e 874 processos so tinham
flags desse tipo, dos quais 19 receberam risco ALTO. Este teste impede a volta.
"""
import json

import pytest

from compliance_agent.sei_triagem_flags import (
    classificar_flag, encaminhamento, risco_sustentado, triar,
)

# frases REAIS colhidas do acervo (as duas familias)
LACUNAS = [
    "Ausência de informação sobre a modalidade de contratação",
    "Ausência de documentos instrutivos da contratação (edital, proposta)",
    "Não consta o CNPJ do favorecido no trecho analisado",
    "Sem informação sobre o objeto da contratação",
    "Não foi possível identificar o fundamento legal",
    "Falta de detalhamento da pesquisa de preços",
]
ACHADOS = [
    "Valor elevado da despesa (R$ 1.719.165,00) sem comprovação de vantajosidade",
    "Reconhecimento de dívida de competência de dezembro de 2024 com liquidação e "
    "pagamento em exercício seguinte",
    "Valor elevado (R$ 3,26 milhões) sem demonstração de lastro contratual",
]


@pytest.mark.parametrize("t", LACUNAS)
def test_queixa_de_captura_e_lacuna(t):
    assert classificar_flag(t) == "lacuna"


@pytest.mark.parametrize("t", ACHADOS)
def test_fato_sobre_o_processo_e_achado(t):
    assert classificar_flag(t) == "achado"


def test_processo_so_com_lacuna_vai_para_o_COLETOR_nao_para_o_fiscal():
    assert encaminhamento(LACUNAS) == "recapturar"
    assert triar(LACUNAS)["so_lacuna"] is True
    assert triar(LACUNAS)["n_achado"] == 0


def test_um_achado_no_meio_de_lacunas_ja_manda_apurar():
    """A lacuna não anula o achado — basta UM fato para o processo virar fila real."""
    mistura = LACUNAS + [ACHADOS[0]]
    assert encaminhamento(mistura) == "apurar"
    t = triar(mistura)
    assert t["n_achado"] == 1 and t["n_lacuna"] == len(LACUNAS)
    assert t["so_lacuna"] is False


def test_sem_flag_nenhuma_nao_e_so_lacuna():
    """Ausência de flag não é 'mal capturado' — não há o que triar."""
    for vazio in ([], None, "", "[]"):
        assert triar(vazio)["so_lacuna"] is False
        assert encaminhamento(vazio) == "sem_sinal"


def test_aceita_o_json_cru_do_banco():
    """`red_flags` vive como texto JSON em `sei_ficha` — não obrigar o chamador a decodificar."""
    assert triar(json.dumps(ACHADOS, ensure_ascii=False))["n_achado"] == 3
    assert triar('nao e json valido')["n_achado"] == 0


def test_alto_sem_achado_e_rebaixado_COM_a_razao_dita():
    nivel, ressalva = risco_sustentado("alto", LACUNAS)
    assert nivel == "indisponivel"
    assert ressalva and "recapturar" in ressalva

def test_alto_com_achado_permanece_alto():
    nivel, ressalva = risco_sustentado("alto", LACUNAS + [ACHADOS[1]])
    assert nivel == "alto" and ressalva is None


def test_baixo_nunca_e_mexido():
    """Só `alto`/`medio` prometem risco; rebaixar um `baixo` não teria sentido."""
    assert risco_sustentado("baixo", LACUNAS) == ("baixo", None)
