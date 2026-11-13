# -*- coding: utf-8 -*-
"""cruzamento — os vereditos do Claude e da cascata, lado a lado, e o que se aprende com a diferença.

Pedido do dono (13/11/2026): "o claude vai ser o CO-MOTOR de tudo. os outros continuam também e depois se
cruzam pra ir treinando os outros modelos e ajustando comparativamente."

O QUE GUARDA (`data/cruzamento_motores.db`):
  · `veredito` — uma linha por motor por chamada: tarefa, item, motor (claude|cascata), modelo, veredito
    NORMALIZADO, nível (0 ⚪ sem sinal · 1 🟡 atenção · 2 🔴 grave · NULL indeterminado), confiança,
    latência, se a cascata recebeu exemplos. NUNCA o texto do prompt nem da resposta;
  · `exemplo` — só quando os dois divergiram: um RESUMO curto da entrada (≤ 600 caracteres, sem CPF) e o
    veredito do Claude como referência. É o "treino" possível sem fine-tuning: vira few-shot rotativo nos
    prompts da cascata (`comotor`);
  · `revisao` — divergência GRAVE (um 🔴, outro ⚪). Nunca se resolve sozinha a favor de um: vai para o
    humano, com os dois vereditos.

O QUE MEDE: concordância por tarefa e por modelo (taxa de acordo COM o Claude), matriz de divergência e,
para o few-shot, a mesma taxa separada em "com exemplos" × "sem exemplos" — o A/B que a memória
`prompt-mais-especifico-piorou-recall` exige antes de acreditar que mexer no prompt ajudou. O placar por
modelo diz ao co-motor qual provedor da cascata prefere em cada tarefa, só com amostra mínima.

Concordar com o Claude não é acertar: o Claude é a REFERÊNCIA, não o gabarito. O painel diz isso.
"""
from __future__ import annotations

import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
NIVEIS = {0: "⚪", 1: "🟡", 2: "🔴"}
AMOSTRA_MINIMA = 20
_RE_CPF = re.compile(r"(?<!\d)(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})(?!\d)")

_DDL = """
CREATE TABLE IF NOT EXISTS veredito(
  id INTEGER PRIMARY KEY, par TEXT NOT NULL, tarefa TEXT NOT NULL, item TEXT, motor TEXT NOT NULL,
  modelo TEXT, veredito TEXT, nivel INTEGER, confianca REAL, latencia_ms INTEGER,
  com_exemplos INTEGER DEFAULT 0, em TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_veredito_par ON veredito(par);
CREATE INDEX IF NOT EXISTS ix_veredito_tarefa ON veredito(tarefa, em);
CREATE TABLE IF NOT EXISTS exemplo(
  id INTEGER PRIMARY KEY, tarefa TEXT NOT NULL, item TEXT, entrada TEXT NOT NULL, referencia TEXT NOT NULL,
  nivel_claude INTEGER, modelo_divergente TEXT, nivel_outro INTEGER, usos INTEGER DEFAULT 0, em TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_exemplo_tarefa ON exemplo(tarefa, usos);
CREATE TABLE IF NOT EXISTS revisao(
  id INTEGER PRIMARY KEY, par TEXT NOT NULL, tarefa TEXT NOT NULL, item TEXT,
  modelo_claude TEXT, veredito_claude TEXT, nivel_claude INTEGER,
  modelo_outro TEXT, veredito_outro TEXT, nivel_outro INTEGER,
  status TEXT DEFAULT 'pendente', em TEXT NOT NULL);
"""


@dataclass
class Lado:
    motor: str                  # 'claude' | 'cascata'
    modelo: str
    veredito: str | None
    nivel: int | None
    confianca: float | None = None
    latencia_ms: int | None = None
    com_exemplos: bool = False


def caminho() -> Path:
    return Path(os.environ.get("JFN_CRUZAMENTO_DB") or (_REPO / "data" / "cruzamento_motores.db"))


def conectar(somente_leitura: bool = False) -> sqlite3.Connection:
    p = caminho()
    if somente_leitura:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=15)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_DDL)
    return con


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mascarar(texto: str) -> str:
    """CPF nunca vai para o banco de exemplos (LGPD): 123.456.789-01 → ***.456.789-**."""
    return _RE_CPF.sub(lambda m: f"***.{m.group(2)}.{m.group(3)}-**", texto or "")


def novo_par() -> str:
    return uuid.uuid4().hex[:16]


def provedor(modelo: str | None) -> str:
    return (modelo or "").split(":", 1)[0] or "desconhecido"


