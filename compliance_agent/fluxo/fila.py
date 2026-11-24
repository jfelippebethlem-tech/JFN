# -*- coding: utf-8 -*-
"""Fila durável do motor de fluxo (`fluxo.jobs`; plano mestre v2 §3.2/§3.3, O1.8).

Evolução da fila de compliance_agent/evidencias.py (mesmos nomes: estado, prazo, ficha, chave; mesma reserva atômica
`UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED) RETURNING`), com o que faltava para virar o motor único:
prioridade, recursos, backoff, quarentena, efeito conferido e outbox de eventos.

Regras que este módulo garante (e os testes em esquema temporário medem):
  · idempotência pela `chave` (UNIQUE): enfileirar duas vezes não cria dois jobs;
  · reserva concorrente sem duplicar: dois nós nunca recebem o mesmo job;
  · lease (`prazo`) renovado por heartbeat; vencido, o job volta à fila (`recuperar_vencidos`);
  · ficha de posse (fencing): vem de uma sequência GLOBAL a cada reserva; quem tem a ficha velha — ou o lease
    vencido — é recusado ao concluir, falhar ou renovar, e não grava resultado velho por cima do novo;
  · "feito" SÓ com efeito conferido; sem conferência é `falhou_efeito` (contrato de estágio, §3.2);
  · erro transitório volta com backoff exponencial; esgotou `max_tentativas` ou erro permanente ⇒ `quarentena`;
  · eventos do job concluído entram na MESMA transação do "feito" (outbox: nada some entre um e outro).

Todo SQL é sem schema: `conectar` fixa o search_path SÓ no esquema do fluxo (produção `fluxo`; teste, o temporário),
então `jobs` aqui nunca é a `public.jobs` do evidencias.py.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from compliance_agent.evidencias import dsn_vigente
from compliance_agent.fluxo.schema import ESQUEMA_PADRAO, validar_esquema

ENV_ESQUEMA = "JFN_FLUXO_ESQUEMA"       # o supervisor repassa ao filho: handler e supervisor no MESMO esquema
BACKOFF_BASE_S = 30.0
BACKOFF_TETO_S = 3600.0
TERMINAIS = ("feito", "falhou_efeito", "quarentena", "cancelado")


def esquema_vigente() -> str:
    return validar_esquema(os.environ.get(ENV_ESQUEMA) or ESQUEMA_PADRAO)


def conectar(dsn: str | None = None, esquema: str | None = None):
    """Conexão psycopg em autocommit com search_path = só o esquema do fluxo. Sob pytest, `dsn_vigente()` não lê o
    arquivo do banco real: o teste tem de passar o DSN explicitamente."""
    import psycopg
    dsn = dsn or dsn_vigente()
    if not dsn:
        raise RuntimeError("sem DSN do PostgreSQL (JFN_EVIDENCIAS_DSN)")
    con = psycopg.connect(dsn, autocommit=True)
    con.execute(f'SET search_path TO "{validar_esquema(esquema or esquema_vigente())}"')
    return con


@dataclass
class Job:
    id: int
    tipo: str
    chave: str
    ficha: int
    payload: dict
    recursos: list[str]
    tentativas: int
    max_tentativas: int
    correlation_id: str | None = None
    volta: dict | None = None


@dataclass
class Resultado:
    """O que o estágio devolve (contrato §3.2): o efeito declarado, se o supervisor o CONFERIU, e os eventos que
    sujam os estágios seguintes."""
    efeito: dict = field(default_factory=dict)
    efeito_conferido: bool = False
    eventos: list[dict] = field(default_factory=list)


def backoff_s(tentativas: int) -> float:
    """Espera antes da próxima tentativa: 30 s, 60 s, 120 s… até 1 h."""
    return min(BACKOFF_TETO_S, BACKOFF_BASE_S * 2 ** max(0, tentativas - 1))


def enfileirar(con, tipo: str, chave: str, payload: Mapping | None = None, prioridade: int = 100,
               recursos: Iterable[str] | None = None, volta: Mapping | None = None, *, no_preferido: str | None = None,
               correlation_id: str | None = None, max_tentativas: int = 5, atraso_s: float = 0.0,
               reabrir: bool = False) -> int | None:
    """Põe o job na fila. Idempotente pela `chave`: já existindo, não cria outro e devolve None.
    `reabrir=True` (propagação: a fonte sujou de novo) devolve à fila um job JÁ TERMINADO em feito/falhou_efeito,
    zerando as tentativas; job em fila ou reservado fica como está (quem chama decide o que fazer — ver
    planejador.propagar_eventos) e quarentena só sai por gente. `atraso_s` = debounce."""
    recursos = list(recursos) if recursos else ["cpu_leve"]
    conflito = ("DO UPDATE SET estado = 'fila', tentativas = 0, payload = EXCLUDED.payload, "
                "disponivel_em = EXCLUDED.disponivel_em, erro_tipo = NULL, erro_resumo = NULL, efeito = NULL, "
                "dono = NULL, prazo = NULL, concluido_em = NULL, correlation_id = EXCLUDED.correlation_id "
                "WHERE jobs.estado IN ('feito', 'falhou_efeito')") if reabrir else "DO NOTHING"
    r = con.execute(
        "INSERT INTO jobs(tipo, chave, payload, prioridade, recursos, volta, no_preferido, correlation_id, "
        "max_tentativas, disponivel_em) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, "
        f"now() + make_interval(secs => %s)) ON CONFLICT (chave) {conflito} RETURNING id",
        (tipo, chave, json.dumps(dict(payload or {})), prioridade, recursos,
         json.dumps(dict(volta)) if volta is not None else None, no_preferido, correlation_id, max_tentativas,
         float(atraso_s))).fetchone()
    return r[0] if r else None


def estado_de(con, chave: str) -> str | None:
    r = con.execute("SELECT estado FROM jobs WHERE chave = %s", (chave,)).fetchone()
    return r[0] if r else None


def reservar(con, no: str, recursos_livres: Mapping[str, int] | Iterable[str], prazo_s: float = 300.0,
             tipos: Iterable[str] | None = None, *, tetos: Mapping[str, int] | None = None,
             ritmo_bloqueado: Iterable[str] | None = None) -> Job | None:
    """Reserva, numa operação atômica, o job em fila de maior prioridade cujos recursos estão TODOS livres neste nó
    e que passa nas restrições da reserva (O2.2 — o que a sombra de 24/11 mediu que faltava):
      · NÓ (`payload.nos`): restrição dura — só um nó da lista reserva; os de `volta.nos` só quando NENHUM nó da
        lista tem heartbeat nos últimos 5 min (§3.5). Sem `payload.nos`, qualquer nó;
      · TETO por fonte/provedor (`payload.concorrencia` × `tetos`): a etiqueta já com N jobs RESERVADOS no mundo
        todo não reserva mais; `por_fonte:<rotina>` lê o teto de `por_fonte`;
      · RITMO da assinatura: job com `payload.ritmo` na lista `ritmo_bloqueado` fica na fila;
      · MONTANTE (`payload.montante`): espera o derivado a montante que está RODANDO ou PRONTO (elegível há menos de
        ESPERA_MONTANTE_MAX_S) — o que ainda junta eventos, ou está barrado há muito, não segura ninguém.
    A reserva é serializada por advisory lock de transação (senão dois nós contariam o mesmo teto ao mesmo tempo).
    Empate de prioridade: o job que prefere este nó vem antes; depois o mais antigo."""
    if isinstance(recursos_livres, Mapping):
        livres = sorted(k for k, n in recursos_livres.items() if n > 0)
    else:
        livres = sorted(set(recursos_livres))
    if not livres:
        return None
    params = {"no": no, "prazo": float(prazo_s), "livres": livres, "tetos": json.dumps(dict(tetos or {})),
              "ritmo": sorted(set(ritmo_bloqueado or ())), "sem_hb": NO_SEM_HEARTBEAT_S,
              "espera": ESPERA_MONTANTE_MAX_S, "tipos": list(tipos) if tipos is not None else None}
    with con.transaction():
        con.execute("SELECT pg_advisory_xact_lock(%s)", (CHAVE_RESERVA,))
        r = con.execute(_SQL_RESERVAR, params).fetchone()
    return Job(*r) if r else None


NO_SEM_HEARTBEAT_S = 300            # = planejador.NO_SEM_HEARTBEAT_S (§3.5)
ESPERA_MONTANTE_MAX_S = 1800        # montante elegível há mais que isto está barrado por fora: não segura o dependente
CHAVE_RESERVA = 4243                # advisory lock da reserva (≠ 42 da liderança)
_SQL_RESERVAR = """
UPDATE jobs SET estado = 'reservado', dono = %(no)s, ficha = nextval('fichas'), tentativas = tentativas + 1,
       prazo = now() + make_interval(secs => %(prazo)s), heartbeat_em = now(), iniciado_em = now()
