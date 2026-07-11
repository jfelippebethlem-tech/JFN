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
  - **OBs pagas** (`data/compliance.db` → ordens_bancarias): dado REAL de PAGAMENTO (Ordem Bancária = fonte
    de verdade). É a espinha financeira do relatório, com **uma tabela por ano** (2023, 2024, 2025, 2026).
  - **Contratos** (`data/compliance.db` → contratos): carteira oficial coletada do SIAFE.
  - **Perfil cadastral / sanções / rede societária / sinais de risco**: `relatorio_riscos.gerar_relatorio_risco`
    (APIs públicas — Receita/PNCP/CEIS-CNEP). É best-effort: se o egress da VM falhar, o relatório sai assim
    mesmo, marcando a seção como INDISPONÍVEL (nunca inventa número).
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from typing import Optional





# retenção: relatórios são REGENERÁVEIS sob demanda (cada /relatorio gera de novo), então não precisam ficar
# acumulando no disco. Mantemos só os recentes (JFN_REPORTS_RETENCAO_DIAS, default 7).



# timeout (s) para o enriquecimento via APIs públicas (egress da VM é lento).
# O relatório é ASSÍNCRONO/push (não está no caminho do `terminal` 60s do Yoda): pode esperar mais para que
# perfil RFB, sinais corporativos (§5) e CEIS/CNEP/CEPIM (§6) populem em vez de cair em INDISPONÍVEL por egress.
# Antes era 35s e o enriquecimento estourava na VM (2 vCPU, egress lento). Agora ~90s + retry com backoff
# (sinal transitório) + cache por CNPJ (TTL 7 dias) para não repetir o egress a cada relatório.
# Se mesmo assim falhar, o relatório sai com os dados REAIS locais (OBs/contratos) e marca o enriquecimento
# como INDISPONÍVEL — degrada honesto, nunca inventa.
# nº de TENTATIVAS do enriquecimento (1 = sem retry). Backoff entre tentativas em _ENRIQUECE_BACKOFF s.
# TTL do cache do enriquecimento por CNPJ (s). 0 desliga o cache (testes determinísticos).
# Idade máxima (dias) de uma linha de `verificacao_sede` para o relatório aceitá-la SEM re-verificar.
# Acima disso o veredito Google é considerado VELHO e o relatório re-verifica on-demand (quota-guarded).
# 0 desliga o on-demand (só lê o que o sweep gravou — comportamento antigo; testes determinísticos).


# ───────────────────────────── helpers de formatação ─────────────────────────────









# ───────────────────────────── resolução de empresa ─────────────────────────────





# ───────────────────────────── tabela-resumo de favorecidos (ACELERAÇÃO) ─────────────────────────────
# `buscar_candidatos` fazia `lower(favorecido_nome) LIKE '%termo%'` + GROUP BY favorecido_cpf em
# ordens_bancarias (~1,12M linhas) → full-scan ~6-18s por chamada (não indexável: substring+função).
# Mas há só ~73.881 favorecidos DISTINTOS. `favorecido_resumo` é o GROUP BY pré-computado (74k linhas):
# o MESMO LIKE roda ~15× mais rápido. nome_ns = nome sem espaços, minúsculo (pré-computado p/ o fallback
# "engeprat"→"ENGE PRAT"). Idempotente; respeita JFN_DB/_resolver_db e busy_timeout (padrão fts.py).













# ───────────────────────────── consultas compliance.db ─────────────────────────────











# ───────────────────────────── enriquecimento (APIs públicas) ─────────────────────────────









# ───────────────────────────── montagem do relatório ─────────────────────────────



