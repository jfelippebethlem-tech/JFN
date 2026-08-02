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
