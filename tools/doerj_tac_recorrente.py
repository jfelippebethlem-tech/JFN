# -*- coding: utf-8 -*-
"""Termos de Ajuste de Contas (TAC) publicados no DOERJ — quem recebe por TAC, quantas vezes, quanto.

TAC é o instrumento pelo qual o Estado paga serviço prestado SEM cobertura contratual regular
(Decreto 47.283/2020). Um TAC é exceção; TAC recorrente com o mesmo fornecedor é o padrão do caso
[[casos/idesi-fundacao-saude-rj]] (a contratação regular nunca chega e o pagamento vira rotina).
Desde 09/09/2026 o corpus do DOERJ é o PDF integral; este módulo lê os extratos de TAC e materializa:

  doerj_tac (data_doe, numero_tac, orgao, fornecedor, cnpj, valor, processo, objeto, id_publicacao)

e imprime o ranking por fornecedor (n de TAC, soma, órgãos). Só sinal positivo e só o que o texto
diz: valor ausente fica NULL, nunca zero; fornecedor não lido fica "(não lido)".

    python -m tools.doerj_tac_recorrente            # materializa e imprime o ranking
    python -m tools.doerj_tac_recorrente --resumo   # só imprime
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
from compliance_agent.reporting.intel_base import moeda  # noqa: E402

DB = _REPO / "data" / "compliance.db"

# O PDF quebra palavras com hífen no fim da linha ("Con- tas", "Ajus- te") e espalha espaços
# ("PA R T E S"). Normaliza-se ANTES de qualquer regex.
_RE_HIFEN_QUEBRA = re.compile(r"(?<=\w)-\s+(?=\w)")   # "RESTAU- RANTE", "OBJE-\nTO": hífen de quebra, sem espaço ANTES
_RE_ESPACADO = re.compile(r"\b(?:[A-ZÇÃÕÉÍÓÚÂÊ] ){2,}[A-ZÇÃÕÉÍÓÚÂÊ]\b")

_RE_TAC = re.compile(r"Termo\s+de\s+Ajuste\s+de\s+Contas(?:\s*[-–]?\s*(?:N\.?I\.?|n[º°o.]*)\s*(\d{1,5}/\d{4}))?", re.I)   # NI antes de nº: o ramo curto casava e engolia o número
_RE_VALOR = re.compile(r"V\s*A\s*(?:-\s*)?L\s*O\s*R(?:\s+TOTAL|\s+GLOBAL)?[^:R$]{0,30}:?\s*R\$\s*([\d][\d.]*,\d{2})", re.I)   # "VA - LOR": hífen de quebra COM espaço antes (o normalizador não o remove p/ não colar "CMP - CAMPOS")
_RE_PARTES = re.compile(r"P\s*A\s*R\s*T\s*E\s*S\s*:\s*(.+?)(?=\s(?:O\s*B\s*J\s*E\s*T\s*O|FUNDAMENTO|V\s*A\s*L\s*O\s*R|DATA|PROCESSO|Id:)\b|$)", re.I | re.S)
_RE_PROCESSO = re.compile(r"SEI\s*-?\s*((?:\d\s?){6}/\s?(?:\d\s?){6}/\s?(?:\d\s?){4})", re.I)   # dígitos podem vir espaçados no PDF
_RE_OBJETO = re.compile(r"O\s*B\s*J\s*E\s*T\s*O\s*:\s*(.+?)(?=\s(?:FUNDAMENTO|V\s*A\s*L\s*O\s*R|DATA|PROCESSO|P\s*A\s*R\s*T\s*E\s*S|PRAZO|Id:)\b|$)", re.I | re.S)
_RE_FIM_EXTRATO = re.compile(r"\bId:\s*\d|\bINSTRUMENTO\s*:|\bEXTRATO\s+DE\s+(?:TERMO|CONTRATO)", re.I)   # fim do extrato: marcador Id do D.O. ou o próximo cabeçalho
_RE_DATA = re.compile(r"DATA\s+D[AE]\s+ASSINATURA\s*:?\s*(\d{2}/\d{2}/\d{4})", re.I)
_RE_CNPJ = re.compile(r"CNPJ[^\d]{0,12}((?:\d\s?){2}\.?\s?(?:\d\s?){3}\.?\s?(?:\d\s?){3}/\s?(?:\d\s?){4}-?\s?(?:\d\s?){2})", re.I)


def normalizar(texto: str) -> str:
    t = re.sub(r"[\x00-\x08\x0b-\x1f]", " ", texto or "")   # fonte de PDF vaza bytes de controle no nome
    t = _RE_HIFEN_QUEBRA.sub("", t)
    t = _RE_ESPACADO.sub(lambda m: m.group(0).replace(" ", ""), t)
    return re.sub(r"[ \t]+", " ", t)


def _valor_br(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _partes(seg: str) -> tuple[str | None, str | None]:
    m = _RE_PARTES.search(seg)
    if not m:
        return None, None
    p = re.sub(r"\s+", " ", m.group(1)).strip(" .")
    # "Fundação Saúde do Estado do Rio de Janeiro e a empresa X" / "… e X LTDA"
    # "Estado do RJ, através da Secretaria X, e EMPRESA" / "Fundação Y e a empresa Z" / "… e a Z LTDA"
    div = re.split(r",?\s+e\s+(?:a\s+empresa\s+|a\s+|o\s+)?(?=[A-ZÀ-Ú0-9])", p, maxsplit=1)
    if len(div) == 2:
        orgao = div[0]
        m2 = re.search(r"atrav[ée]s\s+d[aeo]s?\s+(.+)$", orgao, re.I)
        if m2:
            orgao = m2.group(1)
        return orgao.strip(" ,")[:120], div[1].strip(" .")[:120]
    return p[:120], None


def extrair_tacs(texto: str) -> list[dict]:
    """Cada ocorrência de 'Termo de Ajuste de Contas' vira um registro com o que o entorno diz."""
    t = normalizar(texto)
    out: list[dict] = []
    # O SEGMENTO É PARA A FRENTE, do instrumento até o próximo (2026-09-10). A janela de ±900 chars
    # fabricava extratos híbridos: numa página com vários TACs em sequência (~700 chars cada), o
    # primeiro VALOR/SEI-/nº que a regex via era o do extrato ANTERIOR — a CMP saiu com o nº, o valor
    # e o processo dos vizinhos (PANTHER e GUERREIRO), e 75% dos processos não batiam com o credor
    # da OB no SIAFE. O extrato do D.O. é sempre INSTRUMENTO → PARTES → OBJETO → VALOR → FUNDAMENTO
    # (processo) → DATA; nada do próprio extrato vem antes do instrumento.
    matches = list(_RE_TAC.finditer(t))
    for i, m in enumerate(matches):
        fim = matches[i + 1].start() if i + 1 < len(matches) else len(t)
        fim = min(fim, m.start() + 1500)
        corte = _RE_FIM_EXTRATO.search(t, m.end(), fim)
        if corte:
            fim = corte.start()
        seg = t[m.start():fim]
        orgao, forn = _partes(seg)
        v = _RE_VALOR.search(seg)
        pr = _RE_PROCESSO.search(seg)
        ob = _RE_OBJETO.search(seg)
        dt = _RE_DATA.search(seg)
        cj = _RE_CNPJ.search(seg[max(0, (seg.find(forn[:20]) if forn else 0) - 40):] if forn else seg)
        out.append({
            "cnpj": re.sub(r"\D", "", cj.group(1)) if cj else None,
            "numero_tac": m.group(1),
            "orgao": orgao,
            "fornecedor": forn,
            "valor": _valor_br(v.group(1)) if v else None,
            "processo": "SEI-" + re.sub(r"\s", "", pr.group(1)) if pr else None,
            "objeto": re.sub(r"\s+", " ", ob.group(1)).strip()[:300] if ob else None,
            "data_assinatura": dt.group(1) if dt else None,
        })
    # MENÇÃO não é extrato: resolução que delega "assinar Termo de Ajuste de Contas", sindicância que cita o
    # TAC — sem nº, sem partes e sem valor não entra (medido 09/09: eram a maioria dos "(não lido)").
    out = [r for r in out if r["numero_tac"] or r["fornecedor"] or r["valor"] is not None]
    # a mesma publicação repete o TAC (apostilamento cita o TAC original): dedupe por nº + fornecedor
    vistos, dedup = set(), []
    for r in out:
        k = (r["numero_tac"], (r["fornecedor"] or "")[:40])
        if k in vistos:
            continue
        vistos.add(k)
        dedup.append(r)
    return dedup


def materializar() -> dict:
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    con.executescript("""
        DROP TABLE IF EXISTS doerj_tac;
        CREATE TABLE doerj_tac (
            data_doe TEXT, numero_tac TEXT, orgao TEXT, fornecedor TEXT, cnpj TEXT, valor REAL, processo TEXT,
            objeto TEXT, data_assinatura TEXT, id_publicacao INTEGER, gerado_em TEXT
        );
        CREATE INDEX ix_doerj_tac_forn ON doerj_tac(fornecedor);
    """)
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    rows = con.execute("SELECT id, data_publicacao, texto FROM publicacoes_doerj "
                       "WHERE texto LIKE '%Ajuste de Con%'").fetchall()
    with con:
        for pid, data, texto in rows:
            for r in extrair_tacs(texto):
                con.execute("INSERT INTO doerj_tac VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (str(data), r["numero_tac"], r["orgao"], r["fornecedor"], r["cnpj"], r["valor"], r["processo"],
                             r["objeto"], r["data_assinatura"], pid, agora))
                n += 1
    con.close()
    return {"publicacoes_com_tac": len(rows), "tacs": n}


def resumo(top: int = 15) -> list[dict]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    rows = con.execute(
        "SELECT coalesce(fornecedor,'(não lido)') f, count(*) n, count(valor) n_com_valor, round(sum(valor),2) soma, "
        "count(DISTINCT orgao) n_orgaos, min(data_doe), max(data_doe) FROM doerj_tac GROUP BY f "
        "ORDER BY n DESC, soma DESC LIMIT ?", (top,)).fetchall()
    con.close()
    return [dict(zip(("fornecedor", "n", "n_com_valor", "soma", "n_orgaos", "de", "ate"), r)) for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resumo", action="store_true")
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    if not a.resumo:
        print(json.dumps(materializar(), ensure_ascii=False))
    for r in resumo(a.top):
        print(f"{r['n']:3} TAC | {moeda(r['soma'] or 0):>18} ({r['n_com_valor']} c/ valor) | {r['n_orgaos']} órgão(s) | "
              f"{r['de']}→{r['ate']} | {r['fornecedor']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
