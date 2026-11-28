# -*- coding: utf-8 -*-
"""Conferência de Autenticidade do SEI-RJ (Estado) — a porta pública do ORIGINAL de um documento, pelo par
código verificador + CRC do rodapé (O3.8 rota d; achado da sessão ubuntu-fe em 27/11/2026: 3 de 3 conferidos, com o
documento original e a lista de assinaturas).

De onde vêm os pares: todo documento assinado no SEI-RJ traz no rodapé "código verificador N e o código CRC
XXXXXXXX … Referência: Processo nº …". Cópias do contrato/estudo de um processo RESTRITO aparecem juntadas em
processos que lemos — o par, impresso no texto que já temos, abre o original. Medido no acervo (27/11): 18.394
pares que apontam para OUTRO processo; 1.083 deles para processos restritos.

  extrair_pares(texto, dono) -> [Par]       (puro) pares do texto cujo processo de referência ≠ o dono do texto
  conferir(cliente, ocr, par) -> Original   (HTTP) formulário + captcha (ddddocr); devolve o original + assinaturas

Mesmo mecanismo da Prefeitura (`deploy/vm2/sei_pcrj_conferir.py`), outro host e outro rodapé.
"""
from __future__ import annotations

import base64
import html as H
import re
from dataclasses import dataclass

BASE = "https://sei.rj.gov.br/sei/"
FORM = BASE + "controlador_externo.php?acao=documento_conferir&id_orgao_acesso_externo=0"
ACAO = BASE + ("controlador_externo.php?acao=documento_conferir&acao_origem=documento_conferir&lang=pt_BR"
               "&id_orgao_acesso_externo=0")
_RX_PAR = re.compile(r"c[óo]digo\s+verificador\s*(\d{6,10})\s*e\s+o\s+c[óo]digo\s+CRC\s*([0-9A-F]{8})(.{0,200})",
                     re.I | re.S)
_RX_REF = re.compile(r"Processo\s+n[ºo°.]*\s*(?:SEI[- ]?)?(\d{6})[/.-]?(\d{6})[/.-]?(\d{4})", re.I)
_RX_CAPTCHA = (re.compile(r'id="imgCaptcha"[^>]*src="data:image/png;base64,([^"]+)"'),
               re.compile(r'src="data:image/png;base64,([^"]+)"[^>]*id="imgCaptcha"'))
_RX_VISUALIZAR = re.compile(r'href="([^"]*hash_download[^"]*)"')
_RX_ASSIN = re.compile(r"Lista de Assinaturas \((\d+) registros?\):(.*)$", re.S)
_RX_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)


@dataclass(frozen=True)
class Par:
    verificador: str
    crc: str
    processo: str                     # o processo de REFERÊNCIA (dono do documento original), NNNNNN/NNNNNN/AAAA


@dataclass
class Original:
    par: Par
    conteudo: bytes                   # o original (HTML ou PDF), como o SEI o entrega
    assinaturas: str                  # a lista de assinaturas em texto (nome, cargo, data/hora, tipo)
    n_assinaturas: int


def extrair_pares(texto: str, dono: str | None = None) -> list[Par]:
    """Pares do texto cujo processo de referência é OUTRO que o `dono` (o próprio já lemos). Sem referência: fora
    (não dá para saber de qual processo é). Um par aparece uma vez. Puro."""
    dono_d = re.sub(r"\D", "", dono or "")
    vistos, out = set(), []
    for m in _RX_PAR.finditer(texto or ""):
        r = _RX_REF.search(m.group(3))
        if not r:
            continue
        ref_d = "".join(r.groups())
        par = Par(m.group(1), m.group(2).upper(), f"{r.group(1)}/{r.group(2)}/{r.group(3)}")
        if ref_d == dono_d or (par.verificador, par.crc) in vistos:
            continue
        vistos.add((par.verificador, par.crc))
        out.append(par)
    return out


def _texto(h: str) -> str:
    return " ".join(H.unescape(_RX_TAG.sub(" ", h)).split())


def conferir(cliente, ocr, par: Par, tentativas: int = 8) -> Original | None:
    """Formulário da conferência com o captcha lido por `ocr` (ddddocr.DdddOcr). None = o SEI não confirmou o par
    em `tentativas` (captcha recusado / par inválido) — o documento fica pendente, nunca "inexistente"."""
    for _ in range(tentativas):
        h = cliente.get(FORM).text
        m = next((rx.search(h) for rx in _RX_CAPTCHA if rx.search(h)), None)
        if not m:
            continue
        cap = re.sub(r"[^A-Za-z0-9]", "", ocr.classification(base64.b64decode(m.group(1))))
        r = cliente.post(ACAO, data={"hdnInfraTipoPagina": "3", "txtCodigoVerificador": par.verificador,
                                     "txtCrc": par.crc, "txtInfraCaptcha": cap, "hdnInfraCaptcha": "1",
                                     "sbmPesquisar": "Pesquisar", "hdnInfraPrefixoCookie": "ERJ_SEI_"})
        if "Lista de Assinaturas" not in r.text:
            continue                                  # o formulário voltou (captcha errado): tenta de novo
        v = _RX_VISUALIZAR.search(r.text)
        if not v:
            return None
        doc = cliente.get(BASE + H.unescape(v.group(1)))
        a = _RX_ASSIN.search(_texto(r.text))
        return Original(par=par, conteudo=doc.content, assinaturas=(a.group(2).strip() if a else "")[:4000],
                        n_assinaturas=int(a.group(1)) if a else 0)
    return None
