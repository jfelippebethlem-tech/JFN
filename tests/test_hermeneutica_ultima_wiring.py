# -*- coding: utf-8 -*-
"""A medição tem de CHEGAR ao card — o cano estava cortado no meio.

Medido em 2026-08-02: o card de acurácia (`painel_acuracia.montar`) lê
`data/hermeneutica_ultima.json` e diz "ainda não medido neste ambiente — rode
`tools/eval_hermeneutica --holdout --aceitar`". Só que **nada no repositório escrevia esse
arquivo**: `--aceitar` grava apenas o baseline. O card mandava rodar exatamente o comando que
não o preenchia, e por isso ficaria "sem medição" para sempre, por mais vezes que se medisse.

É a família de falha mais cara da casa: construído, testado, e nunca conectado.
"""
import json

from compliance_agent.reporting import painel_acuracia as PA
from tools import eval_hermeneutica as EH


def test_o_medidor_grava_o_arquivo_que_o_card_le():
    """Contrato entre as duas pontas: quem mede escreve onde quem mostra lê."""
    assert EH.ULTIMA_PADRAO == PA.CAMINHO_ULTIMA, (
        "o medidor grava num caminho e o card lê de outro — o cano continua cortado")


def test_gravar_ultima_produz_o_que_o_card_precisa(tmp_path):
    alvo = tmp_path / "ultima.json"
    EH.gravar_ultima({"n": 100, "acuracia": 0.43, "f1_macro": 0.48,
                      "alucinacao_citacao": 0.01, "abstencao": 0.17,
                      "f1_por_classe": {"vicio": 0.6}}, str(alvo))
    d = json.loads(alvo.read_text(encoding="utf-8"))
    assert d["f1_macro"] == 0.48
    assert d["medido_em"], "sem carimbo de data o card mostraria número velho como se fosse atual"
    assert PA.montar(caminho_ultima=str(alvo), caminho_baseline=str(alvo))["medido_em"], (
        "a data não chega ao card — a chave gravada não é a que ele lê")
    card = PA.montar(caminho_ultima=str(alvo), caminho_baseline=str(alvo))
    assert card["estado"] != "sem_medicao"
    assert card["f1_macro"] == 0.48


# ───── queda de provedor NÃO é qualidade zero (2026-08-03) ─────
# O loop 2 fez toda medição publicar no card. Na primeira execução seguinte, Gemini e Cerebras
# falharam em 100% dos casos e o card passou a exibir "F1 0,0 · insuficiente" — o próprio
# `painel_acuracia` chama isso de mentira ("um card com '—' tratado como 0% é mentira").
# INDISPONÍVEL ≠ 0: medição que não mediu não se publica.

def test_medicao_com_provedor_fora_do_ar_nao_e_publicada(tmp_path):
    alvo = tmp_path / "ultima.json"
    r = EH.gravar_ultima({"n": 100, "f1_macro": 0.0, "acuracia": 0.0,
                          "indisponivel": 1.0, "abstencao": 1.0}, str(alvo))
    assert r is None, "publicou uma queda de provedor como se fosse desempenho do motor"
    assert not alvo.exists()


def test_medicao_com_indisponibilidade_parcial_tolerada_e_publicada(tmp_path):
    alvo = tmp_path / "ultima.json"
    assert EH.gravar_ultima({"n": 100, "f1_macro": 0.5, "acuracia": 0.5,
                             "indisponivel": 0.08, "abstencao": 0.2}, str(alvo)) is not None


def test_a_publicacao_nao_apaga_a_medicao_boa_anterior(tmp_path):
    """Falha de provedor não pode derrubar o último número válido — o card ficaria pior que antes."""
    alvo = tmp_path / "ultima.json"
    EH.gravar_ultima({"n": 100, "f1_macro": 0.48, "indisponivel": 0.11}, str(alvo))
    EH.gravar_ultima({"n": 100, "f1_macro": 0.0, "indisponivel": 1.0}, str(alvo))
    import json as _j
    assert _j.loads(alvo.read_text(encoding="utf-8"))["f1_macro"] == 0.48


def test_amostra_pequena_nao_vira_o_numero_do_painel(tmp_path):
    """Uma sondagem de 6 casos publicou-se no card em 2026-08-03, durante a depuração. Amostra
    de teste não é medição: o card fala do motor para quem lê o relatório."""
    alvo = tmp_path / "ultima.json"
    assert EH.gravar_ultima({"n": 6, "f1_macro": 0.53, "indisponivel": 0.0}, str(alvo)) is None
    assert EH.gravar_ultima({"n": 100, "f1_macro": 0.53, "indisponivel": 0.0}, str(alvo))
