# -*- coding: utf-8 -*-
"""O aviso de "valor é piso" tem de se manter sozinho — e SUMIR quando deixar de ser verdade.

Em 2026-08-09, ao descobrir que a coleta do SIAFE tinha pares (UG, ano) parados em contagem
redonda, 12 notas de caso do vault ganharam um aviso dizendo que seus valores eram PISO e quais
unidades/anos faltavam drenar. O aviso resolve um problema real — a PHOTONLUX saiu de R$ 4,3 mi
para R$ 385,8 mi ao recoletar UM ano — mas cria outro se ficar parado: a drenagem roda a cada 2 h,
e um alerta que lista pendência já resolvida é ruído. Ruído ensina o leitor a pular o bloco de
alerta, que é o pior resultado possível.

Por isso o aviso é reescrito a cada passada e **retirado** quando nenhuma UG citada na nota tem
mais ano travado. E ele só cita unidade que a nota REALMENTE menciona: marcar nota alheia seria
alarme genérico.
"""
from __future__ import annotations

import sqlite3

import pytest

import tools.vault_aviso_piso_siafe as V


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    casos = tmp_path / "casos"
    casos.mkdir()
    monkeypatch.setattr(V, "CASOS", casos)
    return casos


def _nota(casos, nome, corpo):
    p = casos / nome
    p.write_text(f"---\ntipo: caso\n---\n\n# {nome}\n\n{corpo}\n", encoding="utf-8")
    return p


def _db(tmp_path, pares):
    """pares = [(ug, ano, n_linhas)] — n redondo simula coleta parada no teto."""
    p = tmp_path / "c.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, exercicio INT)")
    for ug, ano, n in pares:
        con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?)",
                        [(f"{ano}OB{i:06d}", ug, ano) for i in range(n)])
    con.commit()
    con.close()
    return str(p)


def test_poe_o_aviso_so_na_nota_que_cita_a_ug(vault, tmp_path):
    db = _db(tmp_path, [("294200", 2022, 1000), ("036100", 2023, 37)])
    _nota(vault, "fserj.md", "Pagamentos da UG 294200 somam R$ 10.000,00.")
    _nota(vault, "outro.md", "Nada a ver com aquela unidade, mas cita R$ 5,00.")
    r = V.aplicar(escrever=True, db=db)
    assert r["postos_ou_atualizados"] == 1
    assert V.MARCA in (vault / "fserj.md").read_text()
    assert V.MARCA not in (vault / "outro.md").read_text(), "alarme genérico em nota alheia"


def test_aviso_lista_os_anos_que_faltam(vault, tmp_path):
    db = _db(tmp_path, [("294200", 2021, 1000), ("294200", 2022, 2000), ("294200", 2023, 55)])
    _nota(vault, "fserj.md", "UG 294200 — R$ 1,00")
    V.aplicar(escrever=True, db=db)
    txt = (vault / "fserj.md").read_text()
    assert "2021, 2022" in txt and "2023" not in txt.split("piso-siafe")[1].split("\n\n")[0]


def test_aviso_SOME_quando_a_pendencia_acaba(vault, tmp_path):
    db1 = _db(tmp_path, [("294200", 2022, 1000)])
    _nota(vault, "fserj.md", "UG 294200 — R$ 1,00")
    V.aplicar(escrever=True, db=db1)
    assert V.MARCA in (vault / "fserj.md").read_text()

    db2 = _db(tmp_path / "depois", [("294200", 2022, 4827)]) if (tmp_path / "depois").mkdir() is None else None
    r = V.aplicar(escrever=True, db=db2)
    texto = (vault / "fserj.md").read_text()
    assert V.MARCA not in texto, "o aviso ficou depois de a pendência acabar — vira ruído"
    assert r["retirados"] == 1
    assert "# fserj.md" in texto, "a retirada comeu o conteúdo da nota"


def test_nota_sem_valor_nao_e_tocada(vault, tmp_path):
    db = _db(tmp_path, [("294200", 2022, 1000)])
    p = _nota(vault, "so_texto.md", "Menciona a UG 294200 mas não cita cifra nenhuma.")
    antes = p.read_text()
    V.aplicar(escrever=True, db=db)
    assert p.read_text() == antes


def test_relatorio_nao_escreve(vault, tmp_path):
    db = _db(tmp_path, [("294200", 2022, 1000)])
    p = _nota(vault, "fserj.md", "UG 294200 — R$ 1,00")
    antes = p.read_text()
    V.aplicar(escrever=False, db=db)
    assert p.read_text() == antes
