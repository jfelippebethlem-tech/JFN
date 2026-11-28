# -*- coding: utf-8 -*-
"""Pesquisa PÚBLICA do SEI-RJ como via de leitura dos processos que a unidade da casa vê como RESTRITO.

Achado de 27/11/2026 (sessão ubuntu-fe, a pedido do dono; amostra de 20 dos 4.923 de `data/sei_restritos.json`):
"Unidade atual não possui acesso ao processo restrito" é restrição da UNIDADE logada, não do público — 10/20 abrem
árvore + documentos pela pesquisa pública (link `md_pesq_documento_consulta_externa.php`, HTML e PDF), 6/20 mostram
só a árvore (tipo/data/unidade, sem link) e 4/20 não aparecem. O E2 descartava esses processos como ForaDeAlcance.

Só HTTP (sem navegador): a sessão de `tools.sei_rj_catalogo.Sessao` (captcha ddddocr). Armadilha medida: a resposta
do AJAX vem em iso-8859-1 — `r.json()` quebra; decodificar o conteúdo antes.

  buscar(sessao, processo) -> url da página pública do processo | None   (AJAX com o filtro do nº, 16 dígitos)
  ler_arvore(html) -> Arvore                                             (puro: a tabela tblDocumentos)
  classificar(arvore) -> PUBLICO_COM_DOCS | SO_ARVORE | NAO_ACHADO       (puro)
"""
from __future__ import annotations

import html as H
import json
import re
import urllib.parse
from dataclasses import dataclass, field

BASE = "https://sei.rj.gov.br/sei/modulos/pesquisa/"
PUBLICO_COM_DOCS, SO_ARVORE, NAO_ACHADO = "PUBLICO_COM_DOCS", "SO_ARVORE", "NAO_ACHADO"

_RX_LINHA = re.compile(r'<tr class="infraTr(?:Clara|Escura)">(.*?)</tr>', re.S)
_RX_CELULA = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_RX_DOC_LINK = re.compile(r"window\.open\('(md_pesq_documento_consulta_externa\.php\?[^']+)'")
_RX_PROC_LINK = re.compile(r'href="([^"]*md_pesq_processo_exibir[^"]*)"')
_RX_TAG = re.compile(r"<[^>]+>")


@dataclass
class Documento:
    numero: str
    tipo: str
    data: str
    inclusao: str
    unidade: str
    url: str | None                  # absoluta; None = documento sem link público


@dataclass
class Arvore:
    documentos: list[Documento] = field(default_factory=list)

    @property
    def com_link(self) -> list[Documento]:
        return [d for d in self.documentos if d.url]


def _texto(celula: str) -> str:
    return " ".join(H.unescape(_RX_TAG.sub(" ", celula)).split())


def ler_arvore(pagina: str) -> Arvore:
    """A tabela `tblDocumentos` da página pública do processo. Puro."""
    i = pagina.find('id="tblDocumentos"')
    if i < 0:
        return Arvore()
    fim = pagina.find("</table>", i)
    out = []
    for linha in _RX_LINHA.findall(pagina[i: fim if fim > 0 else None]):
        cel = _RX_CELULA.findall(linha)
        if len(cel) < 6:
            continue
        m = _RX_DOC_LINK.search(cel[1])
        out.append(Documento(numero=_texto(cel[1]), tipo=_texto(cel[2]), data=_texto(cel[3]),
                             inclusao=_texto(cel[4]), unidade=_texto(cel[5]),
                             url=(BASE + H.unescape(m.group(1))) if m else None))
    return Arvore(out)


def classificar(arvore: Arvore | None) -> str:
    if arvore is None or not arvore.documentos:
        return NAO_ACHADO
    return PUBLICO_COM_DOCS if arvore.com_link else SO_ARVORE


def resposta_ajax(conteudo: bytes) -> dict:
    """O JSON do AJAX da pesquisa (iso-8859-1 — `r.json()` quebra)."""
    return json.loads(conteudo.decode("iso-8859-1"))


def buscar(sessao, processo: str) -> str | None:
    """URL da página pública do processo (`sessao` = tools.sei_rj_catalogo.Sessao aberta), ou None se não aparece."""
    from tools.sei_rj_catalogo import AJAX, FORM
    digitos = re.sub(r"\D", "", processo)
    dados = [("q", "*"), ("partialfields", f"sta_prot:P AND prot_pesq:*{digitos}*"), ("chkSinProcessos", "P"),
             ("hdnFlagPesquisa", "1")]
    r = sessao.c.post(AJAX.format(inicio=0), content=urllib.parse.urlencode(dados),
                      headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                               "X-Requested-With": "XMLHttpRequest", "Referer": FORM})
    links = _RX_PROC_LINK.findall(resposta_ajax(r.content).get("html") or "")
    if not links:
        return None
    u = H.unescape(links[0])
    return u if u.startswith("http") else BASE + u.split("/")[-1]


def consultar(sessao, processo: str) -> tuple[str, Arvore | None]:
    """(classe, árvore) do processo pela pesquisa pública."""
    url = buscar(sessao, processo)
    if url is None:
        return NAO_ACHADO, None
    arv = ler_arvore(sessao.c.get(url).text)
    return classificar(arv), arv
