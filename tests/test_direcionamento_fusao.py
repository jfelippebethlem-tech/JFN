# -*- coding: utf-8 -*-
"""FUSÃO determinístico × subjetivo no cérebro de direcionamento.

O dono pediu (2026-07-24): a leitura precisa saber se há corrupção/irregularidade "não só
deterministicamente, mas subjetivamente também" — e as duas camadas precisam CONVERSAR.

Antes, `avaliar_direcionamento` calculava os `sinais_deterministicos` e os anexava ao lado, mas o
`grau` do veredito vinha SÓ do LLM. Consequências:
  • LLM subestima (verde) um sinal objetivo FORTE+cascata (vermelho) → o alarme objetivo era silenciado;
  • LLM cai → grau "indisponivel" mesmo com a camada determinística tendo achado vermelho (produto cego).

A fusão concilia: NENHUM alarme é silenciado (grau = o MAIOR dos dois quando conclusivos); se o LLM
está indisponível/inconclusivo, vale o determinístico; a DIVERGÊNCIA entre camadas é sinalizada para a
análise crítica do auditor. Tudo sem rede (LLM injetável).
"""
from __future__ import annotations

import json

import pytest

from compliance_agent import direcionamento_cerebro as DC

# Texto que dispara a camada determinística em VERMELHO: cláusula FORTE (vedação de somatório de
# atestados) + cascata de 3 inabilitações pelo MESMO motivo. Confirmado empiricamente em analisar_direcionamento_det.
_TXT_VERMELHO_DET = (
    "EDITAL DE PREGAO ELETRONICO E ATA DE JULGAMENTO. " * 5
    + "Termo de referencia e habilitacao. Qualificacao tecnica. Proposta. " * 10
    + "E vedado o somatorio de atestados de capacidade tecnica. "
    + "A empresa ALFA foi inabilitada por nao apresentar atestado de capacidade tecnica. "
    + "A empresa BETA foi inabilitada por nao apresentar atestado de capacidade tecnica. "
    + "A empresa GAMA foi inabilitada por nao apresentar atestado de capacidade tecnica. "
    + "Foi declarada vencedora a empresa OMEGA. "
    + "Preenchimento do edital de licitacao. " * 20
)


def _fake(grau_json: dict):
    async def _g(messages):
        return json.dumps(grau_json)
    return _g


# ──────────────────────────────────────────────────────────────────────────────
# 1) A função pura de fusão
# ──────────────────────────────────────────────────────────────────────────────
# (grau_llm, grau_det, grau_final, fonte_grau que DRIVA o final, camada_mais_severa da divergência|None)
# Divergência só existe entre DUAS opiniões conclusivas que discordam; ausência (None/indisponivel) não diverge.
@pytest.mark.parametrize("llm,det,esperado,fonte,div", [
    ("verde", "vermelho", "vermelho", "objetivo", "objetivo"),      # objetivo mais severo → escala (não silencia)
    ("vermelho", "verde", "vermelho", "subjetivo", "subjetivo"),    # subjetivo mais severo → mantém (interpretativo)
    ("amarelo", "amarelo", "amarelo", "subjetivo+objetivo", None),  # concordância → sem divergência
    (None, "vermelho", "vermelho", "objetivo", None),              # LLM indisponível → vale o determinístico
    ("amarelo", None, "amarelo", "subjetivo", None),               # determinístico inconclusivo → vale o LLM
    (None, None, "indeterminado", "nenhum", None),                # nada conclusivo
    ("indisponivel", "amarelo", "amarelo", "objetivo", None),      # 'indisponivel' conta como inconclusivo
])
def test_fundir_graus_pura(llm, det, esperado, fonte, div):
    r = DC.fundir_graus(llm, det)
    assert r["grau"] == esperado
    assert r["fonte_grau"] == fonte
    if div:
        assert r["divergencia"] is not None and r["divergencia"]["camada_mais_severa"] == div
    else:
        assert r["divergencia"] is None


def test_fundir_graus_concordancia_sem_divergencia():
    assert DC.fundir_graus("amarelo", "amarelo")["divergencia"] is None
    assert DC.fundir_graus("vermelho", "vermelho")["divergencia"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 2) Integração no cérebro — o alarme objetivo não é silenciado pelo LLM
