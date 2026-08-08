# -*- coding: utf-8 -*-
"""Todo caminho que loga no SEI monta o navegador do MESMO jeito.

O DEFEITO, medido em 2026-08-07. `tools/sei_sweep.py` tem três caminhos que fazem login no SEI:
o sweep principal, a leitura dos processos-pai e a RECAPTURA. Os dois primeiros montavam o contexto
do Playwright com `user_agent` de desktop; o terceiro, nascido em 03/08/2026, não — ia com o padrão
do headless, que se apresenta como `HeadlessChrome`.

Efeito no log das duas máquinas: **47 slots de recaptura, 47 abortos, ZERO documento recuperado**,
sempre com a mesma mensagem — "login itkava não completou em 20 tentativas". A mensagem levantava
a hipótese de sessão anterior deixada aberta; ninguém a conferiu, e a diferença real estava a duas
linhas de distância, no arquivo ao lado do chamador que funcionava.

POR QUE ISTO É PIOR QUE UM PASSO QUE NÃO EXISTE. A recaptura RODAVA: entrava no cron, escrevia no
log, marcava o slot e devolvia "+0 documentos com texto nesta sessão". Tinha toda a aparência de
funcionamento — e por isso ninguém foi olhar durante quatro dias, enquanto a fila de recaptura
crescia para 3.617 processos e a casa acreditava estar drenando-a.

A GUARDA. Três cópias de uma configuração é convite para a quarta divergir. A montagem passou a
ser uma só (`_contexto_sei`), e este teste exige que continue sendo: nenhum `new_context` solto no
arquivo, e o UA de desktop declarado num lugar só.
"""
from __future__ import annotations

import inspect
import re

from tools import sei_sweep


def _fonte() -> str:
    return inspect.getsource(sei_sweep)


def test_nenhum_new_context_solto_no_sweep():
    """`new_context` fora do helper volta a permitir que um caminho divirja dos outros."""
    fonte = _fonte()
    soltos = [ln.strip() for ln in fonte.split("\n")
              if "new_context(" in ln and "async def _contexto_sei" not in ln]
    # a única ocorrência legítima é a de dentro do helper
    fora_do_helper = [ln for ln in soltos if "ignore_https_errors=True" in ln
                      and "locale=" in ln and "user_agent=" not in ln]
    assert not fora_do_helper, (
        "contexto montado à mão sem User-Agent — foi exatamente assim que a recaptura passou "
        "quatro dias abortando o login em silêncio:\n  " + "\n  ".join(fora_do_helper))


def test_todos_os_logins_usam_o_contexto_compartilhado():
    """Cada `login(pg, ...)` precisa ter vindo de uma página do contexto único."""
    fonte = _fonte()
    n_login = len(re.findall(r"await login\(pg", fonte))
    n_ctx = len(re.findall(r"ctx = await _contexto_sei\(b\)", fonte))
    assert n_login >= 3, "os caminhos de login sumiram — reveja este teste antes de relaxá-lo"
    assert n_ctx >= n_login, (
        f"{n_login} caminhos fazem login e só {n_ctx} usam `_contexto_sei` — algum voltou a montar "
        "o navegador por conta própria")


def test_user_agent_de_desktop_existe_e_e_unico():
    """O UA mora num lugar só: quem precisar mudá-lo muda para os três caminhos de uma vez."""
    fonte = _fonte()
    assert "_UA_DESKTOP" in fonte
    assert fonte.count('"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "') == 1, (
        "o User-Agent voltou a ser copiado — duas cópias é o começo de duas verdades")
    # NÃO procurar a palavra "HeadlessChrome": ela aparece no COMENTÁRIO que explica o defeito, e
    # uma catraca que lê comentário como código acusa quem a documentou. Já aconteceu hoje, com a
    # catraca de globais do painel. O que interessa é o USO: nenhum `user_agent=` fora do único.
    usos = re.findall(r"user_agent\s*=\s*([A-Za-z_][\w.]*)", fonte)
    assert set(usos) <= {"_UA_DESKTOP"}, (
        f"contexto passando outro User-Agent: {sorted(set(usos) - {'_UA_DESKTOP'})}")


def test_o_helper_declara_o_user_agent():
    """Prova direta: o contexto compartilhado não pode sair sem UA."""
    fonte = inspect.getsource(sei_sweep._contexto_sei)
    assert "user_agent=_UA_DESKTOP" in fonte
    assert "locale=" in fonte and "ignore_https_errors=True" in fonte
