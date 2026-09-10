# -*- coding: utf-8 -*-
"""TAC × favorecimento — o que o papel do D.O. não mostra, as bases da casa cruzam.

Universo: os fornecedores pagos por Termo de Ajuste de Contas (`doerj_tac`, PDF integral do DOERJ). Para
cada um, resolve o CNPJ (registro do TCE-RJ; depois `socios_fornecedor`) e procura SINAIS POSITIVOS:

  doacao_eleitoral        a empresa (CNPJ) consta como doadora em `doacoes_eleitorais` — lícito, mas
                          relevante quando o candidato tem cargo no Estado; grau 🟡, 🔴 se ≥ R$ 50 mil
  doacao_socio            SÓCIO da empresa é doador (nome 3+ tokens corroborado pelos 6 dígitos do CPF
                          mascarado — regra do lex_conflito); 🟡, 🔴 se ≥ R$ 50 mil no conjunto
  agente_publico_no_qsa   sócio que é agente público (`agente_publico_societario`) — 🔴 se o órgão é da
                          saúde estadual (SES/FSERJ), 🟡 nos demais
  socio_comum             sócio presente em 2+ fornecedores de TAC (`socios_fornecedor`) — rede, 🟡
  capital_infimo          capital social < 1% da soma de TAC no período (`empresas_cadastro`) — 🟡
  fachada                 `fantasma_score`/`verificacao_sede_real` acusam fachada/fantasma — 🔴
  emergencia_recorrente   o mesmo fornecedor tem 3+ compras diretas por emergência (`compras_diretas_tcerj`) — 🟡

HONESTIDADE: CNPJ não resolvido = "não localizado", nunca "limpo"; ausência de sinal não é atestado.
Indício ≠ acusação; cada sinal carrega a evidência para conferência humana. Materializa `doerj_tac_sinal`.

    python -m tools.doerj_tac_favorecimento            # materializa + ranking
    python -m tools.doerj_tac_favorecimento --resumo   # só imprime
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
from compliance_agent.reporting.intel_base import moeda  # noqa: E402

DB = _REPO / "data" / "compliance.db"
_STOP = {"LTDA", "ME", "EPP", "SA", "EIRELI", "EMPRESA", "DE", "DO", "DA", "DOS", "DAS", "E", "COMERCIO", "SERVICOS",
         "SERVICO", "CIA", "COMPANHIA", "GRUPO", "INDUSTRIA", "CONSTRUCOES", "CONSTRUTORA", "EMPRESARIAIS", "LTDA."}
DOACAO_FORTE = 50_000.0
ORGAOS_SAUDE = ("SAUDE", "SAÚDE", "FSERJ", "FUNDACAO SAUDE", "FUNDAÇÃO SAÚDE")


def norm(s: str) -> str:
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", unicodedata.normalize("NFKD", (s or "").upper())
                           .encode("ascii", "ignore").decode()).split())


def tokens(nome: str, n: int = 2) -> list[str]:
    """Os N primeiros tokens distintivos (sem forma jurídica) — a chave de casamento por nome."""
    return [t for t in norm(nome).split() if len(t) >= 3 and t not in _STOP][:n]


def _like(col: str, toks: list[str]) -> str:
    return " AND ".join(f"{col} LIKE '%{t}%'" for t in toks) or "0"


def resolver_cnpj(con: sqlite3.Connection, fornecedor: str) -> str | None:
    toks = tokens(fornecedor)
    if not toks:
        return None
    for tabela, col_nome, col_cnpj in (("contratos_tcerj", "fornecedor", "cnpj"), ("socios_fornecedor", "razao", "cnpj")):
        rows = con.execute(f"SELECT {col_cnpj} FROM {tabela} WHERE {_like(col_nome, toks)} AND {col_cnpj} IS NOT NULL").fetchall()
        c = Counter(re.sub(r"\D", "", r[0]) for r in rows if r[0])
        c.pop("", None)
        if c:
            cnpj, n = c.most_common(1)[0]
            if len(cnpj) == 14:
                return cnpj
    return None


def grau_agente(orgao: str | None) -> str:
    """🔴 só para a saúde ESTADUAL (SES/FSERJ — o contratante dos TAC); RioSaúde/Prefeitura é outra esfera → 🟡."""
    o = norm(orgao or "")
    if any(k in o for k in ("PREFEITURA", "RIOSAUDE", "MUNICIP", "CAMARA MUNICIPAL")):
        return "🟡"
    return "🔴" if any(norm(k) in o for k in ORGAOS_SAUDE) else "🟡"


def _doadores_por_nome(con: sqlite3.Connection) -> dict[str, list[tuple]]:
    """Doadores RJ com nome de 3+ tokens → [(candidato, cargo, partido, ano, valor, cpf_meio6)]."""
    out: dict[str, list[tuple]] = defaultdict(list)
    for nome, cand, cargo, part, ano, val, doc in con.execute(
            "SELECT nome_doador, nome_candidato, cargo_candidato, partido, substr(data_doacao,1,4), valor, cpf_cnpj_doador "
            "FROM doacoes_eleitorais WHERE uf='RJ'"):
        n = norm(nome)
        if len(n.split()) >= 3:
            out[n].append((cand, cargo, part, ano, val or 0.0, re.sub(r"\D", "", doc or "")[3:9]))
    return out


def sinais_de(con: sqlite3.Connection, cnpj: str | None, fornecedor: str, n_tac: int, soma_tac: float,
              socios_por_nome: dict[str, set[str]], doadores: dict[str, list[tuple]] | None = None) -> list[dict]:
    out: list[dict] = []
    toks = tokens(fornecedor)
    if cnpj:
        raiz = cnpj[:8]
        # sócio doador — nome 3+ tokens E os 6 dígitos do meio do CPF (mascarado na Receita) batendo
        if doadores:
            achados = []
            for nome, doc in con.execute("SELECT nome_socio, doc_socio FROM socios_receita WHERE cnpj_basico=?", (raiz,)):
                k = norm(nome)
                if k in doadores:
                    meio = re.sub(r"\D", "", doc or "")
                    ds = [d for d in doadores[k] if d[5] and d[5] == meio]
                    if ds:
                        achados.append((nome, ds))
            if achados:
                total = sum(d[4] for _, ds in achados for d in ds)
                det = "; ".join(f"{nome} → " + ", ".join(sorted({f'{d[0][:28]} ({d[1]}, {d[2]}, {d[3]})' for d in ds}))
                                for nome, ds in achados[:3])
                out.append({"sinal": "doacao_socio", "grau": "🔴" if total >= DOACAO_FORTE else "🟡",
                            "detalhe": f"{len(achados)} sócio(s) doador(es), {moeda(total)} (nome + CPF mascarado): {det}",
                            "evidencia": {"socios": [{"nome": n, "doacoes": [list(d) for d in ds]} for n, ds in achados]}})
        d = con.execute("SELECT nome_candidato, cargo_candidato, partido, substr(data_doacao,1,4), round(sum(valor),2) "
                        "FROM doacoes_eleitorais WHERE replace(replace(replace(cpf_cnpj_doador,'.',''),'/',''),'-','')=? "
                        "GROUP BY 1,2,3,4 ORDER BY 5 DESC LIMIT 8", (cnpj,)).fetchall()
        if d:
            total = sum(x[4] or 0 for x in d)
            out.append({"sinal": "doacao_eleitoral", "grau": "🔴" if total >= DOACAO_FORTE else "🟡",
                        "detalhe": f"doou {moeda(total)} a {len(d)} candidato(s): " +
                                   "; ".join(f"{x[0]} ({x[1]}, {x[2]}, {x[3]}) {moeda(x[4])}" for x in d[:4]),
                        "evidencia": {"doacoes": [list(x) for x in d]}})
        a = con.execute("SELECT nome_socio, cargo, vinculo, orgao, origem FROM agente_publico_societario WHERE cnpj_basico=? LIMIT 6",
                        (raiz,)).fetchall()
        if a:
            grau = "🔴" if any(grau_agente(x[3]) == "🔴" for x in a) else "🟡"
            out.append({"sinal": "agente_publico_no_qsa", "grau": grau,
                        "detalhe": "; ".join(f"{x[0]} — {x[1] or '?'} ({x[2] or '?'}) em {x[3] or '?'} [{x[4]}]" for x in a[:3]),
                        "evidencia": {"agentes": [list(x) for x in a]}})
        cap = con.execute("SELECT capital_social, porte_txt FROM empresas_cadastro WHERE cnpj_basico=?", (raiz,)).fetchone()
        if cap and cap[0] is not None and soma_tac > 0 and float(cap[0]) < 0.01 * soma_tac:
            out.append({"sinal": "capital_infimo", "grau": "🟡",
                        "detalhe": f"capital social {moeda(cap[0])} ({cap[1] or 'porte ?'}) para {moeda(soma_tac)} em TAC no período "
                                   f"({100 * float(cap[0]) / soma_tac:.2f}%)",
                        "evidencia": {"capital": cap[0], "porte": cap[1], "soma_tac": soma_tac}})
        f = con.execute("SELECT classificacao, score FROM fantasma_score WHERE replace(replace(replace(cnpj,'.',''),'/',''),'-','')=?",
                        (cnpj,)).fetchone()
        v = con.execute("SELECT veredito, score_suspeita FROM verificacao_sede_real WHERE replace(replace(replace(cnpj,'.',''),'/',''),'-','')=?",
                        (cnpj,)).fetchone()
        ruim = [x for x in ((f[0] if f else None), (v[0] if v else None)) if x and re.search(r"fachada|fantasma|inexist", str(x), re.I)]
        if ruim:
            out.append({"sinal": "fachada", "grau": "🔴", "detalhe": f"fantasma_score={f[0] if f else '—'} · sede_real={v[0] if v else '—'}",
                        "evidencia": {"fantasma": list(f) if f else None, "sede": list(v) if v else None}})
        socios = socios_por_nome.get(cnpj) or set()
        comuns = {s: outros for s in socios if len(outros := socios_por_nome["_por_socio"].get(s, set()) - {cnpj}) >= 1}
        if comuns:
            out.append({"sinal": "socio_comum", "grau": "🟡",
                        "detalhe": "; ".join(f"{s[:40]} também em {len(o)} outro(s) fornecedor(es) de TAC" for s, o in list(comuns.items())[:3]),
                        "evidencia": {"socios": {s: sorted(o) for s, o in comuns.items()}}})
    if toks:
        e = con.execute(f"SELECT count(*), round(sum(valor),2), min(ano_processo), max(ano_processo) FROM compras_diretas_tcerj "
                        f"WHERE {_like('fornecedor', toks)} AND (afastamento LIKE '%merg%' OR enquadramento_legal LIKE '%VIII%' "
                        f"OR enquadramento_legal LIKE '%inciso IV%')").fetchone()
        if e and e[0] and e[0] >= 3:
            out.append({"sinal": "emergencia_recorrente", "grau": "🟡",
                        "detalhe": f"{e[0]} compras diretas por emergência ({e[2]}→{e[3]}) somando {moeda(e[1] or 0)} — além dos {n_tac} TAC",
                        "evidencia": {"n": e[0], "soma": e[1], "anos": [e[2], e[3]]}})
    return out


def materializar(min_tac: int = 3) -> dict:
    con = sqlite3.connect(DB, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    forns = con.execute("SELECT fornecedor, count(*), round(sum(valor),2) FROM doerj_tac WHERE fornecedor IS NOT NULL "
                        "GROUP BY 1 HAVING count(*) >= ? ORDER BY 2 DESC", (min_tac,)).fetchall()
    cnpj_de = {f: resolver_cnpj(con, f) for f, _, _ in forns}
    # rede de sócios só entre os fornecedores de TAC (o que interessa é a ligação entre eles)
    socios_por_nome: dict = defaultdict(set)
    socios_por_nome["_por_socio"] = defaultdict(set)
    cnpjs = [c for c in cnpj_de.values() if c]
    for cnpj in cnpjs:
        for (s,) in con.execute("SELECT socio_nome_norm FROM socios_fornecedor WHERE replace(replace(replace(cnpj,'.',''),'/',''),'-','')=?", (cnpj,)):
            if s and len(s) > 8:
                socios_por_nome[cnpj].add(s)
                socios_por_nome["_por_socio"][s].add(cnpj)
    con.executescript("""
        DROP TABLE IF EXISTS doerj_tac_sinal;
        CREATE TABLE doerj_tac_sinal (fornecedor TEXT, cnpj TEXT, n_tac INTEGER, soma_tac REAL, sinal TEXT, grau TEXT,
                                      detalhe TEXT, evidencia TEXT, gerado_em TEXT);
        CREATE INDEX ix_dts_forn ON doerj_tac_sinal(fornecedor);
    """)
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    doadores = _doadores_por_nome(con)
    n_sin, nao_res, por_sinal = 0, 0, Counter()
    with con:
        for f, n, soma in forns:
            cnpj = cnpj_de[f]
            if not cnpj:
                nao_res += 1
            sinais = sinais_de(con, cnpj, f, n, soma or 0, socios_por_nome, doadores)
            if cnpj and not sinais:      # linha-âncora: o CNPJ resolvido fica materializado mesmo sem sinal
                con.execute("INSERT INTO doerj_tac_sinal VALUES (?,?,?,?,?,?,?,?,?)",
                            (f, cnpj, n, soma, "sem_sinal", "⚪", "nenhum cruzamento positivo — não é atestado", "{}", agora))
            for s in sinais:
                con.execute("INSERT INTO doerj_tac_sinal VALUES (?,?,?,?,?,?,?,?,?)",
                            (f, cnpj, n, soma, s["sinal"], s["grau"], s["detalhe"], json.dumps(s["evidencia"], ensure_ascii=False), agora))
                n_sin += 1
                por_sinal[s["sinal"]] += 1
            if not cnpj:
                con.execute("INSERT INTO doerj_tac_sinal VALUES (?,?,?,?,?,?,?,?,?)",
                            (f, None, n, soma, "cnpj_nao_localizado", "⚪", "nome não casou em contratos_tcerj nem socios_fornecedor — sem cruzamento possível",
                             "{}", agora))
    con.close()
    return {"fornecedores": len(forns), "min_tac": min_tac, "cnpj_resolvido": len(forns) - nao_res, "sinais": n_sin, "por_sinal": dict(por_sinal)}


def resumo(top: int = 20) -> list[dict]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)
    rows = con.execute(
        "SELECT fornecedor, cnpj, n_tac, soma_tac, group_concat(grau || ' ' || sinal, ' · '), "
        "sum(grau='🔴') vermelhos, count(*) n FROM doerj_tac_sinal WHERE sinal NOT IN ('cnpj_nao_localizado','sem_sinal') "
        "GROUP BY 1,2,3,4 ORDER BY vermelhos DESC, n DESC, soma_tac DESC LIMIT ?", (top,)).fetchall()
    con.close()
    return [dict(zip(("fornecedor", "cnpj", "n_tac", "soma_tac", "sinais", "vermelhos", "n"), r)) for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resumo", action="store_true")
    ap.add_argument("--min-tac", type=int, default=3)
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()
    if not a.resumo:
        print(json.dumps(materializar(a.min_tac), ensure_ascii=False))
    for r in resumo(a.top):
        print(f"{r['vermelhos']}🔴 {r['n']} sinal | {r['n_tac']:3} TAC {moeda(r['soma_tac'] or 0):>16} | {r['fornecedor'][:40]:40} | {r['sinais']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
