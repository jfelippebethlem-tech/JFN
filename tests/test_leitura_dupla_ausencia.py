# -*- coding: utf-8 -*-
"""Os dois leitores dizerem "não existe" NÃO é divergência.

Medido em 31 processos do acervo: das 77 linhas na fila de discordância, **61 eram a IA respondendo
`NAO_CONSTA` com a regra vazia** — a MESMA resposta dos dois lados, empilhada como se os leitores
brigassem. O efeito prático é o pior possível numa fila de leitura humana: afogar as 16 linhas em
que alguém de fato achou algo debaixo de 61 linhas de nada.

Também não vira acordo: acordo é os dois acharem o MESMO valor. Ausência concorde é o terceiro
estado — o mesmo veredito de três valores que o painel usa (OK / FALHOU / NÃO MEDI).
"""
from __future__ import annotations

import json

from tools.sei_leitura_dupla import confrontar


def _laudo(monkeypatch, texto, fatos):
    monkeypatch.setattr("tools.sei_leitura_dupla.texto_do_processo", lambda *a, **k: texto)
    # `gerar` devolve o TEXTO do LLM, e o JSON pedido é PLANO — quem parseia é o extrator.
    # (Aninhar em {"fatos": ...} fazia o extrator ler tudo vazio, e o teste de ausência
    #  passava pelo motivo errado: ausência por campo perdido, não por campo inexistente.)
    return confrontar("030001/000001/2024",
                      gerar=lambda *a, **k: json.dumps(fatos, ensure_ascii=False))


def test_ausencia_dos_dois_sai_da_fila_de_discordancia(monkeypatch):
    r = _laudo(monkeypatch, "texto sem contrato, sem pregao e sem artigo algum.",
               {"contrato": "NAO_CONSTA", "pregao": "NAO_CONSTA", "dispositivo": "NAO_CONSTA"})
    assert r["n_ausencia"] >= 3
    for campo in ("contrato", "pregao", "dispositivo"):
        assert campo not in r["discordancia"], f"{campo} voltou para a fila humana sendo ausência"
        assert campo not in r["acordo"], "ausência não é acordo: acordo é achar o MESMO valor"


def test_discordancia_de_verdade_CONTINUA_na_fila(monkeypatch):
    """A guarda não pode ter esvaziado a fila: quando a IA acha e a regra não, aquilo é sinal."""
    r = _laudo(monkeypatch, "Contrato nº 443/2025 firmado.", {"pregao": "12/2024"})
    assert "pregao" in r["discordancia"] and r["discordancia"]["pregao"]["estado"] == "so_ia"


def test_SEM_CONTRATO_do_siafe_e_NAO_CONSTA_da_ia_sao_a_mesma_resposta(monkeypatch):
    """`00000000 - SEM CONTRATO` é o SIAFE declarando que não há instrumento; `NAO_CONSTA` é a IA
    dizendo que não achou. Os dois afirmam ausência de contrato — e isso entrava na fila humana
    como "a regra achou algo que a IA perdeu", que é o oposto do que aconteceu."""
    r = _laudo(monkeypatch, "Contrato: 00000000 - SEM CONTRATO. Segue para pagamento.",
               {"contrato": "NAO_CONSTA"})
    assert "contrato" not in r["discordancia"]
    assert r["ausencia_concorde"]["contrato"]["estado"] == "ausencia_declarada"


def test_contrato_de_verdade_que_a_ia_perdeu_CONTINUA_na_fila(monkeypatch):
    """A guarda vale só para a ausência declarada: número real que a IA não viu é sinal, não ruído."""
    r = _laudo(monkeypatch, "Contrato nº 443/2025 firmado com a empresa.", {"contrato": "NAO_CONSTA"})
    assert r["discordancia"]["contrato"]["estado"] == "so_regra"