# ──────────────────────────────────────────────────────────────────────────────
def test_llm_subestima_objetivo_forte_escala(monkeypatch):
    """LLM diz VERDE, mas o determinístico achou FORTE+cascata (vermelho): o veredito final é vermelho
    e a divergência é sinalizada (o LLM pode ter passado batido no sinal literal)."""
    monkeypatch.setattr(DC, "_gemini_keys", lambda: [])  # garante caminho do fake
    res = DC.avaliar_sync(edital_txt=_TXT_VERMELHO_DET, gerar=_fake(
        {"grau": "verde", "resumo": "nada a apontar", "dados_suficientes": True}))
    assert res["grau"] == "vermelho"           # objetivo não silenciado
    assert res["grau_llm"] == "verde"          # transparência do que o LLM disse
    assert res["grau_det"] == "vermelho"
    assert res["divergencia"] is not None
    assert res["divergencia"]["camada_mais_severa"] == "objetivo"


def test_llm_offline_cai_para_determinismo(monkeypatch):
    """LLM indisponível (levanta exceção) mas o determinístico achou vermelho: o produto NÃO fica cego —
    grau = vermelho pela camada objetiva, com ressalva honesta de que o LLM não respondeu."""
    monkeypatch.setattr(DC, "_gemini_keys", lambda: [])
    async def _boom(messages):
        raise RuntimeError("todos os provedores em cooldown")
    res = DC.avaliar_sync(edital_txt=_TXT_VERMELHO_DET, gerar=_boom)
    assert res["grau"] == "vermelho"           # antes: "indisponivel" (cego)
    assert res["grau_det"] == "vermelho"
    assert res.get("grau_llm") in (None, "indisponivel", "")
    assert res["fonte_grau"] == "objetivo"
    assert "sinais_deterministicos" in res


def test_concordancia_nao_gera_divergencia(monkeypatch):
    """LLM amarelo + determinístico amarelo → amarelo, sem divergência (sem regressão do caso comum)."""
    monkeypatch.setattr(DC, "_gemini_keys", lambda: [])
    txt = ("EDITAL DE PREGAO. " * 5 + "Termo de referencia habilitacao qualificacao tecnica proposta. " * 30
           + "E vedado o somatorio de atestados. ")  # 1 forte, SEM cascata → det amarelo
    res = DC.avaliar_sync(edital_txt=txt, gerar=_fake(
        {"grau": "amarelo", "resumo": "indício a verificar", "dados_suficientes": True}))
    assert res["grau_det"] == "amarelo"
    assert res["grau"] == "amarelo"
    assert res["divergencia"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 3) O pacote humano (Telegram/Claude) EXIBE o veredito conciliado e a divergência
# ──────────────────────────────────────────────────────────────────────────────
def test_pacote_mostra_grau_conciliado_e_divergencia():
    """O auditor precisa VER que o objetivo discordou do LLM — é o gatilho de análise crítica."""
    resultado = {
        "grau": "vermelho", "grau_llm": "amarelo", "grau_det": "vermelho",
        "fonte_grau": "objetivo", "resumo": "x", "dados_suficientes": True,
        "divergencia": {"grau_llm": "amarelo", "grau_det": "vermelho", "delta": 1,
                        "camada_mais_severa": "objetivo", "nota": "camada objetiva mais severa; revisar."},
        "presinais": {}, "exigencias_restritivas": [], "cascata": [],
    }
    pac = DC.montar_pacote_claude({"objeto": "obra X", "id_pncp": "1"}, resultado)
    assert "VERMELHO" in pac                     # grau conciliado em destaque
    assert "amarelo" in pac.lower()              # o que o LLM disse (transparência)
    assert "DIVERGÊNCIA" in pac.upper()          # o alerta de divergência aparece
    assert "objetiv" in pac.lower()              # qual camada foi mais severa


def test_pacote_sem_divergencia_nao_polui():
    """Concordância → sem seção de divergência (não polui o pacote)."""
    resultado = {"grau": "amarelo", "grau_llm": "amarelo", "grau_det": "amarelo",
                 "divergencia": None, "resumo": "x", "presinais": {}}
    pac = DC.montar_pacote_claude({"objeto": "obra Y", "id_pncp": "2"}, resultado)
    assert "DIVERGÊNCIA" not in pac.upper()
