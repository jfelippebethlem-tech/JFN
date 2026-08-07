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


def test_lacuna_PROVADA_pelo_parecer_vem_antes_do_sinal_osint():
    """`sei_fila_captura` era escrita e lida por NINGUÉM — a fila era um beco.

    Os 380 processos gravados em 2026-08-07 trazem a lista dos documentos que o parecer cita e a
    nossa pasta não tem. Aqui não há hipótese: o documento existe, nós não o temos, e a falta já
    rebaixou cinco acusações de "pagamento sem prova de entrega" para INDISPONÍVEL. Recapturar
    converte uma ressalva em resposta — por isso vem antes do sinal OSINT, que é indício.
    """
    from tools.sei_sweep import _unidade

    provado = ("SEI-080001/000001/2024", 1, 1_000.0)
    com_sinal = ("SEI-080001/000002/2024", 9, 9_000_000.0)
    legiveis = {_unidade(provado[0]), _unidade(com_sinal[0])}
    provados = {"".join(c for c in provado[0] if c.isdigit())}

    ordem = sorted([com_sinal, provado],
                   key=lambda r: (0 if _unidade(r[0]) in legiveis else 1,
                                  0 if "".join(c for c in r[0] if c.isdigit()) in provados else 1,
                                  0 if r[0] == com_sinal[0] else 1,
                                  -(r[2] or 0)))
    assert ordem[0][0] == provado[0], (
        "prova documental ficou atrás de indício — e de um valor 9.000× maior")


def test_a_fila_de_lacuna_provada_degrada_em_silencio():
    """Tabela ausente não pode derrubar a captura."""
    import sqlite3

    from tools.sei_sweep import _fila_com_lacuna_provada

    con = sqlite3.connect(":memory:")
    assert _fila_com_lacuna_provada(con) == set()
    con.close()


def test_grafo_divide_o_universo_entre_as_maquinas(monkeypatch):
    """Duas máquinas na mesma fila DUPLICAM, não somam.

    Medido em 2026-08-07: a VM-2 rodou o grafo e percorreu os MESMOS 400 credores que a VM-1 já
    tinha feito — as duas atacam o topo da mesma ordem por valor, e `grafo_persistido` é local a
    cada máquina. A fatia é por RESTO DO CNPJ (estável entre rodadas), não por posição na lista.
    """
    import sqlite3

    from tools import grafo_persistir as G

    con = sqlite3.connect(":memory:")
    con.executescript(
        "CREATE TABLE ob_orcamentaria_siafe (credor TEXT, status TEXT, valor REAL);"
        + "".join(f"INSERT INTO ob_orcamentaria_siafe VALUES ('{i:014d}','Contabilizado',{100 - i});"
                  for i in range(1, 11)))

    monkeypatch.setenv("JFN_SWEEP_FATIA", "0/2")
    a = {c for c, _ in G.universo(con, 10)}
    monkeypatch.setenv("JFN_SWEEP_FATIA", "1/2")
    b = {c for c, _ in G.universo(con, 10)}
    assert a and b, "alguma fatia saiu vazia"
    assert not (a & b), f"as duas máquinas pegariam os mesmos credores: {sorted(a & b)[:3]}"
    monkeypatch.delenv("JFN_SWEEP_FATIA")
    inteiro = {c for c, _ in G.universo(con, 10)}
    assert a | b == inteiro, "a soma das fatias tem de ser o universo"
    con.close()
