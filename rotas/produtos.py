# -*- coding: utf-8 -*-
"""Rotas produtos do JFN — extraído de server.py (split 2026-07-06; rede: tests/test_server_snapshot.py).
Handlers idênticos aos originais; só o decorador mudou de @app p/ @router."""
from __future__ import annotations

import logging
import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


router = APIRouter()

_REL_EM_CURSO: set = set()


_SWEEP_PAUSE_FLAGS = ("data/.pause_sweep_2", "data/.pause_sweep_1", "data/.pause_sei_sweep")


def _pausar_sweeps_para_relatorio() -> None:
    import subprocess
    try:
        for f in _SWEEP_PAUSE_FLAGS:
            Path(f).touch()
        # colchete no padrão evita casar o próprio comando (lição do auto-pkill); mata por padrão seguro
        subprocess.run(["pkill", "-f", "tools[.]sei_sweep"], check=False)
        subprocess.run(["pkill", "-f", "siafe[_]sweep_full"], check=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("não pausou os sweeps antes do relatório (competem pela CPU): %s", exc)


def _retomar_sweeps_se_ocioso() -> None:
    if _REL_EM_CURSO:  # ainda há relatório gerando → mantém pausado
        return
    try:
        for f in _SWEEP_PAUSE_FLAGS:
            Path(f).unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("não despausou os sweeps (ficam parados até remover flag manualmente): %s", exc)


async def _enviar_docs_telegram(result: dict, titulo: str) -> None:
    from compliance_agent.notifications import telegram as _tg
    # PDF primeiro (recebe a caption), depois MD (fonte legível/grep-ável p/ o Yoda), xlsx e parecer Lex.
    # path_md incluído p/ o Yoda mandar MD+PDF (antes só PDF/xlsx/lex iam — o MD ficava de fora).
    paths = [p for p in (result.get("path_pdf"), result.get("path_md"),
                         result.get("path_xlsx"), result.get("path_lex")) if p]
    if not paths:
        await _tg.enviar_mensagem(f"⚠️ {titulo}: gerado, mas sem arquivos para enviar.")
        return
    cap = (f"📄 {titulo}\n{result.get('resumo') or ''}")[:1024]
    falhas = []
    for i, p in enumerate(paths):
        r = await _tg.enviar_arquivo(p, caption=(cap if i == 0 else ""))
        if not (r or {}).get("ok"):
            # entrega muda era o pior modo de falha: o humano fica esperando um PDF que nunca chega
            logger.warning("entrega Telegram FALHOU p/ %s: %s", p, str(r)[:200])
            falhas.append(Path(p).name)
    if falhas:
        await _tg.enviar_mensagem(
            f"⚠️ {titulo}: gerado, mas {len(falhas)} arquivo(s) não subiram no Telegram "
            f"({', '.join(falhas[:3])}). Estão em ~/JFN/reports/.")


async def _gerar_e_enviar_fornecedor(cnpj, empresa, anos, key) -> None:
    from compliance_agent.notifications import telegram as _tg
    from compliance_agent.reporting.inteligencia import montar
    _pausar_sweeps_para_relatorio()
    try:
        result = await montar(cnpj=cnpj, empresa=empresa, anos=anos)
        if not result.get("ok"):
            await _tg.enviar_mensagem(result.get("pergunta") if result.get("ambiguo")
                                      else f"⚠️ Não consegui gerar o relatório: {(result.get('erro') or '')[:300]}")
            return
        await _enviar_docs_telegram(result, f"Relatório de inteligência — {result.get('empresa') or empresa or cnpj}")
    except Exception as exc:  # noqa: BLE001
        await _tg.enviar_mensagem(f"⚠️ Erro ao gerar o relatório de {empresa or cnpj}: {str(exc)[:300]}")
    finally:
        _REL_EM_CURSO.discard(key)
        _retomar_sweeps_se_ocioso()


async def _gerar_e_enviar_orgao(orgao, ug, anos, key) -> None:
    from compliance_agent.notifications import telegram as _tg
    from compliance_agent.reporting.inteligencia_orgao import montar as montar_orgao
    _pausar_sweeps_para_relatorio()
    try:
        result = await asyncio.to_thread(montar_orgao, orgao=orgao, ug=ug, anos=anos)
        if not result.get("ok"):
            await _tg.enviar_mensagem(result.get("pergunta") if result.get("ambiguo")
                                      else f"⚠️ Não consegui gerar o relatório do órgão: {(result.get('erro') or '')[:300]}")
            return
        await _enviar_docs_telegram(result, f"Relatório de órgão — {result.get('orgao') or orgao or ug}")
    except Exception as exc:  # noqa: BLE001
        await _tg.enviar_mensagem(f"⚠️ Erro ao gerar o relatório do órgão {orgao or ug}: {str(exc)[:300]}")
    finally:
        _REL_EM_CURSO.discard(key)
        _retomar_sweeps_se_ocioso()


async def _gerar_e_enviar_dossie(alvo, key) -> None:
    """Dossiê 360 ORQUESTRADO: o painel 360 (dossie: cadastro/QSA/sanções/OB/conflito/rede/mídia)
    + o relatório de INTELIGÊNCIA de fornecedor (montar) COM o parecer jurídico Lex. O pedido do
    Mestre por /dossie é o pacote completo — o painel sozinho não substitui a due diligence + Lex."""
    import re as _re
    from compliance_agent.dossie import dossie
    from compliance_agent.notifications import telegram as _tg
    from compliance_agent.reporting.inteligencia import montar
    _pausar_sweeps_para_relatorio()
    cnpj = _re.sub(r"\D", "", alvo or "")
    try:
        result = await dossie(alvo)
        if not result.get("ok"):
            await _tg.enviar_mensagem(result.get("pergunta") if result.get("ambiguo")
                                      else f"⚠️ Não consegui gerar o dossiê: {(result.get('erro') or '')[:300]}")
            return
        nome = ((result.get("cadastro") or {}).get("razao_social") or alvo)
        await _enviar_docs_telegram(result, f"Dossiê 360 (painel) — {nome}")

        # relatório de inteligência de fornecedor + parecer Lex (o "e tudo o mais")
        if len(cnpj) == 14:
            try:
                intel = await montar(cnpj=cnpj)
                if intel.get("ok"):
                    await _enviar_docs_telegram(
                        intel, f"Relatório de inteligência + parecer Lex — {intel.get('empresa') or nome}")
                else:
                    await _tg.enviar_mensagem(
                        "ℹ️ Dossiê 360 enviado; o relatório de inteligência/Lex não saiu: "
                        f"{(intel.get('erro') or intel.get('pergunta') or 'indisponível')[:200]}")
            except Exception as exc:  # noqa: BLE001
                logger.warning("dossiê: inteligência+Lex falhou p/ %s: %s", cnpj, exc)
                await _tg.enviar_mensagem(
                    "ℹ️ Dossiê 360 (painel) enviado; o relatório de inteligência/Lex falhou "
                    f"e fica pendente ({str(exc)[:160]}).")
    except Exception as exc:  # noqa: BLE001
        await _tg.enviar_mensagem(f"⚠️ Erro ao gerar o dossiê de {alvo}: {str(exc)[:300]}")
    finally:
        _REL_EM_CURSO.discard(key)
        _retomar_sweeps_se_ocioso()


@router.post("/api/relatorio/inteligencia")
async def api_relatorio_inteligencia(payload: Optional[dict] = None):
    """
    Relatório de INTELIGÊNCIA de fornecedor (motor do comando /relatorio do Yoda).
    Body JSON: {"empresa": "NOME"} OU {"cnpj": "..."} (parcial serve no nome), opcional {"anos": [2025,2026]}.
    Retorna {ok, cnpj, empresa, risco, score, resumo, path_md, path_pdf, fonte}.
    Se o nome for ambíguo, retorna {ok:false, ambiguo:true, pergunta, candidatos:[...]} para o Yoda
    repassar a dúvida ao Mestre Jorge.
    """
    from compliance_agent.reporting.inteligencia import montar
    payload = payload or {}
    cnpj = (payload.get("cnpj") or "").strip() or None
    empresa = (payload.get("empresa") or payload.get("nome") or "").strip() or None
    anos = payload.get("anos") or None
    if anos:
        try:
            anos = [int(a) for a in anos]
        except (TypeError, ValueError):
            anos = None
    if not cnpj and not empresa:
        return JSONResponse({"ok": False, "erro": "Informe 'empresa' (nome, parcial serve) ou 'cnpj'."},
                            status_code=400)
    # Geração ASSÍNCRONA: responde já e o JFN empurra os documentos quando prontos (ver helpers acima).
    if payload.get("sync"):  # modo síncrono ainda disponível (CLI/testes): {"sync": true}
        try:
            result = await montar(cnpj=cnpj, empresa=empresa, anos=anos)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "erro": f"Falha ao gerar relatório: {exc}"}, status_code=500)
        return JSONResponse(result)
    # Pré-check de ambiguidade SÍNCRONO (resolução é rápida; só a geração é lenta) → o Yoda trata a
    # dúvida normalmente (a resposta numérica do Mestre Jorge roteia certo), em vez de o JFN empurrar a
    # pergunta sem o Yoda saber. Erro/ambíguo voltam na hora; só o caso resolvido vai p/ background.
    try:
        pre = await montar(cnpj=cnpj, empresa=empresa, so_resolver=True)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": f"Falha ao resolver: {exc}"}, status_code=500)
    if not pre.get("ok") or pre.get("ambiguo"):
        return JSONResponse(pre)
    key = f"forn:{(cnpj or empresa or '').lower()}"
    if key in _REL_EM_CURSO:
        return JSONResponse({"ok": True, "status": "gerando",
                             "msg": "⏳ Já estou preparando esse relatório — te envio aqui em instantes."})
    _REL_EM_CURSO.add(key)
    asyncio.create_task(_gerar_e_enviar_fornecedor(cnpj, empresa, anos, key))
    return JSONResponse({"ok": True, "status": "gerando",
                         "msg": f"📥 Preparando o relatório de *{empresa or cnpj}* (PDF + planilha + parecer Lex). "
                                "Eu te envio aqui mesmo em ~1–2 min — não precisa repetir o comando."})


