# -*- coding: utf-8 -*-
"""Planejador embutido do motor de fluxo (plano mestre v2 §3.3): o supervisor que obtém `pg_try_advisory_lock(42)`
vira o planejador — qualquer nó pode ser, a eleição é automática e o lock (de SESSÃO) cai sozinho se o nó morrer.

O planejador:
  (a) materializa a agenda vencida em jobs (cron de 5 campos, hora de Brasília);
  (b) transforma eventos do outbox em jobs dos dependentes, com debounce, agrupamento e intervalo mínimo (o grafo
      é injetado: `fluxo.grafo.carregar().grafo_planejador()`/`.contrato()` lê o config/fluxo.yaml — O2.1);
  (c) recupera leases vencidos;
  (e) calcula a saúde honesta: SAUDAVEL / DEGRADADO / ATRASADO / BLOQUEADO / INDISPONIVEL.
A prioridade única (§3.7) e o backpressure por fonte (d) entram com o grafo, na O2.

croniter não está no requirements: o parser mínimo daqui cobre o que a casa usa (`*`, `*/n`, `a-b`, `a-b/n`,
listas, dia da semana 0–7) com a regra do Vixie cron — dia do mês e dia da semana restritos juntos valem por OU.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Mapping
from zoneinfo import ZoneInfo

from compliance_agent.fluxo import fila

CHAVE_LIDERANCA = 42
FUSO = ZoneInfo("America/Sao_Paulo")
NO_SEM_HEARTBEAT_S = fila.NO_SEM_HEARTBEAT_S   # §3.5: heartbeat sumido por > 5 min = nó fora
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
    não dispara no deploy. SEM SOBREPOSIÇÃO (O2.2, como o systemd fazia): se já há job do mesmo tipo em fila ou
    reservado (de outro horário ou de evento), o horário passa sem virar job. `contrato` = recursos/prioridade."""
    contrato = contrato or {}
    n = 0
    with con.transaction():
        linhas = con.execute("SELECT id, cron_expr, proximo, tipo_job, payload, now() FROM agenda WHERE ativo AND "
                             "(proximo IS NULL OR proximo <= now()) FOR UPDATE SKIP LOCKED").fetchall()
        for ag_id, expr, proximo, tipo, payload, agora in linhas:
            # rotina legada: um tipo por rotina (rede fundida: evento e agenda juntos); estágio nativo (E17/E18): o
            # tipo é do estágio, então a sobreposição é por LINHA da agenda (5 rotinas do manter não se barram)
            pend = _pendente(con, tipo) if tipo.startswith("legado:") else _pendente_linha(con, tipo, ag_id)
            if proximo is not None and not pend:
                c = contrato.get(tipo, {})
                novo = fila.enfileirar(con, tipo, f"{tipo}:agenda:{ag_id}:{proximo.isoformat()}", payload,
                                       prioridade=c.get("prioridade", 100), recursos=c.get("recursos"),
                                       volta=c.get("volta"), no_preferido=c.get("no_preferido"),
                                       correlation_id=f"agenda:{ag_id}")
                n += novo is not None
            con.execute("UPDATE agenda SET proximo = %s WHERE id = %s", (Cron(expr).proximo(agora), ag_id))
    return n


def _pendente_linha(con, tipo: str, ag_id: str) -> str | None:
    r = con.execute("SELECT max(estado) FROM jobs WHERE tipo = %s AND chave LIKE %s AND estado IN ('fila', "
                    "'reservado')", (tipo, f"{tipo}:agenda:{ag_id}:%")).fetchone()
    return r[0] if r else None


def _pendente(con, tipo: str) -> str | None:
    """'reservado' / 'fila' se há job deste tipo rodando / esperando (qualquer chave), senão None. Desde a decisão
    D2 do dono (24/11) o ritmo da assinatura vale também para a AGENDA das 4 rotinas fundidas: o job preso no ritmo
    conta como pendente — ignorá-lo (O2.2) faria cada horário enfileirar mais um job preso, que soltariam juntos."""
    r = con.execute("SELECT max(estado) FROM jobs WHERE tipo = %s AND estado IN ('fila', 'reservado')",
                    (tipo,)).fetchone()
    return r[0] if r else None


