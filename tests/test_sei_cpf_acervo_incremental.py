# -*- coding: utf-8 -*-
"""sei_cpf_sweep --acervo incremental: pasta sem mudança é pulada; pasta varrida SEM CPF fica marcada (medido ≠
nunca lido); pasta que cresce é relida."""
import json
import sqlite3

from tools.sei_cpf_sweep import varrer_acervo

CPF_TXT = "Sócio: JOÃO DA SILVA SAURO, CPF 529.982.247-25, residente nesta cidade"


def _pasta(raiz, nome, textos):
    t = raiz / nome / "texto"
    t.mkdir(parents=True)
    for i, tx in enumerate(textos):
        (t / f"{i:03d}_doc.txt").write_text(tx, encoding="utf-8")
    return t


def test_incremental_pula_sem_mudanca_e_marca_sem_cpf(tmp_path):
    db, acervo, marca = tmp_path / "c.db", tmp_path / "arq", tmp_path / "marca.json"
    _pasta(acervo, "030001_000001_2025", [CPF_TXT])
    _pasta(acervo, "030001_000002_2025", ["despacho sem documento pessoal algum"])

    r1 = varrer_acervo(db_path=db, acervo=acervo, marca=marca)
    assert r1["processos"] == 2 and r1["pulados_sem_mudanca"] == 0
    vistos = json.loads(marca.read_text("utf-8"))
    assert vistos["030001_000002_2025"]["cpfs"] == 0          # varrida e sem CPF: medido, não ausente
    assert vistos["030001_000001_2025"]["cpfs"] == 1

    r2 = varrer_acervo(db_path=db, acervo=acervo, marca=marca)
    assert r2["processos"] == 0 and r2["pulados_sem_mudanca"] == 2

    (acervo / "030001_000002_2025" / "texto" / "001_novo.txt").write_text(CPF_TXT, encoding="utf-8")
    r3 = varrer_acervo(db_path=db, acervo=acervo, marca=marca)
    assert r3["processos"] == 1 and r3["pulados_sem_mudanca"] == 1
    con = sqlite3.connect(db)
    assert {r[0] for r in con.execute("SELECT numero_sei FROM sei_cpf")} == {
        "SEI-030001/000001/2025", "SEI-030001/000002/2025"}


def test_sem_marca_comportamento_antigo(tmp_path):
    db, acervo = tmp_path / "c.db", tmp_path / "arq"
    _pasta(acervo, "030001_000001_2025", [CPF_TXT])
    assert varrer_acervo(db_path=db, acervo=acervo)["processos"] == 1
    assert varrer_acervo(db_path=db, acervo=acervo)["processos"] == 1   # sem marca relê tudo, como antes
