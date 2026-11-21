# -*- coding: utf-8 -*-
"""
RELATÓRIO DE INTELIGÊNCIA DE FORNECEDOR — orquestrador de 1 chamada.

É o motor do comando `/relatorio` do Yoda. Dado um CNPJ **ou** um nome de empresa, monta um
relatório de due diligence (padrão Kroll/Deloitte, ver CLAUDE.md) e o salva em `reports/` como
`.md` e `.pdf`.

USO (CLI, para IA fraca rodar):
    cd ~/JFN
    .venv/bin/python -m compliance_agent.reporting.inteligencia "MGS Clean"
    .venv/bin/python -m compliance_agent.reporting.inteligencia 19.088.605/0001-04 2023 2024 2025 2026

USO (API, chamado pelo server.py):
    from compliance_agent.reporting.inteligencia import montar
    res = await montar(cnpj="19088605000104")     # async
    # res = {ok, cnpj, empresa, risco, score, resumo, path_md, path_pdf, fonte}

FONTES DE DADO (e honestidade — princípio do JFN: Empenho ≠ Pagamento):
  - **OBs pagas** (`data/compliance.db` → `ob_orcamentaria_siafe`, régua única `cruzamentos_intel._ob_paga`): dado
    REAL de PAGAMENTO (Ordem Bancária = fonte de verdade), nunca o espelho TFE (`ordens_bancarias`, que até
    21/11/2026 era somado aqui). É a espinha financeira do relatório, com **uma tabela por ano**; exercício fora da
    cobertura do SIAFE sai INDISPONÍVEL/PARCIAL (`pagamentos["cobertura"]`), nunca completado com o espelho.
  - **Contratos** (`data/compliance.db` → contratos): carteira oficial coletada do SIAFE.
  - **Perfil cadastral / sanções / rede societária / sinais de risco**: `relatorio_riscos.gerar_relatorio_risco`
    (APIs públicas — Receita/PNCP/CEIS-CNEP). É best-effort: se o egress da VM falhar, o relatório sai assim
    mesmo, marcando a seção como INDISPONÍVEL (nunca inventa número).
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Split 2026-07-06: o código mora em intel_base/intel_dados/intel_analise/intel_md/intel_pdf. Aqui ficam
# só os nomes que o orquestrador usa e os que outros módulos ainda importam daqui (lex, lex_render,
# server, tools, testes) — nome novo de fora deve importar do módulo onde ele mora.
from compliance_agent.reporting.intel_base import (  # noqa: F401,E402
    _DB, _REPORTS, _prune_reports, _slug, cabecalho_frescor, fmt_cnpj, moeda, so_digitos,
)
from compliance_agent.reporting.intel_dados import (  # noqa: F401,E402
    _crescimento, _enriquecer, _recalibrar_risco, atualizar_favorecido_resumo, buscar_candidatos,
    consultar_contratos, consultar_pagamentos,
)
from compliance_agent.reporting.intel_analise import (  # noqa: F401,E402
    _NOTA_CARDINALIDADE, _anomalias_fornecedor, _fatos_para_raciocinio, _frase_cardinalidade, _gazetas_lookup,
    _natureza_sem_fins, _normaliza_raciocinio, _resumo_executivo, _termos_significativos,
    cardinalidade_contratual, parecer_fornecedor, parecer_raciocinado, troca_controle_societaria,
)
from compliance_agent.reporting.intel_md import (  # noqa: F401,E402
    _capital_recebido_md, _num_brl, _render_anomalias, _render_beneficios_socios, _render_benford,
    _render_doacoes_tse, _render_rodizio_fornecedor, _sede_status_cacheado, emendas_do_favorecido, render_md,
)
from compliance_agent.reporting.intel_pdf import (  # noqa: F401,E402
    _mc, _registrar_fonte, _render_parecer_pdf, render_pdf, render_pdf_html,
)



async def montar(cnpj: Optional[str] = None, empresa: Optional[str] = None,
                 anos: Optional[list[int]] = None, salvar: bool = True, so_resolver: bool = False,
                 retornar_ctx: bool = False) -> dict:
    """Monta o relatório de inteligência. Retorna dict (ver docstring do módulo).
    so_resolver=True: só RESOLVE (rápido) e devolve {ok,_resolvido,empresa,cnpj} ou {ambiguo}/{erro}, SEM gerar
    — o endpoint usa p/ tratar a ambiguidade SÍNCRONA (o Yoda roteia a resposta) antes de gerar em background."""
    termo = (cnpj or empresa or "").strip()
    candidatos = buscar_candidatos(termo)
    if not candidatos:
        # o humano confunde empresa×órgão ("relatório da fundação saúde") — se o termo casa uma UG,
        # devolve a pista p/ o Yoda oferecer o produto certo em vez de um beco sem saída
        try:
            import sqlite3 as _sq
            from compliance_agent.reporting.inteligencia_orgao import buscar_orgaos
            orgs = [o for o in buscar_orgaos(termo) if o.get("_match") == "exato"]
        except (ImportError, _sq.Error, OSError, ValueError):  # pista aditiva; sem ela, mensagem padrão
            orgs = []
        if orgs:
            return {"ok": False, "erro": f"Não encontrei EMPRESA para {termo!r}, mas encontrei ÓRGÃO/UG: "
                                         + "; ".join(f"{o['nome']} (UG {o['ug']})" for o in orgs[:3])
                                         + ". Se for esse o alvo, peça o relatório de ÓRGÃO (/orgao).",
                    "empresa": termo,
                    "sugestao_orgao": [{"ug": o["ug"], "nome": o["nome"]} for o in orgs[:3]]}
        return {"ok": False, "erro": f"Não encontrei nenhuma empresa para {termo!r}. "
                                     f"Tente outro nome (parcial serve) ou o CNPJ.", "empresa": termo}

    # decide se pode escolher sozinho, ou se precisa perguntar ao Mestre Jorge (via Yoda)
    alvo = termo.lower().strip()
    e_cnpj = len(so_digitos(termo)) == 14
    exatos = [c for c in candidatos if (c["nome"] or "").lower().strip() == alvo]
    if e_cnpj or len(candidatos) == 1:
        escolhido = candidatos[0]
    elif len(exatos) == 1:
        escolhido = exatos[0]
    else:
        # AMBÍGUO — devolve a dúvida para o Yoda perguntar ao Mestre Jorge
        opcoes = [{
            "n": i + 1, "cnpj": c["cnpj"], "cnpj_fmt": fmt_cnpj(c["cnpj"]),
            "nome": c["nome"] or "(sem nome)",
            "total_pago": c["total_pago"], "n_obs": c["n_obs"],
        } for i, c in enumerate(candidatos)]
        linhas = [f"{o['n']}) {o['nome']} — CNPJ {o['cnpj_fmt']}"
                  + (f" — R$ {moeda(o['total_pago'])} pagos em {o['n_obs']} OBs (SIAFE)" if o["n_obs"]
                     else " — sem OB paga no SIAFE da casa (INDISPONÍVEL, não zero)")
                  for o in opcoes]
        pergunta = (f"Encontrei {len(opcoes)} empresas para \"{termo}\". Qual delas, Mestre Jorge?\n"
                    + "\n".join(linhas)
                    + "\n\nResponda com o número ou o CNPJ.")
        return {"ok": False, "ambiguo": True, "termo": termo, "candidatos": opcoes, "pergunta": pergunta}

    cnpj_d = escolhido["cnpj"]
    resolv = escolhido
    if so_resolver:  # resolveu sem ambiguidade → o endpoint segue p/ geração em background
        return {"ok": True, "_resolvido": cnpj_d, "cnpj": cnpj_d, "empresa": escolhido.get("nome") or termo}

    pagamentos = consultar_pagamentos(cnpj_d, anos)
    contratos = consultar_contratos(cnpj_d)
    cardinalidade = cardinalidade_contratual(cnpj_d)  # OB ≠ contrato ≠ processo (cadeia da despesa, honesto)

    # 4 chamadas INDEPENDENTES em PARALELO (wall-time: soma → máximo). Cada uma é best-effort e não
    # derruba o relatório: enriquecimento (APIs) · cruzamento sócio×OB×SEI×endereço · conflito TSE (DB) ·
    # contratos TCE-RJ (rede). conflito calculado 1× aqui e reusado no render (evita 2ª query).
    async def _cruz():
        try:
            from compliance_agent.cruzamento import cruzar_async
            return await asyncio.wait_for(cruzar_async(cnpj_d), timeout=25)
        except Exception as exc:  # noqa: BLE001
            return {"_erro": str(exc)[:140]}

    async def _conflito_async():
        try:
            from compliance_agent.lex_conflito import conflito as _c
            return (await asyncio.to_thread(_c, cnpj=cnpj_d, limite=300)).get("rede", [])  # completo (dono)
        except Exception:  # noqa: BLE001
            return []

    async def _tcerj_async():
        try:
            from compliance_agent.collectors.tcerj_aberto import contratos_de_fornecedor
            return await asyncio.wait_for(asyncio.to_thread(contratos_de_fornecedor, cnpj_d, 100), timeout=25)
        except Exception:  # noqa: BLE001
            return []

    enriq, cruz, rede, tcerj_itens = await asyncio.gather(
        _enriquecer(cnpj_d), _cruz(), _conflito_async(), _tcerj_async())
    contratado_tcerj = sum((i.get("valor_contrato") or 0) for i in (tcerj_itens or []) if i.get("_tipo") == "contrato")

    nome = (enriq.get("empresa") or resolv["nome"] or "").strip() or fmt_cnpj(cnpj_d)

    # Anomalias PyOD (§8-C) — computadas 1× AQUI (consulta local barata) p/ entrarem no score E serem
    # reusadas no render (ctx["anomalias"]), evitando 2ª query. Best-effort: nunca derruba o relatório.
    try:
        anomalias = await asyncio.to_thread(_anomalias_fornecedor, cnpj_d)
    except Exception:  # noqa: BLE001
        anomalias = {"ok": False, "n_obs": 0, "n_anomalas": 0, "itens": []}
    # Natureza sem-fins (§1) — ANCORADA NO DUMP LOCAL (`empresas_min`); funciona mesmo com enriquecimento
    # RFB INDISPONÍVEL. Computada 1× aqui (consulta local barata) p/ entrar no score E ser reusada no render.
    try:
        natureza_sem_fins = await asyncio.to_thread(_natureza_sem_fins, cnpj_d)
    except Exception:  # noqa: BLE001
        natureza_sem_fins = {"ok": False, "sem_fins": False}
    coend_score = (cruz or {}).get("coendereco") or []  # rede mesma-sede §1-B
    # Status de sede JÁ cacheado (leitura local barata, SEM Google on-demand — §4.1) p/ o score cruzar
    # 'sede = indício de fachada' × 'doador eleitoral' (convergência §1-D×sede, backlog #16).
    try:
        sede_status = await asyncio.to_thread(_sede_status_cacheado, cnpj_d)
    except Exception:  # noqa: BLE001
        sede_status = ""

    # RISCO recalibrado (externo + sinais internos reais) — corrige "BAIXO 0" com indícios. Inclui rede
    # mesma-sede §1-B e anomalias §8-C (peso conservador) p/ o NÚMERO refletir a prosa, não inflar.
    # Emendas parlamentares (§1-D0): computadas 1× AQUI (query local barata) p/ entrarem no SCORE
    # e serem reusadas no render (md+pdf) sem 2ª consulta. Eixo central de risco de OSC/ONG.
    try:
        emendas = emendas_do_favorecido(cnpj_d)
    except Exception as _exc_em:  # noqa: BLE001 — nunca derruba o relatório por causa da seção
        logger.warning("emendas do favorecido falhou: %s", str(_exc_em)[:120])
        emendas = {"tem_dados": False}
    cal = _recalibrar_risco(pagamentos, rede, contratado_tcerj, enriq.get("score", 0), enriq.get("risco", "—"),
                            coendereco=coend_score, anomalias=anomalias,
                            natureza_sem_fins=natureza_sem_fins, sede_status=sede_status,
                            emendas=emendas)
    risco, score = cal["risco"], cal["score"]

    fonte_global = "REAL" if pagamentos["tem_dados"] else "SEM_DADOS_OB"
    contexto = {
        "cnpj": cnpj_d, "cnpj_fmt": fmt_cnpj(cnpj_d), "nome": nome,
        "data": date.today().isoformat(), "risco": risco, "score": score,
        "pagamentos": pagamentos, "contratos": contratos, "cardinalidade": cardinalidade, "enriq": enriq,
        "fonte_enriq": enriq.get("_fonte", "INDISPONIVEL"),
        "cruzamento": cruz, "conflito_rede": rede, "anomalias": anomalias,
        "natureza_sem_fins": natureza_sem_fins, "emendas": emendas,
        "tcerj_itens": tcerj_itens, "contratado_tcerj": contratado_tcerj,
        "calibragem": cal,
    }

    # OSINT keyless (diários oficiais) + ANÁLISE RACIOCINADA — em thread (não bloqueia o event loop),
    # best-effort: nunca derruba nem atrasa o relatório além do bound. (relatório é assíncrono/push.)
    try:
        contexto["gazetas"] = await asyncio.wait_for(
            asyncio.to_thread(_gazetas_lookup, nome, cnpj_d), timeout=20)
    except Exception:  # noqa: BLE001
        contexto["gazetas"] = {}
    try:
        contexto["raciocinio"] = await asyncio.wait_for(
            asyncio.to_thread(parecer_raciocinado, contexto), timeout=55)
    except Exception:  # noqa: BLE001
        contexto["raciocinio"] = ""

    md = render_md(contexto)
    path_md = path_pdf = path_xlsx = ""
    if salvar:
        _prune_reports()  # poda relatórios antigos (regeneráveis sob demanda) antes de salvar os novos
        _REPORTS.mkdir(parents=True, exist_ok=True)
        base = f"inteligencia_{_slug(nome) or cnpj_d}_{contexto['data']}"
        path_md = str(_REPORTS / f"{base}.md")
        Path(path_md).write_text(md, encoding="utf-8")
        try:
            # Onda 7: PDF classe mundial via HTML→Playwright (sem margem estourada/truncamento,
            # com cadastral+sócios+doações+OSINT). FPDF compacto = fallback.
            path_pdf = await render_pdf_html(contexto, str(_REPORTS / f"{base}.pdf"))
        except Exception as exc_html:  # noqa: BLE001
            try:
                path_pdf = render_pdf(contexto, str(_REPORTS / f"{base}.pdf"))
            except Exception as exc:  # noqa: BLE001
                path_pdf = ""
                contexto["_pdf_erro"] = f"html:{str(exc_html)[:70]} | fpdf:{str(exc)[:70]}"
        try:
            from compliance_agent.reporting import planilha
            path_xlsx = planilha.gerar(contexto, str(_REPORTS / f"{base}.xlsx"), modo="fornecedor")
        except Exception as exc:  # noqa: BLE001
            path_xlsx = ""
            contexto["_xlsx_erro"] = str(exc)[:160]

    # 3º documento: PARECER do agente Lex (avaliação jurídica/tomada de contas)
    path_lex = ""
    path_lex_md = ""
    grau_lex = None
    if salvar:
        try:
            from compliance_agent import lex
            lexout = lex.gerar(contexto)
            path_lex = lexout.get("path_lex_pdf", "")
            path_lex_md = lexout.get("path_lex_md", "")
            grau_lex = lexout.get("grau")
        except Exception as exc:  # noqa: BLE001
            contexto["_lex_erro"] = str(exc)[:160]

    out = {
        "ok": True, "cnpj": cnpj_d, "cnpj_fmt": fmt_cnpj(cnpj_d), "empresa": nome,
        "risco": risco, "score": score,
        "resumo": _resumo_executivo(contexto),
        "path_md": path_md, "path_pdf": path_pdf, "path_xlsx": path_xlsx,
        "path_lex": path_lex, "path_lex_md": path_lex_md, "grau_lex": grau_lex,
        "fonte": fonte_global, "fonte_enriq": contexto["fonte_enriq"],
    }
    if retornar_ctx:  # consumido pelo relatório consolidado (reporting/consolidado.py) — sem re-coletar
        out["_ctx"] = contexto
    return out


def gerar(cnpj: Optional[str] = None, empresa: Optional[str] = None,
          anos: Optional[list[int]] = None, salvar: bool = True) -> dict:
    """Wrapper síncrono para CLI/uso fora de loop async."""
    return asyncio.run(montar(cnpj=cnpj, empresa=empresa, anos=anos, salvar=salvar))


# ───────────────────────────── CLI ─────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Uso: python -m compliance_agent.reporting.inteligencia <CNPJ|nome da empresa> [ano1 ano2 ...]")
        sys.exit(1)
    anos_cli = [int(a) for a in args if a.isdigit() and len(a) == 4]
    termo_cli = " ".join(a for a in args if not (a.isdigit() and len(a) == 4)).strip()
    res = gerar(empresa=termo_cli, anos=anos_cli or None)
    print(json.dumps({k: v for k, v in res.items() if k != "resumo"}, ensure_ascii=False, indent=2))
    print("\nRESUMO:", res.get("resumo", ""))
