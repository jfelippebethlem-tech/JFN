#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""siafe_recoleta_2023_processo — recoleta no SIAFE 2 as OB de 2023 para trazer o NÚMERO DO PROCESSO.

POR QUE EXISTE (14/11/2026). As 220.889 OB de 2023 de `ob_orcamentaria_siafe` vieram do SIAFE 1, cuja grade de
OB Orçamentária tem 19 colunas e NÃO tem "Processo". A perícia contábil (`pericia_contabil`) deixava 1.070 contratos
INDETERMINADO com o motivo `ob_do_credor_sem_processo_na_base` — 804 deles só por OB de 2023. O SIAFE 1 foi
desativado em 10/11/2026; o SIAFE 2 oferece o exercício 2023 na tela de login e a grade dele tem a coluna Processo.
O dono autorizou a recoleta em 14/11/2026.

COMO RODA. UG a UG, cada uma pelo coletor de sempre (`siafe_ob_orcamentaria --por-ug --ug-grande --ingerir`), que
pega o `browser_lock(siafe)` — o mesmo do diário, do dreno e do sweep de NE/NL (a sessão do SIAFE é ÚNICA por IP).
`INSERT OR REPLACE` pela chave (numero_ob, ug_emitente, exercicio): a linha do SIAFE 2 substitui a do SIAFE 1, OB de
outra UG nunca é tocada. Resumível: estado em `data/siafe_recoleta_2023.json`; o checkpoint por fatia do coletor
(`uggrande_<ug>_2023.json`) dá a retomada dentro da UG. O checkpoint ANTIGO (escrito na coleta do SIAFE 1, diz
"feito" para tudo) é afastado UMA vez por UG para `.siafe1`.

GUARDA-CORPOS:
  • janela: não começa UG entre 23:10 e 05:40 (sweep de NE 2023 às 23:20, NE/NL 2025 às 03:10, diário às 05:00); a
    UG em curso tem timeout que termina antes das 23:10;
  • carga: `vm_guard.preflight` com teto 6 (o mesmo do dreno);
  • senha recusada/expirada ou MFA não respondido: PARA tudo e avisa — só o dono resolve (uma tentativa, sem martelar);
  • pausa: `data/.pause_siafe_recoleta_2023`.

O efeito é medido, não presumido: por UG, quantas OB 2023 passaram a ter processo (antes → depois).

Uso:
    PYTHONPATH=. .venv/bin/python tools/siafe_recoleta_2023_processo.py --listar
    PYTHONPATH=. nohup nice -n 10 .venv/bin/python tools/siafe_recoleta_2023_processo.py >> data/siafe_recoleta_2023.log 2>&1 &
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DB = _REPO / "data" / "compliance.db"
_ESTADO = _REPO / "data" / "siafe_recoleta_2023.json"
_PAUSA = _REPO / "data" / ".pause_siafe_recoleta_2023"
_CKPT_DIR = _REPO / "data" / "sei_cache"
ANO = 2023
JANELA_FECHA = (23, 10)     # não começa UG a partir daqui…
JANELA_ABRE = (5, 40)       # …até aqui (madrugada é dos outros coletores SIAFE)
TIMEOUT_UG = 3300           # o mesmo teto do dreno; a UG grande continua na próxima passada pelo checkpoint
MAX_LOAD = 6.0
# erro do coletor que só o dono resolve: parar, não repetir
ERROS_DO_DONO = ("senha_incorreta", "senha_expirada", "mfa", "exercicio_bloqueado")


def _agora() -> datetime:
    return datetime.now()


def na_janela_fechada(t: datetime) -> bool:
    """True entre 23:10 e 05:40 (cruza a meia-noite)."""
    hm = (t.hour, t.minute)
    return hm >= JANELA_FECHA or hm < JANELA_ABRE


def proxima_abertura(t: datetime) -> datetime:
    ab = t.replace(hour=JANELA_ABRE[0], minute=JANELA_ABRE[1], second=0, microsecond=0)
    return ab if ab > t else ab + timedelta(days=1)


def segundos_ate_fechar(t: datetime) -> int:
    fe = t.replace(hour=JANELA_FECHA[0], minute=JANELA_FECHA[1], second=0, microsecond=0)
    if fe <= t:
        return 0
    return int((fe - t).total_seconds())


