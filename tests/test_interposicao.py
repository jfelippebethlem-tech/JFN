# -*- coding: utf-8 -*-
"""Perfil de interposição — e as quatro maneiras de o número mentir aqui.

  1. **Faixa 0 lida como idade zero.** O código RFB `0` significa "não se aplica" (sócio pessoa
     jurídica). Tratá-lo como bebê produziria um exército de falsos laranjas.
  2. **Corte absoluto de multiplicidade.** "Sócio em 5+ empresas" transforma contador e
     administrador profissional em suspeito. O corte tem de sair da própria base.
  3. **`None` colapsado em `False`.** Eixo não olhado não é eixo limpo — é a origem do "0 achado"
     que mente.
  4. **CPF mascarado tratado como identidade.** 4% dos documentos da base carregam mais de um nome.

Tudo em SQLite de memória: nenhum teste aqui toca a base real.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.osint import interposicao as it


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE socios_receita(cnpj_basico TEXT, nome_socio TEXT, nome_norm TEXT, "
              "doc_socio TEXT, qualificacao_txt TEXT, data_entrada TEXT, faixa_etaria TEXT)")
    c.execute("CREATE TABLE socios_reverso(doc_socio TEXT, nome_socio TEXT, nome_norm TEXT, "
              "cnpj_basico TEXT)")
    return c


def _socio(c, cnpj="12345678", nome="JOAO DA SILVA", doc="***111222**", faixa="5",
           entrada="20240101", qual="49-Sócio-Administrador"):
    c.execute("INSERT INTO socios_receita VALUES(?,?,?,?,?,?,?)",
              (cnpj, nome, nome, doc, qual, entrada, faixa))


def _reverso(c, doc, nome, n):
    for i in range(n):
        c.execute("INSERT INTO socios_reverso VALUES(?,?,?,?)", (doc, nome, nome, f"{i:08d}"))


# ───────────────────────────── 1. faixa etária ────────────────────────────────────────────────

@pytest.mark.parametrize("faixa,acende", [("1", True), ("2", True),
                                          ("4", False), ("5", False), ("7", False), ("9", False)])
def test_idade_extrema_acende_so_no_socio_JOVEM_demais(con, faixa, acende):
    """Medido: 0–12 anos é 0,02% da base e 13–20 é 0,29% — raridade que sustenta indício."""
    _socio(con, faixa=faixa)
    r = it.avaliar(con, "12345678000199")
    assert r["socios"][0]["eixos"]["idade_extrema"] is acende


def test_socio_com_mais_de_80_e_OBSERVACAO_nao_indicio(con):
    """1,87% da base tem sócio acima de 80 — dono idoso de empresa familiar é o normal. Tratá-lo
    como sinal enchia o topo do ranking de fundadores, e foi o que a calibração real mostrou."""
    _socio(con, faixa="9")
    r = it.avaliar(con, "12345678000199")
    p = r["socios"][0]
    assert p["eixos"]["idade_extrema"] is False and p["idade_avancada"] is True
    assert r["grau"] == "sem_sinal"
    assert "observação, não indício" in " ".join(p["evidencias"])


def test_quadro_de_um_so_socio_NAO_e_eixo(con):
    """54,9% das empresas da base têm um só sócio. Eixo que acende na maioria mede a base."""
    _socio(con)
    r = it.avaliar(con, "12345678000199")
    assert r["quadro_raso"] is True, "a característica continua declarada"
    assert r["grau"] == "sem_sinal", "mas não produz achado sozinha"
    assert "quadro_raso" not in it.EIXOS


def test_faixa_zero_e_pessoa_juridica_nao_bebe(con):
    """`0` = 'não se aplica' na RFB. Lê-lo como idade produziria falso laranja em massa."""
    _socio(con, faixa="0")
    assert it.avaliar(con, "12345678000199")["socios"][0]["eixos"]["idade_extrema"] is None


def test_faixa_ausente_fica_none_e_nao_false(con):
    _socio(con, faixa="")
    assert it.avaliar(con, "12345678000199")["socios"][0]["eixos"]["idade_extrema"] is None


# ───────────────────────────── 2. multiplicidade ──────────────────────────────────────────────

def test_corte_sai_da_base_e_nao_de_numero_escolhido_a_dedo(con):
    for i in range(100):
        _reverso(con, f"***{i:06d}**", f"PESSOA {i}", 1 if i < 99 else 40)
    c = it.corte_multiplicidade(con)
    assert c["n_socios"] == 100 and c["mediana"] == 1
    assert c["corte"] >= it.MINIMO_EMPRESAS, "o piso protege base pequena"
    assert "mediana" in c["regra"], "a régua sai declarada com o número"


def test_socio_de_muitas_empresas_nao_acende_se_a_base_toda_e_assim(con):
    """Mercado regional em que todo mundo é sócio de muitas: o percentil acompanha, o absoluto não."""
    for i in range(50):
        _reverso(con, f"***{i:06d}**", f"PESSOA {i}", 20)
    _socio(con, doc="***000001**", nome="PESSOA 1")
    r = it.avaliar(con, "12345678000199")
    assert r["socios"][0]["eixos"]["multiplicidade"] is False


def test_socio_atipico_acende(con):
    for i in range(99):
        _reverso(con, f"***{i:06d}**", f"PESSOA {i}", 1)
    _reverso(con, "***999999**", "MARIA LARANJA", 60)
    _socio(con, doc="***999999**", nome="MARIA LARANJA")
    r = it.avaliar(con, "12345678000199")
    assert r["socios"][0]["eixos"]["multiplicidade"] is True
    assert "60 empresas" in " ".join(r["socios"][0]["evidencias"])


def test_multiplicidade_conta_pelo_par_documento_nome_nao_so_documento(con):
    """4% dos documentos mascarados da base carregam mais de um nome — contar pelo documento
    somaria as empresas de pessoas diferentes."""
    for i in range(99):
        _reverso(con, f"***{i:06d}**", f"PESSOA {i}", 1)
    _reverso(con, "***777777**", "ANA UM", 2)
    _reverso(con, "***777777**", "BRUNO DOIS", 55)   # mesmo documento, outra pessoa
    _socio(con, doc="***777777**", nome="ANA UM")
    r = it.avaliar(con, "12345678000199")
    assert r["socios"][0]["eixos"]["multiplicidade"] is False, "somou as empresas do homônimo"


# ───────────────────────────── 3. entrada recente ─────────────────────────────────────────────

def test_entrada_as_vesperas_acende(con):
    _socio(con, entrada="20240301")
    r = it.avaliar(con, "12345678000199", data_referencia="2024-04-15")
    assert r["socios"][0]["eixos"]["entrada_recente"] is True


def test_entrada_antiga_nao_acende(con):
    _socio(con, entrada="20150301")
    r = it.avaliar(con, "12345678000199", data_referencia="2024-04-15")
    assert r["socios"][0]["eixos"]["entrada_recente"] is False


def test_entrada_POSTERIOR_a_referencia_nao_acende(con):
    """Sócio que entrou DEPOIS do certame não foi posto para ganhá-lo — é outro fato."""
    _socio(con, entrada="20250301")
    r = it.avaliar(con, "12345678000199", data_referencia="2024-04-15")
    assert r["socios"][0]["eixos"]["entrada_recente"] is False


def test_sem_data_de_referencia_o_eixo_fica_none(con):
    _socio(con, entrada="20240301")
    assert it.avaliar(con, "12345678000199")["socios"][0]["eixos"]["entrada_recente"] is None


# ───────────────────────────── 4. grau e honestidade ──────────────────────────────────────────

def test_empresa_sem_quadro_na_base_e_nao_aferivel_nao_limpa(con):
    r = it.avaliar(con, "99999999000100")
    assert r["grau"] == "nao_aferivel" and r["n_socios"] == 0
    assert "parcial" in r["motivo"]


def test_grau_declara_quantos_eixos_foram_OLHADOS(con):
    """Um eixo aceso de um olhado não é o mesmo indício que um aceso de cinco."""
    _socio(con, faixa="1")
    r = it.avaliar(con, "12345678000199")
    assert r["eixos_acesos"] >= 1 and r["eixos_olhados"] >= r["eixos_acesos"]
    assert r["eixos_possiveis"] == len(it.EIXOS)


def test_quadro_com_socio_menor_e_multiplicidade_sobe_para_forte(con):
    for i in range(99):
        _reverso(con, f"***{i:06d}**", f"PESSOA {i}", 1)
    _reverso(con, "***999999**", "CRIANCA LARANJA", 60)
    _socio(con, doc="***999999**", nome="CRIANCA LARANJA", faixa="1")
    assert it.avaliar(con, "12345678000199")["grau"] == "forte"


def test_quadro_normal_nao_produz_alarme(con):
    for i in range(99):
        _reverso(con, f"***{i:06d}**", f"PESSOA {i}", 1)
    _socio(con, doc="***000005**", nome="PESSOA 5", faixa="5", entrada="20150101")
    _socio(con, doc="***000006**", nome="PESSOA 6", faixa="6", entrada="20150101")
    r = it.avaliar(con, "12345678000199", data_referencia="2024-04-15")
    assert r["grau"] == "sem_sinal" and r["quadro_raso"] is False


def test_servidor_so_entra_quando_o_conjunto_e_fornecido(con):
    _socio(con, nome="JOAO DA SILVA")
    assert it.avaliar(con, "12345678000199")["socios"][0]["eixos"]["servidor"] is None
    r = it.avaliar(con, "12345678000199", servidores={"JOAO DA SILVA"})
    assert r["socios"][0]["eixos"]["servidor"] is True


def test_lacunas_saem_nomeadas_nao_omitidas(con):
    """Eixo que a base não sustenta é lacuna DECLARADA — omiti-lo faria 3 de 5 parecer 5 de 5."""
    _socio(con)
    r = it.avaliar(con, "12345678000199")
    assert len(r["lacunas"]) == 2
    assert any("pessoa física" in x for x in r["lacunas"])


def test_ressalva_do_cpf_mascarado_viaja_com_o_resultado(con):
    _socio(con)
    assert "não é identidade" in it.avaliar(con, "12345678000199")["ressalva"]
    assert "não é identidade" in it.avaliar(con, "99999999000100")["ressalva"]
