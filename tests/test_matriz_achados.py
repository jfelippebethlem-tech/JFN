# -*- coding: utf-8 -*-
"""Matriz de achados — célula sem fonte é o defeito que o módulo existe para impedir.

Uma célula vazia num relatório de diligence **não é espaço em branco**: é a afirmação de que ali
não há nada. E "não há nada" é diferente de "não olhei" — a distinção decide se cabe achado ou
pedido de diligência. Três estados, sempre explícitos.

E citação é CONFERIDA, não declarada: trecho que não existe na fonte derruba a célula, nunca vira
`aferido` por confiança.
"""
from __future__ import annotations

import pytest

from compliance_agent.reporting import matriz_achados as M

FONTE = ("O licitante deverá comprovar capital social mínimo de 15% do valor estimado da "
         "contratação, na forma do item 8.3 do edital.")


# ─────────────────── os três estados ──────────────────────────────────────────────────────────

def test_valor_com_documento_e_aferido():
    c = M.celula("15%", documento="Edital", localizador="item 8.3")
    assert c["estado"] == "aferido" and c["valor"] == "15%"


def test_valor_SEM_documento_nao_entra_como_aferido():
    """É o defeito que dá nome ao módulo: valor sem fonte é o que a matriz proíbe."""
    c = M.celula("15%", documento="")
    assert c["estado"] == "nao_observado" and c["valor"] is None
    assert "sem documento de origem" in c["motivo"]


def test_ausente_COM_documento_e_nao_consta():
    c = M.celula(None, documento="Edital", localizador="cap. 8")
    assert c["estado"] == "nao_consta"
    assert "procurado no documento" in c["motivo"]


def test_ausente_SEM_documento_e_nao_observado():
    """'Não consta' afirma que se olhou. Sem documento, ninguém olhou."""
    c = M.celula(None)
    assert c["estado"] == "nao_observado" and "lacuna de coleta" in c["motivo"]


# ─────────────────── a citação é conferida ────────────────────────────────────────────────────

def test_trecho_que_existe_na_fonte_ancora():
    c = M.celula("15%", documento="Edital", localizador="8.3",
                 trecho="capital social mínimo de 15%", fonte_texto=FONTE)
    assert c["estado"] == "aferido" and c["ancorado"] is True


def test_trecho_INVENTADO_derruba_a_celula():
    c = M.celula("15%", documento="Edital", localizador="8.3",
                 trecho="exigência de capital de 90% do valor", fonte_texto=FONTE)
    assert c["estado"] == "nao_observado" and c["ancorado"] is False
    assert "não sustenta célula aferida" in c["motivo"]


def test_sem_fonte_texto_a_ancoragem_nao_e_afirmada():
    """Não conferir não é conferir e dar certo — `ancorado` fica None."""
    c = M.celula("15%", documento="Edital", trecho="qualquer coisa")
    assert c["estado"] == "aferido" and c["ancorado"] is None


# ─────────────────── linha e campos decisivos ─────────────────────────────────────────────────

def _linha_completa():
    return M.linha("cláusula 8.3", {
        "exigencia": M.celula("capital 15%", documento="Edital", localizador="8.3"),
        "teto_legal": M.celula("10%", documento="Lei 14.133", localizador="art. 69"),
        "beneficiario": M.celula("ALFA LTDA", documento="Ata", localizador="fl. 12"),
    }, decisivos=("exigencia", "teto_legal"))


def test_linha_completa_quando_os_decisivos_estao_aferidos():
    l = _linha_completa()
    assert l["completo"] is True and l["decisivos_faltantes"] == []


def test_decisivo_nao_observado_torna_a_linha_incompleta():
    l = M.linha("cláusula 8.3", {
        "exigencia": M.celula("capital 15%", documento="Edital", localizador="8.3"),
        "teto_legal": M.celula(None),
    }, decisivos=("exigencia", "teto_legal"))
    assert l["completo"] is False and l["decisivos_faltantes"] == ["teto_legal"]


def test_campo_nao_decisivo_faltando_nao_derruba_a_linha():
    l = M.linha("cláusula 8.3", {
        "exigencia": M.celula("capital 15%", documento="Edital"),
        "observacao": M.celula(None),
    }, decisivos=("exigencia",))
    assert l["completo"] is True


# ─────────────────── o efeito sobre o grau ────────────────────────────────────────────────────

def test_matriz_completa_sustenta_o_grau_pretendido():
    c = M.consolidar([_linha_completa()], grau_pretendido="B")
    assert c["grau_limitado_por_cobertura"] is False and c["grau_sustentavel"] == "B"


def test_decisivo_faltando_TRAVA_o_grau_e_diz_qual_campo():
    l = M.linha("aditivo 3", {
        "valor": M.celula("R$ 1.000.000,00", documento="Termo", localizador="cl. 2"),
        "memoria_calculo": M.celula(None),
    }, decisivos=("valor", "memoria_calculo"))
    c = M.consolidar([l], grau_pretendido="B")
    assert c["grau_limitado_por_cobertura"] is True and c["grau_sustentavel"] == "nao_aferivel"
    assert c["travado_por"][0]["campos"] == ["memoria_calculo"]


def test_cobertura_e_fracao_nao_observada_saem_medidas():
    l = M.linha("x", {"a": M.celula("1", documento="D"), "b": M.celula(None),
                      "c": M.celula(None, documento="D")})
    c = M.consolidar([l])
    assert c["n_celulas"] == 3
    assert c["cobertura"] == pytest.approx(1 / 3, abs=1e-4)
    assert c["fracao_nao_observada"] == pytest.approx(1 / 3, abs=1e-4)


# ─────────────────── o HTML ───────────────────────────────────────────────────────────────────

def test_celula_nao_observada_aparece_rotulada_e_nao_em_branco():
    html = M.render_html([M.linha("x", {"a": M.celula(None)})])
    assert "NÃO OBSERVADO" in html and "lacuna de coleta" in html


def test_celula_aferida_mostra_a_fonte_junto_do_valor():
    html = M.render_html([M.linha("x", {"a": M.celula("15%", documento="Edital",
                                                      localizador="item 8.3")})])
    assert "15%" in html and "Edital, item 8.3" in html


def test_coluna_ausente_de_uma_linha_vira_nao_observado_e_nao_some():
    """Linha x não tem a coluna 'b' e linha y não tem a 'a': as duas células faltantes têm de
    aparecer rotuladas. Conto pela CLASSE da célula — a ressalva também usa o rótulo em texto."""
    html = M.render_html([M.linha("x", {"a": M.celula("1", documento="D")}),
                          M.linha("y", {"b": M.celula("2", documento="D")})])
    assert html.count('class="nao_observado"') == 2, "coluna faltando numa linha virou branco"
    assert "campo ausente da matriz" in html


def test_ressalva_explica_os_tres_estados():
    c = M.consolidar([_linha_completa()])
    assert "NÃO OBSERVADO" in c["ressalva"] and "não é ausência do fato" in c["ressalva"]
