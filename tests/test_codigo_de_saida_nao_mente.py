# -*- coding: utf-8 -*-
"""Passo agendado não pode reportar sucesso sem ter feito o que existe para fazer.

A AUDITORIA QUE ORIGINOU ISTO (2026-08-07). Depois de descobrir que a recaptura do SEI abortava o
login havia quatro dias, fui medir os 32 passos agendados desta casa pela taxa de `rc` nos logs de
sweep. A tabela dava `sei_recaptura: 16 execuções, 16 com rc=0` — saúde perfeita. E as 16 eram
justamente os 16 abortos, porque o caminho de falha era um `return` e o `__main__` chamava
`main()` sem `sys.exit`. **A auditoria por código de saída estava cega exatamente onde mais
precisava enxergar.**

O mesmo levantamento mostrou o defeito espelhado: `sei_refichar` com `rc=124` em 407 de 474
execuções (86%). Ali nada estava quebrado — 124 é o `timeout` do shell, e a ferramenta trabalha
~60 s por documento, então o slot de 600 s sempre a matava no meio. Um passo que termina "em
falha" toda vez é alarme permanente, e alarme permanente é alarme desligado: foi na mesma tabela,
lado a lado, que o aborto crônico da recaptura passou despercebido.

As duas pontas do contrato, portanto:
  · falhar de verdade ⇒ `rc != 0`, para a auditoria ver;
  · parar por orçamento ⇒ `rc == 0`, para a auditoria não gritar à toa.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from tools import sei_refichar, sei_sweep

RAIZ = Path(__file__).resolve().parent.parent


def _linhas_de_codigo(mod) -> list[str]:
    """Só o que EXECUTA — comentário citando o padrão não pode satisfazer a catraca.

    Aconteceu três vezes em 07/08/2026: a catraca de globais do painel acusou um comentário meu
    que citava `onclick="..."`; a de contexto do SEI reprovou por causa da palavra que explicava o
    defeito; e a primeira versão DESTE arquivo passou verde com o `sys.exit(main())` removido do
    código, porque ele continuava escrito no comentário logo acima. Catraca que lê comentário como
    código mede a documentação, não o sistema.
    """
    fora = []
    for ln in inspect.getsource(mod).split("\n"):
        corpo = ln.split("#", 1)[0].rstrip()
        if corpo.strip():
            fora.append(corpo)
    return fora


def test_sweep_sei_propaga_o_codigo_de_saida():
    """`main()` solto descarta o retorno e faz todo passo sair 0."""
    codigo = "\n".join(_linhas_de_codigo(sei_sweep))
    assert "sys.exit(main())" in codigo, (
        "o `__main__` voltou a chamar `main()` sem `sys.exit` — o valor de retorno é descartado e "
        "qualquer falha passa a sair com 0, que foi como 16 abortos de recaptura passaram por "
        "saudáveis na auditoria")


def test_aborto_de_login_da_recaptura_nao_sai_zero():
    """O caminho de aborto tem de levantar, não retornar."""
    fonte = "\n".join(_linhas_de_codigo(sei_sweep))
    trecho = fonte[fonte.index("[recap] ABORTADO"):]
    trecho = trecho[:trecho.index("[recap] login OK")]
    assert "raise FalhaDeclarada" in trecho, (
        "o aborto de login da recaptura voltou a ser um `return` — o slot fica marcado como "
        "sucesso e a fila não anda, exatamente o estado que custou 47 slots")


def test_backstop_devolve_falha_sem_crashar():
    """A regra da casa é que o sweep NUNCA crasha; isso não obriga a mentir no código de saída.

    O tipo da exceção importa e foi corrigido depois que a catraca `test_main_engole_excecao_de_run`
    reprovou: a primeira versão usava `RuntimeError` como sinal de "falha já diagnosticada", e é
    exatamente com um `RuntimeError` que aquele teste simula um crash genérico ("write EPIPE —
    browser morreu no meio"). Misturar os dois faria um crash de verdade sair com a mensagem
    tranquila de falha conhecida, perdendo o aviso que manda alguém olhar.
    """
    fonte = inspect.getsource(sei_sweep)
    assert re.search(r"except FalhaDeclarada as e:.*?return 1", fonte, re.S), (
        "o backstop deixou de distinguir falha já diagnosticada de crash inesperado")
    assert "ABORTADO por erro não previsto" in fonte, "o backstop de crash sumiu"


def test_refichar_para_por_orcamento_em_vez_de_morrer_no_timeout():
    """86% de `rc=124` é alarme permanente — e alarme permanente é alarme desligado."""
    fonte = "\n".join(_linhas_de_codigo(sei_refichar))
    assert "--orcamento-s" in fonte
    assert "parou_por_tempo" in fonte, (
        "a ferramenta voltou a depender do `timeout` do shell para parar, e o log volta a "
        "registrar falha em toda execução")


def test_o_sweep_chama_o_refichar_com_orcamento_folgado():
    """O `timeout` continua como rede de segurança, mas tem de ser MAIOR que o orçamento interno."""
    sh = (RAIZ / "tools" / "sweep_sei.sh").read_text(encoding="utf-8")
    m = re.search(r"timeout (\d+)\s+\$PY -m tools\.sei_refichar[^\n]*--orcamento-s (\d+)", sh)
    assert m, "a chamada do refichar no sweep mudou de forma — reveja o contrato aqui"
    externo, interno = int(m.group(1)), int(m.group(2))
    assert interno < externo, (
        f"orçamento interno ({interno}s) precisa ser MENOR que o timeout do shell ({externo}s), "
        "senão a ferramenta continua morrendo antes de conseguir parar sozinha")
    assert externo - interno >= 60, (
        "a folga entre os dois é pequena demais: uma chamada de LLM lenta no fim do orçamento "
        "ainda derruba a ferramenta no timeout")
