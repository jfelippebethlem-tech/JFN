# -*- coding: utf-8 -*-
"""Testes do sono REM do Hermes (metacognição + memória blindada + RAG incremental)."""
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools import hermes_metacognicao as mc  # noqa: E402
from tools.hermes_rag import corpus_hash  # noqa: E402


def test_corpus_hash_deterministico():
    h1, h2 = corpus_hash(), corpus_hash()
    assert h1 == h2
    assert len(h1) == 64 and all(c in "0123456789abcdef" for c in h1)


def test_backup_memoria_exporta_e_roda_rotacao(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "BACKUP_DIR", tmp_path)
    out = mc.backup_memoria()
    assert out["memoria"] > 0, "memória de aprendizado real deve ter itens"
    assert out["pericias"] > 0, "núcleo pericial real deve ter itens"
    arqs = list(tmp_path.glob("*.jsonl"))
    assert len(arqs) == 2
    # cada linha é JSON válido com os campos da tabela
    linha = json.loads(next(open(arqs[0], encoding="utf-8")))
    assert isinstance(linha, dict) and linha


def test_restore_e_aditivo_e_idempotente(tmp_path, monkeypatch):
    # DB isolado com o schema mínimo da memoria_aprendizado
    db = tmp_path / "compliance.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE memoria_aprendizado (id INTEGER PRIMARY KEY, categoria TEXT, "
        "chave TEXT, valor TEXT, confianca REAL, n_observacoes INTEGER, fonte TEXT, "
        "primeira_vez TEXT, ultima_vez TEXT)")
    con.execute("INSERT INTO memoria_aprendizado (categoria, chave, valor) "
                "VALUES ('metodo','ja-existe','regra antiga')")
    con.commit(); con.close()

    jsonl = tmp_path / "export.jsonl"
    jsonl.write_text(
        json.dumps({"categoria": "metodo", "chave": "ja-existe", "valor": "NOVA (não deve sobrescrever)"}) + "\n"
        + json.dumps({"categoria": "licao", "chave": "nova-licao", "valor": "só a OB é pagamento"}) + "\n")

    monkeypatch.setattr(mc, "REPO", tmp_path.parent)
    # REPO/data/compliance.db → monta a estrutura esperada
    (tmp_path.parent / "data").mkdir(exist_ok=True)
    import shutil
    shutil.move(str(db), str(tmp_path.parent / "data/compliance.db"))

    n = mc.restore_memoria(str(jsonl))
    assert n == 1, "só o item novo entra; o existente é preservado (aditivo)"
    n2 = mc.restore_memoria(str(jsonl))
    assert n2 == 0, "segunda passada não duplica (idempotente)"

    con = sqlite3.connect(tmp_path.parent / "data/compliance.db")
    valor = con.execute("SELECT valor FROM memoria_aprendizado WHERE chave='ja-existe'").fetchone()[0]
    assert valor == "regra antiga", "restore NUNCA sobrescreve o que já foi aprendido"
    con.close()


def test_resumo_do_dia_nao_explode_sem_dados():
    # deve devolver string (possivelmente vazia) sem levantar exceção
    assert isinstance(mc._resumo_do_dia(), str)
