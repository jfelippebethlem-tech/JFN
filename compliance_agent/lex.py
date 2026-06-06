# -*- coding: utf-8 -*-
"""
LEX — Agente de avaliação jurídica (Direito Administrativo / Controle Externo).

Emite um PARECER fático-jurídico (tomada de contas) sobre a contratação/licitação/pagamentos de um
fornecedor: aplica os red flags do controle externo (TCU/TCE-RJ) aos dados disponíveis (carteira de
pagamentos por OB, concentração, processos SEI correlacionados) e classifica o grau de atenção
(🟢 verde / 🟡 amarelo / 🔴 vermelho), com fundamento legal. Base de conhecimento: `docs/LEX-BASE-JURIDICA.md`.

Princípio (cláusula de honestidade): aponta INDÍCIOS a verificar, sob presunção de legitimidade dos atos
administrativos; NUNCA afirma crime/improbidade/dolo (compete ao TCE-RJ/MP-RJ/Judiciário, após contraditório).

É o 3º documento do `/relatorio` (junto do PDF de inteligência e da planilha). Mesma estética do JFN.
"""
from __future__ import annotations

from pathlib import Path

from compliance_agent.reporting.inteligencia import (
    _REPORTS, _mc, _registrar_fonte, _render_parecer_pdf, _slug, fmt_cnpj, moeda, so_digitos,
)

# Red flags (resumo operacional; detalhe em docs/LEX-BASE-JURIDICA.md)
_RF = {
    "R2": ("Fracionamento de despesa", "Art. 75 §1º Lei 14.133/2021; Art. 23 §§1º-5º Lei 8.666/93"),
    "R3": ("Pesquisa de preços frágil / possível sobrepreço", "Art. 23 Lei 14.133; Acórdão 1875/2021-TCU (cesta de preços)"),
    "R4": ("Sobrepreço / superfaturamento (valores fora de referência)", "Art. 11 III Lei 14.133; Acórdão 2622/2013-TCU (BDI)"),
    "R5": ("Inexigibilidade/dispensa possivelmente indevida", "Art. 74 Lei 14.133 / Art. 25 Lei 8.666; art. 337-E CP"),
    "R7": ("Restrição de competitividade", "Art. 9º I Lei 14.133; Art. 3º §1º Lei 8.666"),
    "R8": ("Concentração de fornecedor / risco de captura (bid rigging)", "Art. 37 CF/88; Art. 36 §3º I 'd' Lei 12.529; ACFE/OCDE"),
    "R9": ("Aditivos sucessivos acima dos limites", "Arts. 125-126 Lei 14.133; Art. 65 §1º Lei 8.666"),
    "R10": ("Liquidação irregular / pagamento atípico (estornos)", "Arts. 62-63 Lei 4.320/64; Decreto 93.872/86 art. 38"),
    "R12": ("Planejamento de fachada (DFD/ETP/TR genéricos)", "Art. 5º e Art. 18 Lei 14.133"),
}


def _sei_do_fornecedor(cnpj: str) -> list[dict]:
    try:
        from compliance_agent.correlacao_sei import processos_de_fornecedor
        return processos_de_fornecedor(cnpj)
    except Exception:
        return []


