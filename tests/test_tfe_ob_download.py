# -*- coding: utf-8 -*-
"""Download do TFE: o cabeçalho malformado do servidor não derruba o semanal, e só zip válido substitui o anterior.

26/10/2026: o servidor passou a mandar "Connection: close\\x00"; o httpx (h11) recusa a resposta inteira
(RemoteProtocolError) e jfn-tfe-ob.service caiu. E `baixar` gravava `r.content` sem olhar status — uma
página de erro viraria fornecedor_ob.zip.
"""
from __future__ import annotations

import io
import zipfile

import httpx
import pytest

from compliance_agent.collectors import tfe_ob as T


def _zip_bytes():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("fornecedor_ob2026.csv", "a;b\n")
    return b.getvalue()


def _isolar(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "CACHE", tmp_path)
    monkeypatch.setattr(T, "ZIP", tmp_path / "fornecedor_ob.zip")


def test_cabecalho_malformado_cai_para_o_curl(tmp_path, monkeypatch):
    _isolar(tmp_path, monkeypatch)
    def _get(*a, **k):
        raise httpx.RemoteProtocolError("illegal header line: bytearray(b'Connection: close\\x00')")
    def _run(cmd, check):
        open(cmd[cmd.index("-o") + 1], "wb").write(_zip_bytes())
    monkeypatch.setattr(T.httpx, "get", _get)
    monkeypatch.setattr(T.subprocess, "run", _run)
    z = T.baixar(force=True)
    assert zipfile.is_zipfile(z)


def test_corpo_que_nao_e_zip_nao_substitui_o_anterior(tmp_path, monkeypatch):
    _isolar(tmp_path, monkeypatch)
    T.ZIP.write_bytes(_zip_bytes())
    class _R:
        content = b"<html>erro</html>"
        def raise_for_status(self): pass
    monkeypatch.setattr(T.httpx, "get", lambda *a, **k: _R())
    with pytest.raises(RuntimeError):
        T.baixar(force=True)
    assert zipfile.is_zipfile(T.ZIP)


def test_pagina_de_bloqueio_por_ip_e_nomeada(tmp_path, monkeypatch):
    _isolar(tmp_path, monkeypatch)
    class _R:
        content = ("<body>SECRETARIA DE ESTADO DE FAZENDA ... nosso serviço de segurança da informação bloqueia "
                   "acessos provenientes desses endereços IP ...</body>").encode()
        def raise_for_status(self): pass
    monkeypatch.setattr(T.httpx, "get", lambda *a, **k: _R())
    with pytest.raises(RuntimeError, match="recusou o IP"):
        T.baixar(force=True)
