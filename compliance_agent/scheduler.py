"""
Scheduler de compliance — monitoramento CONTÍNUO.

Arquitetura:
  loop_monitoramento()  — a cada 15 min (7h-20h): coleta OBs novas, analisa,
                          alerta imediatamente via Telegram se algo grave
  loop_relatorio()      — às 08:00: gera PDF + resumo diário completo
  loop_comandos()       — sempre: bot Telegram escuta comandos do celular

Uso:
    python -m compliance_agent.scheduler         # roda ciclo completo agora e sai
    python -m compliance_agent.scheduler --loop  # entra nos 3 loops permanentes
"""

import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from rich.console import Console

from compliance_agent.notifications.telegram import (
    enviar_mensagem, enviar_arquivo, enviar_alerta_urgente, BOT_TOKEN
)
from compliance_agent.reports.pdf import gerar_relatorio_diario

console = Console()

REPORT_DIR = Path("reports")
REPORT_DIR.mkdir(exist_ok=True)

HORA_RELATORIO = int(os.environ.get("SCHEDULER_HORA", "8"))
INTERVALO_MONITORAMENTO = int(os.environ.get("MONITOR_INTERVAL", "900"))  # 15 min

# Memória de OBs já processadas (persiste em memória, reset diário)
_obs_processadas: set[str] = set()
_ultima_data_obs: date | None = None


# ─── Utilidades ───────────────────────────────────────────────────────────────

