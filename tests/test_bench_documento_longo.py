# -*- coding: utf-8 -*-
"""A prova que faltava: compreensão de DOCUMENTO LONGO.

Lacuna que eu mesmo declarei e o dono desconfiava desde o início — "modelos fracos como o gemma
não vão analisar os documentos direito". As outras quatro provas usam textos curtos e não medem
isso: janela grande diz quanto texto CABE, não quanto o modelo ENTENDE depois de atravessá-lo.

O documento é REAL (~25 mil tokens, do acervo) e as perguntas foram escolhidas por propriedades
que um teste sintético não teria: o valor pedido está a **78% de profundidade**, e há **dois**
números de empenho espalhados — perguntar "quais" mede COMPLETUDE, não só recuperação.

A pontuação é assimétrica de propósito: "não localizei" vale 20 e um valor inventado vale 0.
Nesta casa, errar com confiança é pior que se declarar incapaz.
"""
from __future__ import annotations

import pytest

from tools.bench_modelos import PROVAS, _p_documento_longo


def test_resposta_completa_e_correta_vale_tudo():
    assert _p_documento_longo(
        "Val Aprox Tributos: R$ 74.650,31. Empenhos: 2024NE07134 e 2024NE08035.") == 100


def test_achar_so_um_empenho_perde_pontos_de_completude():
    """Achar um dos dois é o resultado típico de quem desiste no meio do documento."""
    parcial = _p_documento_longo("R$ 74.650,31 e o empenho 2024NE07134.")
    assert 50 < parcial < 100


def test_valor_inventado_zera():
    """Alucinação com aparência de resposta é o dano que mais importa evitar."""
    assert _p_documento_longo("O valor dos tributos é R$ 12.345,67.") == 0


def test_falha_honesta_vale_mais_que_alucinacao():
    honesta = _p_documento_longo("Não localizei o valor dos tributos no documento.")
    assert honesta > _p_documento_longo("O valor dos tributos é R$ 99.999,99.")
    assert honesta > 0


def test_completude_pontua_mesmo_sem_o_valor():
    """As duas dimensões são independentes: recuperação e cobertura do documento."""
    assert _p_documento_longo("Empenhos: 2024NE07134 e 2024NE08035.") >= 50


@pytest.mark.parametrize("resp", ["", "   ", "não sei responder"])
def test_resposta_vazia_ou_evasiva_nao_quebra(resp):
    assert 0 <= _p_documento_longo(resp) <= 100


def test_prova_entra_no_banco_quando_o_acervo_existe():
    nomes = [p[0] for p in PROVAS]
    assert "documento_longo" in nomes, (
        "a prova sai do banco quando o acervo não está disponível — mas ele está")


def test_execucao_de_prova_unica_produz_nota():
    """O piso de 3 provas existe para não pontuar quem mal foi medido — mas bloqueava
    `--tarefa documento_longo`, que é a execução deliberadamente restrita. O mínimo passou a
    ser o menor entre o piso e o número de provas PEDIDAS."""
    from unittest.mock import patch

    from tools import bench_modelos as B

    with patch.object(B, "_chamar_com_paciencia",
                      return_value="R$ 74.650,31 · 2024NE07134 e 2024NE08035"):
        r = B.avaliar_modelo("modelo/x:free", ["documento_longo"])
    assert r["nota"] == 100.0, "prova única tem de produzir nota"
    assert r["n_provas"] == 1


def test_prova_isolada_nao_apaga_as_medicoes_anteriores(tmp_path, monkeypatch):
    """`detalhe.update({modelo: novo})` substituía o dicionário inteiro: rodar
    `--tarefa documento_longo` apagava rubrica/ausência/extração, e o perfil `fast` ficava sem
    medição. Mesma família do "medição acumula, não substitui" já corrigido no nível do modelo."""
    import json

    from tools import bench_modelos as B

    ranking = tmp_path / "r.json"
    ranking.write_text(json.dumps({
        "notas": {"m/x:free": 100.0},
        "detalhe": {"m/x:free": {"rubrica": {"nota": 100}, "ausencia": {"nota": 100}}},
    }))
    monkeypatch.setattr(B, "SAIDA", ranking)

    anterior = json.loads(ranking.read_text())
    detalhe = dict(anterior["detalhe"])
    novo = {"modelo": "m/x:free", "nota": 0.0, "detalhe": {"documento_longo": {"nota": 0}}}
    alvo = detalhe.setdefault(novo["modelo"], {})
    alvo.update(novo["detalhe"])

    assert set(detalhe["m/x:free"]) == {"rubrica", "ausencia", "documento_longo"}, \
        "as provas antigas foram apagadas pela execução isolada"
