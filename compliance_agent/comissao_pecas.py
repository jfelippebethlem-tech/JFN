# -*- coding: utf-8 -*-
"""Peças da Comissão de Orçamento, Finanças, Fiscalização Financeira e Controle (ALERJ) — catálogo e geradores.

Base: pesquisa de 13/11/2026 (Regimento Interno da ALERJ art. 26 §2º a–j; CE-RJ; LRF; SICONFI testado).
O catálogo lista as 18 peças (P1–P18) com base legal e prazo; as que têm fonte de dado estruturada ganham
GERADOR (PDF no padrão da casa: render_html → chromium). As outras dizem o que falta — nada é inventado.

Fontes: SICONFI (`siconfi_rgf`/`siconfi_rreo`, autodeclarado pelo ente — a peça manda conferir com o RGF publicado),
painéis da CGE e TFE do portal de dados abertos (`dadosabertos_rj.db`), perícia de fornecedor (`comissao_orcamento`).
"""
from __future__ import annotations

import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DB_ABERTOS = RAIZ / "data" / "dadosabertos_rj.db"
RPT = RAIZ / "reports"

NC = "[NÃO CONFIRMADO na fonte primária]"

# ── catálogo (P1–P18) ── `gerador` = id da função abaixo; None = depende de fonte que ainda não temos.
CATALOGO = [
    {"id": "P1", "titulo": "Parecer à PLDO (projeto e emendas)", "base": "CE-RJ art. 210 §§1º–2º; RI art. 26 §2º c; LRF art. 4º",
     "prazo": f"Aprovação antes do recesso de 30/06 (CE art. 107 §2º); envio pelo Executivo {NC}", "gerador": None,
     "falta": "texto do projeto de LDO (anexos de metas e riscos fiscais)"},
    {"id": "P2", "titulo": "Parecer à PLOA (pareceres prévios por órgão e às emendas)", "base": "CE-RJ art. 210 §§1º–3º e §8º; RI art. 26 §2º c; LRF art. 5º",
     "prazo": "Envio na prática até 30/09 (cronograma Seplag); aprovação até 31/12 (fim da sessão legislativa)", "gerador": None,
     "falta": "texto do projeto de LOA por órgão"},
    {"id": "P3", "titulo": "Parecer ao PPA e às revisões", "base": "CE-RJ arts. 209 §1º e 210; RI art. 26 §2º c",
     "prazo": f"Tramita junto com a PLOA (out./nov.) {NC}", "gerador": None, "falta": "texto do PPA"},
    {"id": "P4", "titulo": "Parecer às emendas parlamentares (inclusive impositivas)", "base": "CE-RJ art. 210 §§2º–3º; EC 97/2023",
     "prazo": "Janela de ~5 dias úteis após a leitura da PLOA", "gerador": None, "falta": "emendas estaduais (sem fonte estruturada)"},
    {"id": "P5", "titulo": "Parecer a projeto de crédito suplementar ou especial", "base": "CE-RJ arts. 210 e 211 V–VI; Lei 4.320 arts. 40–46",
     "prazo": "Por projeto", "gerador": None, "falta": "texto do projeto de lei"},
    {"id": "P6", "titulo": "Parecer às contas anuais do Governador", "base": "CE-RJ arts. 99 VIII, 123 I, 145 XIII; RI art. 26 §2º b; LRF arts. 56–57",
     "prazo": "Entrega em 60 dias da abertura da sessão (~1º/04); parecer prévio do TCE em 60 dias", "gerador": None,
     "falta": "parecer prévio do TCE-RJ (PDF, sem API)"},
    {"id": "P7", "titulo": "Tomada de contas do Governador", "base": "CE-RJ art. 99 VIII; RI art. 26 §2º a",
     "prazo": "Se as contas não forem apresentadas em 60 dias da abertura da sessão", "gerador": None, "falta": "—"},
    {"id": "P8", "titulo": "Parecer às contas anuais do TCE-RJ", "base": "CE-RJ art. 131; LRF art. 56 §2º (ver ADI 2324)",
     "prazo": "TCE presta em 60 dias da abertura da sessão", "gerador": None, "falta": "prestação de contas do TCE-RJ"},
    {"id": "P9", "titulo": "Exame dos relatórios de atividades do TCE-RJ", "base": "CE-RJ art. 123 §4º; RI art. 26 §2º g",
     "prazo": "Trimestral e anual", "gerador": None, "falta": "relatórios do TCE (PDF)"},
    {"id": "P10", "titulo": "Subsídio à audiência pública quadrimestral de metas fiscais", "base": "LRF art. 9º §4º; CE-RJ art. 109 §2º II",
     "prazo": "Até o fim de maio, setembro e fevereiro", "gerador": "audiencia_quadrimestral"},
    {"id": "P11", "titulo": "Nota de acompanhamento do RGF por Poder e órgão", "base": "LRF arts. 20, 22, 54–55 e 59",
     "prazo": "RGF publicado até 30/05, 30/09 e 30/01", "gerador": "nota_rgf"},
    {"id": "P12", "titulo": "Nota de acompanhamento do RREO", "base": "CE-RJ art. 209 §3º; LRF arts. 52–53",
     "prazo": "Bimestral, até 30 dias após o bimestre", "gerador": "nota_rreo"},
    {"id": "P13", "titulo": "Relatório de fiscalização — fornecedores com indício, órgão a órgão (base de requerimentos)",
     "base": "RI art. 26 VII e §2º h; CE-RJ art. 123 VI", "prazo": "Livre", "gerador": "fiscalizacao_orgaos"},
    {"id": "P14", "titulo": "Pedido de esclarecimento por despesa não autorizada (art. 127)", "base": "CE-RJ art. 127",
     "prazo": "5 dias; depois parecer do TCE em 30 dias", "gerador": None, "falta": "caso concreto (parte do P13)"},
    {"id": "P15", "titulo": "Convocação de Secretário de Estado", "base": "CE-RJ arts. 100 e 109 §2º III; RI art. 26 III",
     "prazo": "Livre", "gerador": None, "falta": "decisão da Comissão"},
    {"id": "P16", "titulo": "Representação/recurso contra decisão do TCE; sustação de contrato", "base": "CE-RJ art. 123 §§1º–2º; RI art. 26 §2º f",
     "prazo": "Por caso; 90 dias para efetivar a sustação", "gerador": None, "falta": "caso concreto"},
    {"id": "P17", "titulo": "Parecer sobre operações de crédito e subsídios", "base": "RI art. 26 §2º j; CE-RJ art. 210 §8º",
     "prazo": "Por projeto", "gerador": None, "falta": "texto do projeto"},
    {"id": "P18", "titulo": "Monitor de duodécimos (repasses até o dia 20)", "base": "CE-RJ art. 212",
     "prazo": "Mensal", "gerador": None, "falta": "repasses financeiros aos Poderes por mês (MSC/SIAFE)"},
]