def sincronizar_agenda(con, linhas: list[Mapping]) -> dict:
    """`fluxo.agenda` ← `grafo.agenda_linhas()`, idempotente. Linha NOVA entra com `ativo = false` (religar é a O9.0,
    uma a uma); linha existente tem cron/tipo/payload atualizados e o `ativo` preservado — cron mudado zera o
    `proximo` (recalcula sem disparar). Linha que saiu do yaml é DESLIGADA, nunca apagada (histórico)."""
    out = {"novas": 0, "atualizadas": 0, "iguais": 0, "desativadas": 0}
    with con.transaction():
        atuais = {i: (c, t, p) for i, c, t, p in con.execute(
            "SELECT id, cron_expr, tipo_job, payload FROM agenda FOR UPDATE")}
        for x in linhas:
            Cron(x["cron_expr"])                                       # cron inválido não entra
            novo = (x["cron_expr"], x["tipo_job"], dict(x.get("payload") or {}))
            if x["id"] not in atuais:
                # estágio JÁ liberado ⇒ a linha nova entra ativa (26/11/2026: rotina criada depois da religação
                # ficava parada para sempre — só a liberação ativava); estágio não liberado segue esperando por ela
                con.execute("INSERT INTO agenda(id, cron_expr, tipo_job, payload, ativo) VALUES (%s, %s, %s, %s, "
                            "EXISTS (SELECT 1 FROM liberacao WHERE estagio = %s))",
                            (x["id"], novo[0], novo[1], json.dumps(novo[2]), str(novo[2].get("estagio") or "")))
                out["novas"] += 1
            elif atuais[x["id"]] == novo:
                out["iguais"] += 1
            else:
                con.execute("UPDATE agenda SET cron_expr = %s, tipo_job = %s, payload = %s, proximo = CASE WHEN "
                            "cron_expr = %s THEN proximo END WHERE id = %s",
                            (novo[0], novo[1], json.dumps(novo[2]), novo[0], x["id"]))
                out["atualizadas"] += 1
        sairam = sorted(set(atuais) - {x["id"] for x in linhas})
        if sairam:
            out["desativadas"] = con.execute("UPDATE agenda SET ativo = false WHERE id = ANY(%s) AND ativo",
                                             (sairam,)).rowcount
    return out


# ── (b) eventos → dependentes ─────────────────────────────────────────────────────────────────────────
_RX_SHA = re.compile(r"^[0-9a-f]{64}$")


def jobs_nativos(dep: Mapping, chave: str | None, detalhe: Mapping | None) -> list[tuple[str, str, dict]]:
    """Evento de estágio nativo → [(tipo do job, chave do job, payload próprio)], pela `forma` da rota
    (config/fluxo.yaml `nativos.rotas`; formas em grafo.RotaNativa). Pura. ValueError = evento malformado (sem a
    chave/detalhe que a forma exige): o planejador o registra como DESCARTADO, visível na saúde."""
    tipo, forma, det, k = dep["tipo"], dep["forma"], dict(detalhe or {}), (chave or "").strip()
    if forma == "agrupado":
        return [(tipo, tipo, {})]
    if forma == "fixo":
        return [(tipo, f"{tipo}:{dep['chave']}", {})]
    if not k:
        raise ValueError(f"evento sem chave para a forma {forma}")
    if forma == "processo":
        p = k.split("|", 1)[0]
        return [(tipo, f"{tipo}:{p}", {"processo": p})]
    if forma == "documento":
        proc, _, doc = k.partition("|")
        sha = str(det.get("sha256") or "").strip().lower()
        if not proc or not doc or not _RX_SHA.match(sha):
            raise ValueError(f"documento sem processo|doc_id ou sha256 válido: {k!r} {sha[:16]!r}")
        return [(tipo, f"{tipo}:{proc}|{doc}|{sha[:16]}", {"processo": proc, "doc_id": doc, "sha256": sha})]
    if forma == "aquisicao":
        aq = str(det.get("aquisicao_id") or "").strip()
        if not aq:
            raise ValueError(f"versao_nova sem aquisicao_id: {k!r}")
        return [(f"expandir:{tipo}", f"expandir:{tipo}:{aq}", {"aquisicao_id": aq, "processo": k})]
    if forma == "unidade":
        return [(tipo, f"{tipo}:{k}:todos", {"unidade": k})]
    if forma == "detectores":
        unidade, _, ex = k.partition(":")
        return [(f"expandir:{tipo}", f"expandir:{tipo}:{k}",
                 {"unidade": unidade, **({"exercicio": ex} if ex and ex != "todos" else {})})]
    if forma == "laudo":
        return [(tipo, f"{tipo}:laudo:{k}", {"alvo": "laudo", "ref": k})]
    if forma in ("achados", "casos"):                 # k = '<detector>:<escopo>' da rodada do E10
        return [(f"expandir:{tipo}", f"expandir:{tipo}:{k}", {"rodada": k})]
    if forma == "citado":                             # `_prof_de` = profundidade do processo que citou (planejador)
        prof = int(det.get("_prof_de") or 0) + 1
        if prof > int(dep["max_profundidade"]):
            raise _Encerrado(f"citado a {prof} saltos de um processo com OB (máximo {dep['max_profundidade']})")
        return [(tipo, f"{tipo}:{k}", {"processo": k, "citado_por": det.get("de"), "profundidade": prof})]
    raise ValueError(f"forma desconhecida: {forma}")


