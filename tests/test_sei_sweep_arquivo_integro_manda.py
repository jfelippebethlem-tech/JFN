# -*- coding: utf-8 -*-
"""Acervo ÍNTEGRO manda mais que progresso zerado — o sweep relia o que já estava em casa.

O progresso do sweep e o acervo (`data/sei_arquivo/`) são preenchidos por caminhos diferentes: o
sweep grava o primeiro; a colheita da VM-2, a recaptura integral e o `sei_arquivar` gravam o
segundo. Medido em 2026-08-11:

    2.315 pastas no acervo
      321 têm entrada no progresso dizendo ZERO documento
      118 dessas são ÍNTEGRAS pela régua canônica (`manifesto_norm.captura_integra`)

Ou seja: 118 processos capturados e completos continuavam elegíveis para releitura — alguns já com
3 a 5 tentativas gastas. Browser é o recurso mais escasso da casa, e estava sendo gasto no que ela
já tem. Foi assim que o processo de R$ 88,0 mi do caso AGILE/SEEDUC ficou dado como "nunca lido"
enquanto 407 documentos dele estavam no disco desde 09/08.

A regra já existia, e no mesmo arquivo: *"ARQUIVO SEM TEOR MANDA MAIS QUE O PROGRESSO"* devolve à
fila quem tem captura incompleta. Faltava a metade simétrica — captura COMPLETA tira da fila.
O disco decide nos dois sentidos.

**A exceção que fica de pé:** processo que ANDOU (OB mais nova que a captura) volta a ser lido.
Perícia completa precisa do que entrou depois; e sem isso o conserto trocaria releitura inútil por
cegueira a fato novo.
"""
from __future__ import annotations

import json

import tools.sei_sweep as S


def _arquivar(tmp_path, proc: str, docs: int, gerado_em: str, com_texto: int | None = None):
    tag = proc.replace("SEI-", "").replace("/", "_")
    pasta = tmp_path / tag
    (pasta / "texto").mkdir(parents=True)
    com_texto = docs if com_texto is None else com_texto
    ds = []
    for i in range(docs):
        d = {"i": i, "titulo": f"doc {i}", "texto": ""}
        if i < com_texto:
            # tem de passar em `acervo_texto.tem_conteudo`: arquivo com só a etiqueta não conta
            # como documento capturado, e é isso que a régua da casa mede.
            (pasta / "texto" / f"{i}.txt").write_text(
                "teor real do documento " * 40, encoding="utf-8")
            d["texto"] = f"texto/{i}.txt"
        ds.append(d)
    (pasta / "manifest.json").write_text(
        json.dumps({"processo": proc, "gerado_em": gerado_em, "docs": ds}), encoding="utf-8")
    return pasta


def test_captura_integra_no_acervo_e_reconhecida(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "REPO", tmp_path)
    (tmp_path / "data").mkdir()
    _arquivar(tmp_path / "data" / "sei_arquivo", "SEI-1/1/2024", 10, "2026-08-09T10:00:00")
    assert S._arquivo_integro("SEI-1/1/2024") == "2026-08-09T10:00:00"


def test_captura_ABAIXO_do_minimo_nao_conta_como_integra(tmp_path, monkeypatch):
    """A régua é a mesma do motor de avaliação (60% dos documentos com texto): processo que o
    motor recusa avaliar por captura insuficiente é processo a recapturar, não a pular."""
    monkeypatch.setattr(S, "REPO", tmp_path)
    (tmp_path / "data").mkdir()
    _arquivar(tmp_path / "data" / "sei_arquivo", "SEI-2/2/2024", 10, "2026-08-09T10:00:00",
              com_texto=2)
    assert S._arquivo_integro("SEI-2/2/2024") is None


def test_processo_sem_pasta_nao_e_integro(tmp_path, monkeypatch):
    """Nunca capturado não é captura completa — esse caminho segue tratado pela fila normal."""
    monkeypatch.setattr(S, "REPO", tmp_path)
    (tmp_path / "data" / "sei_arquivo").mkdir(parents=True)
    assert S._arquivo_integro("SEI-3/3/2024") is None


def test_OB_mais_nova_que_a_captura_devolve_o_processo_a_fila():
    """A exceção que fica de pé: o processo andou depois de capturado, e a perícia precisa do que
    entrou. Sem ela, o conserto trocaria releitura inútil por cegueira a fato novo."""
    assert S._ob_desatualizada("2026-08-10T00:00:00", "2026-08-01T00:00:00") is True
    assert S._ob_desatualizada("2026-07-01T00:00:00", "2026-08-01T00:00:00") is False
