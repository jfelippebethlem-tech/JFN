# -*- coding: utf-8 -*-
"""selecao — o que conferir na fonte primária em seguida, e onde o mesmo padrão pode se repetir.

FILA DA FONTE. A conferência na fonte é cara (ler a íntegra do SEI e as OB do SIAFE): escolhe-se onde ela rende.
  · fatia DIRIGIDA: laudos de risco alto ainda sem prova primária, por
        valor pago × (taxa de confirmação medida + metade da largura do intervalo) × (1 + fração de indícios em armadilha)
    — valor em jogo, otimismo sob incerteza (a célula mal medida ganha conferência) e armadilha provável; processo
    do mesmo credor de um risco alto já confirmado na fonte vale em dobro;
  · fatia ALEATÓRIA (20%): sorteio uniforme entre TODOS os laudos pagos sem prova primária, de qualquer nota, com a
    probabilidade de inclusão gravada. Sem ela a calibração só enxerga o que a seleção quis ver (Kossen et al. 2021)
    e o falso negativo (Opus disse baixo, a fonte achou alto) nunca é medido.
CRUZAMENTO ENTRE CASOS. Indício confirmado na fonte ⇒ os outros processos pagos ao mesmo credor sobem na fila."""
from __future__ import annotations

import json
import random
import sqlite3
import time
from pathlib import Path

from . import armadilhas, calibracao, config, ledger

_DDL = """
CREATE TABLE IF NOT EXISTS fila_fonte(
  id INTEGER PRIMARY KEY, numero_sei TEXT NOT NULL, rodada TEXT NOT NULL, amostra TEXT NOT NULL, prob_inclusao REAL,
  pontuacao REAL, valor_pago REAL, nota INTEGER, motor TEXT, motivo TEXT, criado_em TEXT NOT NULL,
  UNIQUE(numero_sei, rodada));
CREATE TABLE IF NOT EXISTS cruzamento_caso(
  id INTEGER PRIMARY KEY, origem_sei TEXT NOT NULL, alvo_sei TEXT NOT NULL, credor TEXT, nome_credor TEXT,
  valor_alvo REAL, elo TEXT NOT NULL, criado_em TEXT NOT NULL, UNIQUE(origem_sei, alvo_sei));
"""
FRACAO_ALEATORIA = 0.2


def _agora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _ro(db: Path | None) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db or config.REPO / 'data' / 'compliance.db'}?mode=ro", uri=True, timeout=60)


def cruzar(con, compliance_db: Path | None = None) -> int:
    """Para cada processo com risco alto CONFIRMADO na fonte: os demais processos pagos ao mesmo credor (CNPJ)."""
    from tools.lex_execucao import _chave_processo
    from compliance_agent.cruzamentos_intel import _ob_paga
    con.executescript(_DDL)
    origens = [r[0] for r in con.execute("SELECT DISTINCT numero_sei FROM laudo_versao WHERE nivel_prova=? AND nota>=?",
                                         (config.NIVEL_FONTE, config.ALTO))]
    if not origens:
        return 0
    ro = _ro(compliance_db)
    novos = 0
    try:
        chaves = {_chave_processo(o): o for o in origens}
        credor_de: dict[str, tuple[str, str]] = {}
        por_credor: dict[str, dict[str, float]] = {}
        for proc, credor, nome, valor in ro.execute(
                f"SELECT processo, credor, nome_credor, valor FROM ob_orcamentaria_siafe WHERE {_ob_paga(ro)} "
                "AND processo LIKE '%/%' AND LENGTH(credor)=14"):          # só CNPJ: CPF de pessoa física fica fora
            k = _chave_processo(proc)
            if not k:
                continue
            por_credor.setdefault(credor, {})
            por_credor[credor][k] = por_credor[credor].get(k, 0.0) + (valor or 0)
            if k in chaves:
                credor_de[k] = (credor, nome or "")
        ns_de = {_chave_processo(r[0]): r[0] for r in ro.execute("SELECT numero_sei FROM lex_execucao")}
        ja_fonte = {_chave_processo(r[0]) for r in con.execute(
            "SELECT DISTINCT numero_sei FROM laudo_versao WHERE nivel_prova=?", (config.NIVEL_FONTE,))}
        for k, origem in chaves.items():
            if k not in credor_de:
                continue
            credor, nome = credor_de[k]
            for alvo_k, valor in por_credor.get(credor, {}).items():
                if alvo_k == k or alvo_k in ja_fonte or alvo_k not in ns_de:
                    continue
                novos += con.execute(
                    "INSERT OR IGNORE INTO cruzamento_caso(origem_sei,alvo_sei,credor,nome_credor,valor_alvo,elo,criado_em) "
                    "VALUES(?,?,?,?,?,?,?)", (origem, ns_de[alvo_k], credor, nome[:120], round(valor, 2),
                                              "mesmo credor de risco alto confirmado na fonte", _agora())).rowcount
    finally:
        ro.close()
    con.commit()
    return novos


