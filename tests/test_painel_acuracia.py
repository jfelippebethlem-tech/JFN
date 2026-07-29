# -*- coding: utf-8 -*-
"""Painel de acurácia — e a única coisa que ele não pode fazer.

**Não pode inventar número quando não há medição.** Card em branco é informação; card com "—"
somado como 0% é mentira; e card com o último valor sem dizer de quando é pior ainda, porque
parece atual. Todos os estados aqui são explícitos.

E os alertas existem para o que NÃO pode passar em silêncio: não bater o baseline de classe
majoritária (acurácia de papagaio), alucinar citação (tolerância zero) e o colapso de uma classe
que a média esconde.
"""
from __future__ import annotations

import json

import pytest

from compliance_agent.reporting import painel_acuracia as P


@pytest.fixture()
def arq(tmp_path):
    return lambda nome, d: (
        (tmp_path / nome).write_text(json.dumps(d), encoding="utf-8"),
        str(tmp_path / nome))[1]


def _med(**kw):
    base = {"f1_macro": 0.72, "alucinacao_citacao": 0.0, "bate_o_baseline": True,
            "abstencao": 0.05, "n": 200, "prompt_versao": "v1", "prompt_hash": "abc123",
            "f1_por_classe": {"vicio": 0.78, "licito": 0.66}}
    base.update(kw)
    return base


# ─────────────────── sem medição não se desenha número ────────────────────────────────────────

def test_sem_medicao_o_card_DIZ_isso(tmp_path):
    c = P.montar(caminho_ultima=str(tmp_path / "nada.json"),
                 caminho_baseline=str(tmp_path / "nada2.json"))
    assert c["estado"] == "sem_medicao" and c["f1_macro"] is None
    assert "ainda não foi medida" in c["mensagem"]


def test_html_sem_medicao_nao_desenha_zero(tmp_path):
    html = P.render_html(P.montar(caminho_ultima=str(tmp_path / "x.json"),
                                  caminho_baseline=str(tmp_path / "y.json")))
    assert "0.000" not in html and "0%" not in html
    assert "sem medição" in html or "não foi medida" in html


def test_arquivo_corrompido_nao_quebra_e_vira_sem_medicao(tmp_path):
    p = tmp_path / "u.json"
    p.write_text("{isso não é json", encoding="utf-8")
    assert P.montar(caminho_ultima=str(p),
                    caminho_baseline=str(tmp_path / "b.json"))["estado"] == "sem_medicao"


# ─────────────────── a faixa diz o que se pode AFIRMAR ────────────────────────────────────────

@pytest.mark.parametrize("f1,faixa", [(0.85, "alta"), (0.70, "media"), (0.50, "baixa"),
                                      (0.20, "insuficiente")])
def test_faixa_por_f1(f1, faixa):
    assert P.faixa_de(f1)[0] == faixa


def test_faixa_baixa_vira_alerta(arq):
    u = arq("u.json", _med(f1_macro=0.50))
    c = P.montar(caminho_ultima=u, caminho_baseline="/nao/existe.json")
    assert any("faixa 'baixa'" in a for a in c["alertas"])


# ─────────────────── os três alertas que não podem calar ──────────────────────────────────────

def test_nao_bater_o_papagaio_vira_alerta(arq):
    c = P.montar(caminho_ultima=arq("u.json", _med(bate_o_baseline=False)),
                 caminho_baseline="/nao/existe.json")
    assert any("papagaio" in a for a in c["alertas"])


def test_qualquer_alucinacao_vira_alerta(arq):
    """Tolerância ZERO: 0,5% já acende."""
    c = P.montar(caminho_ultima=arq("u.json", _med(alucinacao_citacao=0.005)),
                 caminho_baseline="/nao/existe.json")
    assert any("tolerância desta casa é ZERO" in a for a in c["alertas"])


def test_colapso_de_uma_classe_e_pego_mesmo_com_media_boa(arq):
    c = P.montar(caminho_ultima=arq("u.json", _med(
        f1_macro=0.72, f1_por_classe={"vicio": 0.95, "licito": 0.05})),
        caminho_baseline="/nao/existe.json")
    assert any("a média esconde" in a for a in c["alertas"])


def test_medicao_boa_nao_produz_alerta(arq):
    c = P.montar(caminho_ultima=arq("u.json", _med()), caminho_baseline="/nao/existe.json")
    assert c["alertas"] == []


# ─────────────────── comparação com o baseline ────────────────────────────────────────────────

def test_sem_baseline_declara_primeira_medicao(arq):
    c = P.montar(caminho_ultima=arq("u.json", _med()), caminho_baseline="/nao/existe.json")
    assert c["comparacao"]["estado"] == "sem_baseline"


def test_delta_contra_o_baseline(arq):
    u = arq("u.json", _med(f1_macro=0.75))
    b = arq("b.json", _med(f1_macro=0.70))
    c = P.montar(caminho_ultima=u, caminho_baseline=b)
    assert c["comparacao"]["delta_f1"] == pytest.approx(0.05)


def test_prompt_DIFERENTE_entre_as_medicoes_e_declarado(arq):
    """Comparar medições de prompts diferentes sem dizer não é comparar a mesma coisa."""
    u = arq("u.json", _med(prompt_hash="novo999"))
    b = arq("b.json", _med(prompt_hash="abc123"))
    c = P.montar(caminho_ultima=u, caminho_baseline=b)
    assert c["comparacao"]["mesmo_prompt"] is False
    assert "o prompt mudou" in c["comparacao"]["nota"]


def test_mesmo_prompt_nao_gera_a_nota(arq):
    c = P.montar(caminho_ultima=arq("u.json", _med()), caminho_baseline=arq("b.json", _med()))
    assert c["comparacao"]["mesmo_prompt"] is True and "nota" not in c["comparacao"]


# ─────────────────── persistência e ressalva ──────────────────────────────────────────────────

def test_gravar_ultima_NAO_persiste_o_holdout(tmp_path):
    alvo = str(tmp_path / "ultima.json")
    P.gravar_ultima({**_med(), "detalhes": [{"id": "caso-do-holdout"}]}, caminho=alvo,
                    medido_em="2026-07-29")
    d = json.loads(open(alvo, encoding="utf-8").read())
    assert "detalhes" not in d and d["medido_em"] == "2026-07-29"


def test_ressalva_lembra_o_teto_de_grau_C(arq):
    c = P.montar(caminho_ultima=arq("u.json", _med()), caminho_baseline="/nao/existe.json")
    assert "grau C" in c["ressalva"] and "sozinho" in c["ressalva"]
    assert "grau C" in P.render_html(c)


def test_html_traz_o_numero_a_faixa_e_a_versao_do_prompt(arq):
    html = P.render_html(P.montar(caminho_ultima=arq("u.json", _med()),
                                  caminho_baseline="/nao/existe.json"))
    assert "0.720" in html and "media" in html and "v1" in html
