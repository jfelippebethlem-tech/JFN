"""
Scheduler diário de compliance.
Roda automaticamente às 7h: coleta DOERJ, executa regras, gera relatório.

Uso:
    python -m compliance_agent.scheduler         # roda agora e sai
    python -m compliance_agent.scheduler --loop  # fica rodando diariamente
"""

import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from rich.console import Console

from compliance_agent.notifications.telegram import enviar_resumo_diario, enviar_arquivo, BOT_TOKEN
from compliance_agent.reports.pdf import gerar_relatorio_diario
from compliance_agent.collectors.caged import cruzar_folhas_multiplas
from compliance_agent.collectors.tse import cruzar_doacoes_contratos

console = Console()

REPORT_DIR = Path("reports")
REPORT_DIR.mkdir(exist_ok=True)

# Daily execution time: 08:00 (DOERJ is published at 08:00)
HORA_EXECUCAO = int(os.environ.get("SCHEDULER_HORA", "8"))


async def _coletar_doerj_com_extras(session, hoje: date) -> list:
    """Collect today's DOERJ + check for yesterday's extra editions."""
    from compliance_agent.collectors.doerj import DOERJCollector

    collector = DOERJCollector(session)
    publicacoes = []

    # Today's edition
    try:
        pub_hoje = await collector.coletar_hoje()
        publicacoes.extend(pub_hoje)
        console.print(f"    DOERJ hoje ({hoje}): {len(pub_hoje)} publicações")
    except Exception as e:
        console.print(f"    [red]Erro DOERJ hoje: {e}[/red]")

    # Yesterday's extra editions (DOERJ publishes "edições extras" irregularly)
    ontem = hoje - timedelta(days=1)
    try:
        pub_ontem = await collector.coletar_data(ontem)
        extras = [p for p in pub_ontem
                  if isinstance(p, dict) and "extra" in str(p.get("edicao", "")).lower()]
        if extras:
            publicacoes.extend(extras)
            console.print(f"    DOERJ extras ontem ({ontem}): {len(extras)} publicações")
        else:
            console.print(f"    DOERJ ontem ({ontem}): {len(pub_ontem)} pub, nenhuma extra")
    except Exception as e:
        console.print(f"    [yellow]Aviso DOERJ ontem: {e}[/yellow]")

    return publicacoes


async def _coletar_siafe_ob(hoje: date) -> dict:
    """Collect SIAFE2 OB data for today via CDP. Non-fatal on error."""
    from compliance_agent.collectors.siafe_ob import run_daily_collection

    try:
        result = await run_daily_collection(hoje)
        det = result.get("details_collected", 0)
        console.print(
            f"    SIAFE2 OB: {result['records_saved']} OBs salvas "
            f"({result['records_fetched']} coletadas, {det} com detalhe)"
        )
        if result["errors"]:
            console.print(f"    [yellow]SIAFE2 avisos: {result['errors'][:2]}[/yellow]")
        return result
    except Exception as e:
        console.print(f"    [yellow]SIAFE2 OB indisponível (Chrome não aberto?): {e}[/yellow]")
        return {"records_saved": 0, "records_fetched": 0, "details_collected": 0, "errors": [str(e)]}