def medir(ug: str, db: Path | str = _DB) -> dict:
    """Linhas da UG em 2023 e quantas trazem processo."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    try:
        # ob-qualquer-status: conta linhas para medir cobertura do campo processo; não soma valor pago
        n, com = con.execute(
            "SELECT COUNT(*), SUM(processo IS NOT NULL AND trim(processo) <> '') FROM ob_orcamentaria_siafe "
            "WHERE exercicio=? AND ug_emitente=?", (ANO, str(ug))).fetchone()
        return {"linhas": int(n or 0), "com_processo": int(com or 0)}
    finally:
        con.close()


def fila(relevancia: dict[str, int], db: Path | str = _DB) -> list[str]:
    """UGs de 2023 na ordem de coleta: primeiro as que pesam nos contratos INDETERMINADO (mais OB candidatas
    primeiro), depois as demais da menor para a maior (mais UGs fechadas por hora de navegador)."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
    try:
        # ob-qualquer-status: tamanho da UG para ordenar a fila de coleta; não soma valor pago
        tam = dict(con.execute("SELECT ug_emitente, COUNT(*) FROM ob_orcamentaria_siafe WHERE exercicio=? "
                               "GROUP BY 1", (ANO,)).fetchall())
    finally:
        con.close()
    relevantes = sorted((u for u in relevancia if u in tam), key=lambda u: (-relevancia[u], u))
    resto = sorted((u for u in tam if u not in relevancia), key=lambda u: (tam[u], u))
    return relevantes + resto


def carregar_estado(arq: Path = _ESTADO) -> dict:
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ugs": {}}


def salvar_estado(est: dict, arq: Path = _ESTADO) -> None:
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(arq)


def afastar_checkpoint_siafe1(ug: str, est_ug: dict, ckpt_dir: Path = _CKPT_DIR) -> bool:
    """Afasta UMA vez o checkpoint da coleta do SIAFE 1 (que marca todas as fatias como feitas). Depois disso o
    checkpoint é desta recoleta e guarda progresso real — afastá-lo de novo recomeçaria a UG do zero."""
    if est_ug.get("ckpt_afastado"):
        return False
    ck = ckpt_dir / f"uggrande_{ug}_{ANO}.json"
    if ck.exists():
        ck.replace(ck.with_name(ck.name + ".siafe1"))
    est_ug["ckpt_afastado"] = True
    return True


def resultado_do_coletor(saida: str) -> dict:
    """Último objeto JSON impresso pelo coletor (ele imprime com indent, várias linhas)."""
    i = saida.rfind("\n{")
    bloco = saida[i + 1:] if i >= 0 else (saida if saida.lstrip().startswith("{") else "")
    try:
        return json.loads(bloco)
    except ValueError:
        return {}


def erro_do_dono(res: dict) -> str | None:
    """Erro que só o dono resolve, procurado no resultado e no `ultimo` do login com retry."""
    cands = [str(d.get("erro") or "") for d in (res, res.get("ultimo") or {})] + [str(e) for e in res.get("erros") or ()]
    for e in cands:
        if e in ERROS_DO_DONO:
            return e
        if e.startswith("mfa"):          # mfa, mfa_sem_codigo, mfa_codigo_rejeitado, mfa_campo_nao_encontrado
            return "mfa"
    return None


def concluida(res: dict) -> bool:
    """A UG terminou: o coletor percorreu as fatias (ok) ou o checkpoint DESTA recoleta já cobre todas."""
    return bool(res.get("ok"))


def _log(m: str) -> None:
    print(f"[{time.strftime('%F %T')}] {m}", flush=True)


def _notificar(texto: str) -> None:
    from compliance_agent.siafe_coord import notificar
    if not notificar(texto):          # melhor-esforço (notificar já engole erro de rede); o log fica com o motivo
        _log("aviso Telegram não saiu")


def _vm_ok() -> tuple[bool, str]:
    try:
        from tools.vm_guard import preflight
        return preflight(max_load=MAX_LOAD)
    except (ImportError, OSError, ValueError) as exc:
        return True, f"guarda indisponível ({type(exc).__name__}) — sigo"


