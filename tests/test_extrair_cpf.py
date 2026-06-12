# -*- coding: utf-8 -*-
"""Testes do extrator de CPF+nome de documentos SEI (validação de dígito verificador = verdade conclusiva)."""
from compliance_agent.sei.extrair_cpf import extrair_cpfs, validar_cpf

# CPFs com DV válido (gerados/conhecidos válidos)
CPF_OK = "529.982.247-25"   # válido (exemplo clássico de teste)
CPF_OK2 = "111.444.777-35"  # válido


def test_valida_dv():
    assert validar_cpf(CPF_OK) and validar_cpf("52998224725")
    assert validar_cpf(CPF_OK2)
    assert not validar_cpf("123.456.789-00")   # DV errado
    assert not validar_cpf("111.111.111-11")   # repetido
    assert not validar_cpf("123")              # curto


def test_extrai_cpf_valido_com_nome():
    txt = "Sócio-administrador JOÃO DA SILVA SANTOS, brasileiro, inscrito no CPF nº 529.982.247-25, residente..."
    r = extrair_cpfs(txt)
    assert len(r) == 1 and r[0]["cpf"] == "52998224725"
    assert "SILVA" in r[0]["nome"].upper() or "João" in r[0]["nome"]


def test_descarta_numero_processo_invalido():
    # 11 dígitos que NÃO são CPF (nº de processo) não devem ser extraídos
    txt = "Processo SEI 080001000123456 e protocolo 12345678900 referente ao desembolso."
    assert extrair_cpfs(txt) == []


def test_descarta_cpf_dv_errado():
    txt = "CPF 123.456.789-00 citado em rodapé."  # DV inválido
    assert extrair_cpfs(txt) == []


def test_dedup_por_cpf():
    txt = f"Fulano CPF {CPF_OK} ... e novamente {CPF_OK} no mesmo doc."
    r = extrair_cpfs(txt)
    assert len(r) == 1


def test_multiplos_socios():
    txt = ("MARIA SOUZA LIMA, CPF 111.444.777-35; e PEDRO ALVES COSTA, inscrito no CPF 529.982.247-25.")
    r = extrair_cpfs(txt)
    cpfs = {x["cpf"] for x in r}
    assert cpfs == {"11144477735", "52998224725"}
