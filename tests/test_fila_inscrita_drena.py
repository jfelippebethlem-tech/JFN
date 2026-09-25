# -*- coding: utf-8 -*-
"""`sei_fila_captura` acumulou 3.632 processos que nenhum job buscava.

Medido em 2026-08-09: a tabela tinha um único leitor, o relatório de requisição. O drenador
(`sei_integra_fila --geral`) montava sua fila varrendo o cache CDP — ou seja, só o que o sweep JÁ
havia capturado. Processo inscrito e sem cache não era buscado por ninguém, e inscrever nele era
registrar intenção, não agendar trabalho. É a família de [[construido-testado-nunca-rodado]]: a
tabela existia, os escritores existiam, e faltava o consumidor.

Estes testes travam as três propriedades do conserto: os inscritos ENTRAM, entram ANTES da
varredura (foram escolhidos a dedo), e quem já está arquivado não volta à fila.
"""
from __future__ import annotations

import sqlite3

import pytest

import tools.sei_integra_fila as F


@pytest.fixture()
def ambiente(tmp_path, monkeypatch):
    db = tmp_path / "compliance.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sei_fila_captura (numero_sei TEXT, sei_norm TEXT, motivo TEXT,"
                " total_pago REAL, n_docs INT, visto_em TEXT)")
    for num, valor in (("SEI-030001/075841/2024", 88_025_677.50),
                       ("SEI-030001/008372/2024", 60_800_962.20),
                       ("SEI-030001/004250/2024", 10_916_064.00),
                       ("SEI-999999/000001/2024", 0.0)):
        con.execute("INSERT INTO sei_fila_captura VALUES (?,?,?,?,0,'2026-08-09')",
                    (num, num, "alvo de investigação", valor))
    con.commit()
    con.close()
    arquivo = tmp_path / "sei_arquivo"
    arquivo.mkdir()
    monkeypatch.setattr(F, "DB", db)
    monkeypatch.setattr(F, "ARQUIVO", arquivo)
    return arquivo


def test_inscritos_entram_na_fila(ambiente):
    assert F._fila_inscrita() == ["SEI-030001/075841/2024", "SEI-030001/008372/2024",
                                  "SEI-030001/004250/2024", "SEI-999999/000001/2024"]


def test_ordem_e_por_valor_pago(ambiente):
    """O de R$ 88 mi vem antes do de R$ 10,9 mi — exposição decide, como no resto da casa."""
    fila = F._fila_inscrita()
    assert fila.index("SEI-030001/075841/2024") < fila.index("SEI-030001/004250/2024")


def test_ja_arquivado_nao_volta(ambiente, monkeypatch):
    monkeypatch.setattr(F, "_arquivado_ok",
                        lambda d: d.name == "030001_075841_2024")
    assert "SEI-030001/075841/2024" not in F._fila_inscrita()
    assert "SEI-030001/008372/2024" in F._fila_inscrita()


def test_limite_respeitado(ambiente):
    assert len(F._fila_inscrita(limite=2)) == 2


def test_sem_a_tabela_devolve_vazio(tmp_path, monkeypatch):
    db = tmp_path / "vazia.db"
    sqlite3.connect(db).close()
    monkeypatch.setattr(F, "DB", db)
    monkeypatch.setattr(F, "ARQUIVO", tmp_path / "arq")
    assert F._fila_inscrita() == []


def test_sem_banco_devolve_vazio(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "DB", tmp_path / "nao_existe.db")
    assert F._fila_inscrita() == []


def test_chars_textual_nao_derruba_a_fila(tmp_path, monkeypatch):
    """`sei_reparar_vazios` gravava `str(len(texto))` e contaminou 1.972 manifests.

    A comparação crua estourava `TypeError: '>=' not supported between str and int` e derrubava o
    drenador `--geral` INTEIRO — seis rodadas mortas entre 24/07 e 09/08, caladas no log do cron.
    Um manifesto com `chars` textual tem de ser lido como ARQUIVADO, não crashar.
    """
    import json
    d = tmp_path / "030001_008372_2024"
    (d / "texto").mkdir(parents=True)
    (d / "texto" / "001.txt").write_text("teor real do documento", encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps(
        {"docs": [{"i": 1, "chars": "2364", "ocr": "True"}]}), encoding="utf-8")
    assert F._chars({"chars": "2364"}) == 2364
    assert F._chars({"chars": None}) == 0 and F._chars({"chars": "abc"}) == 0
    assert F._arquivado_ok(d) is True, "manifesto com teor textual deve contar como arquivado"


def test_produtor_do_reparo_grava_numero():
    """O leitor coage o passado, mas o produtor não pode reincidir."""
    import inspect
    import tools.sei_reparar_vazios as R
    fonte = inspect.getsource(R)
    assert 'd["chars"] = str(len(texto))' not in fonte, (
        "voltou a gravar chars como texto — foi isso que matou o drenador por 16 dias")


def test_recusa_por_carga_e_ADIADO_nao_erro(monkeypatch):
    """O preflight de carga saía com código 0 sem capturar; o `sei_arquivar` seguinte falhava por
    falta de material e a fila registrava **"erro"** — o mesmo rótulo de uma captura quebrada.
    Quem lesse o log diagnosticava problema no processo quando o que houve foi a VM ocupada
    (visto em 2026-08-09: `030001/008372/2024: erro`, e o motivo real era `load1=2.50 > 1.7`).
    """
    import subprocess
    chamadas = []

    class _R:
        def __init__(self, rc): self.returncode = rc

    def _fake(cmd, **kw):
        chamadas.append(cmd)
        return _R(75)                      # EX_TEMPFAIL: preflight recusou por carga

    monkeypatch.setattr(subprocess, "run", _fake)
    assert F._baixar_e_arquivar("030001/008372/2024", {}) == "adiado"
    assert len(chamadas) == 1, "recusado por carga não deve nem tentar arquivar"


def test_tres_adiamentos_seguidos_encerram_a_rodada(monkeypatch):
    """Com a VM ocupada o preflight recusa TODOS — desfilar a fila inteira gasta a janela sem
    baixar nada. A fila fica intacta e a próxima passada retoma do mesmo lugar."""
    monkeypatch.setattr(F, "_baixar_e_arquivar", lambda p, e: "adiado")
    monkeypatch.setattr(F.time, "sleep", lambda *_: None)
    vistos = []
    n = F._rodar_fila(["a", "b", "c", "d", "e"], {}, None, lambda m: vistos.append(m))
    assert n == 3, f"devia parar no terceiro adiamento, tentou {n}"
    assert any("três adiamentos" in v for v in vistos), "o encerramento tem de sair declarado"
