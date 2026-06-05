# -*- coding: utf-8 -*-
"""
Massare / ecossistema — APRENDIZADO CONTÍNUO.

Dois mecanismos, ambos persistentes em SQLite (massare.db):

1) DIÁRIO DE PREVISÕES (forecasts) — o coração do aprendizado quantitativo do Massare.
   Toda tese vira uma previsão REGISTRADA (símbolo, horizonte, direção, probabilidade, racional).
   Quando o futuro chega, `grade_due()` busca o preço realizado no store e CARIMBA acerto/erro.
   `scoreboard()` devolve a taxa de acerto REAL out-of-sample (a única honesta) — é assim que se
   persegue a meta de acerto sem se enganar: o sistema é cobrado pelo que de fato aconteceu.

2) LIÇÕES (lessons) — registro append-only cross-agente (Massare, JFN, Yoda, Hermes).
   Qualquer agente grava o que aprendeu (correção do usuário, padrão confirmado, erro a não
   repetir) e relê as lições recentes para se condicionar. É o "aprender continuamente" comum
   a todos os projetos. Yoda/Hermes também têm memória própria (MEMORY.md/USER.md); aqui fica
   o registro estruturado e versionável de lições do ecossistema.
"""
import time

from massare import store

SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT, asof_date TEXT, symbol TEXT,
    horizon_days INTEGER, direction TEXT,        -- 'up' | 'down'
    prob        REAL, rationale TEXT, model TEXT,
    target_date TEXT,
    base_close  REAL,
    realized_close REAL, realized_dir TEXT,
    correct     INTEGER                          -- NULL até avaliar; 1 acerto, 0 erro
);
CREATE INDEX IF NOT EXISTS ix_fc_symbol ON forecasts(symbol);
CREATE INDEX IF NOT EXISTS ix_fc_open   ON forecasts(correct);

CREATE TABLE IF NOT EXISTS lessons (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT, agent TEXT, topic TEXT, lesson TEXT, evidence TEXT
);
"""


def init():
    with store.connect() as con:
        con.executescript(SCHEMA)


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


def _close_on_or_before(con, symbol, date):
    row = con.execute(
        "SELECT date, close FROM prices WHERE symbol=? AND date<=? ORDER BY date DESC LIMIT 1",
        (symbol, date)).fetchone()
    return row  # (date, close) ou None


# ---------------------------------------------------------------- previsões
def record_forecast(symbol, direction, horizon_days, prob, rationale, model="massare", asof=None):
    """Registra uma previsão. asof = data-base (default: último pregão do símbolo)."""
    init()
    with store.connect() as con:
        if asof is None:
            r = con.execute("SELECT MAX(date) FROM prices WHERE symbol=?", (symbol,)).fetchone()
            asof = r[0] if r else time.strftime("%Y-%m-%d", time.gmtime())
        base = _close_on_or_before(con, symbol, asof)
        base_close = base[1] if base else None
        # target_date = asof + horizon (dias corridos; grade usa último pregão <= target)
        tt = time.mktime(time.strptime(asof, "%Y-%m-%d")) + horizon_days * 86400
        target = time.strftime("%Y-%m-%d", time.localtime(tt))
        con.execute(
            """INSERT INTO forecasts(created_at,asof_date,symbol,horizon_days,direction,prob,
               rationale,model,target_date,base_close) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (_now(), asof, symbol, horizon_days, direction, prob, rationale, model, target, base_close))
    return {"symbol": symbol, "direction": direction, "asof": asof, "target_date": target}


def grade_due(today=None):
    """Avalia previsões cujo alvo já passou e ainda não foram corrigidas."""
    init()
    today = today or time.strftime("%Y-%m-%d", time.gmtime())
    graded = 0
    with store.connect() as con:
        due = con.execute(
            "SELECT id,symbol,target_date,base_close,direction FROM forecasts WHERE correct IS NULL AND target_date<=?",
            (today,)).fetchall()
        for fid, sym, target, base, direction in due:
            rc = _close_on_or_before(con, sym, target)
            if not rc or base is None:
                continue
            realized_close = rc[1]
            realized_dir = "up" if realized_close >= base else "down"
            correct = 1 if realized_dir == direction else 0
            con.execute("UPDATE forecasts SET realized_close=?, realized_dir=?, correct=? WHERE id=?",
                        (realized_close, realized_dir, correct, fid))
            graded += 1
    return graded


def scoreboard():
    """Taxa de acerto REAL (out-of-sample) — geral, por modelo e por horizonte."""
    init()
    with store.connect() as con:
        def rate(where="", args=()):
            r = con.execute(f"SELECT COUNT(*), SUM(correct) FROM forecasts WHERE correct IS NOT NULL {where}", args).fetchone()
            n, s = r[0] or 0, r[1] or 0
            return {"n": n, "hits": s, "hit_rate": round(s / n, 4) if n else None}
        overall = rate()
        by_h = {str(h): rate("AND horizon_days=?", (h,))
                for (h,) in con.execute("SELECT DISTINCT horizon_days FROM forecasts WHERE correct IS NOT NULL").fetchall()}
        by_m = {m: rate("AND model=?", (m,))
                for (m,) in con.execute("SELECT DISTINCT model FROM forecasts WHERE correct IS NOT NULL").fetchall()}
        open_n = con.execute("SELECT COUNT(*) FROM forecasts WHERE correct IS NULL").fetchone()[0]
    return {"overall": overall, "by_horizon": by_h, "by_model": by_m, "pendentes": open_n}


# ---------------------------------------------------------------- lições (cross-agente)
def add_lesson(agent, topic, lesson, evidence=""):
    init()
    with store.connect() as con:
        con.execute("INSERT INTO lessons(ts,agent,topic,lesson,evidence) VALUES(?,?,?,?,?)",
                    (_now(), agent, topic, lesson, evidence))


def recent_lessons(agent=None, limit=20):
    init()
    with store.connect() as con:
        if agent:
            rows = con.execute("SELECT ts,agent,topic,lesson FROM lessons WHERE agent=? ORDER BY id DESC LIMIT ?",
                               (agent, limit)).fetchall()
        else:
            rows = con.execute("SELECT ts,agent,topic,lesson FROM lessons ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{"ts": r[0], "agent": r[1], "topic": r[2], "lesson": r[3]} for r in rows]


if __name__ == "__main__":
    import json
    init()
    print("Scoreboard atual:", json.dumps(scoreboard(), ensure_ascii=False))
    print("Lições recentes:", json.dumps(recent_lessons(limit=5), ensure_ascii=False))
