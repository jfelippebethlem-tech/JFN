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
def api_siafe_stats():
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
        # QUANTO DISSO É O UNIVERSO. Publicar "R$ X coletados" sem a razão faz o número parecer o
        # gasto do Estado; medido em 2026-08-09, a fonte canônica tinha 23,6% das OBs que o espelho
        # conhece, e a coleta sobe a cada drenagem. O detalhe por par sai em
        # `reporting.cobertura_siafe.medir()` (parciais + nunca coletados).
        # A RAZÃO É BARATA; o INVENTÁRIO POR PAR não é. Chamar `medir()` aqui levou a rota de
        # instantânea para **59 s** e a aba do painel passou a cair no "SIAFE indisponível" — o
        # próprio conserto quebrou a tela que ele queria melhorar. Duas contagens bastam para o
        # número de manchete; o detalhe por par continua em /api/siafe/truncamento, que é a tela
        # feita para esperar.
        cob = {}
        try:
            con2 = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                n_esp = con2.execute("SELECT COUNT(*) FROM ordens_bancarias").fetchone()[0]
            finally:
                con2.close()
            if n_esp:
                cob = {"pct_do_espelho": round(100.0 * tot[0] / n_esp, 1),
                       "obs_espelho_total": n_esp,
                       "nota": ("A fonte canônica é a que tem status e campos ricos, mas está "
                                "parcialmente coletada — todo total daqui é PISO. O espelho TFE é "
                                "mais completo em contagem e não publica status. Pares incompletos "
                                "em /api/siafe/truncamento.")}
        except sqlite3.Error as _e:
            logger.warning("cobertura do SIAFE indisponível nesta resposta: %s", _e)
        return JSONResponse({"ok": True, "total": tot[0], "valor_total": round(tot[1] or 0, 2),
                             "por_ano": por_ano, "com_processo": com_processo,
                             "ultima_atualizacao": ultima, "coletou_hoje": coletou_hoje,
                             "cobertura": cob,
                             "fonte": "SIAFE-Rio 2 / OB Orçamentária (23 colunas: NL, PD, Processo, Credor...)"})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.post("/api/siafe/atualizar")
def api_siafe_atualizar(payload: dict = None):
    """Atualização DIÁRIA incremental do SIAFE 2 (aba OB Orçamentária, OBs novas, sem filtro). Mantém a base
    fresca sem sweep. Body opcional {"exercicio": 2026}. Roda em background; veja /api/siafe/stats depois."""
    ano = (payload or {}).get("exercicio")
    args = ["diario"] + ([str(int(ano))] if ano else [])
    return JSONResponse(_siafe_spawn(args, "atualizar"))


@router.post("/api/siafe/sweep")
def api_siafe_sweep(payload: dict = None):
    """SWEEP completo do SIAFE por UG (BACKFILL; fura o teto de 1000). Body {"sistema":"2"} (2=2024-26, 1=2016-23)
    ou {"ug":"133100","exercicio":2026} p/ uma UG. Longo — roda em background."""
    p = payload or {}
    if p.get("ug"):
        args = ["ug", str(p["ug"])] + ([str(int(p["exercicio"]))] if p.get("exercicio") else [])
        return JSONResponse(_siafe_spawn(args, "ug"))
    return JSONResponse(_siafe_spawn(["sweep", str(p.get("sistema", "2"))], "sweep"))


@router.get("/api/siafe/status")
def api_siafe_status():
    """Estado da coleta SIAFE (lockfile: se há coleta rodando e qual)."""
    from compliance_agent import siafe_runner
    return JSONResponse({"ok": True, "lock": siafe_runner.lock_status()})