CALENDARIO = [
    ("30/01", "RGF do 3º quadrimestre e RREO do 6º bimestre", "P11, P12"),
    ("fim de fevereiro", "Audiência pública LRF do 3º quadrimestre", "P10"),
    ("1º/02 a ~1º/04", "Contas do Governador e do TCE-RJ: entrega em 60 dias da abertura", "P6, P7, P8"),
    ("abril", f"PLDO entra {NC}; TCE tem 60 dias para o parecer prévio", "P1"),
    ("fim de maio", "Audiência LRF do 1º quadrimestre; RGF do 1º quadrimestre (30/05)", "P10, P11"),
    ("até 30/06", "LDO aprovada (CE art. 107 §2º)", "P1"),
    ("junho", "Parecer prévio do TCE às contas do Governador chega à ALERJ", "P6"),
    ("fim de setembro", "Audiência LRF do 2º quadrimestre; RGF (30/09); PLOA e PPA entram (~30/09)", "P10, P11, P2, P3"),
    ("out./nov.", "Emendas (~5 dias úteis), pareceres prévios, parecer às emendas", "P2, P4"),
    ("até 31/12", "LOA aprovada antes do fim da sessão legislativa", "P2"),
    ("bimestral", "RREO", "P12"),
    ("trimestral", "Relatório de atividades do TCE-RJ", "P9"),
    ("contínuo", "Créditos adicionais, requerimentos, art. 127, duodécimos", "P5, P13–P18"),
]

