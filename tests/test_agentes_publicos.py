# -*- coding: utf-8 -*-
"""Extração de gestores, fiscais e ordenadores do texto do SEI.

Os trechos abaixo são reproduções dos formatos REAIS encontrados em `data/sei_arquivo/`
(2.055 processos) — inclusive os que produziram falso positivo na primeira varredura.
"""
import pytest

from compliance_agent.sei import agentes_publicos as ap


# ------------------------------------------------------------------ nome plausível

@pytest.mark.parametrize("nome", [
    "Everton Medeiros", "Tayane Cordeiro Palma de Holanda", "SERGIO MICHELOTTO BRAGA",
    "Luís Alberto Miranda Garcia de Sousa",
])
def test_aceita_nome_de_gente(nome):
    assert ap.nome_plausivel(nome)


@pytest.mark.parametrize("nao_nome,porque", [
    ("Nota Fiscal", "documento, não pessoa"),
    ("Comissão de Fiscalização", "órgão colegiado"),
    ("Secretaria de Estado", "unidade administrativa"),
    ("Maj PM De", "posto e sigla — extraído como gestor na 1ª varredura do acervo"),
    ("Aquisição de Motos", "objeto da compra"),
    ("Everton", "uma palavra só"),
])
def test_recusa_o_que_nao_e_pessoa(nao_nome, porque):
    assert not ap.nome_plausivel(nao_nome), porque


def test_nome_nunca_atravessa_quebra_de_linha():
    """Com `\\s+` no separador, 'Aquisição de Motos Aquáticas\\nAnexos' virava nome de fiscal."""
    assert not ap.nome_plausivel("Motos Aquáticas\nAnexos")


# ------------------------------------------------------------------ bloco de assinatura

_HOMOLOGACAO = """ATO DE HOMOLOGAÇÃO
HOMOLOGO a presente licitação, na modalidade Pregão Eletrônico nº PERP 02/2023.

EVERTON MEDEIROS
Subsecretário de Logística
Ordenador de Despesas
Rio de Janeiro, 05 de fevereiro de 2024
"""


def test_le_o_bloco_de_assinatura_nome_cargo_papel():
    ag = ap.extrair_agentes(_HOMOLOGACAO)
    assert len(ag) == 1
    a = ag[0]
    assert a.nome == "EVERTON MEDEIROS"
    assert a.papel == "ordenador_despesa"
    assert a.cargo == "Subsecretário de Logística"
    assert a.origem == "assinatura"
    assert a.decisorio is True


# ------------------------------------------------------------------ rótulo inline

def test_rotulo_inline_com_nome():
    ag = ap.extrair_agentes("Gestor do Contrato: Tadeu Gomes da Costa\nFiscal: André Luiz Gama Filho")
    papeis = {a.papel: a.nome for a in ag}
    assert papeis["gestor_contrato"] == "Tadeu Gomes da Costa"
    assert papeis["fiscal_contrato"] == "André Luiz Gama Filho"


def test_fiscal_tecnico_nao_vira_fiscal_generico():
    ag = ap.extrair_agentes("Fiscal Técnico: Washington Luiz Sanandrez Teixeira")
    assert ag[0].papel == "fiscal_tecnico"


@pytest.mark.parametrize("ruido", [
    "Fiscal - NF 313028",
    "Fiscal: Nota Fiscal eletrônica de serviço",
    "Fiscal - IBS/CBS conforme reforma",
    "FISCAL - Relator: Conselheiro Antonio Lopes Caetano",
    "Fiscal – Empresa DIAGNÓSTICA SUDESTE SERVIÇOS LTDA",
])
def test_armadilhas_do_acervo_nao_viram_pessoa(ruido):
    """Todos colhidos do acervo real: 'Fiscal' seguido de documento, tributo, relator ou empresa."""
    assert ap.extrair_agentes(ruido) == []


# ------------------------------------------------------------------ designação formal

_DESIGNACAO = ("Art. 2º - Designar o servidor Rodolfo da Rocha Varize , Chefe de Serviço, "
               "ID funcional nº 5143197-1, como Fiscal do Contrato nº 12/2024.")


