# -*- coding: utf-8 -*-
"""
RELATÓRIO DE INTELIGÊNCIA DE ÓRGÃO — a contrapartida "por órgão" do relatório de fornecedor.

Em vez de "quanto um fornecedor recebeu", responde **"quanto um órgão (Unidade Gestora) pagou, e a
quem"**: total por ano, tabela de OBs individuais por ano, concentração POR FAVORECIDO (quais empresas
mais recebem) + HHI, e top fornecedores. Reaproveita os helpers do módulo de fornecedor (`inteligencia`).

Aceita o órgão por **nome (parcial)** ou **código de UG**. Ex.: "iterj", "bombeiros", "133100".
Se ambíguo, devolve {ambiguo:true, pergunta, candidatos} para o Yoda perguntar ao Mestre Jorge.

USO (CLI):
    cd ~/JFN && .venv/bin/python -m compliance_agent.reporting.inteligencia_orgao "iterj"
    cd ~/JFN && .venv/bin/python -m compliance_agent.reporting.inteligencia_orgao 133100 2025 2026

USO (API): POST /api/relatorio/orgao  {"orgao":"iterj"}  ou  {"ug":"133100"}  [, "anos":[2025,2026]]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import OrderedDict, defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

from compliance_agent import ugs
from compliance_agent.reporting.inteligencia import (
    cabecalho_frescor,
    _DB, _REPORTS, _hhi, _mc, _registrar_fonte, _render_parecer_pdf, _slug,
    _tab_header, _tab_row, fmt_cnpj, moeda, so_digitos,
)


# ───────────────────────────── resolução de órgão ─────────────────────────────

# Siglas comuns de órgãos do ERJ → termo temático que casa o nome canônico (acento não importa).
# Honesto: a sigla só EXPANDE a busca; se casar várias UGs, o Yoda pergunta qual (NÃO consolida).
SIGLAS_ORGAO = {
    "seeduc": "educacao", "see": "educacao",
    "ses": "saude", "sesrj": "saude",
    "sefaz": "fazenda",
    "seplag": "planejamento gestao", "seplan": "planejamento",
    "seap": "administracao penitenciaria",
    "pcerj": "policia civil", "pc": "policia civil",
    "pmerj": "policia militar", "pm": "policia militar",
    "cbmerj": "bombeiros", "funesbom": "corpo de bombeiros",
    "detran": "detran", "detro": "detro",
    "seinfra": "infraestrutura", "seobras": "infraestrutura obras",
    "setur": "turismo",
    "secti": "ciencia tecnologia", "sects": "ciencia tecnologia",
    "secec": "cultura", "secult": "cultura",
    "sedeics": "desenvolvimento economico", "sedeic": "desenvolvimento economico",
    "tjrj": "tribunal justica", "tj": "tribunal justica",
    "tcerj": "tribunal contas", "tce": "tribunal contas",
    "alerj": "assembleia legislativa",
    "pgerj": "procuradoria", "pge": "procuradoria",
    "mprj": "ministerio publico", "mp": "ministerio publico",
    "uerj": "universidade estado", "uenf": "universidade norte fluminense",
    "rioprevidencia": "rioprevidencia", "rioprev": "rioprevidencia",
    "degase": "degase",
}
# tokens genéricos ignorados no casamento (quase toda UG os tem) — preserva os DISTINTIVOS.
_STOP_UG = {"de", "do", "da", "dos", "das", "e", "estado", "rio", "janeiro", "rj", "erj", "governo"}


def _tokens_sig(s: str) -> list[str]:
    """tokens distintivos (sem acento, sem genéricos) — o que de fato identifica o órgão."""
    return [t for t in _sem_acento(s).split() if t and t not in _STOP_UG]


def _todas_ugs(con) -> list[dict]:
    """Todas as UGs com métricas (uma query). Reusado por buscar_orgaos."""
    rows = con.execute(
        "SELECT ug_codigo, MAX(ug_nome) ug_nome, COUNT(*) n, ROUND(SUM(valor),2) total, "
        "COUNT(DISTINCT favorecido_cpf) forn FROM ordens_bancarias "
        "WHERE valor>0 AND ug_codigo IS NOT NULL GROUP BY ug_codigo").fetchall()
    out = []
    for r in rows:
        cod = str(r["ug_codigo"]).strip()
        out.append({"ug": cod, "nome": ugs.nome_canonico(cod, "") or (r["ug_nome"] or f"UG {cod}"),
                    "total_pago": float(r["total"] or 0.0), "n_obs": int(r["n"] or 0),
                    "n_forn": int(r["forn"] or 0), "_raw": r["ug_nome"] or ""})
    return out


def buscar_orgaos(termo: str, limite: int = 8) -> list[dict]:
    """Resolve órgão por CÓDIGO, NOME (parcial, ACENTO-insensível) ou SIGLA (SEEDUC, SEFAZ, TJRJ…).
    Casa quando TODOS os tokens distintivos do termo aparecem no nome (ignora de/estado/rio/janeiro).
    Sem match exato → devolve SUGESTÕES (overlap de tokens, _match='sugestao'). NÃO consolida várias UGs
    (se o termo casar mais de uma, o Yoda pergunta qual). Retorna [{ug,nome,total_pago,n_obs,n_forn,_match}]."""
    termo = (termo or "").strip()
    if not termo or not _DB.exists():
        return []
    cod = "".join(ch for ch in termo if ch.isdigit())
    con = sqlite3.connect(_DB); con.row_factory = sqlite3.Row
    try:
        todas = _todas_ugs(con)
    finally:
        con.close()
    # 1) código exato de UG
    if cod:
        exato = [u for u in todas if u["ug"] == cod]
        if exato:
            for u in exato:
                u["_match"] = "exato"
            return exato[:limite]
    # 2) expande sigla(s): termo-base + expansão temática (se houver)
    base = _sem_acento(termo)
    termos = [base]
    chave = base.replace(" ", "")
    if chave in SIGLAS_ORGAO:
        termos.append(SIGLAS_ORGAO[chave])
    else:
        for sig, exp in SIGLAS_ORGAO.items():
            if sig in base.split():
                termos.append(exp)
    # 3) casamento token-AND (todos os tokens distintivos presentes), por QUALQUER um dos termos
    exatos = []
    for u in todas:
        nome_norm = _sem_acento(u["nome"] + " " + u["_raw"])
        if any(toks and all(t in nome_norm for t in toks) for toks in (_tokens_sig(t) for t in termos)):
            u["_match"] = "exato"
            exatos.append(u)
    if exatos:
        return sorted(exatos, key=lambda c: (c["total_pago"], c["n_obs"]), reverse=True)[:limite]
    # 4) sem match exato → SUGESTÕES por overlap de tokens (OR), ranqueadas por nº de tokens batidos
    alvo_toks = set()
    for t in termos:
        alvo_toks.update(_tokens_sig(t))
    sug = []
    for u in todas:
        nome_norm = _sem_acento(u["nome"] + " " + u["_raw"])
        hits = sum(1 for t in alvo_toks if t in nome_norm)
        if hits:
            u2 = dict(u); u2["_match"] = "sugestao"; u2["_hits"] = hits
            sug.append(u2)
    sug.sort(key=lambda c: (c["_hits"], c["total_pago"]), reverse=True)
    return sug[:limite]


def _sem_acento(s: str) -> str:
    """minúsculas + sem acento (a busca de UG no banco é acento-sensível: 'Justiça' != 'Justica')."""
    import unicodedata
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def listar_ugs(filtro: Optional[str] = None, limite: int = 50) -> dict:
    """Catálogo das UGs (órgãos) das OBs: código + nome canônico + nº de OBs + total pago. É o /UG do Yoda
    — para o Mestre Jorge saber quais códigos/nomes existem e então pedir o /orgao certo. Filtro opcional
    (acento-INsensível) por nome OU código. Honesto: só OBs com valor>0; total = pagamento (OB), nunca empenho."""
    out = {"ok": True, "filtro": filtro or "", "n": 0, "n_total": 0, "ugs": [], "texto": ""}
    if not _DB.exists():
        out["ok"] = False; out["texto"] = "Base local indisponível."; return out
    con = sqlite3.connect(_DB); con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT ug_codigo, MAX(ug_nome) ug_nome, COUNT(*) n, ROUND(SUM(valor),2) total "
            "FROM ordens_bancarias WHERE valor>0 AND ug_codigo IS NOT NULL GROUP BY ug_codigo").fetchall()
    finally:
        con.close()
    itens = []
    for r in rows:
        cod = str(r["ug_codigo"]).strip()
        nome = ugs.nome_canonico(cod, "") or (r["ug_nome"] or f"UG {cod}")
        itens.append({"ug": cod, "nome": nome, "n_obs": int(r["n"] or 0), "total": float(r["total"] or 0.0)})
    out["n_total"] = len(itens)
    if filtro:
        f = _sem_acento(filtro); fdig = "".join(ch for ch in filtro if ch.isdigit())
        itens = [it for it in itens if f in _sem_acento(it["nome"]) or (fdig and fdig in it["ug"])]
    itens.sort(key=lambda it: it["total"], reverse=True)
    itens = itens[:max(1, limite)]
    out["ugs"] = itens; out["n"] = len(itens)
    # texto pronto p/ Telegram (markdown)
    titulo = f"🏛️ *UGs / órgãos* — {out['n']}" + (f" resultado(s) para “{filtro}”" if filtro else f" de {out['n_total']} (top por pagamento)")
    linhas = [titulo, "_Use o **código** no /orgao (ex.: «relatório do órgão 036100»)._", ""]
    for it in itens:
        nobs = f"{it['n_obs']:,}".replace(",", ".")
        linhas.append(f"• `{it['ug']}` — {it['nome']}")
        linhas.append(f"    {nobs} OBs · R$ {moeda(it['total'])}")
    if not filtro and out["n_total"] > out["n"]:
        linhas += ["", f"_…{out['n_total'] - out['n']} UGs a mais. Filtre por nome: «/ug saúde», «/ug tribunal»._"]
    elif filtro and not itens:
        linhas = [f"🏛️ Nenhuma UG encontrada para “{filtro}”. Tente outro termo (acento não importa) ou «/ug» sem filtro."]
    out["texto"] = "\n".join(linhas)
    return out


# ───────────────────────────── consulta ─────────────────────────────

def consultar_orgao(ug: str, anos: Optional[list[int]] = None) -> dict:
    """OBs pagas PELA UG, por ano, com linhas individuais (favorecido) + concentração por favorecido."""
    out = {"tem_dados": False, "ug": ug, "anos": [], "total_geral": 0.0, "n_geral": 0,
           "por_ano": OrderedDict(), "por_favorecido_geral": {}, "hhi": {}, "n_fornecedores": 0}
    if not _DB.exists():
        return out
    con = sqlite3.connect(_DB)
    con.row_factory = sqlite3.Row
    try:
        q = ("SELECT numero_ob, data_pagamento, data_emissao, favorecido_cpf, favorecido_nome, valor, exercicio "
             "FROM ordens_bancarias WHERE ug_codigo=?")
        params: list = [str(ug)]
        if anos:
            q += " AND exercicio IN (%s)" % ",".join("?" * len(anos))
            params += list(anos)
        q += " ORDER BY exercicio, data_pagamento, numero_ob"
        rows = con.execute(q, params).fetchall()
    finally:
        con.close()
    if not rows:
        return out

    por_ano: "OrderedDict[int, dict]" = OrderedDict()
    forn_geral: dict = defaultdict(float)
    forn_cnpjs: set = set()
    for r in rows:
        ano = int(r["exercicio"] or 0)
        bloco = por_ano.setdefault(ano, {"n": 0, "total": 0.0, "linhas": [], "por_favorecido": defaultdict(float)})
        valor = float(r["valor"] or 0.0)
        nome = (r["favorecido_nome"] or "—").strip()
        cnpj = so_digitos(r["favorecido_cpf"] or "")
        forn_cnpjs.add(cnpj)
        data = (r["data_pagamento"] or r["data_emissao"] or "—")
        bloco["n"] += 1
        bloco["total"] += valor
        bloco["por_favorecido"][nome] += valor
        bloco["linhas"].append({"numero_ob": r["numero_ob"] or "—", "data": data,
                                "favorecido": nome, "cnpj": cnpj, "valor": valor})
        forn_geral[nome] += valor

    out["por_ano"] = por_ano
    out["anos"] = sorted(por_ano.keys())
    out["n_geral"] = sum(b["n"] for b in por_ano.values())
    out["total_geral"] = sum(b["total"] for b in por_ano.values())
    out["por_favorecido_geral"] = dict(sorted(forn_geral.items(), key=lambda kv: kv[1], reverse=True))
    out["n_fornecedores"] = len(forn_cnpjs)
    out["hhi"] = _hhi(out["por_favorecido_geral"])
    out["tem_dados"] = True
    return out


# ───────────────────────────── montagem ─────────────────────────────

def montar(orgao: Optional[str] = None, ug: Optional[str] = None,
           anos: Optional[list[int]] = None, salvar: bool = True, so_resolver: bool = False) -> dict:
    termo = (ug or orgao or "").strip()
    cands = buscar_orgaos(termo)
    if not cands:
        return {"ok": False, "erro": f"Não encontrei órgão/UG para {termo!r}. Veja os códigos/nomes com /ug "
                                     f"(ex.: «/ug {termo}») e tente de novo."}
    cod = "".join(ch for ch in termo if ch.isdigit())
    eh_sugestao = cands[0].get("_match") == "sugestao"  # não houve match exato → confirmar mesmo com 1
    if not eh_sugestao and (len(cands) == 1 or (cod and any(c["ug"] == cod for c in cands))):
        escolhido = next((c for c in cands if c["ug"] == cod), cands[0])
    else:
        opcoes = [{"n": i + 1, "ug": c["ug"], "nome": c["nome"], "total_pago": c["total_pago"], "n_obs": c["n_obs"]}
                  for i, c in enumerate(cands)]
        linhas = [f"{o['n']}) {o['nome']} (UG {o['ug']}) — R$ {moeda(o['total_pago'])} em {o['n_obs']} OBs" for o in opcoes]
        cabec = (f"Não achei um órgão exato para \"{termo}\". Você quis dizer:"
                 if eh_sugestao else
                 f"Encontrei {len(opcoes)} órgãos para \"{termo}\". Qual deles, Mestre Jorge?")
        return {"ok": False, "ambiguo": True, "termo": termo, "candidatos": opcoes,
                "pergunta": cabec + "\n" + "\n".join(linhas)
                            + "\n\nResponda com o número ou o código da UG (ou use /ug para ver todos)."}

    ug_cod = escolhido["ug"]
    if so_resolver:  # resolveu sem ambiguidade → endpoint gera em background
        return {"ok": True, "_resolvido": ug_cod, "ug": ug_cod, "orgao": escolhido["nome"]}
    pagamentos = consultar_orgao(ug_cod, anos)
    nome = escolhido["nome"]
    # concentração geográfica dos fornecedores da UG (best-effort, sobre endereços ingeridos)
    try:
        from compliance_agent.cruzamento import cidades_de_orgao
        geo = cidades_de_orgao(ug=ug_cod, anos=anos, limite=15)
    except Exception as exc:  # noqa: BLE001
        geo = {"ok": False, "_nota": str(exc)[:120]}
    ctx = {"ug": ug_cod, "nome": nome, "data": date.today().isoformat(), "pagamentos": pagamentos,
           "alias": ugs.ALIASES.get(ug_cod, {}), "geo": geo}
    # CRUZAMENTOS DE INTELIGÊNCIA (pedido do dono: todos os cruzamentos no relatório):
    #   - DD fachada/laranja + rodízio temporal (cartel) dos maiores fornecedores + processos SEI a priorizar
    #   - realidade do endereço das sedes (as empresas são reais?)
    # Bounded/degrada honesto. Vêm ANTES do raciocínio p/ a IA conectar também esses achados.
    ctx["dd_orgao"] = _dd_orgao_bounded(ug_cod, anos)
    ctx["endereco_real"] = _endereco_real_orgao(ug_cod)
    ctx["raciocinio"] = parecer_raciocinado_orgao(ctx)  # síntese de IA sobre os fatos (degrada honesto)

    md = render_md(ctx)
    path_md = path_pdf = path_xlsx = ""
    if salvar:
        _REPORTS.mkdir(parents=True, exist_ok=True)
        base = f"inteligencia_orgao_{_slug(nome) or ug_cod}_{ctx['data']}"
        path_md = str(_REPORTS / f"{base}.md")
        Path(path_md).write_text(md, encoding="utf-8")
        try:
            path_pdf = render_pdf(ctx, str(_REPORTS / f"{base}.pdf"))
        except Exception as exc:  # noqa: BLE001
            path_pdf = ""
            ctx["_pdf_erro"] = str(exc)[:160]
        try:
            from compliance_agent.reporting import planilha
            path_xlsx = planilha.gerar(ctx, str(_REPORTS / f"{base}.xlsx"), modo="orgao")
        except Exception as exc:  # noqa: BLE001
            path_xlsx = ""
            ctx["_xlsx_erro"] = str(exc)[:160]

    # PARECER LEX DE ÓRGÃO — o /orgao "pensa" como o /relatorio (3º documento, com grau 🟢🟡🔴).
    path_lex = ""
    grau_lex = ""
    if salvar:
        try:
            from compliance_agent import lex
            _lex = lex.gerar_orgao(ctx, salvar=True)
            path_lex = _lex.get("path_lex_pdf", "") or ""
            grau_lex = _lex.get("grau", "") or ""
        except Exception as exc:  # noqa: BLE001
            ctx["_lex_erro"] = str(exc)[:160]

    return {"ok": True, "ug": ug_cod, "orgao": nome, "resumo": _resumo(ctx),
            "path_md": path_md, "path_pdf": path_pdf, "path_xlsx": path_xlsx,
            "path_lex": path_lex, "grau_lex": grau_lex,
            "fonte": "REAL" if pagamentos["tem_dados"] else "SEM_DADOS"}


def gerar(orgao: Optional[str] = None, ug: Optional[str] = None, anos: Optional[list[int]] = None) -> dict:
    return montar(orgao=orgao, ug=ug, anos=anos)


def _fatos_orgao(ctx: dict) -> str:
    """Compila os FATOS de execução do órgão (sem inventar) p/ a análise raciocinada conectar."""
    p = ctx["pagamentos"]
    if not p.get("tem_dados"):
        return "- Sem Ordens Bancárias na base local para esta UG."
    hhi = p["hhi"]
    top_nome, top_val = next(iter(p["por_favorecido_geral"].items()), ("—", 0))
    L = [f"Órgão/UG: {ctx['nome']} (UG {ctx['ug']}).",
         f"Execução financeira (OB): R$ {moeda(p['total_geral'])} em {p['n_geral']} ordens bancárias a "
         f"{len(p['por_favorecido_geral'])} fornecedores.",
         f"Concentração: maior fornecedor '{top_nome}' = {hhi.get('top_share', 0):.1f}% do valor "
         f"(R$ {moeda(top_val)}); HHI {hhi.get('indice')} (nível {hhi.get('nivel')})."]
    grupos = _recorrentes_identicos(p)
    if grupos:
        L.append("Pagamentos recorrentes de valor IDÊNTICO (ACFE identical payments): "
                 f"{len(grupos)} grupo(s) — ex.: "
                 + "; ".join(f"{g['favorecido'][:30]} {g['n']}× R$ {moeda(g['valor'])}" for g in grupos[:3]) + ".")
    geo = ctx.get("geo") or {}
    if geo.get("ok") and geo.get("cidades"):
        c0 = geo["cidades"][0]
        L.append(f"Concentração geográfica dos fornecedores: maior cidade-sede = "
                 f"{c0.get('cidade')}/{c0.get('uf', '')} ({c0.get('pct', 0):.0f}% do valor com endereço ingerido).")
    # cruzamentos de inteligência (DD fachada/laranja + rodízio/cartel + realidade de endereço)
    dd = ctx.get("dd_orgao") or {}
    if dd.get("ok"):
        alvos = dd.get("alvos_prioritarios") or []
        if alvos:
            L.append("Triagem de Due Diligence (fachada/laranja) nos maiores fornecedores PJ: "
                     f"{len(alvos)} com indício de {dd.get('n_avaliados')} avaliados — ex.: "
                     + "; ".join(f"{a['nome'][:28]} {a['grau']} (score {a['score']}, "
                                 f"{', '.join(c.replace('H-', '') for c in a.get('codigos', [])) or 'sem código'})"
                                 for a in alvos[:3]) + ".")
        else:
            L.append(f"Triagem de Due Diligence: {dd.get('n_avaliados')} maiores fornecedores PJ avaliados, "
                     "nenhum com indício nas hipóteses verificáveis (fachada/laranja costuma morar na cauda, "
                     "não no topo por valor).")
        rod = dd.get("rodizio")
        if rod and rod.get("indicio"):
            L.append(f"Rodízio temporal de vencedores (bid rotation / cartel — OCDE): score {rod.get('score')}, "
                     f"{rod.get('n_campeoes')} 'campeões' revezando o 1º lugar em {rod.get('n_anos')} exercícios "
                     f"(dominância do grupo {rod.get('share_ring')}).")
        if dd.get("processos_prioritarios"):
            L.append(f"{len(dd['processos_prioritarios'])} processo(s) SEI a priorizar no sweep "
                     "(correlação OB↔SEI dos fornecedores com indício).")
    er = ctx.get("endereco_real") or {}
    if er.get("ok"):
        L.append(f"Realidade do endereço das sedes (amostra verificada): {er['afastado']} confirmadas reais, "
                 f"{er['indicio']} com indício (possível baldio/precário), {er['indisponivel']} sem conclusão — "
                 f"de {er['n_verificados']} verificadas em {er['n_forn']} fornecedores PJ. "
                 "INDISPONÍVEL não é prova de inexistência (cobertura cartográfica incompleta).")
    return "\n".join("- " + x for x in L)


_SYS_RACIOCINIO_ORGAO = (
    "Você é auditor sênior de controle externo (TCE-RJ/TCU) analisando a EXECUÇÃO de um órgão público. "
    "A partir EXCLUSIVAMENTE dos fatos listados (NÃO invente dados/nomes/fontes; sem conhecimento externo), "
    "escreva uma ANÁLISE RACIOCINADA que CONECTE TODOS os achados disponíveis (concentração em fornecedor, "
    "pagamentos recorrentes idênticos, concentração geográfica, triagem de DUE DILIGENCE de fachada/laranja "
    "nos maiores fornecedores, RODÍZIO TEMPORAL de vencedores/cartel, processos SEI a priorizar e a "
    "VERIFICAÇÃO DE REALIDADE do endereço das sedes): o que chama atenção, COMO os sinais se REFORÇAM entre si "
    "(ex.: fornecedor dominante + rodízio + sede em endereço não confirmado = hipótese mais forte de "
    "direcionamento/cartel), que hipóteses de risco (captura, fracionamento, direcionamento, conluio, "
    "interposição/laranja) merecem apuração e POR QUÊ, e exatamente O QUE verificar (contrato, certame, SEI). "
    "Construa o raciocínio com PROSA densa e específica aos números dados — cite os valores/percentuais/nomes "
    "dos fatos. Linguagem condicional (indício, sugere, merece apuração) — NUNCA afirme irregularidade nem culpa "
    "(presunção de legitimidade). Responda em MARKDOWN com bullets '- ' (NUNCA JSON/cercas). Até ~450 palavras."
)


def parecer_raciocinado_orgao(ctx: dict) -> str:
    """Síntese raciocinada (gemini→cerebras, bounded) sobre os fatos do órgão. '' se LLM indisponível."""
    try:
        fatos = _fatos_orgao(ctx)
        if not fatos.strip() or fatos.startswith("- Sem"):
            return ""
        from compliance_agent.direcionamento_cerebro import gerar_sync
        from compliance_agent.reporting.inteligencia import _normaliza_raciocinio
        txt = _normaliza_raciocinio(gerar_sync("FATOS:\n" + fatos, _SYS_RACIOCINIO_ORGAO, timeout=45.0))
        return txt if len(txt) > 80 else ""
    except Exception:  # noqa: BLE001
        return ""


def parecer_orgao(ctx: dict) -> str:
    """PARECER de mérito e jurídico sobre a EXECUÇÃO do órgão (honesto, indícios a verificar)."""
    p = ctx["pagamentos"]
    if not p["tem_dados"]:
        return "Sem Ordens Bancárias para esta UG na base local — sem base para parecer de mérito."
    nome = ctx["nome"]
    total = p["total_geral"]
    hhi = p["hhi"]
    top_share = hhi.get("top_share", 0)
    top_nome, top_val = next(iter(p["por_favorecido_geral"].items()), ("—", 0))
    L: list[str] = []
    add = L.append

    add("### Análise de mérito")
    add("")
    add(f"A unidade gestora **{nome} (UG {ctx['ug']})** executou **R$ {moeda(total)}** em **{p['n_geral']} "
        f"ordens bancárias** a **{p['n_fornecedores']} fornecedores** no período. O maior recebedor, "
        f"**{top_nome}**, concentra **R$ {moeda(top_val)}** ({(top_val/(total or 1)*100):.1f}% do total), "
        f"com HHI de {hhi.get('indice')} (concentração {hhi.get('nivel').lower()}).")
    add("")
    if top_share >= 50:
        add(f"A concentração de **{top_share:.1f}%** em um único fornecedor é elevada e exige verificar se as "
            "contratações foram **competitivas** ou se houve fracionamento, dispensa/inexigibilidade reiterada "
            "ou direcionamento. Fornecedor dominante em órgão público é *red flag* clássico de cartel/captura.")
    elif top_share >= 30:
        add(f"A concentração de {top_share:.1f}% no maior fornecedor é relevante e merece exame da competitividade "
            "dos certames e do parcelamento do objeto.")
    else:
        add(f"A distribuição entre fornecedores é relativamente pulverizada (maior fatia {top_share:.1f}%), "
            "o que é um sinal positivo de competitividade — sem afastar a checagem dos maiores contratos.")
    add("")
    alias = ctx.get("alias") or {}
    if alias.get("orgao_superior"):
        add(f"**Atenção de classificação:** a UG {ctx['ug']} tem como órgão superior *{alias['orgao_superior']}*; "
            "pagamentos podem aparecer rotulados pelo órgão superior nas OBs. Confirmar a titularidade da "
            "execução evita atribuição equivocada de responsabilidade.")
        add("")

    # Pagamentos recorrentes idênticos — conecta o padrão ao fornecedor dominante (mérito)
    grupos = _recorrentes_identicos(p)
    if grupos:
        g0 = grupos[0]
        add(f"Registra-se **padrão de pagamentos de valor idêntico**: **{g0['favorecido']}** recebeu "
            f"**{g0['n']}×** o valor exato de **R$ {moeda(g0['valor'])}** (R$ {moeda(g0['total'])} no total). "
            "Parcelas fixas são típicas de serviço continuado, mas a reiteração de valores idênticos integra os "
            "*red flags* da ACFE — cabe caracterizar o contrato (objeto, vigência, **medição** da execução) e "
            "verificar se a parcela é justificada e o objeto **adere à finalidade institucional do órgão**.")
        add("")

    add("### Avaliação jurídica")
    add("")
    add("- **CF/88, art. 37** — impessoalidade e moralidade na execução da despesa;")
    add("- **Lei 14.133/2021** — competitividade, vedação a direcionamento (art. 9º/11) e publicidade no PNCP (art. 94);")
    add("- **Lei 8.666/93, art. 23, §1º e art. 89** — vedação a fracionamento para fugir de modalidade;")
    add("- **Lei 4.320/64** — regularidade do empenho→liquidação→pagamento (OB);")
    add("- **TCU/ACFE** — concentração de fornecedor e pagamentos atípicos como indicadores de risco.")
    add("")
    grau = "ALTO" if top_share >= 50 else ("MÉDIO" if top_share >= 30 else "MODERADO")
    add("### Conclusão e grau de atenção")
    add("")
    add(f"**Grau de atenção recomendado: {grau}.** São **indícios a verificar**, não conclusão de "
        "irregularidade. Recomenda-se levantar contratos e processos SEI dos maiores fornecedores, conferir "
        "modalidade licitatória e checar a regularidade fiscal/sancionatória dos recebedores dominantes.")
    add("")
    add("> **Ressalva:** baseado em dados de pagamento (OB) públicos; sem exame documental dos contratos. "
        "Vigora a presunção de regularidade dos atos administrativos até prova em contrário.")
    return "\n".join(L)


def _resumo(ctx: dict) -> str:
    p = ctx["pagamentos"]
    if not p["tem_dados"]:
        return f"{ctx['nome']} (UG {ctx['ug']}): sem OBs registradas na base local."
    anos_txt = ", ".join(f"{a}: R$ {moeda(p['por_ano'][a]['total'])}" for a in p["anos"])
    top = next(iter(p["por_favorecido_geral"].items()), ("—", 0))
    return (f"{ctx['nome']} (UG {ctx['ug']}) — pagamentos {anos_txt}. Total R$ {moeda(p['total_geral'])} "
            f"em {p['n_geral']} OBs a {p['n_fornecedores']} fornecedores. Concentração HHI {p['hhi'].get('indice')} "
            f"({p['hhi'].get('nivel')}); maior recebedor: {top[0]} (R$ {moeda(top[1])}, "
            f"{(top[1]/(p['total_geral'] or 1)*100):.1f}%).")


# ──────────── cruzamentos de inteligência (DD fachada/laranja · cartel · SEI · endereço) ────────────

def _dd_orgao_bounded(ug: str, anos: Optional[list[int]], top_n: int = 12) -> dict:
    """Triagem de DD (fachada/laranja) + rodízio temporal (cartel/bid rotation) dos maiores fornecedores
    PJ da UG, ranqueada por grau/score, com os processos SEI a priorizar. Reusa
    `compliance_agent.investigacao_orgao_dd`. Bounded (top_n) e degrada HONESTO (uma rede cadastral por
    fornecedor, cacheada; se a rede/DuckDB falhar, devolve {ok:False} e o relatório registra como tal)."""
    try:
        from compliance_agent import investigacao_orgao_dd as iod
        out = iod.investigar_orgao(str(ug), top_n=top_n, anos=anos)
        out["ok"] = bool(out.get("ranking"))
        return out
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "_nota": str(exc)[:160]}


def _endereco_real_orgao(ug: str) -> dict:
    """Cruza os fornecedores (PJ) que a UG pagou com a tabela `endereco_verificacao` para responder
    'as empresas são reais?'. Buckets honestos: **AFASTADO** = sede real/edificada (afasta fachada);
    **INDICIO** = ponto possivelmente baldio/precário (a verificar); **INDISPONIVEL** = sem conclusão
    (cobertura OSM incompleta — NÃO é prova de inexistência, lição §endereço). Lista os indícios com nome."""
    out = {"ok": False, "n_forn": 0, "n_verificados": 0, "afastado": 0, "indicio": 0,
           "indisponivel": 0, "indicios": []}
    try:
        con = sqlite3.connect(_DB); con.row_factory = sqlite3.Row
        try:
            cnpjs = {r[0] for r in con.execute(
                "SELECT DISTINCT favorecido_cpf FROM ordens_bancarias WHERE ug_codigo=? "
                "AND favorecido_cpf IS NOT NULL AND length(favorecido_cpf)=14", (str(ug),)).fetchall()}
            if not cnpjs:
                return out
            out["n_forn"] = len(cnpjs)
            try:
                rows = con.execute(
                    "SELECT cnpj,status,nivel,municipio_geo,evidencia FROM endereco_verificacao").fetchall()
            except sqlite3.OperationalError:
                return out  # tabela ainda não existe (sweep de endereços não rodou)
            indic_cnpjs = []
            for r in rows:
                if r["cnpj"] not in cnpjs:
                    continue
                out["n_verificados"] += 1
                st = (r["status"] or "").upper()
                if st == "AFASTADO":
                    out["afastado"] += 1
                elif st == "INDICIO":
                    out["indicio"] += 1
                    if len(out["indicios"]) < 12:
                        out["indicios"].append({"cnpj": r["cnpj"], "nivel": r["nivel"],
                                                "evidencia": (r["evidencia"] or "")[:160], "nome": ""})
                        indic_cnpjs.append(r["cnpj"])
                else:
                    out["indisponivel"] += 1
            # nomes dos fornecedores com indício (p/ a tabela ficar legível)
            if indic_cnpjs:
                qs = ",".join("?" * len(indic_cnpjs))
                nomes = {r[0]: r[1] for r in con.execute(
                    f"SELECT favorecido_cpf, MAX(favorecido) FROM ordens_bancarias "
                    f"WHERE favorecido_cpf IN ({qs}) GROUP BY favorecido_cpf", indic_cnpjs).fetchall()}
                for it in out["indicios"]:
                    it["nome"] = nomes.get(it["cnpj"], "")
        finally:
            con.close()
        out["ok"] = out["n_verificados"] > 0
        return out
    except Exception as exc:  # noqa: BLE001
        out["_nota"] = str(exc)[:160]
        return out


# ───────────────────────────── render Markdown ─────────────────────────────

def _sigla_descr(nome: str) -> tuple[str, str]:
    """Separa "ITERJ — Instituto de Terras..." em ("ITERJ", "Instituto de Terras...")."""
    if "—" in nome:
        a, b = nome.split("—", 1)
        return a.strip(), b.strip()
    return nome.strip(), ""


def _recorrentes_identicos(p: dict, min_rep: int = 4, min_valor: float = 50_000.0) -> list[dict]:
    """Grupos (fornecedor, valor exato) pagos ≥min_rep vezes acima de min_valor — ACFE identical payments.
    Sinaliza parcelas fixas de contrato continuado (legítimo) e possível fracionamento (a verificar)."""
    if not p.get("tem_dados"):
        return []
    contagem: dict = defaultdict(lambda: {"n": 0, "total": 0.0, "cnpj": ""})
    for a in p["anos"]:
        for ln in p["por_ano"][a]["linhas"]:
            v = round(ln.get("valor") or 0.0, 2)
            if v < min_valor:
                continue
            g = contagem[(ln["favorecido"], v)]
            g["n"] += 1
            g["total"] += v
            g["cnpj"] = ln.get("cnpj", "") or g["cnpj"]
    grupos = [{"favorecido": k[0], "valor": k[1], "n": g["n"], "total": g["total"], "cnpj": g["cnpj"]}
              for k, g in contagem.items() if g["n"] >= min_rep]
    grupos.sort(key=lambda x: -x["total"])
    return grupos


def _secao_dd_md(add, ctx: dict) -> None:
    """Seção 1-D — triagem de DD (fachada/laranja) dos maiores fornecedores + rodízio temporal (cartel) +
    processos SEI a priorizar. É o cruzamento central de inteligência do relatório de órgão."""
    dd = ctx.get("dd_orgao") or {}
    add("## 1-D. TRIAGEM DE DUE DILIGENCE DOS FORNECEDORES (FACHADA / LARANJA / CARTEL)")
    add("")
    add("> Os maiores fornecedores PJ da UG passam por uma **investigação de due diligence** (rede societária, "
        "situação cadastral, capital × recebido, recência, sócio único, endereço, PEP/benefício) que classifica "
        "cada um em **🔴 alto / 🟡 médio / 🟢 sem indício**. Cruza-se ainda o **rodízio temporal de vencedores** "
        "(revezamento no topo ano a ano — assinatura de cartel/*bid rotation*, OCDE) e os **processos SEI** a "
        "priorizar. 🟢 não é atestado de regularidade; **fachada/laranja costuma morar na cauda**, não no topo "
        "por valor — a varredura de cauda roda em background.")
    add("")
    if not dd.get("ok"):
        _nota = dd.get("_nota") or "rede cadastral/DuckDB indisponível no momento"
        add(f"_Triagem de DD indisponível nesta execução ({_nota}). Rode "
            "`python -m compliance_agent.investigacao_orgao_dd {ug}` para o detalhe._".replace("{ug}", ctx["ug"]))
        add("")
        return
    rod = dd.get("rodizio")
    if rod and rod.get("indicio"):
        camps = ", ".join(f"{c['nome'][:26]} ({c['n_vitorias']}×)" for c in (rod.get("campeoes") or [])[:5])
        add(f"### ⟳ Rodízio temporal de vencedores (bid rotation) — score {rod.get('score')}")
        add("")
        add(f"> 🟡 **Indício de cartel/conluio:** {rod.get('n_campeoes')} fornecedores se **revezaram no 1º lugar** "
            f"da UG ao longo de {rod.get('n_anos')} exercícios (alternância {rod.get('alternancia')}, dominância "
            f"do grupo {rod.get('share_ring')}). Campeões: {camps}. O revezamento sistemático do vencedor é "
            "assinatura clássica de *bid rotation* (OCDE *Guidelines for Fighting Bid Rigging*). "
            "OB expõe o **vencedor**, não os licitantes — corroborar no SEI/PNCP (atas, propostas, habilitação).")
        add("")
    ranking = dd.get("ranking") or []
    alvos = dd.get("alvos_prioritarios") or []
    add(f"### Ranking de risco dos {len(ranking)} maiores fornecedores PJ")
    add("")
    add("| # | Grau | Score | Fornecedor | Total pago (R$) | Indícios (hipóteses) | Proc. SEI |")
    add("|--:|:--:|--:|---|--:|---|--:|")
    for i, r in enumerate(ranking, 1):
        cods = ", ".join(c.replace("H-", "") for c in (r.get("codigos") or [])) or "—"
        forn = f"{r['nome'][:42]} ({fmt_cnpj(r['cnpj'])})" if r.get("cnpj") else r["nome"][:42]
        add(f"| {i} | {r['grau']} | {r['score']} | {forn} | {moeda(r['total_pago'])} | {cods} "
            f"| {len(r.get('processos_sei') or [])} |")
    add("")
    if alvos:
        a0 = alvos[0]
        cods0 = ", ".join(c.replace("H-", "") for c in (a0.get("codigos") or [])) or "—"
        add(f"> 🟡 **{len(alvos)} fornecedor(es) com indício** (graus 🔴/🟡). O de maior atenção é "
            f"**{a0['nome']}** (grau {a0['grau']}, score {a0['score']}; hipóteses: {cods0}) — recomenda-se "
            "puxar o contrato, o processo SEI e a regularidade fiscal/sancionatória. Indício ≠ acusação.")
    else:
        add("> 🟢 Nenhum dos maiores fornecedores por valor disparou indício nas hipóteses verificáveis. "
            "Isso **não** afasta fachada/laranja — eles tendem a aparecer em contratos menores (cauda), "
            "cobertos pela varredura de DD estrutural em background.")
    add("")
    procs = dd.get("processos_prioritarios") or []
    if procs:
        add("**Processos SEI a priorizar no sweep** (correlação OB↔SEI dos fornecedores com indício): "
            + ", ".join(procs[:30]) + (" …" if len(procs) > 30 else "") + ".")
        add("")


def _secao_endereco_md(add, ctx: dict) -> None:
    """Seção 1-E — realidade do endereço das sedes (responde 'as empresas são reais?')."""
    er = ctx.get("endereco_real") or {}
    add("## 1-E. REALIDADE DO ENDEREÇO DAS SEDES (AS EMPRESAS SÃO REAIS?)")
    add("")
    add("> Cruza o CNPJ de cada fornecedor com o **mapa** (geocodificação + base cartográfica aberta) para "
        "checar se a **sede declarada existe e é edificada** — afastando (ou sinalizando) empresa de fachada. "
        "Veredito honesto: **AFASTADO** = sede real/edificada; **INDÍCIO** = ponto possivelmente baldio/precário "
        "(a verificar in loco/imagem); **INDISPONÍVEL** = sem conclusão. **INDISPONÍVEL ≠ inexistência** — a "
        "cobertura cartográfica na periferia é incompleta, e satélite no nível da rua nunca acusa baldio "
        "(só Street View/in loco conclui).")
    add("")
    if not er.get("ok"):
        cob = (f"0 de {er.get('n_forn', 0)}") if er.get("n_forn") else "0"
        add(f"_Ainda sem endereços verificados para os fornecedores desta UG ({cob} verificados). O sweep de "
            "endereços (`backfill_verificacao_endereco`) cobre o universo de sedes incrementalmente — esta "
            "seção se preenche à medida que avança._")
        add("")
        return
    add(f"**Cobertura:** {er['n_verificados']} de {er['n_forn']} fornecedores PJ já verificados "
        f"({er['n_verificados']/(er['n_forn'] or 1)*100:.0f}%). "
        f"✔ {er['afastado']} sede real (afastado) · 🟡 {er['indicio']} com indício · "
        f"… {er['indisponivel']} sem conclusão.")
    add("")
    if er.get("indicios"):
        add("| Fornecedor (CNPJ) | Nível | Evidência |")
        add("|---|:--:|---|")
        for it in er["indicios"]:
            forn = f"{(it.get('nome') or '—')[:40]} ({fmt_cnpj(it['cnpj'])})"
            add(f"| {forn} | {it.get('nivel') or '—'} | {(it.get('evidencia') or '—')[:90]} |")
        add("")
        add("> 🟡 **Indício a verificar:** sede em ponto possivelmente não edificado. Conferir o endereço no "
            "mapa real (CEP/Google), por imagem (Street View) ou in loco antes de tratar como achado — "
            "INDISPONÍVEL/centróide de rua não comprova baldio.")
        add("")


def render_md(ctx: dict) -> str:
    p = ctx["pagamentos"]
    sigla, descr = _sigla_descr(ctx["nome"])
    L: list[str] = []
    add = L.append
    add(f"# RELATÓRIO DE INTELIGÊNCIA — {sigla}")
    add(f"### {descr or sigla}  ·  UG {ctx['ug']}")
    add("")
    add("*Execução de pagamentos · Concentração por fornecedor · Risco & Compliance*")
    add("")
    alias = ctx.get("alias") or {}
    if alias:
        add(f"> **Nota de UG:** unidade gestora {ctx['ug']} (SIAFE-Rio 2: {alias.get('siafe_rio2','—')}). "
            f"Órgão superior: {alias.get('orgao_superior','—')}. Nas Ordens Bancárias os pagamentos podem "
            f"aparecer rotulados pelo nome do órgão superior — aqui são atribuídos pela UG.")
        add("")
    add(f"**Data:** {ctx['data']}  |  **Analista:** JFN Intelligence Engine  |  **Fonte:** SIAFE/TFE-RJ (OBs — pagamento)")
    add("")
    add("---")
    add("")
    _fr = cabecalho_frescor()  # honestidade: cobertura/frescor da base no topo
    if _fr:
        add(_fr)
        add("")
    add("## SUMÁRIO EXECUTIVO")
    add("")
    add(_resumo(ctx))
    add("")
    if p["tem_dados"]:
        add("### Execução financeira — pagamentos por exercício")
        add("")
        add("| Exercício | Nº de OBs | Fornecedores | Valor pago (R$) |")
        add("|---|---:|---:|---:|")
        for a in p["anos"]:
            b = p["por_ano"][a]
            nf = len({l["cnpj"] for l in b["linhas"]})
            add(f"| {a} | {b['n']} | {nf} | {moeda(b['total'])} |")
        add(f"| **Total** | **{p['n_geral']}** | **{p['n_fornecedores']}** | **{moeda(p['total_geral'])}** |")
        add("")

    # Concentração por favorecido + HHI
    add("## 1. CONCENTRAÇÃO POR FORNECEDOR (HHI)")
    add("")
    if p["tem_dados"]:
        add(f"**HHI:** {p['hhi'].get('indice')} — concentração **{p['hhi'].get('nivel')}** "
            f"(maior fornecedor = {p['hhi'].get('top_share')}% do valor pago).")
        add("")
        add("| Fornecedor | Valor recebido (R$) | % do total |")
        add("|---|---:|---:|")
        tot = p["total_geral"] or 1
        from compliance_agent.entidades_gov import eh_nao_fornecedor
        _tem_intergov = False
        for nome, val in list(p["por_favorecido_geral"].items())[:25]:
            tag = ""
            if eh_nao_fornecedor(nome):
                tag = " ⟨transf. intergov.⟩"
                _tem_intergov = True
            add(f"| {nome}{tag} | {moeda(val)} | {val/tot*100:.1f}% |")
        add("")
        if _tem_intergov:
            add("> ℹ️ Itens marcados ⟨transf. intergov.⟩ são **transferências intergovernamentais/tributos** "
                "(INSS, Ministérios, fundos de saúde/previdência) — pagamentos obrigatórios, **não** fornecedores "
                "de contratação. Entram no total/HHI por integridade, mas não devem ser lidos como contratos.")
            add("")
        if p["hhi"].get("top_share", 0) >= 50:
            add("> 🔴 **Red flag (ACFE):** um único fornecedor concentra ≥50% dos pagamentos do órgão — "
                "verificar competitividade das contratações (Art. 37 CF/88; Lei 14.133/2021).")
            add("")
    else:
        add("_Sem OBs para esta UG._")
        add("")

    # Concentração GEOGRÁFICA dos fornecedores (cidade-sede)
    geo = ctx.get("geo") or {}
    add("## 1-B. CONCENTRAÇÃO GEOGRÁFICA DOS FORNECEDORES (CIDADE-SEDE)")
    add("")
    add("> Em que **cidades** estão sediados os fornecedores que este órgão paga. Concentração alta numa "
        "cidade pequena/distante da atuação do órgão é red flag clássico (empresas de fachada/direcionamento — "
        "art. 337-F CP). Cruza as OBs com o endereço (Receita/BrasilAPI) do CNPJ.")
    add("")
    if geo.get("ok"):
        add(f"**Cobertura:** {geo.get('cobertura_valor',0)*100:.0f}% do valor pago e "
            f"{geo.get('cobertura_forn',0)*100:.0f}% dos fornecedores têm endereço ingerido "
            "(o ranking abaixo é sobre essa fração).")
        add("")
        add("| Cidade/UF | Fornecedores | OBs | Valor recebido (R$) | % (da fração conhecida) |")
        add("|---|---:|---:|---:|---:|")
        for c in geo["cidades"]:
            cid = f"{c['cidade']}/{c['uf']}" if c.get("uf") else c["cidade"]
            add(f"| {cid} | {c['n_fornecedores']} | {c['n_obs']} | {moeda(c['total_pago'])} | {c['pct']:.1f}% |")
        add("")
        top = geo["cidades"][0]
        if top["pct"] >= 50 and (top.get("uf") or "") and top["cidade"]:
            # HONESTIDADE: se a cidade-topo tem 1 só fornecedor, a "concentração geográfica" é apenas a
            # concentração de FORNECEDOR (já apontada na Seção 1) restada — não um sinal independente.
            if top.get("n_fornecedores", 0) <= 1:
                add(f"> ℹ️ {top['pct']:.0f}% do valor (na fração com endereço) vai a **um único fornecedor** "
                    f"sediado em **{top['cidade']}/{top['uf']}** — isto **não é** um sinal geográfico "
                    "independente: é a mesma concentração de fornecedor da Seção 1, vista pela ótica da sede. "
                    "O ponto de verificação é a competitividade do certame, não a geografia em si.")
            else:
                add(f"> 🟡 **Indício:** {top['pct']:.0f}% do valor (na fração com endereço) vai a "
                    f"**{top['n_fornecedores']} fornecedores** sediados em **{top['cidade']}/{top['uf']}** — "
                    "concentração geográfica multi-empresa é red flag clássico (fachada/direcionamento); "
                    "verificar compatibilidade com o objeto e a competitividade das contratações.")
            add("")
        if geo.get("_nota"):
            add(f"> ℹ️ {geo['_nota']}")
            add("")
    else:
        _motivo = geo.get("_nota") or "sem endereços ingeridos para os fornecedores desta UG"
        add(f"_Concentração geográfica indisponível ({_motivo}). "
            "Rode `python -m compliance_agent.rede_societaria --ingerir-top 2000`._")
        add("")

    # 1-C. Pagamentos recorrentes de valor IDÊNTICO ao mesmo fornecedor (ACFE: identical payments)
    grupos = _recorrentes_identicos(p)
    add("## 1-C. PAGAMENTOS RECORRENTES DE VALOR IDÊNTICO")
    add("")
    add("> O **mesmo valor exato** pago **várias vezes** ao **mesmo fornecedor**. É a assinatura de contrato "
        "continuado em parcelas fixas (legítimo) — mas valores idênticos reiterados também figuram entre os "
        "*red flags* da ACFE (pagamentos repetidos/redondos) e podem mascarar fracionamento ou execução sem "
        "medição. Caracterizar o contrato (objeto, vigência, medição) é o passo de verificação.")
    add("")
    if grupos:
        add("| Fornecedor (CNPJ) | Valor unitário (R$) | Repetições | Total (R$) |")
        add("|---|---:|---:|---:|")
        for g in grupos[:12]:
            forn = f"{g['favorecido']} ({fmt_cnpj(g['cnpj'])})" if g["cnpj"] else g["favorecido"]
            add(f"| {forn} | {moeda(g['valor'])} | {g['n']}× | {moeda(g['total'])} |")
        add("")
        g0 = grupos[0]
        add(f"> 🟡 **Indício:** **{g0['favorecido']}** recebeu **{g0['n']}×** o valor idêntico de "
            f"**R$ {moeda(g0['valor'])}** (R$ {moeda(g0['total'])} no total) — confirmar o contrato de origem "
            "(parcela mensal fixa?), a medição da execução e a aderência do objeto à finalidade do órgão.")
        add("")
    else:
        add("_Nenhum padrão relevante de pagamentos de valor idêntico repetido (≥4× acima de R$ 50 mil)._")
        add("")

    # 1-D. Triagem de Due Diligence (fachada/laranja) + rodízio temporal (cartel) — o coração da inteligência
    _secao_dd_md(add, ctx)
    # 1-E. Verificação de realidade do endereço das sedes (as empresas são reais?)
    _secao_endereco_md(add, ctx)

    # Tabelas de OBs por ano (pagamentos individuais a cada fornecedor)
    add("## 2. PAGAMENTOS (ORDENS BANCÁRIAS) POR ANO")
    add("")
    add("> Por exercício, as **maiores OBs** (materiais) e o fornecedor; a **lista completa** de cada "
        "pagamento está na **planilha XLSX** deste relatório. OB = pagamento definitivo; OBs de R$ 0,00 são "
        "estornos/regularizações.")
    add("")
    if p["tem_dados"]:
        TOP_OB_ANO = 12  # padrão de due diligence: destacar o material; detalhe completo na planilha
        for a in p["anos"]:
            b = p["por_ano"][a]
            add(f"### Exercício {a} — {b['n']} OBs — Total pago: R$ {moeda(b['total'])}")
            add("")
            maiores = sorted(b["linhas"], key=lambda ln: -(ln.get("valor") or 0))[:TOP_OB_ANO]
            add("| # | Nº OB | Data | Fornecedor (CNPJ) | Valor (R$) |")
            add("|---:|---|---|---|---:|")
            for i, ln in enumerate(maiores, 1):
                forn = f"{ln['favorecido']} ({fmt_cnpj(ln['cnpj'])})" if ln["cnpj"] else ln["favorecido"]
                add(f"| {i} | {ln['numero_ob']} | {ln['data']} | {forn} | {moeda(ln['valor'])} |")
            add(f"| | | | **Total {a} ({b['n']} OBs)** | **{moeda(b['total'])}** |")
            if b["n"] > len(maiores):
                add("")
                add(f"> _{len(maiores)} maiores de {b['n']} OBs do exercício — lista completa na planilha XLSX._")
            add("")
    else:
        add("_Sem OBs para esta UG._")
        add("")

    # Parecer escrito do JFN
    add("## 3. ANÁLISE JURÍDICA E DE MÉRITO — PARECER PRELIMINAR DO JFN")
    add("")
    raciocinio = ctx.get("raciocinio")
    if raciocinio:
        add("### Análise raciocinada — cruzamento dos achados (IA sobre os fatos coletados)")
        add("")
        add(raciocinio)
        add("")
        add("> _Síntese gerada por IA **a partir dos fatos coletados** (não inventa dados); indícios para "
            "apuração, não conclusão. O parecer estruturado abaixo permanece como base._")
        add("")
    add(parecer_orgao(ctx))
    add("")

    add("## 4. RECOMENDAÇÕES")
    add("")
    add("- Cruzar os maiores fornecedores (Seção 1) com seus contratos e processos SEI.")
    add("- Verificar a modalidade de contratação dos pagamentos concentrados (pregão/dispensa/inexigibilidade).")
    add("- Monitorar pagamentos atípicos (fim de exercício, valores redondos repetidos).")
    add("")
    add("## 5. REFERÊNCIAS")
    add("")
    add("- **Dados:** SIAFE-Rio / Transparência Fiscal RJ (OBs) — `data/compliance.db`; mapa de UG `data/ug_canonico.json`.")
    add("- **Normas:** Lei 14.133/2021; Lei 8.666/93; CF/88 Art. 37; metodologia TCU; ACFE Report to the Nations.")
    add("")
    add(f"_Gerado pelo JFN Intelligence Engine em {ctx['data']}. Não substitui análise jurídica especializada._")
    add("")
    return "\n".join(L)


# ───────────────────────────── render PDF ─────────────────────────────

def _risco_orgao(ctx: dict) -> dict:
    """Grau/score/achados de NÍVEL ÓRGÃO p/ o sumário executivo (reusa o motor do Lex). Score = indício
    interno de atenção (concentração + padrões ACFE), NUNCA acusação."""
    try:
        from compliance_agent import lex
        ach = lex._achados_orgao(ctx)
        emoji, rotulo, just = lex._grau(ach)
    except Exception:  # noqa: BLE001
        ach, emoji, rotulo, just = [], "🟢", "VERDE", "sem indícios relevantes nos dados disponíveis"
    p = ctx.get("pagamentos") or {}
    top = float((p.get("hhi") or {}).get("top_share") or 0)
    base = sum({1: 6, 2: 12, 3: 22, 4: 34}.get(a.get("grav", 0), 0) for a in ach)
    score = min(99, int(base + min(top, 60) * 0.5))
    return {"achados": ach, "emoji": emoji, "rotulo": rotulo, "just": just, "score": score}


def _secao_dd_pdf(pdf, _t, ctx: dict) -> None:
    """PDF — triagem de DD (fachada/laranja) + rodízio/cartel + processos SEI (cruzamento central)."""
    dd = ctx.get("dd_orgao") or {}
    pdf.add_page(); pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 9, _t("Triagem de Due Diligence dos fornecedores (fachada/laranja/cartel)"), ln=True)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
    _mc(pdf, 4.5, _t("Os maiores fornecedores PJ passam por due diligence (rede societária, situação cadastral, "
                     "capital x recebido, sócio único, endereço) e recebem grau de risco. Cruza-se o rodízio "
                     "temporal de vencedores (bid rotation/cartel) e os processos SEI a priorizar. Grau verde NÃO "
                     "atesta regularidade; fachada/laranja costuma morar na cauda, não no topo por valor."))
    pdf.ln(1)
    if not dd.get("ok"):
        pdf.set_font(pdf._fam, "I", 8); pdf.set_text_color(110, 110, 110)
        _mc(pdf, 4.5, _t("Triagem de DD indisponível nesta execução (rede cadastral/DuckDB) — degrada honesto."))
        pdf.set_text_color(0, 0, 0); return
    rod = dd.get("rodizio")
    if rod and rod.get("indicio"):
        camps = ", ".join(f"{c['nome'][:22]} ({c['n_vitorias']}x)" for c in (rod.get("campeoes") or [])[:4])
        pdf.set_font(pdf._fam, "B", 10); pdf.set_text_color(150, 90, 0)
        pdf.cell(0, 7, _t(f"Rodizio temporal de vencedores (bid rotation) - score {rod.get('score')}"), ln=True)
        pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
        _mc(pdf, 4.5, _t(f"Indício de cartel/conluio: {rod.get('n_campeoes')} fornecedores revezaram o 1o lugar "
                         f"em {rod.get('n_anos')} exercícios (dominância {rod.get('share_ring')}). Campeões: "
                         f"{camps}. OB expõe o vencedor, não os licitantes - corroborar no SEI/PNCP."))
        pdf.ln(1)
    ranking = dd.get("ranking") or []
    pdf.set_font(pdf._fam, "B", 10); pdf.cell(0, 7, _t(f"Ranking de risco - {len(ranking)} maiores fornecedores PJ"), ln=True)
    _tab_header(pdf, [("Grau", 12), ("Sc.", 12), ("Fornecedor", 96), ("Total (R$)", 34), ("Indícios", 22), ("SEI", 10)])
    pdf.set_font(pdf._fam, "", 7)
    for r in ranking:
        cods = ", ".join(c.replace("H-", "") for c in (r.get("codigos") or [])) or "-"
        _tab_row(pdf, [(_t(r["grau"]), 12, "C"), (str(r["score"]), 12, "R"), (_t(r["nome"])[:60], 96, "L"),
                       (moeda(r["total_pago"]), 34, "R"), (_t(cods)[:14], 22, "L"),
                       (str(len(r.get("processos_sei") or [])), 10, "R")], h=4.6)
    procs = dd.get("processos_prioritarios") or []
    if procs:
        pdf.ln(1); pdf.set_font(pdf._fam, "", 7); pdf.set_text_color(80, 80, 80)
        _mc(pdf, 4, _t("Processos SEI a priorizar: " + ", ".join(procs[:24]) + (" ..." if len(procs) > 24 else "")))
        pdf.set_text_color(0, 0, 0)


def _secao_endereco_pdf(pdf, _t, ctx: dict) -> None:
    """PDF — realidade do endereço das sedes (as empresas são reais?)."""
    er = ctx.get("endereco_real") or {}
    pdf.ln(4); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 8, _t("Realidade do endereço das sedes (as empresas são reais?)"), ln=True)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
    if not er.get("ok"):
        pdf.set_font(pdf._fam, "I", 8); pdf.set_text_color(110, 110, 110)
        _mc(pdf, 4.5, _t(f"Sem endereços verificados para esta UG ainda ({er.get('n_forn', 0)} fornecedores PJ). "
                         "O sweep de endereços cobre o universo incrementalmente."))
        pdf.set_text_color(0, 0, 0); return
    _mc(pdf, 4.5, _t(f"Cobertura: {er['n_verificados']} de {er['n_forn']} fornecedores verificados. "
                     f"Sede real (afastado): {er['afastado']} | com indício: {er['indicio']} | "
                     f"sem conclusão: {er['indisponivel']}. INDISPONÍVEL nao prova inexistência (cobertura "
                     "cartográfica incompleta; satélite no nível da rua nunca acusa baldio)."))
    if er.get("indicios"):
        pdf.ln(1); _tab_header(pdf, [("Fornecedor (CNPJ)", 96), ("Nível", 24), ("Evidência", 60)])
        pdf.set_font(pdf._fam, "", 7)
        for it in er["indicios"]:
            forn = f"{(it.get('nome') or '-')[:36]} ({fmt_cnpj(it['cnpj'])})"
            _tab_row(pdf, [(_t(forn)[:60], 96, "L"), (_t(it.get("nivel") or "-"), 24, "C"),
                           (_t(it.get("evidencia") or "-")[:38], 60, "L")], h=4.6)


def render_pdf(ctx: dict, destino: str) -> str:
    from fpdf import FPDF
    p = ctx["pagamentos"]
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf._fam, pdf._uni = _registrar_fonte(pdf)
    pdf.add_page()

    def _t(s: str) -> str:
        s = s or ""
        # glifos que a DejaVu (Unicode) NÃO possui (emoji de risco, seta ⤴) → equivalentes que ELA possui,
        # senão o fpdf2 emite "missing glyphs" e o PDF entregue mostra tofu (mesmo blindagem do parecer Lex).
        if getattr(pdf, "_uni", False):
            return s.replace("🔴", "●").replace("🟡", "●").replace("🟢", "●").replace("⤴", "↗")
        for a, b in (("—", "-"), ("–", "-"), ("₂", "2"), ("•", "-"), ("·", "-"), ("⤴", "->"), ("🔴", ""), ("🟡", ""), ("🟢", "")):
            s = s.replace(a, b)
        return s.encode("latin-1", "replace").decode("latin-1")

    pdf.set_fill_color(20, 30, 50); pdf.set_text_color(255, 255, 255)
    pdf.set_font(pdf._fam, "B", 15)
    pdf.cell(0, 13, _t("RELATÓRIO DE INTELIGÊNCIA DE ÓRGÃO"), fill=True, ln=True, align="C")
    pdf.set_font(pdf._fam, "", 9); pdf.set_fill_color(45, 60, 90)
    pdf.cell(0, 7, _t("Execução de pagamentos · Concentração por fornecedor · Risco"), fill=True, ln=True, align="C")
    pdf.cell(0, 7, _t(f"JFN Intelligence Engine  |  {ctx['data']}"), fill=True, ln=True, align="C")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "B", 14)
    _mc(pdf, 8, _t(f"{ctx['nome']}  ·  UG {ctx['ug']}"))
    pdf.ln(1); pdf.set_font(pdf._fam, "", 9)
    _mc(pdf, 5, _t(_resumo(ctx)))

    # ── SUMÁRIO EXECUTIVO: rating de risco + score (padrão due diligence) ──
    if p["tem_dados"]:
        _risco = _risco_orgao(ctx)
        pdf.ln(3)
        _cor = {"VERMELHO": (220, 53, 69), "AMARELO": (255, 150, 0), "VERDE": (40, 167, 69)}.get(_risco["rotulo"], (90, 90, 90))
        pdf.set_fill_color(*_cor)
        if _risco["rotulo"] == "AMARELO":
            pdf.set_text_color(0, 0, 0)
        else:
            pdf.set_text_color(255, 255, 255)
        pdf.set_font(pdf._fam, "B", 12)
        pdf.cell(0, 9, _t(f"  GRAU DE ATENÇÃO: {_risco['rotulo']}   ·   Score de risco do órgão: {_risco['score']}/100"),
                 fill=True, ln=True)
        pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
        _mc(pdf, 4.5, _t(f"{_risco['just']}. O score é indício INTERNO de atenção (concentração + padrões ACFE), "
                         "NÃO uma acusação. Os red flags e a matriz P×I estão abaixo; o detalhe jurídico, no Parecer Lex anexo."))
    else:
        _risco = {"achados": []}

    if p["tem_dados"]:
        pdf.ln(3); pdf.set_font(pdf._fam, "B", 12)
        pdf.cell(0, 8, _t("Pagamentos por exercício"), ln=True)
        _tab_header(pdf, [("Exercício", 36), ("Nº OBs", 26), ("Fornec.", 26), ("Valor pago (R$)", 62)])
        pdf.set_font(pdf._fam, "", 9)
        for a in p["anos"]:
            b = p["por_ano"][a]
            nf = len({l["cnpj"] for l in b["linhas"]})
            _tab_row(pdf, [(str(a), 36, "L"), (str(b["n"]), 26, "R"), (str(nf), 26, "R"), (moeda(b["total"]), 62, "R")])
        pdf.set_font(pdf._fam, "B", 9)
        _tab_row(pdf, [("Total", 36, "L"), (str(p["n_geral"]), 26, "R"), (str(p["n_fornecedores"]), 26, "R"),
                       (moeda(p["total_geral"]), 62, "R")])

        # Concentração por fornecedor
        pdf.add_page(); pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
        pdf.cell(0, 9, _t("Concentração por fornecedor (HHI)"), ln=True)
        pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 9)
        pdf.cell(0, 6, _t(f"HHI {p['hhi'].get('indice')} — {p['hhi'].get('nivel')} "
                          f"(maior fornecedor = {p['hhi'].get('top_share')}%)"), ln=True); pdf.ln(1)
        _tab_header(pdf, [("Fornecedor", 130), ("Valor (R$)", 36), ("%", 16)])
        pdf.set_font(pdf._fam, "", 8)
        tot = p["total_geral"] or 1
        from compliance_agent.entidades_gov import eh_nao_fornecedor
        for nome, val in list(p["por_favorecido_geral"].items())[:30]:
            rot = (_t(nome)[:74] + " [transf.intergov]") if eh_nao_fornecedor(nome) else _t(nome)[:86]
            _tab_row(pdf, [(rot, 130, "L"), (moeda(val), 36, "R"), (f"{val/tot*100:.1f}", 16, "R")], h=5)

        # Concentração GEOGRÁFICA (sede dos fornecedores) — já calculada em ctx["geo"], antes descartada no PDF
        geo = ctx.get("geo") or {}
        if geo.get("ok") and geo.get("cidades"):
            pdf.ln(4); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 30, 50)
            pdf.cell(0, 8, _t("Concentração geográfica (sede dos fornecedores)"), ln=True)
            pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
            _mc(pdf, 4.5, _t(f"Em que cidades se sediam os fornecedores que o órgão paga (fração com endereço: "
                             f"{geo.get('cobertura_valor', 0)*100:.0f}% do valor). Concentração alta em cidade pequena/"
                             "distante da atuação do órgão é red flag de fachada/direcionamento (art. 337-F CP)."))
            pdf.ln(1)
            _tab_header(pdf, [("Cidade/UF", 70), ("Forn.", 18), ("OBs", 20), ("Valor (R$)", 40), ("%", 16)])
            pdf.set_font(pdf._fam, "", 8)
            for c in geo["cidades"][:12]:
                cid = f"{c['cidade']}/{c['uf']}" if c.get("uf") else c["cidade"]
                _tab_row(pdf, [(_t(cid)[:42], 70, "L"), (str(c["n_fornecedores"]), 18, "R"), (str(c["n_obs"]), 20, "R"),
                               (moeda(c["total_pago"]), 40, "R"), (f"{c['pct']:.1f}", 16, "R")], h=4.8)

        # Pagamentos recorrentes de valor idêntico (ACFE identical payments)
        _grupos = _recorrentes_identicos(p)
        if _grupos:
            pdf.ln(4); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 30, 50)
            pdf.cell(0, 8, _t("Pagamentos recorrentes de valor idêntico"), ln=True)
            pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
            _mc(pdf, 4.5, _t("Mesmo valor exato pago várias vezes ao mesmo fornecedor — parcela fixa de "
                             "contrato continuado (legítimo) ou red flag ACFE (fracionamento/sem medição) a verificar."))
            pdf.ln(1)
            _tab_header(pdf, [("Fornecedor", 96), ("Valor unit. (R$)", 34), ("Rep.", 14), ("Total (R$)", 38)])
            pdf.set_font(pdf._fam, "", 8)
            for g in _grupos[:12]:
                _tab_row(pdf, [(_t(g["favorecido"])[:60], 96, "L"), (moeda(g["valor"]), 34, "R"),
                               (f"{g['n']}x", 14, "R"), (moeda(g["total"]), 38, "R")], h=4.8)

        # Red flags do controle externo + matriz P×I (síntese; detalhe e fundamentos no Parecer Lex anexo)
        _ach = _risco.get("achados") or []
        pdf.ln(4); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 30, 50)
        pdf.cell(0, 8, _t("Red flags do controle externo (síntese · matriz P×I — TCU)"), ln=True)
        pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
        if _ach:
            from compliance_agent.lex import _RF
            _tab_header(pdf, [("Indício (red flag)", 112), ("Grav.", 18), ("P×I", 16), ("Faixa", 28)])
            pdf.set_font(pdf._fam, "", 8)
            for a in _ach:
                _nome = _RF.get(a["rf"], (a["rf"], ""))[0]
                _pp = min(5, 2 + a["grav"] // 2); _ii = a["grav"]; _sc = _pp * _ii
                _faixa = "Baixo" if _sc <= 4 else "Médio" if _sc <= 9 else "Alto" if _sc <= 14 else "Extremo"
                _tab_row(pdf, [(_t(f"{a['rf']} — {_nome}")[:68], 112, "L"), (f"{a['grav']}/5", 18, "R"),
                               (str(_sc), 16, "R"), (_faixa, 28, "L")], h=4.8)
            pdf.ln(1); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(110, 110, 110)
            _mc(pdf, 4, _t("Indícios a verificar (metodologia TCU P×I). Observação, fundamento legal e diligência "
                           "sugerida de cada um estão no Parecer Lex anexo a este relatório."))
            pdf.set_text_color(0, 0, 0)
        else:
            _mc(pdf, 4.5, _t("Nenhum red flag automático disparou a partir dos pagamentos (OB). Presunção de "
                             "regularidade dos atos administrativos mantida."))

        # Triagem de DD (fachada/laranja) + rodízio/cartel + realidade de endereço (cruzamentos de inteligência)
        _secao_dd_pdf(pdf, _t, ctx)
        _secao_endereco_pdf(pdf, _t, ctx)

        # OBs por ano
        for a in p["anos"]:
            b = p["por_ano"][a]
            pdf.add_page(); pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
            pdf.cell(0, 9, _t(f"Pagamentos (OBs) — exercício {a}"), ln=True)
            pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 9)
            _maiores = sorted(b["linhas"], key=lambda ln: -(ln.get("valor") or 0))[:12]
            _nota = f"{b['n']} OBs — Total: R$ {moeda(b['total'])}" + (
                f"  ·  {len(_maiores)} maiores abaixo; lista completa na planilha XLSX" if b["n"] > len(_maiores) else "")
            pdf.cell(0, 6, _t(_nota), ln=True); pdf.ln(1)
            _tab_header(pdf, [("#", 9), ("Nº OB", 26), ("Data", 22), ("Fornecedor", 97), ("Valor (R$)", 36)])
            pdf.set_font(pdf._fam, "", 7)
            for i, ln in enumerate(_maiores, 1):
                _tab_row(pdf, [(str(i), 9, "R"), (_t(ln["numero_ob"]), 26, "L"), (_t(ln["data"])[:10], 22, "L"),
                               (_t(ln["favorecido"])[:60], 97, "L"), (moeda(ln["valor"]), 36, "R")], h=4.5)
            pdf.set_font(pdf._fam, "B", 8)
            _tab_row(pdf, [("", 9, "L"), ("", 26, "L"), ("", 22, "L"), (f"Total {a}", 97, "R"),
                           (moeda(b["total"]), 36, "R")], h=5)

    # Parecer jurídico e de mérito
    pdf.add_page()
    pdf.set_font(pdf._fam, "B", 14); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 10, _t("Análise Jurídica e de Mérito — Parecer Preliminar do JFN"), ln=True)
    pdf.set_text_color(0, 0, 0)
    raciocinio = ctx.get("raciocinio")
    if raciocinio:
        pdf.set_font(pdf._fam, "B", 11); pdf.cell(0, 7, _t("Análise raciocinada — cruzamento dos achados"), ln=True)
        pdf.set_font(pdf._fam, "", 10)
        _render_parecer_pdf(pdf, _t, raciocinio)
        pdf.ln(2)
    _render_parecer_pdf(pdf, _t, parecer_orgao(ctx))

    pdf.ln(3); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(120, 120, 120)
    _mc(pdf, 4, _t("Gerado pelo JFN Intelligence Engine. Não substitui análise jurídica especializada."))

    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(destino)
    return destino


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Uso: python -m compliance_agent.reporting.inteligencia_orgao <órgão/UG> [ano1 ano2 ...]")
        sys.exit(1)
    anos_cli = [int(a) for a in args if a.isdigit() and len(a) == 4]
    termo_cli = " ".join(a for a in args if not (a.isdigit() and len(a) == 4)).strip()
    res = gerar(orgao=termo_cli, anos=anos_cli or None)
    print(json.dumps({k: v for k, v in res.items() if k != "resumo"}, ensure_ascii=False, indent=2))
    print("\nRESUMO:", res.get("resumo", ""))
