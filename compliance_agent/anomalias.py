# -*- coding: utf-8 -*-
"""
ANOMALIAS — núcleo de detecção de risco da Onda 1 (JFN).

Roda sobre as Ordens Bancárias já no `compliance.db` (sem depender de SIAFE/SEI):
  1. QUALIDADE DE DADO + QUARENTENA (`ob_quarentena`): linhas inválidas saem do ML (valor nulo/≤0, sem
     favorecido, exercício nulo, CNPJ inválido, duplicata por hash). "Anomalia" não pode ser erro de ingestão.
  2. REGRAS DETERMINÍSTICAS (`ob_redflag`): red flags defensáveis sem ML, com peso e parecer de 1 linha —
     valor simbólico (aprendizado CASHPAGO), fracionamento same-day, concentração de fornecedor por UG,
     fracionamento temporal. Cada flag aponta o fundamento legal.
  3. SCORE DE ANOMALIA (`ob_anomaly`): ensemble PyOD ECOD + IForest sobre features (valor, log, frequência/
     concentração do fornecedor, UG, temporalidade); score 0–1 + `top_features` + `dataset_hash` + versão.

Reprodutibilidade forense: cada execução grava `dataset_hash` (estado do banco) e `modelo_versao`.
Princípio de honestidade: score/flag é **fila de investigação interna**, NUNCA acusação pública.

CLI:
    python -m compliance_agent.anomalias --rodar           # roda tudo (quarentena + regras + score)
    python -m compliance_agent.anomalias --rodar --limite 200000   # amostra p/ teste rápido
    python -m compliance_agent.anomalias --top 20          # mostra top anomalias
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd

_DB = os.environ.get("JFN_DB", os.path.join(os.path.dirname(__file__), "..", "data", "compliance.db"))
_DB = os.path.abspath(_DB)

MODELO_VERSAO = "onda1-v1.0"
# Limite de dispensa (Lei 14.133/2021 art. 75, valores atualizados 2024 — bens/serviços comuns).
# Configurável; para obras/serviços de engenharia o teto é ~R$ 119.812,02.
LIMITE_DISPENSA = float(os.environ.get("JFN_LIMITE_DISPENSA", "59906.02"))
CONCENTRACAO_LIMIAR = float(os.environ.get("JFN_CONCENTRACAO_LIMIAR", "0.30"))  # 30% do gasto da UG


# ── infra de tabelas ──────────────────────────────────────────────────────────

_DDL = {
    "ob_quarentena": """
        CREATE TABLE IF NOT EXISTS ob_quarentena (
            ob_id INTEGER, motivo TEXT, detalhe TEXT, gerado_em TEXT
        )""",
    "ob_redflag": """
        CREATE TABLE IF NOT EXISTS ob_redflag (
            ob_id INTEGER, regra TEXT, peso REAL, parecer TEXT, fundamento TEXT, gerado_em TEXT
        )""",
    "ob_anomaly": """
        CREATE TABLE IF NOT EXISTS ob_anomaly (
            ob_id INTEGER PRIMARY KEY, score REAL, top_features TEXT,
            modelo_versao TEXT, dataset_hash TEXT, gerado_em TEXT
        )""",
}


def _con():
    return sqlite3.connect(_DB)


def _ddl(con):
    for sql in _DDL.values():
        con.execute(sql)
    con.execute("CREATE INDEX IF NOT EXISTS ix_redflag_ob ON ob_redflag(ob_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_redflag_regra ON ob_redflag(regra)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_anomaly_score ON ob_anomaly(score)")
    # (NÃO indexar ob_id: já é INTEGER PRIMARY KEY = rowid, indexado nativamente — índice extra seria redundante.)
    con.commit()


def _dataset_hash(con) -> str:
    r = con.execute("SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(ROUND(SUM(valor),2),0) FROM ordens_bancarias").fetchone()
    return hashlib.sha1(f"{r[0]}|{r[1]}|{r[2]}".encode()).hexdigest()[:16]


# ── 1. qualidade de dado / quarentena ─────────────────────────────────────────

def _cnpj_valido(c: str) -> bool:
    """Validação módulo-11 de CNPJ (14 dígitos). CPF (11) ou vazio → não barra aqui."""
    c = "".join(ch for ch in (c or "") if ch.isdigit())
    if len(c) != 14:
        return True  # não é CNPJ de 14 dígitos: não invalida (pode ser CPF/PF)
    if c == c[0] * 14:
        return False
    def dv(base, pesos):
        s = sum(int(d) * p for d, p in zip(base, pesos))
        r = s % 11
        return "0" if r < 2 else str(11 - r)
    d1 = dv(c[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dv(c[:13], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return c[12] == d1 and c[13] == d2


def quarentena(df: pd.DataFrame, con) -> pd.DataFrame:
    """Marca linhas inválidas em ob_quarentena e devolve o DF LIMPO (apto ao ML/regras)."""
    con.execute("DELETE FROM ob_quarentena")
    agora = datetime.now().isoformat(timespec="seconds")
    regs = []
    cpf = df["favorecido_cpf"].fillna("").astype(str)
    nome = df["favorecido_nome"].fillna("").astype(str)

    m_valor = df["valor"].isna() | (df["valor"] <= 0)
    m_semfav = (cpf.str.strip() == "") & (nome.str.strip() == "")
    m_exerc = df["exercicio"].isna()
    cnpj_invalido = ~cpf.map(_cnpj_valido)
    # duplicatas por chave de negócio
    chave = (df["numero_ob"].fillna("").astype(str) + "|" + cpf + "|" +
             df["ug_codigo"].fillna("").astype(str) + "|" + df["valor"].fillna(0).astype(str) + "|" +
             df["data_emissao"].fillna("").astype(str))
    m_dup = chave.duplicated(keep="first")

    for mask, motivo in [
        (m_valor, "valor_nulo_ou_nao_positivo"),
        (m_semfav, "sem_favorecido"),
        (m_exerc, "exercicio_nulo"),
        (cnpj_invalido, "cnpj_modulo11_invalido"),
        (m_dup, "duplicata_chave_negocio"),
    ]:
        for ob_id in df.loc[mask, "id"].tolist():
            regs.append((int(ob_id), motivo, "", agora))

    if regs:
        con.executemany("INSERT INTO ob_quarentena VALUES (?,?,?,?)", regs)
        con.commit()
    excluir = m_valor | m_semfav | m_exerc | cnpj_invalido | m_dup
    return df.loc[~excluir].copy()


# ── 2. regras determinísticas ─────────────────────────────────────────────────

def regras(df: pd.DataFrame, con) -> int:
    """Aplica as 4 regras e grava ob_redflag. Retorna nº de flags."""
    con.execute("DELETE FROM ob_redflag")
    agora = datetime.now().isoformat(timespec="seconds")
    flags = []  # (ob_id, regra, peso, parecer, fundamento)

    # R_VALOR_SIMBOLICO (aprendizado CASHPAGO: R$ 0,01 esconde remuneração extraorçamentária)
    simb = df[(df["valor"] > 0) & (df["valor"] <= 1.0)]
    for _, r in simb.iterrows():
        flags.append((int(r["id"]), "R_VALOR_SIMBOLICO", 0.9,
                      f"Valor simbólico (R$ {r['valor']:.2f}) — economicamente incompatível com objeto; "
                      "indício de remuneração oculta/extraorçamentária a apurar.",
                      "Art. 5º Lei 14.133 (princípios); Lei 8.429/92 art. 10 (dano ao erário) — apurar"))

    # R_CONCENTRACAO: fornecedor > limiar do gasto da UG no exercício
    g = (df.groupby(["ug_codigo", "exercicio", "favorecido_cpf"])["valor"].sum().reset_index(name="tot_forn"))
    ug_tot = df.groupby(["ug_codigo", "exercicio"])["valor"].sum().reset_index(name="tot_ug")
    g = g.merge(ug_tot, on=["ug_codigo", "exercicio"])
    g["share"] = g["tot_forn"] / g["tot_ug"].replace(0, np.nan)
    conc = g[(g["share"] >= CONCENTRACAO_LIMIAR) & (g["tot_ug"] > 0)]
    # marca 1 flag por (fornecedor,UG,ano) na OB de maior valor do grupo (vetorizado via MultiIndex)
    if len(conc):
        _cols = ["ug_codigo", "exercicio", "favorecido_cpf"]
        key_idx = pd.MultiIndex.from_frame(df[_cols])
        conc_idx = pd.MultiIndex.from_frame(conc[_cols])
        sub = df[key_idx.isin(conc_idx)]
        idx = sub.groupby(_cols)["valor"].idxmax()
        cmap = {(r.ug_codigo, r.exercicio, r.favorecido_cpf): r.share for r in conc.itertuples()}
        for _, r in df.loc[idx].iterrows():
            sh = cmap.get((r["ug_codigo"], r["exercicio"], r["favorecido_cpf"]), 0)
            flags.append((int(r["id"]), "R_CONCENTRACAO", min(0.8, 0.4 + sh),
                          f"Fornecedor concentra {sh*100:.0f}% do pago pela UG {r['ug_codigo']} em {r['exercicio']}.",
                          "Art. 37 CF/88; risco de captura (bid rigging) — Art. 36 §3º I 'd' Lei 12.529"))

    # R_FRACIONAMENTO_SAMEDAY: mesmo fornecedor+UG+dia, várias OBs somando > limite de dispensa
    if "data_emissao" in df:
        sd = (df.groupby(["favorecido_cpf", "ug_codigo", "data_emissao"])
                .agg(n=("id", "size"), soma=("valor", "sum"), maxid=("id", "max")).reset_index())
        sd = sd[(sd["n"] >= 2) & (sd["soma"] > LIMITE_DISPENSA)]
        for _, r in sd.iterrows():
            flags.append((int(r["maxid"]), "R_FRACIONAMENTO_SAMEDAY", 0.6,
                          f"{int(r['n'])} OBs ao mesmo fornecedor pela UG {r['ug_codigo']} em {r['data_emissao']} "
                          f"somando R$ {r['soma']:,.2f} (> teto de dispensa R$ {LIMITE_DISPENSA:,.2f}).",
                          "Art. 75 §1º Lei 14.133 (anti-fracionamento); Art. 23 §§1º-5º Lei 8.666"))

    # R_FRACIONAMENTO_MES: mesmo fornecedor+UG no mês com várias OBs abaixo do teto somando acima
    if "data_emissao" in df:
        d = df.dropna(subset=["data_emissao"]).copy()
        d["mes"] = d["data_emissao"].astype(str).str.slice(0, 7)
        mm = (d.groupby(["favorecido_cpf", "ug_codigo", "mes"])
                .agg(n=("id", "size"), soma=("valor", "sum"), maxv=("valor", "max"), maxid=("id", "max")).reset_index())
        mm = mm[(mm["n"] >= 3) & (mm["soma"] > LIMITE_DISPENSA) & (mm["maxv"] < LIMITE_DISPENSA)]
        for _, r in mm.iterrows():
            flags.append((int(r["maxid"]), "R_FRACIONAMENTO_MES", 0.5,
                          f"{int(r['n'])} OBs no mês {r['mes']} (UG {r['ug_codigo']}), cada uma < teto mas somando "
                          f"R$ {r['soma']:,.2f} — possível fracionamento temporal.",
                          "Art. 75 §1º Lei 14.133; Súmula TCU 247"))

    if flags:
        con.executemany("INSERT INTO ob_redflag VALUES (?,?,?,?,?,?)",
                        [(a, b, c, d, e, agora) for (a, b, c, d, e) in flags])
        con.commit()
    return len(flags)


# ── 3. score de anomalia (PyOD ECOD + IForest) ────────────────────────────────

def _features(df: pd.DataFrame) -> tuple[np.ndarray, list]:
    d = df.copy()
    d["valor"] = d["valor"].astype(float)
    d["log_valor"] = np.log1p(d["valor"].clip(lower=0))
    forn_freq = d.groupby("favorecido_cpf")["id"].transform("size")
    forn_tot = d.groupby("favorecido_cpf")["valor"].transform("sum")
    ug_freq = d.groupby("ug_codigo")["id"].transform("size")
    ug_tot = d.groupby(["ug_codigo", "exercicio"])["valor"].transform("sum")
    share_ug = d.groupby(["ug_codigo", "exercicio", "favorecido_cpf"])["valor"].transform("sum") / ug_tot.replace(0, np.nan)
    dt = pd.to_datetime(d["data_emissao"], errors="coerce")
    mes = dt.dt.month.fillna(0)
    dow = dt.dt.dayofweek.fillna(0)
    feats = pd.DataFrame({
        "log_valor": d["log_valor"],
        "forn_freq": np.log1p(forn_freq),
        "forn_tot": np.log1p(forn_tot),
        "ug_freq": np.log1p(ug_freq),
        "share_ug": share_ug.fillna(0),
        "mes": mes, "dow": dow,
    })
    names = list(feats.columns)
    X = feats.to_numpy(dtype=float)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    return X, names


def score(df: pd.DataFrame, con, dataset_hash: str) -> int:
    """Ensemble ECOD + IForest; grava ob_anomaly (score 0–1 + top_features)."""
    from pyod.models.ecod import ECOD
    from pyod.models.iforest import IForest
    from sklearn.preprocessing import StandardScaler

    X, names = _features(df)
    Xs = StandardScaler().fit_transform(X)

    def norm(s):
        s = np.asarray(s, dtype=float)
        lo, hi = np.nanpercentile(s, 1), np.nanpercentile(s, 99)
        return np.clip((s - lo) / (hi - lo + 1e-9), 0, 1)

    ecod = ECOD()
    ecod.fit(Xs)
    s_ecod = norm(ecod.decision_scores_)

    n = len(Xs)
    samp = Xs if n <= 150_000 else Xs[np.random.RandomState(42).choice(n, 150_000, replace=False)]
    iforest = IForest(n_estimators=120, max_samples=256, random_state=42, n_jobs=-1)
    iforest.fit(samp)
    s_if = norm(iforest.decision_function(Xs))

    final = (s_ecod + s_if) / 2.0
    # top features por |z| da própria linha (explicabilidade leve)
    z = np.abs(Xs)
    top_idx = np.argsort(-z, axis=1)[:, :3]

    agora = datetime.now().isoformat(timespec="seconds")
    con.execute("DELETE FROM ob_anomaly")
    rows = []
    ids = df["id"].tolist()
    for i, ob_id in enumerate(ids):
        tf = [names[j] for j in top_idx[i]]
        rows.append((int(ob_id), float(final[i]), json.dumps(tf, ensure_ascii=False),
                     MODELO_VERSAO, dataset_hash, agora))
    con.executemany("INSERT OR REPLACE INTO ob_anomaly VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    return len(rows)


# ── orquestração ──────────────────────────────────────────────────────────────

def rodar(limite: int | None = None) -> dict:
    con = _con()
    _ddl(con)
    dh = _dataset_hash(con)
    q = "SELECT id, numero_ob, data_emissao, ug_codigo, favorecido_cpf, favorecido_nome, valor, exercicio FROM ordens_bancarias"
    if limite:
        q += f" LIMIT {int(limite)}"
    df = pd.read_sql(q, con)
    total = len(df)
    limpo = quarentena(df, con)
    n_quar = total - len(limpo)
    n_flags = regras(limpo, con)
    n_score = score(limpo, con, dh) if len(limpo) else 0
    con.close()
    return {"ok": True, "total": total, "quarentena": n_quar, "analisadas": len(limpo),
            "red_flags": n_flags, "scores": n_score, "dataset_hash": dh, "modelo_versao": MODELO_VERSAO}


# Rótulos legíveis das features do score (explicabilidade — equivalente honesto a SHAP p/ o ensemble ECOD+IForest;
# o top_features já guarda as 3 features de maior |z| por OB).
_FEATURE_LABELS = {
    "log_valor": "valor atípico para o conjunto (muito alto ou muito baixo)",
    "forn_freq": "frequência de pagamentos a este fornecedor fora do padrão",
    "forn_tot": "volume total pago a este fornecedor atípico",
    "ug_freq": "volume de OBs desta UG fora do padrão",
    "share_ug": "fatia do fornecedor na UG/exercício muito alta (concentração)",
    "mes": "mês atípico (ex.: concentração em fim de exercício)",
    "dow": "dia da semana atípico para o pagamento",
}


def explicar_features(top_features) -> list[str]:
    """Traduz os top_features (nomes) em motivos legíveis — por que a OB entrou na fila de anomalia."""
    if isinstance(top_features, str):
        try:
            top_features = json.loads(top_features)
        except Exception:
            top_features = [top_features]
    return [_FEATURE_LABELS.get(f, f) for f in (top_features or [])]


# Favorecidos que NÃO são fornecedores de contratação: transferências intra-governamentais,
# tributos e encargos (o Estado paga a si mesmo / à União). Poluem o ranking de anomalias de
# COMPRA — são pagamentos obrigatórios, não licitação. Filtrados por padrão (incluir_gov reinclui).
_NAO_FORNECEDOR = re.compile(
    r"\b(estado do rio|munic[ií]pio d|prefeitura|uni[ãa]o|minist[ée]rio|secretaria de estado|"
    r"tesouro|receita federal|fazenda nacional|procuradoria|inss|instituto nacional do seguro|"
    r"seguro social|fgts|pasep|\bpis\b|caixa econ[oô]mica|banco central|tribunal de|"
    r"c[âa]mara municipal|assembleia legislativa|defensoria|encargos gerais)\b", re.I)


def _eh_nao_fornecedor(nome: str) -> bool:
    return bool(_NAO_FORNECEDOR.search(nome or ""))


def top_anomalias(limite: int = 20, orgao: str | None = None, fornecedor: str | None = None,
                  incluir_gov: bool = False) -> list[dict]:
    """Ranking de OBs por score, com red flags agregadas. Lê ob_anomaly JOIN ordens_bancarias/ob_redflag.
    Por padrão EXCLUI transferências intra-governamentais/tributos (não são fornecedores de compra)."""
    con = _con()
    _ddl(con)
    where, params = [], []
    if orgao:
        where.append("(o.ug_codigo = ? OR o.ug_nome LIKE ?)"); params += [orgao, f"%{orgao}%"]
    if fornecedor:
        where.append("(o.favorecido_cpf = ? OR o.favorecido_nome LIKE ?)"); params += [fornecedor, f"%{fornecedor}%"]
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    # sobre-busca p/ compensar o filtro de não-fornecedor (feito em Python, robusto a acento/caixa)
    fetch = int(limite) if incluir_gov else int(limite) * 4 + 20
    sql = f"""
        SELECT o.id, o.numero_ob, o.data_emissao, o.ug_codigo, o.ug_nome,
               o.favorecido_cpf, o.favorecido_nome, o.valor, a.score, a.top_features,
               (SELECT GROUP_CONCAT(rf.regra, ', ') FROM ob_redflag rf WHERE rf.ob_id=o.id) AS regras,
               (SELECT GROUP_CONCAT(rf.parecer, ' | ') FROM ob_redflag rf WHERE rf.ob_id=o.id) AS pareceres
        FROM ob_anomaly a JOIN ordens_bancarias o ON o.id=a.ob_id
        {wsql}
        ORDER BY (a.score + (SELECT COALESCE(SUM(rf.peso),0) FROM ob_redflag rf WHERE rf.ob_id=o.id)) DESC
        LIMIT ?"""
    params.append(fetch)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(sql, params).fetchall()]
    con.close()
    if not incluir_gov:
        rows = [r for r in rows if not _eh_nao_fornecedor(r.get("favorecido_nome"))]
    return rows[:int(limite)]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Detecção de anomalias/red-flags sobre as OBs (Onda 1).")
    ap.add_argument("--rodar", action="store_true", help="roda quarentena + regras + score")
    ap.add_argument("--limite", type=int, default=None, help="amostra (nº de OBs) p/ teste rápido")
    ap.add_argument("--top", type=int, default=0, help="mostra top N anomalias")
    ap.add_argument("--orgao", type=str, default=None)
    ap.add_argument("--fornecedor", type=str, default=None)
    a = ap.parse_args()
    if a.rodar:
        print(json.dumps(rodar(a.limite), ensure_ascii=False, indent=2))
    if a.top:
        for r in top_anomalias(a.top, a.orgao, a.fornecedor):
            print(f"[{r['score']:.2f}] OB {r['numero_ob']} | UG {r['ug_codigo']} | {r['favorecido_nome']} | "
                  f"R$ {r['valor']:,.2f} | flags: {r['regras'] or '-'}")
