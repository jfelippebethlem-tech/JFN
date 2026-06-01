"""
Telegram notification + remote command bot for the compliance system.

Sends daily summaries, urgent alerts, and report files via Telegram Bot API.
Also listens for commands from the phone:
    /status   — situação atual do sistema
    /obs      — últimas OBs coletadas
    /agora    — dispara ciclo de coleta imediatamente
    /relatorio — envia PDF do dia
    /ajuda    — ajuda

Usage (standalone, for testing):
    python -m compliance_agent.notifications.telegram
"""

import asyncio
import os
from datetime import date
from pathlib import Path
from typing import Union

import httpx

_DEFAULT_TOKEN = "8840263255:AAFsNh8nHEZk5xga-TRmLOTduIe_EpUEESQ"
_DEFAULT_CHAT_ID = "45338178"

BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", _DEFAULT_TOKEN)
CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", _DEFAULT_CHAT_ID)

# Chat ID auto-descoberto na primeira mensagem recebida (salvo em memória)
_auto_chat_id: str = ""


def _base_url() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    if not token:
        return ""
    return f"https://api.telegram.org/bot{token}"


def _get_chat_id(override: str = "") -> str:
    """Retorna o chat_id a usar: override > env > auto-descoberto."""
    global _auto_chat_id
    return (
        override
        or os.environ.get("TELEGRAM_CHAT_ID", CHAT_ID)
        or _auto_chat_id
    )


