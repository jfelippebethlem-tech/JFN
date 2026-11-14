# -*- coding: utf-8 -*-
"""Catraca CST-03 — motor do AO VIVO sem `efeito` declarado só diminui; motor novo nasce com `efeito` (+ prova)."""
from __future__ import annotations

from compliance_agent.qualidade import catraca
from compliance_agent.qualidade.catracas import motores_sem_efeito

BASE = "motores_sem_efeito"


def test_catraca_motores_sem_efeito():
    excesso = catraca.cresceu(motores_sem_efeito(), catraca.ler_base(BASE))
    assert not excesso, catraca.mensagem("CST-03", "motor do AO VIVO sem `efeito` declarado", excesso)


def test_prova_motor_novo_sem_efeito_e_acusado(tmp_path):
    arq = tmp_path / "compliance_agent" / "aovivo" / "motores.yaml"
    arq.parent.mkdir(parents=True)
    arq.write_text(
        "motores:\n"
        "  - {id: velho, classe: motor}\n"
        "  - {id: com_efeito, classe: motor, efeito: {arquivo: data/x.json, horas: 24}}\n"
        "  - {id: apoio, classe: infra}\n"
        "  - {id: novo, classe: motor}\n", encoding="utf-8")
    atual = motores_sem_efeito(tmp_path)
    assert atual == {"velho": 1, "novo": 1}               # infra e motor com efeito não contam
    assert catraca.cresceu(atual, {"velho": 1}) == ["novo: 1 (base 0)"]   # o novo fica vermelho
    assert not catraca.cresceu({"velho": 1}, {"velho": 1, "curado": 1})   # curar só desce
