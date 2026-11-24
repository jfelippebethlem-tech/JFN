# -*- coding: utf-8 -*-
"""
ANOMALIAS — núcleo de detecção de risco da Onda 1 (JFN).

Roda sobre as OB PAGAS do SIAFE já no `compliance.db` (`ob_orcamentaria_siafe`, régua `_ob_paga`, credor CNPJ/CPF).
24/11/2026: até aqui rodava sobre o espelho TFE (`ordens_bancarias`) — regra da casa é OB = SIAFE (decisão do dono:
"OBs são o principal; TFE pode ter erro"). As tabelas do modelo passaram a `*_siafe`, chaveadas pela PK do SIAFE
(numero_ob, ug, exercicio): o coletor grava com INSERT OR REPLACE e o rowid não é estável. As tabelas antigas
(`ob_anomaly`/`ob_redflag`/`ob_quarentena`, ids do TFE) ficam paradas, sem leitor no produto.
Etapas:
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
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd
from compliance_agent.reporting.intel_base import moeda
from compliance_agent.cpf_cnpj import cnpj_valido as _cnpj_dv, digitos as _digitos

_DB = os.environ.get("JFN_DB", os.path.join(os.path.dirname(__file__), "..", "data", "compliance.db"))
_DB = os.path.abspath(_DB)

from compliance_agent.limites_dispensa import limite_dispensa as _limite_do_ano  # noqa: E402

MODELO_VERSAO = "onda1-v2.0-siafe"
# Limite de dispensa (Lei 14.133/2021 art. 75-II, bens/serviços comuns). O teto é POR EXERCÍCIO e
# vem da fonte única `limites_dispensa` — esta linha já carregou o valor de 2024 fixo, aplicado a
# todos os anos: em 2025 e 2026 acusava fracionamento abaixo do teto legal (falso positivo) e em
# 2021-2023 deixava passar (falso negativo). Era a 4ª cópia divergente encontrada no projeto.
# O env continua valendo como override manual de teste; sem ele, o default é o teto do ano
# corrente vindo da fonte única — nunca um número escrito aqui.
LIMITE_DISPENSA = float(os.environ.get("JFN_LIMITE_DISPENSA")
                        or _limite_do_ano(datetime.now().year, "compras"))


def _teto(exercicio) -> float:
    """Teto de dispensa do exercício (art. 75-II). Override por env vence, para teste."""
    if os.environ.get("JFN_LIMITE_DISPENSA"):
        return LIMITE_DISPENSA
    try:
        return _limite_do_ano(int(exercicio), "compras")
    except (TypeError, ValueError):
        return LIMITE_DISPENSA


CONCENTRACAO_LIMIAR = float(os.environ.get("JFN_CONCENTRACAO_LIMIAR", "0.30"))  # 30% do gasto da UG


# ── infra de tabelas ──────────────────────────────────────────────────────────

_DDL = {
    "ob_quarentena_siafe": """
        CREATE TABLE IF NOT EXISTS ob_quarentena_siafe (
            numero_ob TEXT, ug TEXT, exercicio INTEGER, motivo TEXT, detalhe TEXT, gerado_em TEXT
        )""",
    "ob_redflag_siafe": """
        CREATE TABLE IF NOT EXISTS ob_redflag_siafe (
            numero_ob TEXT, ug TEXT, exercicio INTEGER, regra TEXT, peso REAL, parecer TEXT, fundamento TEXT,
            gerado_em TEXT
        )""",
    "ob_anomaly_siafe": """
        CREATE TABLE IF NOT EXISTS ob_anomaly_siafe (
            numero_ob TEXT, ug TEXT, exercicio INTEGER, score REAL, top_features TEXT,
            modelo_versao TEXT, dataset_hash TEXT, gerado_em TEXT, PRIMARY KEY (numero_ob, ug, exercicio)
        )""",
}

# OB paga do SIAFE no formato que o modelo usa (data ISO; `id` = posição na leitura, só dentro de UMA execução —
# o que se grava é a chave do SIAFE)
def _sql_ob_siafe(con) -> str:
    from compliance_agent.cruzamentos_intel import _ob_paga
    from compliance_agent.reporting.intel_base import SQL_CREDOR_TERCEIRO_SIAFE
    from compliance_agent.reporting.cobertura_siafe import ISO_EMISSAO_SIAFE
    return (f"SELECT numero_ob, {ISO_EMISSAO_SIAFE} AS data_emissao, ug_emitente AS ug_codigo, "
            f"credor AS favorecido_cpf, nome_credor AS favorecido_nome, valor, exercicio "
            f"FROM ob_orcamentaria_siafe WHERE {_ob_paga(con)} AND {SQL_CREDOR_TERCEIRO_SIAFE}")


def _chaves(df: pd.DataFrame, ids) -> list[tuple]:
    """id (posição na execução) → chave do SIAFE (numero_ob, ug, exercicio)."""
    sub = df.set_index("id").loc[list(ids), ["numero_ob", "ug_codigo", "exercicio"]]
    return [(str(a), str(b), int(c) if pd.notna(c) else None) for a, b, c in sub.itertuples(index=False)]


def _con():
    return sqlite3.connect(_DB)


def _ddl(con):
    for sql in _DDL.values():
        con.execute(sql)
    con.execute("CREATE INDEX IF NOT EXISTS ix_redflag_siafe_ob ON ob_redflag_siafe(numero_ob, ug, exercicio)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_redflag_siafe_regra ON ob_redflag_siafe(regra)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_anomaly_siafe_score ON ob_anomaly_siafe(score)")
    con.commit()


def _dataset_hash(con) -> str:
    # ob-qualquer-status: impressão digital do estado da tabela (reprodutibilidade), não soma de pagamento
    r = con.execute("SELECT COUNT(*), COALESCE(MAX(coletado_em),''), COALESCE(ROUND(SUM(valor),2),0) "
                    "FROM ob_orcamentaria_siafe").fetchone()
    return hashlib.sha1(f"{r[0]}|{r[1]}|{r[2]}".encode()).hexdigest()[:16]


# ── 1. qualidade de dado / quarentena ─────────────────────────────────────────

def _cnpj_valido(c: str) -> bool:
    """CPF (11) ou vazio → não barra aqui; 14 dígitos → dígito verificador (fonte única `cpf_cnpj`)."""
    return len(_digitos(c)) != 14 or _cnpj_dv(c)


def quarentena(df: pd.DataFrame, con) -> pd.DataFrame:
    """Marca linhas inválidas em ob_quarentena e devolve o DF LIMPO (apto ao ML/regras)."""
    con.execute("DELETE FROM ob_quarentena_siafe")
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
        for k in _chaves(df, df.loc[mask, "id"].tolist()):
            regs.append((*k, motivo, "", agora))

    if regs:
        con.executemany("INSERT INTO ob_quarentena_siafe VALUES (?,?,?,?,?,?)", regs)
        con.commit()
    excluir = m_valor | m_semfav | m_exerc | cnpj_invalido | m_dup
    return df.loc[~excluir].copy()


# ── 2. regras determinísticas ─────────────────────────────────────────────────

def regras(df: pd.DataFrame, con) -> int:
    """Aplica as 4 regras e grava ob_redflag. Retorna nº de flags."""
    con.execute("DELETE FROM ob_redflag_siafe")
    agora = datetime.now().isoformat(timespec="seconds")
    flags = []  # (ob_id, regra, peso, parecer, fundamento)

    # Repasse intragoverno, tributo e encargo NÃO são contratação: não existe fracionamento nem
    # captura de fornecedor em pagamento obrigatório. O filtro já existia no módulo e era aplicado
    # só no RELATÓRIO — as regras rodavam sobre tudo. Medido no acervo: dos 4.453 grupos que a
    # regra same-day marcava com credor CNPJ, 349 eram repasse fundo-a-fundo do SUS e transferência
    # a fundo municipal de saúde. `df_c` = universo de CONTRATAÇÃO.
    df_c = df[~df["favorecido_nome"].map(_eh_nao_fornecedor).fillna(False)] \
        if "favorecido_nome" in df else df

    # R_VALOR_SIMBOLICO (aprendizado CASHPAGO: R$ 0,01 esconde remuneração extraorçamentária)
    simb = df[(df["valor"] > 0) & (df["valor"] <= 1.0)]
    for _, r in simb.iterrows():
        flags.append((int(r["id"]), "R_VALOR_SIMBOLICO", 0.9,
                      f"Valor simbólico (R$ {r['valor']:.2f}) — economicamente incompatível com objeto; "
                      "indício de remuneração oculta/extraorçamentária a apurar.",
                      "Art. 5º Lei 14.133 (princípios); Lei 8.429/92 art. 10 (dano ao erário) — apurar"))

    # R_CONCENTRACAO: fornecedor > limiar do gasto da UG no exercício
    g = (df_c.groupby(["ug_codigo", "exercicio", "favorecido_cpf"])["valor"].sum().reset_index(name="tot_forn"))
    ug_tot = df_c.groupby(["ug_codigo", "exercicio"])["valor"].sum().reset_index(name="tot_ug")
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
    if "data_emissao" in df_c:
        sd = (df_c.groupby(["favorecido_cpf", "ug_codigo", "data_emissao", "exercicio"])
                .agg(n=("id", "size"), soma=("valor", "sum"), maxv=("valor", "max"), maxid=("id", "max")).reset_index())
        sd["teto"] = sd["exercicio"].map(_teto)
        # 23/11/2026: sem `maxv < teto` a regra acusava grupo com OB individual ACIMA do teto — parcela de contrato,
        # não fatia (fatiar é caber embaixo). Mesma correção de `rules/engine._regra_ob_fracionamento`, onde 106 dos
        # 107 alertas gravados eram isso; a regra do MÊS, abaixo, já exigia.
        sd = sd[(sd["n"] >= 2) & (sd["soma"] > sd["teto"]) & (sd["maxv"] < sd["teto"])]
        for _, r in sd.iterrows():
            flags.append((int(r["maxid"]), "R_FRACIONAMENTO_SAMEDAY", 0.3,
                          f"{int(r['n'])} OBs ao mesmo fornecedor pela UG {r['ug_codigo']} em {r['data_emissao']} "
                          f"somando R$ {moeda(r['soma'])} (> teto de dispensa de {r['exercicio']}: "
                          f"R$ {moeda(r['teto'])}). RESSALVA: esta tabela não traz processo/empenho, "
                          f"então NÃO se pôde excluir execução de um MESMO contrato licitado — que é "
                          f"pagamento normal, não fracionamento. Sinal FRACO: só vale em convergência.",
                          "Art. 75 §1º Lei 14.133 (anti-fracionamento); Art. 23 §§1º-5º Lei 8.666"))

    # R_FRACIONAMENTO_MES: mesmo fornecedor+UG no mês com várias OBs abaixo do teto somando acima
    if "data_emissao" in df_c:
        d = df_c.dropna(subset=["data_emissao"]).copy()
        d["mes"] = d["data_emissao"].astype(str).str.slice(0, 7)
        mm = (d.groupby(["favorecido_cpf", "ug_codigo", "mes", "exercicio"])
                .agg(n=("id", "size"), soma=("valor", "sum"), maxv=("valor", "max"), maxid=("id", "max")).reset_index())
        mm["teto"] = mm["exercicio"].map(_teto)
        mm = mm[(mm["n"] >= 3) & (mm["soma"] > mm["teto"]) & (mm["maxv"] < mm["teto"])]
        for _, r in mm.iterrows():
            flags.append((int(r["maxid"]), "R_FRACIONAMENTO_MES", 0.5,
                          f"{int(r['n'])} OBs no mês {r['mes']} (UG {r['ug_codigo']}), cada uma < teto mas somando "
                          f"R$ {moeda(r['soma'])} — possível fracionamento temporal.",
                          "Art. 75 §1º Lei 14.133; Súmula TCU 247"))

    if flags:
        chave = dict(zip([f[0] for f in flags], _chaves(df, [f[0] for f in flags])))
        con.executemany("INSERT INTO ob_redflag_siafe VALUES (?,?,?,?,?,?,?,?)",
                        [(*chave[a], b, c, d, e, agora) for (a, b, c, d, e) in flags])
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
    con.execute("DELETE FROM ob_anomaly_siafe")
    rows = []
    for i, k in enumerate(_chaves(df, df["id"].tolist())):
        tf = [names[j] for j in top_idx[i]]
        rows.append((*k, float(final[i]), json.dumps(tf, ensure_ascii=False),
                     MODELO_VERSAO, dataset_hash, agora))
    con.executemany("INSERT OR REPLACE INTO ob_anomaly_siafe VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return len(rows)


# ── orquestração ──────────────────────────────────────────────────────────────

def rodar(limite: int | None = None) -> dict:
    con = _con()
    _ddl(con)
    dh = _dataset_hash(con)
    q = _sql_ob_siafe(con)
    if limite:
        q += f" LIMIT {int(limite)}"
    df = pd.read_sql(q, con)
    df.insert(0, "id", range(len(df)))
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


# Favorecidos que NÃO são fornecedores de contratação (intra-gov/tributos) — classificador
# compartilhado em compliance_agent.entidades_gov (reusado também pelo cartel/captura).
from compliance_agent.entidades_gov import eh_nao_fornecedor as _eh_nao_fornecedor  # noqa: E402


def top_anomalias(limite: int = 20, orgao: str | None = None, fornecedor: str | None = None,
                  incluir_gov: bool = False) -> list[dict]:
    """Ranking de OBs por score, com red flags agregadas. Lê ob_anomaly_siafe ⋈ ob_orcamentaria_siafe/ob_redflag_siafe
    (OB paga do SIAFE). Por padrão EXCLUI transferências intra-governamentais/tributos (não são fornecedores de compra).
    Modelo ainda não rodado sobre o SIAFE → lista vazia; quem publica pergunta `estado_modelo()` (INDISPONÍVEL ≠ 0)."""
    con = _con()
    _ddl(con)
    where, params = [], []
    if orgao:
        where.append("o.ug_emitente = ?"); params += [orgao]
    if fornecedor:
        where.append("(o.credor = ? OR o.nome_credor LIKE ?)"); params += [fornecedor, f"%{fornecedor}%"]
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    _rf = "WHERE rf.numero_ob=a.numero_ob AND rf.ug=a.ug AND rf.exercicio=a.exercicio"
    # sobre-busca p/ compensar o filtro de não-fornecedor (feito em Python, robusto a acento/caixa)
    fetch = int(limite) if incluir_gov else int(limite) * 4 + 20
    sql = f"""
        SELECT o.numero_ob, o.data_emissao, o.ug_emitente AS ug_codigo, '' AS ug_nome,
               o.credor AS favorecido_cpf, o.nome_credor AS favorecido_nome, o.valor, a.score, a.top_features,
               (SELECT GROUP_CONCAT(rf.regra, ', ') FROM ob_redflag_siafe rf {_rf}) AS regras,
               (SELECT GROUP_CONCAT(rf.parecer, ' | ') FROM ob_redflag_siafe rf {_rf}) AS pareceres
        FROM ob_anomaly_siafe a JOIN ob_orcamentaria_siafe o
             ON o.numero_ob=a.numero_ob AND o.ug_emitente=a.ug AND o.exercicio=a.exercicio
        {wsql}
        ORDER BY (a.score + (SELECT COALESCE(SUM(rf.peso),0) FROM ob_redflag_siafe rf {_rf})) DESC
        LIMIT ?"""
    params.append(fetch)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(sql, params).fetchall()]
    con.close()
    if not incluir_gov:
        rows = [r for r in rows if not _eh_nao_fornecedor(r.get("favorecido_nome"))]
    rows = rows[:int(limite)]
    # nome canônico da UG no display (ITERJ p/ 133100), consistente com os relatórios
    from compliance_agent import ugs as _ugs
    for r in rows:
        r["ug_nome"] = _ugs.nome_canonico(str(r.get("ug_codigo") or ""), fallback="") or r.get("ug_nome")
    return rows


def estado_modelo() -> dict:
    """Estado do modelo sobre o SIAFE: VERIFICADO (rodou: n, versão, quando) ou INDISPONÍVEL (nunca rodou sobre o
    SIAFE) — para a rota não publicar "0 anomalias" quando o modelo simplesmente não existe."""
    con = _con()
    try:
        _ddl(con)
        n, versao, quando = con.execute(
            "SELECT COUNT(*), MAX(modelo_versao), MAX(gerado_em) FROM ob_anomaly_siafe").fetchone()
    finally:
        con.close()
    if not n:
        return {"estado": "INDISPONÍVEL", "motivo": "modelo ainda não rodado sobre a OB paga do SIAFE "
                "(python -m compliance_agent.anomalias --rodar)"}
    return {"estado": "VERIFICADO", "n_obs_pontuadas": n, "modelo_versao": versao, "gerado_em": quando,
            "fonte": "OB paga do SIAFE (ob_orcamentaria_siafe, régua _ob_paga), credor CNPJ/CPF"}


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
                  f"R$ {moeda(r['valor'])} | flags: {r['regras'] or '-'}")