# ── Split 2026-07-06: FACHADA — inteligencia.py re-exporta tudo (callers e testes não mudam) ──
from compliance_agent.reporting.intel_base import (  # noqa: F401,E402
    _DATA, _DB, _REGISTRY, _REPORTS, _RETENCAO_DIAS, _ROOT, _prune_reports, _slug, cabecalho_frescor, fmt_cnpj, moeda, so_digitos,
)
from compliance_agent.reporting.intel_dados import (  # noqa: F401,E402
    _ENRIQUECE_BACKOFF, _ENRIQUECE_CACHE_PREFIXO, _ENRIQUECE_CACHE_TTL, _ENRIQUECE_TENTATIVAS, _ENRIQUECE_TIMEOUT, _carregar_registro, _crescimento, _enriquece_cache_get, _enriquece_cache_set, _enriquecer, _favorecido_resumo_disponivel, _hhi, _nome_por_cnpj, _norm_alnum, _recalibrar_risco, _resolver_db_inteligencia, atualizar_favorecido_resumo, buscar_candidatos, consultar_contratos, consultar_pagamentos, resolver_empresa,
)
from compliance_agent.reporting.intel_analise import (  # noqa: F401,E402
    _FEAT_ANOM, _NOTA_CARDINALIDADE, _anomalias_fornecedor, _fatores_risco, _fatos_para_raciocinio, _frase_cardinalidade, _gazetas_lookup, _natureza_sem_fins, _normaliza_raciocinio, _red_flags, _resumo_executivo, _termos_significativos, cardinalidade_contratual, parecer_fornecedor, parecer_raciocinado, troca_controle_societaria,
)
from compliance_agent.reporting.intel_md import (  # noqa: F401,E402
    _RCLONE_BIN, _SEDE_ONDEMAND_DIAS, _add_rede_fachada, _beneficios_socios, _capital_recebido_md, _fachada_b2_html, _foto_fachada_b2, _num_brl, _realidade_sede, _realidade_sede_texto, _render_anomalias, _render_beneficios_socios, _render_benford, _render_conflito_pessoal, _render_cruzamento, _render_doacoes_tse, _render_execucao, _render_rodizio_fornecedor, _rodizio_fornecedor, _sede_status_cacheado, _sede_total_pago, _sede_velho, _verificar_sede_ondemand, render_md,
)
from compliance_agent.reporting.intel_pdf import (  # noqa: F401,E402
    _emit_md_table, _mc, _registrar_fonte, _render_parecer_pdf, _tab_header, _tab_row, render_pdf, render_pdf_html,
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
                  + (f" — R$ {moeda(o['total_pago'])} movimentados em {o['n_obs']} OBs (bruto TFE)" if o["n_obs"] else " — sem OBs na base")
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
            return (await asyncio.to_thread(_c, cnpj=cnpj_d, limite=30)).get("rede", [])
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
    cal = _recalibrar_risco(pagamentos, rede, contratado_tcerj, enriq.get("score", 0), enriq.get("risco", "—"),
                            coendereco=coend_score, anomalias=anomalias,
                            natureza_sem_fins=natureza_sem_fins, sede_status=sede_status)
    risco, score = cal["risco"], cal["score"]

    fonte_global = "REAL" if pagamentos["tem_dados"] else "SEM_DADOS_OB"
    contexto = {
        "cnpj": cnpj_d, "cnpj_fmt": fmt_cnpj(cnpj_d), "nome": nome,
        "data": date.today().isoformat(), "risco": risco, "score": score,
        "pagamentos": pagamentos, "contratos": contratos, "cardinalidade": cardinalidade, "enriq": enriq,
        "fonte_enriq": enriq.get("_fonte", "INDISPONIVEL"),
        "cruzamento": cruz, "conflito_rede": rede, "anomalias": anomalias,
        "natureza_sem_fins": natureza_sem_fins,
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


# Modelo conceitual da cadeia de despesa (ERRO CONCEITUAL a evitar: OB ≠ contrato). A relação é uma ÁRVORE:
# um PROCESSO SEI (licitação / Registro de Preços-SRP) pode gerar VÁRIOS contratos, VÁRIOS aditivos e MUITAS
# OBs; um CONTRATO gera VÁRIAS OBs (parcelas/medições). OB = pagamento (verdade); nunca contar OB como contrato.












# ───────────────────────────── render Markdown (11 seções) ─────────────────────────────













# Storage SOMADO (R2 primário + B2 transbordo, cada foto em 1 bucket). A localização COMPLETA
# ('remote:bucket/objeto') está em `verificacao_sede.visual_img_b2`; aqui só LEMOS do local EXATO gravado
# (um `rclone cat`), sem failover/duplicação. A foto NÃO fica na VM — é baixada on-demand p/ embutir no PDF.























































# Boilerplate de licitação que NÃO distingue setor (não conta como aderência de objeto×CNAE).




# ───────────────────────────── render PDF (fpdf2) ─────────────────────────────



















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
