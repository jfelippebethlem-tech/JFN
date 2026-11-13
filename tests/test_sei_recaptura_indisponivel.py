# -*- coding: utf-8 -*-
"""Recaptura que não abriu a árvore NÃO é "N → 0 docs com texto".

Laudo dos motores (13/11/2026): `SEI-270005/001173/2024: 127 → 0` em 12/11 22:01:54 — o `.zst`
do cache seguiu com mtime de 05/11 e o acervo com 127 textos, ou seja, nada se perdeu; a leitura
é que não abriu (`ler_processo` devolveu `indisponivel`). Mesmo assim a linha afirmava a perda e
o processo entrava em `recaptura_feitos` como releitura sem ganho, saindo da fila por 7 dias.
INDISPONÍVEL ≠ 0: a leitura falha não vira registro de resultado, e volta no dia seguinte.
"""
from datetime import datetime, timedelta

from tools import sei_sweep as S


def test_zero_com_indisponivel_e_leitura_falha():
    assert S.recap_leitura_indisponivel({"indisponivel": True, "documentos": []}, 0) is True


def test_zero_com_arvore_aberta_e_resultado_real():
    """Árvore abriu e não rendeu texto: isso É resultado (registra como sem ganho)."""
    assert S.recap_leitura_indisponivel({"documentos": [{"url": "u"}]}, 0) is False


def test_com_texto_nunca_e_indisponivel():
    assert S.recap_leitura_indisponivel({"indisponivel": True}, 5) is False


def test_indisponivel_recente_espera_um_dia():
    agora = datetime(2026, 11, 13, 10, 0)
    reg = {"P": (agora - timedelta(hours=3)).isoformat(timespec="seconds"),
           "Q": (agora - timedelta(hours=30)).isoformat(timespec="seconds"),
           "R": "lixo"}
    assert S.recap_indisponivel_recente(reg, "P", agora) is True
    assert S.recap_indisponivel_recente(reg, "Q", agora) is False
    assert S.recap_indisponivel_recente(reg, "R", agora) is False, "data ilegível não segura"
    assert S.recap_indisponivel_recente(reg, "nunca", agora) is False


def test_laco_da_recaptura_usa_a_guarda():
    """O laço não pode voltar a gravar `feitos` antes de perguntar se a leitura falhou."""
    import inspect
    fonte = inspect.getsource(S.run_recaptura)
    i_guarda = fonte.find("recap_leitura_indisponivel(")
    i_feitos = fonte.find("feitos[proc] =")
    assert 0 < i_guarda < i_feitos
    assert "recap_indisponivel_recente(" in fonte