def cruzar(tarefa: str, item: str | None, claude: Lado | None, outro: Lado | None, *,
           entrada_resumo: str = "", par: str | None = None, con: sqlite3.Connection | None = None) -> dict:
    """Grava os lados que existirem; divergência vira exemplo; divergência grave vira revisão."""
    par = par or novo_par()
    proprio = con is None
    con = con or conectar()
    try:
        em = _agora()
        for lado in (claude, outro):
            if lado is None:
                continue
            con.execute("INSERT INTO veredito(par,tarefa,item,motor,modelo,veredito,nivel,confianca,latencia_ms,"
                        "com_exemplos,em) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (par, tarefa, item, lado.motor, lado.modelo, (lado.veredito or None) and str(lado.veredito)[:80],
                         lado.nivel, lado.confianca, lado.latencia_ms, int(bool(lado.com_exemplos)), em))
        div = grave = False
        if claude and outro and claude.nivel is not None and outro.nivel is not None:
            div = claude.nivel != outro.nivel
            grave = abs(claude.nivel - outro.nivel) >= 2
            if div and entrada_resumo.strip():
                ref = f"veredito={claude.veredito} nível={NIVEIS.get(claude.nivel, '?')}"
                con.execute("INSERT INTO exemplo(tarefa,item,entrada,referencia,nivel_claude,modelo_divergente,"
                            "nivel_outro,em) VALUES(?,?,?,?,?,?,?,?)",
                            (tarefa, item, mascarar(entrada_resumo)[:600], ref, claude.nivel, outro.modelo,
                             outro.nivel, em))
            if grave:
                con.execute("INSERT INTO revisao(par,tarefa,item,modelo_claude,veredito_claude,nivel_claude,"
                            "modelo_outro,veredito_outro,nivel_outro,em) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (par, tarefa, item, claude.modelo, claude.veredito, claude.nivel,
                             outro.modelo, outro.veredito, outro.nivel, em))
        con.commit()
        return {"par": par, "divergencia": div, "grave": grave}
    finally:
        if proprio:
            con.close()


def exemplos(tarefa: str, k: int = 3, con: sqlite3.Connection | None = None) -> list[dict]:
    """Few-shot ROTATIVO: os menos usados primeiro (e os mais novos no empate); cada uso é contado."""
    proprio = con is None
    con = con or conectar()
    try:
        rows = con.execute("SELECT id, entrada, referencia FROM exemplo WHERE tarefa=? "
                           "ORDER BY usos ASC, id DESC LIMIT ?", (tarefa, max(0, k))).fetchall()
        if rows:
            con.executemany("UPDATE exemplo SET usos=usos+1 WHERE id=?", [(r[0],) for r in rows])
            con.commit()
        return [{"entrada": r[1], "referencia": r[2]} for r in rows]
    finally:
        if proprio:
            con.close()


_SQL_PARES = """
SELECT c.tarefa, o.modelo, c.nivel, o.nivel, o.com_exemplos
FROM veredito c JOIN veredito o ON o.par = c.par AND o.motor = 'cascata'
WHERE c.motor = 'claude' AND c.em >= ? {filtro}
"""


def _pares(con, dias: int, tarefa: str | None):
    desde = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    sql = _SQL_PARES.format(filtro="AND c.tarefa = ?" if tarefa else "")
    return con.execute(sql, (desde, tarefa) if tarefa else (desde,)).fetchall()


