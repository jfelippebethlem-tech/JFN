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

RELEITURA AMPLIADA (19/11/2026, medição `siafe_ingest_cobertura`). A passada só cobria o exercício CORRENTE e só o
intermediário Contabilizado: 2024/2025 tinham 1.608 OB 'Enviado ao Banco'/'Aguardando…' (R$ 426 mi) nunca relidas,
2026 tinha 778 'Não contabilizado' (R$ 324,7 mi) e 28.771 OB (R$ 4,31 bi) com a foto tirada até 7 dias depois da
emissão e nunca refeita. Agora: `NAO_FINAL` inclui 'Não contabilizado' e envio vazio; `fila_varios` junta os
exercícios; a CONSOLIDAÇÃO relê uma vez o dia dos últimos 60 dias cuja última foto foi precoce (status já final
na foto também muda: devolução e anulação chegam depois); e `rodar` é a entrada do despachante (orçamento de tempo,
fora da janela do diário, para no 1º login que falha — repetir login só soma tentativa e MFA).
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
# NÃO FINAL = o status ainda pode mudar: intermediário do envio, envio vazio, ou nem contabilizada ainda
NAO_FINAL = ("((status='Contabilizado' AND (status_envio IN ('Enviado ao Banco','Aguardando Envio',"
             "'Aguardando Geração RE') OR COALESCE(status_envio,'')='')) OR status='Não contabilizado')")
CONSOLIDA_JANELA_DIAS = 60     # dia emitido há até 60 dias…
CONSOLIDA_FOTO_DIAS = 10       # …cuja ÚLTIMA foto foi tirada até 10 dias após a emissão: relê uma vez
_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"
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
            f"AND {NAO_FINAL} AND numero_ob<>'' GROUP BY 1", (int(exercicio),)).fetchall()
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
        saida.append({"data": d, "n": n, "valor": round(v or 0.0, 2), "exercicio": int(exercicio),
                      "motivo": "nao_final"})
    saida.sort(key=lambda x: -x["valor"])
    return saida[:max_dias]


def fila_consolidacao(exercicio: int, db=None, max_dias: int = 6, agora: datetime | None = None) -> list[dict]:
    """Dias emitidos há 10–60 dias cuja ÚLTIMA leitura (coleta ou releitura) foi até 10 dias após a emissão: a foto
    é precoce mesmo com todo status já final. Uma releitura depois disso tira o dia da fila. Maior valor primeiro."""
    agora = agora or datetime.now()
    hoje = agora.strftime("%Y-%m-%d")
    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=30)
    try:
        dias = con.execute(
            # ob-qualquer-status: idade da foto do dia (lê todo status de propósito; não soma pago)
            f"SELECT data_emissao, COUNT(*), SUM(valor), MAX(julianday(substr(coletado_em,1,10))-julianday({_ISO})) "
            f"FROM ob_orcamentaria_siafe WHERE exercicio=? AND numero_ob<>'' AND julianday(?)-julianday({_ISO}) "
            f"BETWEEN ? AND ? GROUP BY 1", (int(exercicio), hoje, CONSOLIDA_FOTO_DIAS, CONSOLIDA_JANELA_DIAS)).fetchall()
        try:
            relidos = {r[0]: r[1] for r in con.execute(
                "SELECT data_emissao, recoletado_em FROM ob_status_recoleta WHERE exercicio=?", (int(exercicio),))}
        except sqlite3.OperationalError:
            relidos = {}
    finally:
        con.close()
    saida = []
    for d, n, v, idade_foto in dias:
        dia = _iso(d)
        if dia is None or idade_foto is None or idade_foto > CONSOLIDA_FOTO_DIAS:
            continue
        if d in relidos and (datetime.fromisoformat(relidos[d]).date() - dia).days > CONSOLIDA_FOTO_DIAS:
            continue
        saida.append({"data": d, "n": n, "valor": round(v or 0.0, 2), "exercicio": int(exercicio),
                      "motivo": "consolidacao"})
    saida.sort(key=lambda x: -x["valor"])
    return saida[:max_dias]


