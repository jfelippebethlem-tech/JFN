# -*- coding: utf-8 -*-
"""Contratadas da saúde estadual cujos SÓCIOS estão na folha da saúde estadual — por contrato e por TAC.

O que o papel não mostra: a Fundação Saúde (FSERJ) contrata — por licitação (registro do TCE-RJ) e por
Termo de Ajuste de Contas (DOERJ) — empresas cujos donos são o seu próprio corpo clínico. Este módulo
materializa `fserj_socio_agente` cruzando `contratos_tcerj` (unidade FSERJ) e `doerj_tac` com
`agente_publico_societario` (folha do Estado × QSA, casamento por NOME normalizado), e GRADUA:

  🔴 direto     sócio empregado/dirigente da PRÓPRIA FSERJ (art. 14, IV da Lei 14.133 — "agente público do
                órgão ou entidade contratante"); cargo em comissão/direção pesa mais
  🟡 vinculado  sócio servidor da SES (Lei 7.946/18) contratando com a FSERJ — mesmo sistema, ente distinto;
                exige análise jurídica antes de afirmar impedimento
  ⚪ outro      agente de outro órgão (PM, BM, educação…) — relevante para OSINT, não para o art. 14 aqui

HONESTIDADE: casamento por nome; nome comum é hipótese até o CPF. O vínculo tem de valer NA DATA do ato
(folha capturada é recente); a nota diz o alcance. Indício ≠ acusação.

    python -m tools.fserj_socio_agente            # materializa + ranking
    python -m tools.fserj_socio_agente --resumo   # só imprime
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
from compliance_agent.reporting.intel_base import moeda  # noqa: E402

DB = _REPO / "data" / "compliance.db"
NOMES_COMUNS_MIN_TOKENS = 3      # menos que isto (ex.: "JOSE CARLOS SANTOS") = homônimo provável


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^A-Z ]", " ", unicodedata.normalize("NFKD", (s or "").upper())
                           .encode("ascii", "ignore").decode()).split())


def graduar(orgao: str | None, cargo: str | None, vinculo: str | None) -> str:
    """🔴 se o sócio é da própria FSERJ; 🟡 se é da SES (mesmo sistema); ⚪ outros."""
    o = _norm(orgao)   # cargo/vínculo ficam na tabela para leitura humana; a graduação é pelo ENTE
    if "FUNDACAO SAUDE" in o or "FSERJ" in o:
        return "🔴"
    if "SAUDE" in o and not any(k in o for k in ("PREFEITURA", "RIOSAUDE", "MUNICIP")):
        return "🟡"          # saúde ESTADUAL (SES); RioSaúde/Prefeitura é outra esfera → ⚪
    return "⚪"


def peso_nome(nome: str) -> str:
    """'forte' quando o nome tem 3+ tokens distintivos (colisão rara); 'fraco' quando é curto/comum."""
    toks = [t for t in _norm(nome).split() if t not in {"DE", "DA", "DO", "DOS", "DAS", "E"}]
    return "forte" if len(toks) >= NOMES_COMUNS_MIN_TOKENS else "fraco"


def materializar() -> dict:
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    # universo: raízes de CNPJ contratadas pela FSERJ (TCE-RJ) + fornecedores de TAC com CNPJ resolvido
    univ: dict[str, dict] = {}
    for raiz, forn, n, soma in con.execute(
            "SELECT substr(replace(replace(replace(cnpj,'.',''),'/',''),'-',''),1,8), fornecedor, count(*), round(sum(valor_contrato),2) "
            "FROM contratos_tcerj WHERE unidade LIKE 'FSERJ%' AND cnpj IS NOT NULL GROUP BY 1,2"):
        if raiz and len(raiz) == 8:
            u = univ.setdefault(raiz, {"fornecedor": forn, "contratos": 0, "valor_contratos": 0.0, "tacs": 0, "valor_tacs": 0.0})
            u["contratos"] += n
            u["valor_contratos"] += soma or 0
    try:
        for forn, cnpj, n, soma in con.execute(
                "SELECT fornecedor, cnpj, max(n_tac), max(soma_tac) FROM doerj_tac_sinal WHERE cnpj IS NOT NULL GROUP BY 1,2"):
            raiz = cnpj[:8]
            u = univ.setdefault(raiz, {"fornecedor": forn, "contratos": 0, "valor_contratos": 0.0, "tacs": 0, "valor_tacs": 0.0})
            u["tacs"] = max(u["tacs"], n or 0)
            u["valor_tacs"] = max(u["valor_tacs"], soma or 0)
    except sqlite3.OperationalError:
        pass
    con.executescript("""
        DROP TABLE IF EXISTS fserj_socio_agente;
        CREATE TABLE fserj_socio_agente (
            cnpj_basico TEXT, fornecedor TEXT, contratos INTEGER, valor_contratos REAL, tacs INTEGER, valor_tacs REAL,
            socio TEXT, cargo TEXT, vinculo TEXT, orgao TEXT, origem TEXT, grau TEXT, peso_nome TEXT, gerado_em TEXT
        );
        CREATE INDEX ix_fsa_cnpj ON fserj_socio_agente(cnpj_basico);
    """)
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    graus = {"🔴": 0, "🟡": 0, "⚪": 0}
    with con:
        for raiz, u in univ.items():
            for nome, cargo, vinc, orgao, origem in con.execute(
                    "SELECT nome_socio, cargo, vinculo, orgao, origem FROM agente_publico_societario WHERE cnpj_basico=?", (raiz,)):
                g = graduar(orgao, cargo, vinc)
                con.execute("INSERT INTO fserj_socio_agente VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (raiz, u["fornecedor"], u["contratos"], u["valor_contratos"], u["tacs"], u["valor_tacs"],
                             nome, cargo, vinc, orgao, origem, g, peso_nome(nome), agora))
                n += 1
                graus[g] += 1
    con.close()
    return {"fornecedores_universo": len(univ), "linhas": n, "por_grau": graus}


def resumo(top: int = 20) -> list[dict]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    rows = con.execute(
        "SELECT fornecedor, cnpj_basico, contratos, valor_contratos, tacs, valor_tacs, "
        "sum(grau='🔴') v, sum(grau='🟡') a, group_concat(socio || ' [' || grau || ' ' || peso_nome || ']', '; ') "
        "FROM fserj_socio_agente WHERE grau IN ('🔴','🟡') GROUP BY 1,2 "
        "ORDER BY v DESC, a DESC, (coalesce(valor_contratos,0)+coalesce(valor_tacs,0)) DESC LIMIT ?", (top,)).fetchall()
    con.close()
    return [dict(zip(("fornecedor", "cnpj_basico", "contratos", "valor_contratos", "tacs", "valor_tacs", "vermelhos", "amarelos", "socios"), r))
            for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resumo", action="store_true")
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()
    if not a.resumo:
        print(json.dumps(materializar(), ensure_ascii=False))
    for r in resumo(a.top):
        print(f"{r['vermelhos']}🔴 {r['amarelos']}🟡 | ctr {r['contratos']:3} {moeda(r['valor_contratos'] or 0):>16} | TAC {r['tacs']:3} "
              f"{moeda(r['valor_tacs'] or 0):>14} | {r['fornecedor'][:36]:36} | {r['socios'][:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
