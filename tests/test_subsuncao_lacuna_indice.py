# -*- coding: utf-8 -*-
"""Sem o índice do TCU, a subsunção declara a lacuna — não sai calada.

POR QUE EXISTE. `_verificar_norma` devolve `ok=True` com `fonte="indice_ausente"` quando o índice
oficial não está construído: a norma não é invalidada (indisponibilidade não vira acusação), mas
ela também **não foi conferida**. Até 2026-07-31 isso saía no texto sem nenhuma marca — o leitor
recebia uma subsunção `aferivel` fundada num acórdão que ninguém confirmou existir.

O CI de 2026-07-31 (run 30626748433, runner sem índice) acendeu isso em 5 testes de 4 arquivos.
Esta casa já pagou por citação de acórdão FABRICADA; INDISPONÍVEL ≠ OK vale aqui também.

Este teste trava só a DECLARAÇÃO. Se a lacuna deve ou não derrubar o `aferivel` é decisão de
produto e segue em aberto — mas o silêncio, esse, acabou.
"""
from __future__ import annotations

from compliance_agent.knowledge import subsuncao as S
from compliance_agent.knowledge import tcu_juris_index as T

_DADOS = {
    "norma_dispositivo": "Acórdão 1234/2020-Plenário",
    "norma_verbatim": "texto literal da norma invocada",
    "fatos": [{"enunciado": "fato", "trecho": "trecho", "documento": "doc",
               "folha": "1", "grau": "A"}],
    "contra_argumento": "a defesa alega x",
    "subsuncao": "a ponte entre norma e fato",
    "conclusao_enquadra": True,
}


def _sem_indice(monkeypatch):
    monkeypatch.setattr(T, "verificar_citacao",
                        lambda texto, db=None: [{"status": "indice_ausente"}])


def test_sem_indice_o_texto_declara_que_a_norma_nao_foi_conferida(monkeypatch):
    _sem_indice(monkeypatch)
    r = S.montar(_DADOS, None)
    assert r["norma_verificada"]["fonte"] == "indice_ausente"
    texto = S.render_texto(r)
    assert "índice oficial NÃO estava disponível" in texto, (
        "lacuna da premissa maior saiu CALADA — era exatamente o defeito")
    assert "Conferir na fonte" in texto


def test_a_lacuna_nao_invalida_a_norma(monkeypatch):
    """Indisponibilidade não vira acusação — o outro lado da mesma regra."""
    _sem_indice(monkeypatch)
    r = S.montar(_DADOS, None)
    assert r["norma_verificada"]["ok"] is True
    assert not any("premissa maior" in p for p in r["problemas"])


def test_com_indice_nao_ganha_a_nota(monkeypatch):
    """A nota é para a AUSÊNCIA; norma conferida não carrega ressalva que não cabe."""
    monkeypatch.setattr(T, "verificar_citacao",
                        lambda texto, db=None: [{"status": "confirmado"}])
    r = S.montar(_DADOS, None)
    assert "índice oficial NÃO estava disponível" not in S.render_texto(r)
