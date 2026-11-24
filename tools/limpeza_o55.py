# -*- coding: utf-8 -*-
"""Limpeza O5.5 do plano mestre v2 (§5 "Limpeza"): zumbis e lotes com vício conhecido saem da triagem e das filas,
de forma REVERSÍVEL e com autor.

    python tools/limpeza_o55.py                       # ensaio (padrão): conta, mostra amostra, não escreve
    python tools/limpeza_o55.py --aplicar             # grava (pare o jfn.service antes; faça o backup)
    python tools/limpeza_o55.py --desfazer --aplicar  # devolve o estado anterior de tudo do lote
    python tools/limpeza_o55.py --alvo 2 --alvo 4     # só alguns alvos

NUNCA apaga. Cada valor trocado vai antes para `limpeza_registro` (no MESMO banco da linha trocada) com o valor
anterior, o novo, o estado de saída (§3.10), o motivo, o autor e o que ele substitui (`supersedes`). Desfazer
devolve o valor anterior só onde a linha ainda tem o valor que a limpeza pôs (se alguém mudou depois, é conflito,
reportado e não pisado). Idempotente: rodar de novo não troca nada nem duplica o registro.

Alvos:
  1  58.253 alertas "Emprego múltiplo suspeito — CPF …" (`acumulacao`, `descartado`): título de uma versão antiga da
     regra, que agrupava só pelo CPF mascarado; o descarte de 13/11 (commit d233ed20) não tem autor. → `arquivado`.
  2  alertas `fracionamento` do motor antigo (`rules/engine.py::_regra_ob_fracionamento`, por credor/OB): conceito
     errado. → `arquivado`; a leitura pendente do Opus na triagem (`opus_pendente`) é retirada.
  3  zumbis J2/J3 de 28/07 em `achados.db` (`confirmado` que nenhuma corrida posterior reavaliou). → `arquivado`.
  4  lote `acumulacao` de 13/11 (`novo`): a identidade é CPF mascarado + nome (`parcial`), que não sustenta grave.
     → `em_revisao` (estado INCERTO); sai da fila do Opus.
  5  P1 a 0,30 fora do `score_processo` (código: `processo_360.entra_no_score`) — aqui só se MEDE; e a amostra
     estratificada de 50 laudos 🔴 da perícia para a fila de conferência do Opus (só a lista; a O6.5 decide).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
AUTOR = "limpeza-O5.5"
LOTE = "o55-20261124"
SEMENTE = 20261124
N_AMOSTRA_E12 = 50
CORTE_ZUMBI = "2026-07-29"          # J2/J3 gerados em 28/07 e nunca mais reavaliados

MOTIVOS = {
    1: ("zumbi: título 'Emprego múltiplo suspeito — CPF …' é de uma versão antiga da regra, que agrupava só pelo CPF "
        "mascarado (99,57% dos 70.533 grupos juntavam pessoas distintas); nenhuma regra atual gera esse título; o "
        "descarte de 13/11 não tem autor (commit d233ed20; ids em data/backups/alertas_acumulacao_descartados_20261113"
        ".json)"),
    2: ("conceito errado — fracionamento é por objeto, art. 75 §1º; ver P4 (o motor antigo somava OB por credor; "
        "rules/engine.py::_regra_ob_fracionamento, executor tools/sweep_avaliacao_total.sh → analisar.py)"),
    3: ("zumbi: J2/J3 'confirmado' gerado em 28/07 e nunca reavaliado pelas corridas posteriores (o certame saiu do "
        "universo da varredura); J3 com desconto 0,0% = homologado copiado do estimado, não desconto medido"),
    4: ("identidade parcial: o casamento é CPF mascarado (6 dígitos do meio) + nome, sem matrícula nem CPF inteiro — "
        "match_level 'parcial' nunca sustenta grave (plano §4.7); fica em revisão até identidade forte"),
}
SUPERSEDES = {1: "d233ed20:status=descartado", 2: "motor-antigo:rules.ob_fracionamento",
              3: "varredura_certames@2026-07-28", 4: "d233ed20:status=novo"}
ESTADO_SAIDA = {1: "AUSENTE", 2: "AUSENTE", 3: "INCERTO", 4: "INCERTO"}

DDL = """CREATE TABLE IF NOT EXISTS limpeza_registro (
  id INTEGER PRIMARY KEY, lote TEXT NOT NULL, alvo INTEGER NOT NULL, tabela TEXT NOT NULL, chave TEXT NOT NULL,
  campo TEXT NOT NULL, valor_anterior TEXT, valor_novo TEXT, estado_saida TEXT, motivo TEXT NOT NULL,
  autor TEXT NOT NULL, supersedes TEXT, em TEXT NOT NULL, desfeito_em TEXT,
  UNIQUE (lote, tabela, chave, campo))"""

# CPF da folha vem mascarado: 'XX123456XXX', '***.123.456-**' etc. Inteiro = 11 dígitos sem máscara.
_CPF_MASCARADO = re.compile(r"[X*x•]")


@dataclass(frozen=True)
class Mudanca:
    alvo: int
    tabela: str
    chave: tuple            # valores da chave primária, na ordem de CHAVES[tabela]
    campo: str
    novo: object


CHAVES = {"alertas": ("id",), "alertas_triagem": ("alerta_id",), "achado_certame": ("certame", "detector")}


def identidade_parcial(evidencias: str | None) -> bool:
    """True se o alerta de folha só casa a pessoa por CPF mascarado + nome (sem matrícula, sem CPF inteiro)."""
    try:
        ev = json.loads(evidencias or "{}")
    except (TypeError, ValueError):
        return False
    if not isinstance(ev, dict):
        return False
    cpf = str(ev.get("cpf") or "")
    if not cpf or not _CPF_MASCARADO.search(cpf):
        return False
    return not any(ev.get(k) for k in ("matricula", "matriculas", "id_funcional", "cpf_completo"))


# ── seleção (só leitura) ─────────────────────────────────────────────────────────────────────────────────
def _triagem_opus(con: sqlite3.Connection, ids: list[int], alvo: int) -> list[Mudanca]:
    if not ids or not _tem_tabela(con, "alertas_triagem"):
        return []
    out = []
    for i in range(0, len(ids), 900):
        lote = ids[i:i + 900]
        q = ",".join("?" * len(lote))
        out += [Mudanca(alvo, "alertas_triagem", (r[0],), "opus_pendente", 0) for r in con.execute(
            f"SELECT alerta_id FROM alertas_triagem WHERE opus_pendente=1 AND alerta_id IN ({q})", lote)]  # noqa: S608
    return out


def _tem_tabela(con: sqlite3.Connection, nome: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,)).fetchone() is not None


def selecionar(alvo: int, con: sqlite3.Connection | None = None, con_ach: sqlite3.Connection | None = None
               ) -> list[Mudanca]:
    """As mudanças que o alvo pede no estado ATUAL (o que já tem o valor novo não entra)."""
    if alvo == 1:
        return [Mudanca(1, "alertas", (r[0],), "status", "arquivado") for r in con.execute(
            "SELECT id FROM alertas WHERE tipo='acumulacao' AND status='descartado' "
            "AND titulo LIKE 'Emprego múltiplo suspeito%' ORDER BY id")]
    if alvo == 2:
        ids = [r[0] for r in con.execute(
            "SELECT id FROM alertas WHERE tipo='fracionamento' AND COALESCE(status,'novo')<>'arquivado' ORDER BY id")]
        todos = [r[0] for r in con.execute("SELECT id FROM alertas WHERE tipo='fracionamento' ORDER BY id")]
        return [Mudanca(2, "alertas", (i,), "status", "arquivado") for i in ids] + _triagem_opus(con, todos, 2)
    if alvo == 3:
        return [Mudanca(3, "achado_certame", (r[0], r[1]), "status", "arquivado") for r in con_ach.execute(
            "SELECT certame, detector FROM achado_certame WHERE detector IN ('J2','J3') AND status='confirmado' "
            "AND gerado_em < ? ORDER BY detector, certame", (CORTE_ZUMBI,))]
    if alvo == 4:
        ids = [r[0] for r in con.execute(
            "SELECT id, evidencias FROM alertas WHERE tipo='acumulacao' AND status='novo' ORDER BY id")
            if identidade_parcial(r[1])]
        todos = [r[0] for r in con.execute(
            "SELECT id, evidencias FROM alertas WHERE tipo='acumulacao' AND status IN ('novo','em_revisao') ORDER BY id")
            if identidade_parcial(r[1])]
        return [Mudanca(4, "alertas", (i,), "status", "em_revisao") for i in ids] + _triagem_opus(con, todos, 4)
    raise ValueError(f"alvo sem escrita: {alvo}")


def contar(alvo: int, con: sqlite3.Connection | None = None, con_ach: sqlite3.Connection | None = None) -> dict:
    """Número antes/depois do alvo (o que a triagem e as filas enxergam)."""
    um = lambda c, sql, *p: c.execute(sql, p).fetchone()[0]  # noqa: E731
    if alvo == 1:
        return {"descartado_sem_autor": um(con, "SELECT COUNT(*) FROM alertas WHERE tipo='acumulacao' AND status="
                                                "'descartado' AND titulo LIKE 'Emprego múltiplo suspeito%'"),
                "arquivado": um(con, "SELECT COUNT(*) FROM alertas WHERE tipo='acumulacao' AND status='arquivado'")}
    if alvo == 2:
        d = {f"status_{s}": n for s, n in con.execute(
            "SELECT COALESCE(status,'novo'), COUNT(*) FROM alertas WHERE tipo='fracionamento' GROUP BY 1")}
        d["na_triagem_novo"] = um(con, "SELECT COUNT(*) FROM alertas WHERE tipo='fracionamento' AND status='novo'")
        if _tem_tabela(con, "alertas_triagem"):
            d["fila_opus"] = um(con, "SELECT COUNT(*) FROM alertas_triagem t JOIN alertas a ON a.id=t.alerta_id "
                                     "WHERE a.tipo='fracionamento' AND t.opus_pendente=1")
        return d
    if alvo == 3:
        return {f"{d}_{s}": n for d, s, n in con_ach.execute(
            "SELECT detector, status, COUNT(*) FROM achado_certame WHERE detector IN ('J2','J3') "
            "AND gerado_em < ? GROUP BY 1, 2", (CORTE_ZUMBI,))} | {
            "J3_desconto_zero": sum(1 for (v,) in con_ach.execute(
                "SELECT valores FROM achado_certame WHERE detector='J3' AND status IN ('confirmado','arquivado') "
                "AND gerado_em < ?", (CORTE_ZUMBI,)) if (json.loads(v or "{}") or {}).get("desconto_pct") == 0.0)}
    if alvo == 4:
        d = {f"status_{s}": n for s, n in con.execute(
            "SELECT status, COUNT(*) FROM alertas WHERE tipo='acumulacao' AND status IN ('novo','em_revisao') "
            "GROUP BY 1")}
        d["parcial_novo"] = sum(1 for (e,) in con.execute(
            "SELECT evidencias FROM alertas WHERE tipo='acumulacao' AND status='novo'") if identidade_parcial(e))
        d["novo_total_alertas"] = um(con, "SELECT COUNT(*) FROM alertas WHERE status='novo'")
        if _tem_tabela(con, "alertas_triagem"):
            d["fila_opus"] = um(con, "SELECT COUNT(*) FROM alertas_triagem t JOIN alertas a ON a.id=t.alerta_id "
                                     "WHERE a.tipo='acumulacao' AND t.opus_pendente=1")
        return d
    raise ValueError(alvo)


# ── escrita reversível ───────────────────────────────────────────────────────────────────────────────────
def _onde(tabela: str) -> str:
    return " AND ".join(f"{c}=?" for c in CHAVES[tabela])


def aplicar(con: sqlite3.Connection, mudancas: list[Mudanca], *, lote: str = LOTE, em: str | None = None) -> int:
    """Grava as mudanças numa transação. Antes de trocar, registra o valor anterior. Devolve quantas trocou."""
    em = em or datetime.now().isoformat(timespec="seconds")
    con.execute(DDL)
    n = 0
    with con:
        for m in mudancas:
            atual = con.execute(f"SELECT {m.campo} FROM {m.tabela} WHERE {_onde(m.tabela)}", m.chave).fetchone()  # noqa: S608
            if atual is None or atual[0] == m.novo:
                continue
            chave = json.dumps(list(m.chave), ensure_ascii=False)
            con.execute(
                "INSERT INTO limpeza_registro (lote, alvo, tabela, chave, campo, valor_anterior, valor_novo, "
                "estado_saida, motivo, autor, supersedes, em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT (lote, tabela, chave, campo) DO UPDATE SET valor_anterior=excluded.valor_anterior, "
                "valor_novo=excluded.valor_novo, em=excluded.em, desfeito_em=NULL",
                (lote, m.alvo, m.tabela, chave, m.campo, json.dumps(atual[0]), json.dumps(m.novo),
                 ESTADO_SAIDA.get(m.alvo), MOTIVOS[m.alvo], AUTOR, SUPERSEDES.get(m.alvo), em))
            con.execute(f"UPDATE {m.tabela} SET {m.campo}=? WHERE {_onde(m.tabela)}", (m.novo, *m.chave))  # noqa: S608
            n += 1
    return n


def desfazer(con: sqlite3.Connection, *, lote: str = LOTE, alvos: set[int] | None = None,
             aplicar_: bool = False) -> dict:
    """Devolve o valor anterior onde a linha ainda tem o valor da limpeza. Conflito (mudou depois) não é pisado."""
    if not _tem_tabela(con, "limpeza_registro"):
        return {"desfeitos": 0, "conflitos": 0}
    rows = con.execute("SELECT id, alvo, tabela, chave, campo, valor_anterior, valor_novo FROM limpeza_registro "
                       "WHERE lote=? AND desfeito_em IS NULL", (lote,)).fetchall()
    em = datetime.now().isoformat(timespec="seconds")
    feitos = conflitos = 0
    with con:
        for rid, alvo, tabela, chave, campo, ant, novo in rows:
            if alvos and alvo not in alvos:
                continue
            k = tuple(json.loads(chave))
            atual = con.execute(f"SELECT {campo} FROM {tabela} WHERE {_onde(tabela)}", k).fetchone()  # noqa: S608
            if atual is None or atual[0] != json.loads(novo):
                conflitos += 1
                continue
            feitos += 1
            if aplicar_:
                con.execute(f"UPDATE {tabela} SET {campo}=? WHERE {_onde(tabela)}", (json.loads(ant), *k))  # noqa: S608
                con.execute("UPDATE limpeza_registro SET desfeito_em=? WHERE id=?", (em, rid))
    return {"desfeitos": feitos, "conflitos": conflitos, "aplicado": aplicar_}


# ── alvo 5: P1 fraco no score e amostra E12 (só leitura) ───────────────────────────────────────────────────
_VIGENTE = ("SELECT p.processo, p.grau, p.modelo, p.valor_pago, p.conferido_opus FROM pericia_integral p "
            "JOIN (SELECT processo, MAX(id) mid FROM pericia_integral WHERE eixo='_global' AND conferido_opus IN (0,1) "
            "GROUP BY processo) u ON u.processo=p.processo AND p.id=u.mid")


def _motor(modelo: str | None) -> str:
    m = str(modelo or "").lower()
    return "claude" if m.startswith(("claude", "agente")) else (m.split(":")[0].split("/")[0] or "desconhecido")


def _faixa_valor(v) -> str:
    v = float(v or 0)
    return ("sem_valor" if v <= 0 else "ate_1mi" if v < 1e6 else "1mi_10mi" if v < 1e7 else "acima_10mi")


def amostra_e12(con: sqlite3.Connection, n: int = N_AMOSTRA_E12, semente: int = SEMENTE) -> dict:
    """Laudos vigentes 🔴 (grau global ≥ 2) que o Opus ainda NÃO leu — nem conferiu (`conferido_opus=1`) nem escreveu
    (laudo do agente Claude/Opus: conferir o Opus com o Opus não é leitura independente) —, sorteados por estrato
    (motor × faixa de valor pago), alocação proporcional com piso de 1, semente fixa."""
    rows = con.execute(_VIGENTE).fetchall()
    vermelhos = [r for r in rows if r[1] is not None and r[1] >= 2]
    pend = [r for r in vermelhos if r[4] == 0 and _motor(r[2]) != "claude"]
    autor_opus = sum(1 for r in vermelhos if r[4] == 0 and _motor(r[2]) == "claude")
    estratos: dict[tuple, list] = defaultdict(list)
    for r in pend:
        estratos[(_motor(r[2]), _faixa_valor(r[3]))].append(r)
    rnd = random.Random(semente)
    total = len(pend)
    alvo = min(n, total)
    cotas = {k: max(1, round(alvo * len(v) / total)) for k, v in estratos.items()} if total else {}
    while sum(cotas.values()) > alvo:                      # o piso de 1 pode estourar: tira do maior estrato
        k = max(cotas, key=lambda x: (cotas[x], str(x)))
        cotas[k] -= 1
    while sum(cotas.values()) < alvo:
        k = max(estratos, key=lambda x: (len(estratos[x]) - cotas[x], str(x)))
        cotas[k] += 1
    sorteio = []
    for k in sorted(estratos):
        grupo = sorted(estratos[k], key=lambda r: r[0])
        for r in rnd.sample(grupo, min(cotas[k], len(grupo))):
            sorteio.append({"processo": r[0], "grau_global": r[1], "motor": k[0], "faixa_valor": k[1],
                            "valor_pago": r[3]})
    return {"vigentes": len(rows), "vermelhos": len(vermelhos),
            "vermelhos_grau2": sum(1 for r in vermelhos if r[1] == 2),
            "vermelhos_grau_fora_escala": sum(1 for r in vermelhos if r[1] > 2),
            "ja_conferidos_opus": len(vermelhos) - len(pend) - autor_opus, "escritos_pelo_opus": autor_opus,
            "universo_sorteio": total,
            "estratos": {f"{a}|{b}": {"n": len(estratos[(a, b)]), "cota": cotas[(a, b)]} for a, b in sorted(estratos)},
            "semente": semente, "amostra": sorted(sorteio, key=lambda x: (x["motor"], x["faixa_valor"], x["processo"]))}


def medir_p1(con: sqlite3.Connection, con_ach: sqlite3.Connection | None) -> dict:
    """Onde P1 fraco (0,30) aparece hoje: na avaliação 360 gravada e na varredura de certames."""
    n360 = 0
    for (aj,) in con.execute("SELECT achados_json FROM processo_avaliacao WHERE achados_json LIKE '%\"P1\"%'"):
        try:
            a = json.loads(aj or "[]")
        except ValueError:
            continue
        a = a.get("achados", []) if isinstance(a, dict) else a
        n360 += any(isinstance(x, dict) and x.get("codigo") == "P1" for x in a)
    d = {"processo_avaliacao_total": con.execute("SELECT COUNT(*) FROM processo_avaliacao").fetchone()[0],
         "processo_avaliacao_com_P1": n360}
    if con_ach is not None:
        d["achado_certame_P1_confirmado_por_score"] = dict(con_ach.execute(
            "SELECT score, COUNT(*) FROM achado_certame WHERE detector='P1' AND status='confirmado' GROUP BY 1"
        ).fetchall())
    return d


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────────────────
def _amostra_ids(mudancas: list[Mudanca], k: int = 10) -> list:
    principais = [m.chave if len(m.chave) > 1 else m.chave[0] for m in mudancas if m.tabela != "alertas_triagem"]
    return [list(x) if isinstance(x, tuple) else x for x in random.Random(SEMENTE).sample(principais, min(k, len(principais)))]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(RAIZ / "data" / "compliance.db"))
    ap.add_argument("--db-achados", default=str(RAIZ / "data" / "achados.db"))
    ap.add_argument("--alvo", type=int, action="append", choices=[1, 2, 3, 4, 5])
    ap.add_argument("--lote", default=LOTE)
    ap.add_argument("--aplicar", action="store_true", help="grava (sem isto: ensaio)")
    ap.add_argument("--desfazer", action="store_true", help="devolve o estado anterior do lote")
    ap.add_argument("--saida", help="JSON com o relatório (contagens, amostras, lista E12)")
    a = ap.parse_args(argv)
    alvos = sorted(set(a.alvo or [1, 2, 3, 4, 5]))
    con = sqlite3.connect(a.db, timeout=60)
    con_ach = sqlite3.connect(a.db_achados, timeout=60) if Path(a.db_achados).exists() else None
    rel: dict = {"lote": a.lote, "modo": ("desfazer" if a.desfazer else "aplicar") if a.aplicar else "ensaio",
                 "em": datetime.now().isoformat(timespec="seconds"), "alvos": {}}
    if a.desfazer:
        com_alvo = set(alvos) - {5}
        rel["desfazer"] = {"compliance": desfazer(con, lote=a.lote, alvos=com_alvo, aplicar_=a.aplicar)}
        if con_ach is not None:
            rel["desfazer"]["achados"] = desfazer(con_ach, lote=a.lote, alvos=com_alvo, aplicar_=a.aplicar)
    else:
        for alvo in alvos:
            if alvo == 5:
                rel["alvos"]["5"] = {"p1": medir_p1(con, con_ach), "e12": amostra_e12(con)}
                continue
            c = con_ach if alvo == 3 else con
            if c is None:
                rel["alvos"][str(alvo)] = {"erro": "achados.db ausente"}
                continue
            antes = contar(alvo, con, con_ach)
            mud = selecionar(alvo, con, con_ach)
            r = {"antes": antes, "mudancas": len(mud),
                 "por_tabela": {t: sum(1 for m in mud if m.tabela == t) for t in sorted({m.tabela for m in mud})},
                 "amostra_10": _amostra_ids(mud), "motivo": MOTIVOS[alvo]}
            if a.aplicar:
                r["trocados"] = aplicar(c, mud, lote=a.lote)
                r["depois"] = contar(alvo, con, con_ach)
            rel["alvos"][str(alvo)] = r
    txt = json.dumps(rel, ensure_ascii=False, indent=1, default=str)
    if a.saida:
        Path(a.saida).write_text(txt, encoding="utf-8")
    print(txt if len(txt) < 20000 else txt[:20000] + "\n… (cortado; veja --saida)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