@router.post("/api/relatorio/orgao")
async def api_relatorio_orgao(payload: Optional[dict] = None):
    """
    Relatório de inteligência de ÓRGÃO (UG): quanto a unidade gestora pagou, a quem, por ano.
    Body: {"orgao":"NOME ou parcial"} OU {"ug":"133100"}, opcional {"anos":[2025,2026]}.
    Retorna {ok, ug, orgao, resumo, path_md, path_pdf, path_xlsx, path_lex, grau_lex, fonte}
    ou {ambiguo, pergunta, candidatos}. O path_lex é o PARECER LEX de órgão (grau 🟢🟡🔴).
    """
    from compliance_agent.reporting.inteligencia_orgao import montar as montar_orgao
    payload = payload or {}
    ug = (payload.get("ug") or "").strip() or None
    orgao = (payload.get("orgao") or payload.get("nome") or "").strip() or None
    anos = payload.get("anos") or None
    if anos:
        try:
            anos = [int(a) for a in anos]
        except (TypeError, ValueError):
            anos = None
    if not ug and not orgao:
        return JSONResponse({"ok": False, "erro": "Informe 'orgao' (nome, parcial serve) ou 'ug' (código)."},
                            status_code=400)
    if payload.get("sync"):  # modo síncrono (CLI/testes)
        try:
            result = montar_orgao(orgao=orgao, ug=ug, anos=anos)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "erro": f"Falha ao gerar relatório: {exc}"}, status_code=500)
        return JSONResponse(result)
    # Pré-check de ambiguidade SÍNCRONO (Yoda trata a dúvida/numérico); só o resolvido vai p/ background.
    try:
        pre = montar_orgao(orgao=orgao, ug=ug, so_resolver=True)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": f"Falha ao resolver: {exc}"}, status_code=500)
    if not pre.get("ok") or pre.get("ambiguo"):
        return JSONResponse(pre)
    key = f"orgao:{(ug or orgao or '').lower()}"
    if key in _REL_EM_CURSO:
        return JSONResponse({"ok": True, "status": "gerando",
                             "msg": "⏳ Já estou preparando esse relatório de órgão — te envio aqui em instantes."})
    _REL_EM_CURSO.add(key)
    asyncio.create_task(_gerar_e_enviar_orgao(orgao, ug, anos, key))
    return JSONResponse({"ok": True, "status": "gerando",
                         "msg": f"📥 Preparando o relatório do órgão *{orgao or ug}* (PDF + planilha + parecer Lex). "
                                "Eu te envio aqui mesmo em ~1–2 min — não precisa repetir o comando."})