class _Encerrado(Exception):
    """A regra da rota encerra o evento sem job (não é defeito: fica em `detalhe.encerrado`, fora da saúde)."""


def _reaberturas(con, ev_id: int, fonte: str, tipo: str, chave: str | None) -> int:
    """Quantos eventos iguais (fonte, tipo, chave) já foram processados nas últimas 24 h."""
    return con.execute("SELECT count(*) FROM eventos WHERE fonte = %s AND tipo = %s AND chave IS NOT DISTINCT FROM %s "
                       "AND id <> %s AND processado_em > now() - interval '24 hours'",
                       (fonte, tipo, chave, ev_id)).fetchone()[0]


def _consumo(grafo: Mapping[str, list], terminais: Mapping[str, str] | None) -> dict:
    """Os eventos que ESTE grafo consome ou declara terminais: `fontes` (chave legada = fonte inteira) e `pares`
    ('fonte/tipo' das rotas nativas e dos terminais). O resto não é tocado: fica pendente (saúde: BLOQUEADO)."""
    t = terminais or {}
    return {"fontes": sorted({k for k in grafo if "/" not in k} | {k[:-2] for k in t if k.endswith("/*")}),
            "pares": sorted({k for k in grafo if "/" in k} | {k for k in t if not k.endswith("/*")})}


_CONSUMIVEL = "(fonte = ANY(%(fontes)s) OR fonte || '/' || coalesce(tipo, '') = ANY(%(pares)s))"


