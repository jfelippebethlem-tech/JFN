"""siafe_status_ob — recoleta do `status_envio` das OBs que a coleta fotografou em estado intermediário.

POR QUE EXISTE (verificação Fable de 13/11/2026, condição do LIGAR). O `status_envio` é a foto do dia em que a OB
foi colhida e nunca mais muda na base: 37.982 OBs de 2026 (R$ 9.627,8 mi) seguiam "Enviado ao Banco", e onde o
espelho permite conferir, 2,4% delas foram devolvidas depois. Devolução posterior à coleta é invisível para
qualquer soma de OB recente.

COMO. A tela OB Orçamentária filtra por Data Emissão (`siafe_ob_orcamentaria.coletar_por_data`, o mesmo
verificador do diário, que subdivide o dia com mais de 1.000 OBs) e a ingestão é INSERT OR REPLACE pela chave
(numero_ob, ug_emitente, exercicio): recolher o dia atualiza o status. A fila é por DIA, priorizada pelo VALOR
das OBs ainda intermediárias; o dia recolhido sem mudança espera o dobro para voltar (3, 6, 12, 24 dias) —
lição do dreno que repetiu os mesmos pares 3.721 vezes sem ganho.

"Enviado Manualmente" NÃO é intermediário: é estável há anos (2024: 33.191; 2025: 38.220) — é um meio de envio.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DB = _REPO / "data" / "compliance.db"
INTERMEDIARIOS = ("Enviado ao Banco", "Aguardando Envio", "Aguardando Geração RE")
IDADE_MIN_DIAS = 3        # ontem e anteontem já são recolhidos pelo verificador do diário
REFRESCO_DIAS = 3
_ESPERA_MAX_DIAS = 24

logger = logging.getLogger(__name__)

_DDL = """CREATE TABLE IF NOT EXISTS ob_status_recoleta (
    exercicio INTEGER NOT NULL, data_emissao TEXT NOT NULL, recoletado_em TEXT NOT NULL,
    intermed_antes INTEGER, intermed_depois INTEGER, valor_antes REAL, valor_depois REAL,
    sem_mudanca INTEGER NOT NULL DEFAULT 0, transicoes TEXT, PRIMARY KEY (exercicio, data_emissao))"""
_IN = "(" + ",".join("?" * len(INTERMEDIARIOS)) + ")"


def _iso(dmy: str) -> date | None:
    try:
        return datetime.strptime(dmy, "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def espera_dias(sem_mudanca: int) -> int:
    return min(_ESPERA_MAX_DIAS, REFRESCO_DIAS * 2 ** max(0, int(sem_mudanca)))


def fila(exercicio: int, db=None, max_dias: int = 6, agora: datetime | None = None) -> list[dict]:
    """Dias (DD/MM/AAAA) a recolher, do maior valor intermediário para o menor."""
    agora = agora or datetime.now()
    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=30)
    try:
        dias = con.execute(
            # ob-qualquer-status: consulta de cobertura/estado da coleta (lê todo status de propósito; não soma pago)
            "SELECT data_emissao, COUNT(*), SUM(valor) FROM ob_orcamentaria_siafe WHERE exercicio=? "
            f"AND status='Contabilizado' AND status_envio IN {_IN} AND numero_ob<>'' GROUP BY 1",
            (int(exercicio), *INTERMEDIARIOS)).fetchall()
        try:
            feitos = {r[0]: (r[1], r[2]) for r in con.execute(
                "SELECT data_emissao, recoletado_em, sem_mudanca FROM ob_status_recoleta WHERE exercicio=?",
                (int(exercicio),))}
        except sqlite3.OperationalError:
            feitos = {}
    finally:
        con.close()
    corte = agora.date() - timedelta(days=IDADE_MIN_DIAS)
    saida = []
    for d, n, v in dias:
        dia = _iso(d)
        if dia is None or dia > corte:
            continue
        if d in feitos:
            quando, sem = feitos[d]
            if datetime.fromisoformat(quando) > agora - timedelta(days=espera_dias(sem)):
                continue
        saida.append({"data": d, "n": n, "valor": round(v or 0.0, 2)})
    saida.sort(key=lambda x: -x["valor"])
    return saida[:max_dias]


def _foto(con, exercicio: int, data: str) -> dict[tuple, tuple[str, float]]:
    return {(r[0], r[1]): (r[2], r[3]) for r in con.execute(
        # ob-qualquer-status: consulta de cobertura/estado da coleta (lê todo status de propósito; não soma pago)
        "SELECT numero_ob, ug_emitente, status_envio, valor FROM ob_orcamentaria_siafe WHERE exercicio=? "
        f"AND data_emissao=? AND status='Contabilizado' AND status_envio IN {_IN} AND numero_ob<>''",
        (int(exercicio), data, *INTERMEDIARIOS))}


def registrar(exercicio: int, data: str, antes: dict, db=None) -> dict:
    """Compara o dia com a foto de ANTES e grava a passada. Transição = status novo de cada OB que estava
    intermediária; OB que sumiu da tabela conta como 'nao_reencontrada' (coleta parcial, não 'pago')."""
    con = sqlite3.connect(db or _DB, timeout=120)
    try:
        con.execute(_DDL)
        trans: Counter = Counter()
        for (num, ug) in antes:
            # ob-qualquer-status: consulta de cobertura/estado da coleta (lê todo status de propósito; não soma pago)
            r = con.execute("SELECT status_envio FROM ob_orcamentaria_siafe WHERE numero_ob=? AND ug_emitente=? "
                            "AND exercicio=?", (num, ug, int(exercicio))).fetchone()
            trans[(r[0] or "") if r else "nao_reencontrada"] += 1
        depois = _foto(con, exercicio, data)
        mudou = len(depois) != len(antes)
        ant = con.execute("SELECT sem_mudanca FROM ob_status_recoleta WHERE exercicio=? AND data_emissao=?",
                          (int(exercicio), data)).fetchone()
        sem = 0 if mudou else (ant[0] + 1 if ant else 1)
        reg = {"data": data, "intermed_antes": len(antes), "intermed_depois": len(depois),
               "valor_antes": round(sum(v for _, v in antes.values()), 2),
               "valor_depois": round(sum(v for _, v in depois.values()), 2), "transicoes": dict(trans),
               "sem_mudanca": sem}
        con.execute("INSERT OR REPLACE INTO ob_status_recoleta VALUES (?,?,?,?,?,?,?,?,?)",
                    (int(exercicio), data, datetime.now().isoformat(timespec="seconds"), reg["intermed_antes"],
                     reg["intermed_depois"], reg["valor_antes"], reg["valor_depois"], sem,
                     ";".join(f"{k}={v}" for k, v in sorted(trans.items()))))
        con.commit()
    finally:
        con.close()
    return reg


async def recoletar(exercicio: int, max_dias: int = 6, prazo: float | None = None, db=None,
                    _coletar_dia=None, _relogio=time.time, batimento=None) -> dict:
    """Recolhe os dias da fila até `max_dias` ou até o `prazo` (epoch), conferido ENTRE dias. Quem chama segura o
    lock do `siafe_runner` (renovado por `batimento` a cada dia: o lock vence em 30 min sem heartbeat); o
    `browser_lock(siafe)` é pego dentro de `coletar_por_data`."""
    if _coletar_dia is None:
        from compliance_agent import siafe_ob_orcamentaria as M
        _coletar_dia = M.coletar_por_data
    dias, feitos = fila(exercicio, db=db, max_dias=max_dias), []
    for d in dias:
        if prazo is not None and _relogio() >= prazo:
            feitos.append({"data": d["data"], "pulado": "prazo"})
            break
        if batimento:
            batimento()
        con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=60)
        try:
            antes = _foto(con, exercicio, d["data"])
        finally:
            con.close()
        try:
            r = await _coletar_dia(exercicio, d["data"])
        except TimeoutError as e:       # browser ocupado por outra coleta: o dia volta na próxima passada
            r = {"ok": False, "erro": "navegador_ocupado", "detail": str(e)[:120]}
        if not r.get("ok"):
            feitos.append({"data": d["data"], "ok": False, "erro": r.get("erro") or r.get("etapa")})
            continue                     # sem registro: falha não conta como "sem mudança"
        feitos.append({**registrar(exercicio, d["data"], antes, db=db), "ok": True})
    devolvidas = sum(f.get("transicoes", {}).get("Erro no Pagamento", 0) for f in feitos)
    return {"ok": True, "exercicio": exercicio, "fila": len(dias), "dias": feitos,
            "viraram_erro_no_pagamento": devolvidas}
