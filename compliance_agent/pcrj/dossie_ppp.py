# -*- coding: utf-8 -*-
"""Dossiê de PPP/concessão municipal (F4) — consolida as fontes + a análise.

Junta o que a captação levantou de um projeto de PPP:
  • CCPAR (``pcrj_ppp``)          → identificação, fase, investimento, documentos
  • D.O. Rio (``pcrj_doe_materia``) → vencedor, contraprestação, nº de processo
  • motores de análise (``analise``) → triagem de direcionamento/red flags/fraude

e renderiza no padrão Kroll (``reporting/render_html``). Honestidade: dado ausente
vira "INDISPONÍVEL" (nunca 0); indício ≠ acusação; só a fonte primária fecha.

Uso:
    python -m compliance_agent.pcrj.dossie_ppp complexo-hospitalar-souza-aguiar --pdf
"""
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timezone

from . import db
from . import analise
from . import lente_ppp
from ..reporting import render_html as rh

_RE_VALOR = re.compile(r"R\$\s?([\d\.]+,\d{2})")
# valor monetário com separador de milhar, com ou sem "R$" (tabelas do D.O. trazem número cru)
_RE_VALOR_MILHAR = re.compile(r"(\d{1,3}(?:\.\d{3})+,\d{2})")


def _fmt_reais(v) -> str:
    if v is None:
        return "INDISPONÍVEL"
    try:
        return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(v)