async def rodar_ciclo_diario():
    """Executa o ciclo completo de coleta e análise do dia."""
    from compliance_agent.database.models import get_session, init_db
    from compliance_agent.rules.engine import MotorCompliance

    hoje = date.today()
    console.print(f"\n[bold yellow]═══ Ciclo Compliance {hoje} ({datetime.now():%H:%M}) ═══[/bold yellow]")

    init_db()
    session = get_session()

    # 1. Coleta DOERJ do dia + edições extras de ontem
    console.print("[cyan]1/5 Coletando DOERJ (hoje + extras de ontem)...[/cyan]")
    publicacoes = await _coletar_doerj_com_extras(session, hoje)

    # 2. Coleta SIAFE2 OB do dia (requer Chrome aberto e logado)
    console.print("[cyan]2/5 Coletando OBs do SIAFE2...[/cyan]")
    siafe_result = await _coletar_siafe_ob(hoje)

    # 3. Cruza folhas múltiplas e doações eleitorais
    console.print("[cyan]3/5 Cruzando folhas múltiplas e doações eleitorais...[/cyan]")
    try:
        suspeitos_folha = await cruzar_folhas_multiplas(session)
        console.print(f"    {len(suspeitos_folha)} suspeitos de múltiplos empregos.")
    except Exception as e:
        console.print(f"    [red]Erro cruzar_folhas_multiplas: {e}[/red]")
        suspeitos_folha = []

    try:
        alertas_doacoes = cruzar_doacoes_contratos(session)
        console.print(f"    {len(alertas_doacoes)} alertas de doação × contrato.")
    except Exception as e:
        console.print(f"    [red]Erro cruzar_doacoes_contratos: {e}[/red]")
        alertas_doacoes = []

    # 4. Executa motor de regras
    console.print("[cyan]4/5 Executando regras de compliance...[/cyan]")
    competencia = hoje.strftime("%Y-%m")
    try:
        motor = MotorCompliance(session)
        alertas = motor.executar_todas_as_regras(competencia=competencia)
        console.print(f"    {len(alertas)} alertas gerados.")
    except Exception as e:
        console.print(f"    [red]Erro compliance: {e}[/red]")
        alertas = []

    # 5. Salva relatório diário JSON e gera PDF
    console.print("[cyan]5/5 Salvando relatório, PDF e notificações Telegram...[/cyan]")
    report = {
        "data": hoje.isoformat(),
        "hora": datetime.now().isoformat(),
        "doerj": {
            "total_publicacoes": len(publicacoes),
            "nomeacoes": sum(1 for p in publicacoes if getattr(p, "tipo_ato", p.get("tipo_ato") if isinstance(p, dict) else "") == "nomeação"),
            "contratos": sum(1 for p in publicacoes if getattr(p, "tipo_ato", p.get("tipo_ato") if isinstance(p, dict) else "") == "contrato"),
            "licitacoes": sum(1 for p in publicacoes if getattr(p, "tipo_ato", p.get("tipo_ato") if isinstance(p, dict) else "") == "licitação"),
        },
        "siafe_ob": {
            "records_fetched": siafe_result.get("records_fetched", 0),
            "records_saved": siafe_result.get("records_saved", 0),
            "errors": siafe_result.get("errors", []),
        },
        "alertas": {
            "total": len(alertas),
            "alta":  sum(1 for a in alertas if a.get("severidade") == "alta"),
            "media": sum(1 for a in alertas if a.get("severidade") == "média"),
            "baixa": sum(1 for a in alertas if a.get("severidade") == "baixa"),
            "por_tipo": {},
        },
        "alertas_detalhe": alertas[:20],
    }
    for a in alertas:
        t = a.get("tipo", "outros")
        report["alertas"]["por_tipo"][t] = report["alertas"]["por_tipo"].get(t, 0) + 1

    report_path = REPORT_DIR / f"compliance_{hoje.isoformat()}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    console.print(f"    Relatório JSON salvo: {report_path}")

    pdf_path = None
    try:
        pdf_path = gerar_relatorio_diario(report, alertas, REPORT_DIR)
        console.print(f"    Relatório PDF salvo: {pdf_path}")
    except Exception as e:
        console.print(f"    [red]Erro ao gerar PDF: {e}[/red]")

    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    if telegram_token:
        try:
            result = await enviar_resumo_diario(report)
            if result.get("ok"):
                console.print("    Resumo diário enviado ao Telegram.")
            else:
                console.print(f"    [yellow]Telegram: {result.get('error', result)}[/yellow]")
        except Exception as e:
            console.print(f"    [red]Erro Telegram resumo: {e}[/red]")

        if pdf_path and Path(pdf_path).exists() and str(pdf_path).endswith(".pdf"):
            try:
                result_pdf = await enviar_arquivo(pdf_path, caption=f"Relatório Compliance {hoje.isoformat()}")
                if result_pdf.get("ok"):
                    console.print("    PDF enviado ao Telegram.")
                else:
                    console.print(f"    [yellow]Telegram PDF: {result_pdf.get('error', result_pdf)}[/yellow]")
            except Exception as e:
                console.print(f"    [red]Erro Telegram PDF: {e}[/red]")
    else:
        console.print("    [dim]TELEGRAM_BOT_TOKEN não configurado — notificações desabilitadas.[/dim]")

    session.close()
    return report


async def loop_diario(hora_execucao: int = HORA_EXECUCAO):
    """Fica em loop, executando o ciclo diário às 08:00 (padrão)."""
    console.print(f"[green]Scheduler iniciado. Execução diária às {hora_execucao:02d}:00.[/green]")
    while True:
        agora = datetime.now()
        if agora.hour == hora_execucao and agora.minute == 0:
            await rodar_ciclo_diario()
            await asyncio.sleep(61)  # evita dupla execução no mesmo minuto
        else:
            prox = agora.replace(hour=hora_execucao, minute=0, second=0, microsecond=0)
            if prox <= agora:
                prox += timedelta(days=1)
            espera = int((prox - agora).total_seconds())
            console.print(
                f"[dim]Próxima execução: {prox:%d/%m %H:%M} "
                f"(em {espera // 3600}h {(espera % 3600) // 60}min)[/dim]"
            )
            await asyncio.sleep(min(espera, 3600))


if __name__ == "__main__":
    if "--loop" in sys.argv:
        from compliance_agent.notifications.telegram import loop_comandos

        async def _loop_completo():
            await asyncio.gather(loop_diario(), loop_comandos())

        asyncio.run(_loop_completo())
    else:
        asyncio.run(rodar_ciclo_diario())