def propagar_eventos(con, grafo: Mapping[str, list], contrato: Mapping[str, Mapping] | None = None,
                     limite: int = 500, terminais: Mapping[str, str] | None = None) -> int:
    """Cada evento pendente suja os estágios que dependem dele: job `<dep>:<chave do evento>` com debounce. Vários
    eventos da mesma chave antes do job rodar viram UM job (a chave junta). Se o dependente estiver RODANDO, o
    evento fica pendente e volta no próximo ciclo — senão a mudança que chegou durante a execução se perderia.
    Devolve quantos eventos foram processados.

    Quem depende (grafo.grafo_planejador): a FONTE inteira (rotina legada) e/ou o par 'fonte/tipo' (rota de estágio
    nativo, com `forma` — jobs_nativos). Evento sem dependente NÃO é marcado processado (achado 1.1, 25/11): só os
    `terminais` declarados são; os outros nem são lidos aqui (não tomam o `limite`) e a saúde os mostra BLOQUEADO.
    Dependente em quarentena/cancelado (não reabre) ou evento malformado: processado COM `detalhe.descartado`
    (a saúde conta — 1.15).

    Campos do dependente (config/fluxo.yaml via grafo.grafo_planejador): `agrupar` — recálculo da base inteira, UM
    job por tipo (chave = o tipo), qualquer que seja a fonte; e, agrupado, QUALQUER job do tipo em fila (inclusive o
    da agenda: rede fundida) absorve o evento e qualquer um rodando o adia; `intervalo_min_s` — reabre com espera
    até completar o intervalo desde a última execução do TIPO (agenda conta, como a rede contava no despachante);
    `abre_janela` — False quando a fonte é outra rotina: evento de derivado não abre janela de junção (debounce 0,
    regra de propagacao._sujos); `payload` — base do payload do job, a que se soma o `evento`.
    A espera pelo derivado a montante pronto fica na reserva (`payload.montante`, fila.reservar)."""
    contrato = contrato or {}
    feitos = 0
    with con.transaction():
        eventos = con.execute("SELECT id, fonte, chave, tipo, detalhe FROM eventos WHERE processado_em IS NULL AND "
                              f"{_CONSUMIVEL} ORDER BY id LIMIT %(limite)s FOR UPDATE SKIP LOCKED",
                              {**_consumo(grafo, terminais), "limite": limite}).fetchall()
        for ev_id, fonte, chave, tipo_ev, detalhe in eventos:
            adiar, descartes, encerrados = False, [], []
            for dep in list(grafo.get(fonte, [])) + list(grafo.get(f"{fonte}/{tipo_ev}", [])):
                dep = {"tipo": dep} if isinstance(dep, str) else dep
                agrupar = bool(dep.get("agrupar"))
                if dep.get("forma"):
                    det = dict(detalhe or {})
                    if dep.get("max_reaberturas") and _reaberturas(con, ev_id, fonte, tipo_ev, chave) >= \
                            int(dep["max_reaberturas"]):
                        descartes.append(f"{dep['tipo']}: laço — {fonte}/{tipo_ev} {chave} já reabriu "
                                         f"{dep['max_reaberturas']}× em 24 h")
                        continue
                    if dep["forma"] == "citado":
                        r = con.execute("SELECT (payload->>'profundidade')::int FROM jobs WHERE chave = %s",
                                        (f"{dep['tipo']}:{det.get('de')}",)).fetchone()
                        det["_prof_de"] = (r[0] if r else 0) or 0
                    try:
                        alvos = jobs_nativos(dep, chave, det)
                    except _Encerrado as exc:
                        encerrados.append(f"{dep['tipo']}: {exc}")
                        continue
                    except ValueError as exc:
                        descartes.append(f"{dep['tipo']}: {exc}")
                        continue
                else:
                    alvos = [(dep["tipo"], dep["tipo"] if agrupar else f"{dep['tipo']}:{chave or fonte}", {})]
                if agrupar:
                    pend = _pendente(con, dep["tipo"])
                    if pend == "reservado":
                        adiar = True
                        continue
                    if pend == "fila":
                        continue                                    # junta no job que já espera
                for tipo_job, chave_dep, proprio in alvos:
                    c = contrato.get(tipo_job, {})
                    atraso = float(dep.get("debounce_s", 0)) if dep.get("abre_janela", True) else 0.0
                    if dep.get("intervalo_min_s"):
                        ha = con.execute("SELECT extract(epoch FROM now() - max(concluido_em)) FROM jobs WHERE "
                                         + ("tipo = %s" if agrupar else "chave = %s")
                                         + " AND estado IN ('feito', 'falhou_efeito')",
                                         (tipo_job if agrupar else chave_dep,)).fetchone()
                        if ha and ha[0] is not None:
                            atraso = max(atraso, float(dep["intervalo_min_s"]) - float(ha[0]))
                    novo = fila.enfileirar(con, tipo_job, chave_dep,
                                           {**(dep.get("payload") or {}), **proprio,
                                            "evento": {"id": ev_id, "fonte": fonte, "tipo": tipo_ev, "chave": chave}},
                                           prioridade=c.get("prioridade", 100), recursos=c.get("recursos"),
                                           volta=c.get("volta"), no_preferido=c.get("no_preferido"),
                                           atraso_s=atraso, reabrir=True,
                                           correlation_id=(detalhe or {}).get("correlation_id") or f"evento:{ev_id}")
                    if novo is None:
                        est = fila.estado_de(con, chave_dep)
                        if est == "reservado":
                            adiar = True
                        elif est in ("quarentena", "cancelado"):
                            descartes.append(f"{chave_dep} em {est} (não reabre: só por gente)")
            if not adiar:
                marca = {**({"descartado": descartes} if descartes else {}),
                         **({"encerrado": encerrados} if encerrados else {})}
                con.execute("UPDATE eventos SET processado_em = now(), detalhe = coalesce(detalhe, '{}'::jsonb) || "
                            "%s::jsonb WHERE id = %s", (json.dumps(marca), ev_id))
                feitos += 1
    return feitos


# ── (e) saúde honesta ─────────────────────────────────────────────────────────────────────────────────
_ORDEM = ("SAUDAVEL", "DEGRADADO", "ATRASADO", "BLOQUEADO", "INDISPONIVEL")


