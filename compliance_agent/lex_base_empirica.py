# -*- coding: utf-8 -*-
"""
lex_base_empirica — o Lex APRENDE com a NOSSA base (compliance.db).

Em vez de só conhecimento jurídico (manuais), aqui o Lex absorve padrões EMPÍRICOS dos
dados reais já coletados (OBs do TFE/SIAFE, scores de anomalia, concentração por UG,
ubiquidade de fornecedores, cobertura OB↔SEI). Os aprendizados são persistidos em
`memoria_aprendizado` (fonte='empirico'), de onde o Lex e o restante do ecossistema
reaproveitam — calibrando o que é "normal" antes de apontar um indício.

ÉTICA (padrão JFN/Lex): baseline empírico é RÉGUA de contexto, não prova. Um valor acima
da mediana da UG é INDÍCIO a verificar, jamais acusação. Liga-se a [[lex_sancoes]],
[[lex_indicadores_fraude]] e ao módulo de anomalias.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"


def _con():
    return sqlite3.connect(str(_DB))


def _percentil(con, tabela: str, coluna: str, p: float, where: str = "") -> float | None:
    n = con.execute(f"SELECT COUNT(*) FROM {tabela} {where}").fetchone()[0]
    if not n:
        return None
    off = max(0, min(n - 1, int(n * p)))
    r = con.execute(f"SELECT {coluna} FROM {tabela} {where} ORDER BY {coluna} LIMIT 1 OFFSET {off}").fetchone()
    return float(r[0]) if r and r[0] is not None else None


# ── consultas de aprendizado (cada uma devolve fatos para memoria_aprendizado) ──

def fatos_anomalia(con) -> list[tuple]:
    p95 = _percentil(con, "ob_anomaly", "score", 0.95)
    p99 = _percentil(con, "ob_anomaly", "score", 0.99)
    n = con.execute("SELECT COUNT(*) FROM ob_anomaly").fetchone()[0]
    if p95 is None:
        return []
    return [("anomalia_threshold",
             f"Score de anomalia (ensemble PyOD): p95={p95:.3f}, p99={p99:.3f} sobre {n:,} OBs. "
             f"Acima de p99 = OB estatisticamente atípica a priorizar em diligência.",
             0.8, n)]


def fatos_concentracao(con) -> list[tuple]:
    # UGs onde 1 fornecedor concentra mais valor (proxy de captura/direcionamento)
    rows = con.execute("""
        WITH porug AS (
            SELECT ug_codigo, SUM(valor) tot FROM ordens_bancarias
            WHERE valor>0 GROUP BY ug_codigo HAVING tot>0),
        top1 AS (
            SELECT ug_codigo, favorecido_cpf, SUM(valor) v FROM ordens_bancarias
            WHERE valor>0 AND favorecido_cpf IS NOT NULL GROUP BY ug_codigo, favorecido_cpf)
        SELECT p.ug_codigo, MAX(t.v)*100.0/p.tot AS share
        FROM porug p JOIN top1 t ON t.ug_codigo=p.ug_codigo
        GROUP BY p.ug_codigo HAVING share>=60 ORDER BY share DESC LIMIT 15""").fetchall()
    if not rows:
        return []
    amostra = "; ".join(f"UG {ug}={sh:.0f}%" for ug, sh in rows[:8])
    return [("concentracao_ug_top1",
             f"{len(rows)} UG(s) com 1 fornecedor concentrando >=60% do valor pago (red flag ACFE). "
             f"Maiores: {amostra}.", 0.7, len(rows))]


def fatos_ubiquidade(con) -> list[tuple]:
    # fornecedores "ubíquos" (em muitos órgãos) = baseline para NÃO confundir com cartel
    ubiquos = con.execute("""SELECT COUNT(*) FROM (
        SELECT favorecido_cpf FROM ordens_bancarias WHERE favorecido_cpf IS NOT NULL
        GROUP BY favorecido_cpf HAVING COUNT(DISTINCT ug_codigo)>=10)""").fetchone()[0]
    return [("fornecedores_ubiquos",
             f"{ubiquos} fornecedores atuam em >=10 UGs (ubíquos — ex.: utilities/bancos). "
             f"Co-ocorrência entre ubíquos NÃO é indício de cartel; o sinal é entre fornecedores "
             f"NÃO-ubíquos que dividem um conjunto estreito de órgãos.", 0.7, ubiquos)]


def fatos_cobertura_sei(con) -> list[tuple]:
    tot = con.execute("SELECT COUNT(*) FROM ordens_bancarias").fetchone()[0]
    comsei = con.execute("SELECT COUNT(*) FROM ordens_bancarias WHERE TRIM(COALESCE(numero_sei,''))!=''").fetchone()[0]
    siafe = con.execute("SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE TRIM(COALESCE(processo,''))!=''").fetchone()[0]
    if not tot:
        return []  # base vazia: degradar honesto (sem fato) em vez de ZeroDivisionError virar "ERRO" silencioso
    return [("cobertura_ob_sei",
             f"OB↔SEI: {comsei:,}/{tot:,} OBs do TFE com nº SEI ({comsei/tot*100:.2f}%) + {siafe} OBs do SIAFE "
             f"carregam processo na tabela rica. Cobertura limitada pela varredura SIAFE (WAF restringe a VM). "
             f"O Lex deve declarar essa limitação ao opinar sobre processos não lidos.", 0.9, tot)]


def fatos_volume(con) -> list[tuple]:
    r = con.execute("""SELECT COUNT(*), COUNT(DISTINCT ug_codigo), COUNT(DISTINCT favorecido_cpf),
                       MIN(exercicio), MAX(exercicio) FROM ordens_bancarias WHERE exercicio IS NOT NULL""").fetchone()
    p90 = _percentil(con, "ordens_bancarias", "valor", 0.90, "WHERE valor>0")
    if not r[0] or p90 is None:
        return []  # base vazia: sem fato (evita format de None)
    return [("base_volume",
             f"Base: {r[0]:,} OBs (chave única numero_ob+ug+exercício), {r[1]} UGs, {r[2]:,} fornecedores, "
             f"exercícios {r[3]}–{r[4]}. p90 do valor de OB ≈ R$ {p90:,.2f}.", 0.95, r[0])]


_COLETORES = [fatos_volume, fatos_anomalia, fatos_concentracao, fatos_ubiquidade, fatos_cobertura_sei]


def aprender() -> dict:
    """Roda todos os coletores empíricos e faz UPSERT em memoria_aprendizado (fonte='empirico')."""
    if not _DB.exists():
        return {"ok": False, "erro": "compliance.db ausente"}
    con = _con()
    try:
        gravados = []
        for fn in _COLETORES:
            try:
                for chave, valor, conf, nobs in fn(con):
                    ex = con.execute("SELECT id FROM memoria_aprendizado WHERE categoria='empirico' AND chave=?",
                                     (chave,)).fetchone()
                    if ex:
                        con.execute("UPDATE memoria_aprendizado SET valor=?, confianca=?, n_observacoes=?, "
                                    "ultima_vez=datetime('now') WHERE id=?", (valor, conf, nobs, ex[0]))
                    else:
                        con.execute("INSERT INTO memoria_aprendizado (categoria, chave, valor, confianca, "
                                    "n_observacoes, fonte, primeira_vez, ultima_vez) VALUES "
                                    "('empirico', ?, ?, ?, ?, 'empirico', datetime('now'), datetime('now'))",
                                    (chave, valor, conf, nobs))
                    gravados.append(chave)
            except Exception as e:  # noqa: BLE001
                gravados.append(f"{fn.__name__}:ERRO {str(e)[:60]}")
        con.commit()
        return {"ok": True, "aprendizados": gravados,
                "total_memoria": con.execute("SELECT COUNT(*) FROM memoria_aprendizado").fetchone()[0]}
    finally:
        con.close()


# ── consultas pontuais que o Lex chama por caso (contexto empírico de um alvo) ──

def posicao_fornecedor(cnpj: str) -> dict:
    """Onde o fornecedor se situa frente à base: total pago, nº de UGs, percentil de exposição."""
    if not _DB.exists():
        return {}
    con = _con()
    try:
        cpf = "".join(ch for ch in (cnpj or "") if ch.isdigit())
        r = con.execute("""SELECT COUNT(*), COALESCE(SUM(valor),0), COUNT(DISTINCT ug_codigo)
                           FROM ordens_bancarias WHERE favorecido_cpf=?""", (cpf,)).fetchone()
        if not r or not r[0]:
            return {"cnpj": cpf, "tem_dados": False}
        # percentil de exposição entre todos os fornecedores
        total = r[1]
        acima = con.execute("""SELECT COUNT(*) FROM (
            SELECT favorecido_cpf, SUM(valor) v FROM ordens_bancarias WHERE favorecido_cpf IS NOT NULL
            GROUP BY favorecido_cpf HAVING v < ?)""", (total,)).fetchone()[0]
        ntot = con.execute("SELECT COUNT(DISTINCT favorecido_cpf) FROM ordens_bancarias WHERE favorecido_cpf IS NOT NULL").fetchone()[0]
        pct = (acima / ntot * 100) if ntot else 0
        return {"cnpj": cpf, "tem_dados": True, "n_obs": r[0], "total_pago": total,
                "n_ugs": r[2], "percentil_exposicao": round(pct, 1)}
    finally:
        con.close()


def contexto_empirico_md(cnpj: str | None = None) -> str:
    """Bloco curto de contexto empírico para o parecer do Lex (régua da base)."""
    con = _con()
    try:
        fatos = {k: v for k, v in con.execute(
            "SELECT chave, valor FROM memoria_aprendizado WHERE categoria='empirico'")}
    except Exception:
        fatos = {}
    finally:
        con.close()
    L = ["> **Régua empírica (aprendida da base JFN):** " +
         (fatos.get("base_volume", "base em construção") or "")]
    if cnpj:
        pos = posicao_fornecedor(cnpj)
        if pos.get("tem_dados"):
            L.append(f"> **Posição do alvo:** R$ {pos['total_pago']:,.2f} pagos em {pos['n_obs']} OBs / "
                     f"{pos['n_ugs']} UG(s) — percentil {pos['percentil_exposicao']}% de exposição entre os fornecedores do Estado.")
    return "\n".join(L)


if __name__ == "__main__":
    print(json.dumps(aprender(), ensure_ascii=False, indent=2))