@router.post("/api/dossie")
async def api_dossie(payload: Optional[dict] = None):
    """Onda 4 — Dossiê 360 de um CNPJ: cadastro+sanções+OB+conflito+rede+score → PDF.
    Body JSON: {"alvo": "<CNPJ>"}. Indícios para apuração; nenhuma fonte indisponível é fabricada.
    Geração ASSÍNCRONA: responde {status:"gerando"} na hora e o JFN empurra o PDF no Telegram quando
    fica pronto (igual /api/relatorio/inteligencia). Modo síncrono p/ CLI/testes: {"sync": true}."""
    payload = payload or {}
    alvo = (payload.get("alvo") or payload.get("cnpj") or "").strip()
    if not alvo:
        return JSONResponse(content={"ok": False, "erro": "informe {'alvo': CNPJ}"}, status_code=400)
    if payload.get("sync"):  # modo síncrono (CLI/testes)
        try:
            from compliance_agent.dossie import dossie
            return JSONResponse(content=await dossie(alvo))
        except Exception as e:  # noqa: BLE001
            return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)
    key = f"dossie:{alvo.lower()}"
    if key in _REL_EM_CURSO:
        return JSONResponse({"ok": True, "status": "gerando",
                             "msg": "⏳ Já estou preparando esse dossiê — te envio aqui em instantes."})
    _REL_EM_CURSO.add(key)
    asyncio.create_task(_gerar_e_enviar_dossie(alvo, key))
    return JSONResponse({"ok": True, "status": "gerando",
                         "msg": f"📥 Preparando o Dossiê 360 de *{alvo}* (PDF). "
                                "Eu te envio aqui mesmo em ~1–2 min — não precisa repetir o comando."})


