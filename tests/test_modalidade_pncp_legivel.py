"""A modalidade do PNCP sai LEGIVEL e nunca afirma disputa onde nao ha.

Dois defeitos achados em 25/07/2026 na familia de transparencia do indice de certame:

1. o dossie escrevia "modalidade 6" — codigo cru num ENTREGAVEL —, embora a tabela de
   dominio (`MODALIDADE_NOME`, do Manual de Integracao do PNCP) existisse no projeto e
   nunca tivesse sido usada em lugar nenhum;
2. o `else` afirmava "procedimento com disputa" para QUALQUER codigo fora de 8 e 9. Mas
   credenciamento (12) contrata todos os que atendem aos requisitos, SEM disputa entre eles
   (Lei 14.133 art. 79) — seria afirmacao falsa num documento de fiscalizacao. Latente
   hoje (o coletor so traz 4, 6, 8 e 9), vivo no dia em que alguem ampliar MODALIDADES_PADRAO.
"""
import pytest

from compliance_agent.editais.indice_certame import _f_transparencia

CTX = lambda mod: {"tem_dado": True, "modalidade": mod, "data_pub": "2025-01-01"}


def _direta(mod: int) -> dict:
    return [f for f in _f_transparencia(CTX(mod))["flags"] if f["flag"] == "contratacao_direta"][0]


@pytest.mark.parametrize("mod,nome", [
    (4, "Concorrencia-Eletronica"), (6, "Pregao-Eletronico"),
    (8, "Dispensa"), (9, "Inexigibilidade"), (12, "Credenciamento"),
])
def test_o_nome_da_modalidade_aparece_junto_do_codigo(mod, nome):
    """Entregável não mostra código cru — o nome vem junto."""
    assert nome in _direta(mod)["evidencia"]


def test_sem_disputa_pontua_e_com_disputa_nao():
    assert _direta(9)["valor"] == 1.0      # inexigibilidade: discricionariedade pura
    assert _direta(8)["valor"] == 0.7      # dispensa: hipóteses objetivas
    assert _direta(6)["valor"] == 0.0      # pregão eletrônico: há disputa
    assert _direta(4)["valor"] == 0.0      # concorrência eletrônica: há disputa


def test_credenciamento_NAO_e_procedimento_com_disputa():
    """O defeito principal: credenciamento caía no `else` e era declarado com disputa."""
    f = _direta(12)
    assert "sem disputa" in f["evidencia"]
    assert "procedimento com disputa" not in f["evidencia"]
    assert 0 < f["valor"] < _direta(8)["valor"], "credenciamento fica entre 'com disputa' e dispensa"


def test_codigo_desconhecido_nao_afirma_nada():
    """Fora da tabela de domínio, o painel diz que não sabe — INDISPONÍVEL ≠ com disputa."""
    f = _direta(99)
    assert "INDISPON" in f["evidencia"].upper()
    assert "procedimento com disputa" not in f["evidencia"]
    assert f["valor"] == 0.0


def test_sem_registro_no_pncp_continua_indisponivel():
    fam = _f_transparencia({"tem_dado": False, "modalidade": None, "data_pub": None})
    assert fam["apuravel"] is False and fam["valor"] is None
