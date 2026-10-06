# -*- coding: utf-8 -*-
"""O caminho PRINCIPAL não pode ser o único invisível.

Ao trocar o sweep para o nous eu abri um buraco de observabilidade sem perceber: o nous é chamado
por HTTP direto e não passa por `best_free_chat`, então sumiu do `data/llm_trace.db` — o trace ficou
**mudo por cinco horas** enquanto o lote rodava normalmente.

O peso disso está medido nesta mesma sessão: foi o trace que revelou a cascata de doze provedores
(437 chamadas, 54 sucessos, 7,5 h de espera) depois de eu ter culpado, e refutado, o tamanho do
prompt, o paralelismo e a construção do cliente. Perder a medição do caminho principal seria trocar
o diagnóstico pela sorte.
"""
from __future__ import annotations

import inspect

import tools.sei_leitura_dupla as M


def test_o_caminho_do_nous_registra_no_trace_da_casa():
    fonte = inspect.getsource(M._gerar_nous)
    assert "_registrar_trace" in fonte, (
        "sem registro, o caminho principal do sweep fica invisível ao diagnóstico")


def test_o_trace_degrada_em_silencio_e_nao_derruba_a_leitura(monkeypatch, capsys):
    """Observabilidade é melhoria, não dependência dura: trace fora do ar não pode parar o sweep."""
    import builtins
    real = builtins.__import__

    def falha(nome, *a, **k):
        if nome == "compliance_agent.llm.free_llm":
            raise ImportError("simulado")
        return real(nome, *a, **k)

    monkeypatch.setattr(builtins, "__import__", falha)
    M._registrar_trace("nous", True, 100)          # não pode levantar
    assert "trace indisponível" in capsys.readouterr().err
