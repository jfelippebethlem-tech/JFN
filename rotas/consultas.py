# -*- coding: utf-8 -*-
"""Consultas por alvo (CNPJ, nome, órgão, processo): anomalias, cartel, rodízio, cruzamento, PNCP ao vivo, empresa,
idoneidade, vínculos societários, vazamentos, diário oficial, grafo e os varredores SEI (acatamento, direcionamento).

Saiu de `rotas/investigacao.py` na O7.6 (2026-11-25), sem mudar comportamento: mesmas rotas, mesmos corpos.
O cache do painel e os ajudantes (`_ro`, `_cache_calc`…) continuam em `rotas/investigacao.py` e são importados de lá
(o materializador e os testes redirecionam aqueles nomes naquele módulo)."""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from rotas.investigacao import _cache_calc, _cache_get, _cache_put, _com_teto, _ro

router = APIRouter()


@router.get("/api/anomalias")
def api_anomalias(orgao: Optional[str] = None, fornecedor: Optional[str] = None, top: int = 20,
                        incluir_gov: bool = False):
    """Ranking de OBs suspeitas (Onda 1): score PyOD + red flags determinísticas. Filtros: ?orgao= &fornecedor= &top=.

    Honestidade: cada item é INDÍCIO para investigação interna, NUNCA acusação. Rode antes:
    `python -m compliance_agent.anomalias --rodar`."""
    try:
        from compliance_agent import anomalias
        top = max(1, min(int(top or 20), 200))
        rows = anomalias.top_anomalias(top, orgao, fornecedor, incluir_gov=incluir_gov)
        itens = [{
            "ob": r.get("numero_ob"), "data": r.get("data_emissao"),
            "ug": r.get("ug_codigo"), "ug_nome": r.get("ug_nome"),
            "fornecedor": r.get("favorecido_nome"), "cnpj": r.get("favorecido_cpf"),
            "valor": round(r.get("valor") or 0, 2), "score": round(r.get("score") or 0, 3),
            "regras": r.get("regras"), "parecer": r.get("pareceres"),
            "porque": anomalias.explicar_features(r.get("top_features")),
        } for r in rows]
        # Onda 3 — Benford sobre a população filtrada (UG/fornecedor); só quando há filtro
        # (o agregado global sempre conforma; o desvio aparece no recorte).
        benford = None
        if orgao or fornecedor:
            from compliance_agent.analysis.benford import benford_ob
            benford = benford_ob(orgao, fornecedor)
        modelo = anomalias.estado_modelo()   # INDISPONÍVEL (modelo não rodado sobre o SIAFE) ≠ "0 anomalias"
        return JSONResponse({"ok": True, "n": len(itens) if modelo["estado"] != "INDISPONÍVEL" else None,
                             "itens": itens, "benford": benford, "modelo": modelo,
                             "fonte": "OB paga do SIAFE (régua _ob_paga); TFE fora",
                             "aviso": "Indícios para apuração interna — não constituem acusação."})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/cartel")
