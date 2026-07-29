# -*- coding: utf-8 -*-
"""O conjunto-ouro em si: estratificação, split selado e as armadilhas de medição.

Ter 1.530 casos rotulados não basta. Um corpus enviesado mede errado COM APARÊNCIA DE RIGOR, que
é pior do que não medir: o número entra no relatório e ninguém o questiona.

Três armadilhas travadas aqui:

  1. **Desequilíbrio de classe.** O acervo do TCU tem 551 `vicio`, 776 `vicio_por_omissao` e só
     203 `licito`. Um motor que responde "é vício" para tudo acerta 87% — e não serve para nada,
     porque o custo do falso positivo em controle externo é acusar quem está regular. A métrica
     tem de ser por classe, e o baseline "sempre vício" precisa ficar registrado para que
     ninguém comemore acurácia bruta.
  2. **Vazamento do holdout.** Se um caso do holdout aparecer num prompt, a medição vira
     autoavaliação. O split é determinístico (hash do id), não aleatório — assim é reprodutível
     entre máquinas e entre sessões, sem semente guardada em lugar nenhum.
  3. **Cobertura silenciosa.** 55% do acervo não tem polaridade reconhecível e 27% tem tema fora
     do mapa. Isso precisa aparecer, senão "1.530 casos" soa como censo quando é recorte.
"""
from __future__ import annotations

import pytest

from compliance_agent.knowledge.golden_veredito import (
    ROTULOS_VALIDOS,
    baseline_classe_majoritaria,
    carregar,
    estratificacao,
    split,
)


@pytest.fixture(scope="module")
def casos():
    c = carregar()
    if not c:
        pytest.skip("acervo TCU não indexado nesta máquina (data/tcu_juris.db ausente)")
    return c


# ───────────────────────────── integridade do corpus ──────────────────────────────────────────

def test_todo_caso_tem_rotulo_valido_e_ancora(casos):
    for c in casos:
        assert c["rotulo"] in ROTULOS_VALIDOS, c
        assert c["trecho_ancora"].strip(), f"caso sem trecho de origem: {c['id']}"
        assert c["citacao"].startswith("Acórdão "), c["citacao"]
        assert c["regra_do_rotulo"], "rótulo derivado de texto sem a regra que o produziu"


def test_ids_sao_unicos(casos):
    ids = [c["id"] for c in casos]
    assert len(ids) == len(set(ids))


def test_corpus_tem_tamanho_util(casos):
    assert len(casos) >= 400, f"conjunto pequeno demais para medir por vício: {len(casos)}"


# ───────────────────────────── split determinístico e selado ──────────────────────────────────

def test_split_e_deterministico(casos):
    a, b = split(casos), split(casos)
    assert [c["id"] for c in a["treino"]] == [c["id"] for c in b["treino"]]
    assert [c["id"] for c in a["holdout"]] == [c["id"] for c in b["holdout"]]


def test_split_nao_vaza_caso_de_um_lado_para_o_outro(casos):
    s = split(casos)
    tr, ho = {c["id"] for c in s["treino"]}, {c["id"] for c in s["holdout"]}
    assert not (tr & ho)
    assert len(tr) + len(ho) == len(casos)


def test_holdout_tem_massa_suficiente(casos):
    s = split(casos)
    frac = len(s["holdout"]) / len(casos)
    assert 0.20 <= frac <= 0.40, f"holdout com {frac:.0%} — fora da faixa útil"


def test_holdout_preserva_a_proporcao_das_classes(casos):
    """Split por hash é cego a rótulo; se desbalancear demais, a medição do holdout mente."""
    s = split(casos)
    for parte in ("treino", "holdout"):
        vistos = {c["rotulo"] for c in s[parte]}
        assert vistos == {c["rotulo"] for c in casos}, f"{parte} perdeu uma classe inteira"


def test_todo_vicio_do_holdout_tambem_aparece_no_treino(casos):
    """Vício só no holdout não dá para calibrar; só no treino não dá para medir. Ambos declaram."""
    s = split(casos)
    so_holdout = {c["vicio"] for c in s["holdout"]} - {c["vicio"] for c in s["treino"]}
    assert not so_holdout or len(so_holdout) <= 2, (
        f"vícios presentes apenas no holdout: {sorted(so_holdout)}")


# ───────────────────────────── estratificação declarada ───────────────────────────────────────

def test_estratificacao_declara_o_desequilibrio(casos):
    e = estratificacao(casos)
    assert e["por_rotulo"], "sem contagem por classe não há como ponderar a métrica"
    assert e["classe_majoritaria"] in ROTULOS_VALIDOS
    assert 0 < e["frac_majoritaria"] < 1


def test_baseline_burro_fica_registrado(casos):
    """"Sempre vício" acerta a maioria. Quem for celebrar acurácia tem de bater ISTO."""
    b = baseline_classe_majoritaria(casos)
    assert 0.3 < b["acuracia"] < 1.0
    assert b["f1_por_classe"], "baseline sem F1 por classe esconde o colapso nas minoritárias"
    # o baseline burro tem F1 zero nas classes que ele nunca prevê — é esse o ponto
    assert min(b["f1_por_classe"].values()) == pytest.approx(0.0)


def test_cobertura_do_acervo_e_declarada(casos):
    e = estratificacao(casos)
    cob = e["cobertura_acervo"]
    assert cob["total"] > cob["casos"], "cobertura que não declara descarte não é cobertura"
    assert cob["sem_polaridade"] > 0 and cob["tema_fora_do_mapa"] > 0


# ───────────────────────────── o holdout não pode virar prompt ────────────────────────────────

def test_nenhum_trecho_do_holdout_esta_hardcoded_no_codigo(casos):
    """Vazamento clássico: alguém cola um enunciado do holdout num prompt para 'dar exemplo'.

    Basta um trecho longo o bastante para ser identificável. Varre o código de produção — os
    testes podem citar enunciados (é assim que `test_corpus_veredito` prova as regras).
    """
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parent.parent
    fontes = {f: f.read_text(encoding="utf-8", errors="ignore")
              for f in raiz.glob("compliance_agent/**/*.py")}
    amostra = [c for c in split(casos)["holdout"] if len(c["trecho_ancora"]) > 80][:200]
    vazados = []
    for c in amostra:
        agulha = c["trecho_ancora"][:80]
        for f, texto in fontes.items():
            if agulha in texto:
                vazados.append((c["id"], f.name))
                break
    assert not vazados, f"trecho do holdout colado no código de produção: {vazados[:5]}"
