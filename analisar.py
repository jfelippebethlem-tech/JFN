"""
Relatório de auditoria progressiva — mostra tudo que o agente acumulou.

Uso:
    python analisar.py            # resumo do dia atual
    python analisar.py --tudo     # todos os alertas no banco
    python analisar.py --obs      # lista OBs coletadas
    python analisar.py --sessoes  # histórico de coletas
    python analisar.py --rodar    # roda o motor de regras agora e mostra alertas

O banco persiste entre sessões em data/compliance.db.
"""

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Habilita VT100/ANSI no Windows 10+ (CMD e PowerShell)
if sys.platform == "win32":
    os.system("")


def _engine():
    from compliance_agent.database.models import get_engine
    return get_engine()


def _session():
    from compliance_agent.database.models import get_session, init_db
    init_db()
    return get_session()


# ── Cores ANSI simples ────────────────────────────────────────────────────────
R  = "\033[91m"   # vermelho
Y  = "\033[93m"   # amarelo
G  = "\033[92m"   # verde
B  = "\033[96m"   # ciano
W  = "\033[97m"   # branco
DIM = "\033[2m"
BOLD = "\033[1m"
RST = "\033[0m"

SEV_COLOR = {"alta": R, "média": Y, "baixa": DIM}


def hr(char="─", n=72):
    print(char * n)


def cabecalho(titulo: str):
    print(f"\n{BOLD}{B}{'═'*72}{RST}")
    print(f"{BOLD}{B}  {titulo}{RST}")
    print(f"{BOLD}{B}{'═'*72}{RST}\n")


def mostrar_resumo():
    session = _session()
    from compliance_agent.database.models import (
        Alerta, OrdemBancaria, PublicacaoDOERJ, SessaoAuditoria
    )

    cabecalho("Resumo da Auditoria Progressiva")

    # ── Banco de dados ────────────────────────────────────────────────────────
    n_alertas   = session.query(Alerta).count()
    n_obs       = session.query(OrdemBancaria).count()
    n_doerj     = session.query(PublicacaoDOERJ).count()
    n_sessoes   = session.query(SessaoAuditoria).count()

    print(f"  {W}Alertas gerados{RST}      : {BOLD}{n_alertas}{RST}")
    print(f"  {W}OBs coletadas{RST}        : {BOLD}{n_obs}{RST}")
    print(f"  {W}Publicações DOERJ{RST}    : {BOLD}{n_doerj}{RST}")
    print(f"  {W}Sessões de coleta{RST}    : {BOLD}{n_sessoes}{RST}")

    # ── Última coleta ─────────────────────────────────────────────────────────
    ultima = session.query(SessaoAuditoria).order_by(SessaoAuditoria.created_at.desc()).first()
    if ultima:
        print(f"\n  {DIM}Última coleta: {ultima.tipo} em {ultima.data_sessao} "
              f"({ultima.registros} registros, status={ultima.status}){RST}")

    # ── Alertas por severidade ────────────────────────────────────────────────
    print(f"\n  {BOLD}Alertas por severidade:{RST}")
    for sev in ("alta", "média", "baixa"):
        n = session.query(Alerta).filter_by(severidade=sev).count()
        cor = SEV_COLOR.get(sev, W)
        bar = "█" * min(n, 40) + f" {n}"
        print(f"    {cor}{sev:8}{RST} {bar}")

    # ── Top tipos de alerta ───────────────────────────────────────────────────
    from sqlalchemy import func
    tipos = (
        session.query(Alerta.tipo, func.count(Alerta.id).label("n"))
        .group_by(Alerta.tipo)
        .order_by(func.count(Alerta.id).desc())
        .limit(10)
        .all()
    )
    if tipos:
        print(f"\n  {BOLD}Alertas por tipo:{RST}")
        for t in tipos:
            print(f"    {Y}{t.tipo:35}{RST}  {t.n}")

    # ── Alertas alta severidade (últimos 7 dias) ──────────────────────────────
    recentes = (
        session.query(Alerta)
        .filter(
            Alerta.severidade == "alta",
            Alerta.created_at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7),
        )
        .order_by(Alerta.created_at.desc())
        .limit(5)
        .all()
    )
    if recentes:
        print(f"\n  {BOLD}{R}⚠  Alertas ALTOS (últimos 7 dias):{RST}")
        for a in recentes:
            print(f"    {R}•{RST} {a.titulo}")
            print(f"      {DIM}{a.descricao[:120]}...{RST}")

    session.close()


