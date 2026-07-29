# -*- coding: utf-8 -*-
"""O harness de medição — e as armadilhas que fariam o número medir a coisa errada.

Um harness de avaliação mal desenhado é pior que nenhum: ele produz um número alto, o número
entra no relatório, e a partir daí ninguém questiona a qualidade do motor. Três defeitos que
travamos aqui, todos capazes de inflar o resultado sozinhos:

  1. **Enunciado com a resposta dentro.** "É irregular a exigência de X" contém o veredito. Se o
     texto for apresentado assim, o modelo transcreve e o harness mede leitura, não hermenêutica.
  2. **Citação inventada valendo como acerto.** Rótulo certo com trecho que não existe no texto é
     sorte com aparência de prova — e é exatamente o que precisa aparecer na métrica.
  3. **Acurácia sem baseline.** O corpus é 51% `vicio_por_omissao`; um motor que responde sempre
     essa classe acerta metade. O baseline burro sai junto do resultado, sempre.

Tudo com `gerar` injetado: nenhum teste aqui toca a rede.
"""
from __future__ import annotations

import json

import pytest

from tools.eval_hermeneutica import (
    avaliar,
    avaliar_caso,
    mascarar_conclusao,
    por_vicio,
)


def _caso(rotulo="vicio", trecho=None, vicio="barreira_habilitacao", ident="c1"):
    return {"id": ident, "rotulo": rotulo, "vicio": vicio, "condicionada": False,
            "trecho_ancora": trecho or ("É irregular a exigência de comprovação de propriedade "
                                        "de equipamentos como requisito de habilitação.")}


def _resposta(classe, citacao, **extra):
    return lambda *_a, **_k: json.dumps({"classe": classe, "citacao": citacao,
                                         "fundamento": "x", **extra})


# ───────────────────────── 1. a conclusão não pode ir junto ───────────────────────────────────

@pytest.mark.parametrize("entrada,proibido", [
    ("É irregular a exigência de X.", "irregular"),
    ("É ilegal a exigência de Y.", "ilegal"),
    ("Não é obrigatório que o orçamento seja parte do edital.", "obrigatório"),
    ("É vedada a exigência de Z.", "vedada"),
    ("Não configura irregularidade a adoção de W.", "configura"),
])
def test_mascara_remove_o_veredito(entrada, proibido):
    saida = mascarar_conclusao(entrada)
    assert proibido.lower() not in saida.lower(), f"{entrada!r} → {saida!r}"
    assert saida.strip(), "mascarar não pode esvaziar o texto"


def test_mascara_de_dever_remove_o_verbo_mas_preserva_a_conduta():
    e = ("A demonstração da vantagem de renovação deve ser realizada mediante ampla pesquisa "
         "de preços.")
    saida = mascarar_conclusao(e)
    assert "pesquisa de preços" in saida
    assert not saida.lower().startswith("deve")


def test_texto_sem_formula_conhecida_passa_intacto():
    e = "A exigência de atestado com quantitativo superior a 50% do objeto licitado."
    assert mascarar_conclusao(e) == e


def test_mascara_nunca_devolve_vazio():
    assert mascarar_conclusao("É irregular.").strip()


# ───────────────────────── 2. citação tem de existir na fonte ─────────────────────────────────

def test_rotulo_certo_com_citacao_inventada_nao_conta_como_acerto():
    r = avaliar_caso(_caso(), _resposta("vicio", "trecho que jamais apareceu no texto"))
    assert r["previsto"] == "citacao_nao_ancorada"
    assert r["ancorada"] is False


def test_rotulo_certo_com_citacao_real_conta():
    caso = _caso()
    trecho = mascarar_conclusao(caso["trecho_ancora"])[:50]
    r = avaliar_caso(caso, _resposta("vicio", trecho))
    assert r["previsto"] == "vicio" and r["ancorada"] is True


def test_citacao_curta_demais_nao_ancora():
    """Duas palavras casam com qualquer texto — não são âncora."""
    r = avaliar_caso(_caso(), _resposta("vicio", "de X"))
    assert r["previsto"] == "citacao_nao_ancorada"


