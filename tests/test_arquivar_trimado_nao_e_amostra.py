# -*- coding: utf-8 -*-
"""Excerto de STORAGE (`_trimado`) não pode reprovar a qualidade de um processo RELIDO.

`qualidade_cache` decide se o cache pode virar arquivo consultável medindo a fração de documentos
com texto na faixa 390–410 chars — a assinatura do corte do sweep. A ideia é boa: veredito sobre
migalha é pior que nada.

O DEFEITO (medido 2026-08-09 no caso FSERJ). Quando um processo é RELIDO por inteiro, a fusão de
cache preserva as entradas antigas (política correta: releitura pior não apaga texto pago), e essas
entradas são justamente excertos `_trimado` de 400 chars. No SEI-080002/018759/2025 sobraram 8
excertos ao lado de 34 documentos lidos na íntegra: **9 de 42 = 21%** caem na faixa, acima do
limiar de 20% ⇒ "misto" ⇒ o arquivador RECUSA. Sem os excertos: 1 de 34 = 3% ⇒ "completo".

Ou seja: quanto mais fundo se lê um processo, mais provável que ele seja recusado — o inverso do
que a régua quer. `_trimado` marca documento JÁ LIDO cujo cru virou excerto depois da ficha
(ver `tools/sei_sweep.py`), não captura rasa; medir qualidade com ele dentro é medir a política
de storage, não a leitura.
"""
from __future__ import annotations

from tools.sei_arquivar_do_cache import qualidade_cache


def _doc(n: int, *, trimado: bool = False) -> dict:
    d = {"doc": "X", "conteudo": "x" * n}
    if trimado:
        d["_trimado"] = True
    return d


def test_relido_com_excertos_antigos_e_completo():
    """34 lidos na íntegra + 8 excertos de storage = processo COMPLETO, não misto."""
    cd = [_doc(9000) for _ in range(33)] + [_doc(400)] + [_doc(400, trimado=True) for _ in range(8)]
    assert qualidade_cache(cd) == "completo", (
        "excerto de storage reprovou um processo lido por inteiro — o arquivador recusa "
        "justamente o que foi mais bem lido")


def test_captura_rasa_de_verdade_continua_amostra():
    """Sem marca de storage, texto todo na faixa do corte segue sendo amostra."""
    assert qualidade_cache([_doc(400) for _ in range(10)]) == "amostra"


def test_blob_so_de_excertos_nao_vira_arquivo():
    """Cache antigo 100% trimado não tem leitura NENHUMA a arquivar — segue recusado."""
    assert qualidade_cache([_doc(400, trimado=True) for _ in range(10)]) == "amostra"


def test_misto_real_continua_misto():
    """Metade no corte, sem marca de storage: continua misto (não é storage, é leitura ruim)."""
    cd = [_doc(9000) for _ in range(5)] + [_doc(400) for _ in range(5)]
    assert qualidade_cache(cd) == "misto"
