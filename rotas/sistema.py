# -*- coding: utf-8 -*-
"""Rotas sistema do JFN — extraído de server.py (split 2026-07-06; rede: tests/test_server_snapshot.py).
Handlers idênticos aos originais; só o decorador mudou de @app p/ @router."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Raiz do repo (~/JFN). No server.py original `Path(__file__).parent` ERA a raiz; após o split
# p/ rotas/ (2026-07-06) virou rotas/ e todos os caminhos data/ quebraram em silêncio
# (log da coleta SIAFE, cwd do runner, compliance.db do /siafe/stats, progress do /sweeps/status,
# flags do /sweeps/pausar). Fix 2026-07-10: base única na raiz real.
RAIZ = Path(__file__).resolve().parent.parent

def _siafe_spawn(args: list, quem: str):
    """Dispara a coleta SIAFE como subprocesso (não bloqueia a request); respeita o lockfile de sessão única."""
    import subprocess
    import sys as _sys
    from compliance_agent import siafe_runner
    st = siafe_runner.lock_status()
    if st.get("locked"):
        return {"ok": False, "erro": "ocupado", "detail": "Já há uma coleta SIAFE em andamento.", "lock": st}
    log = open(RAIZ / "data" / f"siafe_{quem}.log", "a")
    subprocess.Popen([_sys.executable, "-m", "compliance_agent.siafe_runner", *args],
                     cwd=str(RAIZ), stdout=log, stderr=log, start_new_session=True)
    return {"ok": True, "iniciado": True, "comando": quem, "detail": "Coleta SIAFE iniciada em background."}


@router.get("/api/siafe/stats")
async def api_siafe_stats():
    """Resumo das OBs do SIAFE (tela OB Orçamentária) já coletadas/ingeridas na base (SIAFE preponderante)."""
    try:
        import sqlite3
        from pathlib import Path as _P
        db = _P(os.environ.get("JFN_DATA_DIR", RAIZ / "data")) / "compliance.db"
        con = sqlite3.connect(str(db))
        try:
            tem = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ob_orcamentaria_siafe'").fetchone()
            if not tem:
                return JSONResponse({"ok": True, "total": 0, "detail": "Tabela ainda não criada — rode a coleta SIAFE."})
            tot = con.execute("SELECT COUNT(*), COALESCE(SUM(valor),0) FROM ob_orcamentaria_siafe").fetchone()
            por_ano = [{"exercicio": r[0], "n": r[1], "valor": round(r[2] or 0, 2)}
                       for r in con.execute("SELECT exercicio, COUNT(*), COALESCE(SUM(valor),0) "
                                            "FROM ob_orcamentaria_siafe GROUP BY exercicio ORDER BY exercicio")]
            com_processo = con.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE processo IS NOT NULL AND processo!=''").fetchone()[0]
            # Frescor da coleta — responde "hoje coletou?": MAX do 1º timestamp existente na tabela.
            cols = {r[1] for r in con.execute("PRAGMA table_info(ob_orcamentaria_siafe)")}
            ts_col = next((c for c in ("coletado_em", "created_at", "updated_at", "ingerido_em") if c in cols), None)
            ultima = con.execute(f"SELECT MAX({ts_col}) FROM ob_orcamentaria_siafe").fetchone()[0] if ts_col else None
        finally:
            con.close()
        from datetime import date as _date
        coletou_hoje = bool(ultima and str(ultima)[:10] == _date.today().isoformat())
        return JSONResponse({"ok": True, "total": tot[0], "valor_total": round(tot[1] or 0, 2),
                             "por_ano": por_ano, "com_processo": com_processo,
                             "ultima_atualizacao": ultima, "coletou_hoje": coletou_hoje,
                             "fonte": "SIAFE-Rio 2 / OB Orçamentária (23 colunas: NL, PD, Processo, Credor...)"})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.post("/api/siafe/atualizar")
async def api_siafe_atualizar(payload: dict = None):
    """Atualização DIÁRIA incremental do SIAFE 2 (aba OB Orçamentária, OBs novas, sem filtro). Mantém a base
    fresca sem sweep. Body opcional {"exercicio": 2026}. Roda em background; veja /api/siafe/stats depois."""
    ano = (payload or {}).get("exercicio")
    args = ["diario"] + ([str(int(ano))] if ano else [])
    return JSONResponse(_siafe_spawn(args, "atualizar"))


@router.post("/api/siafe/sweep")
async def api_siafe_sweep(payload: dict = None):
    """SWEEP completo do SIAFE por UG (BACKFILL; fura o teto de 1000). Body {"sistema":"2"} (2=2024-26, 1=2016-23)
    ou {"ug":"133100","exercicio":2026} p/ uma UG. Longo — roda em background."""
    p = payload or {}
    if p.get("ug"):
        args = ["ug", str(p["ug"])] + ([str(int(p["exercicio"]))] if p.get("exercicio") else [])
        return JSONResponse(_siafe_spawn(args, "ug"))
    return JSONResponse(_siafe_spawn(["sweep", str(p.get("sistema", "2"))], "sweep"))


@router.get("/api/siafe/status")
async def api_siafe_status():
    """Estado da coleta SIAFE (lockfile: se há coleta rodando e qual)."""
    from compliance_agent import siafe_runner
    return JSONResponse({"ok": True, "lock": siafe_runner.lock_status()})


@router.get("/api/lista")
async def api_lista():
    """Menu COMPLETO das funções do JFN (para o /lista do Yoda) — gerado da skilltree (capabilities.yaml,
    fonte única), agrupado por domínio. Fica sempre em sincronia com /capacidades; nada de menu fixo defasado."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        texto = SKILLTREE.render_menu()
    except Exception as e:  # noqa: BLE001
        texto = f"🧭 *ECOSSISTEMA JFN* — menu indisponível ({str(e)[:60]}). Use /skills."
    return JSONResponse({"ok": True, "texto": texto})


