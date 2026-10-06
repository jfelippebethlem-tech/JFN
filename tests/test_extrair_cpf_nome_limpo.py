# -*- coding: utf-8 -*-
"""O nome extraído junto do CPF vinha com rótulo, sufixo e tipo de documento colados.

`extrair_cpfs` associa ao CPF o último trecho capitalizado da janela anterior. Como "Nome", "CTPS"
e "Contrato de Gestão" também são palavras capitalizadas, elas entram no nome — e aí o casamento
por `nome_norm` do resolver de CPF falha, porque compara "NOME MARCIO FREITAS DE OLIVEIRA" com
"MARCIO FREITAS DE OLIVEIRA".

Medido em 2026-08-12, cruzando os sócios mascarados contra o corpus de CPF completo: **122 casos**
em que o fragmento do CPF batia, havia um único candidato, e o nome só não fechava por esse tipo de
sujeira. São todos os exemplos abaixo — vieram do acervo real, não de imaginação:

    "NOME MARCIO FREITAS DE OLIVEIRA"              rótulo colado à esquerda
    "FELIPE OLIVEIRA BRUM DA COSTA CTPS"           sigla colada à direita
    "RODRIGO DA COSTA E"                           conectivo solto no fim
    "CONTRATO DE GESTAO SANDRO NATALINO DEMETRIO"  tipo de documento à esquerda

A limpeza é CONSERVADORA de propósito: na dúvida, devolve o nome como está. Nome de pessoa é a
chave de identificação de toda a perícia — cortar demais cria homônimo onde não havia, que é pior
que deixar sujeira.
"""
from __future__ import annotations

from compliance_agent.sei.extrair_cpf import limpar_nome


def test_tira_rotulo_colado_a_esquerda():
    assert limpar_nome("NOME MARCIO FREITAS DE OLIVEIRA") == "MARCIO FREITAS DE OLIVEIRA"
    assert limpar_nome("Nome Geraldo Andre De Miranda Santos") == "Geraldo Andre De Miranda Santos"


def test_tira_sigla_colada_a_direita():
    assert limpar_nome("FELIPE OLIVEIRA BRUM DA COSTA CTPS") == "FELIPE OLIVEIRA BRUM DA COSTA"
    assert limpar_nome("JOSE GABRIEL DA SILVA RG") == "JOSE GABRIEL DA SILVA"


def test_tira_conectivo_solto_no_fim():
    """Nome não termina em "e", "da" ou "de" — é a janela que cortou no meio."""
    assert limpar_nome("RODRIGO DA COSTA E") == "RODRIGO DA COSTA"
    assert limpar_nome("MARIA DAS DORES DE") == "MARIA DAS DORES"


def test_tira_tipo_de_documento_a_esquerda():
    assert limpar_nome("CONTRATO DE GESTAO SANDRO NATALINO DEMETRIO") == "SANDRO NATALINO DEMETRIO"
    assert limpar_nome("TERMO DE POSSE ANA LUCIA PEREIRA") == "ANA LUCIA PEREIRA"


def test_nome_limpo_passa_intacto():
    """A limpeza não pode inventar trabalho: nome já bom sai igual."""
    assert limpar_nome("MARCO AURELIO DAMATO PORTO") == "MARCO AURELIO DAMATO PORTO"
    assert limpar_nome("Ana Maria de Souza") == "Ana Maria de Souza"


def test_nao_corta_ate_sobrar_pouco():
    """CONSERVADORA: se limpar deixaria menos de duas palavras, devolve o original — nome curto
    demais casa com muita gente, e criar homônimo é pior que deixar sujeira."""
    assert limpar_nome("NOME SILVA") == "NOME SILVA"
    assert limpar_nome("CTPS") == "CTPS"


def test_vazio_e_none_nao_quebram():
    assert limpar_nome("") == ""
    assert limpar_nome(None) == ""


def test_o_extrator_ja_devolve_o_nome_limpo():
    from compliance_agent.sei.extrair_cpf import extrair_cpfs
    txt = "Responsável Nome MARCIO FREITAS DE OLIVEIRA CPF 106.060.657-76 assinado"
    pares = extrair_cpfs(txt)
    assert pares and pares[0]["cpf"] == "10606065776"
    assert not pares[0]["nome"].upper().startswith("NOME ")
