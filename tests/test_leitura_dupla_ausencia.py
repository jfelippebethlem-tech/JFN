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


def test_Emb_Legal_nao_sujeito_e_ausencia_DECLARADA_de_fundamento(monkeypatch):
    """O SIAFE declara quando a despesa NÃO tem embasamento legal.

    `Emb. Legal não sujeito`, ao lado de `Mod. Licitação 07 - Não Aplicável`, é o caso de anulação
    de empenho: o sistema AFIRMANDO que não há, não dado faltante. Mesma família do
    `00000000 - SEM CONTRATO` — os dois leitores calando é concordância com a declaração, não
    lacuna de leitura, e por isso sai da fila humana.
    """
    r = _laudo(monkeypatch,
               "Mod. Licitação 07 - Não Aplicável Emb. Legal não sujeito Origem 1\n",
               {"dispositivo": "NAO_CONSTA"})
    assert "dispositivo" not in r["discordancia"]
    assert r["ausencia_concorde"]["dispositivo"]["estado"] == "ausencia_declarada"


def test_declaracao_NAO_apaga_fundamento_que_existe_noutro_ponto(monkeypatch):
    """A guarda vale só quando ninguém achou nada. Se o processo declara "não sujeito" no empenho
    MAS cita o fundamento noutro documento, o fundamento prevalece — foi o que aconteceu em dois
    processos reais, onde EU afirmei ausência lendo o trecho e a régua achou `art. 90` no todo."""
    r = _laudo(monkeypatch,
               "Emb. Legal não sujeito.\nAutorizo na forma do art. 90 da Lei 287/1979.\n",
               {"dispositivo": "art. 90"})
    assert "dispositivo" in r["acordo"]


def test_campo_criado_DEPOIS_da_leitura_nao_conta_como_perda_da_ia(monkeypatch):
    """Ao acrescentar `arp` e `tac` ao formulário, as leituras ANTIGAS passaram a exibir tudo que a
    régua achava como `so_regra` — **836 linhas de fila que não eram divergência**, só ausência de
    pergunta. A marca é a CHAVE FALTANDO: o extrator preenche todo campo perguntado, mesmo vazio.

    O `--recomparar` não conserta isso (reaplica a régua, não refaz a pergunta), então o estado tem
    de dizer a verdade — e o painel precisa distinguir "resolvido" de "não medido".
    """
    import json as _j
    monkeypatch.setattr("tools.sei_leitura_dupla.texto_do_processo",
                        lambda *a, **k: "Adesão a ARP nº 025/2024.")
    import tools.sei_leitura_dupla as M
    r = M.confrontar("030001/000001/2024",
                     gerar=lambda *a, **k: _j.dumps({"contrato": "NAO_CONSTA"}))
    # a leitura simulada responde só `contrato`; os demais campos existem no formulário atual
    assert r["ausencia_concorde"].get("arp", {}).get("estado") != "nao_perguntado", (
        "leitura NOVA tem todos os campos — `nao_perguntado` só vale para leitura antiga")


def test_leitura_antiga_sem_a_chave_vira_nao_perguntado():
    from tools.sei_leitura_dupla import comparar
    antiga = {"estado": "ok", "fatos": {"contrato": "443/2025"}}      # sem `arp`/`tac`
    r = comparar({"arp": {"valor": "025/2024"}}, antiga, {"tem_ob": False})
    assert r["ausencia_concorde"]["arp"]["estado"] == "nao_perguntado"
    assert "arp" not in r["discordancia"]
