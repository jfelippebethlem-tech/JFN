# -*- coding: utf-8 -*-
"""E12 `conferir:<laudo|achado>:<ref>` — conferência por RISCO (plano mestre v2 §3.2 E12, §6 "E12 por risco"; O8.5).

Entrada (por item): `conferir:achado:<id do achado no esquema do E10>` ou `conferir:laudo:<processo>` (laudo v2
VIGENTE do E11). A regra de risco é a da O6.5, reaproveitada sem cópia:
  · achado do E10 — `llm/conferencia_risco.motivos_do_item` (valor = soma das OB de SUPORTE ≥ limiar; baixa
    confiança = estado ≠ INDICIO; divergência não se aplica: uma regra só) + amostra 1/8 (`conferencia_risco.sorteado`
    pela origem do achado). O achado do E10 não tem grau: `grave` não se aplica e é declarado assim;
  · laudo do E11 — `periciar.motivos_e12` (os mesmos motivos, gravados no laudo).
Decisão (nunca um veredito sem o conferente):
  · sem motivo                    → `NAO_JULGADO` ("NÃO JULGADO — fila"): visível, nunca "limpo";
  · autor do item = Opus          → `ABSTEVE(autor_e_conferente)`: regra do dono — o Opus não reconfere o próprio
                                    laudo (o 2º revisor do Opus é o ouro, `qualidade/ouro`);
  · com motivo, precisa do Opus   → `ABSTEVE(sem_llm)` gravado e o job levanta `SemCota` (volta com backoff; nunca
                                    "feito"). A porta do executor da assinatura (`llm/conferencia_executor`: it-campo →
                                    VM-2, mesma trava de ritmo) está plugada, mas RECUSA antes de sáb 28/11/2026 19h
                                    (BRT) sem sondar ninguém; aberta a porta, o julgamento pelo motor ainda não está
                                    ligado (a fila `conferencia_opus` segue fora do motor) — também ABSTEVE(sem_llm).
Gravação idempotente pela chave do job + sha da entrada em `<esquema>.conferencia_e12` (esquema `JFN_E12_ESQUEMA`,
senão o do E11, padrão `sombra`). Efeito conferido em OUTRO processo: a linha existe, os motivos RECALCULADOS do item
relido do PG são os gravados, a decisão é a que os motivos dão e o estado nunca é um veredito.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, Estagio
from compliance_agent.fluxo.fila import Resultado

TIPO = "conferir"
VERSAO = "e12-1"
TAREFA = "conferencia_e12"
ALVOS = ("achado", "laudo")
ESQUEMA_PADRAO = "sombra"
ENV_ESQUEMA = "JFN_E12_ESQUEMA"
BRT = timezone(timedelta(hours=-3))
LIBERADO_EM = datetime(2026, 11, 28, 19, 0, tzinfo=BRT)      # virada do ritmo semanal da assinatura (regra do dono)
NAO_JULGADO = "NAO_JULGADO"
ABSTEVE = "ABSTEVE"
ESTADOS = (NAO_JULGADO, ABSTEVE)                              # sem conferente ligado, nada além disso é gravável

DDL = """CREATE TABLE IF NOT EXISTS "{e}".conferencia_e12(
  chave text NOT NULL, entrada_sha text NOT NULL, alvo text NOT NULL, ref text NOT NULL, autor text,
  motivos jsonb NOT NULL, decisao text NOT NULL, estado text NOT NULL, motivo text NOT NULL,
  versao text NOT NULL, em timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (chave, entrada_sha))"""


class SemCota(RuntimeError):
    """O item precisa do Opus e a assinatura não pode (antes de 28/11 19h, ritmo contido, sem executor): o job volta
    com backoff; o que foi decidido sem LLM (motivos) fica gravado."""


def esquema_vigente(payload: dict | None = None) -> str:
    from compliance_agent.fluxo.schema import validar_esquema
    return validar_esquema((payload or {}).get("esquema") or os.environ.get(ENV_ESQUEMA)
                           or os.environ.get("JFN_E11_ESQUEMA") or ESQUEMA_PADRAO)


def conectar(payload: dict):
    import psycopg

    from compliance_agent.evidencias import dsn_vigente
    dsn = payload.get("dsn") or dsn_vigente()
    if not dsn:
        raise RuntimeError("sem DSN do PostgreSQL (JFN_EVIDENCIAS_DSN)")
    return psycopg.connect(dsn, autocommit=True)


def alvo_de(payload: dict, ctx: Contexto | None = None) -> tuple[str, str]:
    """(alvo, ref) do payload ou do tipo `conferir:<alvo>:<ref>`."""
    partes = (ctx.tipo.split(":", 2) if ctx and ctx.tipo.count(":") >= 2 else [])
    alvo = payload.get("alvo") or (partes[1] if partes else "")
    ref = str(payload.get("ref") or (partes[2] if partes else "")).strip()
    if alvo not in ALVOS or not ref:
        raise ErroPermanente(f"E12: alvo inválido {alvo!r}/{ref!r} (conferir:<achado|laudo>:<ref>)")
    return alvo, ref


def _sha(*partes) -> str:
    return hashlib.sha256(json.dumps(partes, sort_keys=True, default=str).encode()).hexdigest()


# ── o item, relido do PG ───────────────────────────────────────────────────────────────────────────────────────
def ler_item(con, esq: str, alvo: str, ref: str) -> dict | None:
    if alvo == "achado":
        r = con.execute(f'SELECT a.estado, e.origem, e.entradas_hash, e.regra_id, e.regra_versao FROM "{esq}".achado a '
                        f'JOIN "{esq}".execucao_regra e ON e.id = a.execucao_regra_id WHERE a.id = %s',
                        (int(ref),)).fetchone()
        if r is None:
            return None
        fatos = [f for (f,) in con.execute(f'SELECT fato FROM "{esq}".achado_evidencia WHERE achado_id = %s '
                                           "ORDER BY ordem", (int(ref),))]
        return {"alvo": alvo, "ref": ref, "estado": r[0], "origem": r[1], "entradas_hash": r[2].strip(),
                "regra_id": r[3], "regra_versao": r[4], "fatos": fatos, "autor": f"regra:{r[3]}"}
    r = con.execute(f'SELECT chave, modelo, laudo FROM "{esq}".laudos_v2 WHERE processo = %s AND vigente',
                    (ref,)).fetchone()
    if r is None:
        return None
    return {"alvo": alvo, "ref": ref, "chave_laudo": r[0], "autor": r[1] or "", "laudo": r[2]}


def motivos(item: dict, limiar: float | None = None) -> dict:
    """Motivos de risco (regra da O6.5) + o sha da entrada. Puro."""
    from compliance_agent.llm import conferencia_risco as CR
    limiar = CR.limiar_valor() if limiar is None else limiar
    if item["alvo"] == "laudo":
        from compliance_agent.aplicacao.estagios import periciar
        m = periciar.motivos_e12(item["laudo"])["motivos"]
        return {"motivos": m, "nao_se_aplica": ["divergencia"], "limiar": limiar,
                "entrada_sha": _sha(VERSAO, "laudo", item["ref"], item["chave_laudo"], limiar)}
    obs = [Decimal(str(f["valor"])) for f in item["fatos"]
           if f.get("papel") == "suporte" and f.get("tipo") == "ob" and f.get("valor") is not None]
    valor = float(sum(obs)) if obs else None
    indicio = item["estado"] == "INDICIO"
    m = CR.motivos_do_item(nivel=1 if indicio else None, baixa=not indicio, valor=valor, valor_aplica=False,
                           divergente=False, limiar=limiar)
    if not m and CR.sorteado(item["origem"]):
        m.append("amostra")
    return {"motivos": m, "nao_se_aplica": ["divergencia", "grave"], "valor_ob_suporte": valor, "limiar": limiar,
            "entrada_sha": _sha(VERSAO, "achado", item["origem"], item["entradas_hash"], item["regra_versao"],
                                item["estado"], limiar)}


def porta_opus(agora: datetime | None = None, *, ritmo=None, escolher=None) -> str | None:
    """Por que a assinatura NÃO confere agora (None = pode). Antes de 28/11/2026 19h (BRT) recusa sem tocar em nada;
    depois, a trava de ritmo e a escolha de executor de `llm/conferencia_executor` (it-campo → VM-2)."""
    if (agora or datetime.now(BRT)) < LIBERADO_EM:
        return f"assinatura contida até {LIBERADO_EM:%d/%m/%Y %Hh} (BRT)"
    from compliance_agent.llm import conferencia_executor as CE
    m = (ritmo or CE.motivo_ritmo)(TAREFA)
    if m:
        return m
    ex, porque = (escolher or CE.escolher)()
    return None if ex else f"nenhum executor da assinatura disponível ({porque})"


def decidir(item: dict, mot: list[str], porta=None) -> tuple[str, str, str]:
    """(decisao, estado, motivo). `porta` só é consultada quando o item precisaria do Opus."""
    from compliance_agent.llm import conferencia_risco as CR
    if not mot:
        return CR.NAO_JULGADO, NAO_JULGADO, CR.ROTULO_NAO_JULGADO
    if "opus" in str(item.get("autor") or "").lower():
        return "fila", ABSTEVE, "autor_e_conferente: o Opus não reconfere o próprio laudo (2º revisor = ouro)"
    p = (porta or porta_opus)()
    return "fila", ABSTEVE, "sem_llm: " + (p or "conferente do motor ainda não ligado (fila conferencia_opus fora "
                                           "do motor)")


# ── estágio ────────────────────────────────────────────────────────────────────────────────────────────────────
def _handler(payload: dict, ctx: Contexto) -> Resultado:
    alvo, ref = alvo_de(payload, ctx)
    esq = esquema_vigente(payload)
    con = conectar(payload)
    try:
        item = ler_item(con, esq, alvo, ref)
        if item is None:
            raise ErroPermanente(f"E12: {alvo} {ref} não existe em {esq}")
        m = motivos(item)
        decisao, estado, motivo = decidir(item, m["motivos"])
        con.execute(DDL.format(e=esq))
        con.execute(f'INSERT INTO "{esq}".conferencia_e12 (chave, entrada_sha, alvo, ref, autor, motivos, decisao, '
                    "estado, motivo, versao) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (chave, entrada_sha) "
                    "DO UPDATE SET estado = EXCLUDED.estado, motivo = EXCLUDED.motivo, em = now()",
                    (ctx.chave, m["entrada_sha"], alvo, ref, item["autor"], json.dumps(m["motivos"]), decisao,
                     estado, motivo, VERSAO))
    finally:
        con.close()
    if motivo.startswith("sem_llm"):
        raise SemCota(f"{ABSTEVE}({motivo}) — {alvo} {ref}, motivos {','.join(m['motivos'])}")
    return Resultado(efeito={"alvo": alvo, "ref": ref, "entrada_sha": m["entrada_sha"], "motivos": m["motivos"],
                             "decisao": decisao, "estado": estado, "motivo": motivo, "esquema": esq})


def _efeito(payload: dict, ctx: Contexto, resultado: Resultado) -> bool:
    ef = resultado.efeito or {}
    alvo, ref = alvo_de(payload, ctx)
    esq = esquema_vigente(payload)
    con = conectar(payload)
    try:
        item = ler_item(con, esq, alvo, ref)
        r = con.execute(f'SELECT motivos, decisao, estado FROM "{esq}".conferencia_e12 WHERE chave = %s AND '
                        "entrada_sha = %s", (ctx.chave, ef.get("entrada_sha"))).fetchone()
    finally:
        con.close()
    if item is None or r is None:
        return False
    m = motivos(item)
    return (m["entrada_sha"] == ef.get("entrada_sha") and list(r[0]) == m["motivos"] and r[2] in ESTADOS
            and (r[1] == "fila") == bool(m["motivos"]) and r[2] == ef.get("estado"))


ESTAGIO = Estagio(handler=_handler, efeito=_efeito, recursos=["llm"], prioridade=30,
                  volta={"nos": ["vm2"]})
