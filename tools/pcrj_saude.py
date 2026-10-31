# -*- coding: utf-8 -*-
"""Saúde dos pipelines da Prefeitura do Rio — o que está vivo, o que parou, o que fazer.

"Depuração" começa por medir: cada etapa (VM-2 captura → shared-brain → VM-1 ingest → tabelas) tem
aqui contagem, frescor (último registro), erros recentes nos logs e um veredito 🟢/🟡/🔴 com a ação.
Sem isso o defeito clássico da casa se repete: produtor com cron, consumidor sem, e ninguém vê.

    python -m tools.pcrj_saude            # imprime o laudo (md) e grava data/pcrj_saude.json
    python -m tools.pcrj_saude --json     # só o JSON
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PCRJ_DB = RAIZ / "data" / "pcrj.db"
SHARED = Path.home() / "shared-brain"
SAIDA = RAIZ / "data" / "pcrj_saude.json"

# (nome, tabela, coluna de tempo, frescor máximo em horas para 🟢, ação se parado)
ETAPAS_VM1 = [
    ("catálogo SEI (enum → pcrj_processo)", "pcrj_processo", "coletado_em", 48, "VM-2: sei_pcrj_enum.py (passo 4e); VM-1: cron 02:35 pcrj_sei_ingest"),
    ("busca livre (pcrj_sei_busca)", "pcrj_sei_busca", "capturado_em", 72, "VM-2: sei_pcrj_busca.py (passo 4d) — termos em shared-brain/sei_pcrj_busca_termos.txt"),
    ("árvore SEI (pcrj_sei_arvore)", "pcrj_sei_arvore", None, None, "VM-2: sweep (run_sweep.sh) → ingerir_arvore"),
    ("assinaturas SEI (pcrj_sei_assinatura)", "pcrj_sei_assinatura", None, None, "idem árvore; nomes via resolver_assinantes"),
    ("contratos ContasRio (contasrio_contrato)", "contasrio_contrato", "coletado_em", 24 * 8, "VM-2: contasrio_export.py (passo 4a, semanal); VM-1: cron 02:45 contasrio_ingest"),
    ("fiscais ContasRio (contasrio_fiscal)", "contasrio_fiscal", "coletado_em", 24 * 8, "idem, --vista fiscais"),
    ("íntegras CCON (pcrj_processo_doc ccon_*)", "pcrj_processo_doc", "coletado_em", 48, "VM-2: ccon_anexos.py (passo 4c); shared-brain/ccon.db → contasrio_ingest"),
    ("conferência CRC (pcrj_processo_doc sei_conferencia)", "pcrj_processo_doc", "coletado_em", 24 * 8, "VM-1: pcrj_sei_crc_harvest (seg 08:30) → VM-2 sei_pcrj_conferir.py (passo 4b)"),
    ("leitura estruturada (pcrj_doc_campos)", "pcrj_doc_campos", "lido_em", 48, "VM-1: cron 02:55 compliance_agent.pcrj.leitura_campos"),
    ("emergência à incumbente (pcrj_emergencia_sinal)", "pcrj_emergencia_sinal", "gerado_em", 48, "VM-1: cron 03:05 tools.pcrj_emergencia_incumbente"),
    ("OCP R052 compra-teste (pcrj_ocp_sinal)", "pcrj_ocp_sinal", "gerado_em", 48, "VM-1: cron 03:10 tools.pcrj_ocp_redflags"),
    ("requerimentos LAI (data/lai.db)", None, None, None, "aba Prefeitura › LAI ou POST /api/lai/gerar"),
]
LOGS = [
    ("ingest SEI (VM-1)", RAIZ / "data" / "pcrj_sei_ingest.log"),
    ("ingest ContasRio (VM-1)", RAIZ / "data" / "contasrio_ingest.log"),
    ("harvest CRC (VM-1)", RAIZ / "data" / "pcrj_sei_crc_harvest.log"),
]
_RX_TS = re.compile(r"(20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2})")


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    m = _RX_TS.search(str(s))
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1).replace("T", " "), "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _tabela(con, tabela: str, col_tempo: str | None, filtro: str = "") -> dict:
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (tabela,)).fetchone():
        return {"existe": False, "n": 0, "ultimo": None}
    n = con.execute(f"SELECT count(*) FROM {tabela} {filtro}").fetchone()[0]
    ultimo = con.execute(f"SELECT max({col_tempo}) FROM {tabela} {filtro}").fetchone()[0] if col_tempo else None
    return {"existe": True, "n": n, "ultimo": ultimo}


def _busca_completa(con) -> bool:
    """Busca livre 'parada' não é falha quando todos os termos da lista já foram buscados."""
    arq = SHARED / "sei_pcrj_busca_termos.txt"
    if not arq.exists():
        return False
    termos = {ln.split("\t")[0].strip() for ln in arq.read_text(encoding="utf-8").splitlines() if ln.strip()}
    try:
        feitos = {r[0] for r in con.execute("SELECT DISTINCT termo FROM pcrj_sei_busca")}
    except sqlite3.Error:
        return False
    return bool(termos) and len(termos - feitos) <= max(3, len(termos) // 20)


def _veredito(n: int, ultimo: str | None, max_h: int | None) -> tuple[str, str]:
    if not n:
        return "🔴", "vazio"
    if not max_h:
        return "🟢", "ok"
    t = _ts(ultimo)
    if not t:
        return "🟡", "sem carimbo de tempo"
    idade = (datetime.now() - t).total_seconds() / 3600
    if idade <= max_h:
        return "🟢", f"há {idade:.0f} h"
    return ("🟡" if idade <= 2 * max_h else "🔴"), f"parado há {idade / 24:.1f} dias"


def _log(caminho: Path) -> dict:
    if not caminho.exists():
        return {"existe": False}
    try:
        linhas = caminho.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    except OSError:
        return {"existe": False}
    erros = [ln for ln in linhas if re.search(r"Traceback|Error|ERRO|erro", ln)]
    ultimo = None
    for ln in reversed(linhas):
        if _ts(ln):
            ultimo = _ts(ln).strftime("%Y-%m-%d %H:%M")
            break
    return {"existe": True, "linhas": len(linhas), "erros": len(erros), "ultimo_erro": (erros[-1][:160] if erros else None),
            "ultimo": ultimo, "mtime": datetime.fromtimestamp(caminho.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}


def _shared() -> list[dict]:
    saida = []
    for nome in ("sei_pcrj.db", "ccon.db", "sei_pcrj_crc_pares.txt", "sei_pcrj_busca_termos.txt", "sei_pcrj_prioridade.txt"):
        p = SHARED / nome
        if p.exists():
            idade_h = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() / 3600
            saida.append({"arquivo": nome, "mb": round(p.stat().st_size / 1e6, 1), "idade_h": round(idade_h, 1),
                          "grau": "🟢" if idade_h < 36 else ("🟡" if idade_h < 96 else "🔴")})
        else:   # prioridade e termos são opcionais (só existem depois do 1º pedido LAI / 1ª lista): ausência é aviso, não falha
            saida.append({"arquivo": nome, "mb": 0, "idade_h": None,
                          "grau": "🟡" if nome in ("sei_pcrj_prioridade.txt", "sei_pcrj_busca_termos.txt") else "🔴"})
    # listas de entrada (termos, pares, prioridade) são ESTÁTICAS por natureza: envelhecer não é falha
    for s in saida:
        if s["arquivo"].endswith(".txt") and s["grau"] == "🔴" and s["idade_h"] is not None:
            s["grau"] = "🟡"
    return saida


def laudo(db_path=None) -> dict:
    con = sqlite3.connect(f"file:{db_path or PCRJ_DB}?mode=ro", uri=True, timeout=30)
    etapas = []
    try:
        for nome, tabela, col, max_h, acao in ETAPAS_VM1:
            if tabela is None:
                try:
                    from compliance_agent.lai import listar
                    itens = listar(500)
                    n = len(itens)
                    prot = sum(1 for i in itens if i["status"] == "protocolado")
                    venc = sum(1 for i in itens if i.get("vencido"))
                    etapas.append({"etapa": nome, "n": n, "ultimo": (itens[0]["criado_em"] if itens else None),
                                   "grau": "🟢" if not venc else "🔴", "leitura": f"{prot} aguardando, {venc} vencido(s)", "acao": acao})
                except (ImportError, sqlite3.Error, OSError) as e:  # o laudo nunca cai por uma etapa
                    etapas.append({"etapa": nome, "n": 0, "ultimo": None, "grau": "🟡", "leitura": str(e)[:80], "acao": acao})
                continue
            filtro = ""
            if "ccon_*" in nome:
                filtro = "WHERE tipo LIKE 'ccon_%'"
            elif "sei_conferencia" in nome:
                filtro = "WHERE tipo='sei_conferencia'"
            elif tabela == "pcrj_processo":
                filtro = "WHERE sistema='SEI.RIO'"
            t = _tabela(con, tabela, col, filtro)
            grau, leitura = _veredito(t["n"], t["ultimo"], max_h)
            if tabela == "pcrj_sei_busca" and grau != "🔴" and _busca_completa(con):
                grau, leitura = "🟢", f"completa (todos os termos buscados; {leitura})"
            etapas.append({"etapa": nome, "n": t["n"], "ultimo": t["ultimo"], "grau": grau, "leitura": leitura, "acao": acao})
        extras = {}
        for k, sql in (("processos_com_arvore", "SELECT count(DISTINCT numero) FROM pcrj_sei_arvore"),
                       ("processos_catalogo", "SELECT count(*) FROM pcrj_processo WHERE sistema='SEI.RIO'"),
                       ("assinantes_nomeados", "SELECT count(*) FROM pcrj_sei_assinante"),
                       ("docs_texto_vazio", "SELECT count(*) FROM pcrj_processo_doc WHERE texto IS NULL OR length(texto) < 40")):
            try:
                extras[k] = con.execute(sql).fetchone()[0]
            except sqlite3.Error:
                extras[k] = None
    finally:
        con.close()
    logs = [{"log": nome, **_log(p)} for nome, p in LOGS]
    shared = _shared()
    piores = [e for e in etapas if e["grau"] == "🔴"] + [s for s in shared if s["grau"] == "🔴"]
    return {"gerado_em": datetime.now().strftime("%Y-%m-%d %H:%M"), "etapas": etapas, "shared_brain": shared, "logs": logs,
            "extras": extras, "grau_geral": ("🔴" if piores else ("🟡" if any(e["grau"] == "🟡" for e in etapas) else "🟢")),
            "n_vermelhos": len(piores)}


def md(l: dict) -> str:
    L = [f"# Saúde dos pipelines PCRJ — {l['gerado_em']} · geral {l['grau_geral']}", "",
         "| etapa | registros | último | estado | ação se parado |", "|---|---:|---|---|---|"]
    for e in l["etapas"]:
        L.append(f"| {e['etapa']} | {e['n']:,} | {e['ultimo'] or '—'} | {e['grau']} {e['leitura']} | {e['acao']} |".replace(",", "."))
    L += ["", "| shared-brain | MB | idade (h) | |", "|---|---:|---:|---|"]
    for s in l["shared_brain"]:
        L.append(f"| {s['arquivo']} | {s['mb']} | {s['idade_h'] if s['idade_h'] is not None else '—'} | {s['grau']} |")
    L += ["", "| log | último carimbo | erros (últimas 400 linhas) | último erro |", "|---|---|---:|---|"]
    for g in l["logs"]:
        if g.get("existe"):
            L.append(f"| {g['log']} | {g.get('ultimo') or g.get('mtime')} | {g['erros']} | {g.get('ultimo_erro') or '—'} |")
        else:
            L.append(f"| {g['log']} | — | — | log ausente |")
    ex = l["extras"]
    L += ["", f"Catálogo: {ex.get('processos_catalogo')} processos · com árvore capturada: {ex.get('processos_com_arvore')} · "
              f"assinantes nomeados: {ex.get('assinantes_nomeados')} · documentos com texto vazio: {ex.get('docs_texto_vazio')}"]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alertar", action="store_true", help="manda o laudo no Telegram se houver 🔴")
    a = ap.parse_args()
    l = laudo()
    SAIDA.write_text(json.dumps(l, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(l, ensure_ascii=False) if a.json else md(l))
    if a.alertar and l["n_vermelhos"]:
        try:
            import asyncio
            from compliance_agent.notifications import telegram as _tg
            piores = [e for e in l["etapas"] if e["grau"] == "🔴"]
            msg = ("🔴 Pipelines PCRJ com falha (" + str(l["n_vermelhos"]) + "):\n" +
                   "\n".join(f"• {e['etapa']}: {e['leitura']} → {e['acao']}" for e in piores[:8]))
            asyncio.run(_tg.enviar_mensagem(msg[:3500]))
        except (ImportError, RuntimeError, OSError) as exc:
            print(f"alerta Telegram falhou: {exc}")


if __name__ == "__main__":
    main()
