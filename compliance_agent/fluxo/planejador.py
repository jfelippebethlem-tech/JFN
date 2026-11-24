# -*- coding: utf-8 -*-
"""Planejador embutido do motor de fluxo (plano mestre v2 §3.3): o supervisor que obtém `pg_try_advisory_lock(42)`
vira o planejador — qualquer nó pode ser, a eleição é automática e o lock (de SESSÃO) cai sozinho se o nó morrer.

O planejador:
  (a) materializa a agenda vencida em jobs (cron de 5 campos, hora de Brasília);
  (b) transforma eventos do outbox em jobs dos dependentes, com debounce (o grafo é injetado; ligar ao
      config/propagacao.yaml → config/fluxo.yaml é a O2.1);
  (c) recupera leases vencidos;
  (e) calcula a saúde honesta: SAUDAVEL / DEGRADADO / ATRASADO / BLOQUEADO / INDISPONIVEL.
A prioridade única (§3.7) e o backpressure por fonte (d) entram com o grafo, na O2.

croniter não está no requirements: o parser mínimo daqui cobre o que a casa usa (`*`, `*/n`, `a-b`, `a-b/n`,
listas, dia da semana 0–7) com a regra do Vixie cron — dia do mês e dia da semana restritos juntos valem por OU.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Mapping
from zoneinfo import ZoneInfo

from compliance_agent.fluxo import fila

CHAVE_LIDERANCA = 42
FUSO = ZoneInfo("America/Sao_Paulo")
NO_SEM_HEARTBEAT_S = 300            # §3.5: heartbeat sumido por > 5 min = nó fora
FILA_ATRASADA_S = 900               # job elegível esperando mais que isto = ATRASADO
AGENDA_ATRASADA_S = 600             # horário vencido sem virar job = planejador parado

# grafo de EXEMPLO até a O2.1: fonte do evento → estágios que ela suja (com debounce em segundos)
GRAFO_EXEMPLO: dict[str, list[dict]] = {"teste:origem": [{"tipo": "eco", "debounce_s": 0}]}


# ── cron mínimo ───────────────────────────────────────────────────────────────────────────────────────
_LIMITES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _campo(txt: str, lo: int, hi: int) -> set[int]:
    vals: set[int] = set()
    for parte in txt.split(","):
        faixa, _, passo = parte.partition("/")
        p = int(passo) if passo else 1
        if p < 1:
            raise ValueError(f"passo inválido em {txt!r}")
        if faixa == "*":
            a, b = lo, hi
        elif "-" in faixa:
            a, b = (int(x) for x in faixa.split("-", 1))
        else:
            a = int(faixa)
            b = hi if passo else a
        if not (lo <= a <= b <= hi):
            raise ValueError(f"fora do intervalo {lo}-{hi}: {txt!r}")
        vals.update(range(a, b + 1, p))
    return vals


class Cron:
    """Expressão de 5 campos: minuto hora dia-do-mês mês dia-da-semana."""

    def __init__(self, expr: str):
        partes = expr.split()
        if len(partes) != 5:
            raise ValueError(f"cron precisa de 5 campos: {expr!r}")
        self.expr = expr
        self.min, self.hora, self.dia, self.mes, dsem = (_campo(t, *lim) for t, lim in zip(partes, _LIMITES))
        self.dsem = {d % 7 for d in dsem}                    # 7 = domingo = 0
        self.dia_livre, self.dsem_livre = partes[2] == "*", partes[4] == "*"

    def _dia_casa(self, d: datetime) -> bool:
        if d.month not in self.mes:
            return False
        no_dia = d.day in self.dia
        na_sem = (d.isoweekday() % 7) in self.dsem
        if self.dia_livre or self.dsem_livre:
            return no_dia and na_sem
        return no_dia or na_sem

    def proximo(self, depois: datetime) -> datetime:
        """Primeiro horário ESTRITAMENTE depois de `depois` (aware), no fuso de Brasília."""
        local = depois.astimezone(FUSO).replace(second=0, microsecond=0, tzinfo=None) + timedelta(minutes=1)
        dia = local.replace(hour=0, minute=0)
        for _ in range(366 * 5):
            if self._dia_casa(dia):
                for h in sorted(self.hora):
                    for m in sorted(self.min):
                        cand = dia.replace(hour=h, minute=m)
                        if cand >= local:
                            return cand.replace(tzinfo=FUSO)
            dia += timedelta(days=1)
        raise ValueError(f"cron sem horário em 5 anos: {self.expr!r}")


# ── liderança ─────────────────────────────────────────────────────────────────────────────────────────
def tentar_lideranca(con, chave: int = CHAVE_LIDERANCA) -> bool:
    """Lock de SESSÃO: fica com quem pegou enquanto a conexão viver (o supervisor guarda uma só para isto).
    Chamar de novo na mesma sessão devolve True (reentrante)."""
    return bool(con.execute("SELECT pg_try_advisory_lock(%s)", (chave,)).fetchone()[0])


# ── (a) agenda ────────────────────────────────────────────────────────────────────────────────────────
def materializar_agenda(con, contrato: Mapping[str, Mapping] | None = None) -> int:
    """Horário vencido vira job com chave `<tipo>:agenda:<id>:<horário>` (idempotente: dois planejadores, ou um
    que caiu no meio, não duplicam). Atraso de N horários gera UMA execução, não N (o trabalho é idempotente e
    recupera o estado; rajada de atrasados só congestionaria). Agenda nova (`proximo` NULL) só ganha o horário:
    não dispara no deploy. `contrato` = recursos/prioridade por tipo (do registro de estágios)."""
    contrato = contrato or {}
    n = 0
    with con.transaction():
        linhas = con.execute("SELECT id, cron_expr, proximo, tipo_job, payload, now() FROM agenda WHERE ativo AND "
                             "(proximo IS NULL OR proximo <= now()) FOR UPDATE SKIP LOCKED").fetchall()
        for ag_id, expr, proximo, tipo, payload, agora in linhas:
            if proximo is not None:
                c = contrato.get(tipo, {})
                novo = fila.enfileirar(con, tipo, f"{tipo}:agenda:{ag_id}:{proximo.isoformat()}", payload,
                                       prioridade=c.get("prioridade", 100), recursos=c.get("recursos"),
                                       volta=c.get("volta"), correlation_id=f"agenda:{ag_id}")
                n += novo is not None
            con.execute("UPDATE agenda SET proximo = %s WHERE id = %s", (Cron(expr).proximo(agora), ag_id))
    return n


# ── (b) eventos → dependentes ─────────────────────────────────────────────────────────────────────────
def propagar_eventos(con, grafo: Mapping[str, list], contrato: Mapping[str, Mapping] | None = None,
                     limite: int = 500) -> int:
    """Cada evento pendente suja os estágios que dependem da sua `fonte`: job `<dep>:<chave do evento>` com
    debounce. Vários eventos da mesma chave antes do job rodar viram UM job (a chave junta). Se o dependente estiver
    RODANDO, o evento fica pendente e volta no próximo ciclo — senão a mudança que chegou durante a execução se
    perderia. Devolve quantos eventos foram processados."""
    contrato = contrato or {}
    feitos = 0
    with con.transaction():
        eventos = con.execute("SELECT id, fonte, chave, tipo, detalhe FROM eventos WHERE processado_em IS NULL "
                              "ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED", (limite,)).fetchall()
        for ev_id, fonte, chave, tipo_ev, detalhe in eventos:
            adiar = False
            for dep in grafo.get(fonte, []):
                dep = {"tipo": dep} if isinstance(dep, str) else dep
                c = contrato.get(dep["tipo"], {})
                chave_dep = f"{dep['tipo']}:{chave or fonte}"
                novo = fila.enfileirar(con, dep["tipo"], chave_dep,
                                       {"evento": {"id": ev_id, "fonte": fonte, "tipo": tipo_ev, "chave": chave}},
                                       prioridade=c.get("prioridade", 100), recursos=c.get("recursos"),
                                       volta=c.get("volta"), atraso_s=dep.get("debounce_s", 0), reabrir=True,
                                       correlation_id=(detalhe or {}).get("correlation_id") or f"evento:{ev_id}")
                if novo is None and fila.estado_de(con, chave_dep) == "reservado":
                    adiar = True
            if not adiar:
                con.execute("UPDATE eventos SET processado_em = now() WHERE id = %s", (ev_id,))
                feitos += 1
    return feitos


# ── (e) saúde honesta ─────────────────────────────────────────────────────────────────────────────────
_ORDEM = ("SAUDAVEL", "DEGRADADO", "ATRASADO", "BLOQUEADO", "INDISPONIVEL")


def saude(con, nos_esperados: tuple[str, ...] = ()) -> dict:
    """O pior estado vence. Cada motivo é medido aqui (nada é "SAUDAVEL" por falta de leitura):
    INDISPONIVEL nenhum nó vivo · BLOQUEADO job elegível pedindo recurso que nenhum nó vivo oferece ·
    ATRASADO fila elegível parada há mais de 15 min, ou agenda vencida sem virar job · DEGRADADO nó esperado fora,
    ou quarentena/falhou_efeito nas últimas 24 h."""
    motivos: list[tuple[str, str]] = []
    vivos = {no: slots for no, slots in con.execute(
        "SELECT no, slots FROM nos WHERE heartbeat_em > now() - make_interval(secs => %s)", (NO_SEM_HEARTBEAT_S,))}
    if not vivos:
        motivos.append(("INDISPONIVEL", "nenhum nó com heartbeat nos últimos 5 min"))
    oferta = {r for slots in vivos.values() for r, n in (slots or {}).items() if n and n > 0}
    for tipo, recursos in con.execute("SELECT DISTINCT tipo, recursos FROM jobs WHERE estado = 'fila' AND "
                                      "disponivel_em <= now()"):
        sem = sorted(set(recursos) - oferta)
        if vivos and sem:
            motivos.append(("BLOQUEADO", f"{tipo} pede {','.join(sem)}, que nenhum nó vivo oferece"))
    espera = con.execute("SELECT extract(epoch FROM now() - min(disponivel_em)) FROM jobs WHERE estado = 'fila' "
                         "AND disponivel_em <= now()").fetchone()[0]
    if espera is not None and espera > FILA_ATRASADA_S:
        motivos.append(("ATRASADO", f"fila elegível parada há {int(espera)} s"))
    ag = con.execute("SELECT count(*) FROM agenda WHERE ativo AND proximo < now() - make_interval(secs => %s)",
                     (AGENDA_ATRASADA_S,)).fetchone()[0]
    if ag:
        motivos.append(("ATRASADO", f"{ag} horário(s) da agenda vencido(s) sem virar job"))
    for no in nos_esperados:
        if no not in vivos:
            motivos.append(("DEGRADADO", f"nó {no} sem heartbeat"))
    contagem = dict(con.execute("SELECT estado, count(*) FROM jobs GROUP BY estado").fetchall())
    ruins = con.execute("SELECT count(*) FROM jobs WHERE estado IN ('quarentena', 'falhou_efeito') AND "
                        "coalesce(concluido_em, criado_em) > now() - interval '24 hours'").fetchone()[0]
    if ruins:
        motivos.append(("DEGRADADO", f"{ruins} job(s) em quarentena/falhou_efeito nas últimas 24 h"))
    estado = max((m[0] for m in motivos), key=_ORDEM.index, default="SAUDAVEL")
    return {"estado": estado, "motivos": [f"{e}: {t}" for e, t in motivos], "jobs": contagem,
            "nos_vivos": sorted(vivos)}


def ciclo(con, grafo: Mapping[str, list] | None = None, contrato: Mapping[str, Mapping] | None = None) -> dict:
    """Uma rodada do planejador (só quem tem a liderança chama)."""
    grafo = GRAFO_EXEMPLO if grafo is None else grafo
    r = {"agenda": materializar_agenda(con, contrato), "eventos": propagar_eventos(con, grafo, contrato),
         "recuperados": fila.recuperar_vencidos(con)}
    r["saude"] = saude(con)
    con.execute("INSERT INTO metricas(no, nome, valor, rotulos) VALUES (NULL, 'fluxo_saude', %s, %s)",
                (_ORDEM.index(r["saude"]["estado"]), json.dumps({"estado": r["saude"]["estado"]})))
    return r
