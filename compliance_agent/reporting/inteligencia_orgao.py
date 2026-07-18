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
import logging
import sqlite3
import sys
from collections import OrderedDict, defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

from fpdf.enums import XPos, YPos

from compliance_agent import ugs
from compliance_agent.reporting.inteligencia import (
    cabecalho_frescor,
    _DB, _REPORTS, _foto_fachada_b2, _hhi, _mc, _registrar_fonte, _render_parecer_pdf, _slug,
    _tab_header, _tab_row, fmt_cnpj, moeda, so_digitos,
)

_log = logging.getLogger(__name__)


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
    # Funde o índice SIAFE autoritativo (data/ug_index_siafe.json): 444/596 UGs não existem no
    # espelho TFE e eram INVISÍVEIS ao resolvedor (ex.: Fundo Soberano 226300 — achado 2026-07-11).
    # O nome curto do índice ("DETRAN-RJ", "FSERJ") entra no _raw p/ casar a sigla que o humano digita.
    try:
        idx = json.loads((_DB.parent / "ug_index_siafe.json").read_text(encoding="utf-8")).get("ugs") or {}
    except (OSError, ValueError):
        idx = {}
    por_cod = {u["ug"]: u for u in out}
    for cod, curto in idx.items():
        cod = str(cod).strip()
        u = por_cod.get(cod)
        if u is not None:
            if curto and curto.lower() not in u["_raw"].lower():
                u["_raw"] += f" {curto}"
        else:
            out.append({"ug": cod, "nome": ugs.nome_canonico(cod, "") or curto or f"UG {cod}",
                        "total_pago": 0.0, "n_obs": 0, "n_forn": 0, "_raw": curto or ""})
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
           anos: Optional[list[int]] = None, salvar: bool = True, so_resolver: bool = False,
           retornar_ctx: bool = False) -> dict:
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
    ctx["beneficios_socios"] = _beneficios_orgao(ug_cod)  # laranja: benefício de subsistência dos sócios/admin
    ctx["penalidades_tce"] = _penalidades_tce_orgao(ug_cod)  # sanções do TCE-RJ ao órgão (controle externo)
    ctx["concentracao_grupo"] = _concentracao_grupo_orgao(ug_cod)  # concentração oculta por grupo (cartel/conc. fictícia)
    ctx["painel_detectores"] = _painel_detectores_orgao(ug_cod)  # §1-I: visão unificada dos detectores (spec licitações)
    ctx["tac_orgao"] = _tac_orgao(ug_cod)  # §1-J: pagamento fora de contrato (TAC/indenização) + emergencial + worklist
    ctx["anomalia_receita"] = _anomalia_receita_orgao(ug_cod)  # §1-K: cruzamento dump RF × fornecedores (anomalias)
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
    path_lex_md = ""
    grau_lex = ""
    if salvar:
        try:
            from compliance_agent import lex
            _lex = lex.gerar_orgao(ctx, salvar=True)
            path_lex = _lex.get("path_lex_pdf", "") or ""
            path_lex_md = _lex.get("path_lex_md", "") or ""
            grau_lex = _lex.get("grau", "") or ""
        except Exception as exc:  # noqa: BLE001
            ctx["_lex_erro"] = str(exc)[:160]

    out = {"ok": True, "ug": ug_cod, "orgao": nome, "resumo": _resumo(ctx),
           "path_md": path_md, "path_pdf": path_pdf, "path_xlsx": path_xlsx,
           "path_lex": path_lex, "path_lex_md": path_lex_md, "grau_lex": grau_lex,
           "fonte": "REAL" if pagamentos["tem_dados"] else "SEM_DADOS"}
    if retornar_ctx:  # consumido pelo relatório consolidado (reporting/consolidado.py) — sem re-coletar
        out["_ctx"] = ctx
    return out


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
         # contagem de fornecedores SEMPRE por CNPJ distinto (n_fornecedores) — não pelo nº de NOMES em
         # por_favorecido_geral, que infla 1 quando um mesmo CNPJ aparece sob duas grafias (off-by-one:
         # SUMÁRIO/§1 davam 115 por CNPJ e a §3 dava 116 por nome). CNPJ = identidade canônica da PJ.
         f"Execução financeira (OB): R$ {moeda(p['total_geral'])} em {p['n_geral']} ordens bancárias a "
         f"{p['n_fornecedores']} fornecedores.",
         f"Concentração: maior fornecedor '{top_nome}' = {hhi.get('top_share', 0):.1f}% do valor "
         f"(R$ {moeda(top_val)}); HHI {hhi.get('indice')} (nível {hhi.get('nivel')})."]
    grupos = _recorrentes_identicos(p)
    if grupos:
        L.append("Pagamentos recorrentes de valor IDÊNTICO (ACFE identical payments): "
                 f"{len(grupos)} grupo(s) — ex.: "
                 + "; ".join(f"{g['favorecido'][:30]} {g['n']}× R$ {moeda(g['valor'])}" for g in grupos[:8]) + ".")
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
        _fonte_end = ("Google (Geocoding+Address Validation+Places)" if er.get("fonte") == "GOOGLE"
                      else "fonte mista Google+OSM" if er.get("fonte") == "MISTA"
                      else "base cartográfica aberta/OSM")
        L.append(f"Realidade do endereço das sedes (amostra verificada, {_fonte_end}): {er['afastado']} "
                 f"confirmadas reais, {er['indicio']} com indício (possível baldio/precário), "
                 f"{er['indisponivel']} sem conclusão — de {er['n_verificados']} verificadas em "
                 f"{er['n_forn']} fornecedores PJ. INDISPONÍVEL não é prova de inexistência (cobertura incompleta).")
    bs = ctx.get("beneficios_socios") or {}
    if bs.get("ok") and bs.get("n_verificados"):
        if bs.get("n_com_beneficio"):
            L.append(f"Benefícios sociais dos sócios/administradores (laranja): {bs['n_com_beneficio']} vínculo(s) / "
                     f"{bs.get('n_pessoas_beneficio', 0)} pessoa(s) recebem benefício de subsistência entre "
                     f"{bs['n_verificados']} verificados ({bs['cobertura']}% de cobertura) — indício de interposição "
                     "de pessoas (testa-de-ferro) a confirmar no contrato social/SEI; INDISPONÍVEL para os demais.")
        else:
            L.append(f"Benefícios sociais dos sócios/administradores: {bs['n_verificados']} verificados, nenhum "
                     "recebe benefício de subsistência (indício de laranja AFASTADO para os verificados; os não "
                     "resolvidos seguem INDISPONÍVEL).")
    tce = ctx.get("penalidades_tce") or {}
    if tce.get("ok") and tce.get("n_condenacoes"):
        deb = tce.get("por_tipo", {}).get("DEBITO", {}).get("valor", 0.0)
        mul = tce.get("por_tipo", {}).get("MULTA", {}).get("valor", 0.0)
        ress = " (correspondência de nome incerta p/ parte — conferir o ente no processo)" if tce.get("tem_media") else ""
        L.append(f"Sanções do TCE-RJ ao órgão (controle externo, fato JÁ JULGADO): {tce['n_condenacoes']} "
                 f"condenação(ões) em {tce.get('n_eventos', 0)} eventos / {tce['n_processos']} processo(s) de contas, "
                 f"somando R$ {moeda(deb)} em débito e R$ {moeda(mul)} em multa (valor sem dupla contagem da "
                 f"responsabilidade solidária){ress}. Reforça o risco institucional — a Corte de Contas já reconheceu "
                 "falhas de gestão/prestação de contas deste órgão.")
    cg = ctx.get("concentracao_grupo") or {}
    if cg.get("ok") and cg.get("indicio"):
        mm = cg.get("maior_grupo_multi") or {}
        L.append("Concentração OCULTA por grupo econômico (concorrência fictícia / cartel): colapsando os "
                 f"fornecedores por sócio em comum, {cg.get('n_grupos_multi', 0)} grupo(s) multi-CNPJ emergem "
                 f"em {cg.get('n_grupos', 0)} grupos / {cg.get('n_cnpjs', 0)} CNPJs. O maior reúne "
                 f"{mm.get('n_cnpjs', 0)} CNPJs ({mm.get('n_raizes', 0)} raízes) — aparentes concorrentes — "
                 f"concentrando {mm.get('share', 0):.1f}% do valor (R$ {moeda(mm.get('total', 0))}; "
                 f"ex.: {(mm.get('top_nome') or '—')[:30]}). Indício de diversidade fictícia/fracionamento a "
                 "corroborar com editais/licitantes (SEI/PNCP); QSA mascarado/INDISPONÍVEL ≠ afastado.")
    tj = ctx.get("tac_orgao") or {}
    if tj.get("ok"):
        ug_m = tj.get("tac_ug") or {}
        emerg = tj.get("emergencial") or {}
        wl = tj.get("worklist") or {}
        susp = [f for f in (wl.get("fornecedores") or []) if f.get("sede_indicio")]
        frase = ("Pagamento FORA de contrato regular (TAC/indenização/reconhecimento de dívida) na UG: "
                 f"{ug_m.get('pct', 0):.1f}% de R$ {moeda(ug_m.get('total', 0))} pagos "
                 f"(R$ {moeda(ug_m.get('total_tac', 0))} em {ug_m.get('n_tac', 0)} OBs) — indício SISTÊMICO de "
                 "contratação informal/emergencial perpetuada e fuga ao dever de licitar (off-contract spend; "
                 "art. 59 par. único Lei 8.666; art. 149 Lei 14.133; art. 37 CF/88).")
        if emerg.get("ok"):
            frase += (f" Red flag irmã emergencial/dispensa: {emerg.get('n_emerg', 0)} OBs "
                      f"(R$ {moeda(emerg.get('total_emerg', 0))}) citam EMERGENCIAL/DISPENSA.")
        wl_top = (wl.get("fornecedores") or [])[:4]
        if wl_top:
            frase += (" Worklist de co-suspeitos por TAC%: "
                      + "; ".join(f"{(f.get('nome') or '—')[:26]} {f.get('pct', 0):.0f}% "
                                  f"(R$ {moeda(f.get('total_tac', 0))})"
                                  + (" [sede-fachada]" if f.get("sede_indicio") else "")
                                  for f in wl_top) + ".")
        if susp:
            frase += (f" {len(susp)} fornecedor(es) da worklist somam alto TAC% E sede com indício de fachada "
                      "(INDÍCIO/sem-Google) — hipótese de fachada/interposição reforçada, a apurar (indício, não acusação).")
        L.append(frase)
    pd = ctx.get("painel_detectores") or {}
    if pd.get("ok") and pd.get("confirmados"):
        # Painel CONSOLIDA os detectores do spec (§1-I); aqui só os CONFIRMADOS entram no raciocínio. Não
        # repetir a tabela de concentração-grupo da §1-H — o detector J1 a referencia, não a duplica.
        nomes = ", ".join(f"{r['detector']} (score {r['score']:.2f})" for r in pd["confirmados"][:5])
        L.append(f"Painel de detectores do spec de licitações (§1-I, visão unificada): "
                 f"{pd.get('n_confirmados', 0)} detector(es) com indício CONFIRMADO (sobreviveram à checagem "
                 f"inversa) — {nomes}. Ex.: {pd['confirmados'][0]['evidencia']}. São os indícios objetivos do "
                 "spec a corroborar; o J1 (conluio) referencia a concentração-grupo já detalhada acima, sem "
                 f"duplicar. ({pd.get('n_descartados', 0)} afastado(s) pela exculpatória, "
                 f"{pd.get('n_nao_avaliaveis', 0)} INDISPONÍVEL — não somam ao indício.)")
    ar = ctx.get("anomalia_receita") or {}
    if ar.get("ok"):
        cov = ar.get("cobertura") or {}
        sf_flag = [r for r in (ar.get("sem_fins_lucrativos") or []) if not r.get("ressalva")]
        rede = ar.get("rede_mesmo_orgao") or []
        su = ar.get("socio_unico_alto_valor") or []
        partes = []
        if sf_flag:
            t = sf_flag[0]
            partes.append(f"{len(sf_flag)} entidade(s) SEM FINS LUCRATIVOS (associação/fundação/OS, sem perfil de "
                          f"ensino/pesquisa) recebendo como fornecedor — maior: {(t['razao_social'] or '')[:30]} "
                          f"(R$ {moeda(t['total'])})")
        if rede:
            t = rede[0]
            partes.append(f"{len(rede)} administrador(es) compartilhando ≥2 fornecedores do MESMO órgão (rede/"
                          f"concorrência fictícia) — ex.: {(t['nome_socio'] or '')[:26]} em "
                          f"{t['n_fornecedores']} fornecedores")
        if su:
            partes.append(f"{len(su)} fornecedor(es) de alto valor com administrador ÚNICO no QSA (indício de "
                          f"laranja/interposição) — ex.: {(su[0]['razao_social'] or '')[:30]}")
        cad = ar.get("cadastro") or {}
        if cad.get("ok") and cad.get("achados"):
            partes.append(f"{len(cad['achados'])} fornecedor(es) com situação cadastral irregular na Receita "
                          "(INAPTA/baixada)")
        if partes:
            L.append("Cruzamento com o dump da Receita Federal (anomalias nos fornecedores, cobertura "
                     f"{cov.get('pct_empresas_min', 0):.0f}% no dump / {cov.get('pct_qsa', 0):.0f}% com QSA): "
                     + "; ".join(partes) + ". Indício a corroborar com o objeto contratual/SEI; entes públicos e "
                     "instituições legítimas de ensino/pesquisa NÃO são anomalia; CPF mascarado (LGPD).")
        else:
            L.append("Cruzamento com o dump da Receita Federal: nenhuma anomalia robusta (sem-fins não-educacional, "
                     "rede de administradores, laranja sócio-único) entre os fornecedores cobertos pelo dump "
                     f"(cobertura {cov.get('pct_empresas_min', 0):.0f}%). INDISPONÍVEL ≠ ausência para os não-cobertos.")
    return "\n".join("- " + x for x in L)