def fila_varios(exercicios=(2026, 2025, 2024), db=None, max_dias: int = 12, agora: datetime | None = None,
                consolidar: bool = True) -> list[dict]:
    """Fila única de releitura: primeiro os dias com OB NÃO FINAL (de qualquer exercício, maior valor primeiro),
    depois a consolidação dos últimos 60 dias. Um dia aparece uma vez só."""
    nf = sorted((d for ex in exercicios for d in fila(ex, db=db, max_dias=10 ** 6, agora=agora)),
                key=lambda x: -x["valor"])
    vistos = {(d["exercicio"], d["data"]) for d in nf}
    cons = []
    if consolidar:
        cons = sorted((d for ex in exercicios for d in fila_consolidacao(ex, db=db, max_dias=10 ** 6, agora=agora)
                       if (d["exercicio"], d["data"]) not in vistos), key=lambda x: -x["valor"])
    return (nf + cons)[:max_dias]


def _foto(con, exercicio: int, data: str, todas: bool = False) -> dict[tuple, tuple[str, float]]:
    """OBs NÃO FINAIS do dia (ou todas, na consolidação) → (status/envio, valor)."""
    filtro = "" if todas else f"AND {NAO_FINAL} "
    return {(r[0], r[1]): (_rotulo(r[2], r[3]), r[4]) for r in con.execute(
        # ob-qualquer-status: consulta de cobertura/estado da coleta (lê todo status de propósito; não soma pago)
        "SELECT numero_ob, ug_emitente, status, status_envio, valor FROM ob_orcamentaria_siafe WHERE exercicio=? "
        f"AND data_emissao=? {filtro}AND numero_ob<>''", (int(exercicio), data))}


def _rotulo(status: str | None, envio: str | None) -> str:
    """O estado de uma OB numa palavra: o envio se Contabilizada; senão o próprio status (Anulado, Excluído,
    Não contabilizado). Mantém as chaves antigas ('Erro no Pagamento', 'Processado e Pago'…)."""
    return (envio or "") if status == "Contabilizado" else (status or "")


def registrar(exercicio: int, data: str, antes: dict, db=None, consolidacao: bool = False) -> dict:
    """Compara o dia com a foto de ANTES e grava a passada. Transição = estado novo de cada OB que estava não
    final; OB que sumiu da tabela conta como 'nao_reencontrada' (coleta parcial, não 'pago'). Na CONSOLIDAÇÃO
    (`antes` = todas as OBs do dia) só conta quem MUDOU, com a chave 'de→para'."""
    con = sqlite3.connect(db or _DB, timeout=120)
    try:
        con.execute(_DDL)
        trans: Counter = Counter()
        mudaram = 0
        for (num, ug), (rot_antes, _v) in antes.items():
            # ob-qualquer-status: consulta de cobertura/estado da coleta (lê todo status de propósito; não soma pago)
            r = con.execute("SELECT status, status_envio FROM ob_orcamentaria_siafe WHERE numero_ob=? "
                            "AND ug_emitente=? AND exercicio=?", (num, ug, int(exercicio))).fetchone()
            novo = _rotulo(r[0], r[1]) if r else "nao_reencontrada"
            mudaram += novo != rot_antes
            if not consolidacao:
                trans[novo] += 1
            elif novo != rot_antes:
                trans[f"{rot_antes}→{novo}"] += 1
        depois = _foto(con, exercicio, data)
        antes_nf = {k: v for k, v in antes.items() if v[0] in (*INTERMEDIARIOS, "", "Não contabilizado")}
        mudou = bool(mudaram) or len(depois) != len(antes_nf)
        ant = con.execute("SELECT sem_mudanca FROM ob_status_recoleta WHERE exercicio=? AND data_emissao=?",
                          (int(exercicio), data)).fetchone()
        sem = 0 if mudou else (ant[0] + 1 if ant else 1)
        reg = {"data": data, "intermed_antes": len(antes_nf), "intermed_depois": len(depois),
               "valor_antes": round(sum(v for _, v in antes_nf.values()), 2),
               "valor_depois": round(sum(v for _, v in depois.values()), 2), "transicoes": dict(trans),
               "sem_mudanca": sem, "mudaram": mudaram, "consolidacao": consolidacao}
        con.execute("INSERT OR REPLACE INTO ob_status_recoleta VALUES (?,?,?,?,?,?,?,?,?)",
                    (int(exercicio), data, datetime.now().isoformat(timespec="seconds"), reg["intermed_antes"],
                     reg["intermed_depois"], reg["valor_antes"], reg["valor_depois"], sem,
                     ";".join(f"{k}={v}" for k, v in sorted(trans.items()))))
        con.commit()
    finally:
        con.close()
    return reg


