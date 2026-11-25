# -*- coding: utf-8 -*-
"""Rotas `/api/intel/*` de contratação e execução (sanções, conluio, fracionamento, aditivos,
escalada, sobrepreço, prioridade por valor…) + `/api/doerj/tac_recorrente` e `/api/imprensa/orgaos`.

Saiu de `rotas/investigacao.py` na O7.6 (2026-11-25), sem mudar comportamento: mesmas rotas, mesmos corpos.
O cache do painel e os ajudantes (`_ro`, `_cache_calc`…) continuam em `rotas/investigacao.py` e são importados de lá
(o materializador e os testes redirecionam aqueles nomes naquele módulo)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from rotas.investigacao import RAIZ, _cache_calc, _ro, logger

router = APIRouter()


# ── INTELIGÊNCIA 2026-07-17: sancionadas × contratadas, perdedoras contumazes, fantasmas ──

@router.get("/api/intel/sancionadas")
def api_intel_sancionadas(limite: int = 60):
    """Empresas com sanção IMPEDITIVA (CEIS/CNEP) que receberam OB do Estado ou venceram no PNCP —
    com o teste temporal "à época" (ato DENTRO da vigência da sanção). Cache materializado por
    tools/intel (cruzamentos_intel.gerar_cache_intel); fallback = computa na hora."""
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel, sancionadas_contratadas
        d = ler_cache_intel("sancionadas_contratadas")
        if not d:
            d = _cache_calc("intel:sanc", 3600, lambda: sancionadas_contratadas())
        d = dict(d)
        # teto explícito 1000 > n atual (770): cobre a base inteira (~839 KB, leitura de cache)
        d["empresas"] = d.get("empresas", [])[:max(1, min(int(limite or 60), 1000))]
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/doerj/tac_recorrente")
def api_doerj_tac_recorrente(top: int = 20):
    """Termos de Ajuste de Contas publicados no DOERJ (PDF integral, desde 09/09/2026) — quem recebe
    sem cobertura contratual, quantas vezes, quanto. Materializado por tools/doerj_tac_recorrente
    (cruzador 23:00). Valores são os PUBLICADOS nos extratos, não OB; fornecedor '(não lido)' = extrato
    sem campo PARTES legível (conta na soma, não no ranking)."""
    con = _ro()
    try:
        try:
            tot = con.execute("SELECT count(*), count(valor), round(sum(valor),2), min(data_doe), max(data_doe), "
                              "count(DISTINCT fornecedor) FROM doerj_tac").fetchone()
        except sqlite3.OperationalError:
            return JSONResponse({"ok": True, "aviso": "doerj_tac ainda não materializada", "total": 0, "itens": []})
        itens = [dict(zip(("fornecedor", "n", "n_com_valor", "soma", "n_orgaos", "de", "ate", "processos"), r))
                 for r in con.execute(
                     "SELECT fornecedor, count(*), count(valor), round(sum(valor),2) AS soma, count(DISTINCT orgao), "
                     "min(data_doe), max(data_doe), count(DISTINCT processo) FROM doerj_tac "
                     "WHERE fornecedor IS NOT NULL GROUP BY fornecedor ORDER BY count(*) DESC, soma DESC LIMIT ?",
                     (max(1, min(int(top or 20), 200)),))]
        orgaos = [dict(zip(("orgao", "n", "soma"), r)) for r in con.execute(
            "SELECT coalesce(orgao,'(não lido)'), count(*), round(sum(valor),2) FROM doerj_tac GROUP BY 1 "
            "ORDER BY 2 DESC LIMIT 8")]
        # sinais de favorecimento por fornecedor (tools/doerj_tac_favorecimento, cruzador 1d) — 🔴 antes
        sinais: dict[str, list] = {}
        try:
            for f, grau, sinal, det in con.execute(
                    "SELECT fornecedor, grau, sinal, detalhe FROM doerj_tac_sinal WHERE sinal <> 'cnpj_nao_localizado'"):
                sinais.setdefault(f, []).append({"grau": grau, "sinal": sinal, "detalhe": det})
        except sqlite3.OperationalError:
            logger.debug("investigacao.py:1693: exceção ignorada (era except-pass mudo)", exc_info=True)
        for it in itens:
            it["sinais"] = sorted(sinais.get(it["fornecedor"], []), key=lambda x: x["grau"] != "🔴")
        nao_lidos = con.execute("SELECT count(*) FROM doerj_tac WHERE fornecedor IS NULL").fetchone()[0]
        edicoes = con.execute("SELECT count(DISTINCT data_publicacao) FROM publicacoes_doerj").fetchone()[0]
        # controle externo do extrator (10/09): processo do TAC → credor da OB no SIAFE; None = ainda não medido
        concordancia = None
        try:
            _m = con.execute("SELECT valor, texto, em FROM doerj_tac_meta WHERE chave='concordancia_siafe'").fetchone()
            if _m:
                concordancia = {"taxa": _m[0], "texto": _m[1], "em": _m[2]}
        except sqlite3.OperationalError:
            logger.debug("investigacao.py:1705: exceção ignorada (era except-pass mudo)", exc_info=True)
    finally:
        con.close()
    return JSONResponse({"ok": True, "total": tot[0], "com_valor": tot[1], "soma": tot[2] or 0, "de": tot[3],
                         "ate": tot[4], "fornecedores": tot[5], "nao_lidos": nao_lidos, "edicoes": edicoes,
                         "itens": itens, "orgaos": orgaos, "concordancia": concordancia,
                         "sinais_total": sum(len(v) for v in sinais.values()),
                         "sinais_vermelhos": sum(1 for v in sinais.values() for x in v if x["grau"] == "🔴"),
                         # fornecedores por sinal (o mecanismo "contrato venceu → TAC" tem KPI próprio no painel)
                         "por_sinal": {k: sum(1 for v in sinais.values() if any(x["sinal"] == k for x in v))
                                       for k in sorted({x["sinal"] for v in sinais.values() for x in v})}})


@router.get("/api/imprensa/orgaos")
def api_imprensa_orgaos(dias: int = 30, so_adversas: int = 1, limite: int = 120):
    """Imprensa sobre os ÓRGÃOS do Estado/Prefeitura (Google News RSS, sem chave; tools/noticias_orgaos, diário).
    Adversa = título com termo de risco (fraude, operação, TCE, MP…). Indício a confirmar na fonte — nunca prova."""
    import datetime as _dt
    con = _ro()
    try:
        try:
            desde = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=max(1, min(int(dias or 30), 365)))).isoformat(timespec="seconds")
            cond = " AND adversa=1" if so_adversas else ""
            itens = [dict(zip(("orgao", "titulo", "url", "fonte", "data", "adversa", "termos"), r)) for r in con.execute(
                f"SELECT orgao, titulo, url, fonte, data, adversa, termos FROM noticias_orgaos WHERE data >= ?{cond} ORDER BY data DESC LIMIT ?",
                (desde, max(1, min(int(limite or 120), 500))))]
            por_orgao = [dict(zip(("orgao", "n", "adversas"), r)) for r in con.execute(
                "SELECT orgao, count(*), sum(adversa) FROM noticias_orgaos WHERE data >= ? GROUP BY 1 ORDER BY 3 DESC, 2 DESC", (desde,))]
            tot = con.execute("SELECT count(*), sum(adversa), max(visto_em) FROM noticias_orgaos").fetchone()
        except sqlite3.OperationalError:
            return JSONResponse({"ok": True, "aviso": "noticias_orgaos ainda não coletada", "itens": [], "por_orgao": []})
    finally:
        con.close()
    return JSONResponse({"ok": True, "dias": dias, "itens": itens, "por_orgao": por_orgao, "total": tot[0], "adversas_total": tot[1] or 0,
                         "coletado_em": tot[2]})


@router.get("/api/intel/sancionadas_municipio")
def api_intel_sancionadas_municipio(limite: int = 60):
    """Empresas com sanção IMPEDITIVA contratadas pela PREFEITURA DO RIO (pcrj_contratos fonte='pncp'),
    com o teste "à época" (contrato ASSINADO dentro da vigência da sanção). Análogo municipal do
    /api/intel/sancionadas (competência TCM-RJ). Descarta órgão federal/estadual (contabiliza)."""
    try:
        from compliance_agent.cruzamentos_intel import sancionadas_municipio
        ck = "intel:sanc_mun"
        d = _cache_calc(ck, 3600, lambda: sancionadas_municipio())
        d = dict(d)
        d["empresas"] = d.get("empresas", [])[:max(1, min(int(limite or 60), 300))]
        d["explicacao"] = ("Contratação municipal do Rio de empresa sob sanção impeditiva vigente à "
                           "época da assinatura (vedação: Lei 14.133 art. 156 §1º). Competência de "
                           "controle externo: TCM-RJ. `descartados_outra_esfera` = órgãos federais "
                           "(ex.: Fiocruz) e estaduais excluídos por não serem do Município.")
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/concentracao_municipio")
def api_intel_concentracao_municipio(limite: int = 60):
    """Concentração de fornecedor por RAMO de objeto no município do Rio (HHI + top-share sobre
    pcrj_contratos, fonte='pncp'). Análogo municipal do cartel do Estado (que lê OB SIAFE).
    Base = valor CONTRATADO, não pago (ressalva no payload). Competência TCM-RJ."""
    try:
        from compliance_agent.cruzamentos_intel import concentracao_municipio
        ck = "intel:conc_mun"
        d = _cache_calc(ck, 3600, lambda: concentracao_municipio(limite=max(1, min(int(limite or 60), 200))))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001 — idioma-padrão das rotas (catch-and-return)
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/perdedoras")
def api_intel_perdedoras():
    """Perdedoras contumazes ("nunca ganharam"): participam de ≥K certames nas atas e nunca vencem —
    perfil de proposta de cobertura (OCDE). Sai do cache (varrer 8k atas não roda no request)."""
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel
        d = ler_cache_intel("perdedoras_contumazes")
        if not d:
            return JSONResponse({"ok": False, "erro": "cache ainda não gerado — "
                                 "rodar: python -m compliance_agent.cruzamentos_intel cache"})
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/conluio_qsa")
def api_intel_conluio_qsa():
    """CONLUIO DIRETO: vencedor × perdedora do MESMO certame com sócio em comum (QSA Receita)
    ou matriz×filial concorrendo entre si. Cache do intel (com atas); fallback = só PNCP."""
    try:
        from compliance_agent.cruzamentos_intel import conluio_qsa, ler_cache_intel
        d = ler_cache_intel("conluio_qsa")
        if not d:
            d = _cache_calc("intel:conluio", 3600, lambda: conluio_qsa(incluir_atas=False))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/comunidades")
def api_intel_comunidades():
    """Comunidades (Louvain) do grafo família-empresa-órgão, ranqueadas por risco 0-100.
    Sai do cache (construir o grafo completo não roda no request)."""
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel
        from compliance_agent.proveniencia_manchetes import anexar
        d = ler_cache_intel("comunidades")
        if not d:
            return JSONResponse({"ok": False, "erro": "cache ainda não gerado — "
                                 "rodar: python -m compliance_agent.cruzamentos_intel cache"})
        return JSONResponse(anexar("/api/intel/comunidades", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/radar")
def api_intel_radar(limite: int = 100):
    """RADAR composto: score 0-100 por fornecedor somando os sinais de todos os detectores —
    a fila de apuração priorizada. Cache do intel; fallback = computa na hora."""
    try:
        from compliance_agent.cruzamentos_intel import ler_cache_intel, radar_risco
        d = ler_cache_intel("radar_risco")
        if not d:
            lim = max(1, min(int(limite or 100), 300))
            d = _cache_calc(f"intel:radar:{lim}", 3600, lambda: radar_risco(limite=lim))
        from compliance_agent.proveniencia_manchetes import anexar
        return JSONResponse(anexar("/api/intel/radar", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/retro")
def api_intel_retro():
    """Retro-auditoria (hindsight): por detector, sanção POSTERIOR ao 1º sinal (corroboração
    independente) e R$ pagos/vitórias APÓS o alerta (custo da inação). Ledger diário no timer."""
    try:
        from compliance_agent.retro_auditoria import medir
        d = _cache_calc("intel:retro", 3600, lambda: medir())
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/lift")
def api_intel_lift():
    """Validação de cada detector contra o gabarito OBJETIVO (sanções impeditivas): LIFT = taxa de
    sancionados no que o detector marca ÷ taxa-base do universo. lift>1 = sinal; <1 = anti-sinal."""
    try:
        from compliance_agent.retro_auditoria import avaliar_lift
        d = _cache_calc("intel:lift", 3600, lambda: avaliar_lift())
        from compliance_agent.proveniencia_manchetes import anexar
        return JSONResponse(anexar("/api/intel/lift", d))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/fracionamento")
def api_intel_fracionamento(limite: int = 120):
    """Fracionamento de despesa pelo OBJETO (Lei 14.133 art. 75 §1º): unidade gestora × exercício ×
    natureza do objeto, soma das dispensas por valor contra o teto do ano, qualquer que seja o fornecedor.
    O agrupamento por CREDOR+UG+mês não é servido: mede pagamento de contrato contínuo, não fracionamento."""
    try:
        from compliance_agent.fracionamento_objeto import fracionamento_por_objeto
        lim = max(1, min(int(limite or 120), 300))
        d = fracionamento_por_objeto(limite=lim)
        # 23/11/2026: a lista "mesmo credor + UG + mês" SAIU da tela. Ela mede PAGAMENTO, não contratação:
        # enchia de serviço contínuo (luz, vigilância, publicidade, combustível — um contrato pago mês a mês)
        # e de transferência a ente público. Fracionamento é o MESMO OBJETO em contratações distintas.
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/pdf")
async def api_intel_pdf(tipo: str):
    """Gera o PDF Kroll do detector `tipo` e devolve a URL. Síncrono (detectores são rápidos/cache)."""
    try:
        from compliance_agent.intel_relatorio import gerar_pdf_intel
        d = await gerar_pdf_intel(tipo, db_path=str(RAIZ / "data" / "compliance.db"))
        return JSONResponse(d, status_code=200 if d.get("ok") else 400)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/capital_incompativel")
def api_intel_capital(limite: int = 120):
    """Capital irrisório (<R$50k) frente ao volume recebido (≥100× o capital) — subcapitalização/
    fachada (Lei 14.133 art. 5, 62-63). Fonte do capital: dump da Receita (empresas_cadastro)."""
    try:
        from compliance_agent.cruzamentos_intel import capital_incompativel
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:capinc:{lim}", 600, lambda: capital_incompativel(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/prioridade_valor")
def api_intel_prioridade_valor(limite: int = 60, min_score: int = 10):
    """Fila priorizada por VALOR EM RISCO: interseção do RADAR (fornecedor arriscado) com a ECONOMIA
    POTENCIAL (R$ recuperável se tivesse pago a mediana). Cruza 'quem paga mais' com o radar."""
    try:
        from compliance_agent.cruzamentos_intel import prioridade_valor
        lim = max(1, min(int(limite or 60), 200))
        ms = max(0, min(int(min_score or 10), 100))
        d = _cache_calc(f"intel:prival:{lim}:{ms}", 900, lambda: prioridade_valor(min_score=ms, limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/fornecedor_dependente")
def api_intel_fornecedor_dependente(limite: int = 120):
    """Fornecedor comercial com ≥90% da receita do Estado numa única unidade gestora ('empresa do órgão')."""
    try:
        from compliance_agent.cruzamentos_intel import fornecedor_dependente
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:dep:{lim}", 3600, lambda: fornecedor_dependente(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/corrida_dezembro")
def api_intel_corrida_dezembro(limite: int = 120):
    """Fornecedor comercial com ≥75% do valor do ano concentrado em dezembro (corrida do empenho)."""
    try:
        from compliance_agent.cruzamentos_intel import corrida_dezembro
        lim = max(1, min(int(limite or 120), 300))
        d = _cache_calc(f"intel:dez:{lim}", 600, lambda: corrida_dezembro(limite=lim))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/competencia_futura")
def api_intel_competencia_futura():
    """OB SIAFE paga antes da competência que quita: antecipação (L.14.133 art. 145) ou ano registrado errado.
    Sem `except` genérico de propósito (catraca): erro aqui é 500 honesto, não `ok:false` mudo."""
    from compliance_agent.pagamento_competencia_futura import pagamento_competencia_futura
    return JSONResponse(_cache_calc("intel:competencia_futura", 3600, pagamento_competencia_futura))


@router.get("/api/intel/dea_recorrente")
def api_intel_dea_recorrente():
    """DEA (elemento 92) repetida ao mesmo fornecedor em processos distintos — serviço sem empenho prévio
    (L.4320 arts. 37 e 60). Só UGs com Nota de Empenho coletada. Sem `except` genérico (catraca)."""
    from compliance_agent.dea_recorrente import dea_recorrente
    return JSONResponse(_cache_calc("intel:dea_recorrente", 3600, dea_recorrente))


@router.get("/api/intel/ordem_cronologica")
def api_intel_ordem_cronologica():
    """Quebra da ordem cronológica medida no SIAFE (Dec. RJ 49.134/2024 art. 9º: data da NL por fonte).
    Só UGs com NE e NL coletadas. Sem `except` genérico (catraca)."""
    from compliance_agent.ordem_cronologica_siafe import ordem_cronologica
    return JSONResponse(_cache_calc("intel:ordem_cronologica", 3600, ordem_cronologica))


@router.get("/api/intel/aditivos")
def api_intel_aditivos(limite: int = 120, esfera: str = ""):
    """Aditivos que estouram o limite legal de acréscimo (25%/50%, Lei 14.133 art. 125) e change
    orders em série (≥3 aditivos). Fonte: pcrj_contratos + contrato_aditivo."""
    try:
        from compliance_agent.cruzamentos_intel import aditivos_estouro
        lim = max(1, min(int(limite or 120), 300))
        ck = f"intel:adit:{lim}:{esfera or 'todas'}"
        d = _cache_calc(ck, 600, lambda: aditivos_estouro(limite=lim, esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/escalada")
def api_intel_escalada(limite: int = 120, esfera: str = ""):
    """Escalada de preço unitário: MESMO fornecedor vende o MESMO item por preços cada vez maiores
    ao longo do tempo (≥3 compras, ≥45 dias, alta ≥3×). Preço dirigido/captura. Fonte: PNCP."""
    try:
        from compliance_agent.cruzamentos_intel import escalada_preco
        lim = max(1, min(int(limite or 120), 300))
        ck = f"intel:escal:{lim}:{esfera or 'todas'}"
        d = _cache_calc(ck, 3600, lambda: escalada_preco(limite=lim, esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/intel/sobrepreco")
def api_intel_sobrepreco(limite: int = 120, esfera: str = ""):
    """Sobrepreço por mediana de item: mesmo produto (descrição normalizada) comprado por vários
    órgãos; sinaliza preço unitário ≥2× a mediana (e fora de mediana+3·MAD). Fonte: PNCP."""
    try:
        from compliance_agent.cruzamentos_intel import sobrepreco
        lim = max(1, min(int(limite or 120), 300))
        ck = f"intel:sobre:{lim}:{esfera or 'todas'}"
        d = _cache_calc(ck, 3600, lambda: sobrepreco(limite=lim, esfera=esfera or None))
        return JSONResponse(d)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)