INSTITUICAO_CURTA = {"Governo do Estado": "Executivo", "Assembleia Legislativa": "ALERJ", "Tribunal de Contas": "TCE-RJ",
                     "Tribunal de Justiça": "TJRJ", "Ministério Público": "MPRJ", "Ministerio Publico": "MPRJ",
                     "Defensoria": "Defensoria (DPRJ)"}


def curta(inst: str) -> str:
    for k, v in INSTITUICAO_CURTA.items():
        if k.lower() in (inst or "").lower():
            return v
    return inst or "—"


def brl(x) -> str:
    return "—" if x is None else f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x) -> str:
    return "—" if x is None else f"{x:,.2f}%".replace(",", "X").replace(".", ",").replace("X", ".")


def _ro() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_ABERTOS}?mode=ro", uri=True, timeout=30)


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tabela(cab: list, linhas: list) -> str:
    h = "".join(f"<th>{_esc(c)}</th>" for c in cab)
    b = "".join("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in ln) + "</tr>" for ln in linhas)
    return f"<table><tr>{h}</tr>{b}</table>"


# ── leitura do SICONFI ──
def ultimo_periodo_rgf(c) -> tuple[int, int] | None:
    r = c.execute("SELECT exercicio, periodo FROM siconfi_rgf WHERE anexo='RGF-Anexo 01' "
                  "ORDER BY exercicio DESC, periodo DESC LIMIT 1").fetchone()
    return (int(r[0]), int(r[1])) if r else None


def pessoal(c, exercicio: int, periodo: int) -> list[dict]:
    """Despesa total com pessoal × RCL ajustada × limites, por instituição (RGF Anexo 01)."""
    out: dict[str, dict] = {}
    for inst, coluna, conta, valor in c.execute(
            "SELECT instituicao, coluna, conta, valor FROM siconfi_rgf WHERE anexo='RGF-Anexo 01' AND exercicio=? "
            "AND periodo=?", (exercicio, periodo)):
        d = out.setdefault(inst, {"instituicao": inst, "curta": curta(inst)})
        cu, co = (conta or "").upper(), (coluna or "").upper()
        campo = None
        if cu.startswith("DESPESA TOTAL COM PESSOAL"):
            campo = "dtp"
        elif cu.startswith("LIMITE MÁXIMO"):
            campo = "lim_max"
        elif cu.startswith("LIMITE PRUDENCIAL"):
            campo = "lim_prud"
        elif cu.startswith("LIMITE DE ALERTA"):
            campo = "lim_alerta"
        elif "AJUSTADA PARA CÁLCULO DOS LIMITES DA DESPES" in cu:
            campo = "rcl_aj"
        elif cu.startswith("DESPESA LÍQUIDA COM PESSOAL") or cu.startswith("DESPESA LIQUIDA COM PESSOAL"):
            if not co.startswith("TOTAL (C"):      # Defensoria publica mês a mês; o total é "TOTAL (c = a + b)"
                continue
            campo = "liquida"
        elif cu.startswith("DESPESA BRUTA COM PESSOAL") and co.startswith("TOTAL (C"):
            campo = "bruta"
        elif cu.startswith("DESPESAS NÃO COMPUTADAS") and co.startswith("TOTAL (C"):
            campo = "nao_computadas"
        if not campo:
            continue
        d[campo + ("_pct" if "%" in co else "")] = valor
    # Defensoria (sem limite próprio no art. 20): despesa líquida = bruta − não computadas; % sobre a RCL ajustada
    # do ESTADO, só como referência de tamanho.
    rcl_aj = next((d.get("rcl_aj") for d in out.values() if d.get("rcl_aj")), None)
    for d in out.values():
        if d.get("dtp") is None:
            liq = d.get("liquida")
            if liq is None and d.get("bruta") is not None:
                liq = d["bruta"] - (d.get("nao_computadas") or 0)
            if liq is not None:
                d["dtp"] = liq
                d["dtp_pct"] = round(100 * liq / rcl_aj, 2) if rcl_aj else None
    res = []
    for d in out.values():
        p, lm, lp, la = d.get("dtp_pct"), d.get("lim_max_pct"), d.get("lim_prud_pct"), d.get("lim_alerta_pct")
        if "Defensoria" in d["curta"]:
            d["situacao"] = "sem limite LRF próprio (% só referência)"
        elif p is None or lm is None:
            d["situacao"] = "sem dado"
        elif p > lm:
            d["situacao"] = "ACIMA DO LIMITE MÁXIMO"
        elif lp is not None and p > lp:
            d["situacao"] = "acima do limite prudencial"
        elif la is not None and p > la:
            d["situacao"] = "acima do limite de alerta"
        else:
            d["situacao"] = "dentro dos limites"
        res.append(d)
    ordem = ["Executivo", "ALERJ", "TCE-RJ", "TJRJ", "MPRJ", "Defensoria (DPRJ)"]
    return sorted(res, key=lambda d: ordem.index(d["curta"]) if d["curta"] in ordem else 99)


def serie_pessoal(c) -> list[tuple]:
    """(exercicio, periodo, curta, dtp_pct) para a evolução."""
    out = []
    for ex, per in c.execute("SELECT DISTINCT exercicio, periodo FROM siconfi_rgf WHERE anexo='RGF-Anexo 01' "
                             "ORDER BY 1, 2").fetchall():
        for d in pessoal(c, ex, per):
            if d.get("dtp_pct") is not None:
                out.append((ex, per, d["curta"], d["dtp_pct"]))
    return out


def divida(c, exercicio: int, periodo: int) -> dict:
    """DCL e % da DCL sobre a RCL ajustada do Executivo (RGF Anexo 02, coluna 'Até o Nº Quadrimestre')."""
    alvo = f"ATÉ O {periodo}º QUADRIMESTRE"
    d: dict = {}
    for coluna, conta, valor in c.execute(
            "SELECT coluna, conta, valor FROM siconfi_rgf WHERE anexo='RGF-Anexo 02' AND co_poder='E' AND exercicio=? "
            "AND periodo=?", (exercicio, periodo)):
        if (coluna or "").upper() != alvo:
            continue
        cu = (conta or "").upper()
        if cu.startswith("DÍVIDA CONSOLIDADA LÍQUIDA"):
            d["dcl"] = valor
        elif cu.startswith("% DA DCL SOBRE A RCL"):
            d["dcl_pct"] = valor
        elif cu.startswith("LIMITE DEFINIDO POR RESOLUÇÃO DO SENADO"):
            d["limite"] = valor
        elif cu.startswith("RECEITA CORRENTE LÍQUIDA - RCL"):
            d["rcl"] = valor
    return d


# ── geração de PDF ──
def _pdf(ctx: dict, nome: str) -> Path | None:
    from compliance_agent.reporting.render_html import render_html
    RPT.mkdir(exist_ok=True)
    hp, pp = RPT / f"{nome}.html", RPT / f"{nome}.pdf"
    hp.write_text(render_html(ctx))
    subprocess.run(["chromium", "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pp}", f"file://{hp}"], capture_output=True, timeout=240)
    return pp if pp.exists() and pp.stat().st_size > 0 else None


def _ctx(titulo: str, subtitulo: str, metodologia: str, secoes: list, flags: list, proven: list, ressalva: str) -> dict:
    return {"classificacao": "USO DA COMISSÃO — ALERJ", "titulo": titulo, "subtitulo": subtitulo,
            "data": datetime.now().strftime("%d/%m/%Y"),
            "analista": "Comissão de Orçamento, Finanças, Fiscalização Financeira e Controle — apoio técnico (JFN)",
            "metodologia": metodologia, "score": 0, "faixa": "BAIXO", "top_flags": flags, "secoes": secoes,
            "proveniencia": proven, "ressalva": ressalva, "sem_indice": True}


_RESSALVA_SICONFI = ("Dados do SICONFI são AUTODECLARADOS pelo ente; conferir com o RGF/RREO publicado e com os alertas "
                     "do TCE-RJ (LRF art. 59 §1º) antes de citar em peça oficial. O Estado do RJ está no Regime de "
                     "Recuperação Fiscal (LC 159/2017), que altera consequências de limites de endividamento.")


def nota_rgf() -> Path | None:
    c = _ro()
    try:
        up = ultimo_periodo_rgf(c)
        if not up:
            return None
        ex, per = up
        pes = pessoal(c, ex, per)
        dv = divida(c, ex, per)
        serie = serie_pessoal(c)
    finally:
        c.close()
    linhas = [[d["curta"], brl(d.get("dtp")), pct(d.get("dtp_pct")), pct(d.get("lim_alerta_pct")),
               pct(d.get("lim_prud_pct")), pct(d.get("lim_max_pct")), d["situacao"]] for d in pes]
    sec = [{"titulo": f"1. Despesa com pessoal por Poder e órgão — {per}º quadrimestre de {ex} (RGF Anexo 01)",
            "html": tabela(["Instituição", "Despesa total com pessoal", "% RCL ajustada", "Alerta", "Prudencial",
                            "Máximo", "Situação"], linhas)
            + "<p>Limites do art. 20 da LRF por Poder (Executivo 49%; Legislativo 3%, repartido entre ALERJ e TCE-RJ; "
              "Judiciário 6%; Ministério Público 2%). Prudencial = 95% do máximo (art. 22, parágrafo único: vedações); "
              "alerta = 90% (art. 59 §1º II). A Defensoria não tem limite próprio no art. 20.</p>"}]
    if dv:
        excede = dv.get("dcl_pct") is not None and dv["dcl_pct"] > 200
        sec.append({"titulo": "2. Dívida consolidada líquida do Estado (RGF Anexo 02)", "html": tabela(
            ["Indicador", "Valor"], [["Dívida consolidada líquida (DCL)", brl(dv.get("dcl"))],
                                     ["Receita corrente líquida (RCL)", brl(dv.get("rcl"))],
                                     ["DCL / RCL ajustada", pct(dv.get("dcl_pct"))],
                                     ["Limite (Resolução do Senado nº 40/2001)", "200,00% — " + brl(dv.get("limite"))]])
            + ("<p><b>A DCL está acima do limite de 200% da RCL.</b> O Estado está no Regime de Recuperação Fiscal "
               "(LC 159/2017), que suspende ou altera efeitos do limite durante o plano — conferir as condições "
               "vigentes do plano antes de qualificar o fato.</p>" if excede else "")})
    evol: dict[str, list] = {}
    for e, p, cu, v in serie:
        evol.setdefault(cu, []).append((f"{p}Q/{e}", v))
    if evol:
        per_cols = sorted({k for v in evol.values() for k, _ in v}, key=lambda s: (s.split("/")[1], s[0]))[-6:]
        ls = [[cu] + [pct(dict(v).get(k)) for k in per_cols] for cu, v in evol.items()]
        sec.append({"titulo": "3. Evolução da despesa com pessoal (% da RCL ajustada)",
                    "html": tabela(["Instituição"] + per_cols, ls)})
    flags = [f"{d['curta']}: {pct(d.get('dtp_pct'))} da RCL — {d['situacao']}" for d in pes
             if d["situacao"] not in ("dentro dos limites", "sem dado")]
    if dv.get("dcl_pct") is not None:
        flags.append(f"DCL/RCL: {pct(dv['dcl_pct'])} (limite 200%)")
    ctx = _ctx(f"Nota de acompanhamento do RGF — {per}º quadrimestre de {ex}",
               "Despesa com pessoal por Poder e órgão, dívida consolidada · LRF arts. 20, 22, 54–55 e 59",
               "SICONFI/Tesouro (RGF Anexos 01 e 02 por Poder: Executivo, ALERJ, TCE-RJ, TJRJ, MPRJ, Defensoria)",
               sec, flags or ["Todos os Poderes dentro dos limites de pessoal no período"],
               [{"dado": f"RGF {per}º quadrimestre/{ex}", "estado": "REAL", "fonte": "SICONFI (apidatalake.tesouro.gov.br)",
                 "data": datetime.now().strftime("%d/%m/%Y")}], _RESSALVA_SICONFI)
    return _pdf(ctx, f"comissao_P11_rgf_{ex}_{per}Q")


def _v(c, ex: int, per: int, anexo: str, conta: str, coluna: str):
    """Primeiro valor da linha (prefixo de conta) × coluna (prefixo), sem diferenciar maiúsculas."""
    # comparação no PYTHON: o UPPER() do SQLite não converte letra acentuada ("Até" ≠ "ATÉ") e a linha sumia.
    cu, ku = conta.upper(), coluna.upper()
    for cta, col, valor in c.execute("SELECT conta, coluna, valor FROM siconfi_rreo WHERE exercicio=? AND periodo=? "
                                     "AND anexo=? ORDER BY rowid", (ex, per, anexo)):
        if (cta or "").upper().startswith(cu) and (col or "").upper().startswith(ku):
            return valor
    return None


def rreo_resumo(c, ex: int, per: int) -> dict:
    a1, a3, a6 = "RREO-Anexo 01", "RREO-Anexo 03", "RREO-Anexo 06"
    rec, desp = "RECEITAS (EXCETO INTRA-ORÇAMENTÁRIAS)", "DESPESAS (EXCETO INTRA-ORÇAMENTÁRIAS)"
    d = {"rec_prev": _v(c, ex, per, a1, rec, "PREVISÃO ATUALIZADA"), "rec_real": _v(c, ex, per, a1, rec, "Até o Bimestre"),
         "desp_dot": _v(c, ex, per, a1, desp, "DOTAÇÃO ATUALIZADA"),
         "desp_emp": _v(c, ex, per, a1, desp, "DESPESAS EMPENHADAS ATÉ"),
         "desp_liq": _v(c, ex, per, a1, desp, "DESPESAS LIQUIDADAS ATÉ"),
         "desp_pag": _v(c, ex, per, a1, desp, "DESPESAS PAGAS ATÉ"),
         "rcl_12m": _v(c, ex, per, a3, "RECEITA CORRENTE LÍQUIDA (III)", "TOTAL (ÚLTIMOS 12 MESES)"),
         "rcl_prev": _v(c, ex, per, a3, "RECEITA CORRENTE LÍQUIDA (III)", "PREVISÃO ATUALIZADA")}
    d["resultados"] = [(conta, valor) for conta, valor in c.execute(
        "SELECT conta, valor FROM siconfi_rreo WHERE exercicio=? AND periodo=? AND anexo=? AND "
        "(conta LIKE 'RESULTADO PRIM%' OR conta LIKE 'RESULTADO NOMINAL%' OR conta LIKE 'Meta%' OR conta LIKE 'META%') "
        "AND UPPER(coluna) IN ('VALOR','VALOR CORRENTE') ORDER BY rowid", (ex, per, a6))]
    return d


def nota_rreo() -> Path | None:
    """Receita × previsão, despesa por estágio, RCL e resultados primário/nominal × meta da LDO (último bimestre)."""
    c = _ro()
    try:
        r = c.execute("SELECT exercicio, periodo FROM siconfi_rreo WHERE anexo='RREO-Anexo 01' "
                      "ORDER BY exercicio DESC, periodo DESC LIMIT 1").fetchone()
        if not r:
            return None
        ex, per = int(r[0]), int(r[1])
        d = rreo_resumo(c, ex, per)
    finally:
        c.close()
    rp = (100 * d["rec_real"] / d["rec_prev"]) if d.get("rec_real") and d.get("rec_prev") else None
    ideal = 100 * per / 6
    sec = [
        {"titulo": f"1. Receita — até o {per}º bimestre de {ex} (exceto intraorçamentária)", "html": tabela(
            ["Previsão atualizada", "Realizada até o bimestre", "% realizado", "Proporção do ano decorrida"],
            [[brl(d.get("rec_prev")), brl(d.get("rec_real")), pct(rp), pct(ideal)]])
            + "<p>Realização abaixo da proporção do ano decorrida pode indicar frustração de receita (LRF art. 9º: "
              "limitação de empenho). A sazonalidade da arrecadação deve ser considerada.</p>"},
        {"titulo": "2. Despesa por estágio — empenho ≠ liquidação ≠ pagamento", "html": tabela(
            ["Dotação atualizada", "Empenhada", "Liquidada", "Paga"],
            [[brl(d.get("desp_dot")), brl(d.get("desp_emp")), brl(d.get("desp_liq")), brl(d.get("desp_pag"))]])},
        {"titulo": "3. Receita corrente líquida (RREO Anexo 03)", "html": tabela(
            ["RCL — últimos 12 meses", f"RCL — previsão atualizada {ex}"], [[brl(d.get("rcl_12m")), brl(d.get("rcl_prev"))]])},
        {"titulo": "4. Resultados primário e nominal × metas da LDO (RREO Anexo 06)", "html": tabela(
            ["Linha", "Valor"], [[conta[:110], brl(v)] for conta, v in d["resultados"]])
            + "<p>As metas da LDO aparecem na ordem do demonstrativo (primário, depois nominal).</p>"},
    ]
    flags = [f"Receita realizada: {pct(rp)} da previsão com {pct(ideal)} do ano decorrido",
             f"RCL 12 meses: {brl(d.get('rcl_12m'))}", f"Despesa paga até o bimestre: {brl(d.get('desp_pag'))}"]
    ctx = _ctx(f"Nota de acompanhamento do RREO — {per}º bimestre de {ex}",
               "Receita, despesa por estágio, RCL e resultados × metas · LRF arts. 52–53; CE-RJ art. 209 §3º",
               "SICONFI/Tesouro (RREO Anexos 01, 03 e 06 — ente consolidado)", sec, flags,
               [{"dado": f"RREO {per}º bimestre/{ex}", "estado": "REAL", "fonte": "SICONFI",
                 "data": datetime.now().strftime("%d/%m/%Y")}], _RESSALVA_SICONFI)
    return _pdf(ctx, f"comissao_P12_rreo_{ex}_{per}B")


def audiencia_quadrimestral() -> Path | None:
    """Subsídio à audiência pública de metas fiscais: RGF (pessoal + dívida) + execução do Executivo (CGE)."""
    c = _ro()
    try:
        up = ultimo_periodo_rgf(c)
        if not up:
            return None
        ex, per = up
        pes, dv = pessoal(c, ex, per), divida(c, ex, per)
        try:
            exe = c.execute("SELECT ano, SUM(dotacao_atualizada)/12.0, SUM(despesas_empenhadas), "
                            "SUM(despesas_orcamentarias_pagas) FROM cge_execucao_despesa GROUP BY ano ORDER BY ano").fetchall()
        except sqlite3.OperationalError:
            exe = []
    finally:
        c.close()
    sec = [{"titulo": "1. Despesa com pessoal por Poder (RGF Anexo 01)", "html": tabela(
        ["Instituição", "% RCL ajustada", "Limite máximo", "Situação"],
        [[d["curta"], pct(d.get("dtp_pct")), pct(d.get("lim_max_pct")), d["situacao"]] for d in pes])}]
    if dv:
        sec.append({"titulo": "2. Endividamento (RGF Anexo 02)", "html": tabela(
            ["DCL", "RCL", "DCL/RCL", "Limite"], [[brl(dv.get("dcl")), brl(dv.get("rcl")), pct(dv.get("dcl_pct")), "200,00%"]])})
    if exe:
        sec.append({"titulo": "3. Execução da despesa do Poder Executivo (painel da CGE/SIAFE)", "html": tabela(
            ["Exercício", "Empenhado", "Pago"], [[a, brl(e), brl(p)] for a, _, e, p in exe])
            + "<p>Só o Poder Executivo (sem AGERIO, CEDAE e Imprensa Oficial). O mês corrente da fonte é parcial.</p>"})
    sec.append({"titulo": "4. Perguntas sugeridas à Secretaria de Fazenda", "html": "<ol>" + "".join(
        f"<li>{_esc(q)}</li>" for q in [
            f"Qual a trajetória prevista da despesa com pessoal do Executivo até o fim de {ex}, frente ao limite prudencial?",
            "Que medidas do art. 22, parágrafo único, da LRF estão em vigor, se o limite prudencial foi ultrapassado?",
            "Qual o cumprimento das metas do Plano de Recuperação Fiscal no quadrimestre, e a DCL/RCL projetada?",
            "Qual o estoque de restos a pagar por Poder e o cronograma de pagamento?",
            "Houve frustração de receita frente à LOA? Quais contingenciamentos (art. 9º da LRF) foram feitos?"]) + "</ol>"})
    flags = [f"{d['curta']}: pessoal {pct(d.get('dtp_pct'))} da RCL ({d['situacao']})" for d in pes
             if d["situacao"].startswith("acima") or d["situacao"].startswith("ACIMA")]
    ctx = _ctx(f"Audiência pública de metas fiscais — {per}º quadrimestre de {ex}",
               "Subsídio da Comissão para a avaliação do cumprimento das metas fiscais · LRF art. 9º §4º",
               "SICONFI (RGF por Poder) · painéis da CGE/SIAFE (execução do Executivo)", sec,
               flags or ["Sem extrapolação de limite de pessoal no período"],
               [{"dado": f"RGF {per}º quadr./{ex}", "estado": "REAL", "fonte": "SICONFI", "data": datetime.now().strftime("%d/%m/%Y")},
                {"dado": "Execução do Executivo", "estado": "REAL", "fonte": "CGE-RJ (SIAFE)", "data": datetime.now().strftime("%d/%m/%Y")}],
               _RESSALVA_SICONFI)
    return _pdf(ctx, f"comissao_P10_audiencia_{ex}_{per}Q")


def fiscalizacao_orgaos() -> Path | None:
    """Fornecedores com indício, órgão a órgão — base para requerimento de informação (P13) e art. 127 (P14)."""
    from compliance_agent.comissao_orcamento import montar
    d = montar(25)
    if not d.get("ok"):
        return None
    sec, n = [], 1
    for o in d["orgaos"]:
        if not o["problemas"]:
            continue
        ls = []
        for p in o["problemas"]:
            ach = "; ".join(f"{a.get('titulo') or a.get('codigo')}" for a in p["achados"][:3])
            ls.append([p["fornecedor"] or "—", f"{p.get('tipo_doc', 'CNPJ')} {p['cnpj']}", p["grau"], brl(p["total_pago"]), ach])
        sec.append({"titulo": f"{n}. {o['nome']} — {o['n_problemas']} fornecedor(es) com indício · "
                              f"{brl(o['valor_com_problema'])} de {brl(o['total_pago'])} pagos",
                    "html": tabela(["Fornecedor", "Documento", "Grau", "Pago (OB)", "Indícios"], ls)
                    + (f"<p>Mostrando {len(o['problemas'])} de {o['n_problemas']}, maior valor pago primeiro.</p>"
                       if o["n_problemas"] > len(o["problemas"]) else "")})
        n += 1
    t = d["totais"]
    ctx = _ctx("Fiscalização — fornecedores com indício, órgão a órgão",
               "ALERJ, TCE-RJ, TJRJ, MPRJ, Defensoria e órgãos do Executivo · base para requerimentos de informação",
               "Perícia de fornecedor (SIAFE: OB Contabilizado) · resolução de duplicidade por competência · detectores",
               sec, [f"{t['fornecedores_com_problema']} fornecedores com indício em {t['orgaos']} órgãos",
                     f"Valor exposto (pago a quem tem indício): {brl(t['valor_com_problema'])}"],
               [{"dado": "Perícia e detectores", "estado": "REAL", "fonte": "JFN (SIAFE, SEI, Receita)",
                 "data": datetime.now().strftime("%d/%m/%Y")}], d["ressalva"])
    return _pdf(ctx, f"comissao_P13_fiscalizacao_{datetime.now().date()}")


GERADORES = {"nota_rgf": nota_rgf, "nota_rreo": nota_rreo, "audiencia_quadrimestral": audiencia_quadrimestral,
             "fiscalizacao_orgaos": fiscalizacao_orgaos}


def ultimas_geradas() -> dict[str, str]:
    """id da peça → nome do PDF mais recente em reports/."""
    out = {}
    for p in CATALOGO:
        pref = f"comissao_{p['id']}_"
        arq = sorted(RPT.glob(pref + "*.pdf"), key=lambda f: f.stat().st_mtime) if RPT.exists() else []
        if arq:
            out[p["id"]] = arq[-1].name
    return out


def gerar(pid: str) -> Path | None:
    p = next((x for x in CATALOGO if x["id"] == pid), None)
    if not p or not p.get("gerador"):
        return None
    return GERADORES[p["gerador"]]()
