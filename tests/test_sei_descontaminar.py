# -*- coding: utf-8 -*-
"""Descontaminação do acervo já arquivado — e as duas maneiras de piorar o problema.

  1. **Apagar.** A peça alheia é verdadeira; ela só está no lugar errado. Apagá-la perde o
     documento E a informação de a quem devolvê-lo. Aqui ela vai para `_alheios/` com um índice
     que nomeia o processo de origem.
  2. **Inverter a regra do dado ausente.** Documento sem número no `contexto` FICA. Ausência de
     dado não prova que a peça é alheia, e descartá-la trocaria contaminação por perda silenciosa
     — que é pior, porque some sem deixar rastro.

E a junção não é por título: o manifest arquivado normaliza o texto ("programa o de desembolso"),
enquanto a íntegra guarda "Programação de Desembolso". Quem liga com segurança é o prefixo
numérico do arquivo de texto.
"""
from __future__ import annotations

import json

import pytest

from tools import sei_descontaminar as D

PROC = "080001_000744_2024"
ALVO = "SEI-080001/000744/2024"
OUTRO = "Recursos Humanos: Controle de Frequência Nº SEI-030001/006436/2026"


@pytest.fixture()
def acervo(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_CACHE", tmp_path / "cache")
    monkeypatch.setattr(D, "_ARQ", tmp_path / "arquivo")
    (tmp_path / "cache" / f"integra_{PROC}").mkdir(parents=True)
    (tmp_path / "arquivo" / PROC / "texto").mkdir(parents=True)
    return tmp_path


def _monta(base, integra, arquivados):
    (base / "cache" / f"integra_{PROC}" / "manifest.json").write_text(
        json.dumps(integra, ensure_ascii=False), encoding="utf-8")
    (base / "arquivo" / PROC / "manifest.json").write_text(
        json.dumps({"processo": PROC, "docs": arquivados}, ensure_ascii=False), encoding="utf-8")
    for d in arquivados:
        if d.get("texto"):
            (base / "arquivo" / PROC / d["texto"]).write_text("conteúdo", encoding="utf-8")


def _int(i, contexto):
    return {"i": i, "arquivo": f"{i:03d}.pdf", "titulo": f"Doc {i}", "contexto": contexto,
            "ok": True}


def _arq(i, titulo=None):
    return {"i": str(i), "titulo": titulo or f"doc {i}", "texto": f"texto/{i:03d}_doc.txt"}


# ───────────────────────── o que sai e o que fica ─────────────────────────────────────────────

def test_peca_de_outro_processo_sai(acervo):
    _monta(acervo, [_int(0, ALVO), _int(1, OUTRO)], [_arq(0), _arq(1)])
    r = D.aplicar(PROC)
    assert r["aplicado"] and r["movidos"] == 1 and r["ficam"] == 1
    man = json.loads((acervo / "arquivo" / PROC / "manifest.json").read_text())
    assert [d["texto"] for d in man["docs"]] == ["texto/000_doc.txt"]


def test_peca_SEM_numero_no_contexto_FICA(acervo):
    """Ausência de dado não prova que a peça é alheia."""
    _monta(acervo, [_int(0, ALVO), _int(1, "Documento sem número algum")], [_arq(0), _arq(1)])
    r = D.diagnosticar(PROC)
    assert r["a_remover"] == 0 and r["sem_numero_no_contexto"] == 1


def test_nada_e_apagado_a_peca_vai_para_alheios(acervo):
    _monta(acervo, [_int(0, ALVO), _int(1, OUTRO)], [_arq(0), _arq(1)])
    D.aplicar(PROC)
    movida = acervo / "arquivo" / PROC / "_alheios" / "001_doc.txt"
    assert movida.exists() and movida.read_text() == "conteúdo"


def test_o_indice_diz_de_QUAL_processo_a_peca_veio(acervo):
    """Saber que sobrou peça de fora não basta: é preciso saber para onde devolvê-la."""
    _monta(acervo, [_int(0, ALVO), _int(1, OUTRO)], [_arq(0), _arq(1)])
    D.aplicar(PROC)
    idx = json.loads((acervo / "arquivo" / PROC / "_alheios" / "_indice.json").read_text())
    assert idx["itens"][0]["de_processo"] == "030001/006436/2026"


def test_manifest_anterior_fica_guardado(acervo):
    _monta(acervo, [_int(0, ALVO), _int(1, OUTRO)], [_arq(0), _arq(1)])
    D.aplicar(PROC)
    bak = json.loads(
        (acervo / "arquivo" / PROC / "manifest.json.antes-descontaminar").read_text())
    assert len(bak["docs"]) == 2, "o estado anterior tem de ser recuperável"


def test_manifest_declara_o_que_foi_feito_e_como_reverter(acervo):
    _monta(acervo, [_int(0, ALVO), _int(1, OUTRO)], [_arq(0), _arq(1)])
    D.aplicar(PROC)
    man = json.loads((acervo / "arquivo" / PROC / "manifest.json").read_text())
    d = man["descontaminado"]
    assert d["removidos"] == 1 and d["restantes"] == 1
    assert "reversivel" in d and "_alheios" in d["reversivel"]


# ───────────────────────── a junção, e quando não se decide ───────────────────────────────────

def test_junta_pelo_INDICE_do_arquivo_e_nao_pelo_titulo(acervo):
    """O arquivado normaliza o título; casar por texto erraria."""
    _monta(acervo,
           [_int(0, ALVO), _int(1, OUTRO)],
           [_arq(0, "programa o de desembolso"), _arq(1, "despacho educa o")])
    r = D.diagnosticar(PROC)
    assert [i["i"] for i in r["itens"]] == [1]


def test_documento_sem_prefixo_numerico_nao_e_decidido(acervo):
    """Sem a chave de junção não se afirma nada — o documento fica."""
    _monta(acervo, [_int(0, ALVO), _int(1, OUTRO)],
           [_arq(0), {"i": "1", "titulo": "x", "texto": "texto/sem_prefixo.txt"}])
    r = D.diagnosticar(PROC)
    assert r["sem_indice"] == 1 and r["a_remover"] == 0


# ───────────────────────── estados não avaliáveis ─────────────────────────────────────────────

def test_sem_integra_nao_e_limpo_e_sim_nao_avaliavel(acervo):
    (acervo / "arquivo" / PROC / "manifest.json").write_text('{"docs":[]}', encoding="utf-8")
    assert D.diagnosticar(PROC)["estado"] == "sem_integra"


def test_integra_em_formato_antigo_sem_contexto(acervo):
    _monta(acervo, [{"i": 0, "arquivo": "000.pdf", "titulo": "Doc"}], [_arq(0)])
    assert D.diagnosticar(PROC)["estado"] == "sem_contexto"


def test_processo_limpo_nao_e_tocado(acervo):
    _monta(acervo, [_int(0, ALVO), _int(1, ALVO)], [_arq(0), _arq(1)])
    r = D.aplicar(PROC)
    assert r["aplicado"] is False
    assert not (acervo / "arquivo" / PROC / "_alheios").exists()


def test_aplicar_duas_vezes_nao_perde_o_backup_original(acervo):
    """Rodar de novo não pode sobrescrever o backup com o estado já descontaminado."""
    _monta(acervo, [_int(0, ALVO), _int(1, OUTRO)], [_arq(0), _arq(1)])
    D.aplicar(PROC)
    D.aplicar(PROC)
    bak = json.loads(
        (acervo / "arquivo" / PROC / "manifest.json.antes-descontaminar").read_text())
    assert len(bak["docs"]) == 2


def test_listagem_mostra_o_que_AINDA_falta_consertar(acervo):
    """A lista é fila de trabalho, não histórico: pasta já limpa sai dela. É por isso que a
    varredura real voltou `contaminadas: 0` depois de aplicar nas sete."""
    _monta(acervo, [_int(0, ALVO), _int(1, OUTRO)], [_arq(0), _arq(1)])
    assert D.contaminadas() == [PROC]
    D.aplicar(PROC)
    assert D.contaminadas() == []