def mostrar_obs(limite: int = 30):
    session = _session()
    from compliance_agent.database.models import OrdemBancaria

    cabecalho(f"Ordens Bancárias coletadas (últimas {limite})")

    obs = (
        session.query(OrdemBancaria)
        .order_by(OrdemBancaria.data_emissao.desc(), OrdemBancaria.id.desc())
        .limit(limite)
        .all()
    )

    if not obs:
        print(f"  {DIM}Nenhuma OB coletada ainda.{RST}")
        print(f"  {DIM}Execute o scheduler (python -m compliance_agent.scheduler){RST}")
        print(f"  {DIM}ou python -m compliance_agent.collectors.siafe_ob{RST}")
        session.close()
        return

    total_valor = sum(ob.valor or 0 for ob in obs)
    print(f"  {DIM}{len(obs)} OBs  |  Total R$ {total_valor:,.2f}{RST}\n")

    fmt = "{:>6}  {:12}  {:>14}  {:30}  {:10}  {}"
    print(f"  {BOLD}" + fmt.format("nº OB", "Data", "Valor (R$)", "Favorecido", "UG", "Status") + RST)
    hr()
    for ob in obs:
        valor_str = f"{ob.valor:>14,.2f}" if ob.valor else "            —"
        fav = (ob.favorecido_nome or ob.favorecido_cpf or "—")[:29]
        status = ob.status or "—"
        cor = R if status in ("cancelada", "anulada") else (G if status == "paga" else W)
        print(f"  {cor}" +
              fmt.format(
                  str(ob.numero_ob or "—")[:6],
                  str(ob.data_emissao or "—"),
                  valor_str,
                  fav,
                  str(ob.ug_codigo or "—"),
                  status,
              ) + RST)

    session.close()


def mostrar_sessoes():
    session = _session()
    from compliance_agent.database.models import SessaoAuditoria

    cabecalho("Histórico de coletas (memória persistente)")

    sessoes = (
        session.query(SessaoAuditoria)
        .order_by(SessaoAuditoria.created_at.desc())
        .limit(40)
        .all()
    )

    if not sessoes:
        print(f"  {DIM}Nenhuma sessão registrada ainda.{RST}")
        session.close()
        return

    fmt = "{:12}  {:15}  {:8}  {:>8}  {}"
    print(f"  {BOLD}" + fmt.format("Data", "Tipo", "Status", "Registros", "Resumo") + RST)
    hr()
    for s in sessoes:
        cor = G if s.status == "ok" else (R if s.status == "erro" else Y)
        resumo_raw = s.resumo or ""
        try:
            r = json.loads(resumo_raw)
            resumo = f"fetched={r.get('records_fetched','?')} saved={r.get('records_saved','?')}"
        except Exception:
            resumo = resumo_raw[:60]
        print(f"  {cor}" +
              fmt.format(
                  str(s.data_sessao),
                  s.tipo or "—",
                  s.status or "—",
                  str(s.registros),
                  resumo,
              ) + RST)

    session.close()


def mostrar_todos_alertas(limite: int = 50):
    session = _session()
    from compliance_agent.database.models import Alerta

    cabecalho(f"Todos os alertas (últimos {limite})")

    alertas = (
        session.query(Alerta)
        .order_by(Alerta.severidade.desc(), Alerta.created_at.desc())
        .limit(limite)
        .all()
    )

    if not alertas:
        print(f"  {DIM}Nenhum alerta gerado ainda. Execute:{RST}")
        print(f"  {DIM}  python analisar.py --rodar{RST}")
        session.close()
        return

    for a in alertas:
        cor = SEV_COLOR.get(a.severidade, W)
        print(f"\n  {BOLD}{cor}[{a.severidade.upper()}]{RST} {BOLD}{a.titulo}{RST}")
        print(f"  {DIM}Tipo: {a.tipo} | ID: {a.id} | {a.created_at:%d/%m/%Y %H:%M}{RST}")
        print(f"  {a.descricao}")
        try:
            ev = json.loads(a.evidencias or "{}")
            if ev:
                print(f"  {DIM}Evidências: {json.dumps(ev, ensure_ascii=False)[:200]}{RST}")
        except Exception:
            pass
        hr("·")

    session.close()


def rodar_regras():
    session = _session()
    from compliance_agent.rules.engine import MotorCompliance

    cabecalho("Executando motor de regras agora")
    competencia = date.today().strftime("%Y-%m")
    print(f"  Competência: {competencia}")
    print(f"  {DIM}Rodando todas as regras...(pode levar alguns segundos){RST}\n")

    motor = MotorCompliance(session)
    try:
        alertas = motor.executar_todas_as_regras(competencia=competencia)
    except Exception as e:
        print(f"  {R}Erro: {e}{RST}")
        session.close()
        return

    if not alertas:
        print(f"  {G}Nenhum alerta novo gerado.{RST}")
    else:
        print(f"  {BOLD}{len(alertas)} alertas novos:{RST}\n")
        for a in alertas:
            cor = SEV_COLOR.get(a.get("severidade",""), W)
            print(f"  {cor}[{a.get('severidade','?').upper()}]{RST} {a.get('titulo','')}")
            print(f"  {DIM}{a.get('descricao','')[:150]}{RST}\n")

    session.close()
    print(f"\n  Execute {B}python analisar.py --tudo{RST} para ver todos os alertas acumulados.")


