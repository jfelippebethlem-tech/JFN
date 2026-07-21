# -*- coding: utf-8 -*-
"""Rotas produtos do JFN — extraído de server.py (split 2026-07-06; rede: tests/test_server_snapshot.py).
Handlers idênticos aos originais; só o decorador mudou de @app p/ @router."""
from __future__ import annotations

import logging
import asyncio
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


router = APIRouter()
RAIZ = Path(__file__).resolve().parent.parent

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


# Projetos com PERÍCIA MESTRE (documento aprofundado, com íntegras + menu navegável).
# Cada valor é (coroutine que gera o PDF, rótulo). Extensível: mapear novo slug.
async def _pdf_mestre_souza_aguiar() -> str:
    from compliance_agent.pcrj import pericia_mestre
    return await pericia_mestre.gerar_pdf("complexo-hospitalar-souza-aguiar", db_path="data/pcrj.db")


_PERICIAS_MESTRE = {"complexo-hospitalar-souza-aguiar": (_pdf_mestre_souza_aguiar, "Perícia mestre")}


async def _gerar_e_enviar_ppp(slug: str, key: str) -> None:
    from compliance_agent.notifications import telegram as _tg
    from compliance_agent.pcrj import ppp_ccpar
    from compliance_agent.reporting import render_html as rh
    _pausar_sweeps_para_relatorio()
    try:
        await asyncio.to_thread(ppp_ccpar.coletar_projeto, slug, db_path="data/pcrj.db")
        try:  # ingestão do edital (ZIP ~47MB) alimenta o corpus da perícia/lente
            await asyncio.to_thread(ppp_ccpar.ingerir_edital, slug, db_path="data/pcrj.db")
        except Exception as exc:  # noqa: BLE001
            logger.warning("ingestão do edital CCPAR falhou (segue com D.O.): %s", exc)
        if slug in _PERICIAS_MESTRE:  # perícia mestre (íntegras + menu navegável)
            gen, rotulo = _PERICIAS_MESTRE[slug]
            pdf = await gen()
            titulo, resumo = "Complexo Hospitalar Souza Aguiar", \
                "Documento completo — íntegras + sumário navegável. Indício ≠ acusação."
        else:  # dossiê genérico automático
            from compliance_agent.pcrj import dossie_ppp
            ctx = await asyncio.to_thread(dossie_ppp.montar_dossie, slug, "data/pcrj.db")
            pdf = await rh.gerar_pdf(ctx, f"dossie_ppp_{slug}")
            rotulo, titulo = "Dossiê PPP", ctx.get("titulo", slug)
            resumo = f"{ctx.get('faixa', '')} — {ctx.get('subtitulo', '')}"
        await _enviar_docs_telegram({"path_pdf": pdf, "resumo": resumo}, f"{rotulo} — {titulo}")
    except Exception as exc:  # noqa: BLE001
        await _tg.enviar_mensagem(f"⚠️ Erro ao gerar a perícia/dossiê da PPP {slug}: {str(exc)[:300]}")
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
    if payload.get("sync"):  # modo síncrono (CLI/testes) — resumo (não baixa ZIP nem gera PDF)
        if slug in _PERICIAS_MESTRE:
            return JSONResponse(content={"ok": True, "tipo": "Perícia mestre", "slug": slug,
                                         "obs": "perícia aprofundada com íntegras + menu navegável"})
        from compliance_agent.pcrj import dossie_ppp
        return JSONResponse(content=await asyncio.to_thread(dossie_ppp.gerar, slug, db_path="data/pcrj.db"))
    key = f"ppp:{slug}"
    produto = "a perícia (mestre)" if slug in _PERICIAS_MESTRE else "o dossiê"
    if key in _REL_EM_CURSO:
        return JSONResponse({"ok": True, "status": "gerando",
                             "msg": f"⏳ Já estou preparando {produto} dessa PPP — te envio em instantes."})
    _REL_EM_CURSO.add(key)
    asyncio.create_task(_gerar_e_enviar_ppp(slug, key))
    return JSONResponse({"ok": True, "status": "gerando",
                         "msg": f"📥 Preparando {produto} da PPP *{alvo}* (PDF, ~1–2 min). Te envio aqui mesmo."})


# ── Índice de Direcionamento de Certame (Task 4.5) ─────────────────────────
_INDICE_MAX_IDADE_HORAS = 24  # registro persistido mais velho que isso é recalculado na hora


