# -*- coding: utf-8 -*-
"""
pos_sweep_analise — ANÁLISE PÓS-SWEEP automática (disparada pelo supervisor ao concluir os sweeps).
Roda VACUUM + analisa os DADOS coletados (OBs por ano/UG, cobertura SEI, sócios, cruzamento) → salva
relatório em docs/ e AVISA no Telegram com o resumo. Só leitura+VACUUM (seguro). NÃO mexe em código.

As refatorações de código (lock-por-sistema, remover dead-code) são sinalizadas no relatório p/ revisão MANUAL.
Uso: PYTHONPATH=. .venv/bin/python -m tools.pos_sweep_analise
"""
from __future__ import annotations

import sqlite3
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent
_DB = _REPO / "data" / "compliance.db"
CHAT = "45338178"


def _tok() -> str:
    for env in (Path.home() / ".hermes" / ".env", _REPO / ".env"):
        try:
            for ln in env.read_text(encoding="utf-8-sig").splitlines():
                if ln.strip().startswith("TELEGRAM_BOT_TOKEN="):
                    return ln.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            logger.debug("token do bot ilegível no .env")
    return ""


def _tg(texto: str):
    tok = _tok()
    if not tok:
        return
    try:
        data = urllib.parse.urlencode({"chat_id": CHAT, "text": texto}).encode()
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data), timeout=20)
    except Exception:
        pass


def _q(con, sql, p=()):
    try:
        return con.execute(sql, p).fetchall()
    except Exception:
        return []


def analisar() -> dict:
    con = sqlite3.connect(str(_DB))
    try:
        total = _q(con, "SELECT COUNT(*), COALESCE(SUM(valor),0) FROM ob_orcamentaria_siafe")[0]
        por_ano = _q(con, "SELECT exercicio, COUNT(*), COALESCE(SUM(valor),0) FROM ob_orcamentaria_siafe GROUP BY exercicio ORDER BY exercicio")
        com_sei = _q(con, "SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE processo IS NOT NULL AND TRIM(processo)<>''")[0][0]
        ugs = _q(con, "SELECT COUNT(DISTINCT ug_emitente) FROM ob_orcamentaria_siafe")[0][0]
        top_ug = _q(con, "SELECT ug_emitente, COUNT(*) n FROM ob_orcamentaria_siafe GROUP BY ug_emitente ORDER BY n DESC LIMIT 8")
        ob_sei_tfe = _q(con, "SELECT COUNT(*) FROM ordens_bancarias WHERE numero_sei IS NOT NULL AND numero_sei!=''")[0][0]
        socios = _q(con, "SELECT COUNT(DISTINCT cnpj) FROM socios_fornecedor")[0][0]
    finally:
        con.close()
    siafe1 = sum(n for a, n, v in por_ano if a and a <= 2023)
    siafe2 = sum(n for a, n, v in por_ano if a and a >= 2024)
    return {"total": total[0], "valor": total[1], "por_ano": por_ano, "com_sei": com_sei, "ugs": ugs,
            "top_ug": top_ug, "ob_sei_tfe": ob_sei_tfe, "socios": socios, "siafe1": siafe1, "siafe2": siafe2}


def main():
    # 1) VACUUM + checkpoint (recupera espaço do churn de re-ingestão)
    try:
        subprocess.run([str(_REPO / ".venv/bin/python"), "-m", "compliance_agent.manutencao", "--tudo"],
                       cwd=str(_REPO), timeout=1800, capture_output=True)
    except Exception:
        pass
    a = analisar()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    linhas = [f"# Análise pós-sweep — {ts}", "",
              f"- **Total OBs (SIAFE Orçamentária):** {a['total']:,} | R$ {a['valor']:,.2f}",
              f"- **SIAFE 1 (2016–2023):** {a['siafe1']:,} OBs | **SIAFE 2 (2024–2026):** {a['siafe2']:,} OBs",
              f"- **Com nº processo SEI:** {a['com_sei']:,} | **UGs distintas:** {a['ugs']}",
              f"- **OBs (TFE) ligadas a SEI (correlação):** {a['ob_sei_tfe']:,}",
              f"- **CNPJs com sócios/diretores (QSA):** {a['socios']:,}", "",
              "## OBs por ano"]
    for ano, n, v in a["por_ano"]:
        linhas.append(f"- {ano}: {n:,} OBs (R$ {v:,.2f})")
    linhas += ["", "## Top UGs por nº de OBs"]
    for ug, n in a["top_ug"]:
        linhas.append(f"- {ug}: {n:,}")
    linhas += ["", "## TODOs de código (revisão MANUAL — não automatizados)",
               "- Lock por sistema (`siafe_lock_{1,2}.json`).",
               "- Dividir módulos grandes (hermes_goal, inteligencia, telegram, terceirizados).",
               "- Ver docs/ECOSSISTEMA-ANALISE-2026-06-07.md e o TODO do playbook."]
    rel = "\n".join(linhas)
    out = _REPO / "docs" / f"ANALISE-POS-SWEEP-{datetime.now(timezone.utc).strftime('%Y%m%d')}.md"
    try:
        out.write_text(rel, encoding="utf-8")
    except OSError as exc:
        logger.debug("gravação do relatório falhou: %s", exc)
    print(rel, flush=True)
    _tg(f"📊 ANÁLISE PÓS-SWEEP pronta!\n"
        f"Total: {a['total']:,} OBs (R$ {a['valor']/1e9:.2f} bi)\n"
        f"SIAFE 1 (2016-23): {a['siafe1']:,} | SIAFE 2 (2024-26): {a['siafe2']:,}\n"
        f"Com nº SEI: {a['com_sei']:,} | UGs: {a['ugs']} | CNPJs c/ sócios: {a['socios']:,}\n"
        f"OBs TFE ligadas a SEI: {a['ob_sei_tfe']:,}\n"
        f"Relatório: {out.name}. VACUUM feito. TODOs de código aguardam revisão manual.")
    return a


if __name__ == "__main__":
    main()
