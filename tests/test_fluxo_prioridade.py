# -*- coding: utf-8 -*-
"""Prioridade única (O2.1, §3.7 + §16.3): a ordem da fila SEI de tools/sei_sweep._fila portada para uma função pura —
cada degrau, a equivalência com a chave original sobre amostra aleatória, o inteiro de `fluxo.jobs.prioridade`, a
faixa 0 do dono e a reserva Couto."""
import dataclasses
import random

import pytest

from compliance_agent.fluxo import prioridade as PR
from compliance_agent.fluxo.prioridade import Sinais

M = 1_000_000.00


def _ordem(*itens):
    return [nome for nome, _ in sorted(itens, key=lambda x: PR.chave(x[1]))]


@pytest.mark.parametrize("antes,depois", [
    (Sinais(urgente_dono=True), Sinais(manual=True, legivel=True, ob_paga=9e9)),         # faixa 0 fura a fila
    (Sinais(legivel=True), Sinais(lacuna_provada=True, osint=True, ob_paga=9e9)),       # legível antes de tudo o resto
    (Sinais(manual=True), Sinais(legivel=True, contratacao_direta=True, ob_paga=5 * M)),  # manual > direta grande
    (Sinais(contratacao_direta=True, ob_paga=M), Sinais(legivel=True, lacuna_provada=True)),  # direta ≥ piso sobe
    (Sinais(legivel=True, lacuna_provada=True), Sinais(legivel=True, osint=True, ob_paga=9e9)),  # lacuna > OSINT
    (Sinais(legivel=True, osint=True), Sinais(legivel=True, ob_paga=9e9)),               # OSINT > valor
    (Sinais(legivel=True, ob_paga=10.0), Sinais(legivel=True, folha=True, ob_paga=9e9)),  # folha por último no estrato
    (Sinais(legivel=True, ob_paga=2 * M), Sinais(legivel=True, ob_paga=M)),              # maior valor antes
    (Sinais(ob_paga=M, risco=0.9), Sinais(ob_paga=M, risco=0.1)),                        # desempate: risco
    (Sinais(ob_paga=M, idade_dias=30), Sinais(ob_paga=M, idade_dias=1)),                 # desempate: mais antigo
])
def test_cada_degrau(antes, depois):
    assert _ordem(("depois", depois), ("antes", antes)) == ["antes", "depois"]


def test_direta_abaixo_do_piso_nao_sobe():
    abaixo = Sinais(contratacao_direta=True, ob_paga=M - 0.01)
    assert not PR.direta_grande(abaixo) and PR.direta_grande(Sinais(contratacao_direta=True, ob_paga=M))
    assert _ordem(("abaixo", abaixo), ("legivel", Sinais(legivel=True))) == ["legivel", "abaixo"]


def _chave_sei_sweep(r, legiveis, dirigidos, diretas_grandes, provados, sinal, credores, folha):
    """CÓPIA LITERAL da lambda de tools/sei_sweep._fila (`rows.sort(key=...)`), com os conjuntos por parâmetro."""
    return (0 if (r[3] in legiveis or r[0] in dirigidos or r[0] in diretas_grandes) else 1,
            0 if r[0] in dirigidos else 1,
            0 if r[0] in diretas_grandes else 1,
            0 if r[0] in provados else 1,
            0 if (credores.get(r[0]) or set()) & sinal else 1,
            1 if r[0] in folha else 0,
            -(r[2] or 0))