async def _chrome_disponivel() -> bool:
    """Verifica se o Chrome está acessível na porta 9222."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get("http://127.0.0.1:9222/json/version")
            return r.status_code == 200
    except Exception:
        return False


def _reset_obs_se_novo_dia():
    """Reseta a memória de OBs quando virar o dia."""
    global _obs_processadas, _ultima_data_obs
    hoje = date.today()
    if _ultima_data_obs != hoje:
        _obs_processadas = set()
        _ultima_data_obs = hoje


# ─── Análise completa de cada OB nova ────────────────────────────────────────

async def _analisar_ob_rapida(ob, session) -> list[dict]:
    """
    Análise automática e completa de uma OB nova:
      1. CEIS/CNEP — empresa sancionada?
      2. CNPJ — situação cadastral irregular?
      3. PNCP — contrato publicado?
      4. Fracionamento — múltiplas OBs mesmo favorecido no dia?
      5. OB sem processo SEI e valor alto
      6. Valor redondo suspeito
      7. Fundamentação jurídica automática em todos os alertas
    Retorna lista de alertas (pode estar vazia).
    """
    from compliance_agent.database.models import OrdemBancaria, Alerta
    import re

    alertas = []
    hoje = ob.data_emissao or date.today()
    cpf_cnpj = re.sub(r"\D", "", str(ob.favorecido_cpf or ""))

    # 1. CEIS/CNEP — usa cache local, não faz download
    if cpf_cnpj:
        try:
            from compliance_agent.collectors.ceis import verificar_sancao
            resultado = await verificar_sancao(cpf_cnpj, forcar_update=False)
            if resultado.get("sancionado"):
                titulo = f"[URGENTE] OB {ob.numero_ob} para empresa SANCIONADA: {ob.favorecido_nome}"
                alertas.append({
                    "tipo": "empresa_sancionada",
                    "severidade": "alta",
                    "titulo": titulo[:300],
                    "descricao": (
                        f"R$ {ob.valor:,.2f} para {ob.favorecido_nome} — consta no CEIS/CNEP. "
                        f"Lei 14.133/2021 art. 14, I veda contratação de empresa punida."
                    ),
                })
        except Exception:
            pass

    # 2. CNPJ — situação cadastral
    if len(cpf_cnpj) == 14:
        try:
            from compliance_agent.collectors.web_research import consultar_cnpj
            dados_cnpj = await consultar_cnpj(cpf_cnpj)
            situacao = (dados_cnpj.get("situacao_cadastral") or "").upper()
            if situacao and situacao not in ("ATIVA", ""):
                alertas.append({
                    "tipo": "empresa_irregular",
                    "severidade": "alta",
                    "titulo": f"OB {ob.numero_ob} — CNPJ {situacao}: {ob.favorecido_nome}",
                    "descricao": (
                        f"CNPJ {cpf_cnpj} com situação '{situacao}'. "
                        f"Lei 14.133/2021 art. 68 exige regularidade cadastral. "
                        f"Valor: R$ {ob.valor:,.2f}."
                    ),
                })
            # Empresa muito nova (< 6 meses)?
            data_abertura = dados_cnpj.get("data_inicio_atividade", "")
            if data_abertura:
                try:
                    from datetime import date as _date
                    dt_ab = _date.fromisoformat(data_abertura[:10])
                    if (hoje - dt_ab).days < 180:
                        alertas.append({
                            "tipo": "direcionamento",
                            "severidade": "media",
                            "titulo": f"OB {ob.numero_ob} — empresa com {(hoje-dt_ab).days} dias: {ob.favorecido_nome}",
                            "descricao": (
                                f"Empresa aberta há apenas {(hoje-dt_ab).days} dias "
                                f"recebeu R$ {ob.valor:,.2f}. "
                                f"TCU Acórdão 6.100/2022 elenca empresa nova como indício de fachada."
                            ),
                        })
                except Exception:
                    pass
        except Exception:
            pass

    # 3. Fracionamento — múltiplas OBs para o mesmo favorecido no mesmo dia
    if ob.favorecido_nome:
        try:
            outras = session.query(OrdemBancaria).filter(
                OrdemBancaria.data_emissao == hoje,
                OrdemBancaria.favorecido_nome == ob.favorecido_nome,
                OrdemBancaria.id != ob.id,
            ).count()
            total = session.query(
                __import__("sqlalchemy").func.sum(OrdemBancaria.valor)
            ).filter(
                OrdemBancaria.data_emissao == hoje,
                OrdemBancaria.favorecido_nome == ob.favorecido_nome,
            ).scalar() or 0
            # Limite Lei 14.133/2021 art. 75: R$ 57.208 compras / R$ 114.416 obras
            if outras >= 2 and total and total > 57_208:
                alertas.append({
                    "tipo": "fracionamento",
                    "severidade": "alta",
                    "titulo": f"Fracionamento — {ob.favorecido_nome} ({outras+1} OBs = R$ {total:,.2f})",
                    "descricao": (
                        f"{ob.favorecido_nome} recebeu {outras+1} OBs hoje "
                        f"somando R$ {total:,.2f}, acima do limite de dispensa (R$ 57.208). "
                        f"Lei 14.133/2021 art. 75; TCU Acórdão 1.793/2011-Plenário."
                    ),
                })
        except Exception:
            pass

    # 4. OB sem processo SEI e valor alto
    if not ob.numero_processo and ob.valor and ob.valor > 50_000:
        alertas.append({
            "tipo": "sem_processo",
            "severidade": "media",
            "titulo": f"OB {ob.numero_ob} — R$ {ob.valor:,.2f} sem processo SEI",
            "descricao": (
                f"OB de R$ {ob.valor:,.2f} para {ob.favorecido_nome or 'sem nome'} "
                f"sem processo SEI associado. Lei 4.320/64 art. 58-64 exige empenho "
                f"e liquidação com documentação. TCE-RJ Acórdão 7.801/2023."
            ),
        })

    # 5. PNCP — contrato publicado?
    if ob.numero_processo and len(cpf_cnpj) == 14 and ob.valor and ob.valor > 100_000:
        try:
            from compliance_agent.collectors.pncp import verificar_contrato_pncp
            publicado = await verificar_contrato_pncp(cpf_cnpj, ob.numero_processo)
            if publicado is False:
                alertas.append({
                    "tipo": "sem_publicacao_pncp",
                    "severidade": "media",
                    "titulo": f"OB {ob.numero_ob} — contrato não publicado no PNCP",
                    "descricao": (
                        f"OB de R$ {ob.valor:,.2f} para {ob.favorecido_nome}: "
                        f"contrato não encontrado no PNCP. "
                        f"Lei 14.133/2021 art. 94 §1º; TCU Acórdão 5.782/2023."
                    ),
                })
        except Exception:
            pass

    # 6. Valor redondo suspeito (> R$50k e múltiplo exato de R$10k)
    if ob.valor and ob.valor >= 50_000 and ob.valor % 10_000 == 0:
        alertas.append({
            "tipo": "valor_suspeito",
            "severidade": "baixa",
            "titulo": f"OB {ob.numero_ob} — valor redondo suspeito: R$ {ob.valor:,.2f}",
            "descricao": (
                f"OB com valor exato R$ {ob.valor:,.2f} (múltiplo de R$10k) para "
                f"{ob.favorecido_nome or 'sem nome'}. Valores redondos elevados são "
                f"incomuns na prática e merecem atenção."
            ),
        })

    # Salva alertas novos no banco (com fundamentação jurídica automática)
    for a in alertas:
        existe = session.query(Alerta).filter_by(titulo=a["titulo"]).first()
        if not existe:
            desc = a["descricao"]
            try:
                from compliance_agent.knowledge.base_legal import fundamentacao_texto
                from compliance_agent.knowledge.jurisprudencia import fundamentacao_jurisprudencial
                fund = fundamentacao_texto(a["tipo"], a["titulo"])
                jurisp = fundamentacao_jurisprudencial(a["tipo"], a["titulo"])
                if fund:
                    desc += "\n" + fund
                if jurisp:
                    desc += "\n" + jurisp
            except Exception:
                pass
            session.add(Alerta(
                tipo=a["tipo"],
                severidade=a["severidade"],
                titulo=a["titulo"],
                descricao=desc,
                data_referencia=hoje,
                ordem_bancaria_id=ob.id,
            ))
    session.commit()
    return alertas


async def _ciclo_rapido(session, hoje: date) -> int:
    """
    Analisa OBs novas detectadas desde a última checagem.
    Envia alertas urgentes via Telegram para as de alta severidade.
    Retorna o número de OBs novas processadas.
    """
    from compliance_agent.database.models import OrdemBancaria

    all_obs = session.query(OrdemBancaria).filter(
        OrdemBancaria.data_emissao == hoje
    ).all()

    novas = [ob for ob in all_obs if ob.numero_ob not in _obs_processadas]
    if not novas:
        return 0

    console.print(f"  [cyan]{len(novas)} OB(s) nova(s) detectada(s)[/cyan]")

    alertas_urgentes = []

    # Análise individual de cada OB nova (regras + CEIS + CNPJ + PNCP)
    for ob in novas:
        _obs_processadas.add(ob.numero_ob)
        alertas = await _analisar_ob_rapida(ob, session)
        alertas_urgentes.extend(alertas)

    # Análise de IA em lote quando há 5+ OBs novas (evita chamadas excessivas)
    if len(novas) >= 5:
        try:
            from compliance_agent.llm.groq_agent import analisar_obs_com_groq
            from compliance_agent.database.models import Alerta
            obs_dict = [
                {
                    "numero_ob": o.numero_ob,
                    "data_emissao": str(o.data_emissao),
                    "favorecido_nome": o.favorecido_nome,
                    "favorecido_cpf": o.favorecido_cpf,
                    "valor": o.valor,
                    "numero_processo": o.numero_processo,
                    "ug_codigo": o.ug_codigo,
                }
                for o in novas[:40]
            ]
            resultado_ia = await analisar_obs_com_groq(obs_dict)
            for alerta in resultado_ia.get("alertas", []):
                if alerta.get("severidade") == "alta":
                    existe = session.query(Alerta).filter_by(titulo=alerta["titulo"][:300]).first()
                    if not existe:
                        from compliance_agent.database.models import Alerta as AlertaModel
                        import json
                        session.add(AlertaModel(
                            tipo=alerta.get("tipo", "groq_ob"),
                            severidade="alta",
                            titulo=alerta["titulo"][:300],
                            descricao=alerta.get("descricao", ""),
                            evidencias=json.dumps(alerta.get("evidencias", []), ensure_ascii=False),
                            data_referencia=hoje,
                        ))
                        alertas_urgentes.append(alerta)
            session.commit()
        except Exception as e:
            console.print(f"  [yellow]IA lote: {e}[/yellow]")

    # Envia alertas de alta severidade imediatamente via Telegram
    altas = [a for a in alertas_urgentes if a["severidade"] == "alta"]
    if altas:
        linhas = [f"🚨 *{len(altas)} ALERTA(S) — {datetime.now():%H:%M}*\n"]
        for a in altas[:5]:
            desc = (a.get("descricao") or "")[:200]
            linhas.append(f"🔴 *{a['titulo'][:100]}*\n  {desc}\n")
        await enviar_mensagem("\n".join(linhas))

    return len(novas)


async def _enriquecer_obs_novas(session, hoje: date):
    """Enriquece OBs novas com CNPJ + Querido Diário (assíncrono, não bloqueia)."""
    try:
        from compliance_agent.enrichers.cnpj_enricher import enriquecer_obs_do_dia
        await enriquecer_obs_do_dia(session, hoje)
    except Exception as e:
        console.print(f"  [yellow]CNPJ enricher: {e}[/yellow]")

    try:
        from compliance_agent.collectors.querido_diario import enriquecer_obs_com_historico
        await enriquecer_obs_com_historico(session, hoje)
    except Exception as e:
        console.print(f"  [yellow]Querido Diário: {e}[/yellow]")


# ─── Loops principais ─────────────────────────────────────────────────────────

async def loop_monitoramento():
    """
    Loop CONTÍNUO — roda a cada 15 minutos durante o horário comercial.
    Detecta OBs novas (SIAFE2) e publicações DOERJ novas, analisa e alerta.
    """
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.collectors.siafe_ob import run_daily_collection

    console.print("[green]Monitor iniciado — verificação a cada 15 min (7h-20h).[/green]")
    init_db()

    _doerj_coletado_hoje: set[str] = set()

    while True:
        agora = datetime.now()
        hoje = date.today()
        _reset_obs_se_novo_dia()
        chave_dia = hoje.isoformat()
        if chave_dia not in _doerj_coletado_hoje:
            _doerj_coletado_hoje.clear()

        if 7 <= agora.hour < 20:
            console.print(f"\n[dim]── Monitor {agora:%H:%M} ──[/dim]")
            chrome_ok = await _chrome_disponivel()

            # ── SIAFE2 ────────────────────────────────────────────────────────
            if chrome_ok:
                try:
                    result = await run_daily_collection(hoje, collect_details=True)
                    n = result.get("records_saved", 0)
                    if n:
                        session = get_session()
                        try:
                            novas = await _ciclo_rapido(session, hoje)
                            if novas:
                                asyncio.create_task(_enriquecer_obs_novas(session, hoje))
                            console.print(f"  OBs: {n} no banco | Novas: {novas}")
                        finally:
                            session.close()
                    else:
                        erros = result.get("errors", [])
                        if erros:
                            console.print(f"  [yellow]SIAFE2: {erros[0][:80]}[/yellow]")
                except Exception as e:
                    console.print(f"  [yellow]Erro SIAFE2: {e}[/yellow]")
            else:
                console.print("  [dim]Chrome indisponível — SIAFE2 pulado[/dim]")

            # ── DOERJ — coleta periódica (a cada hora) ────────────────────────
            chave_hora = f"{chave_dia}-{agora.hour}"
            if chave_hora not in _doerj_coletado_hoje:
                try:
                    from compliance_agent.collectors.doerj import DOERJCollector
                    from compliance_agent.database.models import get_session
                    session = get_session()
                    try:
                        pubs = await DOERJCollector(session).coletar_hoje()
                        if pubs:
                            console.print(f"  DOERJ: {len(pubs)} publicações")
                            # Analisa com Groq se tiver publicações novas não analisadas
                            from compliance_agent.llm.groq_agent import analisar_doerj_com_groq
                            pubs_dict = [
                                {"tipo_ato": getattr(p, "tipo_ato", ""),
                                 "orgao": getattr(p, "orgao", ""),
                                 "titulo": getattr(p, "titulo", ""),
                                 "texto": getattr(p, "texto", "")}
                                for p in pubs
                            ] if not isinstance(pubs[0], dict) else pubs
                            result_doerj = await analisar_doerj_com_groq(pubs_dict)
                            n_alts_doerj = len(result_doerj.get("alertas", []))
                            if n_alts_doerj:
                                console.print(f"  [yellow]DOERJ: {n_alts_doerj} alerta(s)[/yellow]")
                    finally:
                        session.close()
                    _doerj_coletado_hoje.add(chave_hora)
                except Exception as e:
                    console.print(f"  [yellow]DOERJ monitor: {e}[/yellow]")

        await asyncio.sleep(INTERVALO_MONITORAMENTO)


async def loop_relatorio(hora_execucao: int = HORA_RELATORIO):
    """
    Loop de relatório — às 08:00 gera o PDF completo e envia via Telegram.
    Também coleta DOERJ, roda anomalias, gráfico, Groq completo.
    """
    console.print(f"[green]Relatório diário agendado para {hora_execucao:02d}:00.[/green]")
    while True:
        agora = datetime.now()
        if agora.hour == hora_execucao and agora.minute == 0:
            await rodar_ciclo_relatorio_diario()
            await asyncio.sleep(61)
        else:
            prox = agora.replace(hour=hora_execucao, minute=0, second=0, microsecond=0)
            if prox <= agora:
                prox += timedelta(days=1)
            espera = int((prox - agora).total_seconds())
            console.print(
                f"[dim]Próximo relatório: {prox:%d/%m %H:%M} "
                f"(em {espera // 3600}h {(espera % 3600) // 60}min)[/dim]"
            )
            await asyncio.sleep(min(espera, 3600))


# ─── Ciclo completo de relatório (8:00) ───────────────────────────────────────

async def rodar_ciclo_relatorio_diario():
    """
    Ciclo completo de análise e relatório — chamado às 08:00.
    Coleta DOERJ, SIAFE2, roda todas as análises, gera PDF e envia ao Telegram.
    """
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.rules.engine import MotorCompliance

    hoje = date.today()
    console.print(f"\n[bold yellow]═══ RELATÓRIO DIÁRIO {hoje} ({datetime.now():%H:%M}) ═══[/bold yellow]")
    init_db()
    session = get_session()

    # 1. DOERJ
    console.print("[cyan]1/6 Coletando DOERJ...[/cyan]")
    publicacoes = []
    try:
        from compliance_agent.collectors.doerj import DOERJCollector
        collector = DOERJCollector(session)
        publicacoes = await collector.coletar_hoje()
        console.print(f"    DOERJ: {len(publicacoes)} publicações")
        ontem = hoje - timedelta(days=1)
        pub_ontem = await collector.coletar_data(ontem)
        extras = [p for p in pub_ontem
                  if isinstance(p, dict) and "extra" in str(p.get("edicao", "")).lower()]
        publicacoes.extend(extras)
    except Exception as e:
        console.print(f"    [red]Erro DOERJ: {e}[/red]")

    # 2. SIAFE2 (se Chrome disponível)
    console.print("[cyan]2/6 Coletando SIAFE2...[/cyan]")
    siafe_result = {"records_saved": 0, "records_fetched": 0, "errors": []}
    if await _chrome_disponivel():
        try:
            from compliance_agent.collectors.siafe_ob import run_daily_collection
            siafe_result = await run_daily_collection(hoje)
            console.print(f"    OBs: {siafe_result['records_saved']} salvas")
        except Exception as e:
            console.print(f"    [yellow]SIAFE2: {e}[/yellow]")
    else:
        console.print("    [yellow]Chrome indisponível — coleta SIAFE2 pulada[/yellow]")

    # 3. Cruzamentos
    console.print("[cyan]3/6 Cruzamentos...[/cyan]")
    try:
        from compliance_agent.collectors.caged import cruzar_folhas_multiplas
        suspeitos = await cruzar_folhas_multiplas(session)
        console.print(f"    {len(suspeitos)} suspeitos de múltiplos empregos.")
    except Exception as e:
        console.print(f"    [yellow]CAGED: {e}[/yellow]")
        suspeitos = []

    try:
        from compliance_agent.collectors.tse import cruzar_doacoes_contratos
        alertas_doacoes = cruzar_doacoes_contratos(session)
        console.print(f"    {len(alertas_doacoes)} alertas doação×contrato.")
    except Exception as e:
        console.print(f"    [yellow]TSE: {e}[/yellow]")
        alertas_doacoes = []

    # 4. Regras + IA
    console.print("[cyan]4/6 Regras de compliance + IA...[/cyan]")
    competencia = hoje.strftime("%Y-%m")
    alertas = []
    try:
        motor = MotorCompliance(session)
        alertas = motor.executar_todas_as_regras(competencia=competencia)
        console.print(f"    {len(alertas)} alertas (regras fixas).")
    except Exception as e:
        console.print(f"    [red]Regras: {e}[/red]")

    try:
        from compliance_agent.llm.groq_agent import rodar_analise_groq
        groq_alertas = await rodar_analise_groq(session)
        console.print(f"    {len(groq_alertas)} alertas Groq.")
        alertas += groq_alertas
    except Exception as e:
        console.print(f"    [yellow]Groq: {e}[/yellow]")

    # 5. Verificações adicionais
    console.print("[cyan]5/6 Verificações CEIS, CNPJ, PNCP, anomalias...[/cyan]")
    try:
        from compliance_agent.collectors.ceis import verificar_obs_contra_sancoes
        sancoes = await verificar_obs_contra_sancoes(session, hoje)
        if sancoes:
            console.print(f"    [red]🚨 {len(sancoes)} pagamento(s) a empresa(s) sancionada(s)![/red]")
    except Exception as e:
        console.print(f"    [yellow]CEIS/CNEP: {e}[/yellow]")

    try:
        from compliance_agent.collectors.pncp import verificar_obs_sem_pncp
        flags_pncp = await verificar_obs_sem_pncp(session, hoje)
        console.print(f"    {len(flags_pncp)} OBs sem contrato no PNCP.")
    except Exception as e:
        console.print(f"    [yellow]PNCP: {e}[/yellow]")

    try:
        from compliance_agent.analysis.anomaly_detector import rodar_deteccao_anomalias
        anomalias = await rodar_deteccao_anomalias(session, hoje)
        console.print(f"    {len(anomalias)} anomalias estatísticas.")
        alertas += anomalias
    except Exception as e:
        console.print(f"    [yellow]Anomalias: {e}[/yellow]")

    try:
        from compliance_agent.analysis.graph_analyzer import rodar_analise_grafo
        grafo_alertas = await rodar_analise_grafo(session)
        console.print(f"    {len(grafo_alertas)} alertas de grafo.")
        alertas += grafo_alertas
    except Exception as e:
        console.print(f"    [yellow]Grafo: {e}[/yellow]")

    # 5c. Investigação na internet dos maiores favorecidos do dia
    console.print("[cyan]5c/6 Investigação web (pessoas/CNPJs)...[/cyan]")
    try:
        from compliance_agent.collectors.web_research import investigar_obs_alto_valor
        web_alertas = await investigar_obs_alto_valor(session, hoje)
        if web_alertas:
            console.print(f"    [red]{len(web_alertas)} alvo(s) com risco na web![/red]")
            alertas += [{"tipo": "investigacao_web", "severidade": "alta",
                         "titulo": f"Risco web: {a['favorecido']}",
                         "descricao": f"Termos: {', '.join(a['riscos'])}"}
                        for a in web_alertas]
        else:
            console.print("    Investigação web: nada relevante.")
    except Exception as e:
        console.print(f"    [yellow]Investigação web: {e}[/yellow]")

    # 5d. Análise de processos SEI vinculados às OBs do dia
    console.print("[cyan]5d/6 Processos SEI vinculados...[/cyan]")
    try:
        from compliance_agent.database.models import OrdemBancaria
        from compliance_agent.collectors.sei_portal import analisar_processo_sei
        obs_com_sei = (
            session.query(OrdemBancaria)
            .filter(OrdemBancaria.data_emissao == hoje,
                    OrdemBancaria.numero_processo.isnot(None))
            .limit(5).all()
        )
        n_sei = 0
        for ob in obs_com_sei:
            try:
                res = await analisar_processo_sei(ob.numero_processo, session)
                if res and not res.get("erro"):
                    n_sei += 1
            except Exception:
                pass
        console.print(f"    {n_sei} processo(s) SEI analisado(s).")
    except Exception as e:
        console.print(f"    [yellow]SEI: {e}[/yellow]")

    # 5b. Reflexão com Hermes-3 — o agente APRENDE com o dia
    console.print("[cyan]5b/6 Reflexão e aprendizado (Hermes-3)...[/cyan]")
    try:
        from compliance_agent.llm.memoria import refletir_com_hermes, garantir_contexto_inicial
        garantir_contexto_inicial(session)
        resumo_dia = (
            f"OBs coletadas: {siafe_result.get('records_saved', 0)}. "
            f"Publicações DOERJ: {len(publicacoes)}. "
            f"Alertas gerados: {len(alertas)}. "
            f"Principais: " + "; ".join(
                a.get("titulo", "")[:80] for a in alertas[:10]
            )
        )
        msg = await refletir_com_hermes(resumo_dia, session)
        if msg:
            console.print(f"    {msg}")
    except Exception as e:
        console.print(f"    [yellow]Reflexão Hermes: {e}[/yellow]")

    # 6. Relatório + Telegram
    console.print("[cyan]6/6 Relatório PDF + Telegram...[/cyan]")
    report = _montar_report(hoje, publicacoes, siafe_result, alertas)
    report_path = REPORT_DIR / f"compliance_{hoje.isoformat()}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    pdf_path = None
    try:
        pdf_path = gerar_relatorio_diario(report, alertas, REPORT_DIR)
        console.print(f"    PDF: {pdf_path}")
    except Exception as e:
        console.print(f"    [red]PDF: {e}[/red]")

    if BOT_TOKEN:
        try:
            from compliance_agent.notifications.telegram import enviar_resumo_diario
            r = await enviar_resumo_diario(report)
            if r.get("ok"):
                console.print("    Resumo Telegram ✓")
            else:
                desc = r.get("description", str(r))
                if "chat not found" in str(desc).lower():
                    console.print("    [bold red]Telegram: chat não encontrado.[/bold red]")
                    console.print("    [yellow]AÇÃO: abra o Telegram e envie /start para o bot.[/yellow]")
                else:
                    console.print(f"    [yellow]Telegram: {desc}[/yellow]")
        except Exception as e:
            console.print(f"    [red]Telegram resumo: {e}[/red]")

        if pdf_path and Path(pdf_path).exists():
            try:
                r2 = await enviar_arquivo(pdf_path, caption=f"Relatório Compliance {hoje.isoformat()}")
                if r2.get("ok"):
                    console.print("    PDF Telegram ✓")
            except Exception as e:
                console.print(f"    [red]PDF Telegram: {e}[/red]")

    session.close()
    return report


def _montar_report(hoje: date, publicacoes: list, siafe_result: dict, alertas: list) -> dict:
    return {
        "data": hoje.isoformat(),
        "hora": datetime.now().isoformat(),
        "doerj": {
            "total_publicacoes": len(publicacoes),
            "nomeacoes": sum(1 for p in publicacoes
                            if getattr(p, "tipo_ato", p.get("tipo_ato") if isinstance(p, dict) else "") == "nomeação"),
            "contratos": sum(1 for p in publicacoes
                             if getattr(p, "tipo_ato", p.get("tipo_ato") if isinstance(p, dict) else "") == "contrato"),
            "licitacoes": sum(1 for p in publicacoes
                              if getattr(p, "tipo_ato", p.get("tipo_ato") if isinstance(p, dict) else "") == "licitação"),
        },
        "siafe_ob": {
            "records_fetched": siafe_result.get("records_fetched", 0),
            "records_saved": siafe_result.get("records_saved", 0),
            "errors": siafe_result.get("errors", []),
        },
        "alertas": {
            "total": len(alertas),
            "alta":  sum(1 for a in alertas if a.get("severidade") == "alta"),
            "media": sum(1 for a in alertas if a.get("severidade") in ("média", "media")),
            "baixa": sum(1 for a in alertas if a.get("severidade") == "baixa"),
            "por_tipo": {},
        },
        "alertas_detalhe": alertas[:20],
    }


# ─── Ciclo único (chamado sem --loop, para testes) ────────────────────────────

async def rodar_ciclo_diario():
    """Chamado sem --loop: roda o ciclo completo uma vez e retorna."""
    return await rodar_ciclo_relatorio_diario()


# ─── Resiliência: cada loop se auto-recupera ──────────────────────────────────

async def loop_atualizacao_juridica():
    """
    Loop semanal — toda segunda-feira às 03:00 busca novos acórdãos no TCU e
    TCE-RJ e salva na memória persistente para enriquecer futuras análises.
    """
    console.print("[green]Loop jurídico ativo — atualiza base de acórdãos toda segunda.[/green]")

    _TEMAS = [
        "fracionamento despesa", "superfaturamento contrato", "dispensa indevida licitação",
        "nepotismo cargo comissionado", "empresa irregular habilitação",
        "pagamento sem processo", "concentração fornecedor", "sobrepreço",
    ]

    while True:
        agora = datetime.now()
        # Roda toda segunda-feira às 03h
        if agora.weekday() == 0 and agora.hour == 3:
            console.print("[cyan]Atualizando jurisprudência online (TCU + TCE-RJ)...[/cyan]")
            try:
                from compliance_agent.collectors.lexml_fetcher import buscar_juridico
                from compliance_agent.llm.memoria import aprender
                from compliance_agent.database.models import get_session

                novos = 0
                session = get_session()
                try:
                    for tema in _TEMAS:
                        try:
                            resultado = await buscar_juridico(tema)
                            for ac in resultado.get("tcu", []) + resultado.get("tce_rj", []):
                                numero = ac.get("numero", "")
                                ementa = ac.get("ementa", "")
                                if numero and ementa:
                                    aprender(
                                        "jurisprudencia", numero,
                                        ementa[:400], fonte="lexml_fetcher",
                                        session=session,
                                    )
                                    novos += 1
                        except Exception:
                            pass
                finally:
                    session.close()

                console.print(f"  Jurisprudência: {novos} entradas salvas na memória.")
                if novos:
                    await enviar_mensagem(
                        f"⚖️ *Base jurídica atualizada*\n"
                        f"{novos} acórdãos novos (TCU + TCE-RJ) salvos na memória.\n"
                        f"Use /lei TERMO para consultar."
                    )
            except Exception as e:
                console.print(f"  [yellow]Atualização jurídica: {e}[/yellow]")

            await asyncio.sleep(3700)  # Pula a hora toda para não re-rodar
        else:
            # Calcula próxima segunda às 03h
            prox = agora.replace(hour=3, minute=0, second=0, microsecond=0)
            dias_ate_segunda = (0 - agora.weekday()) % 7
            if dias_ate_segunda == 0 and agora.hour >= 3:
                dias_ate_segunda = 7
            prox += timedelta(days=dias_ate_segunda)
            espera = int((prox - agora).total_seconds())
            console.print(
                f"[dim]Próxima atualização jurídica: {prox:%d/%m %H:%M} "
                f"(em {espera // 3600}h)[/dim]"
            )
            await asyncio.sleep(min(espera, 3600))


async def _loop_resiliente(nome: str, coro_factory):
    """
    Executa um loop e o reinicia se ele cair, avisando no Telegram.
    Garante que um erro num loop não derrube os outros.
    """
    while True:
        try:
            await coro_factory()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            console.print(f"[red]Loop '{nome}' caiu: {e}. Reiniciando em 30s...[/red]")
            try:
                await enviar_mensagem(
                    f"⚠️ Loop *{nome}* teve um erro e vai reiniciar:\n`{str(e)[:200]}`"
                )
            except Exception:
                pass
            await asyncio.sleep(30)


async def _ping_inicio():
    """Avisa no Telegram que o agente subiu e está vivo."""
    if not BOT_TOKEN:
        return
    try:
        await enviar_mensagem(
            f"🟢 *JFN Agente online* ({datetime.now():%d/%m %H:%M})\n"
            "• SIAFE2 + DOERJ monitorados a cada 15 min\n"
            "• Investigo alvos suspeitos sozinho 24/7\n"
            "• Relatório completo às 08:00\n"
            "• Base legal: Lei 14.133, 8.666, 8.429 + TCU/TCE-RJ\n"
            "Comandos: /ajuda — /lei TERMO — ou pergunte algo."
        )
    except Exception:
        pass


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--loop" in sys.argv:
        from compliance_agent.notifications.telegram import loop_comandos
        from compliance_agent.database.models import init_db
        from compliance_agent.llm.memoria import garantir_contexto_inicial
        from compliance_agent.llm.orquestrador import loop_investigador_autonomo
        from compliance_agent.llm.hermes_agent import loop_hermes_continuo

        async def _loop_completo():
            init_db()
            try:
                garantir_contexto_inicial()
            except Exception:
                pass
            await _ping_inicio()
            await asyncio.gather(
                _loop_resiliente("monitor",      loop_monitoramento),
                _loop_resiliente("relatorio",    loop_relatorio),
                _loop_resiliente("telegram",     loop_comandos),
                _loop_resiliente("investigador", loop_investigador_autonomo),
                _loop_resiliente("juridico",     loop_atualizacao_juridica),
                _loop_resiliente("hermes",       loop_hermes_continuo),
            )

        try:
            asyncio.run(_loop_completo())
        except KeyboardInterrupt:
            console.print("\n[yellow]Agente parado pelo usuário.[/yellow]")
    else:
        asyncio.run(rodar_ciclo_diario())