_SYS_RACIOCINIO_ORGAO = (
    "Você é auditor sênior de controle externo (TCE-RJ/TCU) analisando a EXECUÇÃO de um órgão público. "
    "A partir EXCLUSIVAMENTE dos fatos listados (NÃO invente dados/nomes/fontes; sem conhecimento externo), "
    "escreva uma ANÁLISE RACIOCINADA que CONECTE TODOS os achados disponíveis (concentração em fornecedor, "
    "pagamentos recorrentes idênticos, concentração geográfica, triagem de DUE DILIGENCE de fachada/laranja "
    "nos maiores fornecedores, RODÍZIO TEMPORAL de vencedores/cartel, processos SEI a priorizar, a "
    "VERIFICAÇÃO DE REALIDADE do endereço das sedes, as SANÇÕES DO TCE-RJ ao órgão — fato já julgado pela Corte "
    "de Contas, que pondera o risco institucional — e o CRUZAMENTO COM O DUMP DA RECEITA FEDERAL (entidades sem "
    "fins lucrativos recebendo, redes de administradores compartilhados entre fornecedores do órgão, e fornecedores "
    "de alto valor com sócio único = indício de laranja): o que chama atenção, COMO os sinais se REFORÇAM entre si "
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
        _log.warning("DD do órgão %s degradou (seção 1-D): %s", ug, exc)  # não somir calado (lição bug favorecido)
        return {"ok": False, "_nota": str(exc)[:160]}


def _endereco_real_orgao(ug: str) -> dict:
    """Cruza os fornecedores (PJ) que a UG pagou com a verificação de SEDE para responder 'as empresas
    são reais?'. PREFERE a verificação AUTORITATIVA do Google (`verificacao_sede`: Geocoding+Address
    Validation+Places, populada por `tools/sweep_sede_google.py`) e cai p/ o OSM antigo
    (`endereco_verificacao`, deprecado) quando o CNPJ ainda não foi varrido pelo Google — espelha o
    padrão honesto de `inteligencia._realidade_sede_texto`. Buckets honestos: **AFASTADO** = sede
    real/edificada (afasta fachada); **INDICIO** = ponto possivelmente baldio/precário (a verificar);
    **INDISPONIVEL** = sem conclusão (cobertura incompleta — NÃO é prova de inexistência, lição §endereço).
    `n_google` = quantos vereditos vieram da fonte Google (selo de fonte na seção). Lista os indícios com nome."""
    out = {"ok": False, "n_forn": 0, "n_verificados": 0, "afastado": 0, "indicio": 0,
           "indisponivel": 0, "n_google": 0, "indicios": []}
    try:
        con = sqlite3.connect(_DB); con.row_factory = sqlite3.Row
        try:
            cnpjs = {r[0] for r in con.execute(
                "SELECT DISTINCT favorecido_cpf FROM ordens_bancarias WHERE ug_codigo=? "
                "AND favorecido_cpf IS NOT NULL AND length(favorecido_cpf)=14", (str(ug),)).fetchall()}
            if not cnpjs:
                return out
            out["n_forn"] = len(cnpjs)
            # COALESCE da fonte: 1 veredito por CNPJ, PREFERINDO o Google (verificacao_sede) ao OSM
            # (endereco_verificacao). Monta-se o OSM primeiro e o Google SOBREPÕE (autoritativo).
            vereditos: dict = {}  # cnpj -> {status, nivel, evidencia, google: bool}

            def _absorve(tabela: str, google: bool):
                try:
                    rows = con.execute(
                        f"SELECT cnpj,status,nivel,evidencia FROM {tabela}").fetchall()  # noqa: S608 (nome fixo)
                except sqlite3.OperationalError:
                    return  # tabela ainda não existe (sweep correspondente não rodou)
                for r in rows:
                    if r["cnpj"] not in cnpjs:
                        continue
                    # Google sempre sobrepõe; OSM só preenche se ainda não houver veredito p/ o CNPJ
                    if not google and r["cnpj"] in vereditos:
                        continue
                    vereditos[r["cnpj"]] = {"status": (r["status"] or "").upper(),
                                            "nivel": r["nivel"], "evidencia": (r["evidencia"] or "")[:160],
                                            "google": google}

            _absorve("endereco_verificacao", google=False)  # base OSM (fallback)
            _absorve("verificacao_sede", google=True)        # Google sobrepõe (autoritativo)
            if not vereditos:
                return out  # nenhuma das tabelas existe / nenhum CNPJ varrido (sweep não rodou)

            indic_cnpjs = []
            for cnpj, v in vereditos.items():
                out["n_verificados"] += 1
                if v["google"]:
                    out["n_google"] += 1
                st = v["status"]
                if st == "AFASTADO":
                    out["afastado"] += 1
                elif st == "INDICIO":
                    out["indicio"] += 1
                    if len(out["indicios"]) < 12:
                        out["indicios"].append({"cnpj": cnpj, "nivel": v["nivel"],
                                                "evidencia": v["evidencia"], "nome": "",
                                                "google": v["google"]})
                        indic_cnpjs.append(cnpj)
                else:
                    out["indisponivel"] += 1
            # nomes dos fornecedores com indício (p/ a tabela ficar legível)
            if indic_cnpjs:
                qs = ",".join("?" * len(indic_cnpjs))
                nomes = {r[0]: r[1] for r in con.execute(
                    f"SELECT favorecido_cpf, MAX(favorecido_nome) FROM ordens_bancarias "
                    f"WHERE favorecido_cpf IN ({qs}) GROUP BY favorecido_cpf", indic_cnpjs).fetchall()}
                for it in out["indicios"]:
                    it["nome"] = nomes.get(it["cnpj"], "")
        finally:
            con.close()
        out["ok"] = out["n_verificados"] > 0
        # selo de fonte: Google quando TODOS (ou parte) dos vereditos vieram da verificacao_sede
        if out["n_google"] >= out["n_verificados"] and out["n_verificados"] > 0:
            out["fonte"] = "GOOGLE"
        elif out["n_google"] > 0:
            out["fonte"] = "MISTA"
        else:
            out["fonte"] = "OSM"
        return out
    except Exception as exc:  # noqa: BLE001
        _log.warning("Realidade de endereço do órgão %s degradou (seção 1-E): %s", ug, exc)
        out["_nota"] = str(exc)[:160]
        return out


def _beneficios_orgao(ug: str) -> dict:
    """Agrega os BENEFÍCIOS SOCIAIS (laranja) dos sócios/administradores dos fornecedores PJ da UG, via
    `socio_beneficio` (sweep detached) ⋈ `socios_fornecedor`. Cruzamento INTELIGENTE: distingue indício /
    AFASTADO / INDISPONÍVEL e traz a leitura raciocinada. Degrada honesto (tabela/sweep ausente → ok=False)."""
    try:
        con = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
        try:
            cnpjs = [r[0] for r in con.execute(
                "SELECT DISTINCT favorecido_cpf FROM ordens_bancarias WHERE ug_codigo=? "
                "AND favorecido_cpf IS NOT NULL AND length(favorecido_cpf)=14", (str(ug),)).fetchall()]
        finally:
            con.close()
        if not cnpjs:
            return {"ok": False}
        from compliance_agent.reporting import beneficios_view as bv
        agg = bv.agregar_por_cnpjs(cnpjs)
        agg["ok"] = agg.get("total_qsa", 0) > 0
        return agg
    except Exception as exc:  # noqa: BLE001
        _log.warning("Benefícios dos sócios do órgão %s degradou (seção 1-F): %s", ug, exc)
        return {"ok": False, "_nota": str(exc)[:160]}


def _penalidades_tce_orgao(ug: str) -> dict:
    """Sanções do TCE-RJ (`penalidades_tcerj`) imputadas ao órgão desta UG, via mapa curado/auditável
    (string do TCE → UG, com confiança). Fato JÁ JULGADO pela Corte (não indício nosso). Degrada honesto."""
    try:
        from compliance_agent.reporting import penalidades_tce_view as pv
        return pv.por_ug(ug)
    except Exception as exc:  # noqa: BLE001
        _log.warning("Sanções TCE-RJ do órgão %s degradou (seção 1-G): %s", ug, exc)
        return {"ok": False, "_nota": str(exc)[:160]}


def _concentracao_grupo_orgao(ug: str) -> dict:
    """Concentração OCULTA por GRUPO econômico (CNPJs ligados por sócio em comum) dos fornecedores da UG, via
    `grafo_cartel.concentracao_por_grupo`. Revela CONCORRÊNCIA FICTÍCIA: muitos CNPJs que parecem concorrentes
    mas são UM grupo. `indicio=True` quando um grupo MULTI-CNPJ concentra fatia relevante. Degrada honesto
    (DuckDB/QSA ausente → ok=False; INDISPONÍVEL não é prova de ausência de grupo)."""
    try:
        from compliance_agent.grafo_cartel import concentracao_por_grupo
        out = concentracao_por_grupo(str(ug))
        out["ok"] = bool(out.get("grupos"))
        return out
    except Exception as exc:  # noqa: BLE001
        _log.warning("Concentração por grupo do órgão %s degradou (seção 1-H): %s", ug, exc)
        return {"ok": False, "_nota": str(exc)[:160]}


def _painel_detectores_orgao(ug: str) -> dict:
    """Roda o ORQUESTRADOR de detectores de órgão (`detectores.rodar_orgao`) e normaliza a saída para o painel
    §1-I — a VISÃO UNIFICADA dos detectores do spec de licitações (hoje J1 conluio; extensível a P/C/E/X sem
    hardcode: itera sobre a lista de `ResultadoDetector`). Degrada honesto: se o orquestrador quebra (DuckDB/QSA/
    LLM), `ok=False` e a seção informa INDISPONÍVEL — NÃO some, e INDISPONÍVEL ≠ ausência de indício."""
    try:
        from compliance_agent.detectores import rodar_orgao
        resultados = rodar_orgao(str(ug))
    except Exception as exc:  # noqa: BLE001
        _log.warning("Painel de detectores do órgão %s degradou (seção 1-I): %s", ug, exc)
        return {"ok": False, "_nota": str(exc)[:160]}

    def _resumo_evidencia(r) -> str:
        # 1ª evidência (trecho) como resumo legível; sem inventar — vazio vira "—".
        ev = (r.evidencia or [{}])[0] if r.evidencia else {}
        trecho = str(ev.get("trecho") or "").strip().replace("\n", " ")
        if not trecho and r.valores:
            trecho = "; ".join(f"{k}={v}" for k, v in list(r.valores.items())[:3])
        return (trecho or "—")[:120]

    confirmados = [r for r in resultados if r.status == "confirmado" and not r.refutada]
    descartados = [r for r in resultados if r.status == "descartado" or r.refutada]
    nao_avaliaveis = [r for r in resultados if r.status == "nao_avaliavel"]
    linhas = [{
        "detector": r.detector,
        "score": r.score,
        "status": "descartado" if r.refutada else r.status,
        "evidencia": _resumo_evidencia(r),
        "tem_defesa": bool((r.explicacao_inocente or "").strip()),
        "explicacao_inocente": (r.explicacao_inocente or "").strip(),
    } for r in confirmados]
    return {
        "ok": True,
        "n_total": len(resultados),
        "confirmados": linhas,
        "n_confirmados": len(confirmados),
        "n_descartados": len(descartados),
        "n_nao_avaliaveis": len(nao_avaliaveis),
    }


def _tac_orgao(ug: str) -> dict:
    """§1-J — pagamento FORA de contrato regular (TAC/indenização) + emergencial/dispensa, NÍVEL ÓRGÃO.

    Reúne (reusando `reporting.detector_tac`): (a) o % e R$ que a UG pagou via Termo de Ajuste de Contas /
    indenização / reconhecimento de dívida (`tac_por_ug`); (b) a WORKLIST dos fornecedores da UG com maior
    TAC% e R$, marcando os com sede INDÍCIO/sem-Google (`worklist_tac_por_ug`); (c) a red flag IRMÃ
    emergencial/dispensa (`medir_emergencial`). É o achado FSERJ codificado como padrão de órgão. Bounded,
    degrada honesto. HONESTO: indício de contratação fora de licitação, NÃO acusação individual."""
    try:
        from compliance_agent.reporting import detector_tac as dt
        ug_m = dt.tac_por_ug(str(ug))
        emerg = dt.medir_emergencial(str(ug))
        worklist = dt.worklist_tac_por_ug(str(ug), top_n=12)
        # dispara quando o TAC da UG é relevante (≥ faixa mínima e há valor) ou há worklist/emergencial
        tac_relevante = (ug_m.get("pct", 0) >= dt._FAIXA_MIN) and (ug_m.get("total_tac", 0) > 0)
        ok = bool(tac_relevante or worklist.get("ok") or emerg.get("ok"))
        return {"ok": ok, "tac_ug": ug_m, "emergencial": emerg, "worklist": worklist}
    except Exception as exc:  # noqa: BLE001
        _log.warning("TAC/emergencial do órgão %s degradou (seção 1-J): %s", ug, exc)
        return {"ok": False, "_nota": str(exc)[:160]}


def _anomalia_receita_orgao(ug: str) -> dict:
    """§1-K — CRUZAMENTO DUMP DA RECEITA FEDERAL × FORNECEDORES (anomalias determinísticas por UG).

    Reusa a função PURA `reporting.anomalia_receita.anomalias_orgao`: cruza as OBs com o dump da Receita
    (`empresas_min`/`socios_receita`/`socios_reverso`) e flagra: (1) sem-fins-lucrativos recebendo
    (natureza '3xxx'), (2) rede/grupo — pessoas administrando ≥2 fornecedores do MESMO órgão + admin em
    muitos CNPJs (veículo de aluguel), (3) laranja/sócio-único de alto valor. Degrada honesto: se o dump
    não está ingerido, `ok=False` e a seção informa INDISPONÍVEL (≠ ausência de anomalia). Cadastral
    (anomalia 4) NÃO roda no hot-path (rede): fica off (`checar_cadastro=False`)."""
    try:
        from compliance_agent.reporting.anomalia_receita import anomalias_orgao
        return anomalias_orgao(str(ug))
    except Exception as exc:  # noqa: BLE001
        _log.warning("Anomalias Receita do órgão %s degradou (seção 1-K): %s", ug, exc)
        return {"ok": False, "_nota": str(exc)[:160]}


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
    # chaveia por (cnpj, valor) — o CNPJ é a identidade canônica. Chavear pelo nome funde
    # homônimos e quebra o mesmo fornecedor por variação de caixa/acentuação. O nome serve só p/ exibir.
    contagem: dict = defaultdict(lambda: {"n": 0, "total": 0.0, "favorecido": ""})
    for a in p["anos"]:
        for ln in p["por_ano"][a]["linhas"]:
            v = round(ln.get("valor") or 0.0, 2)
            if v < min_valor:
                continue
            cnpj = (ln.get("cnpj") or "").strip()
            # sem CNPJ não há identidade canônica confiável: cai p/ o nome como chave de exibição
            chave = (cnpj or f"nome::{ln['favorecido']}", v)
            g = contagem[chave]
            g["n"] += 1
            g["total"] += v
            g["favorecido"] = ln.get("favorecido") or g["favorecido"]  # nome só p/ exibição
    grupos = [{"favorecido": g["favorecido"], "valor": k[1], "n": g["n"], "total": g["total"],
               "cnpj": k[0] if not str(k[0]).startswith("nome::") else ""}
              for k, g in contagem.items() if g["n"] >= min_rep]
    grupos.sort(key=lambda x: -x["total"])
    return grupos


def _secao_sei_risco_md(add, ctx: dict) -> None:
    """Seção 1-E (órgão) — processos SEI já triados de RISCO (sei_ficha) × OB paga pela UG. Indício, não prova."""
    def _brl(v):
        return f"{(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    add("## 1-D.1. PROCESSOS SEI DE RISCO PAGOS PELA UG (PERÍCIA DOCUMENTAL × OB)")
    add("")
    add("> Cruza os **processos SEI já triados** (perícia documental — `sei_ficha`) com os **pagamentos (OB)** desta "
        "UG: processos de **risco alto/médio** que efetivamente receberam recursos — prioriza a apuração por onde o "
        "dinheiro andou. **Indício, não prova** — risco interno de triagem; presunção de regularidade.")
    add("")
    try:
        from compliance_agent import correlacao_sei
        itens = correlacao_sei.processos_risco_de_orgao(ctx.get("ug", ""))
    except Exception as e:  # noqa: BLE001
        add(f"_Cruzamento SEI×OB indisponível nesta execução ({str(e)[:60]}) — **INDISPONÍVEL**._")
        add("")
        return
    if not itens:
        add("_Nenhum processo SEI de risco (alto/médio) com OB paga localizado para esta UG — **INDISPONÍVEL** "
            "(a perícia documental SEI roda por sweep; pode não ter alcançado processos desta UG)._")
        add("")
        return
    import json as _json
    tot = sum(x.get("total") or 0 for x in itens)
    add(f"🟡 **{len(itens)}** processo(s) de risco com pagamento — **R$ {_brl(tot)}**:")
    add("")
    add("| Processo SEI | Risco | Pago (R$) | OBs | Objeto | 1ª red flag |")
    add("|---|:--:|---:|---:|---|---|")
    for x in itens[:20]:
        try:
            rf = _json.loads(x.get("red_flags") or "[]")
        except Exception:
            rf = []
        flag = (str(rf[0]) if rf else "")[:60].replace("|", "/")
        obj = (x.get("objeto") or "")[:45].replace("|", "/")
        risco = (x.get("nivel_risco") or "").replace("médio", "medio")
        emoji = "🔴" if risco == "alto" else "🟡"
        add(f"| {x.get('numero_sei')} | {emoji} {risco} | {_brl(x.get('total'))} | {x.get('n_obs')} | {obj} | {flag} |")
    add("")
    add("> 🟡 **Indício a apurar:** priorizar a leitura integral dos autos acima (maior risco × maior pagamento). **Indício, não prova.**")
    add("")


# status de contrato (TCE-RJ Dados Abertos) → vigente (ativo) vs encerrado/arquivado
_ST_ATIVO = ("ativo", "em aberto", "aguard", "aprova", "altera", "edi")
_ST_ARQUIV = ("encerrad", "cancelad", "rescind", "extint", "conclu")


def _classe_contrato(status: str) -> tuple[str, str]:
    s = (status or "").strip().lower()
    if any(k in s for k in _ST_ARQUIV):
        return ("⚪ ARQUIVADO", "arquivado")
    if any(k in s for k in _ST_ATIVO):
        return ("🟢 ATIVO", "ativo")
    return ("· —", "indef")


def _secao_contratos_fornecedor_md(add, ctx: dict) -> None:
    """CONTRATOS POR FORNECEDOR — para os maiores fornecedores PJ pagos pela UG, lista os contratos (TCE-RJ
    Dados Abertos `contratos_tcerj`) ATIVOS × ARQUIVADOS, com objeto, processo, vigência, critério de julgamento,
    valor CONTRATADO × valor efetivamente PAGO pela UG. Responde 'que contratos o órgão tem, quais ativos/
    arquivados, qual o objeto, quanto pagou'. Indício/checagem documental, não acusação."""
    import sqlite3
    ug = str(ctx.get("ug") or "")
    add("## 1-L. CONTRATOS POR FORNECEDOR (ATIVOS × ARQUIVADOS · OBJETO · CONTRATADO × PAGO)")
    add("")
    add("> Para cada maior fornecedor PJ pago por esta UG, os **contratos registrados no TCE-RJ (Dados Abertos)** — "
        "**vigentes (ativos)** e **encerrados/arquivados** — com **objeto**, processo, vigência, critério de "
        "julgamento e **valor contratado**. Confronta-se com o **pago pela UG** (espelho TFE — magnitude movimentada). "
        "Contrato registrado em **unidade diversa** desta UG é marcado (◇) — é a carteira do fornecedor, contexto. "
        "**Checagem documental, não acusação** (presunção de legitimidade; só a NF/medição fecha valor).")
    add("")
    if not ug:
        add("_UG não resolvida — **INDISPONÍVEL**._"); add(""); return
    con = sqlite3.connect(_DB); con.row_factory = sqlite3.Row
    try:
        forns = con.execute(
            "SELECT favorecido_cpf cnpj, MAX(favorecido_nome) nome, ROUND(SUM(valor),2) pago, COUNT(*) n "
            "FROM ordens_bancarias WHERE ug_codigo=? AND length(favorecido_cpf)=14 AND valor>0 "
            "GROUP BY favorecido_cpf ORDER BY SUM(valor) DESC LIMIT 50", (ug,)).fetchall()
        nome_ug = (ctx.get("nome") or "").lower()
        algum = False
        sem_contrato: list[str] = []
        for f in forns:
            contratos = con.execute(
                "SELECT objeto, processo, ano_processo, valor_contrato, valor_pago, status, vig_inicio, vig_fim, "
                "criterio_julgamento, unidade FROM contratos_tcerj WHERE cnpj=? "
                "ORDER BY (CASE WHEN lower(status) LIKE 'ativo%' OR lower(status) LIKE 'em aberto%' THEN 0 ELSE 1 END), "
                "valor_contrato DESC", (f["cnpj"],)).fetchall()
            if not contratos:
                sem_contrato.append(f"{(f['nome'] or '')[:34]} (R$ {moeda(f['pago'])})")
                continue
            algum = True
            n_at = sum(1 for c in contratos if _classe_contrato(c["status"])[1] == "ativo")
            n_ar = sum(1 for c in contratos if _classe_contrato(c["status"])[1] == "arquivado")
            cnpj_fmt = f["cnpj"]
            add(f"### {(f['nome'] or '—').strip()} — CNPJ {cnpj_fmt}")
            add(f"**Pago por esta UG:** R$ {moeda(f['pago'])} em {f['n']} OBs · "
                f"**Contratos TCE-RJ:** {len(contratos)} ({n_at} ativo(s), {n_ar} arquivado(s)).")
            add("")
            add("| Situação | Objeto | Processo | Vigência | Critério | Contratado (R$) | Pago no contrato (R$) |")
            add("|:--|:--|:--|:--:|:--:|--:|--:|")
            for c in contratos[:50]:
                badge = _classe_contrato(c["status"])[0]
                obj = (c["objeto"] or "—").strip().replace("|", "/").replace("\n", " ")[:90]
                proc = (c["processo"] or "—").replace("|", "/")
                uni = (c["unidade"] or "").strip().lower()
                marca = " ◇" if (uni and uni not in nome_ug and nome_ug not in uni) else ""
                vig = f"{(c['vig_inicio'] or '?')}→{(c['vig_fim'] or '?')}"
                crit = (c["criterio_julgamento"] or "—")[:18]
                vc = moeda(c["valor_contrato"]) if c["valor_contrato"] else "—"
                vp = moeda(c["valor_pago"]) if c["valor_pago"] else "n/d"
                add(f"| {badge}{marca} | {obj} | {proc} | {vig} | {crit} | {vc} | {vp} |")
            add("")
            if len(contratos) > 12:
                add(f"> _(+{len(contratos) - 12} contrato(s) deste fornecedor omitido(s) — ver xlsx)._"); add("")
        if not algum:
            add("_Nenhum dos maiores fornecedores desta UG tem contrato no `contratos_tcerj` (cobertura TCE-RJ "
                "parcial, ou repasses intragovernamentais sem contrato) — **INDISPONÍVEL ≠ ausência de contrato.**_")
            add("")
        if sem_contrato:
            add(f"> **Sem contrato no TCE-RJ (entre os maiores pagos):** {'; '.join(sem_contrato[:10])}. "
                "Pode ser repasse intragovernamental, contrato não coletado (cobertura parcial) ou execução "
                "fora de contrato — **a apurar, INDISPONÍVEL ≠ 0**.")
            add("")
        add("> **Vigência ativa com pagamento, ou objeto divergente da finalidade da UG, ou critério não "
            "competitivo (dispensa/inexigibilidade) → priorizar leitura do processo. Indício, não prova.**")
        add("")
    except Exception as e:  # noqa: BLE001 — degrada honesto
        add(f"_Seção de contratos indisponível nesta execução ({str(e)[:70]}) — **INDISPONÍVEL**._"); add("")
    finally:
        con.close()


def _quadrante_persecucao(r: dict) -> dict:
    """SEGUNDO eixo do scoring (manual): risco de PUNIÇÃO × risco de ACHADO → quadrante de persecução.
    Reusa `compliance_agent.priorizacao` sobre uma linha do ranking de DD (que já traz codigo/total_pago/
    score/cnpj). HONESTO: só para fornecedor com indício (grau ≠ 🟢) — sem achado não há o que perseguir, e
    materialidade isolada não justifica um quadrante. Para 🟢 devolve {'mostra': False}."""
    if r.get("grau") == "🟢" or not (r.get("codigos") or []):
        return {"mostra": False}
    from compliance_agent import priorizacao as _pz
    achados = [{"codigo": c, "cnpj": r.get("cnpj")} for c in (r.get("codigos") or [])]
    rp = _pz.risco_punicao(achados, total_pago=r.get("total_pago"))
    q = _pz.quadrante(risco_achado=r.get("score") or 0, risco_punicao=rp["score"])
    return {"mostra": True, "quadrante": q, "rotulo": _pz.rotulo_quadrante(q),
            "risco_punicao": rp["score"], "competencia": rp["competencia"].get("nota", "")}


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
    add("| # | Grau | Score | Fornecedor | Total pago (R$) | Indícios (hipóteses) | Quadrante de persecução | Proc. SEI |")
    add("|--:|:--:|--:|---|--:|---|:--|--:|")
    for i, r in enumerate(ranking, 1):
        cods = ", ".join(c.replace("H-", "") for c in (r.get("codigos") or [])) or "—"
        forn = f"{r['nome'][:42]} ({fmt_cnpj(r['cnpj'])})" if r.get("cnpj") else r["nome"][:42]
        qp = _quadrante_persecucao(r)
        qcel = f"`{qp['quadrante']}` — punição {qp['risco_punicao']:.0f}/100" if qp["mostra"] else "—"
        add(f"| {i} | {r['grau']} | {r['score']} | {forn} | {moeda(r['total_pago'])} | {cods} "
            f"| {qcel} | {len(r.get('processos_sei') or [])} |")
    add("")
    # legenda do 2º eixo (manual, seção "Scoring (2 eixos)"): risco de ACHADO × risco de PUNIÇÃO
    if any(_quadrante_persecucao(r)["mostra"] for r in ranking):
        add("> **Quadrante de persecução** (2º eixo do scoring): cruza o *risco de achado* (Score acima — "
            "probabilidade de o indício ser real) com o *risco de punição* (viabilidade de responsabilização: "
            "materialidade do valor + tipificação legal da hipótese + autoria identificável + competência). "
            "`alto-alto` = **prioritário** (provável e punível, atacar primeiro); `baixo-alto` = aprofundar a "
            "apuração (punível se confirmado); `alto-baixo` = inteligência de padrão (monitorar). Indício ≠ acusação.")
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
    add("> Cruza o CNPJ de cada fornecedor com a **verificação de sede** (PREFERINDO o Google — Geocoding + "
        "Address Validation + Places; fallback à base cartográfica aberta/OSM) para checar se a **sede "
        "declarada existe e é edificada** — afastando (ou sinalizando) empresa de fachada. "
        "Veredito honesto: **AFASTADO** = sede real/edificada; **INDÍCIO** = ponto possivelmente baldio/precário "
        "(a verificar in loco/imagem); **INDISPONÍVEL** = sem conclusão. **INDISPONÍVEL ≠ inexistência** — a "
        "cobertura na periferia é incompleta, e satélite no nível da rua nunca acusa baldio "
        "(só Street View/in loco conclui).")
    add("")
    if not er.get("ok"):
        cob = (f"0 de {er.get('n_forn', 0)}") if er.get("n_forn") else "0"
        add(f"_Ainda sem endereços verificados para os fornecedores desta UG ({cob} verificados). O sweep de "
            "sedes (`tools/sweep_sede_google.py`, fallback OSM) cobre o universo de sedes incrementalmente — "
            "esta seção se preenche à medida que avança._")
        add("")
        return
    _fonte = er.get("fonte", "OSM")
    selo = ("[Google: Geocoding+Address Validation+Places]" if _fonte == "GOOGLE"
            else f"[fonte mista: {er.get('n_google', 0)} Google + OSM]" if _fonte == "MISTA"
            else "[base cartográfica aberta/OSM]")
    add(f"**Cobertura:** {er['n_verificados']} de {er['n_forn']} fornecedores PJ já verificados "
        f"({er['n_verificados']/(er['n_forn'] or 1)*100:.0f}%) — {selo}. "
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


def _secao_beneficios_md(add, ctx: dict) -> None:
    """Seção 1-F — benefícios sociais dos sócios/administradores (cruzamento de laranja). Dado + leitura + conclusão."""
    from compliance_agent.reporting import beneficios_view as bv
    b = ctx.get("beneficios_socios") or {}
    add("## 1-F. BENEFÍCIOS SOCIAIS DOS SÓCIOS/ADMINISTRADORES (INDÍCIO DE LARANJA)")
    add("")
    add("> Cruza o **CPF dos sócios e administradores** do QSA dos fornecedores com os **benefícios de "
        "subsistência** por CPF (Bolsa Família, BPC, Auxílio Emergencial, PETI, Garantia-Safra, Seguro-Defeso — "
        "Portal da Transparência/CGU). Quem é **dono/gestor** de empresa que recebe recursos públicos **e** "
        "recebe benefício de subsistência é **indício clássico de testa-de-ferro (laranja)** — interposição de "
        "pessoas (art. 337-F CP; art. 11 Lei 8.429/92). O CPF do QSA vem **mascarado** (LGPD); resolvemos via "
        "fontes oficiais (favorecidos PF + doadores do TSE). **INDISPONÍVEL ≠ ausência de benefício.**")
    add("")
    if not b.get("ok"):
        add("_Ainda sem QSA com CPF mascarado dos fornecedores desta UG, ou a varredura de benefícios "
            "(`tools/beneficios_sweep`) ainda não cobriu este conjunto — o sweep roda em segundo plano e esta "
            "seção se preenche à medida que avança (INDISPONÍVEL, não ausência)._")
        add("")
        return
    add(bv.leitura(b, escopo="desta UG"))
    add("")
    add(f"- Sócios/administradores no QSA (CPF mascarado): **{b['total_qsa']}** · já varridos: **{b['n_varridos']}**")
    add(f"- CPF resolvido (cruzável): **{b['n_resolvidos']}** · benefício verificado: **{b['n_verificados']}** "
        f"(**{b['cobertura']}%** de cobertura) · **INDISPONÍVEL:** {b['n_indisponivel']}")
    add(f"- **Com benefício de subsistência (indício de laranja):** {b['n_com_beneficio']} vínculo(s) · "
        f"{b.get('n_pessoas_beneficio', 0)} pessoa(s)")
    add("")
    itens = b.get("itens") or []
    if itens:
        add("| Fornecedor | Sócio/Administrador | Papel | Benefício | Fonte do CPF |")
        add("|---|---|---|---|---|")
        _fonte = {"favorecidos_pf": "favorecidos PF", "tse_doadores": "doadores TSE"}
        for it in itens[:20]:
            tipos = ", ".join(it.get("tipos") or []) or "(tipo não detalhado)"
            forn = (it.get("razao") or "—")[:38]
            add(f"| {forn} | {(it.get('nome') or '—')[:34]} | {it.get('papel', '')} | {tipos} | "
                f"{_fonte.get(it.get('fonte', ''), it.get('fonte', '') or '—')} |")
        if len(itens) > 20:
            add(f"\n> (+{len(itens) - 20} vínculos com indício — detalhe na planilha XLSX.)")
        add("")
        add("> 🟡 **Indício a confirmar:** receber benefício de subsistência **e** ser sócio/gestor de "
            "fornecedor do Estado sugere **interposição de pessoas (laranja)** — confirmar no contrato social, "
            "na procuração e no processo SEI. **Indício, não prova.** CPF de uso interno (LGPD).")
        add("")


def _secao_tce_md(add, ctx: dict) -> None:
    """Seção 1-G — sanções do TCE-RJ ao órgão (controle externo). Fato JÁ JULGADO, não indício nosso."""
    from compliance_agent.reporting import penalidades_tce_view as pv
    t = ctx.get("penalidades_tce") or {}
    add("## 1-G. SANÇÕES DO TCE-RJ AO ÓRGÃO (CONTROLE EXTERNO)")
    add("")
    add("> Cruza o órgão desta UG com as **condenações do Tribunal de Contas do Estado (TCE-RJ)** — multas e "
        "**débitos** (imputação de devolução de recursos) em processos de prestação/tomada de contas. É o sinal "
        "mais **direto** de irregularidade, pois já foi **julgado pela Corte de Contas** (fato, não indício "
        "interno). O vínculo nome-TCE↔UG usa um **mapa curado** (o TCE usa nome abreviado); correspondências "
        "incertas são sinalizadas. **INDISPONÍVEL ≠ ausência de condenação.**")
    add("")
    if not t.get("ok") or not t.get("n_condenacoes"):
        add(f"_{pv.leitura(t, 'este órgão')}_")
        add("")
        return
    add(pv.leitura(t, "este órgão"))
    add("")
    pt = t.get("por_tipo", {})
    deb = pt.get("DEBITO", {})
    mul = pt.get("MULTA", {})
    add(f"- Condenações: **{t['n_condenacoes']}** (responsáveis) em **{t.get('n_eventos', t['n_condenacoes'])}** "
        f"eventos distintos · **{t['n_processos']}** processo(s) · valor (sem dupla contagem solidária) "
        f"**R$ {moeda(t['valor_total'])}**")
    if deb:
        add(f"- **DÉBITO** (devolução ao erário): {deb.get('n', 0)} evento(s) · **R$ {moeda(deb.get('valor', 0))}**")
    if mul:
        add(f"- **MULTA**: {mul.get('n', 0)} evento(s) · **R$ {moeda(mul.get('valor', 0))}**")
    anos = t.get("por_ano", {})
    if anos:
        add("- Por ano: " + " · ".join(f"{a}: {v['n']}× (R$ {moeda(v['valor'])})" for a, v in anos.items()))
    add("")
    itens = t.get("itens") or []
    if itens:
        add("| Processo | Ano | Tipo | Valor (R$) | Resp. | Natureza | Sessão | Órgão (TCE) |")
        add("|---|---|---|---|---|---|---|---|")
        for it in itens[:20]:
            flag = " ⚠" if it.get("confianca") == "media" else ""
            resp = f"{it.get('n_resp', 1)}×" if it.get("n_resp", 1) > 1 else "1"
            add(f"| {it['processo']} | {it.get('ano', '—')} | {it['tipo']} | {moeda(it['valor'])} | {resp} | "
                f"{it['grupo_natureza'][:22]} | {it['data_sessao']} | {it['orgao_tce'][:24]}{flag} |")
        if len(itens) > 20:
            add(f"\n> (+{len(itens) - 20} eventos — detalhe completo na base do TCE-RJ.)")
        add("")
        if t.get("tem_media"):
            add("> ⚠ Linhas marcadas têm **correspondência de órgão incerta** (extinção/reorganização) — "
                "confirmar o ente exato no número do processo antes de imputar à gestão atual.")
            add("")


def _secao_concentracao_grupo_md(add, ctx: dict) -> None:
    """Seção 1-H — concentração OCULTA por grupo econômico (cartel / concorrência fictícia). Colapsa os
    fornecedores por sócio em comum: muitos CNPJs que parecem concorrentes mas são UM grupo. Indício, não prova."""
    cg = ctx.get("concentracao_grupo") or {}
    add("## 1-H. CONCENTRAÇÃO OCULTA POR GRUPO ECONÔMICO (CARTEL / CONCORRÊNCIA FICTÍCIA)")
    add("")
    add("> Colapsa os fornecedores da UG por **grupo econômico** (CNPJs ligados por **sócio em comum**, dedup "
        "por raiz). Quando muitos CNPJs que se apresentam como **concorrentes** são na verdade **um só grupo**, "
        "a diversidade é **fictícia** — possível concorrência simulada/fracionamento ou *bid rigging* "
        "(**Art. 90 Lei 8.666/93** · **Art. 337-F CP** · **Art. 36 Lei 12.529/2011 — CADE**). É **indício a "
        "corroborar** com editais/licitantes (SEI/PNCP), nunca acusação: mercado restrito explica parte da "
        "concentração, e **QSA mascarado/INDISPONÍVEL ≠ grupo afastado**. Destinatário natural de um achado "
        "confirmado: **Ministério Público** e **CADE**.")
    add("")
    if not cg.get("ok"):
        _nota = cg.get("_nota") or "rede societária (QSA)/DuckDB indisponível ou sem fornecedores PJ para esta UG"
        add(f"_Concentração por grupo indisponível nesta execução ({_nota}). Rode "
            "`python -m compliance_agent.grafo_cartel --captura 20` ou ingira o QSA dos fornecedores para o "
            "detalhe. **INDISPONÍVEL não é prova de ausência de grupo.**_")
        add("")
        return
    add(f"**Panorama:** {cg.get('n_cnpjs', 0)} CNPJs colapsam em **{cg.get('n_grupos', 0)} grupos** "
        f"(**{cg.get('n_grupos_multi', 0)}** multi-CNPJ). HHI por CNPJ {cg.get('hhi_cnpj', 0)} → por grupo "
        f"**{cg.get('hhi_grupo', 0)}** (Δ {cg.get('delta_hhi', 0):+}); maior grupo = "
        f"{cg.get('top_grupo_share', 0):.1f}% do valor.")
    add("")
    grupos_multi = [g for g in (cg.get("grupos") or []) if g.get("n_raizes", 0) >= 2]
    if grupos_multi:
        add("| # | Grupo (raiz) | Nº CNPJs | Nº raízes | Share % | Total (R$) | Maior CNPJ do grupo |")
        add("|--:|---|--:|--:|--:|--:|---|")
        for i, g in enumerate(grupos_multi[:50], 1):
            add(f"| {i} | {fmt_cnpj(g['grupo']) if g.get('grupo') else '—'} | {g['n_cnpjs']} | {g['n_raizes']} | "
                f"{g['share']:.1f}% | {moeda(g['total'])} | {(g.get('top_nome') or '—')[:36]} |")
        add("")
    if cg.get("indicio"):
        mm = cg.get("maior_grupo_multi") or {}
        add(f"> 🟡 **Indício:** o maior grupo econômico reúne **{mm.get('n_cnpjs', 0)} CNPJs** "
            f"(**{mm.get('n_raizes', 0)} raízes** distintas — aparentes concorrentes) e concentra "
            f"**{mm.get('share', 0):.1f}%** do valor pago pela UG (R$ {moeda(mm.get('total', 0))}; ex.: "
            f"**{(mm.get('top_nome') or '—')[:40]}**). Diversidade fictícia desse porte é *red flag* de "
            "concorrência simulada/cartel (Art. 90 Lei 8.666; Art. 337-F CP; Art. 36 Lei 12.529-CADE) — "
            "corroborar os licitantes nos editais (SEI/PNCP) e, se confirmado, comunicar **MP e CADE**. "
            "Indício ≠ prova; mercado restrito explica parte.")
    else:
        add("> 🟢 Nenhum grupo econômico multi-CNPJ concentra fatia relevante do valor pago — sem indício de "
            "concorrência fictícia entre os fornecedores analisados. Isso **não** afasta cartel na cauda nem "
            "grupos com QSA ainda não ingerido (INDISPONÍVEL ≠ afastado).")
    add("")


def _secao_painel_detectores_md(add, ctx: dict) -> None:
    """Seção 1-I — PAINEL DE DETECTORES (spec de licitações). Visão UNIFICADA dos detectores no schema do spec
    (§1.4): só os `confirmado` (não refutados) no topo, com a defesa inocente visível; um resumo honesto dos
    `descartado`/`nao_avaliavel` em 1 linha. Itera sobre a lista de `ResultadoDetector` (extensível a P/C/E/X —
    não hardcode J1). Degrada honesto: se o orquestrador falhou, INFORMA INDISPONÍVEL e a seção NÃO some."""
    pd = ctx.get("painel_detectores") or {}
    add("## 1-I. PAINEL DE DETECTORES (SPEC DE LICITAÇÕES)")
    add("")
    add("> Visão **unificada** dos detectores de corrupção em licitações no schema fechado do spec (score com "
        "âncoras fixas · status `confirmado`/`descartado`/`nao_avaliavel` · passo exculpatório adversarial). "
        "Consolida a leitura por detector (hoje **J1** conluio/cartel — a concentração-grupo da §1-H é a "
        "evidência objetiva por trás dele; aqui não se repete a tabela, só o veredito do detector). "
        "Extensível aos demais cards (P/C/E/X). **Indício ≠ acusação**; `descartado` = afastado pela checagem "
        "inversa; `nao_avaliavel`/**INDISPONÍVEL ≠ 0** (ausência de juízo, não de risco).")
    add("")
    if not pd.get("ok"):
        _nota = pd.get("_nota") or "orquestrador de detectores (DuckDB/QSA/LLM) indisponível nesta execução"
        add(f"_Painel de detectores **INDISPONÍVEL** nesta execução ({_nota}) — degrada honesto. "
            "Rode os detectores (`compliance_agent.detectores.rodar_orgao`) com a base/QSA disponível. "
            "**INDISPONÍVEL não é prova de ausência de indício.**_")
        add("")
        return
    confirmados = pd.get("confirmados") or []
    if confirmados:
        add(f"**{pd.get('n_confirmados', 0)} detector(es) com indício CONFIRMADO** (sobreviveram à checagem "
            f"inversa), de {pd.get('n_total', 0)} avaliado(s):")
        add("")
        add("| Detector | Score | Status | Evidência (resumo) | Defesa inocente? |")
        add("|---|--:|---|---|---|")
        for r in confirmados:
            defesa = "sim" if r.get("tem_defesa") else "—"
            add(f"| {r['detector']} | {r['score']:.2f} | 🔴 {r['status']} | {r['evidencia']} | {defesa} |")
        add("")
        # defesa inocente visível (honestidade: exculpatória sempre à vista, não escondida)
        com_defesa = [r for r in confirmados if r.get("explicacao_inocente")]
        if com_defesa:
            add("> **Hipótese inocente registrada** (presunção de legitimidade — a verificar antes de qualquer "
                "juízo):")
            for r in com_defesa:
                add(f"> - **{r['detector']}:** {r['explicacao_inocente'][:240]}")
            add("")
        add("> 🔴 **Indício a apurar:** os detectores acima sobreviveram ao passo exculpatório — são "
            "indícios objetivos a corroborar nos editais/licitantes/contratos (SEI/PNCP), nunca acusação.")
        add("")
    else:
        add("> 🟢 **Nenhum detector com indício confirmado** nesta execução — sem alarme do spec de licitações "
            "para esta UG. Isso **não** afasta risco na cauda nem detectores ainda INDISPONÍVEIS.")
        add("")
    # resumo honesto dos afastados/indisponíveis em 1 linha
    add(f"> _Resumo: **{pd.get('n_descartados', 0)}** afastado(s) pelo passo exculpatório (checagem inversa), "
        f"**{pd.get('n_nao_avaliaveis', 0)}** indisponível(is) (`nao_avaliavel` — dado/LLM ausente, não "
        "avaliado). INDISPONÍVEL ≠ ausência de indício._")
    add("")


def _secao_tac_md(add, ctx: dict) -> None:
    """Seção 1-J — pagamento FORA de contrato regular (TAC/indenização) + emergencial/dispensa, com a
    WORKLIST dos fornecedores de maior TAC% (marcando sede INDÍCIO/sem-Google). Achado FSERJ como padrão."""
    tj = ctx.get("tac_orgao") or {}
    add("## 1-J. PAGAMENTO FORA DE CONTRATO REGULAR (TAC/INDENIZAÇÃO) + EMERGENCIAL")
    add("")
    add("> Quanto a UG pagou **FORA de contrato regular licitado** — via **Termo de Ajuste de Contas (TAC)**, "
        "**indenização** ou **reconhecimento de dívida** (regularização *a posteriori*: art. 59 par. único Lei "
        "8.666/93; art. 149 Lei 14.133/21) — e quanto saiu por **emergencial/dispensa**. Recorrente e vultoso, é "
        "indício SISTÊMICO de **contratação informal/emergencial perpetuada e fuga ao dever de licitar** (art. 37 "
        "CF/88). **Indício quantitativo da PRÁTICA do órgão, NÃO acusação individual**; INDISPONÍVEL (sem texto na "
        "OB) ≠ 0%.")
    add("")
    if not tj.get("ok"):
        _nota = tj.get("_nota") or "sem TAC/indenização nem emergencial relevante na observação das OBs desta UG"
        add(f"_Sem padrão relevante de TAC/indenização ou emergencial para esta UG ({_nota}). "
            "**INDISPONÍVEL ≠ ausência** — depende da observação preenchida na OB._")
        add("")
        return
    ug_m = tj.get("tac_ug") or {}
    emerg = tj.get("emergencial") or {}
    wl = tj.get("worklist") or {}
    # (a) TAC sistêmico da UG
    add(f"**TAC/indenização (sistêmico da UG):** **{ug_m.get('pct', 0):.1f}%** de R$ {moeda(ug_m.get('total', 0))} "
        f"pagos saíram fora de contrato regular — **R$ {moeda(ug_m.get('total_tac', 0))}** em "
        f"{ug_m.get('n_tac', 0)} OB(s). _Cobertura: {ug_m.get('cobertura', '—')}._")
    add("")
    if ug_m.get("pct", 0) >= 25:
        add(f"> 🔴 **Red flag (off-contract spend):** mais de um quarto do que a UG pagou ({ug_m.get('pct', 0):.0f}%) "
            "saiu por TAC/indenização — apurar a existência de contrato, a causa da 'dívida' e a regularidade da "
            "despesa (art. 59 par. único Lei 8.666; art. 149 Lei 14.133; art. 10 Lei 8.429/92).")
        add("")
    # (b) emergencial / dispensa (red flag irmã)
    if emerg.get("ok"):
        add(f"**Emergencial/dispensa (red flag irmã):** **{emerg.get('n_emerg', 0)}** OB(s) citam "
            f"EMERGENCIAL/DISPENSA na observação — R$ {moeda(emerg.get('total_emerg', 0))} "
            f"({emerg.get('pct', 0):.1f}% do valor com observação). Dispensa/emergência reiterada (art. 75 IV/VIII "
            "Lei 14.133; art. 24 IV Lei 8.666) reforça a hipótese de fuga ao certame. _Indício a verificar._")
        add("")
    # (c) worklist dos fornecedores com maior TAC%
    forn = wl.get("fornecedores") or []
    if forn:
        add(f"**Worklist — fornecedores da UG com maior pagamento via TAC/indenização** "
            f"({wl.get('n_fornecedores', 0)} de maior materialidade):")
        add("")
        add("| # | Fornecedor (CNPJ) | TAC % | R$ via TAC | Total pago | Sede |")
        add("|--:|---|--:|--:|--:|:--|")
        for i, f in enumerate(forn, 1):
            nome = f"{(f.get('nome') or '—')[:40]} ({fmt_cnpj(f['cnpj'])})" if f.get("cnpj") else (f.get("nome") or "—")[:40]
            if f.get("sede_indicio"):
                marca = ("🟡 sede INDÍCIO" + (" · sem Google" if f.get("sem_google") else "")
                         if f.get("sede_status") == "INDICIO" else "🟡 sem Google")
            elif f.get("sede_status") == "AFASTADO":
                marca = "✔ sede real"
            else:
                marca = "… INDISPONÍVEL"
            add(f"| {i} | {nome} | {f.get('pct', 0):.0f}% | {moeda(f.get('total_tac', 0))} | "
                f"{moeda(f.get('total', 0))} | {marca} |")
        add("")
        suspeitos = [f for f in forn if f.get("sede_indicio")]
        if suspeitos:
            nomes = "; ".join(f"**{(s.get('nome') or '—')[:30]}** ({s.get('pct', 0):.0f}% TAC)" for s in suspeitos[:6])
            add(f"> 🟡 **Co-suspeitos a priorizar:** {len(suspeitos)} fornecedor(es) da worklist têm **sede com "
                f"indício de fachada** (INDÍCIO ou sem negócio no Google) ALÉM do alto TAC% — {nomes}. A combinação "
                "**alto pagamento fora de contrato + sede-fachada** eleva a hipótese de empresa de fachada/"
                "interposição; puxar o contrato, o processo SEI e a verificação de sede. **Indício ≠ acusação.**")
        else:
            add("> 🟡 **A verificar:** os fornecedores acima concentram pagamento via TAC/indenização (fora de "
                "contrato regular). Nenhum, entre os verificados, tem sede com indício de fachada — mas o alto "
                "TAC% por si é indício de contratação fora de licitação a apurar. **INDISPONÍVEL ≠ afastado.**")
        add("")


def _secao_anomalia_receita_md(add, ctx: dict) -> None:
    """Seção 1-K — CRUZAMENTO RECEITA FEDERAL × FORNECEDORES (anomalias determinísticas). Cruza as OBs com
    o dump da Receita (`empresas_min`/`socios_receita`/`socios_reverso`): sem-fins recebendo, rede/grupo,
    veículo de aluguel, laranja/sócio-único. Indício ≠ acusação; INDISPONÍVEL ≠ ausência."""
    ar = ctx.get("anomalia_receita") or {}
    add("## 1-K. CRUZAMENTO RECEITA FEDERAL — ANOMALIAS NOS FORNECEDORES")
    add("")
    add("> Cruza os pagamentos (OB) com o **dump da Receita Federal** (natureza jurídica em `empresas_min`; "
        "quadro societário REAL em `socios_receita`; busca reversa em `socios_reverso`) para flagar padrões "
        "**determinísticos** anômalos: **(1)** entidade **sem fins lucrativos** (associação/fundação/OS) "
        "recebendo como fornecedor; **(2)** **rede/grupo** — a mesma pessoa administrando vários fornecedores "
        "do órgão (concorrência fictícia) e administradores presentes em MUITOS CNPJs (veículo de aluguel); "
        "**(3)** **laranja/sócio-único** de alto valor. **Indício ≠ acusação**; entes públicos e instituições "
        "legítimas de ensino/pesquisa **não** são anomalia; **CPF de sócio mascarado (LGPD)**.")
    add("")
    if not ar.get("ok"):
        _nota = ar.get("_nota") or "dump da Receita não ingerido nesta base"
        add(f"_Cruzamento com a Receita indisponível nesta execução ({_nota}). Rode "
            "`python -m tools.socios_dump_sweep` para ingerir o dump. **INDISPONÍVEL ≠ ausência de anomalia.**_")
        add("")
        return
    cov = ar.get("cobertura") or {}
    add(f"**Cobertura honesta:** dos **{cov.get('n_fornecedores_pj', 0)}** fornecedores PJ da UG, "
        f"**{cov.get('n_no_empresas_min', 0)}** ({cov.get('pct_empresas_min', 0):.0f}%) constam no dump de "
        f"empresas e **{cov.get('n_com_qsa', 0)}** ({cov.get('pct_qsa', 0):.0f}%) têm quadro societário (QSA) "
        "ingerido. Os demais seguem **INDISPONÍVEL** (não 'limpos').")
    add("")

    # (1) sem fins lucrativos
    sf = ar.get("sem_fins_lucrativos") or []
    add("### (1) Entidades SEM FINS LUCRATIVOS recebendo como fornecedor")
    add("")
    if sf:
        add("| # | Razão social | Natureza | Total recebido (R$) | Observação |")
        add("|--:|---|---|--:|---|")
        for i, r in enumerate(sf, 1):
            obs = "ensino/pesquisa/estágio — provável legítimo (ressalva)" if r.get("ressalva") else "🟡 a apurar o objeto/credenciamento"
            add(f"| {i} | {(r['razao_social'] or '—')[:42]} | {r.get('natureza_txt', '')} | "
                f"{moeda(r['total'])} | {obs} |")
        add("")
        flag = [r for r in sf if not r.get("ressalva")]
        if flag:
            top = flag[0]
            add(f"> 🟡 **Indício:** {len(flag)} entidade(s) sem fins lucrativos sem perfil claro de "
                f"ensino/pesquisa recebem como fornecedor — a maior é **{(top['razao_social'] or '—')[:40]}** "
                f"(R$ {moeda(top['total'])}). Associação/fundação/OS contratada para fornecer bens/serviços é "
                "*red flag* de **terceirização via OS / contrato de gestão** a confiar o objeto, o credenciamento "
                "e a prestação de contas (Lei 9.637/98; Lei 13.019/2014 — MROSC). Indício, não acusação.")
        else:
            add("> 🟢 As entidades sem fins lucrativos identificadas têm perfil de ensino/pesquisa/estágio "
                "(ressalva) — recebimento provavelmente legítimo.")
        add("")
    else:
        add("_Nenhum fornecedor com natureza jurídica sem fins lucrativos ('3xxx') entre os cobertos pelo dump._")
        add("")

    # (2) rede/grupo
    rede = ar.get("rede_mesmo_orgao") or []
    veic = ar.get("veiculos_aluguel") or []
    add("### (2) Rede / grupo — administradores compartilhados")
    add("")
    if rede:
        add("| # | Administrador (doc) | Nº fornecedores do órgão | Qualificações |")
        add("|--:|---|--:|---|")
        for i, r in enumerate(rede[:15], 1):
            add(f"| {i} | {(r['nome_socio'] or '—')[:34]} ({r.get('doc_socio', '')}) | "
                f"{r['n_fornecedores']} | {(r.get('qualificacoes') or '—')[:34]} |")
        add("")
        top = rede[0]
        add(f"> 🟡 **Indício de grupo / concorrência fictícia:** **{len(rede)}** pessoa(s) administram **≥2** "
            f"fornecedores do MESMO órgão — ex.: **{(top['nome_socio'] or '—')[:34]}** em "
            f"**{top['n_fornecedores']}** fornecedores. Fornecedores aparentemente concorrentes sob a mesma "
            "administração sugerem **concorrência simulada/fracionamento** (Art. 90 Lei 8.666; Art. 337-F CP; "
            "Art. 36 Lei 12.529 — CADE), a corroborar nos certames (SEI/PNCP). **Indício ≠ prova.**")
        add("")
    else:
        add("_Nenhuma pessoa administrando ≥2 fornecedores do órgão entre os cobertos pelo QSA._")
        add("")
    if veic:
        add("**Administradores presentes em muitos CNPJs no Brasil (possível veículo de aluguel):**")
        add("")
        add("| # | Administrador (doc) | Nº de CNPJs (Brasil) |")
        add("|--:|---|--:|")
        for i, r in enumerate(veic[:40], 1):
            add(f"| {i} | {(r['nome_socio'] or '—')[:38]} ({r.get('doc_socio', '')}) | {r['n_cnpjs_brasil']} |")
        add("")
        add("> ⚠ **Ressalva importante:** aparecer em dezenas/centenas de CNPJs é o padrão de **executivos de "
            "grandes conglomerados legítimos** (ex.: diretores de instituições financeiras/holdings) — NÃO é, "
            "por si, anomalia. É *red flag* apenas quando casado com indícios de fachada/laranja no fornecedor "
            "específico. Listado para due diligence, não como acusação.")
        add("")

    # (3) laranja / sócio-único
    su = ar.get("socio_unico_alto_valor") or []
    add("### (3) Laranja / sócio-único de alto valor")
    add("")
    if su:
        add("| # | Razão social | Total recebido (R$) | Único administrador (qualif.) |")
        add("|--:|---|--:|---|")
        for i, r in enumerate(su[:15], 1):
            tag = " · sem-fins" if r.get("sem_fins") else ""
            add(f"| {i} | {(r['razao_social'] or '—')[:38]}{tag} | {moeda(r['total'])} | "
                f"{(r.get('socio_unico') or '—')[:24]} ({(r.get('qualificacao') or '—')[:16]}) |")
        add("")
        add("> 🟡 **Indício:** fornecedores de alto valor com **um único administrador** no QSA. Concentração "
            "de gestão num só sócio em contratos vultosos é *red flag* de **interposição de pessoas (laranja)** "
            "ou capacidade operacional incompatível — a confrontar com a estrutura real (funcionários, sede, "
            "capacidade técnica). **Indício ≠ acusação**; muitas PMEs legítimas têm sócio único.")
        add("")
    else:
        add("_Nenhum fornecedor de alto valor com administrador único entre os cobertos pelo QSA._")
        add("")

    # (4) situação cadastral (só se foi consultada)
    cad = ar.get("cadastro") or {}
    if cad.get("ok") and cad.get("achados"):
        add("### (4) Situação cadastral externa (amostra)")
        add("")
        add("| CNPJ-raiz | Situação | Motivo | Data |")
        add("|---|---|---|---|")
        for r in cad["achados"]:
            add(f"| {r['cnpj_basico']} | {r['situacao']} | {(r.get('descricao') or '—')[:30]} | {r.get('data_situacao', '')} |")
        add("")
        add("> 🔴 Fornecedor(es) com situação cadastral **irregular** (INAPTA/baixada/suspensa) na Receita — "
            "incompatível com o recebimento de pagamento público; conferir a vigência contratual. Fonte: "
            "minhareceita.org (amostra bounded; cache em `cadastro_externo`).")
        add("")

    add("_Ressalvas: indício ≠ acusação (presunção de legitimidade); INDISPONÍVEL ≠ 0 (cobertura do dump "
        "informada acima); entes públicos (natureza '1xxx') e instituições legítimas de ensino/pesquisa não "
        "são anomalia; CPF de sócio PF mascarado por LGPD._")
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
    add(f"**Data:** {ctx['data']}  |  **Analista:** Controle Externo (automatizado)  |  **Fonte:** TFE-RJ (espelho de OBs, D-1 — magnitude movimentada; pagamento auditado = SIAFE)")
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
        for nome, val in list(p["por_favorecido_geral"].items())[:120]:
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
        for g in grupos[:40]:
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
    # 1-D.1. Processos SEI de risco já triados × OB paga pela UG (sintetiza a perícia documental no /orgao)
    _secao_sei_risco_md(add, ctx)
    # 1-L. Contratos por fornecedor (ativos × arquivados, objeto, contratado × pago) — TCE-RJ Dados Abertos
    _secao_contratos_fornecedor_md(add, ctx)
    # 1-E. Verificação de realidade do endereço das sedes (as empresas são reais?)
    _secao_endereco_md(add, ctx)
    # 1-F. Benefícios sociais dos sócios/administradores (cruzamento de laranja — testa-de-ferro)
    _secao_beneficios_md(add, ctx)
    # 1-G. Sanções do TCE-RJ ao órgão (controle externo — fato já julgado)
    _secao_tce_md(add, ctx)
    # 1-H. Concentração OCULTA por grupo econômico (cartel / concorrência fictícia)
    _secao_concentracao_grupo_md(add, ctx)
    # 1-I. Painel de detectores (spec de licitações) — visão unificada dos ResultadoDetector (J1 + futuros)
    _secao_painel_detectores_md(add, ctx)
    # 1-J. Pagamento fora de contrato regular (TAC/indenização) + emergencial + worklist de co-suspeitos
    _secao_tac_md(add, ctx)
    # 1-K. Cruzamento Receita Federal — anomalias (sem-fins / rede-grupo / veículo de aluguel / laranja)
    _secao_anomalia_receita_md(add, ctx)

    # Tabelas de OBs por ano (pagamentos individuais a cada fornecedor)
    add("## 2. PAGAMENTOS (ORDENS BANCÁRIAS) POR ANO")
    add("")
    add("> Por exercício, as **maiores OBs** (materiais) e o fornecedor; a **lista completa** de cada "
        "pagamento está na **planilha XLSX** deste relatório. OB = pagamento definitivo; OBs de R$ 0,00 são "
        "estornos/regularizações.")
    add("")
    if p["tem_dados"]:
        TOP_OB_ANO = 40  # material ampliado (diretriz 2026-07-11: sem limite, tudo no PDF); cauda no XLSX
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
    add("## 3. ANÁLISE JURÍDICA E DE MÉRITO — PARECER PRELIMINAR")
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
    add("- **Dados:** SIAFE-Rio / Transparência Fiscal RJ (OBs) — `data/compliance.db`; mapa de UG `data/ug_canonico.json`; "
        "sanções **TCE-RJ** (`penalidades_tcerj`) por mapa curado órgão↔UG.")
    add("- **Normas:** Lei 14.133/2021; Lei 8.666/93; CF/88 Art. 37; metodologia TCU; ACFE Report to the Nations.")
    add("")
    add(f"_Gerado automaticamente em {ctx['data']}. Não substitui análise jurídica especializada._")
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
    pdf.cell(0, 9, _t("Triagem de Due Diligence dos fornecedores (fachada/laranja/cartel)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
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
        pdf.cell(0, 7, _t(f"Rodizio temporal de vencedores (bid rotation) - score {rod.get('score')}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
        _mc(pdf, 4.5, _t(f"Indício de cartel/conluio: {rod.get('n_campeoes')} fornecedores revezaram o 1o lugar "
                         f"em {rod.get('n_anos')} exercícios (dominância {rod.get('share_ring')}). Campeões: "
                         f"{camps}. OB expõe o vencedor, não os licitantes - corroborar no SEI/PNCP."))
        pdf.ln(1)
    ranking = dd.get("ranking") or []
    pdf.set_font(pdf._fam, "B", 10); pdf.cell(0, 7, _t(f"Ranking de risco - {len(ranking)} maiores fornecedores PJ"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    _tab_header(pdf, [("Grau", 12), ("Sc.", 10), ("Fornecedor", 70), ("Total (R$)", 30), ("Indícios", 20),
                      ("Persecução", 34), ("SEI", 10)])
    pdf.set_font(pdf._fam, "", 7)
    for r in ranking:
        cods = ", ".join(c.replace("H-", "") for c in (r.get("codigos") or [])) or "-"
        qp = _quadrante_persecucao(r)
        qcel = f"{qp['quadrante']} {qp['risco_punicao']:.0f}" if qp["mostra"] else "-"
        _tab_row(pdf, [(_t(r["grau"]), 12, "C"), (str(r["score"]), 10, "R"), (_t(r["nome"])[:44], 70, "L"),
                       (moeda(r["total_pago"]), 30, "R"), (_t(cods)[:13], 20, "L"),
                       (_t(qcel), 34, "L"),
                       (str(len(r.get("processos_sei") or [])), 10, "R")], h=4.6)
    procs = dd.get("processos_prioritarios") or []
    if procs:
        pdf.ln(1); pdf.set_font(pdf._fam, "", 7); pdf.set_text_color(80, 80, 80)
        _mc(pdf, 4, _t("Processos SEI a priorizar: " + ", ".join(procs[:80]) + (f" (+{len(procs)-80} no XLSX)" if len(procs) > 80 else "")))
        pdf.set_text_color(0, 0, 0)


def _secao_endereco_pdf(pdf, _t, ctx: dict) -> None:
    """PDF — realidade do endereço das sedes (as empresas são reais?)."""
    er = ctx.get("endereco_real") or {}
    pdf.ln(4); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 8, _t("Realidade do endereço das sedes (as empresas são reais?)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
    if not er.get("ok"):
        pdf.set_font(pdf._fam, "I", 8); pdf.set_text_color(110, 110, 110)
        _mc(pdf, 4.5, _t(f"Sem endereços verificados para esta UG ainda ({er.get('n_forn', 0)} fornecedores PJ). "
                         "O sweep de endereços cobre o universo incrementalmente."))
        pdf.set_text_color(0, 0, 0); return
    _selo = ("[Google: Geocoding+Address Validation+Places]" if er.get("fonte") == "GOOGLE"
             else f"[fonte mista: {er.get('n_google', 0)} Google + OSM]" if er.get("fonte") == "MISTA"
             else "[base cartográfica aberta/OSM]")
    _mc(pdf, 4.5, _t(f"Cobertura: {er['n_verificados']} de {er['n_forn']} fornecedores verificados {_selo}. "
                     f"Sede real (afastado): {er['afastado']} | com indício: {er['indicio']} | "
                     f"sem conclusão: {er['indisponivel']}. INDISPONÍVEL nao prova inexistência (cobertura "
                     "incompleta; satélite no nível da rua nunca acusa baldio)."))
    if er.get("indicios"):
        pdf.ln(1); _tab_header(pdf, [("Fornecedor (CNPJ)", 96), ("Nível", 24), ("Evidência", 60)])
        pdf.set_font(pdf._fam, "", 7)
        for it in er["indicios"]:
            forn = f"{(it.get('nome') or '-')[:36]} ({fmt_cnpj(it['cnpj'])})"
            _tab_row(pdf, [(_t(forn)[:60], 96, "L"), (_t(it.get("nivel") or "-"), 24, "C"),
                           (_t(it.get("evidencia") or "-")[:38], 60, "L")], h=4.6)


def _secao_beneficios_pdf(pdf, _t, ctx: dict) -> None:
    """PDF — benefícios sociais dos sócios/administradores (cruzamento de laranja)."""
    b = ctx.get("beneficios_socios") or {}
    pdf.ln(4); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 8, _t("Benefícios sociais dos sócios/administradores (indício de laranja)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
    if not b.get("ok"):
        pdf.set_font(pdf._fam, "I", 8); pdf.set_text_color(110, 110, 110)
        _mc(pdf, 4.5, _t("Sem QSA mascarado dos fornecedores desta UG, ou a varredura de benefícios ainda não "
                         "cobriu (INDISPONÍVEL, não ausência — o sweep roda em segundo plano)."))
        pdf.set_text_color(0, 0, 0); return
    from compliance_agent.reporting import beneficios_view as bv
    _mc(pdf, 4.5, _t(bv.leitura(b, escopo="desta UG").replace("**", "")))
    pdf.ln(1)
    _mc(pdf, 4.5, _t(f"QSA mascarado: {b['total_qsa']} | varridos: {b['n_varridos']} | CPF resolvido: "
                     f"{b['n_resolvidos']} | verificados: {b['n_verificados']} ({b['cobertura']}%) | "
                     f"com benefício (indício): {b['n_com_beneficio']} | INDISPONÍVEL: {b['n_indisponivel']}."))
    itens = b.get("itens") or []
    if itens:
        pdf.ln(1); _tab_header(pdf, [("Fornecedor", 70), ("Sócio/Admin", 56), ("Papel", 30), ("Benefício", 36)])
        pdf.set_font(pdf._fam, "", 7)
        for it in itens[:20]:
            tipos = ", ".join(it.get("tipos") or []) or "-"
            _tab_row(pdf, [(_t(it.get("razao", "")[:42]), 70, "L"), (_t(it.get("nome", "")[:34]), 56, "L"),
                           (_t(it.get("papel", "")[:18]), 30, "L"), (_t(tipos)[:22], 36, "L")], h=4.6)
        pdf.ln(1); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(150, 90, 0)
        _mc(pdf, 4, _t("Indício de interposição (laranja), não prova; confirmar no contrato social/procuração/SEI. "
                       "CPF de uso interno (LGPD)."))
        pdf.set_text_color(0, 0, 0)


def _secao_tce_pdf(pdf, _t, ctx: dict) -> None:
    """PDF — sanções do TCE-RJ ao órgão (controle externo, fato já julgado)."""
    from compliance_agent.reporting import penalidades_tce_view as pv
    t = ctx.get("penalidades_tce") or {}
    pdf.ln(4); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 8, _t("Sanções do TCE-RJ ao órgão (controle externo)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
    if not t.get("ok") or not t.get("n_condenacoes"):
        pdf.set_font(pdf._fam, "I", 8); pdf.set_text_color(110, 110, 110)
        _mc(pdf, 4.5, _t(pv.leitura(t, "este órgão").replace("**", "")))
        pdf.set_text_color(0, 0, 0); return
    _mc(pdf, 4.5, _t(pv.leitura(t, "este órgão").replace("**", "")))
    pdf.ln(1)
    pt = t.get("por_tipo", {})
    deb = pt.get("DEBITO", {}); mul = pt.get("MULTA", {})
    _mc(pdf, 4.5, _t(f"Condenações: {t['n_condenacoes']} (responsáveis) em {t.get('n_eventos', 0)} eventos / "
                     f"{t['n_processos']} processo(s) | débito: R$ {moeda(deb.get('valor', 0))} ({deb.get('n', 0)} ev.) | "
                     f"multa: R$ {moeda(mul.get('valor', 0))} ({mul.get('n', 0)} ev.) | "
                     f"total (sem dupla contagem solidária) R$ {moeda(t['valor_total'])}."))
    itens = t.get("itens") or []
    if itens:
        pdf.ln(1); _tab_header(pdf, [("Processo", 38), ("Ano", 12), ("Tipo", 20), ("Valor (R$)", 32), ("Resp.", 14), ("Natureza", 36)])
        pdf.set_font(pdf._fam, "", 7)
        for it in itens[:20]:
            resp = f"{it.get('n_resp', 1)}×" if it.get("n_resp", 1) > 1 else "1"
            _tab_row(pdf, [(_t(str(it["processo"])[:22]), 38, "L"), (_t(str(it.get("ano", "-"))), 12, "C"),
                           (_t(it["tipo"]), 20, "L"), (_t(moeda(it["valor"])), 32, "R"), (_t(resp), 14, "C"),
                           (_t(it["grupo_natureza"][:22]), 36, "L")], h=4.6)
        pdf.ln(1); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(150, 90, 0)
        _mc(pdf, 4, _t("Decisões do TCE-RJ (fato já julgado). Correspondência de órgão por mapa curado; "
                       "linhas incertas exigem conferir o ente no processo."))
        pdf.set_text_color(0, 0, 0)


def _secao_concentracao_grupo_pdf(pdf, _t, ctx: dict) -> None:
    """PDF — concentração OCULTA por grupo econômico (cartel/concorrência fictícia)."""
    cg = ctx.get("concentracao_grupo") or {}
    pdf.ln(4); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 8, _t("Concentração oculta por grupo econômico (cartel/concorrência fictícia)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
    _mc(pdf, 4.5, _t("Colapsa os fornecedores por grupo econômico (CNPJs ligados por sócio em comum). Muitos "
                     "CNPJs que parecem concorrentes mas são um grupo = diversidade fictícia (Art. 90 Lei 8.666; "
                     "Art. 337-F CP; Art. 36 Lei 12.529-CADE). Indício a corroborar (SEI/PNCP); QSA mascarado/"
                     "INDISPONÍVEL nao afasta grupo. Destinatário de achado confirmado: MP e CADE."))
    if not cg.get("ok"):
        pdf.set_font(pdf._fam, "I", 8); pdf.set_text_color(110, 110, 110)
        _mc(pdf, 4.5, _t("Concentração por grupo indisponível nesta execução (QSA/DuckDB) — degrada honesto. "
                         "INDISPONÍVEL não é prova de ausência de grupo."))
        pdf.set_text_color(0, 0, 0); return
    pdf.ln(1)
    _mc(pdf, 4.5, _t(f"{cg.get('n_cnpjs', 0)} CNPJs em {cg.get('n_grupos', 0)} grupos "
                     f"({cg.get('n_grupos_multi', 0)} multi-CNPJ). HHI por CNPJ {cg.get('hhi_cnpj', 0)} -> por "
                     f"grupo {cg.get('hhi_grupo', 0)}; maior grupo = {cg.get('top_grupo_share', 0):.1f}% do valor."))
    grupos_multi = [g for g in (cg.get("grupos") or []) if g.get("n_raizes", 0) >= 2]
    if grupos_multi:
        pdf.ln(1); _tab_header(pdf, [("Grupo (raiz)", 40), ("CNPJs", 16), ("Raízes", 16),
                                     ("Share %", 18), ("Total (R$)", 34), ("Maior CNPJ do grupo", 58)])
        pdf.set_font(pdf._fam, "", 7)
        for g in grupos_multi[:50]:
            _tab_row(pdf, [(_t(fmt_cnpj(g["grupo"]) if g.get("grupo") else "-"), 40, "L"),
                           (str(g["n_cnpjs"]), 16, "R"), (str(g["n_raizes"]), 16, "R"),
                           (f"{g['share']:.1f}", 18, "R"), (moeda(g["total"]), 34, "R"),
                           (_t(g.get("top_nome") or "-")[:36], 58, "L")], h=4.6)
    if cg.get("indicio"):
        mm = cg.get("maior_grupo_multi") or {}
        pdf.ln(1); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(150, 90, 0)
        _mc(pdf, 4, _t(f"Indício: maior grupo reúne {mm.get('n_cnpjs', 0)} CNPJs ({mm.get('n_raizes', 0)} raízes "
                       f"- aparentes concorrentes) e concentra {mm.get('share', 0):.1f}% do valor. Diversidade "
                       "fictícia = red flag de cartel/concorrência simulada; corroborar editais (SEI/PNCP) e, se "
                       "confirmado, comunicar MP e CADE. Indício, não prova; mercado restrito explica parte."))
        pdf.set_text_color(0, 0, 0)


def _secao_painel_detectores_pdf(pdf, _t, ctx: dict) -> None:
    """PDF — espelho da §1-I: painel unificado dos detectores do spec de licitações (só os confirmados no topo +
    resumo honesto dos afastados/indisponíveis). Degrada honesto: INDISPONÍVEL não some."""
    pd = ctx.get("painel_detectores") or {}
    pdf.ln(4); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 8, _t("Painel de detectores (spec de licitações)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
    _mc(pdf, 4.5, _t("Visão unificada dos detectores no schema do spec (score com âncoras fixas; status "
                     "confirmado/descartado/nao_avaliavel; passo exculpatório adversarial). Hoje J1 (conluio/"
                     "cartel) - a concentração-grupo acima é a evidência por trás dele, não se repete. Extensível "
                     "a P/C/E/X. Indício != acusação; INDISPONÍVEL/nao_avaliavel != 0."))
    if not pd.get("ok"):
        pdf.set_font(pdf._fam, "I", 8); pdf.set_text_color(110, 110, 110)
        _mc(pdf, 4.5, _t("Painel de detectores INDISPONÍVEL nesta execução (orquestrador DuckDB/QSA/LLM) — "
                         "degrada honesto. INDISPONÍVEL não é prova de ausência de indício."))
        pdf.set_text_color(0, 0, 0); return
    confirmados = pd.get("confirmados") or []
    pdf.ln(1)
    if confirmados:
        _mc(pdf, 4.5, _t(f"{pd.get('n_confirmados', 0)} detector(es) com indício CONFIRMADO de "
                         f"{pd.get('n_total', 0)} avaliado(s):"))
        pdf.ln(1); _tab_header(pdf, [("Detector", 20), ("Score", 16), ("Status", 22),
                                     ("Evidência (resumo)", 84), ("Defesa", 18)])
        pdf.set_font(pdf._fam, "", 7)
        for r in confirmados:
            defesa = "sim" if r.get("tem_defesa") else "-"
            _tab_row(pdf, [(_t(str(r["detector"]))[:12], 20, "L"), (f"{r['score']:.2f}", 16, "R"),
                           (_t(r["status"]), 22, "L"), (_t(r["evidencia"])[:52], 84, "L"),
                           (defesa, 18, "C")], h=4.6)
        com_defesa = [r for r in confirmados if r.get("explicacao_inocente")]
        if com_defesa:
            pdf.ln(1); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(110, 110, 110)
            for r in com_defesa:
                _mc(pdf, 4, _t(f"Hipótese inocente {r['detector']}: {r['explicacao_inocente'][:160]}"))
            pdf.set_text_color(0, 0, 0)
    else:
        pdf.set_font(pdf._fam, "I", 8); pdf.set_text_color(40, 110, 40)
        _mc(pdf, 4.5, _t("Nenhum detector com indício confirmado nesta execução — sem alarme do spec para esta "
                         "UG (não afasta risco na cauda nem detectores INDISPONÍVEIS)."))
        pdf.set_text_color(0, 0, 0)
    pdf.ln(1); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(110, 110, 110)
    _mc(pdf, 4, _t(f"Resumo: {pd.get('n_descartados', 0)} afastado(s) pela exculpatória, "
                   f"{pd.get('n_nao_avaliaveis', 0)} indisponível(is) (nao_avaliavel). INDISPONÍVEL != "
                   "ausência de indício."))
    pdf.set_text_color(0, 0, 0)


def _fotos_fachada_suspeitos_pdf(pdf, _t, suspeitos: list, limite: int = 6) -> int:
    """Embute no PDF as fotos de fachada (guardadas no B2 pelo `tools.fachada_b2_sync`) dos co-suspeitos
    da worklist §1-J que TÊM `verificacao_sede.visual_img_b2`. REUSA o helper `_foto_fachada_b2` de
    `inteligencia` (baixa via `rclone cat`, bounded, degrada honesto — NÃO duplica a lógica de B2).
    Legenda HONESTA: classe visual + fonte da imagem + fornecedor. Degrada honesto: se a foto faltar ou o
    rclone/B2 falhar, simplesmente não embute aquele suspeito (não quebra o relatório). Devolve quantas
    fotos embutiu. Cada foto vai num arquivo TEMP descartado em seguida (o FPDF lê de caminho)."""
    import os as _os
    import tempfile as _tmp
    embutidas = 0
    for s in suspeitos:
        if embutidas >= limite:
            break
        cnpj = so_digitos(s.get("cnpj") or "")
        if not cnpj:
            continue
        try:
            d = _foto_fachada_b2(cnpj)
        except Exception:  # noqa: BLE001
            d = None
        if not d or not d.get("bytes"):
            continue
        img = d["bytes"]
        ext = "png" if img[:4] == b"\x89PNG" else "jpg"
        tmp = None
        try:
            with _tmp.NamedTemporaryFile(prefix=f"fachada_org_{cnpj}_", suffix=f".{ext}", delete=False) as fh:
                fh.write(img)
                tmp = fh.name
            if embutidas == 0:
                pdf.ln(2); pdf.set_font(pdf._fam, "B", 9); pdf.set_text_color(150, 90, 0)
                pdf.cell(0, 6, _t("Fotos das fachadas-suspeitas (imagem de rua guardada no B2)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.set_text_color(0, 0, 0)
            # quebra de pagina se nao couber a imagem + legenda (~60mm)
            if pdf.get_y() > pdf.h - 70:
                pdf.add_page()
            nome = (s.get("nome") or "-")[:40]
            classe = (d.get("classe") or "").replace("_", " ") or "-"
            fonte = d.get("fonte") or "imagem de rua"
            pdf.set_font(pdf._fam, "B", 8)
            _mc(pdf, 4.2, _t(f"{nome} ({fmt_cnpj(cnpj)})"))
            try:
                pdf.image(tmp, w=85)
            except Exception:  # noqa: BLE001
                continue
            pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(110, 110, 110)
            _mc(pdf, 3.6, _t(f"Classe visual: {classe} - imagem de rua, fonte {fonte}. "
                             "Indicio a confirmar in loco - nao e prova de fachada."))
            pdf.set_text_color(0, 0, 0)
            embutidas += 1
        except Exception:  # noqa: BLE001
            continue
        finally:
            if tmp:
                try:
                    _os.unlink(tmp)
                except OSError:
                    pass
    return embutidas


def _secao_tac_pdf(pdf, _t, ctx: dict) -> None:
    """PDF — espelho da §1-J: pagamento fora de contrato regular (TAC/indenização) + emergencial + worklist."""
    tj = ctx.get("tac_orgao") or {}
    pdf.ln(4); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 8, _t("Pagamento fora de contrato regular (TAC/indenizacao) + emergencial"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
    _mc(pdf, 4.5, _t("Quanto a UG pagou FORA de contrato regular licitado (Termo de Ajuste de Contas, indenizacao, "
                     "reconhecimento de divida - art. 59 par. unico Lei 8.666; art. 149 Lei 14.133) e por "
                     "emergencial/dispensa. Recorrente e vultoso = indicio sistemico de fuga ao dever de licitar "
                     "(art. 37 CF/88). Indicio da PRATICA do orgao, NAO acusacao individual; INDISPONIVEL != 0."))
    if not tj.get("ok"):
        pdf.set_font(pdf._fam, "I", 8); pdf.set_text_color(110, 110, 110)
        _mc(pdf, 4.5, _t("Sem padrao relevante de TAC/indenizacao nem emergencial para esta UG (INDISPONIVEL != "
                         "ausencia - depende da observacao da OB)."))
        pdf.set_text_color(0, 0, 0); return
    ug_m = tj.get("tac_ug") or {}; emerg = tj.get("emergencial") or {}; wl = tj.get("worklist") or {}
    pdf.ln(1)
    _mc(pdf, 4.5, _t(f"TAC/indenizacao (sistemico da UG): {ug_m.get('pct', 0):.1f}% de R$ {moeda(ug_m.get('total', 0))} "
                     f"pagos fora de contrato regular - R$ {moeda(ug_m.get('total_tac', 0))} em "
                     f"{ug_m.get('n_tac', 0)} OB(s). Cobertura: {ug_m.get('cobertura', '-')}."))
    if emerg.get("ok"):
        _mc(pdf, 4.5, _t(f"Emergencial/dispensa (red flag irma): {emerg.get('n_emerg', 0)} OB(s) citam EMERGENCIAL/"
                         f"DISPENSA - R$ {moeda(emerg.get('total_emerg', 0))} ({emerg.get('pct', 0):.1f}% do valor "
                         "com observacao). Dispensa/emergencia reiterada reforca a fuga ao certame."))
    forn = wl.get("fornecedores") or []
    if forn:
        pdf.ln(1); pdf.set_font(pdf._fam, "B", 9)
        pdf.cell(0, 7, _t(f"Worklist - fornecedores da UG com maior pagamento via TAC ({wl.get('n_fornecedores', 0)})"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        _tab_header(pdf, [("Fornecedor (CNPJ)", 92), ("TAC %", 16), ("R$ via TAC", 34), ("Total (R$)", 34), ("Sede", 24)])
        pdf.set_font(pdf._fam, "", 7)
        for f in forn:
            nome = f"{(f.get('nome') or '-')[:34]} ({fmt_cnpj(f['cnpj'])})" if f.get("cnpj") else (f.get("nome") or "-")[:34]
            if f.get("sede_indicio"):
                marca = "INDICIO" if f.get("sede_status") == "INDICIO" else "sem Google"
            elif f.get("sede_status") == "AFASTADO":
                marca = "real"
            else:
                marca = "INDISPON."
            _tab_row(pdf, [(_t(nome)[:58], 92, "L"), (f"{f.get('pct', 0):.0f}%", 16, "R"),
                           (moeda(f.get("total_tac", 0)), 34, "R"), (moeda(f.get("total", 0)), 34, "R"),
                           (_t(marca), 24, "C")], h=4.6)
        suspeitos = [f for f in forn if f.get("sede_indicio")]
        pdf.ln(1); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(150, 90, 0)
        if suspeitos:
            nomes = "; ".join(f"{(s.get('nome') or '-')[:24]} ({s.get('pct', 0):.0f}% TAC)" for s in suspeitos[:5])
            _mc(pdf, 4, _t(f"Co-suspeitos a priorizar: {len(suspeitos)} fornecedor(es) tem sede com indicio de "
                           f"fachada ALEM do alto TAC% - {nomes}. Alto pagamento fora de contrato + sede-fachada "
                           "eleva a hipotese de empresa de fachada/interposicao. Indicio != acusacao."))
        else:
            _mc(pdf, 4, _t("A verificar: fornecedores acima concentram pagamento via TAC (fora de contrato regular). "
                           "Alto TAC% por si e indicio de contratacao fora de licitacao. INDISPONIVEL != afastado."))
        pdf.set_text_color(0, 0, 0)
        # fotos das fachadas-suspeitas (B2) dos co-suspeitos com sede-indicio — reusa o helper de inteligencia
        if suspeitos:
            _fotos_fachada_suspeitos_pdf(pdf, _t, suspeitos)


def _secao_anomalia_receita_pdf(pdf, _t, ctx: dict) -> None:
    """PDF — espelho da §1-K: cruzamento dump da Receita Federal × fornecedores (anomalias determinísticas)."""
    ar = ctx.get("anomalia_receita") or {}
    pdf.add_page(); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 30, 50)
    pdf.cell(0, 8, _t("Cruzamento Receita Federal - anomalias nos fornecedores"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
    _mc(pdf, 4.5, _t("Cruza os pagamentos (OB) com o dump da Receita Federal (natureza juridica; quadro societario "
                     "real; busca reversa) para flagar: (1) entidade SEM FINS LUCRATIVOS recebendo como fornecedor; "
                     "(2) rede/grupo - mesma pessoa administrando varios fornecedores do orgao + admin. em muitos CNPJs; "
                     "(3) laranja/socio-unico de alto valor. Indicio != acusacao; entes publicos e instituicoes "
                     "legitimas de ensino/pesquisa NAO sao anomalia; CPF de socio mascarado (LGPD)."))
    if not ar.get("ok"):
        pdf.set_font(pdf._fam, "I", 8); pdf.set_text_color(110, 110, 110)
        _mc(pdf, 4.5, _t("Cruzamento com a Receita indisponivel nesta execucao (dump nao ingerido). "
                         "INDISPONIVEL != ausencia de anomalia."))
        pdf.set_text_color(0, 0, 0); return
    cov = ar.get("cobertura") or {}
    pdf.ln(1)
    _mc(pdf, 4.5, _t(f"Cobertura honesta: dos {cov.get('n_fornecedores_pj', 0)} fornecedores PJ da UG, "
                     f"{cov.get('n_no_empresas_min', 0)} ({cov.get('pct_empresas_min', 0):.0f}%) constam no dump e "
                     f"{cov.get('n_com_qsa', 0)} ({cov.get('pct_qsa', 0):.0f}%) tem QSA ingerido. Os demais seguem "
                     "INDISPONIVEL (nao 'limpos')."))

    # (1) sem fins lucrativos
    sf = ar.get("sem_fins_lucrativos") or []
    if sf:
        pdf.ln(1); pdf.set_font(pdf._fam, "B", 9)
        pdf.cell(0, 7, _t("(1) Entidades SEM FINS LUCRATIVOS recebendo como fornecedor"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        _tab_header(pdf, [("Razao social", 96), ("Natureza", 34), ("Total (R$)", 32), ("Obs.", 28)])
        pdf.set_font(pdf._fam, "", 7)
        for r in sf[:15]:
            obs = "ressalva" if r.get("ressalva") else "a apurar"
            _tab_row(pdf, [(_t((r.get("razao_social") or "-")[:60]), 96, "L"),
                           (_t((r.get("natureza_txt") or "-")[:20]), 34, "L"),
                           (moeda(r.get("total", 0)), 32, "R"), (_t(obs), 28, "C")], h=4.6)
        flag = [r for r in sf if not r.get("ressalva")]
        pdf.ln(1); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(150, 90, 0)
        if flag:
            t = flag[0]
            _mc(pdf, 4, _t(f"Indicio: {len(flag)} entidade(s) sem fins lucrativos sem perfil de ensino/pesquisa "
                           f"recebem como fornecedor - maior: {(t.get('razao_social') or '-')[:40]} "
                           f"(R$ {moeda(t.get('total', 0))}). OS/contrato de gestao exige confirmar objeto/credenciamento/"
                           "prestacao de contas (Lei 9.637/98; Lei 13.019/2014). Indicio, nao acusacao."))
        else:
            _mc(pdf, 4, _t("As entidades sem fins lucrativos identificadas tem perfil de ensino/pesquisa/estagio "
                           "(ressalva) - recebimento provavelmente legitimo."))
        pdf.set_text_color(0, 0, 0)

    # (2) rede / grupo
    rede = ar.get("rede_mesmo_orgao") or []
    if rede:
        pdf.ln(1); pdf.set_font(pdf._fam, "B", 9)
        pdf.cell(0, 7, _t("(2) Rede/grupo - administradores compartilhados (>=2 fornecedores do orgao)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        _tab_header(pdf, [("Administrador (doc)", 120), ("N fornec.", 22), ("Qualificacoes", 48)])
        pdf.set_font(pdf._fam, "", 7)
        for r in rede[:15]:
            nome = f"{(r.get('nome_socio') or '-')[:42]} ({r.get('doc_socio', '')})"
            _tab_row(pdf, [(_t(nome)[:74], 120, "L"), (str(r.get("n_fornecedores", "")), 22, "C"),
                           (_t((r.get("qualificacoes") or "-")[:30]), 48, "L")], h=4.6)
        t = rede[0]
        pdf.ln(1); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(150, 90, 0)
        _mc(pdf, 4, _t(f"Indicio de grupo/concorrencia ficticia: {len(rede)} pessoa(s) administram >=2 fornecedores "
                       f"do MESMO orgao - ex.: {(t.get('nome_socio') or '-')[:34]} em {t.get('n_fornecedores')} "
                       "fornecedores. Aparentes concorrentes sob a mesma administracao = red flag de concorrencia "
                       "simulada (Art. 90 Lei 8.666; Art. 337-F CP; Art. 36 Lei 12.529-CADE). Indicio != prova."))
        pdf.set_text_color(0, 0, 0)
    veic = ar.get("veiculos_aluguel") or []
    if veic:
        pdf.ln(1); pdf.set_font(pdf._fam, "B", 8.5)
        pdf.cell(0, 6, _t("Administradores em muitos CNPJs no Brasil (possivel veiculo de aluguel):"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        _tab_header(pdf, [("Administrador (doc)", 130), ("N CNPJs (Brasil)", 40)])
        pdf.set_font(pdf._fam, "", 7)
        for r in veic[:40]:
            nome = f"{(r.get('nome_socio') or '-')[:46]} ({r.get('doc_socio', '')})"
            _tab_row(pdf, [(_t(nome)[:80], 130, "L"), (str(r.get("n_cnpjs_brasil", "")), 40, "C")], h=4.6)
        pdf.ln(1); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(110, 110, 110)
        _mc(pdf, 4, _t("Ressalva: aparecer em dezenas/centenas de CNPJs e o padrao de executivos de grandes "
                       "conglomerados legitimos - NAO e, por si, anomalia. Listado para due diligence, nao como acusacao."))
        pdf.set_text_color(0, 0, 0)

    # (3) laranja / socio-unico
    su = ar.get("socio_unico_alto_valor") or []
    if su:
        pdf.ln(1); pdf.set_font(pdf._fam, "B", 9)
        pdf.cell(0, 7, _t("(3) Laranja/socio-unico de alto valor"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        _tab_header(pdf, [("Razao social", 104), ("Total (R$)", 34), ("Unico admin.", 52)])
        pdf.set_font(pdf._fam, "", 7)
        for r in su[:15]:
            tag = " [sem-fins]" if r.get("sem_fins") else ""
            _tab_row(pdf, [(_t((r.get("razao_social") or "-")[:48] + tag), 104, "L"),
                           (moeda(r.get("total", 0)), 34, "R"),
                           (_t((r.get("socio_unico") or "-")[:30]), 52, "L")], h=4.6)
        pdf.ln(1); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(150, 90, 0)
        _mc(pdf, 4, _t("Indicio: fornecedores de alto valor com um unico administrador no QSA. Gestao concentrada "
                       "em contratos vultosos = red flag de interposicao (laranja) ou capacidade incompativel - "
                       "confrontar com a estrutura real. Indicio != acusacao; muitas PMEs legitimas tem socio unico."))
        pdf.set_text_color(0, 0, 0)

    cad = ar.get("cadastro") or {}
    if cad.get("ok") and cad.get("achados"):
        pdf.ln(1); pdf.set_font(pdf._fam, "B", 9)
        pdf.cell(0, 7, _t("(4) Situacao cadastral externa (amostra)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        _tab_header(pdf, [("CNPJ-raiz", 34), ("Situacao", 40), ("Motivo", 80), ("Data", 28)])
        pdf.set_font(pdf._fam, "", 7)
        for r in cad["achados"]:
            _tab_row(pdf, [(r.get("cnpj_basico", ""), 34, "L"), (_t((r.get("situacao") or "")[:22]), 40, "L"),
                           (_t((r.get("descricao") or "-")[:46]), 80, "L"), (r.get("data_situacao", ""), 28, "C")], h=4.6)


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
    pdf.cell(0, 13, _t("RELATÓRIO DE INTELIGÊNCIA DE ÓRGÃO"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_font(pdf._fam, "", 9); pdf.set_fill_color(45, 60, 90)
    pdf.cell(0, 7, _t("Execução de pagamentos · Concentração por fornecedor · Risco"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.cell(0, 7, _t(f"Controle Externo (automatizado)  |  {ctx['data']}"), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
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
                 fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 8)
        _mc(pdf, 4.5, _t(f"{_risco['just']}. O score é indício INTERNO de atenção (concentração + padrões ACFE), "
                         "NÃO uma acusação. Os red flags e a matriz P×I estão abaixo; o detalhe jurídico, no Parecer Lex anexo."))
    else:
        _risco = {"achados": []}

    if p["tem_dados"]:
        pdf.ln(3); pdf.set_font(pdf._fam, "B", 12)
        pdf.cell(0, 8, _t("Pagamentos por exercício"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
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
        pdf.cell(0, 9, _t("Concentração por fornecedor (HHI)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 9)
        pdf.cell(0, 6, _t(f"HHI {p['hhi'].get('indice')} — {p['hhi'].get('nivel')} "
                          f"(maior fornecedor = {p['hhi'].get('top_share')}%)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT); pdf.ln(1)
        _tab_header(pdf, [("Fornecedor", 130), ("Valor (R$)", 36), ("%", 16)])
        pdf.set_font(pdf._fam, "", 8)
        tot = p["total_geral"] or 1
        from compliance_agent.entidades_gov import eh_nao_fornecedor
        for nome, val in list(p["por_favorecido_geral"].items())[:120]:
            rot = (_t(nome)[:74] + " [transf.intergov]") if eh_nao_fornecedor(nome) else _t(nome)[:86]
            _tab_row(pdf, [(rot, 130, "L"), (moeda(val), 36, "R"), (f"{val/tot*100:.1f}", 16, "R")], h=5)

        # Concentração GEOGRÁFICA (sede dos fornecedores) — já calculada em ctx["geo"], antes descartada no PDF
        geo = ctx.get("geo") or {}
        if geo.get("ok") and geo.get("cidades"):
            pdf.ln(4); pdf.set_font(pdf._fam, "B", 12); pdf.set_text_color(20, 30, 50)
            pdf.cell(0, 8, _t("Concentração geográfica (sede dos fornecedores)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
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
            pdf.cell(0, 8, _t("Pagamentos recorrentes de valor idêntico"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
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
        pdf.cell(0, 8, _t("Red flags do controle externo (síntese · matriz P×I — TCU)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
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
        _secao_beneficios_pdf(pdf, _t, ctx)
        _secao_tce_pdf(pdf, _t, ctx)
        _secao_concentracao_grupo_pdf(pdf, _t, ctx)
        _secao_painel_detectores_pdf(pdf, _t, ctx)
        _secao_tac_pdf(pdf, _t, ctx)  # §1-J: TAC/indenização + emergencial + worklist de co-suspeitos
        _secao_anomalia_receita_pdf(pdf, _t, ctx)  # §1-K: cruzamento dump RF × fornecedores (anomalias)

        # OBs por ano
        for a in p["anos"]:
            b = p["por_ano"][a]
            pdf.add_page(); pdf.set_font(pdf._fam, "B", 13); pdf.set_text_color(20, 30, 50)
            pdf.cell(0, 9, _t(f"Pagamentos (OBs) — exercício {a}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_text_color(0, 0, 0); pdf.set_font(pdf._fam, "", 9)
            _maiores = sorted(b["linhas"], key=lambda ln: -(ln.get("valor") or 0))[:12]
            _nota = f"{b['n']} OBs — Total: R$ {moeda(b['total'])}" + (
                f"  ·  {len(_maiores)} maiores abaixo; lista completa na planilha XLSX" if b["n"] > len(_maiores) else "")
            pdf.cell(0, 6, _t(_nota), new_x=XPos.LMARGIN, new_y=YPos.NEXT); pdf.ln(1)
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
    pdf.cell(0, 10, _t("Análise Jurídica e de Mérito — Parecer Preliminar do JFN"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)
    raciocinio = ctx.get("raciocinio")
    if raciocinio:
        pdf.set_font(pdf._fam, "B", 11); pdf.cell(0, 7, _t("Análise raciocinada — cruzamento dos achados"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font(pdf._fam, "", 10)
        _render_parecer_pdf(pdf, _t, raciocinio)
        pdf.ln(2)
    _render_parecer_pdf(pdf, _t, parecer_orgao(ctx))

    pdf.ln(3); pdf.set_font(pdf._fam, "I", 7); pdf.set_text_color(120, 120, 120)
    _mc(pdf, 4, _t("Gerado automaticamente. Não substitui análise jurídica especializada."))

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