def _chaves_projeto(nome: str) -> list[str]:
    """Chaves de casamento por CONTEÚDO derivadas do nome do projeto (nunca hardcoded).

    Inclui o nome inteiro e as 2 últimas palavras significativas (ex.: 'Souza Aguiar'),
    p/ pegar variantes ('...Municipal Souza Aguiar'). Assim um projeto não puxa atos de outro.
    """
    chaves = [nome] if nome else []
    palavras = [w for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", nome or "")]
    if len(palavras) >= 2:
        chaves.append(" ".join(palavras[-2:]))
    return list(dict.fromkeys(c for c in chaves if c and len(c) >= 5))


def _acts_do_projeto(con, chaves: list[str]) -> list[dict]:
    """Atos do D.O. cujo TEXTO menciona o projeto (por conteúdo, não pelo termo de busca)."""
    if not chaves:
        return []
    qs = " OR ".join("texto LIKE ?" for _ in chaves)
    rows = con.execute(
        f"SELECT id_materia,data,ano,tipo,processos,texto FROM pcrj_doe_materia "
        f"WHERE {qs} ORDER BY data DESC",
        [f"%{c}%" for c in chaves],
    ).fetchall()
    return [dict(r) for r in rows]


def _valor_num(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _extrair_resultado(acts: list[dict]) -> dict:
    """Vencedor, contraprestação e processos a partir do texto dos atos (indício).

    Contraprestação: valores ≥ R$ 1 mi numa janela após o vencedor / 'contraprestação' / 'VCM',
    escolhendo o MAIS FREQUENTE (repete na tabela de classificação). Valor duvidoso ⇒ INDISPONÍVEL
    (número errado é pior que ausente — regra de honestidade).
    """
    from collections import Counter
    vencedor, processos = None, []
    candidatos: list[str] = []
    for a in acts:
        txt = a["texto"] or ""
        if vencedor is None:
            m = re.search(r"(?:Concession[áa]ria|Cons[óo]rcio)\s+([A-ZÀ-Ú][\w \./&-]{3,50}?S[/.]?A)", txt)
            if m:
                vencedor = m.group(1).strip()
        ancoras = [w for w in ("contrapresta", "VCM", "contrapresta[çc][ãa]o mensal") if w]
        if vencedor:  # núcleo do nome do vencedor (2 primeiras palavras) como âncora
            ancoras.append(re.escape(" ".join(vencedor.split()[:2])))
        for anc in ancoras:
            for am in re.finditer(anc, txt, re.I):
                janela = txt[am.start(): am.start() + 260]
                for vm in _RE_VALOR_MILHAR.finditer(janela):
                    try:
                        if _valor_num(vm.group(1)) >= 1_000_000:
                            candidatos.append(vm.group(1))
                    except ValueError:
                        continue
        for p in json.loads(a["processos"] or "[]"):
            if p not in processos:
                processos.append(p)
    contrap = Counter(candidatos).most_common(1)[0][0] if candidatos else None
    return {"vencedor": vencedor, "contraprestacao": contrap, "processos": processos}


def _tabela(linhas: list[tuple]) -> str:
    trs = "".join(
        f"<tr><td style='padding:4px 10px;font-weight:600'>{html.escape(str(k))}</td>"
        f"<td style='padding:4px 10px'>{v}</td></tr>" for k, v in linhas
    )
    return f"<table style='border-collapse:collapse;width:100%'>{trs}</table>"


def montar_dossie(slug: str, db_path=None) -> dict:
    db.inicializar(db_path)
    con = db.conectar(db_path)
    try:
        ppp = con.execute("SELECT * FROM pcrj_ppp WHERE slug=?", (slug,)).fetchone()
        ppp = dict(ppp) if ppp else {}
        nome = ppp.get("nome") or slug.replace("-", " ").title()
        # atos do D.O. cujo TEXTO menciona o projeto (chaves derivadas do nome — sem hardcode)
        acts = _acts_do_projeto(con, _chaves_projeto(nome))
        # edital CCPAR ingerido (texto completo das cláusulas de habilitação), se houver
        eds = con.execute(
            "SELECT texto FROM pcrj_processo_doc WHERE numero_processo=? AND tipo='edital_ccpar' "
            "ORDER BY seq", (slug,)).fetchall()
        edital_ccpar = "\n\n".join(r["texto"] for r in eds if r["texto"])
    finally:
        con.close()

    resultado = _extrair_resultado(acts)
    docs = json.loads(ppp.get("docs_json") or "[]")
    datas = json.loads(ppp.get("datas_json") or "[]")

    # análise: prefere o EDITAL CCPAR (cláusulas de habilitação reais); senão, atos do D.O.
    fonte_corpus = "edital+anexos CCPAR (completo)" if edital_ccpar else "atos do D.O. Rio"
    corpus_full = (edital_ccpar or
                   "\n\n".join(a["texto"] for a in acts if a["tipo"] in ("edital", "ppp", "extrato_contrato")))
    corpus = corpus_full[:120_000]  # cap só p/ os motores E1–E7 (a lente roda no texto inteiro)
    an = analise.analisar_edital(
        corpus, numero=(resultado["processos"][0] if resultado["processos"] else ""),
        orgao=ppp.get("orgao_gestor") or "", objeto=nome,
        modalidade="Concessão/PPP", valor=ppp.get("valor_investimento"),
    ) if corpus.strip() else None

    # ── seções (Kroll) ───────────────────────────────────────────────
    secoes = []
    secoes.append({"titulo": "I. Identificação do Projeto", "html": _tabela([
        ("Projeto", html.escape(nome)),
        ("Órgão gestor", html.escape(ppp.get("orgao_gestor") or "INDISPONÍVEL")),
        ("Modalidade", "Concessão Administrativa / PPP"),
        ("Fase", html.escape(ppp.get("fase") or "INDISPONÍVEL")),
        ("Investimento previsto", _fmt_reais(ppp.get("valor_investimento"))),
        ("Fonte", "ccpar.rio + Diário Oficial do Rio (doweb)"),
    ])})

    secoes.append({"titulo": "II. Resultado da Licitação", "html": _tabela([
        ("Vencedor", html.escape(resultado["vencedor"] or "INDISPONÍVEL")),
        ("Contraprestação mensal", "R$ " + resultado["contraprestacao"] if resultado["contraprestacao"] else "INDISPONÍVEL"),
        ("Processos administrativos", ", ".join(resultado["processos"]) or "INDISPONÍVEL"),
    ]) + "<p style='font-size:11px;color:#666'>Vencedor/valor extraídos por indício do texto do D.O.; a íntegra do contrato fecha.</p>"})

    if datas:
        secoes.append({"titulo": "III. Linha do Tempo (datas do projeto)", "html":
            "<ul>" + "".join(f"<li>{html.escape(d)}</li>" for d in datas) + "</ul>"})

    if docs:
        li = "".join(
            f"<li><a href='{html.escape(d['url'])}'>{html.escape(d.get('titulo') or 'documento')}</a></li>"
            for d in docs)
        secoes.append({"titulo": f"IV. Documentos publicados ({len(docs)})", "html": f"<ul>{li}</ul>"})

    if an:
        r = an["resumo"]
        dirc = an.get("direcionamento", {})
        linhas = [
            ("Triagem consolidada", f"{r['faixa']} (score {r['score']})"),
            ("Base analisada", html.escape(fonte_corpus)),
            ("Grau de direcionamento", dirc.get("grau_det", "indeterminado")),
            ("Cláusulas restritivas", dirc.get("n_clausulas_restritivas", 0)),
            ("Cascata de inabilitações", "SIM" if dirc.get("cascata") else "não/indeterminado"),
            ("Red flags Lex", ", ".join(a.get("rf", "") for a in an.get("lex", {}).get("achados", [])) or "—"),
        ]
        sinais = "".join(f"<li>{html.escape(s)}</li>" for s in r.get("sinais", []))
        secoes.append({"titulo": "V. Triagem Analítica (motores integrados)", "page_break": True,
            "html": _tabela(linhas) + (f"<p style='margin-top:8px;font-weight:600'>Sinais:</p><ul>{sinais}</ul>" if sinais else "")
                    + f"<p style='font-size:11px;color:#666'>{html.escape(r['ressalva'])}</p>"})
    else:
        secoes.append({"titulo": "V. Triagem Analítica", "html":
            "<p>Texto de edital/contrato ainda não captado em volume suficiente para a triagem "
            "cláusula-a-cláusula. Requer baixar o edital completo (PDF CCPAR) — pendente.</p>"})

    # VI. Lente PPP-específica (red flags de concessão que o pregão não pega) — no texto INTEGRAL
    lente = lente_ppp.analisar_ppp(corpus_full) if corpus_full.strip() else None
    if lente and lente["flags"]:
        linhas_l = [(f"<b>{html.escape(f['tipo'])}</b> · {f['gravidade']}",
                     f"{html.escape(f['verificar'])}"
                     f"<br><span style='font-size:11px;color:#444'><b>Base:</b> {html.escape(f['base_legal'])}</span>"
                     f"<br><span style='font-size:11px;color:#666'><b>Jurisprudência/TC:</b> "
                     f"{html.escape(f.get('jurisprudencia', ''))}</span>")
                    for f in lente["flags"]]
        secoes.append({"titulo": f"VI. Lente PPP — red flags de concessão ({lente['grau']})",
            "html": _tabela(linhas_l)
                    + f"<p style='font-size:11px;color:#666'>{html.escape(lente['ressalva'])}</p>"})

    score = an["resumo"]["score"] if an else 0.0
    return {
        "titulo": f"Dossiê de Fiscalização — {nome}",
        "subtitulo": "PPP / Concessão Administrativa · Prefeitura do Rio de Janeiro",
        "classificacao": "USO INTERNO — CONTROLE EXTERNO",
        "metodologia": "Captação multi-fonte (CCPAR + D.O. Rio) + motores de análise "
                       "(E1–E7, direcionamento, Lex, hipóteses de fraude). Determinístico.",
        "analista": "Núcleo de Fiscalização JFN",
        "score": score, "rotulo_score": "Índice de risco (triagem)",
        "faixa": (an["resumo"]["faixa"] if an else "🟢 baixo"),
        "top_flags": (an["resumo"]["sinais"][:6] if an else []),
        "secoes": secoes,
        "proveniencia": "ccpar.rio (mapa do projeto) · doweb.rio.rj.gov.br (Elasticsearch do D.O.) · "
                        "motores compliance_agent/detectores, direcionamento_sinais, lex, knowledge.",
        "ressalva": "Indício ≠ acusação. INDISPONÍVEL ≠ 0. Números de processo e valores são indícios "
                    "extraídos de texto público; a íntegra do processo (SIGA/SEI) fecha a prova. "
                    "Empenho ≠ liquidação ≠ pagamento (OB).",
        "data": datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y"),
        "_dados": {"slug": slug, "n_atos_do": len(acts), "resultado": resultado},
    }


def gerar(slug: str, *, pdf: bool = False, db_path=None) -> dict:
    ctx = montar_dossie(slug, db_path=db_path)
    saida = {"slug": slug, "score": ctx["score"], "faixa": ctx["faixa"],
             "n_secoes": len(ctx["secoes"])}
    if pdf:
        import asyncio
        saida["pdf"] = asyncio.run(rh.gerar_pdf(ctx, f"dossie_ppp_{slug}"))
    else:
        html_str = rh.render_html(ctx)
        out = f"output/dossie_ppp_{slug}.html"
        import os
        os.makedirs("output", exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html_str)
        saida["html"] = out
    return saida


def main() -> None:
    ap = argparse.ArgumentParser(description="Dossiê de PPP municipal (CCPAR + D.O. + análise).")
    ap.add_argument("slug")
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    print(json.dumps(gerar(a.slug, pdf=a.pdf, db_path=a.db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
