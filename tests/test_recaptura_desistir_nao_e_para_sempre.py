# -*- coding: utf-8 -*-
"""Uma tentativa sem ganho excluía o processo da recaptura PARA SEMPRE.

O `sei_sweep` já aplica a doutrina desde 2026-08-04 — a tentativa expira em 14 dias, porque "a
abertura do SEI é flaky" e 2.131 dos 2.760 processos abandonados o foram sob episódios de WAF que
já passaram. A fila da recaptura não tinha nada disso: bastava constar do registro para nunca mais
voltar.

Medido em 2026-08-05, o registro tinha 5 entradas e **4 com `lido_antes == lido_depois`** — nenhum
ganho, três delas paradas em 40/40, ou seja, exatamente os casos de teto de coleta que mais
precisam voltar. E as tentativas com +0 são conhecidas e documentadas no próprio módulo: browser
morto (`TargetClosedError`), login que não venceu o WAF, processo gigante que estoura o slot.

Marcar fracasso transitório como "feito" transforma condição passageira em exclusão permanente.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from tools.sweep_recaptura_integral import _sem_ganho_expirou


def test_quem_ganhou_documentos_nao_volta():
    assert _sem_ganho_expirou({"lido_antes": 40, "lido_depois": 65}) is False


def test_tentativa_recente_sem_ganho_respeita_o_cooloff():
    """Não é para martelar: dentro da janela, a tentativa vale e o processo espera."""
    agora = datetime.now().isoformat(timespec="seconds")
    assert _sem_ganho_expirou({"lido_antes": 40, "lido_depois": 40, "em": agora}) is False


def test_tentativa_antiga_sem_ganho_ganha_nova_chance():
    velho = (datetime.now() - timedelta(days=8)).isoformat(timespec="seconds")
    assert _sem_ganho_expirou({"lido_antes": 40, "lido_depois": 40, "em": velho}) is True


def test_registro_sem_data_ganha_nova_chance():
    """São os 4 do registro antigo — gravados antes de existir carimbo de tempo. Excluí-los para
    sempre por falta de metadado seria punir o processo pelo defeito do nosso registro."""
    assert _sem_ganho_expirou({"lido_antes": 40, "lido_depois": 40}) is True
