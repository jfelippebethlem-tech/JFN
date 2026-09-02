# -*- coding: utf-8 -*-
"""Dependência mútua — fornecedor preso a uma unidade que também depende dele.

O que estes testes protegem: o DENOMINADOR. A fatia da unidade tem de ser calculada sobre TUDO
que ela pagou — inclusive folha, prêmios e precatórios, que não trazem CNPJ no campo `credor`.
Medido em 2026-08-24: com o filtro de 14 dígitos aplicado aos dois lados, a MCE aparecia com
68,0% da LOTERJ quando o real é 38,0%, porque R$ 127,7 mi de folha e prêmios ficavam fora do
denominador. Viés sistemático e sempre para cima; o corte caiu de 71 para 34 fornecedores.
"""
import sqlite3

from tools.dependencia_mutua import dependencia


def _banco():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (credor TEXT, ug_emitente TEXT, valor REAL,"
                " nome_credor TEXT, status TEXT)")
    con.execute("CREATE TABLE empresas_cadastro (cnpj_basico TEXT, natureza_cod TEXT)")
    return con


def test_folha_sem_cnpj_ENTRA_no_denominador():
    """A unidade pagou 10 mi ao fornecedor e 10 mi de folha: a fatia dele é 50%, não 100%."""
    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('11111111','2062')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('11111111000199','203100',1e7,'X','Contabilizado')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('FOLHA DE PAGAMENTOS','203100',1e7,"
                "'FOLHA DE PAGAMENTOS','Contabilizado')")
    r = dependencia(con)
    assert len(r) == 1
    assert abs(r[0]["fatia_ug"] - 0.5) < 1e-9, (
        f"fatia {r[0]['fatia_ug']:.3f} — folha ficou fora do denominador e inflou a fatia")


def test_concentracao_do_fornecedor_nao_muda():
    """A concentração é do lado DELE (quanto do que recebe vem de 1 UG) — folha não entra nela."""
    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('11111111','2062')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('11111111000199','203100',1e7,'X','Contabilizado')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('FOLHA','203100',1e7,'FOLHA','Contabilizado')")
    assert dependencia(con)[0]["concentracao"] == 1.0


def test_ob_nao_contabilizada_fica_fora_dos_dois_lados():
    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('11111111','2062')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('11111111000199','203100',1e7,'X','Anulado')")
    assert dependencia(con) == []


def test_repasse_e_natureza_nao_empresarial_saem():
    """Fundo/OSS recebem TRANSFERÊNCIA, não contrato — 100% numa UG é o desenho, não captura."""
    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('22222222','3999')")   # associação
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('22222222000199','203100',1e7,"
                "'INSTITUTO X','Contabilizado')")
    con.execute("INSERT INTO empresas_cadastro VALUES ('33333333','2062')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('33333333000199','203100',1e7,"
                "'FUNDO MUNICIPAL DE SAUDE','Contabilizado')")
    assert dependencia(con) == []
    assert len(dependencia(con, com_repasse=True)) == 2, "o modo de conferência deve mostrar tudo"