def test_abstencao_e_registrada_como_tal_nao_como_erro():
    r = avaliar_caso(_caso(), _resposta("nao_sei", ""))
    assert r["previsto"] == "nao_sei"


def test_classe_fora_da_escala_vira_invalido():
    r = avaliar_caso(_caso(), _resposta("gravissimo", "de comprovação de propriedade"))
    assert r["previsto"] == "invalido"


def test_resposta_sem_json_nao_quebra():
    r = avaliar_caso(_caso(), lambda *_a, **_k: "desculpe, não consigo")
    assert r["previsto"] in {"invalido", "nao_sei"}


def test_provedor_fora_do_ar_e_indisponivel_nao_erro():
    def explode(*_a, **_k):
        raise RuntimeError("429")

    r = avaliar_caso(_caso(), explode)
    assert r["previsto"] == "indisponivel"
    assert "429" in r["erro"]


# ───────────────────────── 3. métricas e baseline ─────────────────────────────────────────────

def test_resultado_traz_o_baseline_burro_junto():
    casos = [_caso(rotulo="vicio", ident=f"a{i}") for i in range(6)]
    casos += [_caso(rotulo="licito", ident=f"b{i}") for i in range(2)]
    r = avaliar(casos, _resposta("vicio", "de comprovação de propriedade de equipamentos"))
    assert "baseline_burro" in r and r["baseline_burro"]["classe"] == "vicio"
    assert "bate_o_baseline" in r


def test_motor_que_responde_sempre_a_mesma_classe_nao_bate_o_baseline():
    """O ponto do baseline: papagaio tem acurácia alta e F1 macro baixo."""
    casos = [_caso(rotulo="vicio", ident=f"a{i}") for i in range(6)]
    casos += [_caso(rotulo="licito", ident=f"b{i}") for i in range(2)]
    r = avaliar(casos, _resposta("vicio", "de comprovação de propriedade de equipamentos"))
    assert r["acuracia"] == pytest.approx(0.75)
    assert r["bate_o_baseline"] is False, "papagaio não pode ser dado como melhoria"


def test_alucinacao_de_citacao_e_uma_metrica_de_primeira_classe():
    casos = [_caso(ident=f"a{i}") for i in range(4)]
    r = avaliar(casos, _resposta("vicio", "citação fabricada"))
    assert r["alucinacao_citacao"] == pytest.approx(1.0)
    assert r["acuracia"] == pytest.approx(0.0), "alucinar não pode contar como acerto"


def test_indisponibilidade_nao_se_confunde_com_erro_de_juizo():
    def explode(*_a, **_k):
        raise RuntimeError("provedor caiu")

    r = avaliar([_caso(ident=f"a{i}") for i in range(3)], explode)
    assert r["indisponivel"] == pytest.approx(1.0)
    assert r["f1_macro"] == pytest.approx(0.0)


def test_metricas_saem_por_classe_nao_so_agregadas():
    casos = [_caso(rotulo="vicio", ident="a"), _caso(rotulo="licito", ident="b")]
    r = avaliar(casos, _resposta("vicio", "de comprovação de propriedade de equipamentos"))
    assert set(r["por_classe"]) == {"vicio", "licito", "vicio_por_omissao"}
    assert r["por_classe"]["licito"]["recall"] == pytest.approx(0.0)


def test_quebra_por_vicio_existe():
    casos = [_caso(vicio="barreira_habilitacao", ident="a"),
             _caso(vicio="lote_pacote", ident="b")]
    r = avaliar(casos, _resposta("vicio", "de comprovação de propriedade de equipamentos"))
    pv = por_vicio(r)
    assert set(pv) == {"barreira_habilitacao", "lote_pacote"}


def test_versao_do_prompt_acompanha_o_resultado():
    """Sem versão de prompt não há como investigar regressão de qualidade depois."""
    r = avaliar([_caso()], _resposta("vicio", "de comprovação"))
    assert r["prompt_versao"]


def test_limite_respeitado():
    casos = [_caso(ident=f"a{i}") for i in range(10)]
    r = avaliar(casos, _resposta("nao_sei", ""), limite=3)
    assert r["n"] == 3
