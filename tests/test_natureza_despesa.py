"""Dicionário oficial da natureza da despesa (Portaria STN/SOF 163/2001).

O que se trava aqui: (1) elementos que NÃO EXISTEM não podem ter sido inventados pela extração;
(2) o subelemento nunca ganha rótulo, porque é de livre definição do ente.
"""
import pytest

from compliance_agent.pcrj import natureza_despesa as N


def test_elementos_inexistentes_nao_foram_inventados():
    """Regressão da armadilha da extração: a Portaria traz DUAS listas de códigos de dois
    dígitos (modalidades e elementos), e varrer o documento inteiro faz uma vazar na outra.
    Na consolidação de 2014, a lista salta de 39 direto para 41.

    ⚠️ O 40 SAIU desta lista: ele não está na consolidação de 2014, mas foi CRIADO pela Portaria
    Conjunta STN/SOF nº 02/2017 e o Município usa. Eu o havia removido por engano, e o custo foi
    perder 10 casos legítimos da lente de pessoa física em elemento de PJ."""
    for c in ("50", "60", "90", "02"):
        assert N.ELEMENTOS.get(c) is None, f"elemento {c} não existe na Portaria 163"


def test_elementos_criados_depois_da_consolidacao_de_2014():
    """A tabela tem VERSÃO. Sem estes três, R$ 6,51 bi do acervo ficavam sem rótulo."""
    assert N.ELEMENTOS["40"].startswith("Serviços de Tecnologia da Informação")
    assert "Parceria Público-Privada" in N.ELEMENTOS["82"]
    assert N.ELEMENTOS["85"] == "Contrato de Gestão"
    for c, (_, norma) in N.ELEMENTOS_POSTERIORES.items():
        assert len(norma) > 20 and ("Portaria" in norma or "Lei" in norma), c


def test_controle_positivo_contra_o_acervo():
    """A tabela tem de cobrir os códigos que o Município REALMENTE usa. Foi este controle que
    denunciou a falta dos elementos 40, 82 e 85 — R$ 6.514.285.739,62 sem rótulo."""
    import sqlite3
    from pathlib import Path
    db = Path("data/compliance.db")
    if not db.exists():
        pytest.skip("compliance.db ausente")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        usados = {r[0]: r[1] for r in con.execute(
            "SELECT substr(natureza,5,2), sum(pago) FROM pcrj_despesa WHERE pago > 0 GROUP BY 1")}
    except sqlite3.OperationalError:
        pytest.skip("pcrj_despesa ausente")
    finally:
        con.close()
    sem_rotulo = {c: v for c, v in usados.items()
                  if c not in N.ELEMENTOS and c not in N.ELEMENTOS_NAO_IDENTIFICADOS}
    assert not sem_rotulo, (
        f"o acervo usa elementos que a tabela não conhece nem declara: {sem_rotulo}")


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
