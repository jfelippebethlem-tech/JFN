"""Eleição 2026 (1º turno) — RJ seção por seção + cruzamento de Jorge Felippe Neto (22800).

Entrada: eleicao2026_rj_secao.sqlite (tools/tse_bu_2026.py), locais 2026/2022, totais oficiais,
jfn_2022_secao_RJ.csv. Saída: output/eleicoes2026/ (xlsx, csv.gz e dados.json do relatório).

Cruzamento = inferência ECOLÓGICA (seção, não eleitor): correlação entre a fatia de JFN e a fatia de
cada candidato nas mesmas seções, e "lift" nos redutos (decil superior de JFN). Indica afinidade
territorial de voto (possível dobrada), não prova que o mesmo eleitor votou nos dois.
"""
import json
import os
import sqlite3

import numpy as np
import pandas as pd

T = os.path.expanduser("~/JFN/data/tse_cache")
OUT = os.path.expanduser("~/JFN/output/eleicoes2026")
JFN = 22800
RIO = 60011
CARGOS = {1: "Presidente", 3: "Governador", 5: "Senador", 6: "Deputado Federal", 7: "Deputado Estadual"}

AP = {
    "AP1 · Centro": "CENTRO|LAPA|GAMBOA|SAÚDE|SANTO CRISTO|CAJU|CIDADE NOVA|ESTÁCIO|RIO COMPRIDO|SANTA TERESA|"
                    "SÃO CRISTÓVÃO|BENFICA|MANGUEIRA|vasco da gama|PAQUETÁ|BAIRRO DE FÁTIMA|CATUMBI",
    "AP2.1 · Zona Sul": "BOTAFOGO|CATETE|COPACABANA|COSME VELHO|FLAMENGO|GÁVEA|GLÓRIA|HUMAITA|IPANEMA|"
                        "JARDIM BOTÂNICO|LAGOA|LARANJEIRAS|LEBLON|LEME|ROCINHA|SÃO CONRADO|URCA|VIDIGAL",
    "AP2.2 · Grande Tijuca": "ALTO DA BOA VISTA|ANDARAÍ|GRAJAÚ|MARACANÃ|PRAÇA DA BANDEIRA|TIJUCA|VILA ISABEL",
    "AP4 · Barra e Jacarepaguá": "ANIL|BARRA DA TIJUCA|barra olímpica|CAMORIM|CIDADE DE DEUS|CURICICA|FREGUESIA JPA|"
                                 "GARDENIA AZUL|ITANHANGÁ|PECHINCHA|PRAÇA SECA|RECREIO|RIO DAS PEDRAS|TANQUE|"
                                 "TAQUARA|VARGEM GRANDE|VARGEM PEQUENA|VILA VALQUEIRE",
    "AP5 · Zona Oeste": "BANGU|BARRA DE GUARATIBA|CAMPO GRANDE|COSMOS|DEODORO|GUARATIBA|ILHA DE GUARATIBA|INHOAÍBA|"
                        "JARDIM SULACAP|MAGALHÃES BASTOS|PACIÊNCIA|PADRE MIGUEL|PEDRA DE GUARATIBA|REALENGO|"
                        "SANTA CRUZ|SANTÍSSIMO|SENADOR CAMARÁ|SENADOR VASCONCELOS|SEPETIBA|VILA MILITAR|"
                        "JARDIM BANGU|VILA KENNEDY|AUGUSTO VASCONCELOS",
}
BAIRRO_AP = {b.upper(): ap for ap, s in AP.items() for b in s.split("|")}
ZONA_OESTE = ("AP4 · Barra e Jacarepaguá", "AP5 · Zona Oeste")
SIGLA = {1: "Pres", 3: "Gov", 5: "Sen", 6: "DepFed", 7: "DepEst"}
# federais pedidos pelo dono para o comparativo seção a seção na capital (homônimos: ficou o mais votado)
FEDS = {2222: "Soraya Santos", 1177: "Dr. Luizinho", 4400: "Bernardo Rossi", 2212: "General Pazuello",
        7090: "Onassis", 2767: "Flavio Galvão", 2269: "Altineu Côrtes", 1522: "Pastor Junior Trovão"}


