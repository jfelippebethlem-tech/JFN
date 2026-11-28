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


# ── a pesquisa pública como NAVEGADOR do E2/E3 (mesma interface do NavegadorSEI: arvore / capturar) ─────────────────
VIA = "pesquisa_publica"
VIA_CONFERENCIA = "conferencia_autenticidade"


def _doc_arvore(d: Documento, pares: dict[str, str] | None = None) -> dict:
    """Documento público no formato da árvore do E2 (`{t, u, restrito, id_documento}`): o título com o nº entre
    parênteses dá o MESMO doc_id do domínio que a árvore do SEI daria; `id_documento` = `p<nº>` (a página pública não
    expõe o id interno — o prefixo deixa claro de onde veio e muda a identidade se a via logada um dia abrir)."""
    crc = (pares or {}).get(d.numero) if d.url is None else None
    # O3.8 d: sem link mas com o par verificador+CRC no acervo = obtível pela Conferência de Autenticidade
    return {"t": f"{d.tipo} ({d.numero})", "u": d.url or "", "restrito": d.url is None and not crc,
            "id_documento": f"p{d.numero}", **({"crc": crc, "verificador": d.numero} if crc else {})}


class NavegadorPublico:
    """O E2 e o E3 pela pesquisa pública (só HTTP). `sessao` = tools.sei_rj_catalogo.Sessao (aberta na 1ª chamada);
    `baixar(url) -> bytes` injetável nos testes."""

    def __init__(self, sessao=None, baixar=None, consultar_fn=None, pares=None, conferir_fn=None):
        self._sessao, self._baixar, self._consultar = sessao, baixar, consultar_fn or consultar
        self._pares, self._conferir = dict(pares or {}), conferir_fn
        self._docs: dict[str, list[dict]] = {}

    def _s(self):
        if self._sessao is None:
            from tools.sei_rj_catalogo import Sessao
            self._sessao = Sessao()
            self._sessao.abrir()
        return self._sessao

    def _arvore(self, processo: str) -> list[dict]:
        if processo not in self._docs:
            _classe, arv = self._consultar(self._s(), processo)
            self._docs[processo] = [_doc_arvore(d, self._pares) for d in (arv.documentos if arv else [])]
        return self._docs[processo]

    def arvore(self, processo: str, pagina: int):
        from compliance_agent.aplicacao.estagios.arvore import PaginaArvore
        docs = self._arvore(processo)
        return PaginaArvore(docs=list(docs), proxima=None, via=VIA, sem_resultado=not docs)

    def _original(self, processo: str, x: dict) -> bytes:
        """O ORIGINAL pela Conferência de Autenticidade (par do acervo). b"" = o SEI não confirmou (fica omitido)."""
        from compliance_agent.sei import conferencia_autenticidade as CA
        par = CA.Par(x["verificador"], x["crc"], processo)
        if self._conferir is not None:
            o = self._conferir(par)
        else:
            import ddddocr
            self._ocr = getattr(self, "_ocr", None) or ddddocr.DdddOcr(show_ad=False)
            o = CA.conferir(self._s().c, self._ocr, par)
        return o.conteudo if o else b""

    def capturar(self, processo: str, guardados: dict, raiz):
        """Baixa os documentos com link que faltam (delta pelos guardados) e grava a pasta no FORMATO da íntegra
        (`manifest.json` + `donos.json` + `NNN.pdf|.html`): o E3 apura, grava e confere pelo mesmo contrato."""
        from pathlib import Path

        from compliance_agent import captura_delta as CD
        from compliance_agent.dominio import processo_id as PI
        docs = self._arvore(processo)
        outdir = Path(raiz) / f"integra_{PI.pasta(processo)}"
        outdir.mkdir(parents=True, exist_ok=True)
        manter = {e["i"] for e in CD.plano_de_captura(docs, CD.carregar_guardados(guardados))["manter"]}
        donos_p = outdir / "donos.json"
        donos = json.loads(donos_p.read_text(encoding="utf-8")) if donos_p.exists() else {}
        baixar = self._baixar or (lambda u: self._s().c.get(u).content)
        manifest, falhas = [], 0
        for i, x in enumerate(docs):
            idd = x["id_documento"]
            ok, nome, v = False, "", None
            if i in manter:
                v = "delta_guardado"
            elif x["u"] or x.get("crc"):
                via_doc = VIA if x["u"] else VIA_CONFERENCIA
                try:
                    corpo = baixar(x["u"]) if x["u"] else self._original(processo, x)
                except (OSError, RuntimeError, ValueError) as e:      # rede: o documento fica omitido (recaptura)
                    corpo, v = b"", f"falhou: {type(e).__name__}"
                if corpo:
                    nome = f"{i:03d}{'.pdf' if corpo[:4] == b'%PDF' else '.html'}"
                    (outdir / nome).write_bytes(corpo)
                    donos[nome] = idd
                    ok, v = True, via_doc
                else:
                    falhas += 1
            manifest.append({"i": i, "arquivo": nome, "titulo": x["t"], "contexto": "", "url": x["u"],
                             "id_documento": idd, "ok": ok, **({"via": v} if v else {})})
        donos_p.write_text(json.dumps(donos), encoding="utf-8")
        (outdir / "manifest.json").write_text(json.dumps({
            "processo": processo, "total_arvore": len(docs), "completo": falhas == 0, "origem": VIA,
            "pdf_lotes": {}, "docs": manifest}, ensure_ascii=False), encoding="utf-8")
        return outdir