def _indice_certame_payload(certame: str, db_path=None) -> dict:
    """Lógica síncrona (testável) do GET /api/certame/indice: devolve o registro de
    `certame_indice` quando persistido recente (<24h); senão calcula na hora, em LEITURA
    (não persiste — quem persiste é o runner/CLI `indice_certame`). Narrativa pericial
    (`narrativa_json`) acompanha quando existir."""
    import json as _json
    import sqlite3 as _sq
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from compliance_agent.editais.indice_certame import _conectar_ro, _matriz_sv, calcular

    certame = (certame or "").strip()
    if not certame:
        return {"ok": False, "erro": "informe ?certame=<numero de controle PNCP>"}
    row, narrativa = None, None
    try:
        con = _conectar_ro(db_path)
        try:
            row = con.execute("SELECT * FROM certame_indice WHERE certame=?",
                              (certame,)).fetchone()
        finally:
            con.close()
    except _sq.OperationalError:  # tabela/DB ainda não existem → calcula na hora
        row = None
    if row is not None:
        raw = row["narrativa_json"] if "narrativa_json" in row.keys() else None
        if raw:
            try:
                narrativa = _json.loads(raw)
            except (TypeError, ValueError):
                narrativa = None
        recente = False
        if row["gerado_em"] and row["score"] is not None:
            try:
                agora = _dt.now(_tz.utc).replace(tzinfo=None)
                recente = agora - _dt.fromisoformat(row["gerado_em"]) <= \
                    _td(hours=_INDICE_MAX_IDADE_HORAS)
            except (TypeError, ValueError):
                recente = False
        if recente:
            drivers = _json.loads(row["drivers_json"]) if row["drivers_json"] else []
            return {"ok": True, "certame": certame, "fonte": "certame_indice",
                    "gerado_em": row["gerado_em"],
                    "indice": {"score": row["score"], "prioridade": row["prioridade"],
                               "faixa": row["faixa"], "confianca": row["confianca"],
                               "familias": (_json.loads(row["familias_json"])
                                            if row["familias_json"] else {}),
                               "drivers": drivers,
                               "matriz_sv": _matriz_sv(row["faixa"], row["confianca"] or 0.0,
                                                       len(drivers))},
                    "narrativa": narrativa}
    r = calcular(certame, db_path)
    return {"ok": True, "certame": certame, "fonte": "calculado",
            "indice": {k: r[k] for k in ("score", "prioridade", "faixa", "confianca",
                                         "familias", "drivers", "matriz_sv")},
            "narrativa": narrativa, "nota": r["_nota"]}


@router.get("/api/certame/indice")
async def api_certame_indice(certame: Optional[str] = None):
    """Índice de Direcionamento de Certame (0-100, 6 famílias — Task 4.5).
    GET ?certame=<numero de controle PNCP>. Lê `certame_indice` se persistido recente (<24h);
    senão calcula na hora (leitura; não persiste). Devolve {ok, indice:{score, prioridade,
    faixa, confianca, familias, drivers, matriz_sv}, narrativa (se persistida)}.
    Indício ≠ acusação; família INDISPONÍVEL ≠ 0 (só reduz a confiança)."""
    if not (certame or "").strip():
        return JSONResponse({"ok": False, "erro": "informe ?certame=<numero de controle PNCP>"},
                            status_code=400)
    try:
        return JSONResponse(await asyncio.to_thread(_indice_certame_payload, certame))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(e)}, status_code=500)


async def _gerar_e_enviar_dossie_mestre(alvo: str | None, key: str) -> None:
    """Dossiê Mestre de licitações (PDF Kroll): portfólio de órgãos (sem alvo) ou um órgão (CNPJ)."""
    from compliance_agent.notifications import telegram as _tg
    from compliance_agent.reporting import dossie_mestre
    _pausar_sweeps_para_relatorio()
    try:
        cnpj = "".join(c for c in (alvo or "") if c.isdigit())
        if len(cnpj) == 14:
            res = await dossie_mestre.gerar_pdf_orgao(cnpj)
        else:
            res = await dossie_mestre.gerar_pdf_portfolio()
        await _enviar_docs_telegram({"path_pdf": res["path_pdf"]}, f"Dossiê Mestre de Licitações — {res['titulo']}")
    except Exception as exc:  # noqa: BLE001
        await _tg.enviar_mensagem(f"⚠️ Erro ao gerar o dossiê mestre: {str(exc)[:300]}")
    finally:
        _REL_EM_CURSO.discard(key)
        _retomar_sweeps_se_ocioso()