def regiao(mun, bairro):
    if mun != RIO:
        return "Fora da capital"
    return BAIRRO_AP.get(str(bairro).upper(), "AP3 · Zona Norte")


def nomes():
    """número → (nome de urna, partido, situação, votos oficiais) por cargo, dos totais oficiais do TSE."""
    out = {}
    for cargo, arq in ((1, "rj-c0001-6257-u.json"), (3, "rj-c0003-u.json"), (5, "rj-c0005-u.json"),
                       (6, "rj-c0006-u.json"), (7, "rj-c0007-u.json")):
        d = json.load(open(f"{T}/totais2026/{arq}"))
        for a in d["carg"][0]["agr"]:
            for p in a["par"]:
                for x in p["cand"]:
                    out[(cargo, int(x["n"]))] = (x["nmu"], p["sg"], x.get("st", ""), int(x["vap"]))
                out.setdefault((cargo, int(p["n"])), (f"LEGENDA {p['sg']}", p["sg"], "legenda", None))
    return out


def locais(ano):
    df = pd.read_csv(f"{T}/eleitorado_local_votacao_{ano}_RJ.csv", sep=";", encoding="latin1", dtype=str)
    df = df[df["NR_TURNO"] == "1"]
    df = df.rename(columns={"CD_MUNICIPIO": "municipio", "NR_ZONA": "zona", "NR_SECAO": "secao"})
    for c in ("municipio", "zona", "secao"):
        df[c] = df[c].astype(int)
    df["lat"] = pd.to_numeric(df["NR_LATITUDE"].str.replace(",", "."), errors="coerce")
    df["lon"] = pd.to_numeric(df["NR_LONGITUDE"].str.replace(",", "."), errors="coerce")
    df["eleitores"] = pd.to_numeric(df["QT_ELEITOR_SECAO"], errors="coerce")
    return df


def corr_controlada(x, y, grupo):
    """Correlação DENTRO do grupo (efeito fixo): tira de cada fatia a média do seu grupo antes de
    correlacionar. Sem isso, dois candidatos fortes em regiões diferentes da cidade saem com correlação
    perto de zero ou negativa mesmo andando juntos dentro de cada região (Jorge na AP5, Pazuello na
    Zona Sul: bruta -0,01, dentro da AP +0,05)."""
    x, y, grupo = pd.Series(x).reset_index(drop=True), pd.Series(y).reset_index(drop=True), pd.Series(grupo).reset_index(drop=True)
    ok = x.notna() & y.notna()
    x, y, grupo = x[ok], y[ok], grupo[ok]
    a = x - x.groupby(grupo).transform("mean")
    b = y - y.groupby(grupo).transform("mean")
    return float(np.corrcoef(a, b)[0, 1]) if len(a) > 2 and a.std() > 0 and b.std() > 0 else None


def lift_controlado(fj, votos, validos, grupo, q=0.9):
    """Índice de reduto controlado: reduto = decil superior de Jorge DENTRO de cada grupo; o esperado é a
    fatia do federal no próprio grupo aplicada aos válidos do reduto. 1,00 = neutro."""
    df = pd.DataFrame({"fj": pd.Series(fj).values, "v": pd.Series(votos).values, "val": pd.Series(validos).values,
                       "g": pd.Series(grupo).values}).dropna(subset=["fj"])
    red = df.fj >= df.groupby("g").fj.transform(lambda s: s.quantile(q))
    taxa = df.groupby("g").v.sum() / df.groupby("g").val.sum()
    esperado = (df.loc[red, "val"] * df.loc[red, "g"].map(taxa)).sum()
    return float(df.loc[red, "v"].sum() / esperado) if esperado else None


