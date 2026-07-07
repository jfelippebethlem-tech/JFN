# -*- coding: utf-8 -*-
"""Radar 24/7 — JFN 2.0, Onda 6. Vigilância + fiscalização preventiva.

O sistema avisa ANTES de você perguntar: vigia alvos (CNPJ/UG/nome/objeto) e, em ciclos
periódicos (timer systemd), cruza com PNCP (novas contratações + propostas EM ABERTO com
cláusula restritiva = alerta no prazo de impugnação), direcionamento (Lex) e anomalias em OB.
Dispara alerta no Telegram com o motivo + IDs/links.

Honesto: alerta = indício para apuração (presunção de legitimidade), nunca acusação.
Tudo grátis (PNCP público). Watchlist e alertas persistidos em SQLite (radar_watch/radar_alertas).
"""
from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)
from datetime import datetime
from pathlib import Path

_DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"
_TIPOS = {"cnpj", "ug", "nome", "objeto"}


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(str(_DB))
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS radar_watch (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alvo TEXT NOT NULL, tipo TEXT NOT NULL, ativo INTEGER DEFAULT 1,
            criado_em TEXT, UNIQUE(alvo, tipo));
        CREATE TABLE IF NOT EXISTS radar_alertas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alvo TEXT, tipo TEXT, motivo TEXT, ref TEXT, severidade TEXT,
            criado_em TEXT, UNIQUE(alvo, ref, motivo));
        """
    )
    return con


def vigiar(alvo: str, tipo: str = "cnpj") -> dict:
    """Adiciona um alvo à watchlist. tipo ∈ {cnpj,ug,nome,objeto}. Idempotente."""
    alvo = (alvo or "").strip()
    tipo = (tipo or "cnpj").strip().lower()
    if not alvo:
        return {"ok": False, "erro": "informe o alvo"}
    if tipo not in _TIPOS:
        return {"ok": False, "erro": f"tipo inválido (use {sorted(_TIPOS)})"}
    con = _con()
    try:
        con.execute("INSERT OR IGNORE INTO radar_watch (alvo, tipo, ativo, criado_em) VALUES (?,?,1,?)",
                    (alvo, tipo, datetime.now().isoformat(timespec="seconds")))
        con.commit()
        n = con.execute("SELECT COUNT(*) FROM radar_watch WHERE ativo=1").fetchone()[0]
    finally:
        con.close()
    return {"ok": True, "vigiando": {"alvo": alvo, "tipo": tipo}, "total_watchlist": n}


def parar_de_vigiar(alvo: str, tipo: str = "cnpj") -> dict:
    con = _con()
    try:
        cur = con.execute("UPDATE radar_watch SET ativo=0 WHERE alvo=? AND tipo=?", (alvo, tipo))
        con.commit()
        return {"ok": True, "removidos": cur.rowcount}
    finally:
        con.close()


def listar_watch() -> list[dict]:
    con = _con()
    try:
        return [{"alvo": a, "tipo": t, "desde": c} for a, t, c in con.execute(
            "SELECT alvo, tipo, criado_em FROM radar_watch WHERE ativo=1 ORDER BY criado_em DESC")]
    finally:
        con.close()


def _registrar_alerta(alvo: str, tipo: str, motivo: str, ref: str, severidade: str = "media") -> bool:
    """Grava um alerta (idempotente por alvo+ref+motivo). True se é NOVO."""
    con = _con()
    try:
        cur = con.execute(
            "INSERT OR IGNORE INTO radar_alertas (alvo,tipo,motivo,ref,severidade,criado_em) "
            "VALUES (?,?,?,?,?,?)", (alvo, tipo, motivo, ref, severidade,
                                    datetime.now().isoformat(timespec="seconds")))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def alertas_recentes(limite: int = 20) -> list[dict]:
    con = _con()
    try:
        return [{"alvo": a, "tipo": t, "motivo": m, "ref": r, "severidade": s, "quando": q}
                for a, t, m, r, s, q in con.execute(
                    "SELECT alvo,tipo,motivo,ref,severidade,criado_em FROM radar_alertas "
                    "ORDER BY criado_em DESC LIMIT ?", (limite,))]
    finally:
        con.close()


def status() -> dict:
    """O que o Radar vigia + últimos alertas (para /radar e GET /api/radar/status)."""
    return {"ok": True, "watchlist": listar_watch(), "alertas_recentes": alertas_recentes(),
            "_nota": "Radar 24/7: vigilância preventiva (PNCP/direcionamento/anomalias). Indício, nunca acusação."}


def _avisar_telegram(texto: str) -> None:
    try:
        from compliance_agent.notifications.telegram import enviar_mensagem
        enviar_mensagem(texto)
    except Exception as exc:
        logger.warning("alerta do radar não entregue no Telegram: %s", exc)


async def ciclo(max_por_alvo: int = 5, avisar: bool = True) -> dict:
    """Um ciclo de vigilância sobre a watchlist. Retorna {novos_alertas:[...]}.

    Para cada alvo: (preventivo) editais PNCP em ABERTO com red flag de restrição → alerta no
    prazo; (CNPJ) anomalias em OB. Idempotente: só alerta o que é novo. Bounded por max_por_alvo.
    """
    from compliance_agent.collectors import pncp
    from compliance_agent.lex import analisar_texto_edital

    novos: list[dict] = []
    for w in listar_watch():
        alvo, tipo = w["alvo"], w["tipo"]
        # (1) PNCP — propostas EM ABERTO no RJ (preventivo); filtra por órgão se tipo=ug, senão por objeto/nome
        try:
            ug = alvo if tipo == "ug" else None
            obj = alvo if tipo in ("nome", "objeto") else None
            abertos = await pncp.buscar_contratacoes(uf="RJ", abertos=True, orgao_cnpj=ug, max_paginas=1)
            if obj:
                abertos = [c for c in abertos if obj.lower() in (c.get("objeto") or "").lower()]
            for c in abertos[:max_por_alvo]:
                ref = c.get("id_pncp")
                if not ref:
                    continue
                docs = await pncp.baixar_documentos(ref, max_arquivos=1)
                texto = "\n".join(d.get("texto", "") for d in docs)
                achados = analisar_texto_edital(texto, numero=ref).get("achados", []) if texto else []
                if achados:  # edital aberto COM red flag = alerta no prazo de impugnação
                    rfs = ", ".join(a["rf"] for a in achados)
                    if _registrar_alerta(alvo, tipo, f"Edital ABERTO com red flag ({rfs})", ref, "alta"):
                        item = {"alvo": alvo, "ref": ref, "motivo": f"edital aberto com {rfs}",
                                "encerra": c.get("data_encerramento"), "link": c.get("link")}
                        novos.append(item)
                        if avisar:
                            _avisar_telegram(
                                f"🛰️ *RADAR* — alvo `{alvo}`\nEdital ABERTO com indício de restrição "
                                f"({rfs}). Encerra: {c.get('data_encerramento')}\n{c.get('link') or ref}")
        except Exception as exc:
            logger.warning("varredura PNCP do alvo %s falhou (sem alerta pode ser falso): %s", alvo, exc)
        # (2) Anomalias em OB do CNPJ vigiado
        if tipo == "cnpj":
            try:
                from compliance_agent import anomalias
                rows = anomalias.top_anomalias(3, None, alvo) or []
                for r in rows:
                    ref = str(r.get("numero_ob") or "")
                    if _registrar_alerta(alvo, tipo, "OB anômala (score alto)", ref, "media"):
                        novos.append({"alvo": alvo, "ref": ref, "motivo": "OB anômala",
                                      "valor": r.get("valor"), "score": r.get("score")})
            except Exception as exc:
                logger.warning("anomalias de OB do alvo %s falharam (sem alerta pode ser falso): %s", alvo, exc)
    return {"ok": True, "novos_alertas": novos, "n": len(novos),
            "_nota": "Vigilância preventiva; indício para apuração, nunca acusação."}


if __name__ == "__main__":  # chamado pelo timer systemd jfn-radar (a cada 20 min)
    import asyncio
    import json

    print(json.dumps(asyncio.run(ciclo()), ensure_ascii=False, default=str))
