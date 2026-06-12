# -*- coding: utf-8 -*-
"""Coletor da Transparência da ALERJ (dados ABERTOS) — pagamentos/execução da Assembleia.

Fonte ABERTA (verificado 2026-06-12): `transparencia.alerj.rj.gov.br/section/report/{id}` lista documentos
mensais (PDF) baixáveis por `www2.alerj.rj.gov.br/leideacesso/verArquivo.asp?idArquivo=N`. report/120=Pagamentos,
report/118=Contratos, report/117=Execução. O DOCIGP (descentralização por gabinete) é app Livewire à parte.

Os PDFs de pagamento são "Ordem cronológica de pagamentos": colunas Programa de Trabalho | Natureza | **Credor** |
Empenho(NE) | Liquidação(NL) | Emissão NL | Ordem Bancária(OB) | Emissão OB | **Despesas Pagas (R$)**.
Determinístico (pdftotext -layout + regex). Honesto: o que não parsear fica de fora (nunca inventa). O credor é
o NOME (sem CNPJ no PDF) → cruzar por nome com `socios_fornecedor`/`endereco_fornecedor` p/ ligar à fachada/relações.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_BASE_REPORT = "https://transparencia.alerj.rj.gov.br/section/report/{rid}"
_VERARQ = "https://www2.alerj.rj.gov.br/leideacesso/verArquivo.asp?idArquivo={idA}"
_UA = "Mozilla/5.0 (X11; Linux x86_64) Chrome/120"

# linha de pagamento (pdftotext -layout): natureza(6) ... CREDOR ... NE ... NL ... data ... R$ valor (último)
_RE_PAG = re.compile(
    r"^\s*(?P<natureza>\d{6})\s+(?P<credor>.+?)\s+(?P<ne>\d{4}NE\d+)\s+(?P<nl>\d{4}NL\d+)\s+"
    r"(?P<data>\d{2}/\d{2}/\d{4}).*?R\$\s*(?P<valor>\d{1,3}(?:\.\d{3})*,\d{2})\s*$")
_RE_MESANO = re.compile(r"pagamentos realizados\s*-\s*([A-Za-zçÇ]+)\s*/?\s*(\d{4})", re.I)


def _f(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def listar_documentos(report_id: int, timeout: int = 25) -> list[dict]:
    """Lista os documentos (idArquivo + rótulo) de uma seção report/{id}. Best-effort, sem rede pesada."""
    try:
        html = subprocess.run(["curl", "-s", "-m", str(timeout), "-A", _UA, _BASE_REPORT.format(rid=report_id)],
                              capture_output=True, text=True).stdout
    except Exception:  # noqa: BLE001
        return []
    ids = re.findall(r"idArquivo%3D(\d+)|idArquivo=(\d+)", html)
    out, vistos = [], set()
    for a, b in ids:
        idA = a or b
        if idA and idA not in vistos:
            vistos.add(idA)
            out.append({"idArquivo": idA, "url": _VERARQ.format(idA=idA)})
    return out


def baixar_pdf(idArquivo: str, destino: str | Path, timeout: int = 40) -> bool:
    """Baixa o PDF do verArquivo.asp. True se baixou um %PDF."""
    p = Path(destino)
    try:
        subprocess.run(["curl", "-s", "-L", "-m", str(timeout), "-A", _UA, _VERARQ.format(idA=idArquivo),
                        "-o", str(p)], check=False)
        return p.exists() and p.stat().st_size > 1000 and p.read_bytes()[:4] == b"%PDF"
    except Exception:  # noqa: BLE001
        return False


def _pdf_texto(pdf: str | Path) -> str:
    try:
        r = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, timeout=60)
        return r.stdout
    except Exception:  # noqa: BLE001
        try:
            import pypdf
            return "\n".join(pg.extract_text() or "" for pg in pypdf.PdfReader(str(pdf)).pages)
        except Exception:  # noqa: BLE001
            return ""


def parsear_pagamentos(texto: str) -> dict:
    """Extrai as linhas de pagamento do texto (pdftotext -layout). Retorna {mes_ano, n, itens}. Honesto."""
    m = _RE_MESANO.search(texto or "")
    mes_ano = f"{m.group(1).title()}/{m.group(2)}" if m else None
    itens = []
    for ln in (texto or "").splitlines():
        g = _RE_PAG.match(ln)
        if not g:
            continue
        credor = re.sub(r"\s+", " ", g.group("credor")).strip()
        if len(credor) < 3:
            continue
        itens.append({"natureza": g.group("natureza"), "credor": credor, "empenho": g.group("ne"),
                      "liquidacao": g.group("nl"), "data": g.group("data"), "valor": _f(g.group("valor"))})
    return {"mes_ano": mes_ano, "n": len(itens), "itens": itens}


if __name__ == "__main__":  # pragma: no cover
    import sys
    if len(sys.argv) > 1 and sys.argv[1].endswith(".pdf"):
        r = parsear_pagamentos(_pdf_texto(sys.argv[1]))
        print(f"{r['mes_ano']}: {r['n']} pagamentos")
        for it in r["itens"][:15]:
            print(f"  {it['data']} {it['credor'][:40]:40} {it['empenho']} R$ {it['valor']:,.2f}")
    else:
        for d in listar_documentos(int(sys.argv[1]) if len(sys.argv) > 1 else 120)[:10]:
            print(d)