@router.get("/api/route")
async def api_route(q: str = ""):
    """Triagem DETERMINÍSTICA pedido→capacidade (sem LLM): pontua cada capacidade do capabilities.yaml
    pela sobreposição de palavras com quando_usar/descricao/id e devolve o melhor + candidatos. Complementa
    o roteador por skills (gen_skills) — o Yoda resolve a rota por regra antes de cogitar o modelo, reduzindo
    erro de tool-use/curl inventado. GET /api/route?q=<pedido>."""
    try:
        import re as _re
        from compliance_agent.skilltree import SKILLTREE

        def _toks(s: str) -> set:
            return {t for t in _re.split(r"[^0-9a-zà-ú]+", (s or "").lower()) if len(t) > 2}

        qt = _toks(q)
        if not qt:
            return JSONResponse({"ok": False, "erro": "parametro q vazio"}, status_code=400)
        ranked = []
        for cid, c in SKILLTREE.capacidades.items():
            quando = _toks(c.get("quando_usar")) | _toks(c.get("exemplo"))
            corpo = _toks(c.get("descricao")) | _toks(cid) | _toks(c.get("dominio"))
            score = 2 * len(qt & quando) + len(qt & corpo)
            if score:
                ranked.append((score, c))
        ranked.sort(key=lambda x: -x[0])

        def _slim(c: dict) -> dict:
            return {k: c.get(k) for k in ("id", "agente", "dominio", "tipo", "metodo", "rota", "status", "descricao")}

        top = [_slim(c) for _, c in ranked[:3]]
        return JSONResponse({"ok": True, "q": q, "match": top[0] if top else None,
                             "candidatos": top, "n_avaliadas": len(SKILLTREE.capacidades)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(e)[:120]}, status_code=500)