def test_equivale_a_ordem_do_sei_sweep_em_amostra_aleatoria():
    rnd = random.Random(20261124)
    for _ in range(30):
        rows, sinais = [], {}
        legiveis, dirigidos, diretas_g, provados, folha, credores = set(), set(), set(), set(), set(), {}
        sinal = {"c-osint"}
        for i in range(60):
            p, unidade, valor = f"P{i}", f"U{rnd.randint(0, 5)}", round(rnd.choice([0, 1, 10]) * rnd.random() * 2 * M, 2)
            rows.append((p, 1, valor, unidade))
            if rnd.random() < .4:
                legiveis.add(unidade)
            man = rnd.random() < .08
            direta = rnd.random() < .2
            lac, osi, fol = rnd.random() < .2, rnd.random() < .15, rnd.random() < .2
            if man:
                dirigidos.add(p)
            if direta and valor >= PR.PISO_DIRETA:
                diretas_g.add(p)
            if lac:
                provados.add(p)
            if osi:
                credores[p] = {"c-osint"}
            if fol:
                folha.add(p)
            sinais[p] = Sinais(legivel=unidade in legiveis, manual=man, contratacao_direta=direta, ob_paga=valor,
                               lacuna_provada=lac, osint=osi, folha=fol)
        # `legivel` depende do conjunto final de unidades legíveis
        sinais = {r[0]: dataclasses.replace(sinais[r[0]], legivel=r[3] in legiveis) for r in rows}
        esperado = [r[0] for r in sorted(rows, key=lambda r: _chave_sei_sweep(
            r, legiveis, dirigidos, diretas_g, provados, sinal, credores, folha))]
        obtido = [r[0] for r in sorted(rows, key=lambda r: PR.chave(sinais[r[0]]))]
        assert obtido == esperado


def test_inteiro_preserva_a_ordem_dos_degraus():
    rnd = random.Random(7)
    amostra = [Sinais(urgente_dono=rnd.random() < .05, legivel=rnd.random() < .5, manual=rnd.random() < .1,
                      contratacao_direta=rnd.random() < .3, ob_paga=rnd.choice([0.0, 5e3, 2e5, 1.5e6, 3e8, 1e11]),
                      lacuna_provada=rnd.random() < .2, osint=rnd.random() < .2, folha=rnd.random() < .2)
              for _ in range(400)]
    for a in amostra:
        for b in amostra[:60]:
            if PR.chave(a)[:8] < PR.chave(b)[:8]:
                assert PR.inteiro(a) <= PR.inteiro(b), (a, b)
    assert max(PR.inteiro(s) for s in amostra) < 2 ** 31                  # cabe no integer do PG
    assert PR.inteiro(Sinais(urgente_dono=True)) < 100_000 * 64 <= PR.inteiro(Sinais())


def test_valor_maior_menor_inteiro_e_sem_valor_vai_ao_fim():
    assert PR.inteiro(Sinais(ob_paga=1e9)) < PR.inteiro(Sinais(ob_paga=1e6)) < PR.inteiro(Sinais(ob_paga=0))


def test_explicar_grava_os_componentes():
    e = PR.explicar(Sinais(contratacao_direta=True, ob_paga=2 * M, couto=True, lente="bombeiros"))
    assert e["direta_grande"] is True and e["sinais"]["lente"] == "bombeiros" and e["inteiro"] == PR.inteiro(
        Sinais(contratacao_direta=True, ob_paga=2 * M, couto=True, lente="bombeiros"))


def test_ordenar_reserva_metade_para_couto_e_urgente_fora_da_cota():
    itens = ([("u", Sinais(urgente_dono=True, couto=False))]
             + [(f"r{i}", Sinais(ob_paga=1e9 - i)) for i in range(6)]
             + [(f"c{i}", Sinais(ob_paga=10.0 - i, couto=True)) for i in range(6)])
    lote = [n for n, _ in PR.ordenar(itens, lambda x: x[1], fracao_couto=0.5)]
    assert lote[0] == "u"
    resto = lote[1:]
    for k in range(1, len(resto) + 1):                                   # ⌈k/2⌉ do período em todo prefixo
        assert sum(n.startswith("c") for n in resto[:k]) >= -(-k // 2)
    assert [n for n in resto if n.startswith("r")] == [f"r{i}" for i in range(6)]   # ordem dentro do grupo intacta


def test_ordenar_sem_cota_e_a_chave_pura():
    itens = [("b", Sinais(ob_paga=1.0, couto=True)), ("a", Sinais(ob_paga=2.0))]
    assert [n for n, _ in PR.ordenar(itens, lambda x: x[1], fracao_couto=0)] == ["a", "b"]