def concordancia(dias: int = 30, tarefa: str | None = None, con: sqlite3.Connection | None = None) -> dict:
    """Taxa de acordo com o Claude por tarefa × modelo, matriz de divergência e o A/B do few-shot.

    Par com qualquer lado indeterminado conta em `indeterminados`, fora da taxa (INDISPONÍVEL ≠ discordância).
    """
    proprio = con is None
    try:
        con = con or conectar(somente_leitura=True)
    except sqlite3.Error:
        return {"medido": False, "motivo": "sem cruzamentos ainda", "por_tarefa_modelo": [], "matriz": {}}
    try:
        try:
            pares = _pares(con, dias, tarefa)
        except sqlite3.Error:
            return {"medido": False, "motivo": "sem cruzamentos ainda", "por_tarefa_modelo": [], "matriz": {}}
        grupos: dict[tuple, dict] = {}
        matriz: dict[str, dict[str, int]] = {}
        for t, modelo, nc, no, fs in pares:
            g = grupos.setdefault((t, modelo or "desconhecido"), {
                "n": 0, "acordos": 0, "indeterminados": 0, "graves": 0,
                "com_exemplos": {"n": 0, "acordos": 0}, "sem_exemplos": {"n": 0, "acordos": 0}})
            if nc is None or no is None:
                g["indeterminados"] += 1
                continue
            g["n"] += 1
            ac = int(nc == no)
            g["acordos"] += ac
            g["graves"] += int(abs(nc - no) >= 2)
            lado = g["com_exemplos" if fs else "sem_exemplos"]
            lado["n"] += 1
            lado["acordos"] += ac
            m = matriz.setdefault(t, {})
            chave = f"{NIVEIS[nc]}×{NIVEIS[no]}"
            m[chave] = m.get(chave, 0) + 1
        linhas = []
        for (t, modelo), g in sorted(grupos.items()):
            taxa = (lambda d: round(d["acordos"] / d["n"], 3) if d["n"] else None)
            linhas.append({"tarefa": t, "modelo": modelo, "n": g["n"], "acordos": g["acordos"],
                           "taxa_acordo": taxa(g), "graves": g["graves"], "indeterminados": g["indeterminados"],
                           "taxa_com_exemplos": taxa(g["com_exemplos"]), "n_com_exemplos": g["com_exemplos"]["n"],
                           "taxa_sem_exemplos": taxa(g["sem_exemplos"]), "n_sem_exemplos": g["sem_exemplos"]["n"],
                           "amostra_suficiente": g["n"] >= AMOSTRA_MINIMA})
        return {"medido": bool(linhas), "dias": dias, "por_tarefa_modelo": linhas, "matriz": matriz,
                "legenda": "matriz Claude×outro; acordo com o Claude é referência, não gabarito"}
    finally:
        if proprio:
            con.close()


def placar(tarefa: str, dias: int = 30, con: sqlite3.Connection | None = None) -> dict[str, dict]:
    """Por PROVEDOR da cascata (gemini, groq, openrouter…): n e taxa de acordo com o Claude nesta tarefa."""
    c = concordancia(dias, tarefa, con=con)
    agg: dict[str, dict] = {}
    for ln in c["por_tarefa_modelo"]:
        a = agg.setdefault(provedor(ln["modelo"]), {"n": 0, "acordos": 0})
        a["n"] += ln["n"]
        a["acordos"] += ln["acordos"]
    return {p: {**a, "taxa": round(a["acordos"] / a["n"], 3) if a["n"] else None} for p, a in agg.items()}


def preferido(tarefa: str, minimo: int = AMOSTRA_MINIMA, con: sqlite3.Connection | None = None) -> str | None:
    """O provedor que MAIS concorda com o Claude nesta tarefa — só com amostra mínima em TODOS os comparados
    e só se bater, por margem, o líder atual da cascata (o mais amostrado). Sem medição suficiente: None."""
    p = {k: v for k, v in placar(tarefa, con=con).items() if v["n"] >= minimo and v["taxa"] is not None}
    if len(p) < 2:
        return None
    lider = max(p, key=lambda k: p[k]["n"])
    melhor = max(p, key=lambda k: (p[k]["taxa"], p[k]["n"]))
    if melhor != lider and p[melhor]["taxa"] >= p[lider]["taxa"] + 0.05:
        return melhor
    return None


def revisoes_pendentes(limite: int = 50, con: sqlite3.Connection | None = None) -> list[dict]:
    proprio = con is None
    try:
        con = con or conectar(somente_leitura=True)
        cols = ("id", "tarefa", "item", "modelo_claude", "veredito_claude", "nivel_claude",
                "modelo_outro", "veredito_outro", "nivel_outro", "em")
        rows = con.execute(f"SELECT {','.join(cols)} FROM revisao WHERE status='pendente' "
                           "ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        return [dict(zip(cols, r)) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        if proprio and con is not None:
            con.close()


def resumo_painel(dias: int = 30) -> dict:
    """Bloco "Cruzamento de motores" do painel (rota `/api/ao-vivo/cruzamento`)."""
    c = concordancia(dias)
    try:
        con = conectar(somente_leitura=True)
        try:
            n_rev = con.execute("SELECT COUNT(*) FROM revisao WHERE status='pendente'").fetchone()[0]
            n_ex = con.execute("SELECT COUNT(*) FROM exemplo").fetchone()[0]
            hoje = datetime.now().date().isoformat()
            por_motor = dict(con.execute("SELECT motor, COUNT(*) FROM veredito WHERE em >= ? GROUP BY motor",
                                         (hoje,)).fetchall())
        finally:
            con.close()
    except sqlite3.Error:
        n_rev = n_ex = 0
        por_motor = {}
    return {**c, "revisao_pendente": n_rev, "exemplos_few_shot": n_ex, "vereditos_hoje": por_motor,
            "revisoes": revisoes_pendentes(20)}
