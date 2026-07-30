# -*- coding: utf-8 -*-
"""O grafo que o painel SERVE tem de usar a régua calibrada da casa.

O DESCOMPASSO. `osint/vinculos.py` tem uma tabela de força por tipo de aresta, calibrada em lições
que esta casa já pagou: `mesma_sala` 0,75 porque por sala o acervo dá grupos que significam algo;
`mesmo_predio` 0,05 porque o topo do acervo por prédio é um endereço com 318 CNPJs;
`nome_igual_sem_documento` 0,10 porque "existe para APARECER, não para pesar".

E o grafo que o usuário efetivamente vê — `grafo_poder`, servido por `GET /api/grafo` — ligava tudo
sem força nenhuma: sócio por `socio_nome_norm` (nome puro) valia o mesmo que sócio por documento, e
co-endereço não distinguia sala de prédio.

O TAMANHO DO ERRO, medido em 2026-07-29 sobre o acervo:

  · **76% das arestas de co-endereço são de PRÉDIO** (435 de 570) — valiam 0,75 e valem 0,05.
    Sobrepeso de 15× em três quartos das arestas de uma das seções que mais acusa.
  · Só **3,8%** dos vínculos de sócio têm CPF resolvido (1.190 de 31.449). Os outros 94,9% têm nome
    mais o CPF MASCARADO da Receita (`***261845**`), cuja colisão medida nesta base é ~4%.

Este último caso é o dominante em qualquer grafo societário brasileiro de fonte aberta, e o
vocabulário fechado não o tinha: nem `mesmo_socio` (0,90, que pressupõe documento) nem
`nome_igual_sem_documento` (0,10, que descarta a máscara). Daí `mesmo_socio_doc_parcial` (0,70).

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_grafo_poder_regua.py -q
"""
from __future__ import annotations

import pytest

from compliance_agent.osint.vinculos import TIPOS_ARESTA


def test_vocabulario_tem_o_caso_dominante_da_receita():
    """CPF mascarado + nome não é documento nem é nome puro — e é 94,9% do acervo."""
    t = TIPOS_ARESTA.get("mesmo_socio_doc_parcial")
    assert t is not None, (
        "falta o tipo para o caso dominante: sócio identificado por nome + CPF mascarado da RFB"
    )
    assert 0.10 < t.forca < 0.90, (
        f"força {t.forca}: tem de ficar ENTRE nome puro (0,10) e documento pleno (0,90)"
    )
    assert t.exculpatoria, "todo tipo de aresta carrega a explicação inocente"
    assert "4%" in t.exculpatoria or "colis" in t.exculpatoria.lower(), (
        "a colisão medida da máscara tem de estar declarada no próprio tipo"
    )


def test_a_regua_mantem_a_distancia_entre_sala_e_predio():
    """É a lição mais cara do eixo de endereço: 15× de diferença, e ela não pode encolher."""
    sala = TIPOS_ARESTA["mesma_sala"].forca
    predio = TIPOS_ARESTA["mesmo_predio"].forca
    assert sala / predio >= 10, (
        f"sala/prédio caiu para {sala / predio:.1f}× — por prédio o topo do acervo tem 318 CNPJs"
    )


# ── o grafo servido pela API ──────────────────────────────────────────────────

def test_grafo_poder_declara_forca_e_tipo_calibrado():
    from compliance_agent import grafo_poder

    fonte = __import__("pathlib").Path(grafo_poder.__file__).read_text()
    assert "TIPOS_ARESTA" in fonte, (
        "grafo_poder não consulta a régua de `osint/vinculos` — a calibragem existe e não está "
        "onde o usuário olha"
    )
    assert "classificar_endereco" in fonte, (
        "co-endereço sem `classificar_endereco` trata prédio como sala: sobrepeso de 15× em 76% "
        "das arestas"
    )


def test_calibrar_aresta_de_socio_gradua_pela_identificacao():
    """Três graus, e o do meio é o que mais aparece."""
    from compliance_agent.grafo_poder import calibrar_socio

    tipo, forca, _ = calibrar_socio(doc_resolvido="12345678901", doc_mascarado="***456789**")
    assert tipo == "mesmo_socio" and forca == pytest.approx(0.90)

    tipo, forca, obs = calibrar_socio(doc_resolvido="", doc_mascarado="***456789**")
    assert tipo == "mesmo_socio_doc_parcial" and forca == pytest.approx(0.70)
    assert obs, "o grau intermediário tem de declarar por que não é documento pleno"

    tipo, forca, obs = calibrar_socio(doc_resolvido="", doc_mascarado="")
    assert tipo == "nome_igual_sem_documento" and forca == pytest.approx(0.10)
    assert obs, "nome puro tem de vir com a ressalva de homonímia"


def test_calibrar_endereco_separa_sala_de_predio():
    from compliance_agent.grafo_poder import calibrar_endereco

    tipo, forca, _ = calibrar_endereco("RUA DA ASSEMBLEIA 10")
    assert tipo == "mesmo_predio" and forca == pytest.approx(0.05)

    tipo, forca, _ = calibrar_endereco("RUA DA ASSEMBLEIA 10 SALA 1201")
    assert tipo == "mesma_sala" and forca == pytest.approx(0.75)

    # coworking não liga ninguém a ninguém, mesmo com sala
    tipo, forca, obs = calibrar_endereco("AV RIO BRANCO 100 SALA 500 COWORKING")
    assert tipo == "mesmo_predio", "endereço de natureza compartilhada não pode valer como sala"
    assert obs


def test_aresta_de_pagamento_nao_recebe_forca_de_proximidade():
    """`pago_por` é FATO (a OB existe), não inferência de proximidade. Dar-lhe força de vínculo
    misturaria duas coisas diferentes e inflaria o grau de qualquer fornecedor grande."""
    from compliance_agent.grafo_poder import forca_da_relacao

    forca, tipo = forca_da_relacao("pago_por")
    assert forca is None, "pagamento não é vínculo de proximidade — não tem força de aresta"
    assert tipo is None


def test_vizinhanca_real_traz_forca_em_toda_aresta_de_vinculo():
    from pathlib import Path

    from compliance_agent.database.models import _resolver_db
    from compliance_agent.grafo_poder import vizinhanca

    if not Path(_resolver_db()).exists():
        pytest.skip("compliance.db ausente nesta máquina")

    d = vizinhanca("133100", saltos=2)
    assert d["ok"]
    sem_forca = [a for a in d["arestas"]
                 if a["rel"] not in ("pago_por",) and "forca" not in a]
    assert not sem_forca, f"aresta de vínculo sem força declarada: {sem_forca[:3]}"
    for a in d["arestas"]:
        if "forca" in a:
            assert 0.0 < a["forca"] <= 1.0
            assert a.get("tipo_calibrado") in TIPOS_ARESTA
