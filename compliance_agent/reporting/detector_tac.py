# -*- coding: utf-8 -*-
"""
Detector determinístico RF-TAC — pagamento FORA de contrato regular por TERMO DE AJUSTE DE CONTAS /
INDENIZAÇÃO / RECONHECIMENTO DE DÍVIDA.

O achado central do caso IDESI/FSERJ codificado como PADRÃO: parte relevante do valor pago a um CNPJ (ou
sistemicamente por uma UG) não sai de um contrato regular licitado, mas de "Termo de Ajuste de Contas" (TAC),
"indenização" ou "reconhecimento de dívida" — instrumentos de regularização *a posteriori* (art. 59, par. único,
Lei 8.666/93; art. 149 Lei 14.133/21) que, quando recorrentes e em alto valor, indicam contratação informal/
emergencial perpetuada e fuga ao dever de licitar.

Função PURA e testável (recebe linhas (valor, observacao) ou um DB path). HONESTO: o % é um indício
quantitativo, não acusação; INDISPONÍVEL (sem `observacao`) ≠ 0%. A regex casa o texto livre da OB (SIAFE).

Quem consome:
  • `/relatorio` (reporting/inteligencia._red_flags) → RF-TAC por CNPJ.
  • Lex §II-E (via rede_fachada) → entra no pacote de sinais e na investigação DD.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

# Regex (pedido do dono): casa os instrumentos de regularização fora de contrato regular no texto livre da OB.
# "RECONHEC...DIVIDA" tolera "RECONHECIMENTO DE DÍVIDA" (a frase natural) — janela de até 12 chars.
_RX_TAC = re.compile(r"AJUSTE DE CONTAS|INDENIZ|RECONHEC.{0,12}D[IÍ]VIDA", re.IGNORECASE)

# Faixas de severidade por % do valor pago via TAC/indenização (sobre o universo COM observação preenchida).
# Conservador: < limiar mínimo não vira red flag (ruído); faixas crescentes = severidade crescente.
_FAIXA_MIN = 10.0  # abaixo disto não dispara (presunção de regularidade; pode ser ajuste pontual legítimo)


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolver_db(db_path=None) -> Path:
    """DB efetivo: arg > JFN_DB > JFN_DATA_DIR/compliance.db (mesma convenção do inteligencia.py)."""
    if db_path:
        return Path(db_path)
    env = os.environ.get("JFN_DB")
    if env:
        return Path(env)
    data = Path(os.environ.get("JFN_DATA_DIR", _root() / "data"))
    return data / "compliance.db"


def _digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _severidade(pct: float, total_tac: float) -> tuple[str, str]:
    """(grau, nivel) por faixa de % — e o valor absoluto reforça (R$100M+ em TAC é grave mesmo a %médio)."""
    if pct >= 50 or (pct >= 30 and total_tac >= 100_000_000):
        return "🔴", "ALTO"
    if pct >= 30 or (pct >= _FAIXA_MIN and total_tac >= 50_000_000):
        return "🟡", "MEDIO"
    return "🟡", "BAIXO"


# ───────────────────────── núcleo PURO (sobre linhas, sem DB) ─────────────────────────

def medir_tac(linhas) -> dict:
    """Mede o % do valor pago via TAC/indenização sobre um conjunto de linhas (valor, observacao).

    Args:
      linhas: iterável de tuplas/dicts com `valor` (float) e `observacao` (str|None).
              Aceita (valor, obs) ou {"valor":, "observacao":}.

    Retorna {n, n_tac, total, total_tac, pct, n_sem_obs, cobertura}.
      • total/pct são sobre TODAS as linhas (denominador = tudo que a entidade recebeu).
      • cobertura distingue "verificado" de INDISPONÍVEL (sem nenhuma observação preenchida).
    HONESTO: se 100% das linhas não têm observação, pct=0 mas cobertura=INDISPONIVEL (≠ "limpo").
    """
    n = n_tac = n_sem_obs = 0
    total = total_tac = 0.0
    for ln in linhas:
        if isinstance(ln, dict):
            v = ln.get("valor")
            obs = ln.get("observacao")
        else:
            v, obs = ln[0], ln[1]
        try:
            v = float(v or 0.0)
        except (TypeError, ValueError):
            v = 0.0
        n += 1
        total += v
        if not (obs or "").strip():
            n_sem_obs += 1
            continue
        if _RX_TAC.search(obs):
            n_tac += 1
            total_tac += v
    pct = (100.0 * total_tac / total) if total else 0.0
    if n == 0:
        cobertura = "INDISPONIVEL (sem pagamentos)"
    elif n_sem_obs == n:
        cobertura = "INDISPONIVEL (nenhuma OB com observação preenchida)"
    elif n_sem_obs:
        cobertura = f"verificado ({n - n_sem_obs}/{n} OBs com observação; {n_sem_obs} sem texto)"
    else:
        cobertura = f"verificado ({n} OBs)"
    return {"n": n, "n_tac": n_tac, "total": round(total, 2), "total_tac": round(total_tac, 2),
            "pct": round(pct, 1), "n_sem_obs": n_sem_obs, "cobertura": cobertura}


def _ro_conn(db: Path) -> sqlite3.Connection | None:
    if not db.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=15)
        con.execute("PRAGMA busy_timeout=15000")
        return con
    except Exception:  # noqa: BLE001
        return None


# ───────────────────────── por CNPJ ─────────────────────────

def tac_por_cnpj(cnpj: str, *, db_path=None) -> dict:
    """% do valor pago a UM CNPJ (matriz+filiais pela raiz de 8 díg) via TAC/indenização.

    Retorna o dict de `medir_tac` + {cnpj, raiz}. Degrada honesto (DB ausente → cobertura INDISPONIVEL).
    """
    raiz = _digitos(cnpj)[:8]
    db = _resolver_db(db_path)
    con = _ro_conn(db)
    if not con or not raiz:
        out = medir_tac([])
        out.update({"cnpj": _digitos(cnpj), "raiz": raiz})
        return out
    try:
        try:
            linhas = con.execute(
                "SELECT valor, observacao FROM ordens_bancarias WHERE favorecido_cpf LIKE ?",
                (f"{raiz}%",)).fetchall()
        except sqlite3.OperationalError:
            linhas = []
    finally:
        con.close()
    out = medir_tac(linhas)
    out.update({"cnpj": _digitos(cnpj), "raiz": raiz})
    return out


# ───────────────────────── por UG (o sistêmico) ─────────────────────────

def tac_por_ug(ug_codigo: str, *, db_path=None) -> dict:
    """% do valor pago por UMA UG pagadora via TAC/indenização (o sinal sistêmico: FSERJ/294200).

    Retorna o dict de `medir_tac` + {ug_codigo, ug_nome}.
    """
    ug = str(ug_codigo or "").strip()
    db = _resolver_db(db_path)
    con = _ro_conn(db)
    if not con or not ug:
        out = medir_tac([])
        out.update({"ug_codigo": ug, "ug_nome": ""})
        return out
    nome = ""
    try:
        try:
            linhas = con.execute(
                "SELECT valor, observacao FROM ordens_bancarias WHERE ug_codigo=?", (ug,)).fetchall()
            r = con.execute(
                "SELECT ug_nome FROM ordens_bancarias WHERE ug_codigo=? AND ug_nome IS NOT NULL LIMIT 1",
                (ug,)).fetchone()
            nome = (r[0] if r else "") or ""
        except sqlite3.OperationalError:
            linhas = []
    finally:
        con.close()
    out = medir_tac(linhas)
    out.update({"ug_codigo": ug, "ug_nome": nome})
    return out


def _ugs_do_cnpj(cnpj: str, db: Path) -> list[tuple[str, str, float]]:
    """UGs pagadoras de um CNPJ (código, nome, total pago a ele por essa UG), maior→menor."""
    raiz = _digitos(cnpj)[:8]
    con = _ro_conn(db)
    if not con or not raiz:
        return []
    try:
        try:
            rows = con.execute(
                "SELECT ug_codigo, MAX(ug_nome), SUM(valor) FROM ordens_bancarias "
                "WHERE favorecido_cpf LIKE ? GROUP BY ug_codigo ORDER BY SUM(valor) DESC",
                (f"{raiz}%",)).fetchall()
        except sqlite3.OperationalError:
            rows = []
    finally:
        con.close()
    return [(str(r[0] or ""), str(r[1] or ""), float(r[2] or 0.0)) for r in rows]


# ───────────────────────── moeda (formatação local, sem dependência) ─────────────────────────

def _moeda(v) -> str:
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ 0,00"


# ───────────────────────── red flag pronta p/ render ─────────────────────────

def red_flag_tac(cnpj: str, *, db_path=None, com_ug: bool = True) -> dict | None:
    """Monta a RF-TAC pronta p/ o relatório (e p/ o pacote do Lex), ou None se não dispara.

    Combina o % por CNPJ com o contexto SISTÊMICO da(s) UG(s) pagadora(s) — "na FSERJ isso é X% de R$Y".

    Retorna {codigo, titulo, descricao, fundamento, status, nivel, grau, pct, total_tac, cnpj_metricas,
             ugs:[…]} ou None.
    """
    db = _resolver_db(db_path)
    m = tac_por_cnpj(cnpj, db_path=db)
    # contexto das UGs pagadoras (sistêmico)
    ugs_ctx: list[dict] = []
    if com_ug:
        for ug, _nm, _tot in _ugs_do_cnpj(cnpj, db)[:3]:
            if not ug:
                continue
            u = tac_por_ug(ug, db_path=db)
            if u.get("pct", 0) >= _FAIXA_MIN:
                ugs_ctx.append(u)
    # dispara se o CNPJ OU a sua UG pagadora têm TAC relevante
    cnpj_dispara = m.get("pct", 0) >= _FAIXA_MIN and m.get("total_tac", 0) > 0
    if not cnpj_dispara and not ugs_ctx:
        return None
    grau, nivel = _severidade(m.get("pct", 0.0), m.get("total_tac", 0.0))
    # se o CNPJ não dispara mas a UG sim, a severidade vem da UG (contexto sistêmico)
    if not cnpj_dispara and ugs_ctx:
        u0 = max(ugs_ctx, key=lambda x: x.get("pct", 0))
        grau, nivel = _severidade(u0.get("pct", 0.0), u0.get("total_tac", 0.0))

    partes = []
    if cnpj_dispara:
        partes.append(
            f"**{m['pct']:.0f}% de {_moeda(m['total'])}** pagos a este fornecedor saíram FORA de contrato "
            f"regular, via Termo de Ajuste de Contas / indenização / reconhecimento de dívida "
            f"({_moeda(m['total_tac'])} em {m['n_tac']} OB(s)).")
    for u in ugs_ctx:
        partes.append(
            f"Na UG pagadora **{u.get('ug_nome') or u.get('ug_codigo')}** ({u.get('ug_codigo')}) o padrão é "
            f"SISTÊMICO: **{u['pct']:.0f}%** de {_moeda(u['total'])} pagos por TAC/indenização "
            f"({_moeda(u['total_tac'])}).")
    desc = (" ".join(partes) + " Regularização *a posteriori* de despesa sem contrato regular, quando "
            "recorrente e vultosa, indica contratação informal/emergencial perpetuada e fuga ao dever de "
            "licitar — apurar a existência de contrato, a causa da 'dívida' e a regularidade dos pagamentos. "
            "(Indício quantitativo; INDISPONÍVEL ≠ 0% — depende da observação da OB.)")
    fund = ("Art. 59, par. único, Lei 8.666/93 (indenização por serviços executados sem contrato); "
            "art. 149 Lei 14.133/21; art. 37 CF/88 (dever de licitar); art. 10 Lei 8.429/92; "
            "ACFE — payments outside contract / off-contract spend.")
    return {
        "codigo": "RF-TAC", "titulo": "RF-TAC — Pagamento fora de contrato regular (TAC/indenização)",
        "descricao": desc, "fundamento": fund, "status": "CONFIRMADO", "nivel": nivel, "grau": grau,
        "pct": m.get("pct", 0.0), "total_tac": m.get("total_tac", 0.0), "total": m.get("total", 0.0),
        "n_tac": m.get("n_tac", 0), "cobertura": m.get("cobertura", ""),
        "cnpj_metricas": m, "ugs": ugs_ctx,
    }


# ───────────────────────── CLI ─────────────────────────

if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Detector RF-TAC (pagamento fora de contrato regular)")
    ap.add_argument("alvo", help="CNPJ (14/8 díg) ou, com --ug, código da UG")
    ap.add_argument("--ug", action="store_true", help="trata o alvo como código de UG")
    a = ap.parse_args()
    if a.ug:
        print(json.dumps(tac_por_ug(a.alvo), ensure_ascii=False, indent=2))
    else:
        rf = red_flag_tac(a.alvo)
        print(json.dumps(rf or {"rf_tac": None, "metricas": tac_por_cnpj(a.alvo)},
                         ensure_ascii=False, indent=2))