def _detectar(ctx: dict) -> list[dict]:
    """Detecta indícios a partir dos dados disponíveis. Cada item: {rf, obs, gravidade(1-5)}."""
    p = ctx.get("pagamentos") or {}
    achados = []
    if not p.get("tem_dados"):
        return achados
    hhi = p.get("hhi", {})
    top = hhi.get("top_share", 0) or 0
    org_top = next(iter(p.get("por_orgao_geral", {})), "—")
    # R8 — concentração
    if top >= 60:
        achados.append({"rf": "R8", "grav": 4,
                        "obs": f"{top:.1f}% do valor pago concentrado em um único órgão (**{org_top}**) — "
                               "concentração extrema para um prestador de serviços."})
    elif top >= 40:
        achados.append({"rf": "R8", "grav": 3,
                        "obs": f"Concentração relevante ({top:.1f}%) em **{org_top}**."})
    # crescimento abrupto -> indício de planejamento/captura (R12) + materialidade
    anos = p.get("anos", [])
    if len(anos) >= 2:
        t0 = p["por_ano"][anos[0]]["total"] or 0
        t1 = p["por_ano"][anos[-1]]["total"] or 0
        if t0 > 0 and t1 > t0 * 3:
            achados.append({"rf": "R12", "grav": 3,
                            "obs": f"Crescimento abrupto dos pagamentos de R$ {moeda(t0)} ({anos[0]}) para "
                                   f"R$ {moeda(t1)} ({anos[-1]}) — {((t1-t0)/t0*100):+.0f}%."})
    # R10 — estornos (OB valor zero)
    zeros = sum(1 for a in anos for ln in p["por_ano"][a]["linhas"] if ln["valor"] == 0)
    if zeros >= 3:
        achados.append({"rf": "R10", "grav": 2,
                        "obs": f"{zeros} ordens bancárias de valor R$ 0,00 (estornos/regularizações) — verificar a regularidade da liquidação."})
    # materialidade alta + muitos órgãos sem objeto homogêneo -> R2/R5 a verificar
    if (p.get("total_geral") or 0) >= 50_000_000 and len(p.get("por_orgao_geral", {})) >= 6:
        achados.append({"rf": "R2", "grav": 2,
                        "obs": f"Volume expressivo (R$ {moeda(p['total_geral'])}) pulverizado em {len(p['por_orgao_geral'])} órgãos — "
                               "verificar se há fracionamento ou contratações por dispensa abaixo do teto."})
    # risco corporativo alto -> reforça R8
    if ctx.get("risco") == "ALTO":
        achados.append({"rf": "R8", "grav": 2, "obs": f"Rating de risco corporativo ALTO (score {ctx.get('score')}/100) — diligência sobre quadro societário/vínculos."})
    return achados


def _grau(achados: list, sei: list) -> tuple:
    """(emoji, rótulo, justificativa). VERDE/AMARELO/VERMELHO conforme convergência + gravidade."""
    n = len(achados)
    gmax = max((a["grav"] for a in achados), default=0)
    if n >= 3 and gmax >= 4:
        return "🔴", "VERMELHO", "convergência de 3+ indícios, ao menos um grave — recomenda-se controle externo"
    if n >= 1 and (gmax >= 4 or n >= 2):
        return "🟡", "AMARELO", "indícios pontuais a esclarecer mediante diligência"
    if n >= 1:
        return "🟡", "AMARELO", "indício isolado de baixa gravidade"
    return "🟢", "VERDE", "sem indícios relevantes nos dados disponíveis — presunção de regularidade mantida"


