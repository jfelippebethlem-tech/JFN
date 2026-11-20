#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""siafe_documento_sweep — amplia a cobertura de Nota de Empenho e Nota de Liquidação, UG a UG.

POR QUE EXISTE (04/11/2026). Os detectores de ordem cronológica (Dec. RJ 49.134 art. 9º) e de DEA recorrente
só valem nas UGs com NE e NL COMPLETAS (`siafe_documento_cobertura`). Coletar uma UG grande leva 15–30 min de
navegador; a varredura faz isso em janelas, sem disputar a sessão única do SIAFE.

GUARDA-CORPOS:
  • uma coleta por vez, cada uma em subprocesso que pega o lock do siafe_runner E o `browser_lock(siafe)` —
    o mesmo do dreno e do coletor da OB (duas sessões na mesma conta derrubam uma à outra);
  • prazo (`--ate HH:MM`): não começa coleta nova depois dele — o diário do SIAFE é às 05:00;
  • carga: não começa coleta nova com load de 1 min acima de `--load-max`;
  • ordem: UG de maior valor pago (OB Contabilizada) primeiro; pula UG completa há menos de 30 dias.

VÁRIOS EXERCÍCIOS (19/11/2026, medição `siafe_ingest_cobertura`): NE em 4 e NL em 3 das 341 (UG, ano) de 2024–2026;
NL citadas pelas OBs pagas achadas: 15,5% em 2025, 0% em 2024 e 2026. A varredura das 03:10 ficou parada 6 das 8
últimas noites pela guarda `load > 3.0` (a linha de base da VM é 3–5; o modo de crash é memória — ver o dreno) e a
de 2023 tentou LOGIN em 13 UGs seguidas com o MFA pendente. Agora: `--exercicios` monta a fila de todos os anos por
valor pago; UG completa do exercício CORRENTE é relida só ACIMA do último número (incremental, semanal); a passada
para no 1º login que falha e no SIAFE ocupado; `--minutos` dá o orçamento (nunca entra na janela do diário).

Uso:
    PYTHONPATH=. .venv/bin/python tools/siafe_documento_sweep.py --exercicio 2025 --ate 04:40 --max-ugs 3
    PYTHONPATH=. .venv/bin/python tools/siafe_documento_sweep.py --exercicios 2026,2025,2024 --minutos 90
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

from compliance_agent.cruzamentos_intel import _ob_paga
from compliance_agent.siafe_documento import prazo_absoluto

_REPO = Path(__file__).resolve().parents[1]
_DB = _REPO / "data" / "compliance.db"
_FRESCA_DIAS = 30
_INCREMENTAL_DIAS = 7          # UG completa do exercício corrente: relê acima do último número a cada 7 dias
ESTADO = _REPO / "data" / "siafe_documento_sweep_estado.json"


def fila(exercicio: int, db=None, max_ugs: int = 3) -> list[tuple[str, str]]:
    """[(ug, tipo)] na ordem de coleta: maior valor pago primeiro; tipo que já está completo e fresco fica fora."""
    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=30)
    try:
        ugs = [r[0] for r in con.execute(
            # valor pago a FORNECEDOR (credor CNPJ): por valor bruto a previdência e a folha encabeçavam a fila,
            # e nelas a ordem cronológica não se aplica (Dec. 49.134 art. 9º p.ú. a)
            f"SELECT ug_emitente FROM ob_orcamentaria_siafe WHERE exercicio=? AND {_ob_paga(con)} "
            "AND length(credor)=14 GROUP BY 1 ORDER BY SUM(valor) DESC", (int(exercicio),))]
        try:
            cob = {(r[0], r[1]): (r[2], r[3]) for r in con.execute(
                "SELECT ug_emitente, tipo, completo, em FROM siafe_documento_cobertura WHERE exercicio=?",
                (int(exercicio),))}
        except sqlite3.OperationalError:
            cob = {}
    finally:
        con.close()
    limite = (datetime.now() - timedelta(days=_FRESCA_DIAS)).strftime("%F %T")
    saida, n = [], 0
    for ug in ugs:
        faltam = [t for t in ("NE", "NL") if not (cob.get((ug, t), (0, ""))[0] and cob[(ug, t)][1] >= limite)]
        if not faltam:
            continue
        saida += [(ug, t) for t in faltam]
        n += 1
        if n >= max_ugs:
            break
    return saida


def _ultimo_numero(con, tipo: str, ug: str, ex: int) -> str | None:
    from compliance_agent.siafe_documento import TIPOS
    t = TIPOS[tipo]
    base = t["base"](ex) if t.get("base") else f"{ex}{tipo}"
    try:
        r = con.execute(f"SELECT MAX(numero) FROM {t['tabela']} WHERE ug_emitente=? AND exercicio=? AND numero LIKE ?",
                        (ug, ex, f"{base}%")).fetchone()
    except sqlite3.OperationalError:
        return None
    return r[0] if r else None