@router.post("/api/mandato/minuta")
async def api_mandato_minuta(payload: Optional[dict] = None):
    """Onda 10 — Instrumento de mandato: gera minuta .docx (requerimento ALERJ / representação TCE /
    notícia de fato MP / post). Body {"tipo","base"}. Diligência/representação, NUNCA condenação."""
    try:
        from compliance_agent.mandato import gerar

        p = payload or {}
        return JSONResponse(content=gerar(p.get("tipo", ""), p.get("base", "")))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


# ── PPP / concessões municipais (Prefeitura do Rio) ────────────────────────
_PPP_SLUGS = {
    "souza aguiar": "complexo-hospitalar-souza-aguiar",
    "souza-aguiar": "complexo-hospitalar-souza-aguiar",
    "complexo hospitalar souza aguiar": "complexo-hospitalar-souza-aguiar",
}


def _resolver_slug_ppp(alvo: str) -> str:
    import re as _re
    a = (alvo or "").strip().lower()
    if a in _PPP_SLUGS:
        return _PPP_SLUGS[a]
    if "souza aguiar" in a or "souza-aguiar" in a:
        return "complexo-hospitalar-souza-aguiar"
    return _re.sub(r"[^a-z0-9]+", "-", a).strip("-")


async def _gerar_e_enviar_ppp(slug: str, key: str) -> None:
    from compliance_agent.notifications import telegram as _tg
    from compliance_agent.pcrj import ppp_ccpar, dossie_ppp
    from compliance_agent.reporting import render_html as rh
    _pausar_sweeps_para_relatorio()
    try:
        await asyncio.to_thread(ppp_ccpar.coletar_projeto, slug, db_path="data/pcrj.db")
        try:  # ingestão do edital (ZIP ~47MB) é opcional — sem ela o dossiê roda sobre o D.O.
            await asyncio.to_thread(ppp_ccpar.ingerir_edital, slug, db_path="data/pcrj.db")
        except Exception as exc:  # noqa: BLE001
            logger.warning("ingestão do edital CCPAR falhou (segue com D.O.): %s", exc)
        ctx = await asyncio.to_thread(dossie_ppp.montar_dossie, slug, "data/pcrj.db")
        pdf = await rh.gerar_pdf(ctx, f"dossie_ppp_{slug}")
        resumo = f"{ctx.get('faixa', '')} — {ctx.get('subtitulo', '')}"
        await _enviar_docs_telegram({"path_pdf": pdf, "resumo": resumo},
                                    f"Dossiê PPP — {ctx.get('titulo', slug)}")
    except Exception as exc:  # noqa: BLE001
        await _tg.enviar_mensagem(f"⚠️ Erro ao gerar o dossiê da PPP {slug}: {str(exc)[:300]}")
    finally:
        _REL_EM_CURSO.discard(key)
        _retomar_sweeps_se_ocioso()