async def _gerar_e_enviar_dossie_completo(cnpj: str, key: str) -> None:
    """Dossiê COMPLETO de fornecedor (360 + fachada + cláusulas na íntegra + suspeitas + SEI) e,
    na sequência, o relatório de inteligência + parecer Lex — o pacote inteiro no Telegram."""
    from compliance_agent.dossie import gerar_pdf_completo
    from compliance_agent.notifications import telegram as _tg
    from compliance_agent.reporting.inteligencia import montar
    _pausar_sweeps_para_relatorio()
    try:
        res = await gerar_pdf_completo(cnpj)
        if not res.get("ok"):
            await _tg.enviar_mensagem(f"⚠️ Dossiê completo indisponível: {(res.get('erro') or '')[:200]}")
        else:
            await _enviar_docs_telegram({"path_pdf": res["path_pdf"]},
                                        f"Dossiê Completo — {res.get('titulo') or cnpj}")
        try:  # inteligência de fornecedor + Lex (contrato/licitação/processo/pagamentos) + planilha
            intel = await montar(cnpj=cnpj)
            if intel.get("ok"):
                await _enviar_docs_telegram(intel, f"Análise jurídica + planilha — {intel.get('empresa') or cnpj}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("dossiê completo: inteligência+Lex falhou p/ %s: %s", cnpj, exc)
    except Exception as exc:  # noqa: BLE001
        await _tg.enviar_mensagem(f"⚠️ Erro no dossiê completo de {cnpj}: {str(exc)[:300]}")
    finally:
        _REL_EM_CURSO.discard(key)
        _retomar_sweeps_se_ocioso()


@router.post("/api/dossie/completo")
async def api_dossie_completo(payload: dict | None = None):
    """Dossiê COMPLETO de fornecedor (assíncrono, PDF no Telegram): dossiê 360 + veredito de fachada
    + cláusulas restritivas na íntegra + suspeitas + árvore/íntegra SEI + análise jurídica + planilha."""
    payload = payload or {}
    alvo = (payload.get("cnpj") or payload.get("alvo") or "").strip()
    cnpj = "".join(c for c in alvo if c.isdigit())
    if len(cnpj) != 14:
        return JSONResponse({"ok": False, "erro": "informe um CNPJ (14 dígitos)"}, status_code=400)
    if payload.get("sync"):
        from compliance_agent.dossie import gerar_pdf_completo
        return JSONResponse(await gerar_pdf_completo(cnpj))
    key = f"dossie_completo:{cnpj}"
    if key in _REL_EM_CURSO:
        return JSONResponse({"ok": True, "status": "em_curso"})
    _REL_EM_CURSO.add(key)
    asyncio.create_task(_gerar_e_enviar_dossie_completo(cnpj, key))
    return JSONResponse({"ok": True, "status": "gerando",
                         "msg": "Gerando o dossiê completo — empurro o PDF no Telegram quando pronto."})


@router.post("/api/dossie/mestre")
async def api_dossie_mestre(payload: dict | None = None):
    """Dossiê Mestre de licitações (assíncrono, empurra PDF no Telegram). Sem `alvo` → PORTFÓLIO de
    órgãos (ranking + peer-benchmark); com `alvo`=CNPJ do órgão → dossiê de conjunto do órgão."""
    payload = payload or {}
    alvo = (payload.get("alvo") or payload.get("cnpj") or "").strip() or None
    if payload.get("sync"):  # caminho testável/síncrono
        from compliance_agent.reporting import dossie_mestre
        cnpj = "".join(c for c in (alvo or "") if c.isdigit())
        res = (await dossie_mestre.gerar_pdf_orgao(cnpj) if len(cnpj) == 14
               else await dossie_mestre.gerar_pdf_portfolio())
        return JSONResponse({"ok": True, "path_pdf": res["path_pdf"], "titulo": res["titulo"]})
    key = f"dossie_mestre:{alvo or 'portfolio'}"
    if key in _REL_EM_CURSO:
        return JSONResponse({"ok": True, "status": "em_curso", "msg": "dossiê mestre já sendo gerado"})
    _REL_EM_CURSO.add(key)
    asyncio.create_task(_gerar_e_enviar_dossie_mestre(alvo, key))
    return JSONResponse({"ok": True, "status": "gerando",
                         "msg": f"Gerando o dossiê mestre {'do órgão' if alvo else 'do portfólio'} — "
                                "empurro o PDF no Telegram quando ficar pronto."})


@router.get("/api/conjunto/orgao")
async def api_conjunto_orgao(cnpj: Optional[str] = None):
    """Avaliação de CONJUNTO dos certames de um órgão (dossiê mestre §5): distribuição do índice
    (mediana/p90), reincidência de cláusula restritiva (≥3 certames → auditoria temática), eliminações
    por motivo trivial sem saneamento, HHI de vitórias e casos-âncora. ?cnpj=<CNPJ do órgão no PNCP>."""
    if not (cnpj or "").strip():
        return JSONResponse({"ok": False, "erro": "informe ?cnpj=<CNPJ do órgão (14 dígitos)>"},
                            status_code=400)
    try:
        from compliance_agent.editais.avaliacao_conjunto import avaliar_orgao, ctx_secao
        av = await asyncio.to_thread(avaliar_orgao, "".join(c for c in cnpj if c.isdigit()))
        return JSONResponse({"ok": True, "avaliacao": av, "secao_html": ctx_secao(av)["html"]})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/conjunto/unidades")
async def api_conjunto_unidades(min_certames: int = 3):
    """Ranking por UNIDADE/secretaria do RJ (granularidade que o CNPJ guarda-chuva esconde):
    Hospital Pedro Ernesto, Fundo Estadual de Saúde, etc., pela mediana do Índice de Certame.
    Só unidades com ≥min_certames indexados E com unidade conhecida no PNCP. Indício ≠ acusação."""
    try:
        from compliance_agent.editais.avaliacao_conjunto import avaliar_unidades
        r = await asyncio.to_thread(avaliar_unidades, ("42498600", "42498733"), None,
                                    max(1, min(int(min_certames), 20)))
        return JSONResponse({"ok": True, **r})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/conjunto/portfolio")
async def api_conjunto_portfolio(min_certames: int = 3):
    """Ranking de ÓRGÃOS por risco de certame (portfólio, dossiê mestre §5): órgãos com
    ≥min_certames indexados, mediana do índice, desvio vs pares (peer-benchmark), gatilhos de
    auditoria temática. Determinístico e auditável; indício ≠ acusação."""
    try:
        from compliance_agent.editais.avaliacao_conjunto import avaliar_portfolio
        pf = await asyncio.to_thread(avaliar_portfolio, None, max(1, min(int(min_certames), 50)))
        return JSONResponse({"ok": True, **pf})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(e)}, status_code=500)


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