async def recoletar(exercicio: int, max_dias: int = 6, prazo: float | None = None, db=None,
                    _coletar_dia=None, _relogio=time.time, batimento=None, agora: datetime | None = None) -> dict:
    """Recolhe os dias da fila até `max_dias` ou até o `prazo` (epoch), conferido ENTRE dias. Quem chama segura o
    lock do `siafe_runner` (renovado por `batimento` a cada dia: o lock vence em 30 min sem heartbeat); o
    `browser_lock(siafe)` é pego dentro de `coletar_por_data`. `agora` (padrão: relógio real) fixa o corte da fila —
    sem ele o teste com data sintética virava bomba-relógio quando o dia "recente" envelhecia."""
    dias = fila(exercicio, db=db, max_dias=max_dias, agora=agora)
    r = await _recoletar_dias(dias, prazo=prazo, db=db, _coletar_dia=_coletar_dia, _relogio=_relogio,
                              batimento=batimento)
    return {**r, "exercicio": exercicio}


def _falha_de_login(r: dict) -> bool:
    """Login/MFA/senha que falhou: a passada PARA (cada dia é um login novo; repetir só soma tentativa e pede MFA
    de novo ao dono). `coletar_por_data` devolve etapa 'login_nav'; o coletor de documentos, 'login'."""
    txt = f"{r.get('etapa') or ''} {r.get('erro') or ''}".lower()
    return any(k in txt for k in ("login", "mfa", "senha", "credencial"))


async def _recoletar_dias(dias: list[dict], prazo: float | None = None, db=None, _coletar_dia=None,
                          _relogio=time.time, batimento=None) -> dict:
    if _coletar_dia is None:
        from compliance_agent import siafe_ob_orcamentaria as M
        _coletar_dia = M.coletar_por_data
    feitos, parou = [], None
    for d in dias:
        ex, cons = int(d.get("exercicio")), d.get("motivo") == "consolidacao"
        if prazo is not None and _relogio() >= prazo:
            feitos.append({"data": d["data"], "exercicio": ex, "pulado": "prazo"})
            break
        if batimento:
            batimento()
        con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=60)
        try:
            antes = _foto(con, ex, d["data"], todas=cons)
        finally:
            con.close()
        try:
            r = await _coletar_dia(ex, d["data"])
        except TimeoutError as e:       # browser ocupado por outra coleta: o dia volta na próxima passada
            r = {"ok": False, "erro": "navegador_ocupado", "detail": str(e)[:120]}
        if not r.get("ok"):
            feitos.append({"data": d["data"], "exercicio": ex, "ok": False, "erro": r.get("erro") or r.get("etapa")})
            if _falha_de_login(r) or r.get("erro") == "navegador_ocupado":
                parou = feitos[-1]["erro"]
                break
            continue                     # sem registro: falha não conta como "sem mudança"
        feitos.append({**registrar(ex, d["data"], antes, db=db, consolidacao=cons), "exercicio": ex, "ok": True})
    devolvidas = sum(f.get("transicoes", {}).get("Erro no Pagamento", 0) for f in feitos)
    devolvidas += sum(v for f in feitos for k, v in f.get("transicoes", {}).items() if k.endswith("→Erro no Pagamento"))
    return {"ok": parou is None, "fila": len(dias), "dias": feitos, "parou": parou,
            "viraram_erro_no_pagamento": devolvidas,
            "relidos": sum(1 for f in feitos if f.get("ok")),
            "ob_que_mudaram": sum(f.get("mudaram", 0) for f in feitos)}