def fila_varios(exercicios=(2026, 2025, 2024), db=None, max_itens: int = 20, agora: datetime | None = None,
                tipos=("NE", "NL")) -> list[dict]:
    """Fila de vários exercícios: (1) o que falta ou ficou parcial, maior valor pago a fornecedor primeiro; (2) a
    passada INCREMENTAL das UGs completas do exercício corrente (acima do último número); (3) a releitura inteira
    da completa com mais de 30 dias. NE antes de NL na mesma UG (a NL confere a NE)."""
    agora = agora or _agora()
    corrente = agora.year
    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=30)
    try:
        try:
            cob = {(r[0], r[1], int(r[2])): (r[3], r[4]) for r in con.execute(
                "SELECT ug_emitente, tipo, exercicio, completo, em FROM siafe_documento_cobertura")}
        except sqlite3.OperationalError:
            cob = {}
        falta, incr, velha = [], [], []
        for ex in exercicios:
            for ug, val in con.execute(
                    # valor pago a FORNECEDOR (credor CNPJ) — a ordem cronológica não se aplica à folha
                    f"SELECT ug_emitente, SUM(valor) FROM ob_orcamentaria_siafe WHERE exercicio=? AND {_ob_paga(con)} "
                    "AND length(credor)=14 GROUP BY 1", (int(ex),)):
                for tipo in tipos:
                    comp, em = cob.get((ug, tipo, int(ex)), (0, ""))
                    item = {"ug": ug, "tipo": tipo, "exercicio": int(ex), "valor": round(val or 0.0, 2),
                            "a_partir": None}
                    idade = (agora - datetime.fromisoformat(em)).days if em else None
                    if not comp:
                        falta.append({**item, "motivo": "parcial" if em else "nunca_lida"})
                    elif idade is not None and idade > _FRESCA_DIAS:
                        velha.append({**item, "motivo": "releitura_30d"})
                    elif int(ex) == corrente and idade is not None and idade >= _INCREMENTAL_DIAS:
                        ult = _ultimo_numero(con, tipo, ug, int(ex))
                        if ult:
                            incr.append({**item, "a_partir": ult, "motivo": "incremental"})
    finally:
        con.close()
    ordem = {"NE": 0, "NL": 1}
    chave = lambda x: (-x["valor"], x["exercicio"], ordem.get(x["tipo"], 9))   # noqa: E731
    return (sorted(falta, key=chave) + sorted(incr, key=chave) + sorted(velha, key=chave))[:max_itens]


def bj_vencido(db=None, agora: datetime | None = None, horas: int = 20) -> bool:
    """Bloqueio Judicial (lista única do Estado, ~105 linhas, ~2 min): relido 1×/dia no começo da varredura."""
    agora = agora or _agora()
    try:
        con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=30)
        try:
            r = con.execute("SELECT em FROM siafe_documento_cobertura WHERE tipo='BJ' AND completo=1 "
                            "ORDER BY em DESC LIMIT 1").fetchone()
        finally:
            con.close()
    except sqlite3.OperationalError:
        return True
    return not r or (agora - datetime.fromisoformat(r[0])).total_seconds() > horas * 3600


def _agora() -> datetime:
    return datetime.now()


def _passou(prazo: datetime) -> bool:
    """`prazo` é absoluto (ver `siafe_documento.prazo_absoluto`): comparar `HH:MM` como texto fazia a execução
    das 23:20 com `--ate 02:55` parar na hora (laudo 13/11/2026)."""
    return _agora() >= prazo


def _parar(resumo: dict, saida: str) -> str | None:
    """Motivo para encerrar a passada inteira (não só pular a UG): login/MFA que falhou — cada UG seguinte seria
    mais um login e mais um código pedido ao dono (16/11/2026: 13 logins seguidos com o MFA pendente) — ou o SIAFE
    ocupado por outra coleta (sessão única)."""
    etapa = str(resumo.get("etapa") or "")
    if etapa == "login" or "mfa" in str(resumo.get("erro") or "").lower():
        return f"login falhou ({resumo.get('erro') or etapa})"
    if "SIAFE ocupado" in saida:
        return "SIAFE ocupado por outra coleta"
    return None