def mostrar_sancoes():
    """Lista todos os alertas de sanção CEIS/CNEP encontrados."""
    session = _session()
    from compliance_agent.database.models import Alerta

    cabecalho("Alertas de Sanção (CEIS / CNEP / Histórico DOERJ)")

    tipos_sancao = ["empresa_sancionada", "empresa_irregular", "historico_sancao_doerj"]
    alertas = (
        session.query(Alerta)
        .filter(Alerta.tipo.in_(tipos_sancao))
        .order_by(Alerta.created_at.desc())
        .all()
    )

    if not alertas:
        print(f"  {DIM}Nenhuma sanção detectada até o momento.{RST}")
        print(f"  {DIM}Os CSVs do CEIS/CNEP são baixados automaticamente na primeira coleta.{RST}")
        session.close()
        return

    print(f"  {R}{BOLD}{len(alertas)} empresa(s) sancionada(s) detectada(s){RST}\n")
    for a in alertas:
        print(f"  {R}[SANÇÃO]{RST} {a.titulo}")
        print(f"  {DIM}{a.descricao[:200]}{RST}")
        print()

    session.close()


def mostrar_grafo():
    """Mostra os alertas gerados pela análise de grafo de relacionamentos."""
    session = _session()
    from compliance_agent.database.models import Alerta

    cabecalho("Análise de Rede (Grafo de Relacionamentos)")

    tipos_grafo = ["triangulo_nepotismo", "hub_suspeito", "hub_rede", "concentracao_pagamentos"]
    alertas = (
        session.query(Alerta)
        .filter(Alerta.tipo.in_(tipos_grafo))
        .order_by(Alerta.severidade, Alerta.created_at.desc())
        .all()
    )

    if not alertas:
        print(f"  {DIM}Nenhum padrão de rede detectado ainda.{RST}")
        print(f"  {DIM}O grafo cresce conforme mais dados são coletados.{RST}")
        session.close()
        return

    for a in alertas:
        cor = SEV_COLOR.get(a.severidade, W)
        print(f"  {cor}[{a.severidade.upper()}]{RST} {a.titulo}")
        print(f"  {DIM}{a.descricao[:200]}{RST}\n")

    session.close()


def mostrar_top_favorecidos(limite: int = 15):
    """Ranking dos favorecidos que mais receberam em OBs."""
    session = _session()
    from compliance_agent.database.models import OrdemBancaria
    from sqlalchemy import func

    cabecalho(f"Top {limite} Favorecidos por Valor Total de OBs")

    q = (
        session.query(
            OrdemBancaria.favorecido_nome,
            OrdemBancaria.favorecido_cpf,
            func.count(OrdemBancaria.id).label("n_obs"),
            func.sum(OrdemBancaria.valor).label("total"),
            func.count(func.distinct(OrdemBancaria.ug_codigo)).label("n_ugs"),
        )
        .filter(OrdemBancaria.favorecido_nome.isnot(None), OrdemBancaria.valor > 0)
        .group_by(OrdemBancaria.favorecido_cpf)
        .order_by(func.sum(OrdemBancaria.valor).desc())
        .limit(limite)
        .all()
    )

    if not q:
        print(f"  {DIM}Nenhuma OB com favorecido e valor no banco.{RST}")
        session.close()
        return

    total_geral = sum(r.total or 0 for r in q)
    print(f"  {DIM}Total (top {limite}): R$ {total_geral:,.2f}{RST}\n")
    print(f"  {'#':>3}  {'Favorecido':<40} {'OBs':>5}  {'UGs':>4}  {'Total':>15}")
    print(f"  {'─'*3}  {'─'*40} {'─'*5}  {'─'*4}  {'─'*15}")
    for i, r in enumerate(q, 1):
        nome = (r.favorecido_nome or "?")[:40]
        total = r.total or 0
        # Flag se recebe de muitas UGs (hub suspeito)
        flag = f"  {Y}◆ {r.n_ugs} UGs{RST}" if r.n_ugs >= 3 else ""
        print(f"  {i:>3}. {nome:<40} {r.n_obs:>5}  {r.n_ugs:>4}  R$ {total:>12,.2f}{flag}")

    session.close()


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--obs" in args:
        mostrar_obs()
    elif "--sessoes" in args:
        mostrar_sessoes()
    elif "--tudo" in args:
        mostrar_todos_alertas()
    elif "--rodar" in args:
        rodar_regras()
    elif "--sancoes" in args:
        mostrar_sancoes()
    elif "--grafo" in args:
        mostrar_grafo()
    elif "--top" in args:
        mostrar_top_favorecidos()
    else:
        mostrar_resumo()