@router.get("/api/lista")
def api_lista():
    """Menu COMPLETO das funções do JFN (para o /lista do Yoda) — gerado da skilltree (capabilities.yaml,
    fonte única), agrupado por domínio. Fica sempre em sincronia com /capacidades; nada de menu fixo defasado."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        texto = SKILLTREE.render_menu()
    except Exception as e:  # noqa: BLE001
        texto = f"🧭 *ECOSSISTEMA JFN* — menu indisponível ({str(e)[:60]}). Use /skills."
    return JSONResponse({"ok": True, "texto": texto})


@router.get("/api/route")
def api_route(q: str = ""):
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


@router.get("/api/pericia/cobertura")
def api_pericia_cobertura():
    """Quanto do acervo já recebeu JUÍZO documento a documento — e por qual cadeia de LLM.

    Pedido do dono (2026-08-03): as perícias rodando 24/7 e visíveis no painel. O primeiro
    requisito de 'rodando' é poder ver quanto já rodou: o número (39 de 2.082 quando isto foi
    escrito) só existia para quem abrisse o SQLite.
    """
    try:
        from compliance_agent.reporting import cobertura_pericia
        return JSONResponse(content=cobertura_pericia.medir())
    except (ImportError, OSError, ValueError, KeyError, TypeError) as e:
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/motor/fotografia")
def api_motor_fotografia():
    """O estado do MOTOR: faixas, achados por código e por origem, motivos no topo da fila.

    Estes números só existiam via SQL na mão, e cada correção de detector exigia medi-los de novo
    — foi assim que duas medições saíram erradas em 2026-08-04 (uma engolindo exceção, outra
    comparando chave de 19 caracteres com chaves de 20). É a mesma função que a pipeline
    `tools/pos_correcao` usa para o antes/depois, então o painel e o diff nunca divergem.
    """
    try:
        from tools.pos_correcao import fotografia
        return JSONResponse(content=fotografia())
    except (ImportError, OSError, ValueError, KeyError, TypeError) as e:
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/tac/ranking")
def api_tac_ranking():
    """Quem paga FORA de contrato regular, e quanto fora da curva está.

    `detector_tac.tac_por_ug` sempre respondeu por UMA unidade, dentro do `/orgao` — e um
    percentual sozinho não sustenta afirmação nenhuma. Medido em 2026-08-04 pela primeira vez de
    forma comparativa: entre as 56 unidades que movimentaram mais de R$ 300 mi, a **mediana é
    0,3%** e a FUNDAÇÃO SAÚDE está em **27,0% (R$ 2,81 bi de R$ 10,41 bi)** — noventa vezes a
    mediana. E não é "a saúde sendo assim": o FUNDO ESTADUAL DA SAÚDE, três vezes maior, paga
    2,8%.

    Lê o JSON gerado por `tools/tac_ranking_ugs.py`: a definição de TAC é a regex canônica do
    `detector_tac`, aplicada em UMA passada sobre 1,16 milhão de OBs — cálculo que nunca pode
    acontecer dentro do request.
    """
    import json as _json
    from pathlib import Path as _Path
    alvo = _Path(__file__).resolve().parent.parent / "data" / "tac_ranking_ugs.json"
    try:
        return JSONResponse(content=_json.loads(alvo.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return JSONResponse(content={
            "ok": True, "indisponivel": True,
            "motivo": ("ranking ainda não gerado — rodar `python tools/tac_ranking_ugs.py` "
                       "(uma passada sobre as OBs; fora do horário de pico)")})


@router.get("/api/siafe/truncamento")
def api_siafe_truncamento():
    """A fonte CANÔNICA de pagamento está truncada — e nada avisava.

    A tela de OB Orçamentária do SIAFE-Rio 2 devolve no máximo 1.000 registros por consulta, e uma
    coleta feita só com `--por-ug` numa UG grande para exatamente nesse número, em silêncio.
    Medido em 2026-08-04: **23 pares (UG, ano) de 642** param em 1.000, enquanto outros chegam a
    6.836; nesses 23 o SIAFE conhece R$ 8,46 bi contra R$ 19,26 bi no espelho TFE. Toda soma por
    UG e toda medida de cobertura saem desse dado — o limite da nossa própria coleta tem de ser
    visível como qualquer outro INDISPONÍVEL.
    """
    try:
        from compliance_agent.reporting import cobertura_siafe
        return JSONResponse(content=cobertura_siafe.medir())
    except (ImportError, OSError, ValueError, KeyError, TypeError) as e:
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/captura/cobertura")
def api_captura_cobertura():
    """Quanto do que foi PAGO o motor consegue ler — o número que limita todos os outros.

    O painel mostrava achados, fila do fiscal e cobertura da perícia sem dizer sobre que fração
    do dinheiro a casa consegue afirmar alguma coisa. Medido em 2026-08-04: **1.941 processos
    íntegros de 40.482 com OB paga (4,8%)**, num universo de R$ 18,06 bi. Ponto cego medido é
    melhor que ponto cego calado.
    """
    try:
        from compliance_agent.reporting import cobertura_captura
        return JSONResponse(content=cobertura_captura.medir())
    except (ImportError, OSError, ValueError, KeyError, TypeError) as e:
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/ob/retiradas")
def api_ob_retiradas():
    """OBs que o portal da transparência publicou e depois DESPUBLICOU.

    A base é reconstruída por exercício a cada coleta do TFE — corretamente, e até 2026-08-04 em
    SILÊNCIO: 140 OBs somando R$ 30.001.367,60 sumiram sem aviso, e só apareceram dois dias
    depois porque um golden de números quebrou. Ordem bancária é a prova de pagamento; sair do
    portal é fato sobre a prova, e agora é visível no dia em que acontece.
    """
    try:
        from compliance_agent.reporting import ob_retiradas
        return JSONResponse(content=ob_retiradas.medir())
    except (ImportError, OSError, ValueError, KeyError, TypeError) as e:
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/sweeps/status")
def api_sweeps_status():
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
def api_sweeps_pausar():
    """Admin (painel): PAUSA os sweeps. Cria data/.pause_sweeps (tudo) e data/.pause_sei_sweep (corta o SEI
    inclusive no meio de uma sessão — sei_sweep.py checa a flag mid-run). Os scripts do cron pulam enquanto existir."""
    d = RAIZ / "data"
    (d / ".pause_sweeps").touch()
    (d / ".pause_sei_sweep").touch()
    return JSONResponse({"ok": True, "pausado": True})


@router.post("/api/sweeps/retomar")
def api_sweeps_retomar():
    """Admin (painel): RETOMA os sweeps (remove as flags de pausa). O cron horário volta a rodar."""
    d = RAIZ / "data"
    for f in (".pause_sweeps", ".pause_sei_sweep"):
        (d / f).unlink(missing_ok=True)
    return JSONResponse({"ok": True, "pausado": False})


@router.get("/api/ugs")
def api_ugs(filtro: Optional[str] = None, limite: int = 50):
    """Catálogo das UGs (órgãos) — o /UG do Yoda. Código + nome canônico + nº de OBs + total pago, para
    o Mestre Jorge saber quais existem e pedir o /orgao certo. Filtro acento-insensível por nome OU código."""
    try:
        from compliance_agent.reporting.inteligencia_orgao import listar_ugs
        limite = max(1, min(int(limite or 50), 151))
        dados = listar_ugs(filtro=filtro, limite=limite)
        # `ok=False` SEM motivo é falha muda: o chamador recebia `erro=None` e não sabia se a base
        # sumiu ou se o catálogo está vazio. O `texto` do módulo já diz ("Base local
        # indisponível.") — basta não descartá-lo. INDISPONÍVEL tem de vir dito.
        ok = bool(dados.get("ok", True))
        corpo = {"ok": ok, "texto": dados.get("texto", ""), "ugs": dados.get("ugs", []),
                 "n": dados.get("n", 0), "n_total": dados.get("n_total", 0)}
        if not ok:
            corpo["erro"] = dados.get("texto") or "catálogo de UGs indisponível"
            corpo["indisponivel"] = True     # ausência de FONTE, não erro de execução
        return JSONResponse(corpo)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "erro": str(exc)}, status_code=500)


@router.get("/api/memoria")
def api_memoria(limite: int = 15):
    """Onda 11 — Memória consolidada do ecossistema (Massare/Lex/Hermes)."""
    try:
        from compliance_agent.memoria import consolidar
        return JSONResponse(content=consolidar(limite))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/eval/hermeneutica")
def api_eval_hermeneutica():
    """A.3.5 — acurácia MEDIDA do juízo jurídico, visível junto do produto.

    Métrica que só existe em log de job não disciplina ninguém: quem lê o relatório não sabe
    quanto vale o juízo que está lendo, e quem mexe no prompt não vê o efeito. Sem medição a rota
    devolve `estado='sem_medicao'` — nunca zero, que seria afirmar qualidade nula onde não houve
    aferição.
    """
    try:
        from compliance_agent.reporting import painel_acuracia
        return JSONResponse(content=painel_acuracia.montar())
    # Estreito de propósito: `montar()` já é defensivo (arquivo ausente/corrompido vira estado
    # declarado), então aqui só restam falha de import e erro de leitura/forma.
    except (ImportError, OSError, ValueError, KeyError, TypeError) as e:
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


_LIFT_CACHE: dict = {"t": 0.0}


@router.get("/api/eval/lift")
def api_eval_lift():
    """G.8 — poder preditivo MEDIDO de cada detector, contra sanção POSTERIOR ao sinal.

    Publicar o número é o que muda a fila: sem ele, sinal bom e sinal inútil disputam a mesma
    atenção. Lift abaixo de 1 sai como ALERTA, não escondido — aponta para empresas menos
    sancionadas que a base, e priorizar por ele desperdiça o tempo do fiscal.

    Medido no painel (2026-07-31): 18,95 s por chamada, sempre — a varredura do acervo contra
    sanção posterior é a mesma que a rota irmã `/api/intel/lift` já cacheava por 1 h. Aqui não
    havia cache nenhum, e o custo caía inteiro na aba de Acurácia a cada abertura.
    """
    import time as _t
    try:
        from compliance_agent.reporting import painel_lift
        if _t.time() - _LIFT_CACHE.get("t", 0) < 3600 and "d" in _LIFT_CACHE:
            return JSONResponse(content=_LIFT_CACHE["d"])
        d = painel_lift.montar()
        if d.get("estado") == "medido":  # estado degradado não fica preso por 1 h
            _LIFT_CACHE.update({"t": _t.time(), "d": d})
        return JSONResponse(content=d)
    # Estreito de propósito: `montar()` já é defensivo (arquivo ausente/corrompido vira estado
    # declarado), então aqui só restam falha de import e erro de leitura/forma.
    except (ImportError, OSError, ValueError, KeyError, TypeError) as e:
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
def api_skills(filtro: str = ""):
    """Skilltree (capacidades) agrupada por domínio — texto p/ o /skills do Telegram."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        return JSONResponse(content={"ok": True, "texto": SKILLTREE.render(filtro),
                                     "n": len(SKILLTREE.capacidades), "sha": SKILLTREE.sha})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/skill")
