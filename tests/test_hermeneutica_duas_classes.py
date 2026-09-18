# -*- coding: utf-8 -*-
"""A pergunta que a fila do fiscal faz é binária: isso é irregular ou não?

Por que este modo existe. O corpus tem três rótulos, mas `vicio_por_omissao` é propriedade da
FORMA da frase, não da conduta: verbo de dever em 774 dos 776 casos dessa classe (100%), contra
36% de `vicio` e 24% de `licito`. Com o verbo apagado a classe é impossível; com o verbo
presente ela é trivial. Medir três classes assim mede gramática, não hermenêutica.

Duas classes resolvem a pergunta que importa — e, para o número ser interpretável, entra o
BASELINE DEÔNTICO: um papagaio de uma linha que responde "irregular" sempre que houver verbo de
dever. Ele mede exatamente o atalho. Motor que não bate esse papagaio não está julgando nada.
"""
import pytest

from compliance_agent.knowledge import golden_veredito as G


def test_binarizar_une_as_duas_faces_do_vicio():
    assert G.binarizar("vicio") == "irregular"
    assert G.binarizar("vicio_por_omissao") == "irregular"
    assert G.binarizar("licito") == "licito"


@pytest.mark.parametrize("abst", ["nao_sei", "indisponivel", "citacao_nao_ancorada", "invalido"])
def test_binarizar_preserva_a_abstencao(abst):
    """Abstenção não pode virar 'lícito' por descuido — ela é métrica própria da casa."""
    assert G.binarizar(abst) == abst


def test_metricas_aceita_o_conjunto_binario_de_rotulos():
    pares = [("irregular", "irregular"), ("licito", "licito"),
             ("irregular", "licito"), ("licito", "nao_sei")]
    m = G.metricas(pares, rotulos=G.ROTULOS_BINARIOS)
    assert set(m["f1_por_classe"]) == {"irregular", "licito"}
    assert m["abstencao"] == 0.25


def test_baseline_deontico_e_o_papagaio_a_bater():
    casos = [
        {"id": "1", "rotulo": "vicio_por_omissao", "trecho_ancora": "A Administração deve descontar."},
        {"id": "2", "rotulo": "licito", "trecho_ancora": "A adoção do pregão é admissível."},
        {"id": "3", "rotulo": "vicio", "trecho_ancora": "Exigência de atestado sem justificativa."},
    ]
    b = G.baseline_deontico(casos)
    # acerta 1 e 2 pelo verbo; erra 3 (vício sem verbo de dever)
    assert b["acuracia"] == pytest.approx(2 / 3)
    assert "f1_macro" in b and b["regra"]


def test_baseline_deontico_com_corpus_vazio_nao_inventa():
    assert G.baseline_deontico([])["acuracia"] == 0.0


# ───── a catraca não pode comparar réguas diferentes ─────

def test_catraca_recusa_comparar_modos_diferentes():
    """O baseline de 2026-08-02 (F1 0,48) foi medido em 3 classes sobre enunciado mutilado.
    Confrontá-lo com um F1 de 2 classes acusaria regressão ou melhoria inexistente."""
    from tools.eval_hermeneutica import comparar_com_baseline
    c = comparar_com_baseline({"modo": "2classes", "f1_macro": 0.40},
                              {"modo": "3classes", "f1_macro": 0.48})
    assert c["modo_incompativel"] is True
    assert c["regressoes"] == [] and c["melhorias"] == []


def test_catraca_compara_normalmente_dentro_do_mesmo_modo():
    from tools.eval_hermeneutica import comparar_com_baseline
    c = comparar_com_baseline({"modo": "2classes", "f1_macro": 0.30},
                              {"modo": "2classes", "f1_macro": 0.60})
    assert not c["ok"] and c["regressoes"]