def _prazo(a, agora: datetime) -> datetime:
    """`--ate` absoluto; com `--minutos`, o menor entre agora+minutos e as 04:00 (janela do diário das 05:00)."""
    prazo = prazo_absoluto(a.ate, agora)
    if a.minutos:
        prazo = min(prazo, agora + timedelta(minutes=a.minutos), prazo_absoluto("04:00", agora))
    return prazo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exercicio", type=int, default=datetime.now().year - 1)
    ap.add_argument("--exercicios", default="", help="vários anos (ex.: 2026,2025,2024): fila única por valor")
    ap.add_argument("--ate", default="04:40", help="não começa coleta nova depois deste horário (HH:MM)")
    ap.add_argument("--minutos", type=int, default=0, help="orçamento da passada (para entre UGs e entre fatias)")
    ap.add_argument("--max-ugs", type=int, default=3)
    # 3.0 barrou 6 das 8 últimas noites (linha de base da VM 3–5); o modo de crash é memória (ver o dreno: 6.0)
    ap.add_argument("--load-max", type=float, default=6.0)
    ap.add_argument("--ugs", default="", help="UGs separadas por vírgula, NESTA ordem (fila dirigida)")
    ap.add_argument("--tipos", default="NE,NL", help="NE, NL ou NE,NL")
    a = ap.parse_args()
    tipos = [t.strip().upper() for t in a.tipos.split(",") if t.strip()]
    if a.exercicios:
        exs = tuple(int(x) for x in a.exercicios.split(",") if x.strip())
        trabalho = fila_varios(exs, max_itens=a.max_ugs * len(tipos), tipos=tuple(tipos))
        if bj_vencido():
            trabalho.insert(0, {"ug": "TODAS", "tipo": "BJ", "exercicio": max(exs), "a_partir": None,
                                "motivo": "bloqueio_judicial_diario"})
    elif a.ugs:
        # fila DIRIGIDA (12/11/2026): o resolvedor de duplicidade precisa do PROCESSO das NEs de 2023 das UGs
        # cujas OBs vieram sem processo (SIAFE 1 desativado; o SIAFE 2 ainda serve 2023). Mesma regra de
        # frescor da fila por valor: tipo completo há < 30 dias fica fora.
        alvo = [u.strip() for u in a.ugs.split(",") if u.strip()]
        livres = set(fila(a.exercicio, max_ugs=10 ** 6))
        trabalho = [{"ug": u, "tipo": t, "exercicio": a.exercicio, "a_partir": None}
                    for u in alvo for t in tipos if (u, t) in livres][: a.max_ugs * len(tipos)]
    else:
        trabalho = [{"ug": u, "tipo": t, "exercicio": a.exercicio, "a_partir": None}
                    for u, t in fila(a.exercicio, max_ugs=a.max_ugs) if t in tipos]
    prazo = _prazo(a, _agora())
    ate_abs = prazo.strftime("%Y-%m-%dT%H:%M")
    print(f"[{time.strftime('%F %T')}] fila: {[(x['ug'], x['tipo'], x['exercicio']) for x in trabalho]} "
          f"· prazo {ate_abs}", flush=True)
    feitos, parou = [], None
    for it in trabalho:
        ug, tipo, ex = it["ug"], it["tipo"], it["exercicio"]
        if _passou(prazo):
            parou = f"prazo {ate_abs}"
            print(f"  prazo {ate_abs} atingido — paro antes de {ug}/{tipo}/{ex}", flush=True)
            break
        carga = os.getloadavg()[0]
        if carga > a.load_max:
            parou = f"load {carga:.2f}"
            print(f"  load {carga:.2f} > {a.load_max} — paro antes de {ug}/{tipo}/{ex}", flush=True)
            break
        t0 = time.time()
        # o prazo vai PARA DENTRO do coletor: ele para entre fatias e faz logout. Matar no meio deixaria a sessão
        # viva no servidor e o login seguinte (o diário das 05:00) cairia na sessão órfã.
        cmd = [sys.executable, "-m", "compliance_agent.siafe_documento", "--tipo", tipo, "--ug", ug,
               "--exercicio", str(ex), "--ate", ate_abs]
        if it.get("a_partir"):
            cmd += ["--a-partir", it["a_partir"]]
        r = subprocess.run(cmd, cwd=_REPO, capture_output=True, text=True, timeout=7200)
        ult = (r.stdout.strip().splitlines() or [""])[-1]
        try:
            d = json.loads(ult)
            resumo = {k: d.get(k) for k in ("ok", "ingeridas", "capou", "cobertura_pela_ob", "cobertura_pela_nl",
                                             "ne_rebaixada", "etapa", "erro")}
        except ValueError:
            # a causa mora no stderr (traceback): 19/11 296100/NE/2024 morreu com rc=1 e só a linha do login ficou
            resumo = {"rc": r.returncode, "saida": ult[:200], "erro": " | ".join(r.stderr.strip().splitlines()[-3:])[:400]}
        print(f"  {ug}/{tipo}/{ex}{' (incremental)' if it.get('a_partir') else ''} em {time.time() - t0:.0f}s: "
              f"{resumo}", flush=True)
        feitos.append({**it, **resumo, "segundos": round(time.time() - t0)})
        parou = _parar(resumo, f"{r.stdout[-300:]} {r.stderr[-300:]}")
        if parou:
            print(f"  paro a passada: {parou}", flush=True)
            break
    try:
        ESTADO.write_text(json.dumps({"em": time.strftime("%F %T"), "fila": len(trabalho), "feitos": feitos,
                                      "parou": parou}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    except OSError as exc:
        print(f"  estado não gravado: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
