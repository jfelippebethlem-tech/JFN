# -*- coding: utf-8 -*-
"""O gate de citações vale para TODO canal, não só para o parecer.

Já encontramos quatro acórdãos impossíveis por aritmética na base curada. O dano de afirmar um
acórdão inexistente é o mesmo no PDF e no Telegram — o que muda é a forma do aviso: nota
completa de conferência na peça, uma linha no chat.
"""
from __future__ import annotations

from compliance_agent.reporting.gate_citacoes import sanear_canal


def test_citacao_impossivel_e_suprimida_no_canal():
    saida = sanear_canal("Conforme o Acórdão 9999/2024-Plenário, o gestor responde.",
                         contexto="teste")
    assert "9999" not in saida


def test_texto_limpo_sai_sem_rodape():
    """Rodapé em toda resposta seria ruído; só aparece quando algo mudou."""
    limpo = "O contrato foi assinado em março e a execução começou em abril."
    assert sanear_canal(limpo, contexto="teste") == limpo


def test_rodape_de_uma_linha_quando_houve_supressao():
    saida = sanear_canal("Vide Acórdão 9999/2024-Plenário.", contexto="teste")
    rodape = [ln for ln in saida.splitlines() if "Conferência de citações" in ln]
    assert len(rodape) == 1


def test_nunca_levanta_mesmo_com_entrada_estranha():
    """Uma dúvida de citação não pode derrubar a resposta ao usuário."""
    for entrada in ("", None, "Acórdão sem número", "🙂"):
        sanear_canal(entrada or "", contexto="teste")
