# -*- coding: utf-8 -*-
"""Retomada dos mistos da O3.6 em sombra (`tools/ocr_mistos_sombra.py`): a saída é a do E5 atual (o efeito do
`ocr.conferir` passa no lateral gravado), o nativo fica intacto e a retomada é idempotente por (documento, página)."""
import json
import os
from pathlib import Path

import pytest

from compliance_agent.aplicacao.estagios import confirmar_ocr as C
from compliance_agent.aplicacao.estagios import ocr as O
from compliance_agent.aplicacao.estagios import ocr_recorte as R
from compliance_agent.aplicacao.estagios import texto as T
from tests.test_estagio_ocr import Falso
from tests.test_estagio_texto import pdf_de
from tools import ocr_bancada_o36 as B
from tools import ocr_mistos_sombra as S


class Interrompe(Falso):
    """Lê a 1ª página pedida e 'morre' (processo morto) na 2ª — nada de linha de resultado."""

    def ler(self, pdf, paginas):
        if paginas == [3]:
            raise SystemExit("morto no meio do documento")
        return super().ler(pdf, paginas)


@pytest.fixture()
def sombra(tmp_path, monkeypatch):
    pdf = pdf_de(tmp_path / "001.pdf", ["nativa", ("escaneada", "Pag 2"), "escaneada"])
    d = tmp_path / "sombra"
    d.mkdir()
    (d / "fila.jsonl").write_text(json.dumps({"hd": str(pdf), "origem": "c", "processo": "999999/000001/2026",
                                              "tag": "t", "i": "1", "tipo": "nota_fiscal", "doc_id": "sei:123456",
                                              "escaneadas": 2}) + "\n", encoding="utf-8")
    monkeypatch.setattr(B, "SNAPSHOT", tmp_path / "nao_existe.db")
    monkeypatch.setattr(R, "leitores_do_no", lambda: {})
    monkeypatch.setattr(C, "leitura_independente", lambda *a, **k: {})
    monkeypatch.setattr(C, "barras", lambda *a, **k: {"chaves": []})
    monkeypatch.setenv("JFN_SOMBRA_RESERVAS", str(tmp_path / "reservas"))
    return pdf, d


def _linhas(d):
    return [json.loads(x) for arq in sorted((d / "resultados").glob("*.jsonl")) for x in arq.read_text().splitlines()]


def test_saida_e_a_do_e5_e_nativo_intacto_e_nao_refaz(sombra, monkeypatch):
    pdf, d = sombra
    lidos = Falso("rapidocr", {2: "Valor total R$ 9.999,00", 3: "CNPJ 00.000.000/0001-91"})
    monkeypatch.setattr(O, "ExecutorCPU", lambda: lidos)
    monkeypatch.setattr(O, "ExecutorTesseract", lambda: Falso("tesseract"))
    assert S.rodar(d, "cpu", "0/1", None, dinamico=True)["documentos"] == 1
    (r,) = _linhas(d)
    assert r["conferencia_e5"]["ok"] and r["nativas_intactas"] and r["versao"] == O.VERSAO
    lat, _ = T.ler_lateral(d / r["lateral"])
    assert lat["entrada_sha"] == T.sha256_arquivo(pdf) and lat["doc_id"] == "sei:123456" and lat["versao"] == O.VERSAO
    assert lat["compostas"][0] == T.extrair(pdf)["paginas"][0]["texto"]           # a nativa, byte a byte
    assert set(lat["paginas"]) == {"2", "3"} and all(v["linhas"] for v in lat["paginas"].values())
    assert lat["sombra"]["gravado_pg"] is False
    assert S.rodar(d, "cpu", "0/1", None, dinamico=True)["documentos"] == 0     # já feito: não relê
    assert lidos.pedidas == [[2], [3]]


def test_interrompido_no_meio_retoma_so_a_pagina_que_faltou(sombra, monkeypatch):
    _, d = sombra
    monkeypatch.setattr(O, "ExecutorTesseract", lambda: Falso("tesseract"))
    morre = Interrompe("rapidocr", {2: "Valor R$ 1,00", 3: "Valor R$ 2,00"})
    monkeypatch.setattr(O, "ExecutorCPU", lambda: morre)
    with pytest.raises(SystemExit):
        S.rodar(d, "cpu", "0/1", None, dinamico=True)
    assert _linhas(d) == []
    for p in Path(os.environ["JFN_SOMBRA_RESERVAS"]).iterdir():
        p.unlink()                                                 # o script de subida limpa as reservas
    volta = Falso("rapidocr", {2: "Valor R$ 1,00", 3: "Valor R$ 2,00"})
    monkeypatch.setattr(O, "ExecutorCPU", lambda: volta)
    S.rodar(d, "cpu", "0/1", None, dinamico=True)
    assert volta.pedidas == [[3]]                                  # a página 2 veio do cache do E5
    (r,) = _linhas(d)
    assert r["conferencia_e5"]["ok"] and r["dedup_cache"] == 1


def test_governador_le_o_limite_e_sem_arquivo_libera_todos(tmp_path):
    assert S._permitidos(tmp_path, 6) == 6
    (tmp_path / "governo.json").write_text(json.dumps({"permitidos": 2}))
    assert S._permitidos(tmp_path, 6) == 2


def test_gpu_espera_folga_para_carregar_e_recua_quando_outro_sobe(monkeypatch):
    g = S._GuardaVRAM()
    leituras = iter([(4.1, 8.0), (0.1, 8.0), (4.0, 8.0), (8.0, 8.0)])     # Voicebox; descarregou; eu; Voicebox de volta
    monkeypatch.setattr(S._GuardaVRAM, "_uso", staticmethod(lambda: next(leituras)))
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    g.antes_do_documento()                       # esperou a folga (4,1 GB ocupados ⇒ não carrega)
    assert g.base == 0.1
    g.antes_do_documento()                       # só eu na GPU: segue
    with pytest.raises(SystemExit, match="recuo da GPU"):
        g.antes_do_documento()
