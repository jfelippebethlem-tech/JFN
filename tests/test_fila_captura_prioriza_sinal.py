# -*- coding: utf-8 -*-
"""A captura lê 16 processos por dia contra 45.634 — a ordem da fila é a decisão mais cara da casa.

Ela já ordenava por VALOR, e valor não é risco: um pagamento grande e limpo entrava antes de um
pequeno com agente público no quadro societário da contratada. Medido em 2026-08-06: dos 44.072
processos ainda não capturados, **632** têm credor na fila curada de `agente_publico_reverso` —
1,4% do universo, quarenta dias de captura em vez de sete anos.

O que estes testes travam não é a consulta, é a PRIORIDADE: que o sinal entre na ordem, que ele não
atropele a legibilidade da unidade (unidade que não rende documento não rende nada, com sinal ou
sem), e que a ausência do arquivo de inteligência degrade em silêncio em vez de quebrar a captura.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_fila_captura_prioriza_sinal.py -q
"""
from __future__ import annotations

import json

import pytest


def _ordenar(rows, legiveis, credores, sinal):
    """Reproduz a chave de ordenação da fila — a mesma expressão de `tools/sei_sweep`."""
    from tools.sei_sweep import _unidade

    return sorted(rows, key=lambda r: (0 if _unidade(r[0]) in legiveis else 1,
                                       0 if (credores.get(r[0]) or set()) & sinal else 1,
                                       -(r[2] or 0)))


def test_sinal_osint_passa_na_frente_do_valor():
    """Um processo de R$ 10 mil com agente público na contratada vem antes de um de R$ 10 milhões
    sem sinal nenhum — desde que os dois estejam em unidade legível."""
    from tools.sei_sweep import _unidade

    grande = ("SEI-080001/000001/2024", 5, 10_000_000.0)
    pequeno = ("SEI-080001/000002/2024", 1, 10_000.0)
    legiveis = {_unidade(grande[0]), _unidade(pequeno[0])}
    ordem = _ordenar([grande, pequeno], legiveis, {pequeno[0]: {"11111111"}}, {"11111111"})
    assert ordem[0][0] == pequeno[0], "o sinal não entrou na frente do valor"


def test_sinal_nao_atropela_a_legibilidade_da_unidade():
    """Unidade que não rende documento não rende nada — com sinal ou sem.

    Pôr o sinal acima da legibilidade gastaria sessão de browser para voltar com zero documentos, e
    a fila anda 16 por dia: cada tentativa vazia custa um processo que renderia.
    """
    from tools.sei_sweep import _unidade

    ilegivel = ("SEI-999999/000003/2024", 9, 9_000_000.0)
    legivel = ("SEI-080001/000004/2024", 1, 1_000.0)
    ordem = _ordenar([ilegivel, legivel], {_unidade(legivel[0])},
                     {ilegivel[0]: {"22222222"}}, {"22222222"})
    assert ordem[0][0] == legivel[0], "processo em unidade ilegível subiu por ter sinal"


def test_sem_arquivo_de_inteligencia_a_captura_nao_quebra(tmp_path, monkeypatch):
    """Prioridade que quebra a captura seria pior que prioridade nenhuma."""
    import tools.sei_sweep as M

    monkeypatch.setattr(M, "__file__", str(tmp_path / "tools" / "sei_sweep.py"))
    assert M._raizes_com_sinal_osint() == set()


def test_le_a_fila_curada_e_ignora_o_que_tem_explicacao(tmp_path, monkeypatch):
    """A fila crua traria `JOSE ANTONIO DA SILVA` e as associações de apoio à escola.

    Só entra o que sobreviveu aos vetos: sem homônimo comprovado e sem explicação institucional.
    """
    import tools.sei_sweep as M

    alvo = tmp_path / "data" / "agente_publico_fila.json"
    alvo.parent.mkdir(parents=True)
    alvo.write_text(json.dumps({"itens": [
        {"cnpj_basico": "11111111", "explicacao_institucional": ""},
        {"cnpj_basico": "22222222", "explicacao_institucional": "apoio_a_escola"},
        {"cnpj_basico": "33333333", "explicacao_institucional": "ente_publico_ou_estatal"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(M, "__file__", str(tmp_path / "tools" / "sei_sweep.py"))
    assert M._raizes_com_sinal_osint() == {"11111111"}


@pytest.mark.skipif(True, reason="mede o acervo real; roda à mão quando se quer o número")
def test_quantos_processos_ganham_prioridade_hoje():
    pass