def coletar_ug(ug: str, timeout_s: int) -> tuple[dict, int]:
    saida_log = _REPO / "data" / f"siafe_recoleta_2023_{ug}.log"
    env = {k: v for k, v in os.environ.items() if k != "JFN_SIAFE_LOGIN_URL"}   # SIAFE 2, sempre
    env["PYTHONPATH"] = str(_REPO)
    try:
        r = subprocess.run(["timeout", "-k", "120", str(timeout_s), "nice", "-n", "10", sys.executable, "-m",
                            "compliance_agent.siafe_ob_orcamentaria", "--exercicio", str(ANO), "--por-ug", ug,
                            "--ug-grande", "--ingerir"], cwd=_REPO, env=env, capture_output=True, text=True,
                           timeout=timeout_s + 300)
        stdout, out, rc = r.stdout or "", (r.stdout or "") + (r.stderr or ""), r.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        rc = 124
    with open(saida_log, "a", encoding="utf-8") as f:
        f.write(f"\n===== {time.strftime('%F %T')} rc={rc}\n{out}")
    return resultado_do_coletor(stdout), rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listar", action="store_true", help="só mostra a fila e o estado")
    ap.add_argument("--relevancia", default=str(_REPO / "data" / "siafe_recoleta_2023_relevancia.json"),
                    help="JSON {ug: nº de OB 2023 sem processo candidatas a contrato INDETERMINADO}")
    ap.add_argument("--max-ugs", type=int, default=0, help="para depois de N UGs nesta execução (0 = todas)")
    a = ap.parse_args()
    try:
        relev = {str(k): int(v) for k, v in json.loads(Path(a.relevancia).read_text()).items()}
    except (OSError, ValueError):
        relev = {}
    est = carregar_estado()
    ordem = fila(relev)
    pend = [u for u in ordem if not est["ugs"].get(u, {}).get("concluida")]
    if a.listar:
        print(json.dumps({"fila": len(ordem), "pendentes": len(pend), "proximas": pend[:15],
                          "concluidas": len(ordem) - len(pend)}, ensure_ascii=False, indent=1))
        return 0
    from compliance_agent.host_siafe import exigir_autorizacao
    exigir_autorizacao()
    _log(f"início: {len(pend)} UG(s) pendentes de {len(ordem)}")
    feitas = falhas_seguidas = 0
    for ug in pend:
        while True:
            if _PAUSA.exists():
                _log(f"pausa ({_PAUSA.name}) — paro"); return 0
            t = _agora()
            if na_janela_fechada(t):
                ab = proxima_abertura(t)
                _log(f"janela dos outros coletores SIAFE — durmo até {ab:%F %H:%M}")
                time.sleep(max(60, (ab - t).total_seconds()))
                continue
            ok, motivo = _vm_ok()
            if not ok:
                _log(f"VM saturada ({motivo}) — espero 10 min"); time.sleep(600); continue
            break
        e_ug = est["ugs"].setdefault(ug, {"passadas": 0})
        if afastar_checkpoint_siafe1(ug, e_ug):
            salvar_estado(est)
        antes = medir(ug)
        lim = min(TIMEOUT_UG, segundos_ate_fechar(_agora()))
        if lim < 300:
            continue
        _log(f"UG {ug}: começo (antes {antes['linhas']} linhas, {antes['com_processo']} com processo; "
             f"timeout {lim}s)")
        t0 = time.time()
        res, rc = coletar_ug(ug, lim)
        depois = medir(ug)
        e_ug["passadas"] = e_ug.get("passadas", 0) + 1
        e_ug.update(ultimo_rc=rc, ultimo_em=time.strftime("%F %T"), antes=e_ug.get("antes", antes), depois=depois,
                    ultimo=({k: res.get(k) for k in ("ok", "erro", "etapa", "ingeridas", "fatias", "nada_a_fazer")}
                            if res else {"sem_json": True}))
        dono = erro_do_dono(res)
        if concluida(res):
            e_ug["concluida"] = True
            falhas_seguidas = 0
            feitas += 1
        else:
            falhas_seguidas += 1
        salvar_estado(est)
        _log(f"UG {ug}: rc={rc} em {time.time() - t0:.0f}s · {antes['com_processo']} → {depois['com_processo']} "
             f"com processo ({depois['linhas']} linhas) · {e_ug['ultimo']}")
        if dono:
            _log(f"PARO: '{dono}' — só o dono resolve")
            _notificar(f"🔑 JFN — recoleta SIAFE 2023 (processo das OB) parou: {dono}. " + {
                "mfa": "Responda o código do SIAFE com 'siafe codigo NNNNNN' e me avise para religar.",
                "exercicio_bloqueado": "O SIAFE 2 diz que o exercício 2023 está bloqueado para a conta: pedir ao "
                                       "Administrador do SIAFE (SEFAZ) a permissão de acesso ao SIAFE-Rio 2023.",
            }.get(dono, "Atualize SIAFE_PASS no .env do JFN e me avise para religar."))
            return 3
        if falhas_seguidas >= 3:
            _log("3 UGs seguidas sem concluir — paro para exame (estado preservado, religar retoma)")
            _notificar("⚠️ JFN — recoleta SIAFE 2023 parou após 3 UGs seguidas sem concluir. Ver "
                       "data/siafe_recoleta_2023.log.")
            return 4
        if not concluida(res) and rc != 124:
            time.sleep(240)        # sessão presa no servidor: 240 s entre logins (medido em 25/10/2026)
        if a.max_ugs and feitas >= a.max_ugs:
            break
    _log(f"fim da passada: {feitas} UG(s) concluídas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