# ─────────────────────────── entrada do despachante (config/propagacao.yaml: siafe_status_releitura) ───────────
ESTADO = _REPO / "data" / "siafe_status_releitura.json"
JANELA_DIARIO = ("04:00", "06:40")   # diário 05:00 + pós-coleta (45 min); 1 h antes: um dia em curso termina


def _na_janela(agora: datetime, janela=JANELA_DIARIO) -> bool:
    hm = agora.strftime("%H:%M")
    return janela[0] <= hm < janela[1]


def prazo_fora_da_janela(agora: datetime, minutos: int, janela=JANELA_DIARIO) -> datetime:
    """Fim do orçamento: `agora + minutos`, mas nunca depois do início da janela do diário (04:00)."""
    fim = agora + timedelta(minutes=minutos)
    h, m = (int(x) for x in janela[0].split(":"))
    ini = agora.replace(hour=h, minute=m, second=0, microsecond=0)
    if ini <= agora:
        ini += timedelta(days=1)
    return min(fim, ini)


def rodar(exercicios=(2026, 2025, 2024), minutos: int = 80, max_dias: int = 12, agora: datetime | None = None,
          _recoletar=None) -> dict:
    """Uma passada com orçamento: lock do runner (o mesmo do diário/dreno), fora da janela do diário, fila de
    vários exercícios. Grava o resultado em `ESTADO` sempre (é o efeito que o despachante confere)."""
    import asyncio
    import json
    agora = agora or datetime.now()
    res: dict
    if _na_janela(agora):
        res = {"ok": True, "pulado": f"janela do diário {JANELA_DIARIO[0]}–{JANELA_DIARIO[1]}"}
    else:
        from compliance_agent import siafe_runner as R
        fim = prazo_fora_da_janela(agora, minutos)
        if not R._acquire("status:releitura"):
            res = {"ok": True, "pulado": "SIAFE ocupado", "lock": R.lock_status()}
        else:
            try:
                dias = fila_varios(exercicios, max_dias=max_dias, agora=agora)
                corre = _recoletar or _recoletar_dias
                res = asyncio.run(corre(dias, prazo=fim.timestamp(), batimento=R.refresh_lock))
                res["prazo"] = fim.isoformat(timespec="minutes")
            finally:
                R._release()
    res["em"] = datetime.now().isoformat(timespec="seconds")
    ESTADO.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return res


def main() -> None:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="releitura de status das OBs não finais (vários exercícios)")
    ap.add_argument("--exercicios", default="2026,2025,2024")
    ap.add_argument("--minutos", type=int, default=80, help="orçamento da passada (para entre dias)")
    ap.add_argument("--max-dias", type=int, default=12)
    ap.add_argument("--fila", action="store_true", help="só mostra a fila (não abre o SIAFE)")
    a = ap.parse_args()
    exs = tuple(int(x) for x in a.exercicios.split(",") if x.strip())
    if a.fila:
        print(json.dumps(fila_varios(exs, max_dias=a.max_dias), ensure_ascii=False, indent=1))
        return
    from compliance_agent import host_siafe
    host_siafe.exigir_autorizacao()
    r = rodar(exs, minutos=a.minutos, max_dias=a.max_dias)
    print(json.dumps(r, ensure_ascii=False, default=str)[:4000])
    if r.get("parou"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