WHERE id = (
  SELECT j.id FROM jobs j
  WHERE j.estado = 'fila' AND j.disponivel_em <= now() AND j.recursos <@ %(livres)s::text[]
    AND (%(tipos)s::text[] IS NULL OR j.tipo = ANY(%(tipos)s::text[]))
    AND (NOT (j.payload ? 'nos') OR j.payload->'nos' ? %(no)s
         OR (coalesce(j.volta->'nos' ? %(no)s, false)
             AND NOT EXISTS (SELECT 1 FROM nos x WHERE x.heartbeat_em > now() - make_interval(secs => %(sem_hb)s)
                             AND j.payload->'nos' ? x.no)))
    AND NOT (j.payload ? 'ritmo' AND j.payload->>'ritmo' = ANY(%(ritmo)s::text[]))
    AND NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements_text(coalesce(j.payload->'concorrencia', '[]'::jsonb)) t(tag)
      WHERE (SELECT count(*) FROM jobs r WHERE r.estado = 'reservado' AND r.payload->'concorrencia' ? t.tag)
            >= coalesce((%(tetos)s::jsonb ->> split_part(t.tag, ':', 1))::int, 2147483647))
    AND NOT EXISTS (
      SELECT 1 FROM jobs u
      WHERE j.payload ? 'montante'
        AND u.tipo IN (SELECT jsonb_array_elements_text(j.payload->'montante'))
        AND (u.estado = 'reservado'
             OR (u.estado = 'fila' AND u.disponivel_em <= now()
                 AND u.disponivel_em > now() - make_interval(secs => %(espera)s))))
  ORDER BY j.prioridade, (j.no_preferido IS DISTINCT FROM %(no)s), j.disponivel_em, j.id
  LIMIT 1 FOR UPDATE OF j SKIP LOCKED)