@router.post("/api/cartel")  # aceita GET e POST: o Yoda às vezes chuta o método (evita 405 na integração)
def api_cartel(modo: str = "captura", cnpj: Optional[str] = None, top: int = 20):
    """Grafo fornecedor↔órgão (Onda 3). ?modo=captura (UGs concentradas) | dependencia (fornecedores
    presos a 1 órgão) | vizinhanca&cnpj=... (co-ocorrência/rodízio). Indício a verificar, nunca acusação."""
    try:
        from compliance_agent import grafo_cartel as G
        top = max(1, min(int(top or 20), 100))
        # captura/dependencia varrem a base inteira e não dependem de cnpj. Medido 21/11/2026 sob carga: 24 s e 51 s
        # (não ~3 s) → `_cache_calc` (um cálculo por chave + entrega o último valor enquanto recalcula), TTL 1 h:
        # a OB do SIAFE muda por dia, não por minuto.
        if modo in ("captura", "dependencia"):
            def _calc():
                dados = (G.dependencia_fornecedores(limite=top) if modo == "dependencia"
                         else G.captura_orgaos(limite=top))
                return {"ok": True, "modo": modo, "dados": dados,
                        "aviso": "Indícios de captura/cartel para apuração interna — não constituem acusação."}
            return JSONResponse(_cache_calc(f"cartel:{modo}:{top}", 3600, _calc))
        if modo == "vizinhanca":
            if not cnpj:
                return JSONResponse({"ok": False, "erro": "informe ?cnpj="}, status_code=400)
            dados = G.vizinhanca_cartel(cnpj, limite=top)
        elif modo == "rede":  # fornecedores com sócio em comum (Onda 4)
            if not cnpj:
                return JSONResponse({"ok": False, "erro": "informe ?cnpj="}, status_code=400)
            from compliance_agent import rede_societaria as R
            dados = R.rede_por_socio(cnpj)
        elif modo == "cruzado":  # co-ocorrência + sócio comum (persistido socios_fornecedor, top-300)
            if not cnpj:
                return JSONResponse({"ok": False, "erro": "informe ?cnpj="}, status_code=400)
            from compliance_agent import rede_societaria as R
            dados = R.cruzar_cartel(cnpj)
        elif modo == "qsa":  # vizinhança de cartel + QSA cruzado AO VIVO (cadeia BrasilAPI→OpenCNPJ→CNPJ.ws)
            if not cnpj:
                return JSONResponse({"ok": False, "erro": "informe ?cnpj="}, status_code=400)
            dados = G.cartel_com_qsa(cnpj, limite=top)
        else:
            dados = G.captura_orgaos(limite=top)
        out = {"ok": True, "modo": modo, "dados": dados,
               "aviso": "Indícios de captura/cartel para apuração interna — não constituem acusação."}
        return JSONResponse(out)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/rodizio")
@router.post("/api/rodizio")  # aceita GET e POST (o Yoda às vezes chuta o método)
def api_rodizio(ug: Optional[str] = None, top: int = 20, qsa: int = 0):
    """Rodízio temporal de cartel (bid rotation): vencedores que se revezam no topo de uma UG ano a ano.
    ?ug=036100 → analisa uma UG (&qsa=1 cruza sócios dos campeões = concorrência fictícia) | sem ug →
    varredura das UGs com indício. Indício a verificar, nunca acusação."""
    try:
        from compliance_agent import rodizio_temporal as RT
        top = max(1, min(int(top or 20), 100))
        if ug:
            dados = RT.rodizio_com_qsa(str(ug)) if qsa else RT.rodizio_orgao(str(ug))
        else:
            dados = RT.rodizio_varredura(limite=top)
        return JSONResponse({"ok": True, "ug": ug, "dados": dados,
                             "aviso": "Indício de rodízio de vencedores para apuração interna — "
                                      "OB é o pagamento, não a lista de licitantes; corroborar no SEI/PNCP."})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/cruzamento")
async def api_cruzamento(cnpj: str):
    """Cruzamento sócio × OB (SIAFE) × processo SEI × endereço de um fornecedor (Onda 4+).
    Retorna sócios, empresas com sócio em comum (com cidade/mesma sede), fornecedores no MESMO
    endereço (red flag de fachada, independe de sócio), processos SEI e indícios. Indício, nunca acusação."""
    try:
        from compliance_agent.cruzamento import cruzar_async
        dados = await cruzar_async(cnpj)
        return JSONResponse({"ok": True, "dados": dados,
                             "aviso": "Indícios de grupo econômico/fachada para apuração interna — não são acusação."})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/orgao/cidades")
