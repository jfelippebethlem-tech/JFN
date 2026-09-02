# -*- coding: utf-8 -*-
"""Declarar captura vazia é honesto — desistir dela não era o combinado.

Medido em 2026-08-04: **120 processos** estavam marcados `n_docs>0` no progresso do sweep e não
tinham UM documento com texto no acervo. O sweep os pulava para sempre (`_pular` decide por
`n_docs>0`), e a ferramenta que os devolveria à fila (`sei_reparar_truncados --sem-texto`) pula
quem já tem `captura_vazia` — de modo que a declaração virou isenção permanente de nova
tentativa. Zona morta: sem teor E marcado como lido.
"""
import json

import pytest

import tools.sei_sweep as S


def _acervo(tmp_path, monkeypatch, docs_txt):
    """Monta data/sei_arquivo/<tag>/ com os textos dados e aponta o REPO do sweep para lá."""
    tag = "030001_083934_2024"
    pasta = tmp_path / "data" / "sei_arquivo" / tag
    (pasta / "texto").mkdir(parents=True)
    man = {"docs": []}
    for i, corpo in enumerate(docs_txt):
        nome = f"{i:03d}_x.txt"
        (pasta / "texto" / nome).write_text(corpo, encoding="utf-8")
        man["docs"].append({"i": i, "titulo": f"Doc {i}", "texto": f"texto/{nome}"})
    (pasta / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    monkeypatch.setattr(S, "REPO", tmp_path)
    return "SEI-030001/083934/2024"


def test_arquivo_so_com_etiqueta_conta_como_SEM_TEOR(tmp_path, monkeypatch):
    proc = _acervo(tmp_path, monkeypatch,
                   ["[Despacho] (fase: tramitacao · tipo: despacho)\n\n"] * 3)
    assert S._arquivo_incompleto(proc) is True


def test_arquivo_com_teor_nao_volta_para_a_fila(tmp_path, monkeypatch):
    proc = _acervo(tmp_path, monkeypatch,
                   ["[Despacho] (tipo: despacho)\n\nTeor real do documento, com folga acima do piso de 40."] * 3)
    assert S._arquivo_incompleto(proc) is False


def test_processo_sem_pasta_nao_e_SEM_TEOR(tmp_path, monkeypatch):
    """Nunca arquivado ≠ arquivado vazio: o primeiro já é tratado pela ausência no progresso, e
    confundir os dois faria o sweep re-enfileirar o acervo inteiro."""
    monkeypatch.setattr(S, "REPO", tmp_path)
    assert S._arquivo_incompleto("SEI-999999/999999/9999") is False


def test_captura_PARCIAL_tambem_volta_para_a_fila(tmp_path, monkeypatch):
    """O critério é o MESMO do `captura_integra` (60%): um processo que o motor recusa avaliar
    por captura insuficiente é, por definição, um processo a recapturar. Réguas diferentes para
    ler e para avaliar deixariam 86 processos parciais presos entre as duas."""
    # 5 documentos, 1 com teor: o mínimo é int(5*0,6)=3, então 1 < 3 → parcial.
    proc = _acervo(tmp_path, monkeypatch, [
        "[A] (tipo: despacho)\n\nTeor real do documento, com folga acima do piso de 40.",
        "[B] (tipo: despacho)\n\n", "[C] (tipo: despacho)\n\n",
        "[D] (tipo: despacho)\n\n", "[E] (tipo: despacho)\n\n",
    ])
    assert S._arquivo_incompleto(proc) is True


def test_captura_INTEGRA_segue_pulada(tmp_path, monkeypatch):
    """1.941 processos íntegros não podem voltar à fila — seria re-ler o acervo inteiro."""
    proc = _acervo(tmp_path, monkeypatch,
                   ["[X] (tipo: despacho)\n\nTeor real do documento, com folga acima do piso."] * 3)
    assert S._arquivo_incompleto(proc) is False