@router.get("/api/sweeps/status")
async def api_sweeps_status():
    """Status dos SWEEPS (coleta contínua): SEI (lê processos SEI das OBs) + SIAFE 2 (OB Orçamentária).
    Para o Yoda responder 'como está o sweep' sem se perder — texto pronto p/ Telegram."""
    import subprocess
    base = RAIZ

    def _alive(pat: str) -> bool:
        try:
            return bool(subprocess.run(["pgrep", "-f", pat], capture_output=True).stdout.strip())
        except Exception:  # noqa: BLE001
            return False

    # SEI
    sei_feitos = 0
    try:
        sei_feitos = len(json.loads((base / "data/sei_cache/sei_sweep_progress.json").read_text()).get("feitos", {}))
    except Exception as exc:  # noqa: BLE001
        logger.warning("sweeps/status: falha lendo sei_sweep_progress.json (feitos=0 pode ser falso): %s", exc)
    sei_tail = ""
    try:
        _ls = [ln for ln in (base / "data/sei_cache/sei_sweep_loop.out").read_text().splitlines() if ln.strip()]
        sei_tail = _ls[-1][:170] if _ls else ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("sweeps/status: sem tail de sei_sweep_loop.out: %s", exc)
    sei_sup, sei_run = _alive("sei_supervisor.sh"), _alive("tools[.]sei_sweep")
    sia_sup, sia_run = _alive("siafe_supervisor.sh"), _alive("siafe[_]sweep_full")
    pausado = (base / "data/.pause_sei_sweep").exists() or (base / "data/.pause_sweep_2").exists()

    sia_total = 0
    try:
        import sqlite3
        _c = sqlite3.connect(base / "data/compliance.db")
        sia_total = _c.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe").fetchone()[0]
        _c.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("sweeps/status: falha contando ob_orcamentaria_siafe (total=0 pode ser falso): %s", exc)

    # SIAFE 2: detecta varredura COMPLETA (o supervisor encerra ao concluir; não é "parado/quebrado")
    sia_completo = False
    try:
        _sl = [ln for ln in (base / "data/siafe_sweep_full_2.log").read_text().splitlines() if ln.strip()][-3:]
        sia_completo = any("SWEEP COMPLETO" in ln for ln in _sl)
    except Exception as exc:  # noqa: BLE001
        logger.debug("sweeps/status: sem leitura de siafe_sweep_full_2.log: %s", exc)

    def _ic(ok):
        return "🟢" if ok else "🔴"
    estado_sei = "pausado (relatório em curso tem prioridade)" if pausado else ("rodando" if sei_run else ("supervisionado" if sei_sup else "parado"))
    if pausado:
        estado_sia = "pausado"
    elif sia_run:
        estado_sia = "rodando"
    elif sia_completo:
        estado_sia = "✅ varredura completa (todas as UGs); reabre com nova coleta diária"
    elif sia_sup:
        estado_sia = "supervisionado"
    else:
        estado_sia = "ocioso (varredura concluída)"
    _sia_fmt = f"{sia_total:,}".replace(",", ".")
    texto = (
        "🛰️ **Sweeps (coleta contínua)**\n\n"
        f"{_ic(sei_sup or sei_run)} **SEI** — {estado_sei}\n"
        f"   {sei_feitos} processos lidos (checkpoint, resumível).\n"
        f"   _{sei_tail}_\n\n"
        f"{_ic(sia_sup or sia_run or sia_completo)} **SIAFE 2** — {estado_sia}\n"
        f"   base OB Orçamentária: {_sia_fmt} OBs ingeridas."
    )
    return JSONResponse({"ok": True, "texto": texto,
                         "sei": {"feitos": sei_feitos, "supervisor": sei_sup, "rodando": sei_run, "ultima": sei_tail},
                         "siafe": {"supervisor": sia_sup, "rodando": sia_run, "ob_orcamentaria": sia_total},
                         "pausado": pausado})


@router.post("/api/sweeps/pausar")
async def api_sweeps_pausar():
    """Admin (painel): PAUSA os sweeps. Cria data/.pause_sweeps (tudo) e data/.pause_sei_sweep (corta o SEI
    inclusive no meio de uma sessão — sei_sweep.py checa a flag mid-run). Os scripts do cron pulam enquanto existir."""
    d = RAIZ / "data"
    (d / ".pause_sweeps").touch()
    (d / ".pause_sei_sweep").touch()
    return JSONResponse({"ok": True, "pausado": True})


