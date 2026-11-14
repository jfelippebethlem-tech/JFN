"""siafe_gd — Guia de Devolução (GD) do SIAFE-Rio 2: quanto de cada OB voltou do banco.

POR QUE EXISTE (verificação Fable de 13/11/2026, condição do LIGAR da perícia diária). A OB devolvida continua
'Contabilizado' no SIAFE. Com `status_envio = 'Erro no Pagamento'` a devolução é integral (99,5% conferido); com GD
e outro status (Parcialmente Pago, Processado e Pago, Enviado Manualmente) o valor devolvido só existe na tela
Guia de Devolução — sem ela a perícia tira a OB da soma e o pago vira piso. A coleta da tela mora em
`siafe_documento` (tipo "GD", mesma grade da NE/NL); aqui ficam a fila, a leitura para a perícia e a passada diária.

Vínculo GD → OB: coluna OB da guia + UG emitente (o número da OB e o da GD se repetem entre UGs — ver a PK que
apagava OB de outra UG). Guia cancelada/estornada/anulada não abate nada.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DB = _REPO / "data" / "compliance.db"
_FRESCA_DIAS_CORRENTE = 7     # GD nova entra todo dia no ano corrente
_FRESCA_DIAS_FECHADO = 30
_RE_NAO_VALE = re.compile(r"cancel|estorn|anula|exclu", re.I)

logger = logging.getLogger(__name__)


def devolvido_por_ob(con) -> dict[tuple[str, str], float]:
    """{(numero_ob, ug_emitente): valor devolvido somado} das guias válidas. Sem a tabela = {} (nada conhecido —
    a perícia segue com a regra de piso, nunca com zero devolvido)."""
    try:
        linhas = con.execute("SELECT ob, ug_emitente, status, valor FROM gd_siafe "
                             "WHERE ob IS NOT NULL AND ob<>''").fetchall()
    except sqlite3.OperationalError:
        return {}
    dev: dict[tuple[str, str], float] = {}
    for ob, ug, status, valor in linhas:
        if valor is None or _RE_NAO_VALE.search(status or ""):
            continue
        k = (str(ob).strip(), str(ug).strip())
        dev[k] = round(dev.get(k, 0.0) + float(valor), 2)
    return dev


def fila_gd(exercicio: int, db=None, max_ugs: int = 2, agora: datetime | None = None) -> list[str]:
    """UGs na ordem de coleta da GD: primeiro as de maior valor em OB com GD cujo valor devolvido a perícia ainda
    não conhece (GD na OB sem 'Erro no Pagamento' e sem a guia na base); depois o resto por valor pago (a
    devolução POSTERIOR à coleta da OB não deixa rastro na OB). Pula UG com GD completa e fresca."""
    agora = agora or datetime.now()
    con = sqlite3.connect(f"file:{db or _DB}?mode=ro", uri=True, timeout=30)
    try:
        try:
            con.execute("SELECT 1 FROM gd_siafe LIMIT 1")
            sem_guia = "NOT EXISTS (SELECT 1 FROM gd_siafe g WHERE g.numero=o.gd AND g.ug_emitente=o.ug_emitente)"
        except sqlite3.OperationalError:
            sem_guia = "1"
        ugs = [r[0] for r in con.execute(
            "SELECT o.ug_emitente FROM ob_orcamentaria_siafe o WHERE o.exercicio=? AND o.status='Contabilizado' "
            "GROUP BY 1 ORDER BY SUM(CASE WHEN o.gd LIKE '20__GD%' AND COALESCE(o.status_envio,'')<>'Erro no Pagamento' "
            f"AND {sem_guia} THEN o.valor ELSE 0 END) DESC, SUM(o.valor) DESC", (int(exercicio),))]
        try:
            cob = {r[0]: (r[1], r[2]) for r in con.execute(
                "SELECT ug_emitente, completo, em FROM siafe_documento_cobertura WHERE tipo='GD' AND exercicio=?",
                (int(exercicio),))}
        except sqlite3.OperationalError:
            cob = {}
    finally:
        con.close()
    dias = _FRESCA_DIAS_CORRENTE if int(exercicio) >= agora.year else _FRESCA_DIAS_FECHADO
    limite = (agora - timedelta(days=dias)).strftime("%F %T")
    return [u for u in ugs if not (cob.get(u, (0, ""))[0] and cob[u][1] >= limite)][:max_ugs]


async def coletar_fila(exercicio: int, max_ugs: int = 2, ate: str | None = None, db=None,
                       _coletar=None, _fila=None, batimento=None) -> dict:
    """Uma passada da fila da GD NO PROCESSO CHAMADOR (quem chama já segura o lock do `siafe_runner`; o
    `browser_lock(siafe)` é pego dentro de `siafe_documento.coletar_ug`). `ate` = prazo absoluto AAAA-MM-DDTHH:MM,
    conferido entre UGs e, dentro da UG, entre fatias (sai com logout, nunca no meio)."""
    from compliance_agent import siafe_documento as D
    coletar = _coletar or D.coletar_ug
    ugs = (_fila or fila_gd)(exercicio, db=db, max_ugs=max_ugs)
    feitas = []
    for ug in ugs:
        if D._passou(ate):
            feitas.append({"ug": ug, "pulada": "prazo"})
            break
        if batimento:                  # heartbeat do lock do runner entre UGs
            batimento()
        r = await coletar(ug, exercicio, "GD", ate)
        completo = D.fechar_cobertura("GD", ug, exercicio, r, db=db)
        feitas.append({"ug": ug, "ok": r.get("ok"), "ingeridas": r.get("ingeridas"), "etapa": r.get("etapa"),
                       "cobertura_pela_ob": r.get("cobertura_pela_ob"), "completo": completo})
    return {"ok": True, "exercicio": exercicio, "ugs": feitas}