@router.post("/api/ppp")
async def api_ppp(payload: Optional[dict] = None):
    """Dossiê pericial de PPP/concessão municipal (CCPAR + D.O. Rio + motores + lente PPP) → PDF Kroll.
    Body: {"projeto"|"slug": "souza aguiar"}. ASSÍNCRONO (empurra o PDF no Telegram); {"sync": true}
    devolve o resultado na hora (CLI/testes). Indícios p/ apuração; indício ≠ acusação; INDISPONÍVEL ≠ 0."""
    payload = payload or {}
    alvo = (payload.get("projeto") or payload.get("slug") or payload.get("alvo") or "").strip()
    if not alvo:
        return JSONResponse(content={"ok": False, "erro": "informe {'projeto': 'souza aguiar'} ou {'slug': ...}"},
                            status_code=400)
    slug = _resolver_slug_ppp(alvo)
    if payload.get("sync"):  # modo síncrono (CLI/testes) — gera HTML, não baixa o ZIP
        from compliance_agent.pcrj import dossie_ppp
        return JSONResponse(content=await asyncio.to_thread(dossie_ppp.gerar, slug, db_path="data/pcrj.db"))
    key = f"ppp:{slug}"
    if key in _REL_EM_CURSO:
        return JSONResponse({"ok": True, "status": "gerando",
                             "msg": "⏳ Já estou preparando esse dossiê de PPP — te envio em instantes."})
    _REL_EM_CURSO.add(key)
    asyncio.create_task(_gerar_e_enviar_ppp(slug, key))
    return JSONResponse({"ok": True, "status": "gerando",
                         "msg": f"📥 Preparando o dossiê da PPP *{alvo}* (PDF, ~1–2 min). Te envio aqui mesmo."})


@router.get("/api/ppp/triagem")
async def api_ppp_triagem():
    """Triagem EM LOTE das PPPs/concessões municipais captadas, pela lente PPP (garantia via Fundo
    Nacional de Saúde, aporte, PMI-captura, 5% RCL, verificador) — lista rankeada por gravidade.
    Síncrona e rápida. Indícios p/ apuração; dossiê completo por /ppp <projeto>."""
    from compliance_agent.pcrj import triagem_ppp
    try:
        return JSONResponse(content=await asyncio.to_thread(triagem_ppp.triar_lote, db_path="data/pcrj.db"))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)