def test_designacao_captura_id_funcional():
    ag = ap.extrair_agentes(_DESIGNACAO)
    assert any(a.id_funcional == "5143197-1" for a in ag)
    assert any(a.nome == "Rodolfo da Rocha Varize" for a in ag)


def test_designacao_sem_papel_no_contexto_nao_inventa_papel():
    assert ap.extrair_agentes("Designar o servidor Rodolfo da Rocha Varize para a comissão.") == []


def test_id_funcional_vence_na_deduplicacao():
    texto = ("Fiscal do Contrato: Rodolfo da Rocha Varize\n"
             "Designar o servidor Rodolfo da Rocha Varize, Chefe, ID funcional nº 5143197-1, "
             "como Fiscal do Contrato.")
    ag = [a for a in ap.extrair_agentes(texto) if a.nome == "Rodolfo da Rocha Varize"]
    assert len(ag) == 1 and ag[0].id_funcional == "5143197-1"


# ------------------------------------------------------------------ ficha do processo

def test_execucao_sem_fiscal_designado_vira_lacuna_com_fundamento():
    f = ap.montar_ficha("SEI-123", {
        "doc1": _HOMOLOGACAO,
        "doc2": "Segue a medição nº 3 e a respectiva nota fiscal para liquidação.",
    })
    assert any("117" in l for l in f.lacunas), "tem de citar o art. 117 da Lei 14.133"
    assert f.decisores and f.decisores[0].nome == "EVERTON MEDEIROS"


def test_lacuna_nao_e_acusacao():
    """A regra do projeto: LACUNA DE CAPTURA ≠ INEXISTÊNCIA."""
    f = ap.montar_ficha("SEI-123", {"d": "medição e nota fiscal"})
    assert any("não foi capturado" in l for l in f.lacunas)


def test_ausencia_de_ordenador_e_apontada():
    f = ap.montar_ficha("SEI-1", {"d": "Fiscal: André Luiz Gama Filho"})
    assert any("ordenador" in l.lower() for l in f.lacunas)
    assert f.decisores == []


def test_segregacao_de_funcoes_quando_ordenador_tambem_fiscaliza():
    texto = """EVERTON MEDEIROS
Subsecretário de Logística
Ordenador de Despesas

Fiscal do Contrato: Everton Medeiros
Segue medição para liquidação.
"""
    f = ap.montar_ficha("SEI-9", {"d": texto})
    assert any("SEGREGAÇÃO" in a for a in f.alertas)
    assert any("art. 5º" in a for a in f.alertas)


def test_ficha_sem_execucao_nao_cobra_fiscal():
    f = ap.montar_ficha("SEI-2", {"d": _HOMOLOGACAO})
    assert not any("117" in l for l in f.lacunas)


def test_resumo_texto_monta_tabela_e_alertas():
    f = ap.montar_ficha("SEI-3", {"d": _HOMOLOGACAO})
    r = ap.resumo_texto(f)
    assert "| Ordenador de Despesas | EVERTON MEDEIROS |" in r
    assert "SEI-3" in r


def test_resumo_vazio_quando_nada_encontrado():
    f = ap.FichaResponsabilidade(processo="X")
    assert ap.resumo_texto(f) == ""


@pytest.mark.parametrize("titulo", [
    "[Nota Fiscal - NFs Consig. - SEI-5355-2026 (131593503)]",
    "Nota Fiscal - NFs CONSIG (85664531)",
    "Nota Fiscal: Materiais Diversos",
    "DANFE Fiscal - Item Unico",
])
def test_titulo_de_nota_fiscal_nao_produz_pessoa(titulo):
    """'NFs Consig' entrou como fiscal de contrato em 6 processos do acervo real.

    A lista de ruído barrava 'NF' com limite de palavra e o 's' de 'NFs' furava o \\b. A guarda
    boa é a palavra ANTERIOR: se vem 'Nota'/'DANFE' antes de 'Fiscal', é documento, não gente.
    """
    assert ap.extrair_agentes(titulo) == []


def test_fiscal_legitimo_continua_passando_apos_a_guarda():
    """A guarda não pode cegar o caso bom."""
    ag = ap.extrair_agentes("Fiscal do Contrato: Gustavo Silva Trovão")
    assert ag and ag[0].nome == "Gustavo Silva Trovão"