def api_skill(id: str):
    """Detalhe de uma capacidade (rota, args, quando usar, status) — p/ o /skill <id>."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        return JSONResponse(content={"ok": True, "texto": SKILLTREE.detalhe(id)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.post("/api/skills/reload")
def api_skills_reload():
    """Recarrega capabilities.yaml do disco (fail-safe) — p/ o /skills_reload (admin no Yoda)."""
    try:
        from compliance_agent.skilltree import SKILLTREE
        return JSONResponse(content={"ok": True, **SKILLTREE.reload()})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "erro": str(e)}, status_code=500)


@router.get("/api/skills/validate")
def api_skills_validate():
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
    "pericia": ("pericia_fornecedor", "perícia de fornecedor concluída"),
    "ata": ("ata_documento", "ata de julgamento coletada"),
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
        except OSError as exc:
            logger.debug("bus: checkpoint SEI ilegível (%s)", exc)

        if ciclo % 3 == 0:
            vivos = {"sei": _pgrep("tools[.]sei_sweep"), "siafe": _pgrep("siafe[_]sweep_full")}
        try:
            l1, l5, _ = os.getloadavg()
        except OSError:
            l1 = l5 = 0.0
        mem_pct = None
        try:  # % de RAM em uso (MemAvailable é a métrica honesta no Linux)
            info = {}
            with open("/proc/meminfo") as fh:
                for ln in fh:
                    k, v = ln.split(":", 1)
                    info[k] = int(v.split()[0])
            mem_pct = round(100 * (1 - info["MemAvailable"] / info["MemTotal"]))
        except (OSError, ValueError, KeyError, IndexError, ZeroDivisionError) as exc:
            logger.debug("bus: meminfo indisponível (%s)", exc)
        estado = "critico" if l1 >= 5.0 else ("carga" if l1 >= 3.5 else "ok")
        evs.append({"tipo": "pulse", "load1": round(l1, 2), "load5": round(l5, 2),
                    "mem": mem_pct, "estado": estado, "sweeps": vivos})

        agora = _t.strftime("%H:%M:%S")
        for ev in evs:
            ev["t"] = agora
            for q in list(_bus_subs):
                try:
                    q.put_nowait(ev)
                except Exception as exc:  # noqa: BLE001 — fila cheia = cliente lento
                    logger.debug("evento descartado para cliente lento (%s)", exc)
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


# ── Cockpit do SISTEMA (aba g_sweeps evoluída, pedido do dono 2026-07-26) ──────
# Números caros (du do arquivo SEI, COUNT DISTINCT de processos) ficam num cache
# de 15 min: a aba se atualiza a cada 30 s e não pode custar disco a cada tick.
_SIS_CACHE: dict = {"t": 0.0}


def _sis_medidas_caras() -> dict:
    import sqlite3
    import subprocess
    import time as _t
    if _t.time() - _SIS_CACHE.get("t", 0) < 900 and "sei_arquivo_bytes" in _SIS_CACHE:
        return _SIS_CACHE
    m: dict = {"t": _t.time()}
    base = RAIZ / "data" / "sei_arquivo"
    try:
        m["sei_arquivados"] = sum(1 for e in os.scandir(base) if e.is_dir())
    except Exception:  # noqa: BLE001
        m["sei_arquivados"] = None
    try:
        out = subprocess.run(["du", "-sb", str(base)], capture_output=True, text=True, timeout=90).stdout
        m["sei_arquivo_bytes"] = int(out.split()[0]) if out else None
    except Exception:  # noqa: BLE001
        m["sei_arquivo_bytes"] = None
    try:
        con = sqlite3.connect(RAIZ / "data" / "compliance.db")
        m["sei_fila_total"] = con.execute(
            "SELECT COUNT(DISTINCT processo) FROM ob_orcamentaria_siafe "
            "WHERE processo IS NOT NULL AND processo!=''").fetchone()[0]
        con.close()
    except Exception:  # noqa: BLE001
        m["sei_fila_total"] = None
    _SIS_CACHE.clear()
    _SIS_CACHE.update(m)
    return _SIS_CACHE


@router.get("/api/sistema/atividade")
def api_sistema_atividade():
    """Atividade de TODA a máquina numa resposta: sweeps vivos (e quando mexeram),
    fila SEI lida × restante, arquivo compacto (nº e bytes), pipelines (SLO) e
    aprendizados acumulados. INDISPONÍVEL vira null, nunca 0 inventado."""
    import sqlite3
    import subprocess
    import time as _t

    def _alive(pat: str) -> bool:
        try:
            return bool(subprocess.run(["pgrep", "-f", pat], capture_output=True).stdout.strip())
        except Exception:  # noqa: BLE001
            return False

    def _idade_s(rel: str):
        try:
            return int(_t.time() - (RAIZ / rel).stat().st_mtime)
        except Exception:  # noqa: BLE001
            return None

    pausado = (RAIZ / "data/.pause_sei_sweep").exists() or (RAIZ / "data/.pause_sweep_2").exists()
    sweeps = [
        {"nome": "SEI sweep", "vivo": _alive("tools[.]sei_sweep"), "supervisor": _alive("sei_supervisor.sh"),
         "atividade_s": _idade_s("data/sei_cache/sei_sweep_loop.out")},
        {"nome": "SIAFE 2 (OB)", "vivo": _alive("siafe[_]sweep_full"), "supervisor": _alive("siafe_supervisor.sh"),
         "atividade_s": _idade_s("data/siafe_sweep_full_2.log")},
        {"nome": "Coleta SIAFE diária", "vivo": _alive("compliance_agent[.]siafe_runner"), "supervisor": None,
         "atividade_s": _idade_s("data/siafe_cron.log")},
    ]

    pipelines = []
    try:
        slo = json.loads((RAIZ / "data/pipelines_slo_estado.json").read_text())
        pipelines = [{"nome": k, "estado": (v if isinstance(v, str) else json.dumps(v)[:40])}
                     for k, v in sorted(slo.items())]
    except Exception as exc:  # noqa: BLE001
        logger.debug("sistema/atividade: sem pipelines_slo_estado.json: %s", exc)

    apr = {"vault_notas": None, "memoria_db": None, "fichas_sei": None,
           "direcionamentos": None, "arvores_sei": None}
    try:
        apr["vault_notas"] = len(list((Path.home() / "vault" / "aprendizados").glob("*.md")))
    except OSError as exc:  # vault ausente/sem permissão: INDISPONÍVEL (None), não zero
        logger.debug("sistema/atividade: não contei as notas do vault (%s)", exc)
    try:
        con = sqlite3.connect(RAIZ / "data" / "compliance.db")
        for chave, tab in (("memoria_db", "memoria_aprendizado"), ("fichas_sei", "sei_ficha"),
                           ("direcionamentos", "sei_direcionamento"), ("arvores_sei", "sei_arvore")):
            try:
                apr[chave] = con.execute(f"SELECT COUNT(*) FROM {tab}").fetchone()[0]
            except sqlite3.Error as exc:  # tabela ainda não criada: fica None (INDISPONÍVEL)
                logger.debug("sistema/atividade: sem contagem de %s (%s)", tab, exc)
        con.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("sistema/atividade: compliance.db indisponível p/ aprendizados: %s", exc)

    caras = _sis_medidas_caras()
    sei = {"arquivados": caras.get("sei_arquivados"),
           "arquivo_bytes": caras.get("sei_arquivo_bytes"),
           "fila_total": caras.get("sei_fila_total")}
    if sei["arquivados"] is not None and sei["fila_total"]:
        sei["pct_lido"] = round(100.0 * sei["arquivados"] / sei["fila_total"], 1)
    else:
        sei["pct_lido"] = None

    return JSONResponse({"ok": True, "pausado": pausado, "sweeps": sweeps,
                         "pipelines": pipelines, "sei": sei, "aprendizados": apr})
