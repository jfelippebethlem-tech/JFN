#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sono REM do Hermes — ciclo diário de meta-cognição + memória blindada.

Por que existe: a auto-melhoria (`auto_melhoria.py`) e a reflexão (`refletir_com_hermes`)
só rodavam dentro de `scheduler.py --loop`, que NÃO roda em produção (o jfn.service sobe
só a API). Resultado: a inteligência progressiva de LLM estava DORMENTE. Este tool é o
acordador: um comando, chamado por timer diário (jfn-metacognicao.timer), sem ligar o
scheduler pesado inteiro.

Passos do `run` (cada um à prova de falha — um passo caindo não derruba os outros):
  1. HIGIENE    — contexto inicial + seeds de método (idempotentes) + poda de stubs.
  2. REFLEXÃO   — resumo REAL do dia (alertas + perícias do núcleo) → lições (memória).
  3. AUTO-MELHORIA — critica o próprio método contra os vereditos do vault → regras novas.
  4. RAG        — reindexa o corpus SÓ se mudou (vereditos novos entram no RAG; lição
                  da perícia 4-vias: "RAG deve carregar VEREDITOS").
  5. BACKUP     — exporta a memória de aprendizado p/ JSONL no vault (Syncthing) —
                  sobrevive até a corrupção do compliance.db ("malformed" já aconteceu).

Uso:
  python tools/hermes_metacognicao.py run              # ciclo completo (timer diário)
  python tools/hermes_metacognicao.py backup           # só o export da memória
  python tools/hermes_metacognicao.py restore <jsonl>  # reimporta memória exportada
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(r"C:\JFN\jfn")           # adaptado do original da VM (/home/ubuntu/JFN)
sys.path.insert(0, str(REPO))

BACKUP_DIR = Path(r"C:\Users\iterj\vault\aprendizados\hermes-memoria")  # vault sincronizado (Syncthing)
MANTER_BACKUPS = 7


# ─── 5. Backup / restore da memória (sqlite → JSONL no vault) ─────────────────

def backup_memoria() -> dict:
    """Exporta memoria_aprendizado (compliance.db) + pericias (nucleo_memoria.db) p/ JSONL.
    Vault é sincronizado (Syncthing) → o aprendizado sobrevive a corrupção/perda do DB."""
    import sqlite3
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    hoje = datetime.now().strftime("%Y-%m-%d")
    out = {"memoria": 0, "pericias": 0}

    con = sqlite3.connect(str(REPO / "data/compliance.db"), timeout=30)
    con.row_factory = sqlite3.Row
    try:
        arq = BACKUP_DIR / f"memoria_aprendizado_{hoje}.jsonl"
        with open(arq, "w", encoding="utf-8") as f:
            for r in con.execute("SELECT * FROM memoria_aprendizado"):
                f.write(json.dumps(dict(r), ensure_ascii=False, default=str) + "\n")
                out["memoria"] += 1
    finally:
        con.close()

    con = sqlite3.connect(str(REPO / "data/nucleo_memoria.db"), timeout=30)
    con.row_factory = sqlite3.Row
    try:
        arq = BACKUP_DIR / f"nucleo_pericias_{hoje}.jsonl"
        with open(arq, "w", encoding="utf-8") as f:
            for r in con.execute("SELECT * FROM pericias"):
                f.write(json.dumps(dict(r), ensure_ascii=False, default=str) + "\n")
                out["pericias"] += 1
    finally:
        con.close()

    # rotação: mantém os N mais recentes de cada série
    for prefixo in ("memoria_aprendizado_", "nucleo_pericias_"):
        serie = sorted(BACKUP_DIR.glob(f"{prefixo}*.jsonl"))
        for velho in serie[:-MANTER_BACKUPS]:
            velho.unlink()
    return out


def restore_memoria(jsonl: str) -> int:
    """Reimporta um export de memoria_aprendizado (não sobrescreve itens existentes:
    chave categoria+chave já presente = pulado; restauração é aditiva e segura)."""
    import sqlite3
    con = sqlite3.connect(str(REPO / "data/compliance.db"), timeout=30)
    n = 0
    try:
        for linha in open(jsonl, encoding="utf-8"):
            r = json.loads(linha)
            existe = con.execute(
                "SELECT 1 FROM memoria_aprendizado WHERE categoria=? AND chave=?",
                (r["categoria"], r["chave"])).fetchone()
            if existe:
                continue
            con.execute(
                "INSERT INTO memoria_aprendizado (categoria, chave, valor, confianca, "
                "n_observacoes, fonte, primeira_vez, ultima_vez) VALUES (?,?,?,?,?,?,?,?)",
                (r["categoria"], r["chave"], r.get("valor"), r.get("confianca", 0.5),
                 r.get("n_observacoes", 1), r.get("fonte", "restore"),
                 r.get("primeira_vez"), r.get("ultima_vez")))
            n += 1
        con.commit()
    finally:
        con.close()
    return n