def api_orgao_cidades(ug: Optional[str] = None, top: int = 20):
    """Concentração GEOGRÁFICA dos fornecedores de um órgão (ou de todo o Estado se ug ausente):
    em que cidades se sediam quem o órgão paga. Red flag de fachada/direcionamento (art. 337-F CP)."""
    try:
        from compliance_agent.cruzamento import cidades_de_orgao
        top = max(1, min(int(top or 20), 100))
        dados = cidades_de_orgao(ug=ug, limite=top)
        return JSONResponse({"ok": dados.get("ok", False), "dados": dados})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/pncp")
async def api_pncp(uf: str = "RJ", orgao: str = "", cnpj: str = "", id: str = "",
                   abertos: bool = False, modalidade: int = 0, dias: int = 30,
                   esfera: str = ""):
    """Onda 2 — PNCP (API pública de consulta, sem login): licitação SEM depender do SEI.

    - id= : ANÁLISE PROFUNDA de uma contratação (numeroControlePNCP) — baixa o edital/TR
      (PDF/ZIP/DOCX) e roda os red flags R3/R5/R7/R9/R12 do Lex sobre o texto real (Onda 2c).
    - cnpj= : contratos de um FORNECEDOR (CNPJ) no período (API de gestão).
    - senão : contratações publicadas (histórico) ou com PROPOSTA EM ABERTO (abertos=true,
      fiscalização preventiva), filtráveis por uf/orgão(cnpj)/modalidade. modalidade=0 varre
      as de maior risco (pregão/dispensa/inexigibilidade/concorrência). dias = janela de busca.
    Retorno: {ok, modo, ...}. Indício, nunca acusação (presunção de legitimidade).
    """
    from datetime import date, timedelta

    try:
        from compliance_agent.collectors import pncp

        hoje = date.today()
        if id:
            from compliance_agent.lex import analisar_texto_edital

            docs = await pncp.baixar_documentos(id)
            texto = "\n".join(d.get("texto", "") for d in docs)
            analise = analisar_texto_edital(texto, numero=id)
            # não devolve o texto bruto (grande) — só metadados dos docs + os achados
            docs_meta = [{k: d[k] for k in ("titulo", "tipo", "url", "n_chars")} for d in docs]
            return JSONResponse(content={
                "ok": True, "modo": "analise", "id_pncp": id,
                "docs": docs_meta, "lido": analise["lido"],
                "red_flags": analise["achados"],
                "_fonte": "PNCP API (arquivos do edital) + motor Lex R1-R12",
                "_nota": "Indício a verificar (presunção de legitimidade); achados sobre o TEXTO "
                         "lido do edital. lido=false => download/extração não retornou texto."})
        if cnpj:
            contratos = await pncp.buscar_contratos_fornecedor(
                cnpj, hoje - timedelta(days=max(dias, 365)), hoje)
            return JSONResponse(content={"ok": True, "modo": "fornecedor", "cnpj": cnpj,
                                         "n": len(contratos), "contratos": contratos,
                                         "_fonte": "PNCP API consulta (sem login)"})
        ck = f"pncp:{uf}:{orgao}:{abertos}:{modalidade}:{dias}:{esfera}"
        if (cache := _cache_get(ck, 3600)) is not None:
            return JSONResponse(content=cache)
        contratacoes, nota = await _com_teto(pncp.buscar_contratacoes(
            uf=uf, data_ini=hoje - timedelta(days=dias), data_fim=hoje,
            modalidade=(modalidade or None), abertos=abertos,
            orgao_cnpj=(orgao or None)), "PNCP")
        if nota:  # indisponibilidade NÃO entra no cache: congelaria a aba vazia por 1 h
            return JSONResponse(content={
                "ok": True, "indisponivel": True, "uf": uf, "n": 0, "contratacoes": [],
                "_fonte": "PNCP API consulta (sem login)", "_nota": nota})
        if esfera and esfera != "todas":
            # esfera OFICIAL do ente (pncp_ente + exceções de unidade) — aba estanque no painel
            from compliance_agent.collectors.pncp_resultados import (
                classificar_esfera, esferas_por_ente)
            _c = _ro()
            try:
                oficial = esferas_por_ente(_c)
            finally:
                _c.close()
            contratacoes = [x for x in contratacoes if classificar_esfera(
                {"orgao_cnpj": x.get("orgao_cnpj"), "orgao_nome": x.get("orgao"),
                 "unidade_nome": x.get("unidade"), "municipio": x.get("municipio")},
                oficial) == esfera]
        return JSONResponse(content=_cache_put(ck, {
            "ok": True, "modo": "abertos" if abertos else "publicacao",
            "uf": uf, "n": len(contratacoes), "contratacoes": contratacoes,
            "_fonte": "PNCP API consulta (sem login)",
            "_nota": "Indício/triagem; red_flags do edital virão da Onda 2c. Proveniência: link+id_pncp."}))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/empresa")