# ═══ SEI — árvore completa de uma empresa (busca + download em lote) ═══
# Reusa tools/sei_integra_fila.py --empresa (mesmo lock/browser_lock/resumibilidade dos sweeps SEI
# já agendados — não reinventa o playbook único). Roda como subprocess destacado (pode levar
# minutos a horas); o painel acompanha por polling e baixa o que já estiver pronto (parcial > nada).
_SEI_EMPRESA_EM_CURSO: dict = {}


def _sei_processos_empresa(cnpj: str) -> list[str]:
    from compliance_agent.correlacao_sei import processos_de_fornecedor
    return sorted({p["numero_sei"] for p in processos_de_fornecedor(cnpj, limite=300) if p.get("numero_sei")})


def _sei_arquivado(numero_sei: str) -> bool:
    import re
    m = re.search(r"(\d{6})/(\d{6})/(\d{4})", numero_sei or "")
    if not m:
        return False
    d = RAIZ / "data" / "sei_arquivo" / f"{m.group(1)}_{m.group(2)}_{m.group(3)}"
    return d.is_dir() and (d / "texto").is_dir() and any((d / "texto").glob("*.txt"))


@router.post("/api/sei/empresa/iniciar")
async def api_sei_empresa_iniciar(payload: dict | None = None):
    """Dispara a busca+download da árvore SEI completa de uma empresa. Background (subprocess
    destacado): pode levar minutos a horas conforme o nº de processos — acompanhe por
    /api/sei/empresa/status. Respeita o single-instance dos sweeps SEI (nunca 2 browsers): se
    outro sweep já estiver com o browser, este pedido fica pendente e roda quando ele soltar."""
    payload = payload or {}
    cnpj = "".join(c for c in (payload.get("cnpj") or "") if c.isdigit())
    if len(cnpj) != 14:
        return JSONResponse({"ok": False, "erro": "informe um CNPJ (14 dígitos)"}, status_code=400)
    busca_viva = bool(payload.get("busca_viva"))
    info = _SEI_EMPRESA_EM_CURSO.get(cnpj)
    if info and info["proc"].poll() is None:
        return JSONResponse({"ok": True, "status": "em_curso", "msg": "já está rodando"})
    import subprocess
    env = dict(os.environ, SEI_SEM_TG="1", PYTHONPATH=str(RAIZ))
    cmd = [str(RAIZ / ".venv" / "bin" / "python"), "tools/sei_integra_fila.py",
           "--empresa", cnpj, "--segundos", "7200"]
    if busca_viva:
        cmd.append("--busca-viva")
    proc = subprocess.Popen(cmd, cwd=str(RAIZ), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _SEI_EMPRESA_EM_CURSO[cnpj] = {"proc": proc, "busca_viva": busca_viva}
    return JSONResponse({"ok": True, "status": "iniciado",
                         "msg": "Buscando e baixando os processos SEI dessa empresa — acompanhe o "
                                "progresso; o que já estiver arquivado já pode ser baixado."})


@router.get("/api/sei/empresa/status")
async def api_sei_empresa_status(cnpj: str = ""):
    """Progresso da árvore SEI de uma empresa: quantos processos existem (via OB paga —
    processos_de_fornecedor) vs quantos já estão no arquivo compacto. Nota: só enxerga processos
    sem OB ainda se /iniciar tiver sido chamado com busca_viva=true (Pesquisa Avançada ao vivo)."""
    cnpj = "".join(c for c in cnpj if c.isdigit())
    if len(cnpj) != 14:
        return JSONResponse({"ok": False, "erro": "informe um CNPJ (14 dígitos)"}, status_code=400)
    procs = _sei_processos_empresa(cnpj)
    arquivados = [p for p in procs if _sei_arquivado(p)]
    info = _SEI_EMPRESA_EM_CURSO.get(cnpj)
    rodando = bool(info and info["proc"].poll() is None)
    return JSONResponse({"ok": True, "cnpj": cnpj, "n_processos": len(procs),
                         "n_arquivados": len(arquivados), "processos": procs, "rodando": rodando,
                         "pronto": len(arquivados) > 0,
                         "concluido": (not rodando) and len(procs) > 0 and len(arquivados) == len(procs)})


@router.get("/api/sei/empresa/zip")
async def api_sei_empresa_zip(cnpj: str = ""):
    """ZIP do arquivo compacto (texto+fotos+manifest) de cada processo SEI JÁ arquivado dessa
    empresa. Baixa o que já tem — não espera os que ainda faltam (parcial > nada; o payload diz
    honestamente quantos de quantos foram incluídos)."""
    import re
    import zipfile
    cnpj = "".join(c for c in cnpj if c.isdigit())
    if len(cnpj) != 14:
        return JSONResponse({"ok": False, "erro": "informe um CNPJ (14 dígitos)"}, status_code=400)
    procs = _sei_processos_empresa(cnpj)
    arquivados = [p for p in procs if _sei_arquivado(p)]
    if not arquivados:
        return JSONResponse({"ok": False, "erro": "nenhum processo arquivado ainda — dispare "
                             "/api/sei/empresa/iniciar e acompanhe o status"}, status_code=404)
    dest_dir = RAIZ / "reports"
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / f"sei_arvore_{cnpj}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for numero in arquivados:
            m = re.search(r"(\d{6})/(\d{6})/(\d{4})", numero)
            slug = f"{m.group(1)}_{m.group(2)}_{m.group(3)}"
            pasta = RAIZ / "data" / "sei_arquivo" / slug
            for f in pasta.rglob("*"):
                if f.is_file():
                    zf.write(f, arcname=f"{slug}/{f.relative_to(pasta)}")
    return JSONResponse({"ok": True, "url": f"/reports/{zip_path.name}",
                         "n_incluidos": len(arquivados), "n_total": len(procs)})
