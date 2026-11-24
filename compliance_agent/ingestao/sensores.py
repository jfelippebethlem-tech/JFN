# -*- coding: utf-8 -*-
"""Os 6 sensores por fonte (O4.11; doc 2 §40.2): completude, validade, unicidade, consistência, atualidade,
reconciliação origem×ingestão.

Cada sensor é uma FUNÇÃO PURA sobre registros (ou sobre números já medidos) e devolve sempre o mesmo formato:

    {"sensor": nome, "estado": "OK" | "ALERTA" | "INDISPONIVEL", "valor": float | None, "n": int, "detalhe": str}

INDISPONÍVEL ≠ 0: tabela ausente, fonte nunca coletada, origem que não declara total — o sensor diz que NÃO
mediu, nunca devolve 100% nem zero no escuro. O SQL que alimenta cada sensor sai de `sql_*` (identificadores já
validados pelo contrato) e `medir_fonte` junta tudo numa conexão SÓ-LEITURA. Validade e consistência rodam
sobre a AMOSTRA das linhas mais recentes (regex não existe no SQLite); completude também, para não varrer
1,37 mi de OB a cada medição; unicidade é a tabela inteira (GROUP BY na chave natural).
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime

from compliance_agent.ingestao.contrato import Fonte, RegraConsistencia, validar_registro

OK, ALERTA, INDISPONIVEL = "OK", "ALERTA", "INDISPONIVEL"
COMPLETUDE_MIN = 0.95
VALIDADE_MIN = 0.99
AMOSTRA = 5000


def _r(sensor, estado, valor=None, n=0, detalhe=""):
    return {"sensor": sensor, "estado": estado, "valor": None if valor is None else round(valor, 6),
            "n": n, "detalhe": detalhe}


def _preenchido(v) -> bool:
    return v is not None and str(v).strip() != ""


# ── funções puras ──────────────────────────────────────────────────────────────────────────────────

def completude(registros: list[dict], campos_criticos: list[str], minimo: float = COMPLETUDE_MIN) -> dict:
    if not campos_criticos:
        return _r("completude", INDISPONIVEL, detalhe="contrato sem campo crítico declarado")
    if not registros:
        return _r("completude", INDISPONIVEL, detalhe="nenhum registro para medir")
    total = len(registros) * len(campos_criticos)
    cheios = sum(_preenchido(r.get(c)) for r in registros for c in campos_criticos)
    piores = sorted(campos_criticos, key=lambda c: sum(_preenchido(r.get(c)) for r in registros))[:3]
    frac = cheios / total
    return _r("completude", OK if frac >= minimo else ALERTA, frac, len(registros),
              f"{cheios}/{total} células críticas preenchidas; menos preenchidos: {', '.join(piores)}")


def validade(registros: list[dict], fonte: Fonte, minimo: float = VALIDADE_MIN) -> dict:
    if not fonte.campos:
        return _r("validade", INDISPONIVEL, detalhe="contrato sem campos")
    if not registros:
        return _r("validade", INDISPONIVEL, detalhe="nenhum registro para medir")
    motivos: dict[str, int] = {}
    invalidos = 0
    for reg in registros:
        m = validar_registro(fonte, reg)
        if m:
            invalidos += 1
            k = m[0].split(":")[0]
            motivos[k] = motivos.get(k, 0) + 1
    frac = 1 - invalidos / len(registros)
    top = ", ".join(f"{k}={v}" for k, v in sorted(motivos.items(), key=lambda x: -x[1])[:3])
    return _r("validade", OK if frac >= minimo else ALERTA, frac, len(registros),
              f"{invalidos} inválido(s)" + (f" — {top}" if top else ""))


def unicidade_de_contagens(linhas: int, excedentes: int, chaves_repetidas: int, maximo: float = 0.0) -> dict:
    """`excedentes` = linhas além da 1ª de cada chave repetida."""
    if linhas == 0:
        return _r("unicidade", INDISPONIVEL, detalhe="tabela vazia")
    frac = excedentes / linhas
    return _r("unicidade", OK if frac <= maximo else ALERTA, frac, linhas,
              f"{chaves_repetidas} chave(s) natural(is) repetida(s), {excedentes} linha(s) excedente(s)")


def unicidade(registros: list[dict], chave: list[str], maximo: float = 0.0) -> dict:
    vistos: dict[tuple, int] = {}
    for r in registros:
        k = tuple(str(r.get(c) or "").strip() for c in chave)
        vistos[k] = vistos.get(k, 0) + 1
    rep = [n for n in vistos.values() if n > 1]
    return unicidade_de_contagens(len(registros), sum(n - 1 for n in rep), len(rep), maximo)


def _como_data(v) -> date | None:
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _comparavel(v):
    d = _como_data(v)
    if d is not None:
        return d
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def violacao(regra: RegraConsistencia, reg: dict) -> bool | None:
    """True viola, False respeita, None não julga (campo vazio/ilegível)."""
    a, b = (reg.get(c) for c in regra.campos)
    if not _preenchido(a) or not _preenchido(b):
        return None
    if regra.tipo == "ordem":
        x, y = _comparavel(a), _comparavel(b)
        if x is None or y is None or type(x) is not type(y):
            return None
        return x > y
    d = _como_data(a)
    try:
        ex = int(str(b).strip())
    except ValueError:
        return None
    return None if d is None else d.year != ex


def consistencia(registros: list[dict], regras: list[RegraConsistencia]) -> dict:
    if not regras:
        return _r("consistencia", INDISPONIVEL, detalhe="contrato sem regra entre campos")
    if not registros:
        return _r("consistencia", INDISPONIVEL, detalhe="nenhum registro para medir")
    julgados = violados = 0
    por_regra: dict[str, int] = {}
    for reg in registros:
        for regra in regras:
            v = violacao(regra, reg)
            if v is None:
                continue
            julgados += 1
            if v:
                violados += 1
                k = f"{regra.tipo}({','.join(regra.campos)})"
                por_regra[k] = por_regra.get(k, 0) + 1
    if not julgados:
        return _r("consistencia", INDISPONIVEL, n=len(registros), detalhe="nenhuma linha julgável (campos vazios)")
    frac = 1 - violados / julgados
    return _r("consistencia", OK if violados == 0 else ALERTA, frac, julgados,
              f"{violados} violação(ões) em {julgados} julgamento(s)"
              + (f" — {', '.join(f'{k}={v}' for k, v in por_regra.items())}" if por_regra else ""))


def _instante(v, formato: str) -> datetime | None:
    s = str(v or "").strip()
    if not s:
        return None
    try:
        if formato == "data_br":
            return datetime.strptime(s[:10], "%d/%m/%Y")
        if formato == "data_iso":
            return datetime.strptime(s[:10], "%Y-%m-%d")
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.replace(tzinfo=None)
    except ValueError:
        return None


def atualidade(ultima, agora: datetime, slo_h: float | None, *, estado_fonte: str = "ATIVA",
               motivo_estado: str | None = None, formato: str = "datahora_iso") -> dict:
    """Atraso da última coleta contra o SLO. Fonte declarada INDISPONÍVEL/CONGELADA na origem não vira
    ATRASADO: o sensor repete o motivo declarado (o TFE recusa datacenter — não é coleta 'atrasada')."""
    if estado_fonte in ("INDISPONIVEL", "CONGELADA_NA_ORIGEM"):
        d = _instante(ultima, formato)
        h = None if d is None else (agora - d).total_seconds() / 3600
        return _r("atualidade", INDISPONIVEL, h, detalhe=f"{estado_fonte}: {motivo_estado or 'sem motivo'}")
    if slo_h is None:
        return _r("atualidade", INDISPONIVEL, detalhe="sem SLO no contrato")
    d = _instante(ultima, formato)
    if d is None:
        return _r("atualidade", INDISPONIVEL, detalhe="nunca coletada (ou frescor ilegível)")
    h = (agora - d).total_seconds() / 3600
    return _r("atualidade", OK if h <= slo_h else ALERTA, h, 1,
              f"última coleta {d.isoformat(sep=' ', timespec='seconds')}; atraso {h:.1f} h × SLO {slo_h:g} h"
              + ("" if h <= slo_h else " — ATRASADO"))


def reconciliacao(origem: int | None, ingeridos: int | None, tolerancia: float = 0.0) -> dict:
    """Origem × ingestão. `origem` = o que a fonte DECLARA (recordsFiltered, QuantidadeParticipante, total do
    arquivo); sem isso não há reconciliação — INDISPONÍVEL, não OK."""
    if origem is None or ingeridos is None:
        return _r("reconciliacao", INDISPONIVEL, detalhe="a origem não declara total para este lote/fonte")
    if origem == 0:
        return _r("reconciliacao", OK if ingeridos == 0 else ALERTA, 0.0 if ingeridos == 0 else 1.0, ingeridos,
                  f"origem declara 0, ingeridos {ingeridos}")
    dif = (ingeridos - origem) / origem
    return _r("reconciliacao", OK if abs(dif) <= tolerancia else ALERTA, dif, ingeridos,
              f"origem {origem} × ingeridos {ingeridos} ({dif:+.2%})")


# ── SQL (identificadores já validados pelo contrato) ───────────────────────────────────────────────

def _q(nome: str) -> str:
    return f'"{nome}"'


def sql_amostra(fonte: Fonte, limite: int = AMOSTRA) -> str:
    cols = ", ".join(_q(c) for c in fonte.campos)
    return f"SELECT {cols} FROM {_q(fonte.tabela)} ORDER BY rowid DESC LIMIT {int(limite)}"


def sql_unicidade(fonte: Fonte) -> str:
    k = ", ".join(_q(c) for c in fonte.chave_natural)
    return (f"SELECT (SELECT COUNT(*) FROM {_q(fonte.tabela)}), COALESCE(SUM(n - 1), 0), COUNT(*) "
            f"FROM (SELECT COUNT(*) AS n FROM {_q(fonte.tabela)} GROUP BY {k} HAVING COUNT(*) > 1)")


def sql_frescor(fonte: Fonte) -> str:
    c = _q(fonte.coluna_frescor)
    if fonte.formato_frescor == "data_br":   # DD/MM/AAAA é texto: MAX cru ordenaria pelo dia do mês
        return (f"SELECT MAX(substr({c},7,4)||'-'||substr({c},4,2)||'-'||substr({c},1,2)) "
                f"FROM {_q(fonte.tabela)}")
    return f"SELECT MAX({c}) FROM {_q(fonte.tabela)}"


SQL_ULTIMO_LOTE = ("SELECT origem_declarada, aceitos + duplicados FROM ingestao_lote WHERE fonte = ? "
                   "ORDER BY iniciado_em DESC LIMIT 1")


def _tem(con, tabela: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
                       (tabela,)).fetchone() is not None


def medir_fonte(con: sqlite3.Connection, fonte_id: str, fonte: Fonte, agora: datetime | None = None,
                amostra: int = AMOSTRA) -> dict:
    """Os 6 sensores de uma fonte externa. Só lê. Fonte interna ou tabela ausente → tudo INDISPONÍVEL."""
    agora = agora or datetime.now()
    nomes = ("completude", "validade", "unicidade", "consistencia", "atualidade", "reconciliacao")
    if fonte.natureza != "externa":
        return {"fonte": fonte_id, "sensores": [_r(n, INDISPONIVEL, detalhe="fonte interna") for n in nomes]}
    if not _tem(con, fonte.tabela):
        return {"fonte": fonte_id, "sensores": [_r(n, INDISPONIVEL, detalhe=f"tabela {fonte.tabela} ausente neste banco")
                                                for n in nomes]}
    cur = con.execute(sql_amostra(fonte, amostra))
    cols = [d[0] for d in cur.description]
    regs = [dict(zip(cols, linha)) for linha in cur.fetchall()]
    criticos = [c for c, d in fonte.campos.items() if d.critico]
    linhas, exced, rep = con.execute(sql_unicidade(fonte)).fetchone()
    ultima = con.execute(sql_frescor(fonte)).fetchone()[0]
    origem = ingeridos = None
    if _tem(con, "ingestao_lote"):
        r = con.execute(SQL_ULTIMO_LOTE, (fonte_id,)).fetchone()
        if r:
            origem, ingeridos = r
    return {"fonte": fonte_id, "tabela": fonte.tabela, "amostra": len(regs), "sensores": [
        completude(regs, criticos),
        validade(regs, fonte),
        unicidade_de_contagens(linhas, exced, rep),
        consistencia(regs, fonte.consistencia),
        atualidade(ultima, agora, fonte.slo_frescor_h, estado_fonte=fonte.estado,
                   motivo_estado=fonte.motivo_estado, formato=fonte.formato_frescor),
        reconciliacao(origem, ingeridos),
    ]}