async def enviar_mensagem(
    texto: str,
    chat_id: str = "",
    parse_mode: str = "Markdown",
) -> dict:
    """
    Send a text message to a Telegram chat.

    Args:
        texto:      Message text (Markdown supported).
        chat_id:    Target chat ID. Falls back to TELEGRAM_CHAT_ID env var.
        parse_mode: Telegram parse mode ("Markdown" or "HTML").

    Returns:
        Telegram API response dict.
    """
    target = _get_chat_id(chat_id)
    base = _base_url()
    if not base or not target:
        return {"ok": False, "error": "BOT_TOKEN ou CHAT_ID não configurado"}

    # Telegram Markdown v1 has limits — truncate if too long
    max_len = 4096
    if len(texto) > max_len:
        texto = texto[: max_len - 3] + "..."

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base}/sendMessage",
                json={
                    "chat_id": target,
                    "text": texto,
                    "parse_mode": parse_mode,
                },
            )
            return resp.json()
    except httpx.TimeoutException:
        return {"ok": False, "error": "timeout"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def enviar_arquivo(
    path: Union[str, Path],
    caption: str = "",
    chat_id: str = "",
) -> dict:
    """
    Send a file to a Telegram chat as a document.

    Args:
        path:    Path to the file to send.
        caption: Optional caption text.
        chat_id: Target chat ID. Falls back to TELEGRAM_CHAT_ID env var.

    Returns:
        Telegram API response dict.
    """
    target = _get_chat_id(chat_id)
    base = _base_url()
    if not base or not target:
        return {"ok": False, "error": "BOT_TOKEN ou CHAT_ID não configurado"}

    file_path = Path(path)
    if not file_path.exists():
        return {"ok": False, "error": f"Arquivo não encontrado: {path}"}

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            with open(file_path, "rb") as f:
                resp = await client.post(
                    f"{base}/sendDocument",
                    data={"chat_id": target, "caption": caption[:1024] if caption else ""},
                    files={"document": (file_path.name, f, "application/octet-stream")},
                )
            return resp.json()
    except httpx.TimeoutException:
        return {"ok": False, "error": "timeout ao enviar arquivo"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def enviar_resumo_diario(report: dict) -> dict:
    """
    Send a nicely formatted daily summary report to Telegram.

    Args:
        report: Daily report dict from scheduler (contains doerj and alertas stats).

    Returns:
        Telegram API response dict.
    """
    hoje = report.get("data", str(date.today()))
    doerj = report.get("doerj", {})
    alertas = report.get("alertas", {})

    alta = alertas.get("alta", 0)
    media = alertas.get("media", 0)
    baixa = alertas.get("baixa", 0)
    total_alertas = alertas.get("total", 0)

    # Determine status emoji based on alert severity
    if alta > 0:
        status_emoji = "🔴"
        status_text = "ATENÇÃO ALTA"
    elif media > 0:
        status_emoji = "🟡"
        status_text = "ATENÇÃO MÉDIA"
    else:
        status_emoji = "🟢"
        status_text = "NORMAL"

    # Build message
    linhas = [
        f"{status_emoji} *JFN Compliance — {hoje}*",
        f"Status: *{status_text}*",
        "",
        "*📰 DOERJ do dia:*",
        f"  • Total publicações: {doerj.get('total_publicacoes', 0)}",
        f"  • Nomeações: {doerj.get('nomeacoes', 0)}",
        f"  • Contratos: {doerj.get('contratos', 0)}",
        f"  • Licitações: {doerj.get('licitacoes', 0)}",
        "",
        "*🚨 Alertas gerados:*",
        f"  🔴 Alta severidade: *{alta}*",
        f"  🟡 Média severidade: *{media}*",
        f"  🟢 Baixa severidade: *{baixa}*",
        f"  Total: {total_alertas}",
    ]

    # Top 3 alert titles
    alertas_detalhe = report.get("alertas_detalhe", [])
    alerta_alta = [a for a in alertas_detalhe if a.get("severidade") == "alta"]
    if alerta_alta:
        linhas.append("")
        linhas.append("*🔝 Top alertas (alta):*")
        for a in alerta_alta[:3]:
            titulo = a.get("titulo", "")[:80]
            linhas.append(f"  • {titulo}")

    texto = "\n".join(linhas)
    return await enviar_mensagem(texto)


async def enviar_alerta_urgente(
    titulo: str,
    descricao: str,
    severidade: str = "alta",
) -> dict:
    """
    Send an urgent alert notification to Telegram.

    Args:
        titulo:     Alert title.
        descricao:  Alert description.
        severidade: "alta" or "média".

    Returns:
        Telegram API response dict.
    """
    emoji = "🚨" if severidade == "alta" else "⚠️"
    sev_upper = severidade.upper()

    texto = (
        f"{emoji} *ALERTA {sev_upper}*\n"
        f"\n"
        f"*{titulo[:200]}*\n"
        f"\n"
        f"{descricao[:800]}"
    )
    return await enviar_mensagem(texto)


async def testar_conexao(chat_id: str = "") -> bool:
    """
    Send a test message to verify Telegram bot configuration.

    Returns:
        True if the message was sent successfully.
    """
    resp = await enviar_mensagem(
        "✅ *JFN Compliance* — conexão Telegram OK!",
        chat_id=chat_id,
    )
    return resp.get("ok", False) is True


# ─── Remote command bot ───────────────────────────────────────────────────────

async def obter_atualizacoes(offset: int = 0, timeout: int = 25) -> list:
    """Long-poll Telegram for new updates. Returns list of update dicts."""
    base = _base_url()
    if not base:
        return []
    try:
        async with httpx.AsyncClient(timeout=timeout + 5) as client:
            resp = await client.get(
                f"{base}/getUpdates",
                params={
                    "offset": offset,
                    "timeout": timeout,
                    "allowed_updates": ["message"],
                },
            )
            data = resp.json()
            return data.get("result", []) if data.get("ok") else []
    except Exception:
        return []


async def _status_reply() -> str:
    try:
        from compliance_agent.database.models import (
            get_session, SessaoAuditoria, OrdemBancaria, Alerta
        )
        from sqlalchemy import desc, func
        session = get_session()
        try:
            total_obs = session.query(func.count(OrdemBancaria.id)).scalar() or 0
            total_alertas = session.query(func.count(Alerta.id)).scalar() or 0
            sessoes = (
                session.query(SessaoAuditoria)
                .order_by(desc(SessaoAuditoria.created_at))
                .limit(4)
                .all()
            )
            linhas = [f"*📊 JFN Compliance — Status*\n",
                      f"OBs no banco: *{total_obs}*",
                      f"Alertas totais: *{total_alertas}*"]
            if sessoes:
                linhas.append("\n*Últimas sessões:*")
                for s in sessoes:
                    e = "✅" if s.status == "ok" else ("⚠️" if s.status == "parcial" else "❌")
                    linhas.append(f"  {e} `{s.data_sessao}` [{s.tipo}] {s.registros} reg.")
            return "\n".join(linhas)
        finally:
            session.close()
    except Exception as exc:
        return f"Erro ao ler status: {exc}"


async def _obs_reply() -> str:
    try:
        from compliance_agent.database.models import get_session, OrdemBancaria
        from sqlalchemy import desc
        session = get_session()
        try:
            obs = (
                session.query(OrdemBancaria)
                .order_by(desc(OrdemBancaria.data_emissao), desc(OrdemBancaria.id))
                .limit(10)
                .all()
            )
            if not obs:
                return "Nenhuma OB coletada ainda."
            linhas = [f"*📋 Últimas {len(obs)} OBs:*\n"]
            for ob in obs:
                fav = (ob.favorecido_nome or "sem detalhe")[:35]
                val = f"R$ {ob.valor:,.2f}" if ob.valor else "—"
                linhas.append(f"• `{ob.numero_ob}` {ob.data_emissao} {val}\n  ↳ {fav}")
            return "\n".join(linhas)
        finally:
            session.close()
    except Exception as exc:
        return f"Erro ao ler OBs: {exc}"


_AJUDA = (
    "*🤖 JFN Compliance Bot — Auditoria RJ*\n\n"
    "*Monitoramento:*\n"
    "  /status — situação atual do sistema\n"
    "  /obs — últimas OBs coletadas\n"
    "  /alertas — alertas de alta severidade recentes\n"
    "  /agora — dispara coleta e análise completa agora\n\n"
    "*Relatórios:*\n"
    "  /relatorio — envia PDF do dia\n"
    "  /top — ranking dos maiores favorecidos\n"
    "  /sancoes — verifica CEIS/CNEP agora\n\n"
    "*Busca:*\n"
    "  /buscar NOME — busca empresa/pessoa no banco\n\n"
    "*Ajuda:*\n"
    "  /chrome — como abrir o Chrome no modo correto\n"
    "  /ajuda — esta mensagem"
)


async def _alertas_reply() -> str:
    try:
        from compliance_agent.database.models import get_session, Alerta
        from sqlalchemy import desc
        session = get_session()
        try:
            alertas = (
                session.query(Alerta)
                .filter(Alerta.severidade == "alta")
                .order_by(desc(Alerta.created_at))
                .limit(8)
                .all()
            )
            if not alertas:
                return "Nenhum alerta de alta severidade recente. ✅"
            linhas = [f"*🚨 Alertas de Alta Severidade ({len(alertas)}):*\n"]
            for a in alertas:
                dt = str(a.data_referencia or "")[:10]
                linhas.append(f"🔴 [{dt}] *{a.titulo[:80]}*\n  {(a.descricao or '')[:120]}")
            return "\n\n".join(linhas)
        finally:
            session.close()
    except Exception as exc:
        return f"Erro ao ler alertas: {exc}"


async def _top_reply() -> str:
    try:
        from compliance_agent.database.models import get_session, OrdemBancaria
        import sqlalchemy as sa
        session = get_session()
        try:
            rows = (
                session.query(
                    OrdemBancaria.favorecido_nome,
                    sa.func.sum(OrdemBancaria.valor).label("total"),
                    sa.func.count(OrdemBancaria.id).label("n"),
                )
                .filter(OrdemBancaria.favorecido_nome.isnot(None))
                .group_by(OrdemBancaria.favorecido_nome)
                .order_by(sa.desc("total"))
                .limit(10)
                .all()
            )
            if not rows:
                return "Sem dados de favorecidos no banco ainda."
            linhas = ["*🏆 Top 10 Favorecidos (total histórico):*\n"]
            for i, r in enumerate(rows, 1):
                linhas.append(f"{i}. *{r.favorecido_nome[:40]}*\n   R$ {r.total:,.2f} ({r.n} OBs)")
            return "\n".join(linhas)
        finally:
            session.close()
    except Exception as exc:
        return f"Erro: {exc}"


async def _buscar_reply(termo: str) -> str:
    if not termo.strip():
        return "Use: /buscar NOME DA EMPRESA"
    try:
        from compliance_agent.database.models import get_session, OrdemBancaria, Alerta
        from sqlalchemy import or_
        session = get_session()
        try:
            t = f"%{termo.strip()}%"
            obs = (
                session.query(OrdemBancaria)
                .filter(or_(
                    OrdemBancaria.favorecido_nome.ilike(t),
                    OrdemBancaria.favorecido_cpf.ilike(t),
                ))
                .order_by(OrdemBancaria.data_emissao.desc())
                .limit(5)
                .all()
            )
            alertas = (
                session.query(Alerta)
                .filter(Alerta.titulo.ilike(t))
                .order_by(Alerta.created_at.desc())
                .limit(3)
                .all()
            )
            linhas = [f"*🔍 Busca por: {termo}*\n"]
            if obs:
                linhas.append(f"*OBs encontradas ({len(obs)}):*")
                for ob in obs:
                    v = f"R$ {ob.valor:,.2f}" if ob.valor else "—"
                    linhas.append(f"• `{ob.numero_ob}` {ob.data_emissao} {v}")
            else:
                linhas.append("Nenhuma OB encontrada.")
            if alertas:
                linhas.append(f"\n*Alertas relacionados ({len(alertas)}):*")
                for a in alertas:
                    e = "🔴" if a.severidade == "alta" else "🟡"
                    linhas.append(f"{e} {a.titulo[:80]}")
            return "\n".join(linhas)
        finally:
            session.close()
    except Exception as exc:
        return f"Erro na busca: {exc}"


_CHROME_INSTRUCOES = (
    "*🖥️ Como abrir o Chrome no modo correto:*\n\n"
    "1\\. Feche o Chrome completamente \\(todos os ícones na bandeja\\)\n\n"
    "2\\. Abra o CMD \\(Win\\+R → cmd\\) e cole:\n"
    "`\"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\" "
    "--remote-debugging-port=9222`\n\n"
    "3\\. OU use o atalho `chrome_debug.bat` na pasta do JFN\\.\n\n"
    "4\\. O Chrome vai abrir normalmente — entre no SIAFE2 e faça login\\.\n\n"
    "5\\. Pronto\\! O agente detecta automaticamente\\."
)


async def processar_comando(texto: str, chat_id: str) -> None:
    """Handle a single command sent by the user via Telegram."""
    partes = texto.strip().split(None, 1)
    cmd = partes[0].lower() if partes else ""
    args = partes[1] if len(partes) > 1 else ""

    if cmd in ("/start", "/ajuda", "/help"):
        await enviar_mensagem(_AJUDA, chat_id=chat_id)

    elif cmd == "/status":
        await enviar_mensagem(await _status_reply(), chat_id=chat_id)

    elif cmd == "/obs":
        await enviar_mensagem(await _obs_reply(), chat_id=chat_id)

    elif cmd == "/alertas":
        await enviar_mensagem(await _alertas_reply(), chat_id=chat_id)

    elif cmd == "/top":
        await enviar_mensagem(await _top_reply(), chat_id=chat_id)

    elif cmd == "/buscar":
        await enviar_mensagem(await _buscar_reply(args), chat_id=chat_id)

    elif cmd == "/chrome":
        await enviar_mensagem(_CHROME_INSTRUCOES, chat_id=chat_id, parse_mode="MarkdownV2")

    elif cmd == "/sancoes":
        await enviar_mensagem("⏳ Verificando CEIS/CNEP...", chat_id=chat_id)
        try:
            from compliance_agent.collectors.ceis import atualizar_cache_sancoes
            ok_c, ok_n = await atualizar_cache_sancoes()
            await enviar_mensagem(
                f"CEIS: {'✅' if ok_c else '❌'} | CNEP: {'✅' if ok_n else '❌'}\n"
                "Cache atualizado. Use /agora para cruzar com OBs.",
                chat_id=chat_id,
            )
        except Exception as exc:
            await enviar_mensagem(f"❌ Erro: {exc}", chat_id=chat_id)

    elif cmd == "/agora":
        await enviar_mensagem("⏳ Iniciando ciclo completo...", chat_id=chat_id)
        try:
            from compliance_agent.scheduler import rodar_ciclo_relatorio_diario
            report = await rodar_ciclo_relatorio_diario()
            total = report.get("doerj", {}).get("total_publicacoes", 0)
            obs_salvas = report.get("siafe_ob", {}).get("records_saved", 0)
            n_alertas = report.get("alertas", {}).get("total", 0)
            alta = report.get("alertas", {}).get("alta", 0)
            reply = (
                f"✅ *Ciclo concluído!*\n"
                f"  DOERJ: {total} publicações\n"
                f"  OBs: {obs_salvas}\n"
                f"  Alertas: {n_alertas} ({alta} alta)"
            )
        except Exception as exc:
            reply = f"❌ Erro: {exc}"
        await enviar_mensagem(reply, chat_id=chat_id)

    elif cmd == "/relatorio":
        hoje = date.today().isoformat()
        pdf = Path("reports") / f"compliance_{hoje}.pdf"
        if pdf.exists():
            await enviar_mensagem("📄 Enviando relatório...", chat_id=chat_id)
            await enviar_arquivo(pdf, caption=f"Compliance {hoje}", chat_id=chat_id)
        else:
            await enviar_mensagem(
                f"Relatório de hoje ({hoje}) ainda não gerado. Use /agora para gerar.",
                chat_id=chat_id,
            )

    elif cmd.startswith("/"):
        await enviar_mensagem(
            f"Comando desconhecido: `{cmd}`\nDigite /ajuda para ver os comandos.",
            chat_id=chat_id,
        )


async def loop_comandos():
    """
    Long-poll Telegram for commands in a continuous loop.
    Run this concurrently with loop_diario() via asyncio.gather().

    If TELEGRAM_BOT_TOKEN is not set, returns immediately (no-op).
    """
    if not _base_url():
        return

    offset = 0
    print("[Telegram] Bot de comandos ativo. Aguardando mensagens do celular...")

    global _auto_chat_id
    while True:
        try:
            updates = await obter_atualizacoes(offset=offset, timeout=25)
            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message", {})
                text = msg.get("text", "")
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if chat_id and not _auto_chat_id:
                    _auto_chat_id = chat_id
                    print(f"[Telegram] Chat ID detectado: {chat_id}")
                if text and chat_id:
                    asyncio.create_task(processar_comando(text, chat_id))
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(5)


if __name__ == "__main__":
    async def _test():
        ok = await testar_conexao()
        print(f"Telegram OK: {ok}")
        print("Aguardando comandos (Ctrl+C para parar)...")
        await loop_comandos()
    asyncio.run(_test())