@router.post("/api/sweeps/retomar")
async def api_sweeps_retomar():
    """Admin (painel): RETOMA os sweeps (remove as flags de pausa). O cron horário volta a rodar."""
    d = RAIZ / "data"
    for f in (".pause_sweeps", ".pause_sei_sweep"):
        (d / f).unlink(missing_ok=True)
    return JSONResponse({"ok": True, "pausado": False})


@router.get("/api/ugs")
async def api_ugs(filtro: Optional[str] = None, limite: int = 50):
    """Catálogo das UGs (órgãos) — o /UG do Yoda. Código + nome canônico + nº de OBs + total pago, para
    o Mestre Jorge saber quais existem e pedir o /orgao certo. Filtro acento-insensível por nome OU código."""
    try:
        from compliance_agent.reporting.inteligencia_orgao import listar_ugs
        limite = max(1, min(int(limite or 50), 151))
        dados = listar_ugs(filtro=filtro, limite=limite)
        return JSONResponse({"ok": dados.get("ok", True), "texto": dados.get("texto", ""),
                             "ugs": dados.get("ugs", []), "n": dados.get("n", 0), "n_total": dados.get("n_total", 0)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/memoria")
async def api_memoria(limite: int = 15):
    """Onda 11 — Memória consolidada do ecossistema (Massare/Lex/Hermes)."""
    try:
        from compliance_agent.memoria import consolidar
        return JSONResponse(content=consolidar(limite))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/agenda")
async def api_agenda():
    """Observabilidade central: timers systemd + crons + pausas num relatório só (determinístico, leitura-só).
    Consolidação agêntica 2026-07-06 — o Yoda responde 'como estão os jobs?' sem vasculhar ~20 logs."""
    try:
        from compliance_agent import agenda_jobs
        import asyncio
        texto = await asyncio.to_thread(agenda_jobs.render)  # subprocessos systemctl fora do event loop
        return JSONResponse(content={"ok": True, "texto": texto})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/pipelines")
async def api_pipelines():
    """SLO de frescor por etapa (config/pipelines.yaml) — a agenda vê o GATILHO, aqui vemos o OUTPUT."""
    try:
        import asyncio
        from tools.pipelines_slo import checar
        itens = await asyncio.to_thread(checar)
        ruins = [i["nome"] for i in itens if i["status"] in ("stale", "ausente")]
        return JSONResponse(content={"ok": True, "total": len(itens), "ruins": ruins, "itens": itens})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/skills")
async def api_skills(filtro: str = ""):
    """Skilltree (capacidades) agrupada por domínio — texto p/ o /skills do Telegram."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        return JSONResponse(content={"ok": True, "texto": SKILLTREE.render(filtro),
                                     "n": len(SKILLTREE.capacidades), "sha": SKILLTREE.sha})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/skill")
async def api_skill(id: str):
    """Detalhe de uma capacidade (rota, args, quando usar, status) — p/ o /skill <id>."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        return JSONResponse(content={"ok": True, "texto": SKILLTREE.detalhe(id)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.post("/api/skills/reload")
async def api_skills_reload():
    """Recarrega capabilities.yaml do disco (fail-safe) — p/ o /skills_reload (admin no Yoda)."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        return JSONResponse(content={"ok": True, **SKILLTREE.reload()})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/skills/validate")
async def api_skills_validate():
    """Valida o contrato (schema + rotas PRONTO existem) — p/ o /skills_validate (admin)."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        probs = SKILLTREE.validate()
        return JSONResponse(content={"ok": not probs, "problemas": probs})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


# ── Barramento de eventos ao vivo (SSE) — alimenta o Conduíte do painel ──────────────────
# Um ÚNICO amostrador para N inscritos (leve p/ 2 vCPU): MAX(rowid) é O(1) (~1ms nas 5
# tabelas), pgrep só a cada 3 ciclos, DB aberto read-only e fechado a cada amostra.
# Sem inscritos, o amostrador morre sozinho — custo zero quando ninguém olha o painel.

_bus_subs: set = set()
_bus_task = None

_BUS_TABELAS = {
    "ob_siafe": ("ob_orcamentaria_siafe", "OB SIAFE ingerida"),
    "ob_tfe": ("ordens_bancarias", "OB (espelho TFE) ingerida"),
    "alerta": ("alertas", "alerta de compliance"),
    "radar": ("radar_alertas", "alerta do radar"),
    "clausula": ("clausula_veredito", "cláusula julgada pelo colegiado"),
}


async def _bus_sampler():
    import asyncio
    import sqlite3
    import time as _t
    marcas: dict = {}
    sei_size = None
    ciclo = 0
    vivos = {"sei": False, "siafe": False}

    def _pgrep(pat):
        import subprocess
        try:
            return bool(subprocess.run(["pgrep", "-f", pat], capture_output=True, timeout=3).stdout.strip())
        except Exception:  # noqa: BLE001
            return False

    while _bus_subs:
        evs = []
        try:
            con = sqlite3.connect(f"file:{RAIZ / 'data' / 'compliance.db'}?mode=ro", uri=True, timeout=2)
            try:
                for chave, (tabela, rotulo) in _BUS_TABELAS.items():
                    try:
                        atual = con.execute(f"SELECT MAX(rowid) FROM {tabela}").fetchone()[0] or 0
                    except sqlite3.OperationalError:
                        continue  # tabela ainda não existe nesta base
                    antes = marcas.get(chave)
                    if antes is not None and atual > antes:
                        evs.append({"tipo": chave, "delta": atual - antes, "rotulo": rotulo})
                    marcas[chave] = atual
            finally:
                con.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("bus: amostra de DB falhou (segue vivo): %s", exc)

        # avanço do sweep SEI pelo tamanho do checkpoint (parse do JSON inteiro seria caro)
        try:
            sz = (RAIZ / "data/sei_cache/sei_sweep_progress.json").stat().st_size
            if sei_size is not None and sz != sei_size:
                evs.append({"tipo": "sei_doc", "delta": 1, "rotulo": "sweep SEI avançou (checkpoint)"})
            sei_size = sz
        except OSError:
            pass

        if ciclo % 3 == 0:
            vivos = {"sei": _pgrep("tools[.]sei_sweep"), "siafe": _pgrep("siafe[_]sweep_full")}
        try:
            l1, l5, _ = os.getloadavg()
        except OSError:
            l1 = l5 = 0.0
        estado = "critico" if l1 >= 5.0 else ("carga" if l1 >= 3.5 else "ok")
        evs.append({"tipo": "pulse", "load1": round(l1, 2), "load5": round(l5, 2),
                    "estado": estado, "sweeps": vivos})

        agora = _t.strftime("%H:%M:%S")
        for ev in evs:
            ev["t"] = agora
            for q in list(_bus_subs):
                try:
                    q.put_nowait(ev)
                except Exception:  # noqa: BLE001 — fila cheia = cliente lento; descarta p/ ele
                    pass
        ciclo += 1
        await asyncio.sleep(4)


@router.get("/api/eventos/stream")
async def api_eventos_stream():
    """SSE com a vida real do sistema: deltas de OB/alertas/cláusulas, avanço de sweep e pulso
    de carga. O painel usa cada evento como um pulso de plasma no Conduíte; sem eventos, a
    lâmina apenas respira (silêncio honesto). Fallback do cliente: polling de 30s já existente."""
    import asyncio
    from fastapi.responses import StreamingResponse
    global _bus_task
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _bus_subs.add(q)
    if _bus_task is None or _bus_task.done():
        _bus_task = asyncio.create_task(_bus_sampler())

    async def gen():
        try:
            yield "retry: 5000\n\n"
            while True:
                item = await q.get()
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            _bus_subs.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
