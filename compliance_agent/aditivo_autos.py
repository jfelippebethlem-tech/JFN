# -*- coding: utf-8 -*-
"""Valor global ATUALIZADO do contrato lido dos TERMOS ADITIVOS que estão nos autos capturados (14/11/2026).

Por que existe: o TCE-RJ não publica termos aditivos, e a perícia contábil comparava o pago com o valor ORIGINAL
registrado. Caso real (INEA × DIMENSIONAL, contrato 06/2023, processo SEI-070002/007444/2022): R$ 12.798.999,00 no
TCE-RJ; o 3º termo aditivo (61/2025), que está nos autos do processo de pagamento SEI-070002/005515/2024, diz
"totalizando o valor global do contrato com o Reajustamento o total de R$ 45.518.414,08" — o "pago acima do valor"
de R$ 8,7 mi não existia.

Regra (determinística, sem modelo):
  · documento de Termo Aditivo = título do documento no manifesto que COMEÇA por "termo aditivo" (ou "1º/primeiro
    termo aditivo"), sem "minuta"/"rascunho"/"proposta";
  · do MESMO contrato: no processo do próprio contrato, basta não citar no cabeçalho processo de OUTRO contrato do
    credor; em processo de pagamento (vínculo VERIFICADO), o cabeçalho (2.000 primeiros caracteres) TEM de citar o
    processo do contrato e nenhum processo de outro contrato do credor;
  · corpo = texto antes da assinatura eletrônica / da página do Diário Oficial (a publicação traz extratos de OUTROS
    contratos); o valor vem de frase que dá o TOTAL do contrato (nunca o valor do termo, nunca "VALOR DO CONTRATO:"
    de extrato), em ordem de preferência: global com reajustamento > "passa a ser" > "totalizando o contrato";
    duas frases do mesmo nível com valores distintos = não extraído;
  · vale o aditivo MAIS RECENTE (maior número de documento SEI, que é sequencial). Se o mais recente fala em R$ e
    não teve o valor extraído, o estado é SEM_VALOR — a perícia nunca afirma "acima do valor" com ele.
A citação literal (trecho do corpo, conferido por `verificacao.citacao_existe`) vai junto.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from compliance_agent.llm import verificacao as V

COM_VALOR, SEM_VALOR = "com_valor", "sem_valor"
CABECALHO = 2000

# título que É o termo (não minuta, parecer, solicitação ou despacho sobre ele) — medido 14/11/2026: uma "Minuta de
# Termo Aditivo" trazia valor global de rascunho
_RE_TITULO = re.compile(r"^\s*(?:\d{1,2}\s*[º°oª]?\s*|primeiro\s+|segundo\s+|terceiro\s+|quarto\s+|quinto\s+)?"
                        r"termo\s+aditivo", re.I)
_RE_MINUTA = re.compile(r"minuta|rascunho|proposta", re.I)
_RE_FIM_CORPO = re.compile(r"assinado\s+eletronicamente|DI[ÁA]RIO\s+OFICIAL", re.I)
_RE_DOC_SEI = re.compile(r"\((\d{6,10})\)\s*$")
_RE_NUM_ADITIVO = re.compile(r"TERMO\s+ADITIVO\s+N[º°o.]*\s*(\d{1,4}\s*/\s*\d{4})", re.I)
_RE_DATA_ASS = re.compile(r"assinado\s+eletronicamente.{0,160}?\bem\s+(\d{2}/\d{2}/\d{4})", re.I | re.S)
_V = r"R\$\s*((?:\d{1,3}(?:\.\d{3})+|\d+),\d{2})"
FRASES = (   # (nível, regex) — menor nível = preferido
    (1, re.compile(r"valor\s+global\s+do\s+contrato[^.;]{0,80}?total\s+de\s+" + _V, re.I)),
    (2, re.compile(r"passa(?:ndo)?\s+o\s+valor\s+(?:global|total)\s+(?:atualizado\s+)?do\s+contrato\s+(?:a\s+ser\s+de|"
                   r"para|a)\s+" + _V, re.I)),
    (2, re.compile(r"valor\s+(?:global|total)\s+(?:atualizado\s+)?do\s+contrato\s+(?:passa\s+a\s+ser|fica|ser[áa])\s+"
                   r"(?:de\s+)?" + _V, re.I)),
    (3, re.compile(r"totalizando\s+o\s+contrato\s+o\s+valor\s+(?:global\s+)?de\s+" + _V, re.I)),
)
_RE_REAL = re.compile(r"R\$\s*\d")


def _num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def corpo(texto: str) -> str:
    """Texto antes da assinatura / do Diário Oficial (só se o marcador vier depois do cabeçalho)."""
    for m in _RE_FIM_CORPO.finditer(texto):
        if m.start() > 300:
            return texto[:m.start()]
    return texto


def extrair_valor(texto: str) -> dict | None:
    """{'valor', 'trecho'} da frase de TOTAL do contrato no corpo, ou None (não extraído com segurança)."""
    c = " ".join(corpo(texto).split())
    for nivel in sorted({n for n, _ in FRASES}):
        achados = [(m, _num(m.group(1))) for n, rx in FRASES if n == nivel for m in rx.finditer(c)]
        if not achados:
            continue
        if len({v for _, v in achados}) > 1:
            return None
        m, v = achados[0]
        tr = c[max(0, m.start() - 120):m.end() + 40]
        return {"valor": v, "trecho": tr} if V.citacao_existe(tr, c) and v > 0 else None
    return None


def fala_em_dinheiro(texto: str) -> bool:
    return bool(_RE_REAL.search(corpo(texto)))


def _docs_aditivo(pasta: Path):
    try:
        man = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for d in man.get("docs") or []:
        tit = str(d.get("titulo") or "") if isinstance(d, dict) else ""
        if not isinstance(d, dict) or not d.get("texto") or not _RE_TITULO.search(tit) or _RE_MINUTA.search(tit):
            continue
        try:
            t = (pasta / d["texto"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = _RE_DOC_SEI.search(str(d.get("titulo") or ""))
        yield str(d.get("titulo") or ""), int(m.group(1)) if m else int(d.get("i") or 0), t


def aditivos_do_contrato(pastas: list[tuple[Path, bool]], proc_contrato: str, outros_processos: set[str],
                         chaves_citadas) -> list[dict]:
    """Termos aditivos do contrato nos autos. `pastas` = [(pasta, é_processo_do_contrato)]; `chaves_citadas(txt)`
    = conjunto de chaves de processo citadas (a função do vínculo)."""
    out, vistos = [], set()
    for pasta, do_contrato in pastas:
        for titulo, doc_sei, texto in _docs_aditivo(pasta):
            cab = chaves_citadas(texto[:CABECALHO])
            if cab & outros_processos:
                continue
            if not do_contrato and proc_contrato not in cab:
                continue
            if doc_sei in vistos:
                continue
            vistos.add(doc_sei)
            ext = extrair_valor(texto)
            num = _RE_NUM_ADITIVO.search(texto[:CABECALHO])
            data = _RE_DATA_ASS.search(texto)
            out.append({"doc_sei": doc_sei, "titulo": titulo[:120], "processo": pasta.name.replace("_", "/"),
                        "numero": re.sub(r"\s", "", num.group(1)) if num else "",
                        "data": data.group(1) if data else "",
                        "valor": ext["valor"] if ext else None, "trecho": ext["trecho"] if ext else "",
                        "fala_em_dinheiro": fala_em_dinheiro(texto)})
    return sorted(out, key=lambda a: a["doc_sei"])


def situacao(aditivos: list[dict]) -> dict | None:
    """O que vale para a perícia: o aditivo MAIS RECENTE com dinheiro no corpo. Termo só de prazo (sem R$) não muda
    valor e é ignorado. None = nenhum aditivo que fale em valor."""
    com_dinheiro = [a for a in aditivos if a["fala_em_dinheiro"]]
    if not com_dinheiro:
        return None
    ult = com_dinheiro[-1]
    if ult["valor"] is None:
        return {"estado": SEM_VALOR, **ult}
    return {"estado": COM_VALOR, **ult}