def selecionar(con, n: int = 30, compliance_db: Path | None = None, semente: str | None = None) -> list[dict]:
    """Monta a rodada da fila da fonte (idempotente por rodada = dia). Devolve as linhas escolhidas."""
    from tools.lex_execucao import _chave_processo, mapa_obs_siafe
    con.executescript(_DDL)
    rodada = semente or time.strftime("%Y-%m-%d")
    cal = calibracao.carregar()
    ja = {r[0] for r in con.execute("SELECT DISTINCT numero_sei FROM laudo_versao WHERE nivel_prova=?", (config.NIVEL_FONTE,))}
    elo = {r[0]: r[1] for r in con.execute("SELECT alvo_sei, origem_sei FROM cruzamento_caso")}
    ro = _ro(compliance_db)
    try:
        linhas = [r for r in ro.execute("SELECT numero_sei, nota_risco, modelo, indicios FROM lex_execucao "
                                        "WHERE nota_risco IS NOT NULL") if r[0] not in ja]
        obs = mapa_obs_siafe(ro, [r[0] for r in linhas])
    finally:
        ro.close()
    cands = []
    for ns, nota, modelo, ind in linhas:
        pago = (obs.get(_chave_processo(ns) or "") or {}).get("total", 0.0)
        if pago <= 0:
            continue
        motor, nivel = ledger.motor_e_nivel(modelo)
        if nivel < 0:
            continue
        cands.append({"numero_sei": ns, "nota": nota, "motor": motor, "nivel": nivel, "valor_pago": round(pago, 2),
                      "indicios": ledger._lista(ind), "modelo": modelo})
    n_ale = max(1, round(n * FRACAO_ALEATORIA)) if cands else 0
    rnd = random.Random("jfn-fila-fonte:" + rodada)
    escolhidos: dict[str, dict] = {}
    for c in rnd.sample(cands, min(n_ale, len(cands))):
        escolhidos[c["numero_sei"]] = {**c, "amostra": "aleatoria", "prob_inclusao": round(n_ale / len(cands), 6),
                                       "pontuacao": None, "motivo": "fatia aleatória (mede a calibração sem viés de seleção)"}
    dirigidos = []
    for c in cands:
        if c["nota"] < config.ALTO or c["numero_sei"] in escolhidos:
            continue
        conf = calibracao.confianca(c["modelo"], c["nota"], cal)
        p = conf.get("p_confirma")
        lo, hi = conf.get("ic95") or (0.0, 1.0)
        otimista = (p if p is not None else 0.5) + (hi - lo) / 2
        frac = (sum(1 for i in c["indicios"] if armadilhas.do_indicio(i)) / len(c["indicios"])) if c["indicios"] else 0.0
        bonus = 2.0 if c["numero_sei"] in elo else 1.0
        pont = c["valor_pago"] * otimista * (1 + frac) * bonus
        motivo = ((conf.get("texto") or "")
                  + (f"; {frac * 100:.0f}% dos indícios em armadilha conhecida" if frac else "")
                  + (f"; mesmo credor de {elo[c['numero_sei']]} (risco alto confirmado na fonte)" if bonus > 1 else ""))
        dirigidos.append({**c, "amostra": "dirigida", "prob_inclusao": None, "pontuacao": round(pont, 4), "motivo": motivo})
    for c in sorted(dirigidos, key=lambda x: -x["pontuacao"])[:max(0, n - len(escolhidos))]:
        escolhidos[c["numero_sei"]] = c
    for c in escolhidos.values():
        con.execute("INSERT OR IGNORE INTO fila_fonte(numero_sei,rodada,amostra,prob_inclusao,pontuacao,valor_pago,nota,"
                    "motor,motivo,criado_em) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (c["numero_sei"], rodada, c["amostra"], c["prob_inclusao"], c["pontuacao"], c["valor_pago"], c["nota"],
                     c["motor"], c["motivo"][:600], _agora()))
    con.commit()
    out = [{k: v for k, v in c.items() if k not in ("indicios", "modelo")} for c in escolhidos.values()]
    (config.dados() / "fila_fonte.json").write_text(json.dumps({"rodada": rodada, "roteiro": roteiro(), "itens": out}, ensure_ascii=False,
                                                              indent=1), encoding="utf-8")
    return out


def roteiro() -> str:
    """O roteiro que acompanha cada conferência na fonte (os passos aprendidos nos casos confirmados)."""
    return "Roteiro da conferência na fonte primária:\n- " + "\n- ".join(r["passo"] for r in armadilhas.ROTEIRO_DA_FONTE)


def marcar_conferidos(con) -> int:
    """Conferência na fonte de processo que saiu da fila: o par herda a amostra e a probabilidade de inclusão."""
    con.executescript(_DDL)
    cur = con.execute(
        "UPDATE conferencia SET amostra=(SELECT f.amostra FROM fila_fonte f WHERE f.numero_sei=conferencia.numero_sei "
        "ORDER BY f.id DESC LIMIT 1), prob_inclusao=(SELECT f.prob_inclusao FROM fila_fonte f WHERE "
        "f.numero_sei=conferencia.numero_sei ORDER BY f.id DESC LIMIT 1) WHERE nivel_depois=? AND amostra='dirigida' AND "
        "numero_sei IN (SELECT numero_sei FROM fila_fonte WHERE amostra='aleatoria')", (config.NIVEL_FONTE,))
    con.commit()
    return cur.rowcount