def saude(con, nos_esperados: tuple[str, ...] = (), grafo: Mapping[str, list] | None = None,
          terminais: Mapping[str, str] | None = None, dividas: Mapping[str, str] | None = None,
          ritmo_bloqueado=None) -> dict:
    """O pior estado vence. Cada motivo é medido aqui (nada é "SAUDAVEL" por falta de leitura):
    INDISPONIVEL nenhum nó vivo · BLOQUEADO job elegível pedindo recurso que nenhum nó vivo oferece, ou evento
    pendente que NINGUÉM consome (só medido com o `grafo`; `dividas` = o motivo declarado no yaml) ·
    ATRASADO fila elegível parada há mais de 15 min, ou agenda vencida sem virar job · DEGRADADO nó esperado fora,
    TODA quarentena aberta, falhou_efeito aberto, ou evento descartado nas últimas 24 h. Job com volta declarada
    (`volta.recursos`) não é BLOQUEADO se a volta tem slot vivo; job segurado pelo ritmo da assinatura
    (`ritmo_bloqueado`) não é ATRASADO — vai em `ritmo_segura`."""
    motivos: list[tuple[str, str]] = []
    vivos = {no: slots for no, slots in con.execute(
        "SELECT no, slots FROM nos WHERE heartbeat_em > now() - make_interval(secs => %s)", (NO_SEM_HEARTBEAT_S,))}
    if not vivos:
        motivos.append(("INDISPONIVEL", "nenhum nó com heartbeat nos últimos 5 min"))
    oferta = {r for slots in vivos.values() for r, n in (slots or {}).items() if n and n > 0}

    def oferta_de(nos) -> set[str]:
        return {r for no in nos or () for r, n in (vivos.get(no) or {}).items() if n and n > 0}
    vistos: set[str] = set()
    for tipo, recursos, volta in con.execute("SELECT DISTINCT tipo, recursos, volta FROM jobs WHERE estado = 'fila' "
                                             "AND disponivel_em <= now() ORDER BY tipo"):
        sem = sorted(set(recursos) - oferta)
        v = volta or {}
        if sem and v.get("recursos") and set(v["recursos"]) <= oferta_de(v.get("nos")):
            sem = []                                           # a volta declarada (GPU → CPU) tem slot vivo
        if vivos and sem and tipo not in vistos:
            vistos.add(tipo)
            motivos.append(("BLOQUEADO", f"{tipo} pede {','.join(sem)}, que nenhum nó vivo oferece"))
    if grafo is not None:
        dividas = dividas or {}
        for fonte, tipo, n in con.execute(
                "SELECT fonte, tipo, count(*) FROM eventos WHERE processado_em IS NULL AND NOT "
                f"{_CONSUMIVEL} GROUP BY 1, 2 ORDER BY 1, 2", _consumo(grafo, terminais)):
            par = f"{fonte}/{tipo}"
            motivos.append(("BLOQUEADO", f"evento sem consumidor: {par} ×{n}"
                            + (f" (dívida declarada: {dividas[par]})" if par in dividas else "")))
    # job segurado pelo ritmo da assinatura (porta fechada) NÃO é fila parada: espera conhecida, contada à parte
    rit = sorted(set(ritmo_bloqueado or ()))
    espera = con.execute("SELECT extract(epoch FROM now() - min(disponivel_em)) FROM jobs WHERE estado = 'fila' "
                         "AND disponivel_em <= now() AND NOT (payload ? 'ritmo' AND payload->>'ritmo' = ANY(%s))",
                         (rit,)).fetchone()[0]
    if espera is not None and espera > FILA_ATRASADA_S:
        motivos.append(("ATRASADO", f"fila elegível parada há {int(espera)} s"))
    segurados = dict(con.execute("SELECT payload->>'ritmo', count(*) FROM jobs WHERE estado = 'fila' AND payload ? "
                                 "'ritmo' AND payload->>'ritmo' = ANY(%s) GROUP BY 1", (rit,)).fetchall())
    ag = con.execute("SELECT count(*) FROM agenda WHERE ativo AND proximo < now() - make_interval(secs => %s)",
                     (AGENDA_ATRASADA_S,)).fetchone()[0]
    if ag:
        motivos.append(("ATRASADO", f"{ag} horário(s) da agenda vencido(s) sem virar job"))
    for no in nos_esperados:
        if no not in vivos:
            motivos.append(("DEGRADADO", f"nó {no} sem heartbeat"))
    contagem = dict(con.execute("SELECT estado, count(*) FROM jobs GROUP BY estado").fetchall())
    if contagem.get("quarentena"):
        motivos.append(("DEGRADADO", f"{contagem['quarentena']} job(s) em quarentena (só sai por gente)"))
    if contagem.get("falhou_efeito"):
        motivos.append(("DEGRADADO", f"{contagem['falhou_efeito']} job(s) em falhou_efeito (tentativas esgotadas)"))
    desc = con.execute("SELECT count(*) FROM eventos WHERE detalhe ? 'descartado' AND processado_em > now() - "
                       "interval '24 hours'").fetchone()[0]
    if desc:
        motivos.append(("DEGRADADO", f"{desc} evento(s) descartado(s) nas últimas 24 h (dependente em "
                                     "quarentena/cancelado, ou evento malformado)"))
    estado = max((m[0] for m in motivos), key=_ORDEM.index, default="SAUDAVEL")
    return {"estado": estado, "motivos": [f"{e}: {t}" for e, t in motivos], "jobs": contagem,
            "nos_vivos": sorted(vivos), "ritmo_segura": segurados}


