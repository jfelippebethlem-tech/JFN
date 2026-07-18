# -*- coding: utf-8 -*-
"""lex_forense — análise forense QUANTITATIVA dos pagamentos (determinística, sem LLM).

Técnicas clássicas de contabilidade forense aplicadas às OBs do alvo, no padrão da casa
(indício ≠ acusação; INDISPONÍVEL ≠ 0; degrada honesto declarando insuficiência):

- **Lei de Benford** (1º dígito, conformidade por MAD de Nigrini) — desvio é indício
  ESTATÍSTICO fraco isolado; só ganha peso convergindo com outras linhas.
- **Valores redondos** — medição real raramente fecha em milhar exato; estimativa/fatura
  combinada fecha. Contexto importa (tarifas/aluguéis são legitimamente redondos).
- **Sazonalidade ano×mês** — corrida de fim de exercício e padrões de cadência.
- **Cadência por órgão** — regularidade de parcela (serviço contínuo) vs. surtos.
- **Rastreabilidade documental** — % do dinheiro com processo SEI identificado.
- **Linha do tempo forense** — cadastro, sócios, marcos de pagamento em ordem.
- **Cenários discriminantes** — para cada achado, a hipótese benigna, a de risco e o
  DOCUMENTO que decide entre elas (o teste discriminante orienta a diligência).
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict

logger = logging.getLogger(__name__)

_BENFORD_ESPERADO = {d: math.log10(1 + 1 / d) for d in range(1, 10)}
_MIN_BENFORD = 100  # abaixo disso o teste não tem potência — declarar, não calcular


def _brl(v) -> str:
    return f"{(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(v) -> str:
    return f"{v:.1f}".replace(".", ",")


def _linhas(p: dict) -> list[dict]:
    out = []
    for bloco in (p.get("por_ano") or {}).values():
        out.extend(bloco.get("linhas") or [])
    return out


# ─────────────────────────── Benford (1º dígito, MAD Nigrini) ───────────────────────────

def benford(valores: list[float]) -> dict:
    vals = [abs(v) for v in valores if v and abs(v) >= 10]  # <10 não tem 1º dígito estável
    n = len(vals)
    if n < _MIN_BENFORD:
        return {"ok": False, "n": n, "motivo": f"amostra insuficiente ({n} < {_MIN_BENFORD} OBs)"}
    obs = defaultdict(int)
    for v in vals:
        obs[int(str(v).lstrip("0.")[0])] += 1
    dist = {d: obs.get(d, 0) / n for d in range(1, 10)}
    mad = sum(abs(dist[d] - _BENFORD_ESPERADO[d]) for d in range(1, 10)) / 9
    if mad <= 0.006:
        rotulo, leitura = "conformidade próxima", "distribuição típica de dados transacionais orgânicos"
    elif mad <= 0.012:
        rotulo, leitura = "conformidade aceitável", "sem anomalia de dígito relevante"
    elif mad <= 0.015:
        rotulo, leitura = "conformidade marginal", "leve distorção — observar em conjunto com as demais lentes"
    else:
        rotulo, leitura = "NÃO-conformidade", ("distorção de 1º dígito acima do limiar de Nigrini — "
                                               "compatível com valores arbitrados/fracionados (ou com mix "
                                               "legítimo de tarifas fixas); indício estatístico a corroborar")
    pior = max(range(1, 10), key=lambda d: dist[d] - _BENFORD_ESPERADO[d])
    return {"ok": True, "n": n, "mad": mad, "rotulo": rotulo, "leitura": leitura,
            "dist": dist, "pior_digito": pior,
            "pior_excesso": (dist[pior] - _BENFORD_ESPERADO[pior]) * 100}


def redondos(valores: list[float]) -> dict:
    vals = [abs(v) for v in valores if v and abs(v) >= 1000]
    n = len(vals)
    if not n:
        return {"ok": False, "n": 0}
    mil = sum(1 for v in vals if abs(v % 1000) < 0.005)
    cem = sum(1 for v in vals if abs(v % 100) < 0.005)
    return {"ok": True, "n": n, "pct_mil": mil / n * 100, "pct_cem": cem / n * 100, "n_mil": mil}


# ───────────────────────────── sazonalidade e cadência ─────────────────────────────

_MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def sazonalidade(linhas: list[dict]) -> dict:
    m: dict = defaultdict(lambda: defaultdict(float))
    for ln in linhas:
        d = ln.get("data") or ""
        if isinstance(d, str) and len(d) >= 7 and d[4:5] == "-":
            try:
                m[int(d[:4])][int(d[5:7])] += float(ln.get("valor") or 0)
            except ValueError:
                continue
    return dict(m)


def cadencia_por_orgao(linhas: list[dict], top: int = 8) -> list[dict]:
    ag: dict = defaultdict(lambda: {"n": 0, "total": 0.0, "datas": [], "maior": 0.0})
    for ln in linhas:
        o = ln.get("orgao") or "—"
        v = float(ln.get("valor") or 0)
        a = ag[o]
        a["n"] += 1
        a["total"] += v
        a["maior"] = max(a["maior"], v)
        d = ln.get("data") or ""
        if isinstance(d, str) and len(d) >= 7:
            a["datas"].append(d[:7])
    out = []
    for o, a in sorted(ag.items(), key=lambda kv: -kv[1]["total"])[:top]:
        meses = sorted(set(a["datas"]))
        out.append({"orgao": o, "n": a["n"], "total": a["total"], "maior": a["maior"],
                    "primeira": meses[0] if meses else "—", "ultima": meses[-1] if meses else "—",
                    "meses_ativos": len(meses),
                    "media_mes": a["total"] / len(meses) if meses else 0.0})
    return out


def rastreabilidade(sei: list[dict], p: dict) -> dict:
    tot_v = p.get("total_geral") or 0
    tot_n = p.get("n_geral") or 0
    if not tot_n:
        return {"ok": False}
    cob_n = sum(int(s.get("n_obs") or 0) for s in sei or [])
    cob_v = sum(float(s.get("total") or 0) for s in sei or [])
    return {"ok": True, "pct_n": min(100.0, cob_n / tot_n * 100),
            "pct_v": min(100.0, cob_v / tot_v * 100) if tot_v else 0.0,
            "n_proc": len(sei or []), "descoberto_v": max(0.0, tot_v - cob_v)}


# ───────────────────────────── linha do tempo forense ─────────────────────────────

def linha_do_tempo(emp: dict, linhas: list[dict], achados: list[dict]) -> list[tuple[str, str]]:
    ev: list[tuple[str, str]] = []
    if emp.get("data_abertura"):
        ev.append((emp["data_abertura"], "Abertura do CNPJ na Receita Federal"))
    for s in (emp.get("socios") or []):
        if s.get("entrada"):
            ev.append((s["entrada"], f"Entrada de sócio/administrador: {(s.get('nome') or '—')[:40]}"))
    datadas = [(ln.get("data"), float(ln.get("valor") or 0)) for ln in linhas
               if isinstance(ln.get("data"), str) and len(ln.get("data") or "") >= 10]
    if datadas:
        datadas.sort()
        ev.append((datadas[0][0], f"Primeira OB estadual observada (R$ {_brl(datadas[0][1])})"))
        maior = max(datadas, key=lambda t: t[1])
        ev.append((maior[0], f"Maior OB do período (R$ {_brl(maior[1])})"))
        ev.append((datadas[-1][0], f"Última OB observada (R$ {_brl(datadas[-1][1])})"))
    for a in achados:
        if str(a.get("rf")) == "R6":  # troca de controle já carrega a cronologia no obs
            ev.append(("(ver achado R6)", "Troca de controle societário POSTERIOR a receita pública"))
    return sorted(ev, key=lambda t: t[0])


# ───────────────────────── cenários e testes discriminantes ─────────────────────────

_DISCRIMINANTES = {
    "R2": ("parcela fixa prevista em contrato de serviço contínuo",
           "medição forjada/fatura combinada (mesmo valor sem lastro de medição)",
           "contrato + cronograma físico-financeiro e as MEDIÇÕES atestadas: parcela fixa está prevista? "
           "os relatórios de execução variam enquanto o valor não varia?"),
    "R5": ("emergência real, pontual e documentada (ou repasse legítimo a entidade credenciada)",
           "emergência fabricada por desídia para fugir do certame, perpetuada por renovação",
           "data do FATO GERADOR da emergência vs. data do contrato + parecer jurídico da dispensa "
           "(instrução do art. 72 da Lei 14.133/2021) + quantas vezes o mesmo objeto foi 'emergencial'"),
    "R6": ("aquisição societária legítima (M&A) com preço compatível",
           "interposição de pessoas — venda de 'empresa com contratos' a laranjas",
           "alteração contratual arquivada na JUCERJA (preço da cessão de quotas, forma de pagamento) "
           "+ perfil patrimonial dos ingressantes (capacidade econômica de comprar a empresa)"),
    "R7": ("grupo econômico declarado atuando em segmentos distintos",
           "concorrência simulada — o mesmo dono dos dois lados do certame",
           "atas de sessão dos certames COMUNS: os fornecedores do mesmo sócio apresentaram propostas "
           "'concorrentes' entre si? (aí o indício vira quase-prova de simulação)"),
    "R8": ("mercado especializado com poucos players aptos (concentração de mérito)",
           "captura do órgão/rodízio combinado entre fornecedores",
           "atas dos certames: nº de propostas VÁLIDAS, cascata de desclassificações e QSA/endereços "
           "dos derrotados (derrotado-fantasma que nunca vence em lugar nenhum = cartel de cobertura)"),
    "R10": ("regularizações contábeis normais (anulação e reempenho)",
            "ciclo de empenho-estorno para reter dotação ou mascarar liquidação irregular",
            "documentos de anulação no SIAFE (motivo declarado) + cronologia estorno→novo empenho"),
    "R11": ("CNAE secundário compatível não capturado pelo cadastro resumido",
            "empresa de prateleira habilitada para objeto alheio à sua atividade real",
            "cartão CNPJ completo (CNAEs secundários) + acervo/atestados de capacidade técnica (CAT) "
            "apresentados na habilitação"),
    "DD/": ("cadastro/sede desatualizados na Receita",
            "fachada sem operação real no endereço declarado",
            "verificação da sede (imagem/visita), contrato social e quadro de FUNCIONÁRIOS (RAIS/CAGED)"),
}


def cenarios(achados: list[dict], exculpatorio: list[dict]) -> list[dict]:
    exc = {}
    for e in exculpatorio or []:
        exc.setdefault(e.get("rf"), e)
    out = []
    for a in sorted(achados or [], key=lambda x: -(x.get("grav") or 0))[:8]:
        rf = str(a.get("rf") or "")
        chave = "DD/" if rf.startswith("DD/") else rf
        ben, ris, teste = _DISCRIMINANTES.get(chave, (
            "ato regular cuja documentação simplesmente não está na base",
            "irregularidade que a documentação confirmaria",
            "íntegra do processo SEI da contratação (edital/TR, pesquisa de preços, atas, atestos)"))
        e = exc.get(rf)
        if e and e.get("defesa"):
            ben = e["defesa"]
        out.append({"rf": rf, "grav": a.get("grav", 0), "benigno": ben, "risco": ris, "teste": teste,
                    "sobrevive": bool(e and e.get("sobrevive"))})
    return out


# ─────────────────────────────── render (markdown) ───────────────────────────────

def secao_forense_md(ctx: dict, analise: dict) -> str:
    """§II-H — ANÁLISE FORENSE QUANTITATIVA. String vazia quando não há pagamento algum."""
    p = ctx.get("pagamentos") or {}
    linhas = _linhas(p)
    if not linhas:
        return ""
    valores = [float(ln.get("valor") or 0) for ln in linhas]
    L: list[str] = []
    add = L.append
    add("## II-H. ANÁLISE FORENSE QUANTITATIVA (contabilidade forense)")
    add("")
    add("*Técnicas de auditoria forense sobre a série de OBs do alvo. Regra de leitura: cada teste "
        "isolado é RÉGUA, não prova — o valor probatório nasce da convergência (ver Triangulação, IV-B).*")
    add("")

    b = benford(valores)
    add("### Lei de Benford (1º dígito)")
    add("")
    if b.get("ok"):
        add(f"Sobre **{b['n']}** OBs (≥ R$ 10,00): **MAD = {b['mad']:.4f}".replace(".", ",")
            + f"** → **{b['rotulo']}** (limiares de Nigrini: ≤0,006 próxima; ≤0,012 aceitável; "
              "≤0,015 marginal; >0,015 não-conformidade). " + b["leitura"] + ".")
        add("")
        add("| Dígito | Observado | Esperado (Benford) | Desvio |")
        add("|---:|---:|---:|---:|")
        for d in range(1, 10):
            o, e = b["dist"][d] * 100, _BENFORD_ESPERADO[d] * 100
            add(f"| {d} | {_pct(o)}% | {_pct(e)}% | {'+' if o >= e else '−'}{_pct(abs(o - e))} p.p. |")
        add("")
        if b["rotulo"].startswith("NÃO"):
            add(f"> O dígito **{b['pior_digito']}** concentra o maior excesso (+{_pct(b['pior_excesso'])} p.p.). "
                "Investigar a faixa de valor correspondente — fracionamento sob teto de dispensa costuma "
                "estufar dígitos específicos logo abaixo do limite legal.")
            add("")
    else:
        add(f"> Não aplicado: {b.get('motivo')} — o teste perde potência estatística e afirmá-lo seria "
            "fabricar precisão (INDISPONÍVEL ≠ 0).")
        add("")

    r = redondos(valores)
    add("### Valores redondos")
    add("")
    if r.get("ok"):
        add(f"Das **{r['n']}** OBs ≥ R$ 1.000,00: **{_pct(r['pct_mil'])}%** fecham em milhar exato "
            f"({r['n_mil']} OBs) e **{_pct(r['pct_cem'])}%** em centena exata. Medições reais raramente "
            "fecham redondo; estimativas, arbitramentos e faturas combinadas fecham. Tarifas públicas, "
            "aluguéis e parcelas contratuais fixas são exceções LEGÍTIMAS — interpretar junto com o objeto.")
    else:
        add("> Sem OBs ≥ R$ 1.000,00 para o teste.")
    add("")

    saz = sazonalidade(linhas)
    if saz:
        add("### Sazonalidade (valor pago por ano × mês)")
        add("")
        add("| Ano | " + " | ".join(_MESES) + " | Total |")
        add("|---|" + "---:|" * 13)
        for ano in sorted(saz):
            tot = sum(saz[ano].values())
            cels = []
            for m in range(1, 13):
                v = saz[ano].get(m, 0)
                cels.append("—" if not v else ("**" + _brl(v / 1000) + "k**" if v >= 0.25 * tot and tot > 0
                                               else _brl(v / 1000) + "k"))
            add(f"| {ano} | " + " | ".join(cels) + f" | R$ {_brl(tot)} |")
        add("")
        add("*Células em **negrito** concentram ≥25% do ano. Dezembro forte recorrente = corrida de "
            "empenho (conferir liquidação real — arts. 62-63 da Lei 4.320/64).*")
        add("")

    cad = cadencia_por_orgao(linhas)
    if cad:
        add("### Cadência por órgão (regularidade da execução)")
        add("")
        add("| Órgão | OBs | Total (R$) | Meses ativos | Média/mês ativo (R$) | Maior OB (R$) | Janela |")
        add("|---|---:|---:|---:|---:|---:|---|")
        for c in cad:
            add(f"| {c['orgao'][:38]} | {c['n']} | {_brl(c['total'])} | {c['meses_ativos']} | "
                f"{_brl(c['media_mes'])} | {_brl(c['maior'])} | {c['primeira']}→{c['ultima']} |")
        add("")
        add("*Serviço contínuo saudável = muitos meses ativos com média estável. Poucos meses com OBs "
            "gigantes = surto (obra/aquisição pontual ou pagamento acumulado a examinar).*")
        add("")

    ras = rastreabilidade(analise.get("sei") or [], p)
    if ras.get("ok"):
        add("### Rastreabilidade documental (dinheiro × processo)")
        add("")
        add(f"**{_pct(ras['pct_v'])}%** do valor pago tem processo SEI identificado na base correlacionada "
            f"({ras['n_proc']} processo(s); {_pct(ras['pct_n'])}% das OBs). "
            + (f"**R$ {_brl(ras['descoberto_v'])} ainda sem processo rastreado** — zona de sombra a cobrir "
               "via coleta SIAFE (tela OB Orçamentária) antes de qualquer conclusão."
               if ras["descoberto_v"] > 0 else
               "Cobertura documental integral — toda a despesa tem porta de entrada processual conhecida."))
        add("")

    emp = (ctx.get("enriq", {}).get("dados") or {}).get("empresa") or {}
    ev = linha_do_tempo(emp, linhas, analise.get("achados") or [])
    if len(ev) >= 3:
        add("### Linha do tempo forense")
        add("")
        add("| Data | Evento |")
        add("|---|---|")
        for d, e in ev:
            add(f"| {d} | {e} |")
        add("")
        add("*A cronologia é a espinha da prova indiciária: sócio que entra DEPOIS do dinheiro, primeira OB "
            "colada na abertura do CNPJ e picos sem contrato novo são os nós a puxar.*")
        add("")
    return "\n".join(L)


def secao_cenarios_md(analise: dict) -> str:
    """§IV-D.2 — cenários benigno × risco com o TESTE DISCRIMINANTE por achado."""
    cs = cenarios(analise.get("achados") or [], analise.get("exculpatorio") or [])
    if not cs:
        return ""
    L: list[str] = []
    add = L.append
    add("### Cenários e testes discriminantes (o documento que decide)")
    add("")
    add("*Método: para cada achado, a hipótese benigna mais plausível, a hipótese de risco e o teste "
        "que discrimina entre elas — a diligência deixa de ser genérica e vira pedido de documento "
        "específico (arts. 20-21 da LINDB: decidir pelas consequências reais, não pela abstração).*")
    add("")
    add("| Achado | Hipótese benigna | Hipótese de risco | TESTE DISCRIMINANTE |")
    add("|---|---|---|---|")
    for c in cs:
        ben = (c["benigno"] or "").replace("|", "/")
        add(f"| **{c['rf']}** (grav. {c['grav']}/5"
            + (", defesa sobrevive" if c["sobrevive"] else "")
            + f") | {ben[:140]} | {c['risco'][:140]} | {c['teste'][:200]} |")
    add("")
    return "\n".join(L)