def checar_neutro(html, contexto):
    """Gate de neutralidade do entregável. Nome público do cadastro do TSE (bairro "Marechal Hermes",
    "CIEP Ministro Hermes de Lima") casa com termo proibido sem ser menção interna: só esses nomes,
    tirados do próprio dado, são retirados antes da checagem."""
    import re
    import sys
    sys.path.insert(0, os.path.expanduser("~/JFN"))
    from compliance_agent.reporting.neutralidade import termos_proibidos
    loc = locais(2026)
    nomes = pd.concat([loc.NM_BAIRRO, loc.NM_LOCAL_VOTACAO]).dropna().unique()
    publicos = sorted({n for n in nomes if termos_proibidos(n)}, key=len, reverse=True)
    texto = html
    for n in publicos:
        texto = re.sub(re.escape(n), "", texto, flags=re.I)
    texto = re.sub(r"(?i)marechal hermes", "", texto)
    termos = termos_proibidos(texto)
    assert not termos, f"{contexto}: termo interno {termos}"


def main():
    os.makedirs(OUT, exist_ok=True)
    con = sqlite3.connect(f"{T}/eleicao2026_rj_secao.sqlite")
    nm = nomes()
    loc = locais(2026)
    # seções agregadas votam na principal: soma os eleitores das agregadas na principal
    princ = loc[loc["CD_TIPO_SECAO_AGREGADA"] == "1"][["municipio", "zona", "secao", "NM_MUNICIPIO",
                                                      "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "DS_ENDERECO",
                                                      "NM_BAIRRO", "lat", "lon"]]
    princ = princ.drop_duplicates(["municipio", "zona", "secao"])

    v = pd.read_sql("SELECT * FROM voto WHERE cargo IN (3,5,6,7,1)", con)
    sec = pd.read_sql("SELECT municipio,zona,secao,eleicao,cargo,aptos,comparecimento,soma_votos FROM secao", con)
    print("votos", len(v), "seções", sec[["municipio", "zona", "secao"]].drop_duplicates().shape[0])

    # ---------- conferência contra o total oficial ----------
    tot = v[v.tipo == "nominal"].groupby(["cargo", "numero"]).qtd.sum()
    conf = []
    for (cargo, n), (nmu, sg, st, vap) in nm.items():
        if vap is not None and cargo != 1:
            conf.append((CARGOS[cargo], n, nmu, vap, int(tot.get((cargo, n), 0))))
    conf = pd.DataFrame(conf, columns=["cargo", "numero", "nome", "oficial_TSE", "soma_secoes"])
    conf["diferenca"] = conf.soma_secoes - conf.oficial_TSE
    print("conferência: candidatos com diferença ≠ 0:", (conf.diferenca != 0).sum(), "de", len(conf))

    # ---------- base longa por seção ----------
    # voto nominal em número fora da lista oficial = candidatura com votos anulados pelo TSE: não é válido
    oficial = pd.Series([(c, n) in nm for c, n in zip(v.cargo, v.numero)], index=v.index)
    anul = (v.tipo == "nominal") & ~oficial
    anulados = v[anul].groupby(["cargo", "numero"]).qtd.sum()
    v.loc[anul, "tipo"] = "anulado"
    print("votos anulados (fora da lista oficial):", {f"{c}/{n}": int(q) for (c, n), q in anulados.items()})
    v = v.merge(princ, on=["municipio", "zona", "secao"], how="left")
    v["regiao"] = [regiao(m, b) for m, b in zip(v.municipio, v.NM_BAIRRO)]
    v["nome"] = [nm.get((c, n), (None,))[0] if t in ("nominal", "legenda") else t.upper()
                 for c, n, t in zip(v.cargo, v.numero, v.tipo)]
    v["partido_sg"] = [nm.get((c, n), (None, None))[1] if t in ("nominal", "legenda") else None
                       for c, n, t in zip(v.cargo, v.numero, v.tipo)]
    v["valido"] = v.tipo.isin(["nominal", "legenda"])
    for cargo in (3, 6, 7, 5, 1):
        x = v[v.cargo == cargo][["NM_MUNICIPIO", "municipio", "zona", "secao", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO",
                                 "NM_BAIRRO", "regiao", "tipo", "partido_sg", "numero", "nome", "qtd"]]
        x.to_csv(f"{OUT}/votos_secao_{CARGOS[cargo].replace(' ', '_').lower()}_2026_RJ.csv.gz",
                 index=False, sep=";", encoding="utf-8")

    de = v[v.cargo == 7]
    keys = ["municipio", "zona", "secao"]
    val7 = de[de.valido].groupby(keys).qtd.sum().rename("validos")
    j = de[(de.tipo == "nominal") & (de.numero == JFN)].groupby(keys).qtd.sum().rename("jfn")
    s = pd.concat([val7, j], axis=1).fillna(0).reset_index()
    comp = sec[sec.cargo == 7].set_index(keys)[["aptos", "comparecimento"]]
    s = s.merge(comp, left_on=keys, right_index=True, how="left").merge(princ, on=keys, how="left")
    s["regiao"] = [regiao(m, b) for m, b in zip(s.municipio, s.NM_BAIRRO)]
    s["pct_jfn"] = s.jfn / s.validos.replace(0, np.nan) * 100

    def agrupa(df, by):
        g = df.groupby(by).agg(votos_jfn=("jfn", "sum"), validos=("validos", "sum"), aptos=("aptos", "sum"),
                               comparecimento=("comparecimento", "sum"), secoes=("secao", "count")).reset_index()
        g["pct_validos"] = g.votos_jfn / g.validos * 100
        g["pct_do_total_jfn"] = g.votos_jfn / s.jfn.sum() * 100
        return g.sort_values("votos_jfn", ascending=False)

    por_mun = agrupa(s, ["NM_MUNICIPIO"])
    por_reg = agrupa(s, ["regiao"])
    rio = s[s.municipio == RIO]
    por_zona = agrupa(rio, ["zona"])
    por_bairro = agrupa(rio, ["regiao", "NM_BAIRRO"])
    por_local = agrupa(rio, ["regiao", "NM_BAIRRO", "zona", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "DS_ENDERECO"])
    latlon = princ.groupby(["zona", "NR_LOCAL_VOTACAO"])[["lat", "lon"]].first()
    por_local = por_local.merge(latlon, left_on=["zona", "NR_LOCAL_VOTACAO"], right_index=True, how="left")

    # posição de JFN entre os candidatos a dep. estadual em cada bairro
    nb = de[(de.municipio == RIO) & (de.tipo == "nominal")].groupby(["NM_BAIRRO", "numero"]).qtd.sum().reset_index()
    nb["pos"] = nb.groupby("NM_BAIRRO").qtd.rank(ascending=False, method="min")
    pos = nb[nb.numero == JFN].set_index("NM_BAIRRO").pos
    lider = nb.sort_values("qtd", ascending=False).drop_duplicates("NM_BAIRRO").set_index("NM_BAIRRO")
    por_bairro["posicao_jfn"] = por_bairro.NM_BAIRRO.map(pos)
    por_bairro["mais_votado"] = por_bairro.NM_BAIRRO.map(lambda b: nm.get((7, lider.numero.get(b)), ("?",))[0])
    por_bairro["votos_mais_votado"] = por_bairro.NM_BAIRRO.map(lider.qtd)

    # ---------- 2022 x 2026 por bairro ----------
    try:
        j22 = pd.read_csv(f"{T}/jfn_2022_secao_RJ.csv", sep=";")
        l22 = locais(2022)
        l22 = l22[l22.CD_TIPO_SECAO_AGREGADA == "1"].drop_duplicates(keys)[keys + ["NM_BAIRRO"]]
        j22 = j22.rename(columns={"cd_municipio": "municipio"}).merge(l22, on=keys, how="left")
        b22 = j22[j22.municipio == RIO].groupby("NM_BAIRRO").agg(votos_jfn_2022=("votos_jfn", "sum"),
                                                                validos_2022=("validos_dep_est", "sum"))
        por_bairro = por_bairro.merge(b22, left_on="NM_BAIRRO", right_index=True, how="left")
        por_bairro["pct_validos_2022"] = por_bairro.votos_jfn_2022 / por_bairro.validos_2022 * 100
        por_bairro["variacao_votos"] = por_bairro.votos_jfn - por_bairro.votos_jfn_2022
        m22 = j22.groupby("nm_municipio").votos_jfn.sum()
        por_mun["votos_jfn_2022"] = por_mun.NM_MUNICIPIO.map(m22)
        por_mun["variacao_votos"] = por_mun.votos_jfn - por_mun.votos_jfn_2022
        total22 = int(j22.votos_jfn.sum())
    except FileNotFoundError:
        total22 = None

    # ---------- rankings por recorte ----------
    def ranking(cargo, mascara, n=None):
        x = v[(v.cargo == cargo) & mascara & v.valido]
        tv = x.qtd.sum()
        r = x[x.tipo == "nominal"].groupby(["numero", "nome", "partido_sg"]).qtd.sum().reset_index()
        r["pct_validos"] = r.qtd / tv * 100
        r = r.sort_values("qtd", ascending=False).reset_index(drop=True)
        r.index += 1
        return r.rename(columns={"qtd": "votos"})

    recortes = {"Estado": v.municipio > 0, "Capital": v.municipio == RIO,
                "Zona Oeste (AP4+AP5)": v.regiao.isin(ZONA_OESTE), "AP5": v.regiao == ZONA_OESTE[1],
                "AP4": v.regiao == ZONA_OESTE[0]}
    rank = {(c, r): ranking(c, m) for c in (7, 6, 3, 5, 1) for r, m in recortes.items()}
    maj_reg = {}
    for cargo in (3, 5, 1):
        x = (v[(v.cargo == cargo) & v.valido].pivot_table(index="regiao", columns="nome", values="qtd", aggfunc="sum")
             .fillna(0))
        maj_reg[cargo] = x.div(x.sum(axis=1), axis=0) * 100

    # ---------- cruzamento ----------
    def cruzamento(cargo, mascara, min_pct=0.3):
        base = s[mascara(s) & (s.validos >= 50)].copy()
        base["fj"] = base.jfn / base.validos
        corte = base.fj.quantile(0.9)
        x = v[(v.cargo == cargo) & v.valido]
        vt = x.groupby(keys).qtd.sum().rename("vt")
        piv = x[x.tipo == "nominal"].pivot_table(index=keys, columns="numero", values="qtd", aggfunc="sum").fillna(0)
        piv = piv.reindex(base.set_index(keys).index).fillna(0)
        vt = vt.reindex(piv.index)
        frac = piv.div(vt, axis=0)
        fj = base.set_index(keys).fj
        red = fj >= corte
        # grupo de controle: AP na capital, município fora dela
        grupo = pd.Series(np.where(base.municipio == RIO, base.regiao, base.NM_MUNICIPIO), index=fj.index)
        tot_reg = piv.sum()
        linhas = []
        for n in piv.columns:
            share = tot_reg[n] / vt.sum() * 100
            if share < min_pct:
                continue
            c = np.corrcoef(fj.values, frac[n].values)[0, 1]
            cc = corr_controlada(fj, frac[n], grupo)
            lc = lift_controlado(fj, piv[n], vt, grupo)
            sh_red = piv.loc[red, n].sum() / vt[red].sum() * 100
            nmu, sg, st, _ = nm.get((cargo, n), ("?", "?", "", None))
            linhas.append((n, nmu, sg, st, int(tot_reg[n]), share, int(piv.loc[red, n].sum()), sh_red,
                           sh_red / share, c, cc, lc))
        df = pd.DataFrame(linhas, columns=["numero", "nome", "partido", "situacao", "votos_no_recorte",
                                           "pct_no_recorte", "votos_nos_redutos_jfn", "pct_nos_redutos_jfn",
                                           "lift_reduto", "correlacao_secao", "correlacao_controlada", "lift_controlado"])
        meta = {"secoes": int(len(base)), "secoes_reduto": int(red.sum()), "corte_pct_jfn": float(corte * 100),
                "votos_jfn_redutos": int(base.jfn[red.values].sum())}
        return df.sort_values("correlacao_controlada", ascending=False).reset_index(drop=True), meta

    cz = {}
    for nome_r, f in (("Capital", lambda d: d.municipio == RIO),
                      ("Zona Oeste (AP4+AP5)", lambda d: d.regiao.isin(ZONA_OESTE)),
                      ("Estado", lambda d: d.municipio > 0)):
        for cargo in (6, 3, 5, 1):
            cz[(cargo, nome_r)] = cruzamento(cargo, f, 0.3 if cargo == 6 else 0)

    # ---------- comparativo seção a seção na capital: JFN x federais pedidos ----------
    df6 = v[(v.cargo == 6) & (v.municipio == RIO)]
    val6 = df6[df6.valido].groupby(keys).qtd.sum().rename("validos_dep_fed")
    f6 = (df6[(df6.tipo == "nominal") & df6.numero.isin(list(FEDS))]
          .pivot_table(index=keys, columns="numero", values="qtd", aggfunc="sum")
          .reindex(columns=list(FEDS)).fillna(0).astype(int))
    f6.columns = [f"fed_{n}" for n in f6.columns]
    cmp = (rio[keys + ["NM_LOCAL_VOTACAO", "NM_BAIRRO", "regiao", "aptos", "comparecimento", "validos", "jfn", "pct_jfn"]]
           .merge(val6, left_on=keys, right_index=True, how="left")
           .merge(f6, left_on=keys, right_index=True, how="left").fillna({c: 0 for c in f6.columns}))
    cmp = cmp.rename(columns={"validos": "validos_dep_est", "jfn": "votos_jfn"})
    for n in FEDS:
        cmp[f"pct_fed_{n}"] = cmp[f"fed_{n}"] / cmp.validos_dep_fed.replace(0, np.nan) * 100
    base = cmp[cmp.validos_dep_est >= 50]
    corte_r = base.pct_jfn.quantile(0.9)
    red = base.pct_jfn >= corte_r
    resumo_feds = []
    for n, rot in FEDS.items():
        c = f"fed_{n}"
        tot_cap = int(cmp[c].sum())
        sh = tot_cap / cmp.validos_dep_fed.sum() * 100
        sh_red = base.loc[red, c].sum() / base.loc[red, "validos_dep_fed"].sum() * 100
        bz = cmp[cmp.regiao.isin(ZONA_OESTE)]
        porb = cmp.groupby("NM_BAIRRO")[c].sum().sort_values(ascending=False)
        resumo_feds.append({
            "numero": n, "nome": nm.get((6, n), (rot,))[0], "partido": nm.get((6, n), (None, "?"))[1],
            "situacao": nm.get((6, n), (None, None, "?"))[2], "votos_estado": nm.get((6, n), (None, None, None, None))[3],
            "votos_capital": tot_cap, "votos_zona_oeste": int(bz[c].sum()), "pct_capital": sh,
            "secoes_com_voto": int((cmp[c] > 0).sum()),
            "secoes_ambos": int(((cmp[c] > 0) & (cmp.votos_jfn > 0)).sum()),
            "secoes_fed_maior_que_jfn": int((cmp[c] > cmp.votos_jfn).sum()),
            "secoes_jfn_maior": int((cmp.votos_jfn > cmp[c]).sum()),
            "correlacao_com_jfn": float(np.corrcoef(base.pct_jfn, base[f"pct_fed_{n}"].fillna(0))[0, 1]),
            "correlacao_controlada": corr_controlada(base.pct_jfn, base[f"pct_fed_{n}"], base.regiao),
            "correlacao_controlada_zo": corr_controlada(base.pct_jfn[base.regiao.isin(ZONA_OESTE)],
                                                        base[f"pct_fed_{n}"][base.regiao.isin(ZONA_OESTE)],
                                                        base.regiao[base.regiao.isin(ZONA_OESTE)]),
            "lift_controlado": lift_controlado(base.pct_jfn, base[c], base.validos_dep_fed, base.regiao),
            "pct_nos_redutos_jfn": sh_red, "lift_reduto": sh_red / sh if sh else None,
            "melhor_bairro": porb.index[0] if len(porb) else None, "votos_melhor_bairro": int(porb.iloc[0]) if len(porb) else 0,
        })
    resumo_feds = pd.DataFrame(resumo_feds)
    cmp_bairro = cmp.groupby(["regiao", "NM_BAIRRO"])[["validos_dep_est", "votos_jfn", "validos_dep_fed"]
                                                      + [f"fed_{n}" for n in FEDS]].sum().reset_index()
    cmp.rename(columns=lambda c: c.replace("jfn", "jorge")).to_csv(f"{OUT}/comparativo_secao_capital_jorge_x_federais.csv", index=False, sep=";", encoding="utf-8-sig")

    # ---------- Excel ----------
    xl = f"{OUT}/Eleicao2026_RJ_secoes_Jorge_Felippe_Neto.xlsx"
    # entregável não carrega sigla interna: colunas "jfn" saem como "jorge"
    def neutro(df):
        return df.rename(columns=lambda c: str(c).replace("jfn", "jorge"))

    with pd.ExcelWriter(xl, engine="openpyxl") as w:
        resumo = por_reg.copy()
        neutro(resumo).to_excel(w, sheet_name="Jorge por região", index=False)
        neutro(por_mun).to_excel(w, sheet_name="Jorge por município", index=False)
        neutro(por_zona).to_excel(w, sheet_name="Jorge por zona (capital)", index=False)
        neutro(por_bairro).to_excel(w, sheet_name="Jorge por bairro (capital)", index=False)
        neutro(por_local).to_excel(w, sheet_name="Jorge por local (capital)", index=False)
        neutro(s.sort_values("jfn", ascending=False)).to_excel(w, sheet_name="Jorge por seção (estado)", index=False)
        for (cargo, nome_r), (df, meta) in cz.items():
            neutro(df).to_excel(w, sheet_name=f"Cruz {SIGLA[cargo]} {nome_r[:14]}", index=False)
        for (c, r), df in rank.items():
            neutro(df).to_excel(w, sheet_name=f"Rank {SIGLA[c]} {r[:14]}")
        for c, df in maj_reg.items():
            neutro(df.round(2)).to_excel(w, sheet_name=f"{CARGOS[c]} por região")
        neutro(resumo_feds).to_excel(w, sheet_name="Federais x Jorge resumo", index=False)
        neutro(cmp_bairro).to_excel(w, sheet_name="Federais x Jorge bairro", index=False)
        neutro(cmp).to_excel(w, sheet_name="Federais x Jorge seção capital", index=False)
        neutro(conf).to_excel(w, sheet_name="Conferência TSE", index=False)

    # ---------- dados do relatório ----------
    rel = {
        "total_jfn": int(s.jfn.sum()), "total22": total22,
        "oficial": nm[(7, JFN)][3], "situacao": nm[(7, JFN)][2],
        "conf_diferencas": int((conf.diferenca != 0).sum()), "conf_n": int(len(conf)),
        "secoes": int(len(s)), "secoes_com_voto": int((s.jfn > 0).sum()),
        "anulados": {CARGOS[c]: int(q) for c, q in anulados.groupby(level=0).sum().items()},
        "por_reg": por_reg.to_dict("records"), "por_mun": por_mun.head(25).to_dict("records"),
        "por_zona": por_zona.to_dict("records"),
        "por_bairro": por_bairro.to_dict("records"),
        "locais": por_local.to_dict("records"),
        "rank": {f"{c}|{r}": pd.concat([df.head(25), df.iloc[25:][df.iloc[25:].numero == JFN]]).reset_index().to_dict("records")
                 for (c, r), df in rank.items()},
        "maj_reg": {str(c): df.round(2).reset_index().to_dict("records") for c, df in maj_reg.items()},
        "feds": {"resumo": resumo_feds.to_dict("records"), "corte_reduto": float(corte_r),
                 "bairro": cmp_bairro.to_dict("records"),
                 "cols": list(cmp.columns), "linhas": cmp.round(2).values.tolist()},
        "cruz": {f"{c}|{r}": {"meta": m, "linhas": df.to_dict("records")} for (c, r), (df, m) in cz.items()},
        "top_secoes": s[s.municipio == RIO].sort_values("jfn", ascending=False).head(30)[
            ["zona", "secao", "NM_LOCAL_VOTACAO", "NM_BAIRRO", "regiao", "jfn", "validos", "pct_jfn"]].to_dict("records"),
    }
    json.dump(rel, open(f"{OUT}/dados_relatorio.json", "w"), ensure_ascii=False, default=lambda o: None if pd.isna(o) else (int(o) if isinstance(o, np.integer) else float(o)))
    print("OK", xl, "JFN seções:", rel["total_jfn"], "oficial:", rel["oficial"])


if __name__ == "__main__":
    main()
