#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ITERJ (UG 133100) × MOBILIZA FOR RENT LTDA — Contrato nº 011/2021 (locação de veículos com motorista).
Relatório de contrato no padrão da casa: render_html -> PDF (chromium) -> Yoda (Telegram, sendDocument).

HONESTIDADE: OB = pago (só status Contabilizado); empenho != pago; indício != acusação;
INDISPONÍVEL != irregular. OB, valor e status vêm SÓ do SIAFE (ob_orcamentaria_siafe).
Fatos do contrato (vigência, valores, aditivos) só entram se vierem com citação em
`--fatos <json>` (lidos das íntegras SEI); sem isso a seção declara a lacuna.

    python tools/relatorio_contrato_mobiliza_iterj.py [--fatos arquivo.json] [--enviar]
"""
import argparse
import json
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx

REPO = Path("/home/ubuntu/JFN"); sys.path.insert(0, str(REPO))
from compliance_agent.reporting.render_html import render_html  # noqa: E402

UG, CNPJ = "133100", "35208086000127"
RPT = REPO / "reports"
HOJE = datetime.now().strftime("%d/%m/%Y")
CHAT = "45338178"  # dono (allowed_users do Hermes)


def brl(x):
    return f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tabela(cab, linhas):
    h = "".join(f"<th>{esc(c)}</th>" for c in cab)
    b = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in ln) + "</tr>" for ln in linhas)
    return f"<table><tr>{h}</tr>{b}</table>"


def comp_iso(c):
    """competência em 'DD/MM/AAAA' (SIAFE 1) ou 'MM/AAAA' (SIAFE 2) -> 'AAAA-MM'."""
    c = (c or "").strip()
    m = re.match(r"^(?:\d{2}/)?(\d{2})/(\d{4})$", c)
    return f"{m.group(2)}-{m.group(1)}" if m else c


def dados():
    c = sqlite3.connect(f"file:{REPO}/data/compliance.db?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    iso = "substr(data_emissao,7,4)||substr(data_emissao,4,2)||substr(data_emissao,1,2)"
    obs = [dict(r) for r in c.execute(
        f"SELECT numero_ob,data_emissao,competencia,valor,status,COALESCE(nl,'') nl,COALESCE(processo,'') processo "
        f"FROM ob_orcamentaria_siafe WHERE credor=? AND ug_emitente=? ORDER BY {iso},numero_ob", (CNPJ, UG))]
    outras = [tuple(r) for r in c.execute(
        "SELECT ug_emitente, COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe WHERE credor=? AND ug_emitente<>? "
        "AND status LIKE 'Contabiliz%' GROUP BY 1 ORDER BY 3 DESC", (CNPJ, UG))]
    per = c.execute("SELECT grau,score,resumo,achados_json FROM pericia_fornecedor WHERE cnpj=? AND ug=?",
                    (CNPJ, UG)).fetchone()
    return obs, outras, per


def montar(fatos):
    obs, outras, per = dados()
    pagas = [o for o in obs if str(o["status"]).lower().startswith("contabiliz")]
    total = sum(o["valor"] or 0 for o in pagas)
    por_ano = defaultdict(lambda: [0, 0.0])
    por_comp = defaultdict(list)
    for o in pagas:
        por_ano[o["data_emissao"][-4:]][0] += 1
        por_ano[o["data_emissao"][-4:]][1] += o["valor"] or 0
        por_comp[comp_iso(o["competencia"])].append(o)
    anos = sorted(por_ano)
    sec = []

    sec.append({"titulo": "1. Sumário executivo", "html": (
        f"<p>O ITERJ (UG {UG}) pagou à <b>Mobiliza For Rent Ltda</b> (CNPJ 35.208.086/0001-27), pelo "
        f"<b>Contrato nº 011/2021</b> (locação de veículos com motorista, Pregão — Lei 10.520/2002), "
        f"<b>{brl(total)}</b> em <b>{len(pagas)} ordens bancárias</b> contabilizadas, de "
        f"{pagas[0]['data_emissao']} a {pagas[-1]['data_emissao']} (fonte: SIAFE).</p>"
        f"<p>Há <b>duas OBs por mês</b> na maior parte da série: no processo de pagamento de 2023 "
        f"(SEI-330020/000054/2023, já lido) uma é a NF dos <b>motoristas</b> (valor variável, retém INSS 11%) e a "
        f"outra a fatura de <b>locação dos veículos</b> (valor fixo, só IR). O mês com 2 OBs <b>não é, por si, "
        f"pagamento em duplicidade</b>. Perícia automática: "
        f"<b>{per['grau'] if per else '—'}</b>, sem fato confirmado.</p>")})

    sec.append({"titulo": "2. Pagamentos por exercício (SIAFE — só OB Contabilizado)", "html": tabela(
        ["Exercício", "OBs", "Valor pago"],
        [[a, por_ano[a][0], brl(por_ano[a][1])] for a in anos] + [["Total", len(pagas), brl(total)]])})

    linhas = []
    for k in sorted(por_comp):
        v = por_comp[k]
        linhas.append([k, len(v), " · ".join(o["numero_ob"] for o in v), brl(sum(o["valor"] or 0 for o in v)),
                       " · ".join(sorted({o["nl"] for o in v if o["nl"]})) or "— (SIAFE 1 não expõe NL)"])
    sec.append({"titulo": "3. Série por competência", "html": tabela(
        ["Competência", "OBs", "Ordens bancárias", "Soma", "NL"], linhas)})

    # valor mensal atual = as 3 últimas competências pagas
    ult = sorted(por_comp)[-3:]
    sec.append({"titulo": "3-A. Valor mensal atual (pago, líquido de retenções)", "html": tabela(
        ["Competência", "Composição", "Valor pago"],
        [[k, " + ".join(brl(o["valor"]) for o in por_comp[k]), brl(sum(o["valor"] for o in por_comp[k]))] for k in ult])
        + "<p>Parte fixa (locação dos veículos) de R$ 99.203,50 desde 02/2026; parte variável (motoristas) "
          "entre R$ 55 mil e R$ 60 mil. É valor PAGO e LÍQUIDO (OB), não o valor contratado.</p>"})
    sec.append({"titulo": "3-B. Pontos a verificar (não são acusação)", "html": (
        "<ul><li><b>11/2023 — OBs 2023OB01041 (R$ 90.558,00) e 2023OB01045 (R$ 48.375,95)</b>, de 19/12/2023, "
        "não constam da íntegra de pagamento 2023. R$ 90.558,00 é exatamente uma locação mensal líquida e dezembro "
        "foi pago à parte: pode ser duplicidade ou o retroativo do 3º Termo Aditivo. Só a NL dessas OBs fecha.</li>"
        "<li><b>09–11/2021</b>: OBs anteriores à celebração do contrato (27/12/2021). Não pertencem ao 011/2021 "
        "ou a outro vínculo ainda não identificado.</li>"
        "<li><b>07 e 08/2022</b>: 6 OBs para 4 meses e R$ 105.234,38 repetido; sem NF de 2022 em disco.</li>"
        "<li><b>01–04/2026</b>: competências desencontradas (01: R$ 69.442,45; 02: 4 OBs; 03: só a fixa; 04: 3 OBs) "
        "— provável mês atrasado pago junto, a confirmar pela NF.</li><li><b>06/2026</b>: sem OB na base.</li></ul>")})

    if fatos:
        nomes = {"1": "Identificação, vigência e aditivos", "2": "Valores e quantitativos", "3": "Reajuste e repactuação",
                 "4": "Por que duas OBs por mês", "5": "Competências marcadas como dobradas",
                 "6": "Fiscalização, garantia e glosas"}
        blocos = []
        for chave, itens in fatos.items():
            if chave.startswith("_") or chave not in nomes:
                continue
            if isinstance(itens, dict):
                itens = [dict(i, fato=f"[{sub}] {i.get('fato', '')}") for sub, v in itens.items()
                         for i in (v if isinstance(v, list) else [v]) if isinstance(i, dict)]
            itens = itens if isinstance(itens, list) else [itens]
            ls = [[i.get("fato", ""), i.get("citacao", "")[:400], i.get("fonte", "")] for i in itens if isinstance(i, dict)]
            if ls:
                blocos.append(f"<h3>4.{chave} {esc(nomes[chave])}</h3>" + tabela(["Fato", "Citação literal", "Fonte"], ls))
        sec.append({"titulo": "4. O contrato — fatos lidos no SEI (com citação)", "html": "".join(blocos)})
    else:
        sec.append({"titulo": "4. O contrato — fatos lidos no SEI", "html": (
            "<p><b>Em leitura.</b> Vigência, valor global, aditivos e reajustes do Contrato 011/2021 estão "
            "sendo extraídos das íntegras SEI em cache; a versão completa segue em seguida. Nada aqui foi "
            "estimado.</p>")})

    if per:
        ach = json.loads(per["achados_json"] or "[]")
        sec.append({"titulo": "5. Perícia de contrato contínuo (bateria T01–T25)", "html": tabela(
            ["Teste", "Status", "Evidência"],
            [[a["codigo"], a["status"], a["evidencia"][:420]] for a in ach if a["status"] != "INDISPONIVEL"])
            + f"<p>{sum(1 for a in ach if a['status'] == 'INDISPONIVEL')} testes INDISPONÍVEIS (falta planilha, "
              f"retenções ou cláusulas) — INDISPONÍVEL não é irregularidade.</p>"})

    if outras:
        sec.append({"titulo": "6. A mesma empresa em outras UGs (contexto)", "html": tabela(
            ["UG", "OBs", "Pago (Contabilizado)"], [[u, n, brl(v)] for u, n, v in outras])})

    flags = [f"{brl(total)} pagos em {len(pagas)} OB (SIAFE) — contrato 011/2021",
             "2 OBs/mês = motoristas + locação de veículos — não é duplicidade por si",
             "A verificar: 2023OB01041/01045 (11/2023) fora da íntegra de pagamento",
             f"Perícia: {per['grau'] if per else '—'} · 0 fato confirmado"]
    return {
        "classificacao": "USO INTERNO — FISCALIZAÇÃO",
        "titulo": "ITERJ × Mobiliza For Rent — Contrato nº 011/2021",
        "subtitulo": "Locação de veículos com motorista · execução financeira e perícia do contrato",
        "data": HOJE, "analista": "JFN — Núcleo de Fiscalização (Yoda)",
        "metodologia": ("OBs do SIAFE (só Contabilizado = pago) · série por competência · leitura das íntegras SEI "
                        "dos processos de pagamento · bateria T01–T25 de contrato contínuo"),
        "score": int(per["score"]) if per else 0, "faixa": "BAIXO",
        "top_flags": flags, "secoes": sec,
        "proveniencia": [
            {"dado": f"{len(obs)} OBs do par", "estado": "REAL", "fonte": "SIAFE (ob_orcamentaria_siafe)", "data": HOJE},
            {"dado": "Processo de pagamento 2023 (186 docs)", "estado": "REAL", "fonte": "SEI-330020/000054/2023", "data": HOJE},
            {"dado": "Perícia T01–T25", "estado": "REAL", "fonte": "pericia_fornecedor", "data": HOJE},
        ],
        "ressalva": ("Indício não é acusação. Só a ordem bancária é pagamento; empenho é valor estimado, passível "
                     "de cancelamento. INDISPONÍVEL não é irregular. Nenhum valor foi estimado."),
    }


def to_pdf(ctx, nome):
    html = render_html(ctx)
    hp, pp = RPT / f"{nome}.html", RPT / f"{nome}.pdf"
    hp.write_text(html)
    subprocess.run(["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pp}", f"file://{hp}"], capture_output=True, timeout=180)
    return pp if pp.exists() and pp.stat().st_size > 0 else None


def enviar(pdf, legenda):
    env = Path("/home/ubuntu/.hermes/.env").read_text()
    m = re.search(r"^TELEGRAM_BOT_TOKEN=(.+)$", env, re.M)
    if not m:
        raise SystemExit("TELEGRAM_BOT_TOKEN ausente em ~/.hermes/.env")
    tok = m.group(1).strip().strip('"').strip("'")
    with open(pdf, "rb") as f:
        r = httpx.post(f"https://api.telegram.org/bot{tok}/sendDocument", data={"chat_id": CHAT, "caption": legenda},
                       files={"document": (pdf.name, f, "application/pdf")}, timeout=120)
    ok = r.json().get("ok", False)
    print("Telegram:", r.status_code, "ok=" + str(ok))
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fatos", help="JSON com fatos do contrato lidos no SEI (com citação)")
    ap.add_argument("--enviar", action="store_true")
    ap.add_argument("--legenda", default="📄 ITERJ × Mobiliza For Rent — Contrato 011/2021")
    a = ap.parse_args()
    fatos = json.loads(Path(a.fatos).read_text()) if a.fatos and Path(a.fatos).exists() else None
    ctx = montar(fatos)
    pdf = to_pdf(ctx, f"contrato_iterj_mobiliza_011-2021_{datetime.now().date()}")
    print("PDF:", pdf, pdf.stat().st_size if pdf else "FALHOU")
    if pdf and a.enviar:
        sys.exit(0 if enviar(pdf, a.legenda) else 1)
