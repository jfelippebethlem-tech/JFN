# -*- coding: utf-8 -*-
"""O `nous` EXISTE — só não é um "provedor" do free_llm.

Passei três iterações atrás da lentidão do sweep citando a regra da casa ("Sweep SEI → nous
`stepfun:free`, Cerebras nunca no volume") e fixando `FREE_LLM_PREFER=nous`. Isso nunca significou
nada: `nous` não está em `_get_provider_order`. Ele vive em `tools/sei_ficha.py` (`_nous_cred` +
`STEPFUN`), chamado direto por HTTP — eu procurava um NOME DE PROVEDOR onde havia uma FUNÇÃO
DEDICADA. A regra estava certa e implementada; quem não a leu fui eu.

E o motivo dela é o que a cascata não tinha: o nous é **sem limite**. O cerebras estourou 429
cinquenta vezes em 4 h e cada leitura passou a percorrer doze provedores, somando o timeout de
todos — 437 chamadas para 54 sucessos.

Medido no acervo: 38,8 s por processo pelo nous (contra 22 s do cerebras enquanto a cota durava, e
contra 831 s no pior caso da cascata).
"""
from __future__ import annotations

import inspect

import tools.sei_leitura_dupla as M


def test_o_leitor_padrao_do_volume_e_o_nous():
    fonte = inspect.getsource(M.extrair_interpretativo)
    assert "_gerar_nous()" in fonte, "o volume de SEI é do nous — é regra da casa, com motivo medido"
    assert fonte.index("_gerar_nous()") < fonte.index("_gerar_cadeia_curta()"), (
        "a cadeia curta é rede de segurança, não o caminho principal")


def test_sem_token_cai_na_cadeia_curta_em_vez_de_estourar(monkeypatch):
    """Degradar honesto: sem credencial do nous a leitura continua, por outro caminho."""
    monkeypatch.setattr(M, "_gerar_nous", lambda: None)
    assert M._gerar_cadeia_curta() is not None


def test_a_cadeia_curta_nao_percorre_os_doze(monkeypatch):
    import os
    monkeypatch.delenv("FREE_LLM_ONLY", raising=False)
    M._gerar_cadeia_curta()
    assert len(os.environ["FREE_LLM_ONLY"].split(",")) <= 4, (
        "cascata longa custou 7,5 h de espera para 12% de sucesso")
