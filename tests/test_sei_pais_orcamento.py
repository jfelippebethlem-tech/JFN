# -*- coding: utf-8 -*-
"""O slot de processos-pai morria de SIGKILL em TODAS as execuções — e culpava o WAF por isso.

Medido em 2026-08-06: `sei_pais rc=137` nas dez últimas rodadas do `sweep_sei.sh`, desde 05/08 pelo
menos, e NENHUMA linha `[pais] FIM` no log. O `timeout -k 120 --foreground 900` manda SIGTERM aos
900 s, mas o laço só consulta `_PARAR` ENTRE processos — e uma leitura de pai tem mediana de 121 s,
p90 de 137 s e máximo MEDIDO de 502 s (1.222 leituras). O SIGKILL sempre vencia.

A consequência não ficava no slot: o browser nunca fechava, a sessão itkava ficava pendurada, e os
DOIS slots seguintes falhavam no login — com a mensagem "não venceu o WAF", que é exatamente a
explicação que esta casa proíbe (o acesso é liberado; culpar acesso/WAF já mascarou defeito antes).

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_sei_pais_orcamento.py -q
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def test_run_pais_tem_orcamento_e_para_sozinho():
    from tools.sei_sweep import run_pais

    sig = inspect.signature(run_pais)
    assert "orcamento_s" in sig.parameters, "o laço voltou a depender de ser MORTO para parar"
    orc = sig.parameters["orcamento_s"].default
    assert isinstance(orc, int) and 0 < orc, "orçamento tem de ser um prazo real"

    fonte = inspect.getsource(run_pais)
    assert "orcamento_s and gasto > orcamento_s" in fonte, (
        "o orçamento existe mas não é consultado no laço")


def test_orcamento_cabe_dentro_do_timeout_do_sweep_com_margem_de_uma_leitura():
    """700 s de orçamento dentro de 900 s de timeout deixam 200 s — mais que o p90 de 137 s.

    Se alguém subir o orçamento até encostar no timeout, o SIGKILL volta e com ele a sessão
    pendurada. Este teste lê os DOIS números das suas fontes reais e compara.
    """
    from tools.sei_sweep import run_pais

    orc = inspect.signature(run_pais).parameters["orcamento_s"].default
    sh = (RAIZ / "tools" / "sweep_sei.sh").read_text(encoding="utf-8")
    m = re.search(r"timeout -k \d+ --foreground (\d+) \$PY -m tools\.sei_sweep --seguir-pais", sh)
    assert m, "a linha do slot de pais mudou de forma — reveja este teste junto"
    limite = int(m.group(1))
    assert orc + 137 <= limite, (
        f"orçamento {orc}s + p90 de uma leitura (137s) passa do timeout {limite}s do slot: "
        "o SIGKILL volta a matar o browser com a sessão aberta")


def test_aborto_de_login_nao_culpa_waf_nem_acesso():
    """Regra da casa, e não é estilo: culpar acesso/WAF já mascarou defeito nosso mais de uma vez.

    Aqui a mensagem apontava para a fonte enquanto a causa real era o slot anterior morto a
    SIGKILL deixando a sessão aberta.
    """
    fonte = (RAIZ / "tools" / "sei_sweep.py").read_text(encoding="utf-8")
    for trecho in re.findall(r"_log\((?:f?\"[^\"]*\"\s*)+\)", fonte):
        if "ABORTADO" in trecho and "login" in trecho:
            assert "venceu o WAF" not in trecho, (
                f"mensagem de aborto voltou a atribuir a falha ao WAF: {trecho[:120]}")
            assert "NÃO se atribui" in trecho, (
                f"mensagem de aborto sem a ressalva de causa: {trecho[:120]}")
