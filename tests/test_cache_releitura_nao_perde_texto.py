# -*- coding: utf-8 -*-
"""Releitura pior não pode apagar texto que o cache já tinha — a gravação FUNDE, não sobrescreve.

O CASO REAL (2026-08-08, primeiro slot de recaptura que logou). A recaptura releu o
SEI-030001/005866/2026 com o teto levantado; a sessão trouxe 100 documentos com texto e o cache
anterior tinha 101. A gravação sobrescrevia o arquivo inteiro, e o documento que só a leitura
antiga tinha — um doc pode falhar individualmente numa sessão e ter vindo na anterior — foi
APAGADO por uma rotina que existe para SOMAR. O log registrou `101 → 100` e o slot terminou com
"+0 documentos", quando na verdade terminou com −1.

A guarda de leitura truncada não cobre isso: ela só veta a gravação quando o BROWSER morre no meio.
Falha de um documento com a página viva passa por ela.

Regra da fusão: o que a leitura nova traz MANDA (conteúdo mais fresco vence); o que só o cache
antigo tem é RESGATADO, identificado pelo campo `doc` (título + número SEI). E o resgate aparece
também no RETORNO, porque a recaptura conta o ganho pelo que a função devolve — resgate invisível
ao contador viraria "releitura sem ganho" no progresso e o processo sairia da fila como se nada
faltasse.
"""
from __future__ import annotations

import json

from tools.sei_reader import _grava_cache_atomico


def _doc(nome: str, conteudo: str = "texto com tamanho razoável para contar") -> dict:
    return {"doc": nome, "conteudo": conteudo, "via": "html"}


def test_releitura_com_menos_docs_resgata_o_que_o_cache_tinha(tmp_path):
    cache = tmp_path / "cdp_SEI_030001_005866_2026.json"
    cache.write_text(json.dumps({
        "numero": "SEI-030001/005866/2026",
        "conteudo_documentos": [_doc("Despacho (111)"), _doc("Nota de Empenho (222)"),
                                _doc("Só a leitura antiga tem (333)")],
    }), encoding="utf-8")

    res = {"numero": "SEI-030001/005866/2026",
           "conteudo_documentos": [_doc("Despacho (111)", "versão NOVA, mais fresca"),
                                   _doc("Nota de Empenho (222)")]}
    _grava_cache_atomico(cache, res)

    gravado = json.loads(cache.read_text(encoding="utf-8"))
    por_doc = {d["doc"]: d["conteudo"] for d in gravado["conteudo_documentos"]}
    assert "Só a leitura antiga tem (333)" in por_doc, (
        "a releitura pior apagou um documento que o cache tinha — o caso 101→100 de volta")
    assert por_doc["Despacho (111)"] == "versão NOVA, mais fresca", (
        "a fusão deixou o conteúdo velho vencer o fresco — o certo é novo manda, antigo resgata")
    assert len(gravado["conteudo_documentos"]) == 3


def test_o_resgate_aparece_no_retorno_para_o_contador_de_ganho(tmp_path):
    cache = tmp_path / "cdp_X.json"
    cache.write_text(json.dumps({
        "conteudo_documentos": [_doc("A (1)"), _doc("B (2)")]}), encoding="utf-8")
    res = {"conteudo_documentos": [_doc("A (1)")]}
    _grava_cache_atomico(cache, res)
    assert {d["doc"] for d in res["conteudo_documentos"]} == {"A (1)", "B (2)"}, (
        "o resgate ficou só no disco — quem conta ganho pelo retorno registraria perda")


def test_doc_antigo_sem_conteudo_nao_e_resgatado(tmp_path):
    """Etiqueta vazia não é texto: resgatar doc sem `conteudo` só inflaria a contagem."""
    cache = tmp_path / "cdp_Y.json"
    cache.write_text(json.dumps({
        "conteudo_documentos": [{"doc": "Vazio (9)", "conteudo": "", "via": "html"}]}),
        encoding="utf-8")
    res = {"conteudo_documentos": [_doc("Novo (1)")]}
    _grava_cache_atomico(cache, res)
    gravado = json.loads(cache.read_text(encoding="utf-8"))
    assert [d["doc"] for d in gravado["conteudo_documentos"]] == ["Novo (1)"]


def test_sem_cache_anterior_grava_normal(tmp_path):
    cache = tmp_path / "cdp_Z.json"
    res = {"conteudo_documentos": [_doc("Único (7)")], "anexo_bytes": b"%PDF-lixo"}
    _grava_cache_atomico(cache, res)
    gravado = json.loads(cache.read_text(encoding="utf-8"))
    assert [d["doc"] for d in gravado["conteudo_documentos"]] == ["Único (7)"]
    assert "%PDF" not in cache.read_text(encoding="utf-8"), (
        "o anexo binário voltou a vazar para o disco — era o cache de 127 MB")