RETURNING id, tipo, chave, ficha, payload, recursos, tentativas, max_tentativas, correlation_id, volta"""


def heartbeat(con, ficha: int, prazo_s: float = 300.0) -> bool:
    """Renova o lease. False = a reserva não é mais desta ficha (venceu e foi recuperada, ou outro nó a tem): o
    supervisor tem de matar o filho — o trabalho dele não vale mais."""
    cur = con.execute("UPDATE jobs SET heartbeat_em = now(), prazo = now() + make_interval(secs => %s) "
                      "WHERE ficha = %s AND estado = 'reservado' AND prazo >= now()", (float(prazo_s), ficha))
    return cur.rowcount == 1


_POSSE = "ficha = %s AND estado = 'reservado' AND prazo >= now()"


def concluir(con, ficha: int, resultado: Resultado) -> str | None:
    """Fecha a reserva vigente: 'feito' SÓ se o efeito foi conferido, senão 'falhou_efeito' (nunca "feito" por
    declaração). Os eventos só são gravados no 'feito', na mesma transação. None = ficha velha/lease vencido:
    recusado, nada é gravado."""
    estado = "feito" if resultado.efeito_conferido else "falhou_efeito"
    with con.transaction():
        r = con.execute(
            f"UPDATE jobs SET estado = %s, efeito = %s, concluido_em = now(), prazo = NULL, "
            f"erro_tipo = CASE WHEN %s::text = 'falhou_efeito' THEN 'efeito' END, "
            f"erro_resumo = CASE WHEN %s::text = 'falhou_efeito' THEN 'efeito declarado não conferido' END "
            f"WHERE {_POSSE} RETURNING chave, correlation_id",
            (estado, json.dumps(resultado.efeito or {}), estado, estado, ficha)).fetchone()
        if r is None:
            return None
        if estado == "feito":
            for ev in resultado.eventos:
                emitir(con, ev["fonte"], ev["tipo"], ev.get("chave", r[0]),
                       {**(ev.get("detalhe") or {}), "correlation_id": r[1]})
    return estado


def falhar(con, ficha: int, erro: str, transitorio: bool = True, erro_tipo: str = "erro") -> str | None:
    """Devolve à fila com backoff exponencial (transitório e com tentativas sobrando) ou manda à quarentena
    (dead-letter). None = recusado (ficha velha)."""
    r = con.execute(
        "UPDATE jobs SET estado = CASE WHEN %s::boolean AND tentativas < max_tentativas THEN 'fila' "
        "ELSE 'quarentena' END, "
        f"disponivel_em = now() + {_BACKOFF_SQL}, prazo = NULL, dono = NULL, erro_tipo = %s, "
        f"erro_resumo = left(%s, 2000) WHERE {_POSSE} RETURNING estado",
        (bool(transitorio), BACKOFF_TETO_S, BACKOFF_BASE_S, erro_tipo, str(erro), ficha)).fetchone()
    return r[0] if r else None


# o mesmo backoff_s() em SQL, sobre as tentativas já gastas (parâmetros: teto, base)
_BACKOFF_SQL = "make_interval(secs => least(%s, %s * power(2, greatest(0, tentativas - 1))))"


def recuperar_vencidos(con) -> int:
    """Reserva com lease vencido (o nó morreu ou travou) volta à fila com backoff — ou à quarentena, se já gastou
    as tentativas. A ficha antiga perde a posse (o estado deixa de ser 'reservado'). Devolve quantos."""
    cur = con.execute(
        "UPDATE jobs SET estado = CASE WHEN tentativas >= max_tentativas THEN 'quarentena' ELSE 'fila' END, "
        "erro_tipo = 'lease_vencido', erro_resumo = 'lease vencido com ' || coalesce(dono, '?'), dono = NULL, "
        f"prazo = NULL, disponivel_em = now() + {_BACKOFF_SQL} WHERE estado = 'reservado' AND prazo < now()",
        (BACKOFF_TETO_S, BACKOFF_BASE_S))
    return cur.rowcount


def emitir(con, fonte: str, tipo: str, chave: str | None = None, detalhe: Mapping | None = None) -> int:
    """Grava um evento no outbox (`eventos`). O planejador o transforma em jobs dos dependentes."""
    return con.execute("INSERT INTO eventos(fonte, tipo, chave, detalhe) VALUES (%s, %s, %s, %s) RETURNING id",
                       (fonte, tipo, chave, json.dumps(dict(detalhe or {})))).fetchone()[0]