def ciclo(con, grafo: Mapping[str, list] | None = None, contrato: Mapping[str, Mapping] | None = None,
          terminais: Mapping[str, str] | None = None, nos_esperados: tuple[str, ...] = (),
          dividas: Mapping[str, str] | None = None, ritmo_bloqueado=None) -> dict:
    """Uma rodada do planejador (só quem tem a liderança chama). `nos_esperados` = os nós do yaml (1.15)."""
    grafo = GRAFO_EXEMPLO if grafo is None else grafo
    r = {"agenda": materializar_agenda(con, contrato),
         "eventos": propagar_eventos(con, grafo, contrato, terminais=terminais),
         "recuperados": fila.recuperar_vencidos(con)}
    r["saude"] = saude(con, tuple(nos_esperados), grafo, terminais, dividas, ritmo_bloqueado)
    con.execute("INSERT INTO metricas(no, nome, valor, rotulos) VALUES (NULL, 'fluxo_saude', %s, %s)",
                (_ORDEM.index(r["saude"]["estado"]), json.dumps({"estado": r["saude"]["estado"]})))
    return r


_CHAVES_DO_CONTRATO = ("nos", "timeout_s", "concorrencia", "ritmo", "montante", "estagio")


def reaplicar_contrato(con, g) -> dict[str, int]:
    """O contrato ATUAL do yaml vale para os jobs nativos que ainda esperam ('fila'): recursos, prioridade, volta, nó
    preferido e as chaves de contrato do payload (nos, timeout_s, concorrencia, ritmo, montante). Reservado/feito não
    mudam; o resto do payload (chave do trabalho, evento) fica. Chamada pelo líder na recarga do yaml.
    26/11/2026: 4 mudanças de contrato do E6 no dia não chegavam à fila (payload.nos=['vm2'] congelado). Idempotente."""
    out: dict[str, int] = {}
    for ek, e in g.estagios.items():
        c, base = g.contrato_do_estagio(ek), g.payload_do_estagio(ek)
        n = con.execute(
            "UPDATE jobs SET recursos = %(rec)s, prioridade = %(pr)s, volta = %(volta)s, no_preferido = %(np)s, "
            "payload = (payload - %(chaves)s::text[]) || %(base)s::jsonb "
            "WHERE tipo = %(tipo)s AND estado = 'fila' AND (recursos IS DISTINCT FROM %(rec)s "
            "OR prioridade IS DISTINCT FROM %(pr)s OR volta IS DISTINCT FROM %(volta)s::jsonb "
            "OR no_preferido IS DISTINCT FROM %(np)s "
            "OR (payload - %(chaves)s::text[]) || %(base)s::jsonb IS DISTINCT FROM payload)",
            {"rec": list(c["recursos"]), "pr": c["prioridade"], "volta": json.dumps(c["volta"]) if c["volta"] else None,
             "np": c["no_preferido"], "chaves": list(_CHAVES_DO_CONTRATO), "base": json.dumps(base),
             "tipo": e.tipo}).rowcount
        if n:
            out[e.tipo] = n
    return out