# ─── 2. Resumo real do dia (o que o sistema viu nas últimas 24h) ──────────────

def _resumo_do_dia() -> str:
    import sqlite3
    partes = []
    try:
        con = sqlite3.connect(str(REPO / "data/compliance.db"), timeout=30)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT severidade, titulo, descricao FROM alertas "
            "WHERE created_at >= datetime('now','-1 day') "
            "ORDER BY severidade DESC LIMIT 15").fetchall()
        con.close()
        if rows:
            partes.append("ALERTAS DAS ÚLTIMAS 24H:")
            partes += [f"- [{r['severidade']}] {r['titulo']}: {(r['descricao'] or '')[:180]}"
                       for r in rows]
    except Exception:
        pass
    try:
        con = sqlite3.connect(str(REPO / "data/nucleo_memoria.db"), timeout=30)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT categoria, orgao, valor, risco_score, classificacao, veredito_perito "
            "FROM pericias WHERE quando >= datetime('now','-1 day') "
            "ORDER BY risco_score DESC LIMIT 15").fetchall()
        con.close()
        if rows:
            partes.append("PERÍCIAS DO NÚCLEO NAS ÚLTIMAS 24H:")
            partes += [f"- {r['categoria']}/{r['orgao']}: R$ {r['valor']} risco={r['risco_score']} "
                       f"({r['classificacao']}) veredito={r['veredito_perito'] or 'pendente'}"
                       for r in rows]
    except Exception:
        pass
    return "\n".join(partes)


# ─── Ciclo completo ────────────────────────────────────────────────────────────

async def run() -> dict:
    res: dict = {"quando": datetime.now().isoformat(timespec="seconds")}

    # 1. higiene (idempotente)
    try:
        from compliance_agent.llm.memoria import garantir_contexto_inicial, podar_memoria
        from compliance_agent.llm.auto_melhoria import seed_metodos
        garantir_contexto_inicial()
        seed_metodos()
        res["podados"] = podar_memoria()
    except Exception as e:  # noqa: BLE001
        res["higiene_erro"] = str(e)[:150]

    # 2. reflexão sobre o dia real
    try:
        from compliance_agent.llm.memoria import refletir_com_hermes
        resumo = _resumo_do_dia()
        if resumo:
            res["reflexao"] = await refletir_com_hermes(resumo) or "sem lições novas"
        else:
            res["reflexao"] = "sem observações nas últimas 24h — pulado (não inventar lição)"
    except Exception as e:  # noqa: BLE001
        res["reflexao_erro"] = str(e)[:150]

    # 3. auto-melhoria de método (crítica contra vereditos do vault)
    try:
        from compliance_agent.llm.auto_melhoria import auto_melhorar
        am = await auto_melhorar()
        res["auto_melhoria"] = am.get("novas_auto_correcoes", [])
        res["total_metodos"] = am.get("total_metodos")
    except Exception as e:  # noqa: BLE001
        res["auto_melhoria_erro"] = str(e)[:150]

    # 4. RAG — reindexa só se o corpus mudou (vereditos novos entram)
    try:
        from tools.hermes_rag import build_se_mudou
        res["rag_rebuild"] = build_se_mudou()
    except Exception as e:  # noqa: BLE001
        res["rag_erro"] = str(e)[:150]

    # 5. backup da memória → vault
    try:
        res["backup"] = backup_memoria()
    except Exception as e:  # noqa: BLE001
        res["backup_erro"] = str(e)[:150]

    # aviso no Telegram SÓ se aprendeu regra de método nova (silencioso no dia-a-dia)
    if res.get("auto_melhoria"):
        try:
            from compliance_agent.envfile import carregar_env
            carregar_env()
            from compliance_agent.notifications.telegram import enviar_mensagem
            await enviar_mensagem(
                "🧠 *Hermes — meta-cognição diária:* novas regras de método: "
                + ", ".join(res["auto_melhoria"][:5]))
        except Exception:
            pass
    return res


if __name__ == "__main__":
    import asyncio
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "backup":
        print(json.dumps(backup_memoria(), ensure_ascii=False))
    elif cmd == "restore":
        if len(sys.argv) < 3:
            raise SystemExit("uso: hermes_metacognicao.py restore <arquivo.jsonl>")
        print(f"{restore_memoria(sys.argv[2])} itens restaurados (aditivo, sem sobrescrever).")
    else:
        print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=1))
