"""Dicionário oficial da natureza da despesa (Portaria STN/SOF 163/2001).

O que se trava aqui: (1) elementos que NÃO EXISTEM não podem ter sido inventados pela extração;
(2) o subelemento nunca ganha rótulo, porque é de livre definição do ente.
"""
import pytest

from compliance_agent.pcrj import natureza_despesa as N


def test_elementos_inexistentes_nao_foram_inventados():
    """Regressão da armadilha da extração: a Portaria traz DUAS listas de códigos de dois
    dígitos (modalidades e elementos), e varrer o documento inteiro faz uma vazar na outra.
    A lista de elementos salta de 39 direto para 41 — 40, 50, 60 e 90 não existem."""
    for c in ("40", "50", "60", "90", "02"):
        assert N.ELEMENTOS.get(c) is None, f"elemento {c} não existe na Portaria 163"


def test_elementos_conhecidos_estao_corretos():
    assert N.ELEMENTOS["30"] == "Material de Consumo"
    assert N.ELEMENTOS["39"] == "Outros Serviços de Terceiros - Pessoa Jurídica"
    assert N.ELEMENTOS["36"] == "Outros Serviços de Terceiros - Pessoa Física"
    assert N.ELEMENTOS["51"] == "Obras e Instalações"
    assert N.ELEMENTOS["52"] == "Equipamentos e Material Permanente"
    assert N.ELEMENTOS["61"] == "Aquisição de Imóveis"
    assert N.ELEMENTOS["91"] == "Sentenças Judiciais"


def test_decomposicao_por_posicao():
    d = N.descrever("33903911")
    assert d["categoria"] == "Despesa Corrente"
    assert d["grupo"] == "Outras Despesas Correntes"
    assert d["modalidade"] == "Aplicações Diretas"
    assert d["elemento"] == "Outros Serviços de Terceiros - Pessoa Jurídica"
    assert d["codigo_elemento"] == "39" and d["codigo_subelemento"] == "11"


def test_modalidade_50_e_transferencia_a_entidade_privada():
    assert "sem Fins Lucrativos" in N.modalidade("33503901")


def test_investimento_e_grupo_4():
    assert N.grupo("44905202") == "Investimentos"
    assert N.elemento("44905202") == "Equipamentos e Material Permanente"


def test_subelemento_nunca_ganha_rotulo():
    """É desdobramento de livre definição do ente. Dizer que '30.04 é vestuário' porque os
    credores são confecções transformaria inferência em fato dentro de um relatório."""
    assert N.subelemento("33903004") is None
    d = N.descrever("33903004")
    assert d["codigo_subelemento"] == "04" and d["subelemento"] is None
    assert "livre definição" in d["_nota_subelemento"]


def test_codigo_desconhecido_e_none_nunca_outros():
    assert N.elemento("33902811") is None or isinstance(N.elemento("33902811"), str)
    assert N.elemento("") is None
    assert N.grupo("") is None


def test_natureza_curta_demais_nao_explode():
    d = N.descrever("339")
    assert d["elemento"] is None and d["codigo_elemento"] is None


def test_lista_de_nao_contratuais_so_tem_elementos_reais():
    """Se um código dessa lista não existe na Portaria, o corte do universo está errado."""
    faltando = [c for c in N.ELEMENTOS_NAO_CONTRATUAIS if c not in N.ELEMENTOS]
    assert not faltando, f"códigos fora da Portaria: {faltando}"


def test_universo_usa_a_mesma_lista():
    """Uma definição, dois usuários — cópia divergente é o erro que a casa já catalogou."""
    from compliance_agent.pcrj.universo import ELEMENTOS_FORA
    assert ELEMENTOS_FORA == dict(N.ELEMENTOS_NAO_CONTRATUAIS)


def test_elementos_de_contratacao_ficam_DENTRO_do_universo():
    from compliance_agent.pcrj.universo import ELEMENTOS_FORA
    for c in ("30", "39", "37", "51", "52", "61", "35"):
        assert c not in ELEMENTOS_FORA, f"elemento {c} é contratação e não pode ser excluído"
