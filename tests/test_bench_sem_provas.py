# -*- coding: utf-8 -*-
"""Nenhuma prova medida é INDISPONÍVEL — não é nota zero, e não é crash.

Achado pela VM-2 em 2026-07-28: três testes de `test_bench_documento_longo` morriam com
`ZeroDivisionError` em `tools/bench_modelos.py:381`, numa máquina sem o acervo. Não era
ambiente: é código sem guarda.

O caminho até o defeito é instrutivo. O piso `MIN_PROVAS_MEDIDAS` existe para não dar nota a
quem mal foi medido. Depois ele passou a atrapalhar execução deliberadamente restrita
(`--tarefa documento_longo`), e virou `minimo = min(MIN_PROVAS_MEDIDAS, len(provas))`. Com
ZERO provas — filtro que não casa nada, acervo ausente —, `minimo` é 0, `len(notas) >= 0` é
verdade, e o "medido" abre caminho para `sum(notas) / len(notas)`.

Correção do piso, não do sintoma: sem prova alguma, nada foi medido. `nota` é `None`
(INDISPONÍVEL), como já é para quem foi medido de menos — a mesma regra que esta casa já
teve de aprender dentro da própria ferramenta de medir, quando ela somava 0 para prova que
estourou por 429.
"""
import tools.bench_modelos as B


def test_nenhuma_prova_casa_o_filtro_nao_divide_por_zero(monkeypatch):
    """`--tarefa` que não casa nada: zero provas, e `minimo` virava 0 — logo "medido"."""
    def nunca_chamado(*a, **k):
        raise AssertionError("sem provas, nenhum modelo deveria ser chamado")

    monkeypatch.setattr(B, "_chamar_com_paciencia", nunca_chamado)
    r = B.avaliar_modelo("modelo/qualquer", tarefas=["tarefa_que_nao_existe"])
    assert r["nota"] is None, "sem prova medida a nota é INDISPONÍVEL, nunca 0,0"
    assert r["n_provas"] == 0


def test_uma_prova_pedida_e_medida_continua_valendo(monkeypatch):
    """O piso não pode voltar a bloquear execução deliberadamente restrita a uma prova."""
    monkeypatch.setattr(B, "_chamar_com_paciencia", lambda *a, **k: "resposta")
    uma = B.PROVAS[0][0]
    r = B.avaliar_modelo("modelo/qualquer", tarefas=[uma])
    assert r["n_provas"] == 1
    assert r["nota"] is not None, "uma prova PEDIDA e medida tem nota — esse foi o motivo do min()"
