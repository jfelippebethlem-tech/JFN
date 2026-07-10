#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cérebro-sync — o elo DETERMINÍSTICO DB → vault (diário, cron 06:25).

Desenho (espelha a outra VM): DB → vault (determinístico, diário) → agentes (metacognição/RAG/Claude)
→ decisões → de volta ao vault (hub + hipóteses + diário + log). O vault vira ÓRGÃO do sistema:
os números vivem no compliance.db e este script os MATERIALIZA no vault todo dia; os agentes leem
o vault fresco (o RAG do Hermes re-indexa às 06:50 só-se-mudou) e as decisões voltam como notas.

Saídas (todas idempotentes; mesma foto do DB ⇒ mesmo texto):
  1. dados/estado-do-sistema.md            — painel do sistema (REESCRITO inteiro)
  2. casos/*.md                            — bloco `cerebro:dados` (entre sentinelas) p/ casos com cnpj:/ug:
  3. 00-INDEX.md                           — bloco `cerebro:hub` (casos abertos + hipóteses + saúde 1-linha)
  4. diario/AAAA-MM-DD.md                  — cria se ausente + seção gerada (delta 24h)
  5. log.md                                — ledger append-only (1 linha por run)

Regras: OB = SIAFE direto (`ob_orcamentaria_siafe`, status='Contabilizado'), NUNCA o espelho TFE.
Datas do DB são DD/MM/AAAA → ordenar SEMPRE pela forma ISO derivada (MAX lexicográfico mente).
Sentinelas são DONAS do código: texto entre `<!-- cerebro:...:inicio -->` e `fim` é regravado a cada run;
edição humana ali se perde (editar FORA do bloco). Honesto: INDISPONÍVEL ≠ 0 — sem dado, escreve "n/d".
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

JFN = Path(__file__).resolve().parents[1]
VAULT = Path.home() / "vault"
DB = JFN / "data" / "compliance.db"
HOJE = datetime.now().strftime("%Y-%m-%d")


def brl(v) -> str:
    if v is None:
        return "n/d"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def mil(n) -> str:
    """Milhar BR p/ contagens (1.234.567). Nunca usar {:,} cru no texto final."""
    return "n/d" if n is None else f"{n:,}".replace(",", ".")


ISO_EXPR = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"


def frontmatter(texto: str) -> dict:
    """Frontmatter YAML raso (chave: valor) — suficiente p/ os casos do vault."""
    m = re.match(r"^---\n(.*?)\n---", texto, re.S)
    if not m:
        return {}
    fm = {}
    for ln in m.group(1).splitlines():
        mm = re.match(r"^(\w[\w-]*):\s*(.*)$", ln)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip().strip('"')
    return fm


def substituir_bloco(texto: str, tag: str, corpo: str) -> str:
    """Regrava o conteúdo entre as sentinelas `cerebro:<tag>`; se não existirem, anexa ao fim."""
    ini, fim = f"<!-- cerebro:{tag}:inicio -->", f"<!-- cerebro:{tag}:fim -->"
    bloco = f"{ini}\n{corpo.rstrip()}\n{fim}"
    if ini in texto and fim in texto:
        return re.sub(re.escape(ini) + r".*?" + re.escape(fim), lambda _: bloco, texto, flags=re.S)
    return texto.rstrip() + "\n\n" + bloco + "\n"


# ── 1. blocos por CASO ─────────────────────────────────────────────────────────
def bloco_caso(db, fm: dict) -> str | None:
    cnpj, ug = digits(fm.get("cnpj", "")), digits(fm.get("ug", ""))
    linhas = []
    if cnpj:
        n, tot, ult = db.execute(
            f"SELECT COUNT(*), SUM(valor), MAX({ISO_EXPR}) FROM ob_orcamentaria_siafe "
            "WHERE credor=? AND status='Contabilizado'", (cnpj,)).fetchone()
        ugs = db.execute(
            "SELECT ug_emitente, COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe "
            "WHERE credor=? AND status='Contabilizado' GROUP BY 1 ORDER BY 3 DESC, 1 LIMIT 3", (cnpj,)).fetchall()
        sanc = db.execute("SELECT COUNT(*) FROM sancoes_federais WHERE replace(replace(replace(cpf_cnpj,'.',''),'/',''),'-','')=?",
                          (cnpj,)).fetchone()[0]
        fichas = db.execute("SELECT COUNT(*) FROM sei_ficha WHERE cnpjs LIKE ?", (f"%{cnpj}%",)).fetchone()[0]
        emp = db.execute("SELECT situacao, municipio, uf FROM empresas WHERE replace(replace(replace(cnpj,'.',''),'/',''),'-','')=?",
                         (cnpj,)).fetchone()
        linhas.append(f"- **OB SIAFE (contabilizadas):** {n} · **{brl(tot)}** · última {ult or 'n/d'}")
        if ugs:
            linhas.append("- **Top UGs pagadoras:** " + " · ".join(f"{u} ({c} OB, {brl(v)})" for u, c, v in ugs))
        linhas.append(f"- **Sanções federais (cadastros):** {sanc} · **Fichas SEI citando o CNPJ:** {fichas}")
        if emp:
            linhas.append(f"- **Receita:** situação {emp[0] or 'n/d'} · {emp[1] or 'n/d'}/{emp[2] or 'n/d'}")
    if ug:
        n, tot, ult = db.execute(
            f"SELECT COUNT(*), SUM(valor), MAX({ISO_EXPR}) FROM ob_orcamentaria_siafe "
            "WHERE ug_emitente=? AND status='Contabilizado'", (ug,)).fetchone()
        top = db.execute(
            "SELECT nome_credor, COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe "
            "WHERE ug_emitente=? AND status='Contabilizado' GROUP BY 1 ORDER BY 3 DESC, 1 LIMIT 3", (ug,)).fetchall()
        linhas.append(f"- **UG {ug} — OB SIAFE emitidas:** {n} · **{brl(tot)}** · última {ult or 'n/d'}")
        if top:
            linhas.append("- **Top credores da UG:** " + " · ".join(f"{(c or 'n/d')[:34]} ({brl(v)})" for c, _, v in top))
    if not linhas:
        return None
    return "## 📊 Dados do sistema (gerado — não editar dentro do bloco)\n" + "\n".join(linhas) + \
        "\n\n> Fonte: `compliance.db` (SIAFE/Receita/CEIS/SEI) via `tools/cerebro_sync.py` — regravado diariamente."


# ── 2. painel estado-do-sistema ────────────────────────────────────────────────
def painel(db) -> str:
    n_ob, tot_ob, ult_ob = db.execute(
        f"SELECT COUNT(*), SUM(valor), MAX({ISO_EXPR}) FROM ob_orcamentaria_siafe WHERE status='Contabilizado'").fetchone()
    por_ex = db.execute(
        "SELECT exercicio, COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe "
        "WHERE status='Contabilizado' GROUP BY 1 ORDER BY 1 DESC LIMIT 4").fetchall()
    fichas = db.execute("SELECT COUNT(*) FROM sei_ficha").fetchone()[0]
    sanc = db.execute("SELECT COUNT(*) FROM sancoes_federais").fetchone()[0]
    emp = db.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]

    prog_f = JFN / "data" / "sei_cache" / "sei_sweep_progress.json"
    lidos = com_docs = esgotados = "n/d"
    try:
        feitos = json.loads(prog_f.read_text()).get("feitos", {})
        lidos = len(feitos)
        com_docs = sum(1 for v in feitos.values() if isinstance(v, dict) and v.get("n_docs", 0) > 0)
        esgotados = sum(1 for v in feitos.values()
                        if isinstance(v, dict) and not v.get("n_docs", 0) and v.get("tentativas", 1) >= 3)
    except Exception:
        pass

    # taxa do sweep por dia (7d) direto do log — padrão EXATO ("frescor" também tem "→")
    taxa = []
    try:
        log = (JFN / "data" / "sei_sweep.log").read_text(errors="replace")
        for i in range(6, -1, -1):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            ls = re.findall(rf"{d} .*→ (\d+) docs", log)
            if ls:
                ok = sum(1 for x in ls if x != "0")
                taxa.append(f"{d[5:]}: {ok}/{len(ls)}")
    except Exception:
        pass

    vivos = []
    for nome, p in [("sweep SEI", "data/sei_sweep.log"), ("SIAFE diário", "data/siafe_runner_cron.log"),
                    ("íntegra noturna", "data/sei_integra_fila.log")]:
        f = JFN / p
        if f.exists():
            h = (datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)).total_seconds() / 3600
            vivos.append(f"{nome}: {'🟢' if h < 26 else '🔴'} ({h:.0f}h)")
        else:
            vivos.append(f"{nome}: ⚪ sem log")

    return f"""---
tipo: painel
atualizado: {HOJE}
gerado_por: tools/cerebro_sync.py
resumo: painel diário determinístico do sistema (OB SIAFE, SEI, cadastros, saúde dos pipelines) — regravado todo run; números vivem no compliance.db.
tags: [painel, sistema, gerado]
---

# 📟 Estado do Sistema (gerado diariamente)

> Regravado por `tools/cerebro_sync.py` (cron 06:25). **Não editar** — mudanças se perdem no próximo run.

## Ordens Bancárias (SIAFE — a verdade de pagamento)
- **Contabilizadas:** {mil(n_ob)} · **{brl(tot_ob)}** · última emissão **{ult_ob or 'n/d'}**
{chr(10).join(f'- {ex}: {mil(c)} OB · {brl(v)}' for ex, c, v in por_ex)}

## SEI
- **Fichas analisadas:** {mil(fichas)} · **Processos varridos:** {mil(lidos) if isinstance(lidos, int) else lidos} ({com_docs} com docs · {esgotados} esgotados 3×)
- **Taxa do sweep (7d, lidos com docs/tentativas):** {' · '.join(taxa) or 'n/d'}

## Cadastros
- **Sanções federais (CEIS/CNEP…):** {mil(sanc)} · **Empresas enriquecidas (Receita):** {mil(emp)}

## Pipelines (frescor do log)
- {' · '.join(vivos)}

> Ligações: [[MOC-Casos]] · [[MOC-Dados]] · [[00-INDEX]] · hipóteses em `hipoteses/`.
"""


# ── 3. hub / 4. diário / 5. log ────────────────────────────────────────────────
def bloco_hub(db, casos: list[tuple[str, dict]]) -> str:
    abertos = [(p, fm) for p, fm in casos if (fm.get("status", "").lower().startswith("abert")
                                              or "ANDAMENTO" in fm.get("status", "").upper())]
    abertos.sort(key=lambda x: (0 if "🔴" in x[1].get("severidade", "") else 1, x[0].name))
    linhas = ["## 🫀 Órgão — visão gerada (diária)", "",
              f"**Casos abertos: {len(abertos)}** · painel: [[dados/estado-do-sistema]]", ""]
    for p, fm in abertos:
        sev = fm.get("severidade", "—").split("(")[0].strip()
        atu = fm.get("atualizado", "n/d")
        try:
            velho = (datetime.now() - datetime.strptime(atu, "%Y-%m-%d")).days > 21
        except ValueError:
            velho = False
        linhas.append(f"- [[casos/{p.stem}]] — {sev} · atualizado {atu}{' ⚠️ parado >21d' if velho else ''}")
    hips = sorted((VAULT / "hipoteses").glob("*.md")) if (VAULT / "hipoteses").exists() else []
    hips = [h for h in hips if not h.name.startswith("_")]
    ab = [h for h in hips if "status: aberta" in h.read_text(errors="replace")[:400]]
    linhas.append(f"\n**Hipóteses:** {len(ab)} abertas de {len(hips)} — `hipoteses/`" +
                  ("".join(f"\n- [[hipoteses/{h.stem}]]" for h in ab)))
    return "\n".join(linhas)


def diario_e_log(db) -> str:
    novas24 = db.execute("SELECT COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe "
                         "WHERE status='Contabilizado' AND coletado_em >= datetime('now','-1 day','localtime')").fetchone()
    resumo = f"OB coletadas 24h: {novas24[0]} ({brl(novas24[1]) if novas24[0] else 'R$ 0,00'})"
    ddir = VAULT / "diario"
    ddir.mkdir(exist_ok=True)
    dfile = ddir / f"{HOJE}.md"
    if not dfile.exists():
        dfile.write_text(f"---\ntipo: diario\natualizado: {HOJE}\ntags: [diario]\n---\n\n# {HOJE}\n", encoding="utf-8")
    txt = substituir_bloco(dfile.read_text(encoding="utf-8"), "diario",
                           f"## Sistema (gerado)\n- {resumo}\n- Painel do dia: [[dados/estado-do-sistema]]")
    dfile.write_text(txt, encoding="utf-8")
    return resumo


def main() -> int:
    if not DB.exists() or not VAULT.exists():
        print(f"faltando {'DB' if not DB.exists() else 'vault'} — abortando honesto", file=sys.stderr)
        return 2
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)  # read-only: o órgão NUNCA escreve no DB
    casos = [(p, frontmatter(p.read_text(errors="replace"))) for p in sorted((VAULT / "casos").glob("*.md"))]

    n_blocos = 0
    for p, fm in casos:
        corpo = bloco_caso(db, fm)
        if corpo:
            p.write_text(substituir_bloco(p.read_text(encoding="utf-8"), "dados", corpo), encoding="utf-8")
            n_blocos += 1

    (VAULT / "dados").mkdir(exist_ok=True)
    (VAULT / "dados" / "estado-do-sistema.md").write_text(painel(db), encoding="utf-8")

    hub_f = VAULT / "00-INDEX.md"
    hub_f.write_text(substituir_bloco(hub_f.read_text(encoding="utf-8"), "hub", bloco_hub(db, casos)),
                     encoding="utf-8")

    resumo = diario_e_log(db)
    with (VAULT / "log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {datetime.now().strftime('%Y-%m-%d %H:%M')} cerebro_sync | painel + {n_blocos} casos + hub + diário · {resumo}\n")
    print(f"ok: painel + {n_blocos} blocos de caso + hub + diário ({resumo})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
