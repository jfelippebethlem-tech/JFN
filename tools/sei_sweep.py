#!/usr/bin/env python3
"""
SWEEP do SEI — lê os processos das OBs **um a um**, com LOGIN ÚNICO (itkava) e sessão reusada.

Confirmado ao vivo (2026-06-09): o reader lê processo a processo (ex.: SEI-330003/002534/2024 → 10 docs).
O `ler()` faz login a cada chamada (~49s); aqui logamos UMA vez e iteramos `ler_processo` (~15s/processo).

Honesto e seguro:
  - Prioriza por VALOR (maior exposição primeiro); pula o que já está em cache (<24h).
  - Fora do escopo do itkava (0 docs) é registrado e seguimos — não martela.
  - Resumível (checkpoint `data/sei_cache/sei_sweep_progress.json`).
  - Respeita a pausa do SIAFE (`data/.pause_sweep_2`) e o browser_lock (nunca 2 browsers).
  - Para sozinho se o login cair (WAF) ou ao atingir --max.

Uso:
    PYTHONPATH=. .venv/bin/python -m tools.sei_sweep --max 50          # lê até 50 processos novos
    PYTHONPATH=. .venv/bin/python -m tools.sei_sweep --max 50 --ug 133100   # só processos de OBs de uma UG
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import sqlite3
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "compliance.db"
CACHE = REPO / "data" / "sei_cache"
PROG = CACHE / "sei_sweep_progress.json"
PAUSE = REPO / "data" / ".pause_sei_sweep"  # pausa PRÓPRIA (o browser_lock já serializa com o SIAFE)
LOG = REPO / "data" / "sei_sweep.log"


def _log(m: str):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {m}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


# ENCERRAMENTO GRACIOSO: o orquestrador (`sweep_sei.sh`) embrulha o sweep em `timeout 1500`. Sem tratar o
# SIGTERM, o `timeout` mata o processo no meio → o browser é morto à força → Node emite EPIPE (parece crash).
# Aqui o SIGTERM só LEVANTA UMA FLAG; o loop a checa entre processos e sai LIMPO (fecha o browser no finally),
# terminando o processo em curso. `timeout` (sem --kill-after) não força SIGKILL, então há tempo de fechar.
_PARAR = False


def _pedir_parada(signum, _frame):  # noqa: ANN001
    global _PARAR
    _PARAR = True


# Assinaturas de MORTE de browser/pipe (Playwright/Chromium): quando aparecem, a sessão inteira está perdida —
# não adianta seguir varrendo (toda leitura seguinte falha). Tratamos como saída limpa (cron repete), nunca crash.
_SINAIS_BROWSER_MORTO = (
    "epipe", "targetclosed", "target closed", "target page, context or browser has been closed",
    "browser has been closed", "connection closed", "browser closed", "page closed",
    "websocket", "pipe closed", "transport", "broken pipe", "playwright was closed",
)


def _browser_morto(exc: BaseException) -> bool:
    """True se a exceção indica que o BROWSER/pipe caiu (não um erro pontual de um processo). Usado para abortar
    a sessão de forma LIMPA em vez de insistir 20× num browser morto. Conservador: na dúvida, retorna False
    (segue para o próximo processo) — só corta a sessão quando a assinatura é claramente de morte de browser."""
    nome = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "targetclosed" in nome or "browser" in nome and "closed" in nome:
        return True
    return any(s in msg for s in _SINAIS_BROWSER_MORTO)


def _carregar_prog() -> dict:
    if PROG.exists():
        try:
            return json.loads(PROG.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("checkpoint %s ilegível — sweep recomeça do zero: %s", PROG.name, exc)
    return {"feitos": {}}  # proc -> {n_docs, em}


def _salvar_prog(p: dict):
    PROG.parent.mkdir(parents=True, exist_ok=True)
    # MERGE-ON-SAVE + write ATÔMICO (fix 2026-07-10): instâncias sobrepostas (cron chains) faziam
    # load-modify-save do arquivo INTEIRO — a última a salvar apagava os feitos das outras (274
    # leituras de 07-09/10 sumiram assim), e um read no meio de um write parcial caía no
    # "ilegível → recomeça do zero". Merge: o nosso (mais novo) prevalece; o do disco completa.
    try:
        no_disco = json.loads(PROG.read_text(encoding="utf-8")).get("feitos", {})
    except Exception:
        no_disco = {}
    fe = p.setdefault("feitos", {})
    for k, v in no_disco.items():
        fe.setdefault(k, v)
    tmp = PROG.with_name(f"{PROG.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(PROG)


def _unidades_legiveis() -> set[str]:
    """Unidades SEI que o itkava JÁ leu (cache cdp_*.json com documentos>0) — escopo aprendido.
    Ex.: de 'cdp_SEI_330003_002534_2024.json' (10 docs) extrai a unidade '330003'."""
    uni: set[str] = set()
    for cf in CACHE.glob("cdp_SEI_*.json"):
        try:
            d = json.loads(cf.read_text(encoding="utf-8"))
            if len(d.get("documentos") or []) > 0:
                m = re.search(r"cdp_SEI_(\d{6})_", cf.name)
                if m:
                    uni.add(m.group(1))
        except Exception as exc:
            logger.debug("cache %s ilegível ao mapear unidades: %s", cf.name, exc)
    return uni


def _unidade(proc: str) -> str:
    m = re.match(r"SEI-\s*(\d{6})", proc or "")  # tolera 'SEI- 330003' (espaço) e 'SEI-080002'
    return m.group(1) if m else ""


def _unidades_sem_acesso(prog: dict, min_amostra: int = 6) -> set:
    """Unidades APRENDIDAS como fora do acesso do itkava: >= min_amostra processos tentados e TODOS com
    0 docs → o login não enxerga aquela unidade (INDISPONÍVEL por acesso). Pular o resto dela evita
    milhares de tentativas fúteis. Honesto: é falta de ACESSO, não 'sem processo'."""
    from collections import defaultdict
    tot: dict = defaultdict(int)
    zero: dict = defaultdict(int)
    for p, f in (prog.get("feitos") or {}).items():
        u = _unidade(p)
        if not u:
            continue
        tot[u] += 1
        if (f.get("n_docs", 0) or 0) == 0:
            zero[u] += 1
    return {u for u in tot if tot[u] >= min_amostra and zero[u] == tot[u]}


def _fila(ug: str | None, limite: int, cnpj: str | None = None) -> list[tuple]:
    """Processos SEI distintos das OBs, priorizando as UNIDADES que o itkava já leu (escopo
    aprendido), depois por valor desc. Filtra por UG e/ou CNPJ do favorecido (alvo de um relatório)."""
    con = sqlite3.connect(str(DB))
    where = "numero_sei LIKE 'SEI-%/%/20%'"
    args: list = []
    if ug:
        where += " AND ug_codigo=?"
        args.append(ug)
    if cnpj:  # processos das OBs de UM fornecedor — pré-carrega o SEI antes do /relatorio dele
        where += " AND replace(replace(replace(favorecido_cpf,'.',''),'/',''),'-','')=?"
        args.append(re.sub(r"\D", "", cnpj))
    # TODOS os processos distintos das OBs (universo ~49k) — sem teto: o sweep deve estudar TODOS os
    # processos de TODAS as OBs (pedido do dono). O `run` filtra os já feitos e pega o próximo lote;
    # o skip-após-3-tentativas trata os fora-de-escopo (acesso do itkava) sem martelar. Ordena: unidade
    # LEGÍVEL primeiro (rende docs), depois por valor — o trabalho útil sai antes; o resto marcha depois.
    rows = con.execute(
        f"SELECT numero_sei, COUNT(*) nob, ROUND(SUM(valor),2) tot FROM ordens_bancarias "
        f"WHERE {where} GROUP BY numero_sei ORDER BY tot DESC",
        tuple(args),
    ).fetchall()
    con.close()
    legiveis = _unidades_legiveis()
    rows.sort(key=lambda r: (0 if _unidade(r[0]) in legiveis else 1, -(r[2] or 0)))
    return rows


def _arvores_encerradas() -> set[str]:
    """Conjunto de processos com situação AUTORITATIVA de encerramento (`sei_arvore.encerrado=1`) — o gate
    FIRME de skip da fase 'update diário'. O flag `encerrado` já embute as salvaguardas (autoritativo
    arquivado/concluído + sem OB recente + sem aditivo + sem filho vigente, em sei_arvore_build); aqui
    re-checamos a recência da última OB como cinto-e-suspensório contra build defasado. Honesto: na dúvida
    (sem DB, sem tabela, sem coluna, erro) retorna VAZIO → não pula nada. Só é chamado em --diario."""
    if not DB.exists():
        return set()
    con = sqlite3.connect(str(DB))
    try:
        if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sei_arvore'").fetchone():
            return set()
        cols = {r[1] for r in con.execute("PRAGMA table_info(sei_arvore)")}
        if "encerrado" not in cols:
            return set()
        rows = con.execute(
            "SELECT numero_sei, COALESCE(ultima_ob,'') FROM sei_arvore WHERE encerrado=1").fetchall()
    except sqlite3.Error:
        return set()
    finally:
        con.close()
    hoje = datetime.now().date()
    out: set[str] = set()
    for numero, ult in rows:
        if not numero:
            continue
        if ult:  # defesa extra: última OB recente (≤18m) → NÃO pula, mesmo marcado encerrado
            try:
                if (hoje - datetime.fromisoformat(ult[:10]).date()).days <= 548:
                    continue
            except ValueError as exc:
                logger.debug("ultima_ob de %s não parseia (%r): %s", numero, ult, exc)
        out.add(numero)
    return out


def _iso(d: str) -> str:
    """Normaliza data p/ ISO YYYY-MM-DD. Aceita ISO (TFE) e dd/mm/yyyy (SIAFE). '' se não reconhecer."""
    d = (d or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", d):
        return d[:10]
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def _ultima_ob_por_processo() -> dict:
    """Data (ISO) da OB MAIS RECENTE de cada processo SEI, cruzando as DUAS fontes (TFE + SIAFE 1/2).
    FRESCOR POR OB (pedido do dono 2026-07-03): uma OB nova = o processo SEI andou (novo pagamento/etapa)
    → tem de ser re-lido, senão a perícia roda com pagamentos/docs INCOMPLETOS. Honesto: sem DB → {}."""
    if not DB.exists():
        return {}
    out: dict[str, str] = {}
    con = sqlite3.connect(str(DB))
    try:
        # TFE (ordens_bancarias): datas já ISO
        for proc, dt in con.execute(
            "SELECT numero_sei, MAX(COALESCE(data_pagamento, data_emissao)) FROM ordens_bancarias "
            "WHERE numero_sei LIKE 'SEI-%/%/20%' GROUP BY numero_sei"):
            if proc and dt:
                out[proc] = max(out.get(proc, ""), dt[:10])
        # SIAFE (ob_orcamentaria_siafe): data dd/mm/yyyy → reduz em Python (não ordena lexicalmente)
        for proc, dt in con.execute(
            "SELECT processo, data_emissao FROM ob_orcamentaria_siafe WHERE processo LIKE 'SEI-%/%/20%'"):
            iso = _iso(dt)
            if proc and iso:
                out[proc] = max(out.get(proc, ""), iso)
    except sqlite3.Error as exc:
        logger.warning("query de última OB por processo falhou — frescor por OB incompleto: %s", exc)
    finally:
        con.close()
    return out


def _ob_desatualizada(ult_ob_iso: str, lido_em: str) -> bool:
    """True se há OB (ISO) mais NOVA que a última leitura (checkpoint 'em') → processo andou → re-ler."""
    return bool(ult_ob_iso and lido_em and ult_ob_iso > lido_em[:10])


def _falha_recente(f: dict | None, horas: float = 4.0) -> bool:
    """COOLOFF de janela (fix constância 2026-07-03): última tentativa FALHOU (0 docs) há menos de `horas`
    → não re-tentar na MESMA janela de WAF. Sem isto, as 3 tentativas caem numa única hora ruim e o
    processo estaciona injustamente (caso 120228: 3 tentativas em 55min de 28/06 → preso 5 dias)."""
    if not f or (f.get("n_docs", 0) or 0) > 0 or not f.get("em"):
        return False
    try:
        return (datetime.now() - datetime.fromisoformat(f["em"])).total_seconds() < horas * 3600
    except (ValueError, TypeError):
        return False


def _ja_lido_ok(proc: str) -> bool:
    """True só se o processo já foi lido COM SUCESSO (documentos>0) e fresco (<7d). Um cache de 0 docs
    é leitura intermitente que FALHOU — não pular, retentar (a abertura do SEI é flaky)."""
    cf = CACHE / f"cdp_{re.sub(r'[^0-9A-Za-z]', '_', proc)}.json"
    if not cf.exists():
        return False
    try:
        c = json.loads(cf.read_text(encoding="utf-8"))
        if len(c.get("documentos") or []) > 0 and c.get("_cached_at"):
            return (datetime.now() - datetime.fromisoformat(c["_cached_at"])).total_seconds() < 7 * 86400
    except Exception as exc:
        logger.debug("cache de %s ilegível em _ja_lido_ok — vai re-ler: %s", proc, exc)
    return False


def _salvar_cadeia_no_cache(proc: str, cadeia: list):
    """Anexa a cadeia (relacionados lidos) ao cache cdp_*.json do processo — o Lex passa a ver a árvore."""
    cf = CACHE / f"cdp_{re.sub(r'[^0-9A-Za-z]', '_', proc)}.json"
    try:
        d = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else {"numero": proc}
        d["cadeia"] = cadeia
        d["_cached_at"] = datetime.now().isoformat()
        cf.write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    except Exception as exc:
        logger.warning("falha ao gravar cadeia no cache de %s — árvore perdida: %s", proc, exc)


async def _ficha_e_storage(proc: str):
    """Extrai a FICHA (cascata gemini-lite→stepfun:free) do conteúdo REAL e guarda SÓ a ficha no cache,
    DESCARTANDO o `texto` (menu lateral do SEI = lixo de ~12k chars). Storage: ~3-7× menor, sem perda útil.
    Retorna (n_chars_antes, n_chars_depois, modelo) ou None."""
    from tools.sei_ficha import conteudo_real, extrair_ficha, STEPFUN
    cf = CACHE / f"cdp_{re.sub(r'[^0-9A-Za-z]', '_', proc)}.json"
    if not cf.exists():
        return None
    try:
        d = json.loads(cf.read_text(encoding="utf-8"))
        antes = len(cf.read_text(encoding="utf-8"))
        cont = conteudo_real(d)
        if len(cont) < 150:
            return None
        # SÓ o nous stepfun:free (100% grátis/sem limite — diretriz do dono: gemini FORA do sweep).
        # extrair_ficha já retenta 502/503 transientes. Se falhar, retorna None → fica p/ a próxima passada
        # (sweep resumível: não marca como feito, retenta depois). Vamos aos poucos.
        f = await extrair_ficha(cont, STEPFUN, provider="nous")
        modelo = STEPFUN  # id real do catálogo (o rótulo antigo "stepfun:free" não existe mais — 404)
        if f.get("_erro"):
            return None
        d["ficha"] = f
        d["texto"] = (d.get("texto") or "")[:200]   # descarta o menu lixo; mantém só uma amostra
        # STORAGE: com a ficha (relevante) em mãos, trima o conteúdo cru — guarda só um EXCERTO de cada
        # doc (traçabilidade), não o texto inteiro. A ficha é a fonte queryável; o excerto aponta a origem.
        for c in (d.get("conteudo_documentos") or []):
            if isinstance(c, dict) and c.get("conteudo"):
                c["conteudo"] = c["conteudo"][:400]
                c["_trimado"] = True
        for rel in (d.get("cadeia") or []):
            if rel.get("texto"):
                rel["texto"] = rel["texto"][:400]
        d["_ficha_modelo"] = modelo
        cf.write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return (antes, len(cf.read_text(encoding="utf-8")), modelo)
    except Exception:  # noqa: BLE001
        return None


async def run(max_n: int, ug: str | None, tentativas_login: int = 20,
              seguir_arvore: bool = True, max_rel_arvore: int = 3, fazer_ficha: bool = True,
              cnpj: str | None = None, diario: bool = False):
    from compliance_agent.envfile import carregar_env
    carregar_env()
    from compliance_agent.recursos import browser_lock_async, aguardar_load_async
    from compliance_agent.collectors.sei_cdp import _proxy_do_env
    from tools.sei_reader import login, ler_processo, seguir_relacionados, _ler_cracked, _montar_resultado_cracked
    from playwright.async_api import async_playwright

    prog = _carregar_prog()
    # Unidades APRENDIDAS como fora do acesso do itkava (amostra suficiente, todas 0 docs) → pular o resto
    # delas (são INDISPONÍVEL por acesso, não vazias) em vez de tentar milhares fútilmente. Adaptativo.
    sem_acesso = _unidades_sem_acesso(prog)
    # FRESCOR POR OB: última OB (TFE+SIAFE) de cada processo → re-ler o que ANDOU desde a leitura.
    ob_recente = _ultima_ob_por_processo()
    _n_stale = sum(1 for p, f in prog["feitos"].items()
                   if f.get("n_docs", 0) and _ob_desatualizada(ob_recente.get(p, ""), f.get("em", "")))
    if _n_stale:
        _log(f"[frescor] {_n_stale} processos já lidos têm OB mais nova que a leitura → serão re-lidos.")
    # FASE UPDATE-DIÁRIO (regra do dono 'não pode errar'): só AQUI pulamos as árvores ENCERRADAS — gate
    # firme da sei_arvore (situação autoritativa arquivado/concluído + sem OB recente + sem aditivo + sem
    # filho vigente). NUNCA no drain inicial (diario=False), p/ não deixar processo por ler na 1ª passada.
    encerradas: set[str] = set()
    if diario:
        try:
            encerradas = _arvores_encerradas()  # gate firme + defesa extra de recência da última OB
        except Exception as e:  # noqa: BLE001 — na dúvida não pula nada (conservador)
            _log(f"[diario] não consegui carregar árvores encerradas ({type(e).__name__}) — não pulo nenhuma.")
            encerradas = set()
        if encerradas:
            _log(f"[diario] {len(encerradas)} árvores ENCERRADAS (gate firme) serão puladas nesta passada diária.")

    def _pular(p: str) -> bool:
        if _ja_lido_ok(p):
            return True
        if _unidade(p) in sem_acesso:  # unidade inteira fora do acesso do itkava (INDISPONÍVEL)
            return True
        if diario and p in encerradas:  # SÓ no update-diário: árvore encerrada (gate firme corroborado)
            return True
        f = prog["feitos"].get(p)
        if _falha_recente(f):  # cooloff: falha há <4h espera a PRÓXIMA janela de WAF (não queima tentativa)
            return True
        # FRESCOR POR OB: OB mais nova que a última leitura → processo andou → NÃO pular (re-ler p/ perícia
        # completa). Vem depois do cooloff (não martela na mesma janela) e do sem_acesso. Auto-limita: ao
        # re-ler, 'em' vira agora() > data da OB → não re-dispara.
        if f and f.get("n_docs", 0) and _ob_desatualizada(ob_recente.get(p, ""), f.get("em", "")):
            return False
        # já lido com docs, ou já tentado >=3x sem sucesso (processo vazio/restrito de verdade)
        return bool(f and (f.get("n_docs", 0) > 0 or f.get("tentativas", 1) >= 3))

    fila = [(p, nob, tot) for (p, nob, tot) in _fila(ug, max_n, cnpj) if not _pular(p)][:max_n]
    if not fila:
        _log("nada novo na fila (tudo já lido/cacheado).")
        return
    _log(f"fila: {len(fila)} processos novos (de OBs{'/UG ' + ug if ug else ''}); login único itkava…")

    await aguardar_load_async(max_por_core=1.5, espera_max=120)
    proxy = _proxy_do_env()
    n_ok = n_zero = n_doc_total = 0
    # CRASH-PROOF (regra do dono: sweep NUNCA crasha): a sessão inteira do browser fica sob try/except. Se o
    # browser/pipe MORRE (EPIPE, TargetClosed, WAF derrubando, lock estourado), vira SAÍDA LIMPA logada — o cron
    # repete no próximo slot. Nada de traceback não-tratado nem Node crashando o processo.
    try:
        async with browser_lock_async(espera_max=600), async_playwright() as pw:
            b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"],
                                         **({"proxy": proxy} if proxy else {}))
            ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            pg = await ctx.new_page()
            try:
                if not await login(pg, tentativas=tentativas_login):
                    _log("ABORTADO: login itkava não venceu o WAF agora (tente mais tarde).")
                    return
                _log("login OK — varrendo…")
                for i, (proc, nob, tot) in enumerate(fila, 1):
                    if _PARAR:
                        _log("SIGTERM/timeout — encerrando LIMPO entre processos (browser fecha no finally, sem EPIPE)."); break
                    if PAUSE.exists():
                        _log("pausa detectada (.pause_sei_sweep) — encerrando limpo."); break
                    t0 = time.time()
                    # a busca→abrir do SEI é INTERMITENTE (cai na caixa) — retenta até abrir (docs/relacionados>0),
                    # como o ler_com_cadeia. Sem retry, leituras válidas viravam "0 docs" (era o bug do sweep).
                    try:
                        r, nd = {}, 0
                        for _try in range(3):
                            # SEMPRE fresco: _ja_lido_ok já pulou os sucessos; aqui são 0-doc/novos → não usar cache 0-doc.
                            r = await ler_processo(pg, proc, usar_cache=False)
                            nd = len(r.get("documentos") or [])
                            # sucesso = DOCUMENTOS>0. relacionados sozinho (sem docs) é a CAIXA/desktop (~40 inbox),
                            # NÃO um processo aberto — não contar como sucesso.
                            if nd > 0:
                                break
                            await asyncio.sleep(2)
                        if nd == 0 and (r.get("indisponivel") or len(r.get("relacionados") or []) > 15):
                            # CAIXA/leitura falha (indisponivel=árvore não abriu; rel>15=inbox legado) →
                            # tenta o método CRACKED, como ler()/ler_com_cadeia. Provado ao vivo: recupera
                            # p.ex. 270042 ITERJ (normal=0/rel40 → cracked=10); fica 0 honesto em restrito.
                            # 2026-07-10: o filtro do menu (sei_cdp) zerou o rel~40 da caixa → o gatilho
                            # passa a ser o flag indisponivel do ler_processo (arvore_vista=False).
                            dump = await _ler_cracked(pg, proc)
                            if dump.get("documentos"):
                                r = await _montar_resultado_cracked(pg, proc, dump, usar_cache=False)
                                nd = len(r.get("documentos") or [])
                    except Exception as e:  # noqa: BLE001
                        _log(f"  [{i}/{len(fila)}] {proc} ERRO {type(e).__name__}: {str(e)[:60]}")
                        # se foi o BROWSER que caiu, as próximas leituras também falham → aborta a sessão limpa
                        # (o cron repete) em vez de logar 20 erros seguidos; demais erros: segue p/ o próximo.
                        if _browser_morto(e):
                            _log("  browser/pipe caiu no meio — encerrando a sessão LIMPO (cron repete). Sem crash.")
                            break
                        continue
                    # controle de RESTRITOS: registra o resultado final ao longo do sweep (0-doc+árvore-não-abriu
                    # +existe no cadastro = provável acesso restrito). Degrada em silêncio, nunca derruba o sweep.
                    try:
                        from tools import sei_restritos as _restr
                        _restr.registrar(proc, r)
                    except Exception:  # noqa: BLE001
                        pass
                    # SEI-2: segue a ÁRVORE de relacionados (o processo de pagamento tem pouco; a licitação/
                    # contrato relacionado tem a substância). Guarda 1<=N<=15 evita a CAIXA (~40 inbox).
                    rel = r.get("relacionados") or []
                    cadeia = []
                    if seguir_arvore and 1 <= len(rel) <= 15:
                        try:
                            cadeia = await seguir_relacionados(pg, r.get("url") or "", rel, max_rel=max_rel_arvore)
                        except Exception:  # noqa: BLE001
                            cadeia = []
                    nd_arv = sum(c.get("n_docs", 0) for c in cadeia)
                    if cadeia:
                        _salvar_cadeia_no_cache(proc, cadeia)  # Lex passa a enxergar a árvore
                    # FICHA + STORAGE: extrai só o relevante e descarta o `texto` (menu lixo de ~12k chars).
                    ficha_info = None
                    if fazer_ficha and (nd or nd_arv):
                        try:
                            ficha_info = await _ficha_e_storage(proc)
                        except Exception:  # noqa: BLE001
                            ficha_info = None
                    _f = prog["feitos"].get(proc, {})
                    prog["feitos"][proc] = {"n_docs": nd, "tentativas": _f.get("tentativas", 0) + 1,
                                            "rel": len(rel), "arvore_docs": nd_arv, "arvore_n": len(cadeia),
                                            "em": datetime.now().isoformat(timespec="seconds")}
                    _salvar_prog(prog)
                    if nd or nd_arv:
                        n_ok += 1; n_doc_total += nd + nd_arv
                    else:
                        n_zero += 1
                    _arv = f" +árvore {len(cadeia)} proc/{nd_arv} docs" if cadeia else ""
                    _fic = ""
                    if ficha_info:
                        a, dp, mdl = ficha_info
                        _fic = f" · ficha[{mdl}] {a}→{dp}ch ({a / max(dp, 1):.0f}× menor)"
                    _log(f"  [{i}/{len(fila)}] {proc} → {nd} docs{_arv}{_fic} (R$ {tot:,.0f}, {nob} OBs) {time.time()-t0:.0f}s")
            finally:
                try:
                    await b.close()  # fechar um browser JÁ MORTO levanta (EPIPE/TargetClosed) — nunca pode crashar
                except Exception as e:  # noqa: BLE001
                    _log(f"  (encerramento do browser ignorado: {type(e).__name__})")
    except Exception as e:  # noqa: BLE001 — CRASH-PROOF: morte de browser/pipe/lock vira saída LIMPA (cron repete)
        _log(f"sessão de browser caiu ({type(e).__name__}: {str(e)[:80]}) — encerrando LIMPO, sem crash. Cron repete.")
        return
    _log(f"FIM: {n_ok} com docs ({n_doc_total} docs), {n_zero} sem (fora de escopo/vazio). "
         f"Progresso em {PROG.name}.")


async def run_pais(max_n: int, tentativas_login: int = 20, fazer_ficha: bool = True,
                   so_alta: bool = False, cnpj: str | None = None):
    """MODO 'SEGUIR PAIS' (recupera a substância dos dockets vazios/execução): detecta no cache os
    PROCESSOS-PAI de CONTRATAÇÃO referenciados (regex SEI + janela de palavra-chave de contratação, com
    denylist de boilerplate do menu lateral) que AINDA NÃO estão no cache, e os LÊ na mesma sessão única
    itkava — gravando docs + ficha no mesmo cache. Resumível (o que já lê fica em cache e não re-enfileira);
    bounded (o orquestrador embrulha em `timeout`); crash-proof (morte de browser = saída limpa).

    Por que funciona: o docket de pagamento aponta "processo de contratação em andamento de nº SEI-..." no
    CORPO de um despacho — é o pai que tem o contrato/parecer. Honesto: detecção é indício; refs do menu são
    descartadas; nada é inventado."""
    from compliance_agent.envfile import carregar_env
    carregar_env()
    from compliance_agent.recursos import browser_lock_async, aguardar_load_async
    from compliance_agent.collectors.sei_cdp import _proxy_do_env
    from tools.sei_reader import login, ler_processo, _ler_cracked, _montar_resultado_cracked
    from tools.sei_pais import carregar_cache, detectar_pais, _norm
    from playwright.async_api import async_playwright

    cache = carregar_cache()
    pais = detectar_pais(cache, incluir_relacionados=not so_alta)
    if cnpj:  # foca nos pais citados por dockets do CNPJ alvo (pré-carrega o /relatorio dele)
        cd = re.sub(r"\D", "", cnpj)
        # origem é o docket que citou; cruza com as OBs do CNPJ
        con = sqlite3.connect(str(DB))
        seus = {r[0] for r in con.execute(
            "SELECT DISTINCT numero_sei FROM ordens_bancarias WHERE "
            "replace(replace(replace(favorecido_cpf,'.',''),'/',''),'-','')=?", (cd,)).fetchall()}
        con.close()
        pais = [p for p in pais if p["origem"] in seus] or pais  # se nada casar, não trava: usa todos
    prog = _carregar_prog()
    feitos = prog.get("pais_feitos") or {}
    fila = [p for p in pais if _norm(p["pai"]) not in {_norm(k) for k in feitos
            if (feitos[k].get("n_docs", 0) or 0) > 0}][:max_n]
    if not fila:
        _log("[pais] nada novo (todos os pais detectados já lidos/cacheados).")
        return
    _log(f"[pais] {len(fila)} processos-pai de contratação a ler (de {len(pais)} detectados); login único itkava…")

    await aguardar_load_async(max_por_core=1.5, espera_max=120)
    proxy = _proxy_do_env()
    n_ok = n_zero = n_doc_total = 0
    try:
        async with browser_lock_async(espera_max=600), async_playwright() as pw:
            b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--ignore-certificate-errors"],
                                         **({"proxy": proxy} if proxy else {}))
            ctx = await b.new_context(ignore_https_errors=True, locale="pt-BR",
                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            pg = await ctx.new_page()
            try:
                if not await login(pg, tentativas=tentativas_login):
                    _log("[pais] ABORTADO: login itkava não venceu o WAF agora."); return
                _log("[pais] login OK — lendo os pais…")
                for i, p in enumerate(fila, 1):
                    if _PARAR:
                        _log("[pais] SIGTERM/timeout — encerrando LIMPO entre processos."); break
                    if PAUSE.exists():
                        _log("[pais] pausa detectada — encerrando limpo."); break
                    proc = p["pai"]
                    t0 = time.time()
                    try:
                        r, nd = {}, 0
                        for _try in range(3):
                            r = await ler_processo(pg, proc, usar_cache=False)
                            nd = len(r.get("documentos") or [])
                            if nd > 0:
                                break
                            await asyncio.sleep(2)
                        if nd == 0:
                            # caminho normal caiu na caixa (rel=40/0 docs) → tenta o método CRACKED, como
                            # ler()/ler_com_cadeia (provado ao vivo: recupera 270042 ITERJ onde o normal
                            # dá 0; fica 0 honesto em restrito). NÃO substitui o normal — só recupera o 0.
                            dump = await _ler_cracked(pg, proc)
                            if dump.get("documentos"):
                                r = await _montar_resultado_cracked(pg, proc, dump, usar_cache=False)
                                nd = len(r.get("documentos") or [])
                    except Exception as e:  # noqa: BLE001
                        _log(f"  [pais {i}/{len(fila)}] {proc} ERRO {type(e).__name__}: {str(e)[:60]}")
                        if _browser_morto(e):
                            _log("  [pais] browser/pipe caiu — encerrando a sessão LIMPO. Sem crash."); break
                        continue
                    # controle de RESTRITOS: registra o resultado final ao longo do sweep (0-doc+árvore-não-abriu
                    # +existe no cadastro = provável acesso restrito). Degrada em silêncio, nunca derruba o sweep.
                    try:
                        from tools import sei_restritos as _restr
                        _restr.registrar(proc, r)
                    except Exception:  # noqa: BLE001
                        pass
                    ficha_info = None
                    if fazer_ficha and nd:
                        try:
                            ficha_info = await _ficha_e_storage(proc)
                        except Exception:  # noqa: BLE001
                            ficha_info = None
                    feitos[proc] = {"n_docs": nd, "via": p["fonte"], "conf": p["confianca"],
                                    "origem": p["origem"], "em": datetime.now().isoformat(timespec="seconds")}
                    prog["pais_feitos"] = feitos
                    _salvar_prog(prog)
                    if nd:
                        n_ok += 1; n_doc_total += nd
                    else:
                        n_zero += 1
                    _fic = ""
                    if ficha_info:
                        a_, dp, mdl = ficha_info
                        _fic = f" · ficha[{mdl}] {a_}→{dp}ch"
                    _log(f"  [pais {i}/{len(fila)}] {proc} → {nd} docs{_fic} "
                         f"({p['confianca']}/{p['fonte']}, ←{p['origem']}) {time.time()-t0:.0f}s")
            finally:
                try:
                    await b.close()
                except Exception as e:  # noqa: BLE001
                    _log(f"  [pais] (encerramento do browser ignorado: {type(e).__name__})")
    except Exception as e:  # noqa: BLE001 — CRASH-PROOF
        _log(f"[pais] sessão de browser caiu ({type(e).__name__}: {str(e)[:80]}) — encerrando LIMPO. Cron repete.")
        return
    _log(f"[pais] FIM: {n_ok} pais com docs ({n_doc_total} docs), {n_zero} sem. Progresso em {PROG.name}.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--ug", type=str, default=None)
    ap.add_argument("--sem-arvore", action="store_true", help="NÃO seguir os relacionados (só o processo)")
    ap.add_argument("--max-rel", type=int, default=3, help="máx. de relacionados a seguir por processo")
    ap.add_argument("--sem-ficha", action="store_true", help="NÃO extrair ficha/storage (só ler+cachear cru)")
    ap.add_argument("--cnpj", type=str, default=None, help="só os processos das OBs de um fornecedor (pré-carrega o /relatorio dele)")
    ap.add_argument("--diario", action="store_true",
                    help="FASE UPDATE-DIÁRIO: pula as árvores ENCERRADAS (gate firme da sei_arvore — situação "
                         "autoritativa + sem OB recente/aditivo/filho vigente). NUNCA usar no drain inicial.")
    ap.add_argument("--seguir-pais", action="store_true",
                    help="MODO PAI: detecta no cache os processos-pai de CONTRATAÇÃO referenciados pelos "
                         "dockets (execução/pagamento) e os lê — recupera a substância dos 'vazios'.")
    ap.add_argument("--pais-so-alta", action="store_true",
                    help="(com --seguir-pais) só os pais de ALTA confiança (conteúdo+keyword), ignora leads de relacionados")
    a = ap.parse_args()
    # encerramento gracioso por timeout/SIGTERM: o loop vê a flag e sai limpo (fecha o browser) — sem EPIPE.
    try:
        signal.signal(signal.SIGTERM, _pedir_parada)
    except (ValueError, OSError) as exc:  # noqa: BLE001 — em thread non-main signal não pode ser registrado; ignora
        logger.debug("SIGTERM não registrado (thread non-main): %s", exc)
    # BACKSTOP DE PROCESSO (regra do dono: o sweep NUNCA crasha): nada escapa como traceback não-tratado.
    # KeyboardInterrupt/SystemExit (BaseException) propagam normal; qualquer Exception vira log + saída limpa.
    try:
        if a.seguir_pais:
            asyncio.run(run_pais(a.max, fazer_ficha=not a.sem_ficha, so_alta=a.pais_so_alta, cnpj=a.cnpj))
        else:
            asyncio.run(run(a.max, a.ug, seguir_arvore=not a.sem_arvore, max_rel_arvore=a.max_rel,
                            fazer_ficha=not a.sem_ficha, cnpj=a.cnpj, diario=a.diario))
    except Exception as e:  # noqa: BLE001
        _log(f"ABORTADO por erro não previsto ({type(e).__name__}: {str(e)[:120]}) — saída limpa, sem crash. Cron repete.")


if __name__ == "__main__":
    main()