def parecer_md(ctx: dict) -> str:
    cnpj = ctx.get("cnpj", "")
    sei = _sei_do_fornecedor(cnpj)
    achados = _detectar(ctx)
    emoji, rotulo, just = _grau(achados, sei)
    p = ctx.get("pagamentos") or {}
    L = []
    add = L.append

    add(f"# PARECER JURÍDICO PRELIMINAR — {ctx.get('nome','')}")
    add(f"### Lex · Avaliação fático-jurídica de contratação, licitação e pagamentos")
    add("")
    add(f"*Tomada de contas preliminar — Direito Administrativo e Controle Externo (TCU/TCE-RJ)*")
    add("")
    add(f"**CNPJ:** {fmt_cnpj(cnpj)}  |  **Data:** {ctx.get('data','')}  |  **Analista:** Agente Lex (JFN)")
    add(f"**Grau de atenção:** {emoji} **{rotulo}** — {just}.")
    add("")
    add("---")
    add("")

    # I. Identificação
    add("## I. IDENTIFICAÇÃO")
    add("")
    add(f"- **Fornecedor:** {ctx.get('nome','')} (CNPJ {fmt_cnpj(cnpj)})")
    if p.get("tem_dados"):
        add(f"- **Exposição:** R$ {moeda(p['total_geral'])} em {p['n_geral']} OBs, {len(p.get('por_orgao_geral',{}))} órgãos, "
            f"exercícios {', '.join(map(str, p.get('anos', [])))}")
    add(f"- **Processos SEI vinculados (origem das OBs):** {len(sei)} identificado(s) na base correlacionada (SIAFE)")
    add("")

    # II. Fatos
    add("## II. FATOS — processos administrativos a examinar")
    add("")
    if sei:
        add("Cada Ordem Bancária remete a um processo SEI (DFD → ETP → TR/edital → contrato → empenho → liquidação → OB). "
            "Processos vinculados a este fornecedor (insumo para a análise documental):")
        add("")
        add("| Processo SEI | Nº de OBs | Valor pago (R$) |")
        add("|---|---:|---:|")
        for s in sei[:25]:
            add(f"| {s.get('numero_sei')} | {s.get('n_obs')} | {moeda(s.get('total'))} |")
        add("")
    else:
        add("> Ainda não há processos SEI correlacionados a este CNPJ na base (a correlação OB↔SEI vem da coleta SIAFE — "
            "tela OB Orçamentária). **Diligência:** rodar a coleta SIAFE do(s) exercício(s) e a correlação para puxar os processos.")
        add("")

    # III. Análise por red flag
    add("## III. ANÁLISE DE MÉRITO POR INDÍCIO (red flags do controle externo)")
    add("")
    if achados:
        for a in achados:
            nome, fund = _RF.get(a["rf"], (a["rf"], ""))
            add(f"### {a['rf']} — {nome}")
            add(f"- **Observação:** {a['obs']}")
            add(f"- **Fundamento:** {fund}")
            add(f"- **Contraponto (presunção de regularidade):** o fato pode ter explicação legítima (objeto técnico, "
                "demanda concentrada por competência institucional). Não há, aqui, juízo de irregularidade.")
            add(f"- **Diligência sugerida:** abrir os processos SEI vinculados e verificar edital (especificações), "
                "pesquisa de preços, mapa de licitantes/sócios, atestos e aditivos.")
            add("")
    else:
        add("Nenhum indício automático disparou a partir dos dados financeiros disponíveis. A análise documental dos "
            "processos SEI (edital, contrato, pagamento) é a diligência recomendada para confirmação.")
        add("")

    # IV. Matriz P×I
    add("## IV. MATRIZ DE RISCO (P × I — metodologia TCU)")
    add("")
    add("| Indício | P (1-5) | I (1-5) | Score | Faixa |")
    add("|---|---:|---:|---:|---|")
    for a in achados:
        nome = _RF.get(a["rf"], (a["rf"], ""))[0]
        pp = min(5, 2 + a["grav"] // 2); ii = a["grav"]
        sc = pp * ii
        faixa = "Baixo" if sc <= 4 else "Médio" if sc <= 9 else "Alto" if sc <= 14 else "Extremo"
        add(f"| {a['rf']} {nome} | {pp} | {ii} | {sc} | {faixa} |")
    if not achados:
        add("| — | — | — | — | — |")
    add("")

    # V. Conclusão
    add("## V. CONCLUSÃO — GRAU DE ATENÇÃO")
    add("")
    add(f"**{emoji} {rotulo}.** {just[0].upper()+just[1:]}.")
    add("")

    # VI. Recomendações
    add("## VI. RECOMENDAÇÕES DE ENCAMINHAMENTO")
    add("")
    add("- **Diligência documental:** obter, nos processos SEI vinculados, o edital/TR (especificações), a pesquisa "
        "de preços (cesta — Acórdão 1875/2021-TCU), o mapa de licitantes (sócios/endereços) e os atestos/medições.")
    add("- **Controle externo:** havendo indício de dano, representar ao **TCE-RJ** (jurisdição sobre a despesa estadual).")
    add("- **Demais órgãos:** ciência ao **MP-RJ** (improbidade) e ao **CADE** (conluio/bid rigging, Lei 12.529) se cabível; "
        "PAR (Lei 12.846) e ciência à **CGE-RJ** (controle interno).")
    add("")

    # VII. Ressalvas
    add("## VII. RESSALVAS")
    add("")
    add("> 1. Os apontamentos são **INDÍCIOS**, sujeitos a contraditório e ampla defesa. "
        "2. Vigora a **presunção de legitimidade** dos atos administrativos (dúvida sobre economicidade favorece o gestor — "
        "TCE-RJ, Proc. 101.922-9/12). 3. Lex **não afirma crime, improbidade ou dolo** — competência do TCE-RJ, MP-RJ e "
        "Judiciário. 4. Conclusões limitadas aos dados/documentos analisados; lacunas geram **diligência**, não condenação.")
    add("")
    add(f"_Parecer gerado automaticamente pelo Agente Lex (JFN) em {ctx.get('data','')}. "
        "Base jurídica: docs/LEX-BASE-JURIDICA.md. Não substitui parecer jurídico formal._")
    return "\n".join(L)


def render_pdf(ctx: dict, destino: str) -> str:
    """PDF do parecer Lex — mesma estética do JFN (capa azul + texto corrido)."""
    from fpdf import FPDF
    md = parecer_md(ctx)
    achados = _detectar(ctx)
    emoji, rotulo, _ = _grau(achados, _sei_do_fornecedor(ctx.get("cnpj", "")))
    cor = {"VERMELHO": (220, 53, 69), "AMARELO": (255, 150, 0), "VERDE": (40, 167, 69)}.get(rotulo, (90, 90, 90))

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf._fam, pdf._uni = _registrar_fonte(pdf)
    pdf.add_page()

    def _t(s):
        s = s or ""
        if getattr(pdf, "_uni", False):
            return s
        for a, b in (("—", "-"), ("–", "-"), ("·", "-"), ("→", "->"), ("≥", ">="), ("🟢", ""), ("🟡", ""), ("🔴", "")):
            s = s.replace(a, b)
        return s.encode("latin-1", "replace").decode("latin-1")

    pdf.set_fill_color(20, 30, 50); pdf.set_text_color(255, 255, 255); pdf.set_font(pdf._fam, "B", 15)
    pdf.cell(0, 13, _t("PARECER JURÍDICO — AGENTE LEX"), fill=True, ln=True, align="C")
    pdf.set_font(pdf._fam, "", 9); pdf.set_fill_color(45, 60, 90)
    pdf.cell(0, 7, _t("Avaliação fático-jurídica · Direito Administrativo e Controle Externo (TCU/TCE-RJ)"), fill=True, ln=True, align="C")
    pdf.cell(0, 7, _t(f"JFN Intelligence Engine  |  {ctx.get('data','')}"), fill=True, ln=True, align="C")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "B", 14)
    _mc(pdf, 8, _t(ctx.get("nome", "")))
    pdf.set_font(pdf._fam, "", 10); pdf.cell(0, 6, _t(f"CNPJ: {fmt_cnpj(ctx.get('cnpj',''))}"), ln=True)
    pdf.ln(2)
    pdf.set_fill_color(*cor); pdf.set_text_color(255, 255, 255) if rotulo != "AMARELO" else pdf.set_text_color(0, 0, 0)
    pdf.set_font(pdf._fam, "B", 12)
    pdf.cell(0, 9, _t(f"  GRAU DE ATENÇÃO: {rotulo}"), fill=True, ln=True)
    pdf.set_text_color(0, 0, 0); pdf.ln(3)
    # corpo (pula o cabeçalho markdown já renderizado na capa)
    corpo = md.split("---\n\n", 1)[-1]
    _render_parecer_pdf(pdf, _t, corpo)

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(destino)
    return destino


def gerar(ctx: dict, salvar: bool = True) -> dict:
    """Gera o parecer Lex (md + pdf) para o contexto de um fornecedor. Retorna {ok, path_lex_pdf, path_lex_md, grau}."""
    achados = _detectar(ctx)
    emoji, rotulo, _ = _grau(achados, _sei_do_fornecedor(ctx.get("cnpj", "")))
    out = {"ok": True, "grau": rotulo, "n_indicios": len(achados), "path_lex_pdf": "", "path_lex_md": ""}
    if salvar:
        base = f"parecer_lex_{_slug(ctx.get('nome','')) or so_digitos(ctx.get('cnpj',''))}_{ctx.get('data','')}"
        md_path = _REPORTS / f"{base}.md"
        md_path.write_text(parecer_md(ctx), encoding="utf-8")
        out["path_lex_md"] = str(md_path)
        try:
            out["path_lex_pdf"] = render_pdf(ctx, str(_REPORTS / f"{base}.pdf"))
        except Exception as exc:  # noqa: BLE001
            out["_pdf_erro"] = str(exc)[:160]
    return out
