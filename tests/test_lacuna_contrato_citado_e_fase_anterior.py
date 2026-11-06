# -*- coding: utf-8 -*-
"""F_CONTRATACAO ("Contrato/ata formalizados" ausente) — dois falsos positivos do motor, medidos em 06/11/2026.

Dos 177 processos com a lacuna em grau médio (era 10 em 09/09): 27 citam "Contrato nº NNN/AAAA" no texto
(extrato no DOERJ, cópia anexada com título mudo, aditivo) e 19 só têm planejamento — contrato ainda não
exigível. Nos dois casos o achado cai para baixa e diz o que se vê; não some.
"""
from __future__ import annotations

from pathlib import Path

from compliance_agent import processo_360 as P


def test_extrato_no_doerj_conta_como_contrato_citado(monkeypatch):
    textos = {"Despacho": "encaminho para ciência",
              "Anexo DOERJ": "EXTRATO DE INSTRUMENTO CONTRATUAL INSTRUMENTO : CONTRATO N° 14/2023. PARTES"}
    monkeypatch.setattr(P, "_texto_de", lambda pasta, d, teto=None: textos[d["titulo"]])
    cit = P._contrato_citado(Path("."), [{"titulo": "Despacho"}, {"titulo": "Anexo DOERJ"}])
    assert cit == {"ref": "Anexo DOERJ", "trecho": "CONTRATO N° 14/2023"}


def test_sem_ano_de_quatro_digitos_e_contrato_social_nao_contam(monkeypatch):
    """'Contrato nº 06/05' era data; contrato social é peça de habilitação."""
    textos = {"a": "Contrato nº \n06/05 assinado", "b": "conforme contrato social registrado",
              "c": "nos termos do contrato vigente"}
    monkeypatch.setattr(P, "_texto_de", lambda pasta, d, teto=None: textos[d["titulo"]])
    assert P._contrato_citado(Path("."), [{"titulo": k} for k in textos]) is None


def test_fase_anterior_so_com_planejamento_e_nada_depois():
    assert P._em_fase_anterior({"planejamento", "tramitacao"}, False)
    assert not P._em_fase_anterior({"tramitacao"}, False)                      # mudo: não presume
    assert not P._em_fase_anterior({"planejamento", "despesa"}, False)         # já gastou
    assert not P._em_fase_anterior({"planejamento", "selecao"}, False)         # selecionou: contrato é exigível
    assert not P._em_fase_anterior({"planejamento"}, True)                     # pagou sem contrato: é o achado
