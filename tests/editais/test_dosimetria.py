# -*- coding: utf-8 -*-
"""Dosimetria da medida — as três travas que separam pedido cabível de peça devolvida.

  1. **Débito exige dano com OB.** Sobrepreço é vício do orçamento; superfaturamento é dano, e
     dano exige pagamento. Empenho não é pagamento — é o invariante mais duro da casa.
  2. **Sanção pessoal exige responsável identificado.** O extrator de ordenador/gestor/fiscal tem
     cobertura baixa; pedir multa sem saber quem assinou é peça devolvida.
  3. **Grau C não sustenta medida pessoal.** Juízo de IA tem teto C em `editais/flags`; aqui esse
     teto corta o pedido, não só o rótulo.

E `faltou` é tão importante quanto `medida`: dizer "cabe determinação" sem dizer que só não cabe
débito por ausência de OB deixa o leitor sem saber o que buscar.
"""
from __future__ import annotations

from compliance_agent.editais import dosimetria as D


def _g(**kw):
    base = dict(sv=12, teste_objetivo_violado=False, dano_apurado=None, dano_com_ob=False,
                responsavel_identificado=False, reincidencia_agente=0, grau_evidencia=None,
                indicio_penal=False)
    base.update(kw)
    return D.graduar(**base)


# ───────────────────────── escalada normal ────────────────────────────────────────────────────

def test_achado_leve_e_recomendacao():
    assert _g(sv=4)["medida"] == "recomendacao"


def test_violacao_objetiva_de_norma_vira_determinacao():
    r = _g(sv=4, teste_objetivo_violado=True)
    assert r["medida"] == "determinacao"
    assert "art. 250, II" in r["fundamento"]


def test_matriz_alta_sozinha_nao_passa_de_determinacao():
    """S×V mede gravidade e verossimilhança do padrão — não mede prova nem dano."""
    assert _g(sv=25)["medida"] == "determinacao"


# ───────────────────────── trava 1: débito exige OB ───────────────────────────────────────────

def test_dano_SEM_ordem_bancaria_nao_vira_debito():
    r = _g(sv=20, dano_apurado=1_000_000.0, dano_com_ob=False,
           responsavel_identificado=True, grau_evidencia="A")
    assert r["medida"] != "debito"
    assert any("Ordem Bancária" in f for f in r["faltou_para_medida_mais_gravosa"])
    assert any("empenho não é pagamento" in f for f in r["faltou_para_medida_mais_gravosa"])


def test_dano_COM_ordem_bancaria_vira_debito():
    r = _g(sv=20, dano_apurado=1_000_000.0, dano_com_ob=True,
           responsavel_identificado=True, grau_evidencia="A")
    assert r["medida"] == "debito" and "arts. 19 e 57" in r["fundamento"]


def test_pagamento_sem_valor_apurado_pede_a_memoria_de_calculo():
    r = _g(sv=20, dano_apurado=None, dano_com_ob=True)
    assert any("memória de cálculo" in f for f in r["faltou_para_medida_mais_gravosa"])


# ───────────────────────── trava 2: responsável identificado ──────────────────────────────────

def test_multa_sem_responsavel_identificado_nao_sai():
    r = _g(sv=20, grau_evidencia="A", responsavel_identificado=False)
    assert r["medida"] == "determinacao"
    assert any("responsável identificado" in f for f in r["faltou_para_medida_mais_gravosa"])


def test_multa_com_responsavel_e_evidencia_forte_sai():
    r = _g(sv=20, grau_evidencia="B", responsavel_identificado=True)
    assert r["medida"] == "multa" and "art. 58" in r["fundamento"]


# ───────────────────────── trava 3: grau C não sanciona ───────────────────────────────────────

def test_grau_C_nao_sustenta_multa_por_mais_grave_que_seja():
    """Juízo de IA tem teto C; o teto corta o PEDIDO, não só o rótulo."""
    r = _g(sv=25, grau_evidencia="C", responsavel_identificado=True)
    assert r["medida"] == "determinacao"
    assert any("juízo de IA" in f for f in r["faltou_para_medida_mais_gravosa"])


def test_grau_nao_declarado_e_tratado_como_fraco():
    r = _g(sv=25, grau_evidencia=None, responsavel_identificado=True)
    assert r["medida"] == "determinacao"


# ───────────────────────── inabilitação e criminal ────────────────────────────────────────────

def test_reincidencia_do_agente_agrava_para_inabilitacao():
    r = _g(sv=20, grau_evidencia="A", responsavel_identificado=True, reincidencia_agente=3)
    assert r["medida"] == "inabilitacao" and "art. 60" in r["fundamento"]


def test_reincidencia_SEM_base_pessoal_nao_agrava():
    r = _g(sv=20, grau_evidencia="C", responsavel_identificado=False, reincidencia_agente=5)
    assert r["medida"] == "determinacao"
    assert any("antes de a reincidência agravar" in f
               for f in r["faltou_para_medida_mais_gravosa"])


def test_criminal_e_ENCAMINHAMENTO_nunca_imputacao():
    r = _g(sv=22, grau_evidencia="A", responsavel_identificado=True, indicio_penal=True)
    e = r["encaminhamentos"][0]
    assert e["medida"] == "representacao_criminal"
    assert "compete ao Ministério" in e["nota"] and "não imputação" in e["nota"]


def test_criminal_sobre_evidencia_fraca_nao_sai():
    r = _g(sv=22, grau_evidencia="C", indicio_penal=True)
    assert r["encaminhamentos"] == []
    assert any("notícia-crime" in f for f in r["faltou_para_medida_mais_gravosa"])


# ───────────────────────── honestidade do texto ───────────────────────────────────────────────

def test_texto_diz_o_que_falta_para_a_medida_mais_gravosa():
    txt = D.render_texto(_g(sv=20, dano_apurado=500.0, grau_evidencia="C"))
    assert "o que buscar" in txt


def test_ressalva_de_competencia_viaja_com_o_resultado():
    r = _g()
    assert "não decisão" in r["ressalva"] and "contraditório" in r["ressalva"]
    assert "SUGESTÃO" in D.render_texto(r)


def test_sv_fora_da_faixa_e_clampado_sem_quebrar():
    assert D.graduar(sv=99)["sv"] == 25
    assert D.graduar(sv=-4)["sv"] == 1


def test_toda_medida_da_escala_tem_fundamento_legal():
    faltando = [m for m in D.ESCALA if not D.FUNDAMENTO.get(m)]
    assert not faltando and D.FUNDAMENTO["representacao_criminal"]