def api_empresa(cnpj: str):
    """Onda 12 (providers) — cadastro + sócios (QSA) por CNPJ, fonte hospedada (BrasilAPI→cnpj.pw).
    Sem baixar base: HTTP sob demanda + cache TTL. Resposta com proveniência (fonte+data+estado)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("registry", cnpj=cnpj).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/idoneidade")
def api_idoneidade(cnpj: str = "", nome: str = ""):
    """Onda 12 (providers) — triagem em listas: CEIS/CNEP (BR) + sanções/PEP (OpenSanctions).
    lookup_all: consulta todos os backends disponíveis. Indício a confirmar, nunca acusação."""
    try:
        from compliance_agent.providers import get_providers
        res = get_providers().lookup_all("sanctions", cnpj=(cnpj or None), nome=(nome or None))
        return JSONResponse(content={"resultados": [r.__dict__ for r in res]})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/ownership")
def api_ownership(nome: str = "", lei: str = ""):
    """Onda 12 (providers) — controle internacional (LEI + relações) via GLEIF (sem chave)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("ownership", nome=(nome or None), lei=(lei or None)).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/leaks")
def api_leaks(termo: str):
    """Onda 12 (providers) — busca hospedada em vazamentos offshore (ICIJ; link MANUAL)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("leaks", termo=termo).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/links")
def api_links(nome: str = "", cnpj: str = ""):
    """Onda 12 (providers) — pistas de investigação HOSPEDADA (Max Intel, OSINT-Brazuca, Bellingcat,
    RedeCNPJ, JusBrasil/Escavador). Deep-links já preenchidos com o alvo; uso MANUAL (o JFN só monta)."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("links", nome=(nome or None), cnpj=(cnpj or None)).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/diario")
