# -*- coding: utf-8 -*-
"""Aborto de CONFIGURAÇÃO que se repete a cada rodada deve se auto-silenciar — senão vira ruído.

A 'Maps Embed API' está desabilitada no Google Cloud do dono. É config que só ele resolve, e que
nenhuma rodada do sweep muda — mas o sweep tentava a cada 3 h e registrava `rc=3`. Medido em
2026-08-08: 20 abortos idênticos na auditoria, um alarme permanente que dessensibiliza a tabela
inteira. Foi exatamente nessa tabela, dessensibilizada, que a recaptura morta passou 4 dias
invisível.

A régua (a mesma do refichar e da sentinela): alarme que não muvuca ação vira alarme desligado.
Depois de 3 abortos idênticos consecutivos, o sweep cria o próprio flag de pausa, com o motivo e o
que o dono precisa fazer ESCRITO nele. Reabilitar a API zera o contador; render bem-sucedido zera
o contador. Só o flag de pausa fica para o dono apagar à mão — de propósito, porque a decisão de
retomar é dele.

NÃO é "culpar o acesso": o próprio Google Cloud reporta a API como desabilitada. É config ausente,
não fonte negada — a distinção que a doutrina da casa exige.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TOOL = RAIZ / "tools" / "fachada_streetview_sweep.py"


def _fonte() -> str:
    return TOOL.read_text(encoding="utf-8")


def test_conta_abortos_seguidos_e_pausa_no_terceiro():
    f = _fonte()
    # o contador existe e o limiar é 3
    assert ".streetview_403_seguidos" in f, "o contador de abortos seguidos sumiu"
    assert re.search(r"if n >= 3:", f), "o limiar de auto-pausa mudou sem que este teste soubesse"
    assert ".pause_fachada_streetview_sweep" in f, "a auto-pausa não cria o flag de pausa"


def test_o_flag_de_pausa_diz_ao_dono_o_que_fazer():
    """Flag mudo é pior que nenhum: quem o encontra tem de saber por que existe e como sair."""
    f = _fonte()
    m = re.search(r'pausa\.write_text\(\s*\n?\s*"([^"]+(?:"\s*\n?\s*"[^"]+)*)"', f)
    assert m, "não achei o texto do flag de pausa"
    texto = m.group(0)
    assert "Maps Embed API" in texto, "o flag não nomeia a causa"
    assert "APAGUE" in texto or "apague" in texto, "o flag não diz COMO retomar"


def test_recuperacao_zera_o_contador():
    """API que volta a responder não pode deixar dívida de abortos antigos travando o próximo."""
    f = _fonte()
    assert re.search(r"_marca_403.*\.unlink\(\)", f, re.S), (
        "o contador não é zerado quando a API responde — uma habilitação futura não limparia o "
        "histórico e o sweep pausaria à toa")


def test_nao_culpa_acesso_nem_waf():
    """A doutrina da casa: nunca culpar acesso/WAF. Aqui a causa é config, e o texto tem de dizê-lo."""
    f = _fonte()
    bloco = f[f.index("Maps Embed API 403"):]
    bloco = bloco[:2000]
    assert "DESABILITADA no projeto Google Cloud" in bloco or "desabilitada" in bloco.lower(), (
        "o aborto tem de atribuir a causa à CONFIGURAÇÃO (API desabilitada), não a acesso/WAF")