def api_diario(querystring: str, territory_ids: str = "", desde: str = "", ate: str = "", size: int = 20):
    """Onda 12 (providers) — diários oficiais municipais (Querido Diário). Busca por palavra-chave +
    território IBGE (RJ capital = 3304557) + janela de datas. Sem chave; on-demand + cache."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("gazettes", querystring=querystring, territory_ids=territory_ids,
                                           desde=desde, ate=ate, size=size).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/doador_contrato")
def api_doador_contrato(cnpj: str):
    """Onda 12 (providers) — TSE doador×contrato: sócios (QSA) do fornecedor que aparecem como
    doadores de campanha (RJ). Indício de conflito a CONFERIR, nunca acusação (CPF mascarado → casa
    por nome). Requer doacao_tse populado (carregar_doacoes_rj(ano))."""
    try:
        from compliance_agent.providers import lookup
        return JSONResponse(content=lookup("eleitoral", cnpj=cnpj).__dict__)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/grafo")
def api_grafo(alvo: str, saltos: int = 2, so_contrato: bool = False):
    """Onda 4 — Grafo de Poder: vizinhança de um alvo (CNPJ/UG/nome) unindo
    sócios+OB+doações+folha+co-endereço, até `saltos`. so_contrato=true foca o fluxo
    de dinheiro (cnpj↔ug↔sócio). Vínculo = indício de relação, nunca prova."""
    try:
        from compliance_agent.grafo_poder import vizinhanca

        return JSONResponse(content=vizinhanca(alvo, saltos=saltos, so_contrato=so_contrato))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/grafo/ftm")
def api_grafo_ftm(alvo: str, saltos: int = 2):
    """Onda 12 — Export do Grafo de Poder no modelo FollowTheMoney (interoperar c/ Aleph/Gephi)."""
    try:
        from compliance_agent.grafo_ftm import export
        return JSONResponse(content=export(alvo, saltos=saltos))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/sei/acatamento")
async def api_sei_acatamento(processo: str = ""):
    """Auditoria de ACATAMENTO de pareceres (art. 53 Lei 14.133; dossiê mestre §4): a autoridade
    acolheu, contrariou motivadamente, silenciou ou ignorou os pareceres de PGE/PGM/CGE/CGM/jurídico?
    Lê o ARQUIVO compacto do processo (regra da casa: arquivo antes de browser). ?processo=SEI-.../nº."""
    if not (processo or "").strip():
        return JSONResponse({"ok": False, "erro": "informe ?processo=<nº SEI>"}, status_code=400)
    try:
        from compliance_agent.sei_recomendacoes import auditar_acatamento
        from tools.backfill_dossie_mestre import ARQUIVO, _leitura_do_arquivo

        slug = "".join(c if c.isalnum() else "_" for c in processo.replace("SEI-", "")).strip("_")
        pdir = ARQUIVO / slug
        leitura = await asyncio.to_thread(_leitura_do_arquivo, pdir)
        if not leitura:
            return JSONResponse({"ok": False, "erro": f"processo '{processo}' sem arquivo compacto em "
                                 "data/sei_arquivo (rode tools/sei_consultar primeiro) — INDISPONÍVEL ≠ 0"},
                                status_code=404)
        docs = [{"ref": d["doc"], "tipo": d["doc"], "texto": d["conteudo"]}
                for d in leitura["conteudo_documentos"]]
        r = await asyncio.to_thread(auditar_acatamento, docs)
        return JSONResponse({"ok": True, "processo": leitura["numero"], "n_docs": len(docs), **r})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/sei/direcionamento")
async def api_sei_direcionamento(ug: str = "", objeto: str = "", uf: str = "RJ", max_itens: int = 8):
    """Onda 5 — Varredor de direcionamento: busca editais (PNCP), extrai por schema, roda
    red flags do Lex e ranqueia por gravidade. ?ug= (cnpj órgão) &objeto= (filtro). Indício
    de restrição/direcionamento a verificar, nunca acusação."""
    try:
        from compliance_agent.sei_direcionamento import varrer_direcionamento

        ck = f"seidir:{uf}:{ug}:{objeto}:{max_itens}"
        if (cache := _cache_get(ck, 3600)) is not None:
            return JSONResponse(content=cache)
        res, nota = await _com_teto(
            varrer_direcionamento(uf=uf, ug=(ug or None), objeto=(objeto or None),
                                  max_itens=max(1, min(int(max_itens), 15))),
            "PNCP (varredura de direcionamento)")
        if nota:
            return JSONResponse(content={"ok": True, "indisponivel": True, "itens": [],
                                         "_nota": nota})
        return JSONResponse(content=_cache_put(ck, res))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/sancoes/detalhar")
def api_sancoes_detalhar(cnpj: str = "", esfera: str = "estadual", uf: str = "RJ"):
    """Detalha as sanções de um CNPJ: tipo, abrangência, órgão, vigência e se VEDA de fato o
    contrato com o ente-alvo (default Estado-RJ). Responde 'quais são e qual a abrangência'."""
    try:
        from compliance_agent.sancao_abrangencia import detalhar
        c = re.sub(r"\D", "", cnpj or "")
        if len(c) != 14:
            return JSONResponse({"ok": False, "erro": "CNPJ inválido"})
        con = _ro(linhas=True)
        try:
            return JSONResponse(detalhar(c, con, esfera, (uf or "RJ").upper()))
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)
