"""PDFs da eleição 2026 (1º turno) no padrão da casa (html_to_pdf):

  A) votação de Jorge Felippe Neto (22800) — estado, AP, bairro, zona, local, seção e correlação
     com os 8 federais pedidos (capital, seção a seção);
  B) votação de Douglas Ruas (governador, 22) em cada zona eleitoral da capital, dividida por AP.

Fonte: eleicao2026_rj_secao.sqlite (tools/tse_bu_2026.py) + locais de votação do TSE.
Sem corte por tamanho (diretriz do dono): toda seção entra nos anexos.
"""
import asyncio
import html as H
import os
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.expanduser("~/JFN"))
sys.path.insert(0, os.path.dirname(__file__))
from compliance_agent.reporting.render_html import html_to_pdf  # noqa: E402
import eleicao2026_analise as A  # noqa: E402

OUT = os.path.expanduser("~/JFN/output/eleicoes2026")
KEYS = ["municipio", "zona", "secao"]
ORD_AP = ["AP1 · Centro", "AP2.1 · Zona Sul", "AP2.2 · Grande Tijuca", "AP3 · Zona Norte",
          "AP4 · Barra e Jacarepaguá", "AP5 · Zona Oeste"]
DOUGLAS, PAES = 22, 55
FONTE_BAIRRO = ("Na capital, o bairro e a Área de Planejamento de cada escola são os <b>oficiais da Prefeitura do Rio</b>, "
                "definidos pela localização da escola na malha oficial de 167 bairros (pgeo3.rio.rj.gov.br); o nome que o cadastro "
                "do TSE dá ao bairro diverge do oficial em cerca de 19% das escolas da capital. Nos demais municípios, vale o "
                "bairro do cadastro de locais de votação do TSE, com grafias unificadas.")
BLOCO = 4000  # linhas por bloco de anexo impresso separadamente
# nome curto de coluna: como cada federal é conhecido (o último sobrenome nem sempre é: "Altineu Cortes")
CURTO = {2222: "Soraya", 1177: "Luizinho", 4400: "Rossi", 2212: "Pazuello", 7090: "Onassis", 2767: "Galvão",
         2269: "Altineu", 1522: "Trovão"}


# ---------------- formatação ----------------
def n0(x):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{int(round(x)):,}".replace(",", ".")


def p2(x):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.2f}%".replace(",", "X").replace(".", ",").replace("X", ".")


def d2(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    x = 0.0 if abs(x) < 0.005 else x  # sem "-0,00"
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


SIGLAS = r"Rj|Ciep|Ciem|Jpa|Ufrj|Uerj|Uff|Unirio|Faetec|Cefet|Senai|Sesi|Sesc|Iserj|Ifrj|Puc|Cap|Cpii|Ii|Iii|Iv|Vi|Vii|Viii|Ix|Xi|Xii"


def tit(s):
    s = str(s or "").lower().title()
    s = re.sub(r"(?<=\s)(De|Da|Do|Dos|Das|E)(?=\s)", lambda m: m.group(0).lower(), s)
    return re.sub(rf"\b({SIGLAS})\b", lambda m: m.group(0).upper(), s)


def e(s):
    return H.escape(str(s if s is not None else ""))


def tabela(cab, linhas, num=(), cls="", destaque=None):
    """cab: lista de títulos; linhas: lista de listas já formatadas; num: índices numéricos."""
    th = "".join(f'<th class="{"n" if i in num else ""}">{c}</th>' for i, c in enumerate(cab))
    corpo = []
    for j, l in enumerate(linhas):
        d = ' class="hl"' if destaque and destaque(j) else ""
        corpo.append(f"<tr{d}>" + "".join(f'<td class="{"n" if i in num else ""}">{v}</td>' for i, v in enumerate(l)) + "</tr>")
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(corpo)}</tbody></table>'


CSS = """
* { box-sizing: border-box; }
body { font-family: Georgia, 'Times New Roman', serif; color:#1a1a1a; font-size:10.5px; line-height:1.55; margin:0; }
.capa { border-bottom:3px solid #1f4e79; padding-bottom:14px; margin-bottom:16px; }
.classif { color:#1f4e79; font-weight:700; letter-spacing:.15em; font-size:9px; text-transform:uppercase; font-family:Arial,sans-serif; }
h1 { font-size:23px; color:#1f4e79; margin:8px 0 4px; line-height:1.2; }
.meta { color:#555; font-size:9.5px; }
.kpis { display:grid; grid-template-columns:repeat(3,1fr); gap:0; border:1px solid #d7dde6; margin:14px 0; }
.kpi { padding:9px 12px; border-right:1px solid #e3e8ef; border-bottom:1px solid #e3e8ef; }
.kpi b { display:block; font-size:16px; color:#12335a; font-family:Arial,sans-serif; }
.kpi span { font-size:8.5px; color:#666; font-family:Arial,sans-serif; }
h2 { font-size:14px; color:#1f4e79; border-bottom:1.5px solid #1f4e79; padding-bottom:4px; margin:22px 0 8px; page-break-after:avoid; }
h3 { font-size:12px; color:#12335a; background:#eef3fa; border-left:4px solid #1f4e79; padding:5px 10px; margin:14px 0 6px; page-break-after:avoid; }
p { margin:5px 0; text-align:justify; }
.toc { list-style:none; padding-left:0; } .toc a { color:#1f4e79; text-decoration:none; } .toc li { margin:2px 0; }
table { width:100%; border-collapse:collapse; font-size:8.6px; margin:6px 0 10px; font-family:Arial,sans-serif; }
th, td { text-align:left; padding:3px 5px; border-bottom:1px solid #e8ebef; vertical-align:top; }
th { background:#1f4e79; color:#fff; font-weight:600; font-size:8px; }
thead { display:table-header-group; } tr { page-break-inside:avoid; }
th.n, td.n { text-align:right; white-space:nowrap; }
tbody tr:nth-child(even) td { background:#f5f8fc; }
tr.hl td { background:#fff4dc !important; font-weight:700; }
table.mini { font-size:7.4px; } table.mini th { font-size:7px; } table.mini td, table.mini th { padding:2px 3px; }
.callout { background:#fff8e1; border-left:4px solid #f9a825; padding:7px 11px; margin:8px 0; page-break-inside:avoid; }
.ok { background:#f1f8f4; border-left:4px solid #2e7d32; padding:7px 11px; margin:8px 0; page-break-inside:avoid; }
.nota { font-size:8.5px; color:#666; font-style:italic; }
.pg { page-break-before:always; }
.fonte { font-family:'Courier New',monospace; font-size:8px; color:#444; }
.wrap { padding:0 4mm; }
"""


def documento(titulo, subtitulo, kpis, toc, corpo):
    k = "".join(f'<div class="kpi"><b>{v}</b><span>{r}</span></div>' for v, r in kpis)
    t = "".join(f'<li><a href="#{a}">{e(n)}</a></li>' for a, n in toc)
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{e(titulo)}</title><style>{CSS}</style></head>
<body><div class="wrap">
<div class="capa"><div class="classif">Eleições Gerais 2026 · 1º turno · 04/10/2026 · Estado do Rio de Janeiro</div>
<h1>{e(titulo)}</h1><div class="meta">{subtitulo}<br>Emitido em {datetime.now():%d/%m/%Y} · Fonte primária: boletins de urna publicados pelo Tribunal Superior Eleitoral</div></div>
<div class="kpis">{k}</div>
<h2>Sumário</h2><ol class="toc">{t}</ol>
{corpo}
</div></body></html>"""


# ---------------- dados ----------------
def carregar():
    con = sqlite3.connect(f"{A.T}/eleicao2026_rj_secao.sqlite")
    nm = A.nomes()
    loc = A.locais(2026)
    princ = loc[loc["CD_TIPO_SECAO_AGREGADA"] == "1"].drop_duplicates(KEYS)[
        KEYS + ["NM_MUNICIPIO", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "NM_BAIRRO", "NM_BAIRRO_TSE", "DS_ENDERECO", "k_escola"]]
    v = pd.read_sql("SELECT * FROM voto WHERE cargo IN (3,6,7)", con)
    oficial = pd.Series([(c, n) in nm for c, n in zip(v.cargo, v.numero)], index=v.index)
    v.loc[(v.tipo == "nominal") & ~oficial, "tipo"] = "anulado"  # como no total do TSE
    v["valido"] = v.tipo.isin(["nominal", "legenda"])
    sec = pd.read_sql("SELECT municipio,zona,secao,cargo,aptos,comparecimento FROM secao WHERE cargo IN (3,7)", con)
    base = sec[sec.cargo == 7].drop(columns="cargo").merge(princ, on=KEYS, how="left")
    base["regiao"] = [A.regiao(m, b) for m, b in zip(base.municipio, base.NM_BAIRRO)]
    return nm, v, base


def por_secao(v, cargo, numeros):
    x = v[v.cargo == cargo]
    val = x[x.valido].groupby(KEYS).qtd.sum().rename("validos")
    piv = (x[(x.tipo == "nominal") & x.numero.isin(numeros)]
           .pivot_table(index=KEYS, columns="numero", values="qtd", aggfunc="sum").reindex(columns=numeros).fillna(0))
    return pd.concat([val, piv], axis=1).fillna(0)


# ---------------- PDF A: Jorge ----------------
METODO_CORR = """<p><b>Como a correlação é medida.</b> Em cada seção com 50 ou mais válidos de estadual, toma-se a fatia de Jorge nos
válidos de estadual e a do federal nos válidos de federal. A <b>correlação controlada</b> compara as duas fatias <b>dentro da mesma Área
de Planejamento</b>: de cada fatia se subtrai a média da sua AP antes de correlacionar. Sem esse controle, dois candidatos fortes em
regiões diferentes da cidade aparecem com correlação nula ou negativa mesmo quando, dentro de cada região, sobem juntos: Jorge é forte
na AP5, e um federal forte na Zona Sul anula a relação quando a cidade é tomada inteira. A <b>correlação bruta</b> (cidade inteira, sem
controle) aparece ao lado. O <b>índice de reduto controlado</b> toma as seções do decil superior de Jorge <b>dentro de cada AP</b> e compara
os votos do federal ali com o que ele teria se repetisse nelas a própria fatia da AP; 1,00 é neutro, 1,50 é 50% acima.</p>"""


def secoes_jorge_feds(v, base):
    """Uma linha por seção: votos de Jorge e válidos de estadual; votos de cada federal pedido e válidos de federal."""
    feds = list(A.FEDS)
    s7 = por_secao(v, 7, [A.JFN]).rename(columns={A.JFN: "jorge", "validos": "val7"})
    s6 = por_secao(v, 6, feds).rename(columns={"validos": "val6"})
    d = base.merge(s7, left_on=KEYS, right_index=True, how="left").merge(s6, left_on=KEYS, right_index=True, how="left").fillna(
        {c: 0 for c in ["jorge", "val7", "val6"] + feds})
    d["pj"] = d.jorge / d.val7.replace(0, np.nan) * 100
    # voto do PL (nominal 22… + legenda 22) em cada cargo: o fator que Jorge e os federais do PL dividem
    for cargo, col, div in ((7, "pl7", 1000), (6, "pl6", 100)):
        x = v[(v.cargo == cargo) & v.valido]
        pl = x[((x.tipo == "nominal") & (x.numero // div == 22)) | ((x.tipo == "legenda") & (x.numero == 22))]
        d = d.merge(pl.groupby(KEYS).qtd.sum().rename(col), left_on=KEYS, right_index=True, how="left")
        d[col] = d[col].fillna(0)
    return d


def pdf_jorge(nm, v, base):
    J = A.JFN
    feds = list(A.FEDS)
    d = secoes_jorge_feds(v, base)
    total = int(d.jorge.sum())
    assert total == nm[(7, J)][3], (total, nm[(7, J)][3])
    rio = d[d.municipio == A.RIO].copy()
    cap = int(rio.jorge.sum())
    zo = int(rio[rio.regiao.isin(A.ZONA_OESTE)].jorge.sum())

    # posições
    nomi = v[(v.cargo == 7) & (v.tipo == "nominal")].merge(base[KEYS + ["regiao"]], on=KEYS, how="left")

    def posicao(mask):
        r = nomi[mask(nomi)].groupby("numero").qtd.sum().sort_values(ascending=False)
        return int(list(r.index).index(J)) + 1, len(r)

    pos_est = posicao(lambda x: x.municipio > 0)
    pos_cap = posicao(lambda x: x.municipio == A.RIO)
    pos_zo = posicao(lambda x: x.regiao.isin(A.ZONA_OESTE))
    j22 = pd.read_csv(f"{A.T}/jfn_2022_secao_RJ.csv", sep=";")
    t22 = int(j22.votos_jfn.sum())

    def agrega(df, by):
        g = df.groupby(by).agg(votos=("jorge", "sum"), validos=("val7", "sum"), secoes=("secao", "count"),
                               aptos=("aptos", "sum"), comp=("comparecimento", "sum")).reset_index()
        g["pct"] = g.votos / g.validos * 100
        g["pct_tot"] = g.votos / total * 100
        return g.sort_values("votos", ascending=False)

    reg = agrega(d, ["regiao"])
    mun = agrega(d, ["NM_MUNICIPIO"])
    l22 = A.locais(2022)
    l22 = l22[l22.CD_TIPO_SECAO_AGREGADA == "1"].drop_duplicates(KEYS)[KEYS + ["NM_BAIRRO"]]
    j22 = j22.rename(columns={"cd_municipio": "municipio"}).merge(l22, on=KEYS, how="left")
    mun["v22"] = mun.NM_MUNICIPIO.map(j22.groupby("nm_municipio").votos_jfn.sum())
    bai = agrega(rio, ["regiao", "NM_BAIRRO"])
    bai["v22"] = bai.NM_BAIRRO.map(j22[j22.municipio == A.RIO].groupby("NM_BAIRRO").votos_jfn.sum())
    nb = nomi[nomi.municipio == A.RIO].merge(base[KEYS + ["NM_BAIRRO"]], on=KEYS, how="left")
    nb = nb.groupby(["NM_BAIRRO", "numero"]).qtd.sum().reset_index()
    nb["pos"] = nb.groupby("NM_BAIRRO").qtd.rank(ascending=False, method="min")
    bai["pos"] = bai.NM_BAIRRO.map(nb[nb.numero == J].set_index("NM_BAIRRO").pos)
    lid = nb.sort_values("qtd", ascending=False).drop_duplicates("NM_BAIRRO").set_index("NM_BAIRRO")
    bai["lider"] = bai.NM_BAIRRO.map(lambda b: nm.get((7, lid.numero.get(b)), ("?",))[0])
    bai["lider_v"] = bai.NM_BAIRRO.map(lid.qtd)
    zon_cap = agrega(rio, ["zona"])
    zon_ap = agrega(rio, ["zona", "regiao"])
    zon_est = agrega(d, ["NM_MUNICIPIO", "zona"])
    locs = agrega(rio, ["regiao", "NM_BAIRRO", "zona", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO"])
    assert int(bai.votos.sum()) == cap == int(zon_cap.votos.sum()) == int(locs.votos.sum())
    assert int(reg.votos.sum()) == total == int(mun.votos.sum()) == int(zon_est.votos.sum())

    # correlação com federais (capital), por recorte
    rb = rio[rio.val7 >= 50].copy()

    def corr_fed(df, n):
        f = df[n] / df.val6.replace(0, np.nan) * 100
        ok = f.notna() & df.pj.notna()
        return float(np.corrcoef(df.pj[ok], f[ok])[0, 1]) if ok.sum() > 2 and f[ok].std() > 0 else None

    corte = rb.pj.quantile(0.9)
    red = rb[rb.pj >= corte]
    fedrows = []
    for n in feds:
        nome, sg, st, vap = nm[(6, n)]
        tc = int(rio[n].sum())
        sh = tc / rio.val6.sum() * 100
        shr = red[n].sum() / red.val6.sum() * 100
        fedrows.append(dict(
            n=n, nome=nome, sg=sg, st=st, vap=vap, cap=tc, zo=int(rio[rio.regiao.isin(A.ZONA_OESTE)][n].sum()),
            sh=sh, shr=shr, lift=shr / sh if sh else None,
            c_cap=corr_fed(rb, n), c_zo=corr_fed(rb[rb.regiao.isin(A.ZONA_OESTE)], n),
            cc=A.corr_controlada(rb.pj, rb[n] / rb.val6.replace(0, np.nan) * 100, rb.regiao),
            cc_zo=A.corr_controlada(rb.pj[rb.regiao.isin(A.ZONA_OESTE)], (rb[n] / rb.val6.replace(0, np.nan) * 100)[rb.regiao.isin(A.ZONA_OESTE)],
                                    rb.regiao[rb.regiao.isin(A.ZONA_OESTE)]),
            liftc=A.lift_controlado(rb.pj, rb[n], rb.val6, rb.regiao),
            c_ap5=corr_fed(rb[rb.regiao == A.ZONA_OESTE[1]], n), c_ap4=corr_fed(rb[rb.regiao == A.ZONA_OESTE[0]], n),
            supera=int((rio[n] > rio.jorge).sum()), perde=int((rio.jorge > rio[n]).sum()),
            empate=int((rio.jorge == rio[n]).sum()), ambos=int(((rio[n] > 0) & (rio.jorge > 0)).sum())))
    fr = pd.DataFrame(fedrows).sort_values("cc", ascending=False)
    fb = rio.groupby(["regiao", "NM_BAIRRO"])[["jorge", "val7", "val6"] + feds].sum().reset_index().sort_values("jorge", ascending=False)

    # -------- texto --------
    C = []
    toc = []

    def sec(ancora, titulo, conteudo, quebra=False):
        toc.append((ancora, titulo))
        C.append(f'<h2 id="{ancora}" class="{"pg" if quebra else ""}">{e(titulo)}</h2>{conteudo}')

    ap5 = reg.set_index("regiao").votos.get(A.ZONA_OESTE[1], 0)
    ap4 = reg.set_index("regiao").votos.get(A.ZONA_OESTE[0], 0)
    top_b = bai[bai.regiao.isin(A.ZONA_OESTE)].head(5)
    lidera = bai[bai.pos == 1].NM_BAIRRO.map(tit).tolist()
    m_fora = mun[mun.NM_MUNICIPIO != "RIO DE JANEIRO"].head(5)
    maior_pct = bai[bai.validos > 3000].sort_values("pct", ascending=False).head(5)
    sec("s1", "1. Sumário executivo", f"""
<p>Jorge Felippe Neto (PL, número 22800) foi <b>{e(nm[(7, J)][2][0].lower() + nm[(7, J)][2][1:])}</b> para a Assembleia Legislativa do Estado do Rio de Janeiro com
<b>{n0(total)} votos</b>, {p2(total / v[(v.cargo == 7) & v.valido].qtd.sum() * 100)} dos votos válidos do estado, o {pos_est[0]}º maior votação
entre {n0(pos_est[1])} candidatos com voto nominal. Em 2022, disputando pelo AVANTE com o número 70800, obteve {n0(t22)} votos; o crescimento
foi de {n0(total - t22)} votos ({p2((total / t22 - 1) * 100)}).</p>
<p>A votação é fortemente concentrada na capital, que respondeu por <b>{n0(cap)} votos ({p2(cap / total * 100)} do total)</b>, com o
{pos_cap[0]}º lugar entre {n0(pos_cap[1])} candidatos votados na cidade. Dentro da capital, o eixo é a Zona Oeste: a AP5 (Bangu, Realengo,
Campo Grande, Santa Cruz, Guaratiba e entorno) deu {n0(ap5)} votos e a AP4 (Barra e Jacarepaguá) {n0(ap4)}, somando {n0(zo)}
({p2(zo / total * 100)} do total). Na Zona Oeste, Jorge é o {pos_zo[0]}º candidato a deputado estadual mais votado.</p>
<p>Os maiores volumes por bairro na Zona Oeste foram {", ".join(f"{tit(r.NM_BAIRRO)} ({n0(r.votos)})" for r in top_b.itertuples())}.
Foi o candidato a estadual mais votado em {len(lidera)} bairro(s) da capital: {", ".join(lidera) or "nenhum"}. Em participação proporcional
(bairros com mais de 3 mil válidos), os maiores índices foram {", ".join(f"{tit(r.NM_BAIRRO)} ({p2(r.pct)})" for r in maior_pct.itertuples())}.</p>
<p>Fora da capital, os municípios com mais votos foram {", ".join(f"{tit(r.NM_MUNICIPIO)} ({n0(r.votos)})" for r in m_fora.itertuples())}.</p>
<p>Entre os oito candidatos a deputado federal analisados, o que mais acompanha o território de Jorge na capital é
<b>{tit(fr.iloc[0].nome)}</b> (correlação controlada por região de {d2(fr.iloc[0].cc)}), seguido de {tit(fr.iloc[1].nome)}
({d2(fr.iloc[1].cc)}) e {tit(fr.iloc[2].nome)} ({d2(fr.iloc[2].cc)}). O de menor afinidade é {tit(fr.iloc[-1].nome)}
({d2(fr.iloc[-1].cc)}). {"Nenhum dos oito tem correlação controlada negativa." if (fr.cc >= 0).all() else
f"{int((fr.cc < 0).sum())} dos oito têm correlação controlada negativa."} A seção 8 explica a medida e detalha cada um.</p>""")

    sec("s2", "2. Fonte, método e conferência", f"""
<p>Todos os números deste relatório foram apurados a partir dos <b>boletins de urna</b> (BU) de cada seção eleitoral do Estado do Rio de
Janeiro, publicados pelo Tribunal Superior Eleitoral no repositório oficial de resultados (pleito 3220, 1º turno de 04/10/2026). Foram
decodificados {n0(len(d))} boletins, um por seção principal; as seções agregadas votam na urna da seção principal e não têm boletim próprio.
Endereço e local de votação vêm do cadastro de locais de votação do TSE de 2026. """ + FONTE_BAIRRO + """ A comparação com 2022 usa o
arquivo oficial de votação por seção de 2022 do TSE, com o mesmo critério de bairro aplicado aos locais de 2022.</p>
<div class="ok"><b>Conferência integral.</b> Em todas as {n0(len(d))} seções, a soma dos votos de cada cargo é igual ao comparecimento.
A soma das seções coincide, candidato a candidato, com o total oficial do TSE para os 1.928 candidatos a governador, senador, deputado
federal e deputado estadual, e os 1.883 percentuais sobre válidos coincidem com os do TSE. Votos dados a números que não constam da lista
oficial (candidaturas com votos anulados) são tratados como anulados, como no total oficial.</div>
<p><b>Votos válidos</b> são os nominais e de legenda, excluídos brancos, nulos e anulados. Todo percentual é calculado sobre os válidos do
mesmo cargo, no mesmo recorte. <b>Áreas de Planejamento (AP)</b> seguem a malha oficial da
Prefeitura do Rio; "Zona Oeste" designa AP4 + AP5. Como o eleitor vota no local onde está inscrito, que nem sempre fica no bairro onde
mora, uma seção pertence ao bairro do local de votação, e as manchas eleitorais de bairros vizinhos se sobrepõem.</p>""")

    sec("s3", "3. Distribuição por região do estado", "<p>A tabela reparte o total de Jorge entre as Áreas de Planejamento da capital e o "
        "restante do estado. A coluna \"% válidos\" mede a força relativa dentro de cada recorte; \"% do total\" mede o peso do recorte na "
        "votação dele.</p>" + tabela(
            ["Região", "Votos", "% do total", "% válidos", "Válidos dep. est.", "Seções", "Aptos", "Comparecimento"],
            [[e(r.regiao), n0(r.votos), p2(r.pct_tot), p2(r.pct), n0(r.validos), n0(r.secoes), n0(r.aptos), n0(r.comp)]
             for r in reg.assign(o=reg.regiao.map(lambda x: (ORD_AP + ["Fora da capital"]).index(x))).sort_values("o").itertuples()],
            num=range(1, 8)))

    sec("s4", "4. Todos os municípios", f"<p>Os {len(mun)} municípios do estado, ordenados por votos. Em {int((mun.votos > 0).sum())} houve "
        "ao menos um voto para Jorge. A coluna 2022 traz a votação no mesmo município na eleição anterior.</p>" + tabela(
            ["Município", "Votos 2026", "% válidos", "% do total", "Votos 2022", "Variação", "Seções"],
            [[tit(r.NM_MUNICIPIO), n0(r.votos), p2(r.pct), p2(r.pct_tot), n0(r.v22),
              ("+" if (r.votos - (r.v22 or 0)) > 0 else "") + n0(r.votos - (0 if pd.isna(r.v22) else r.v22)), n0(r.secoes)]
             for r in mun.itertuples()], num=range(1, 7)))

    sec("s5", "5. Capital, bairro a bairro", f"""<p>Os {len(bai)} bairros oficiais da capital que têm local de votação, agrupados por
Área de Planejamento. "Posição" é o lugar de Jorge entre todos os candidatos a deputado estadual votados no bairro; "Mais votado" é o
candidato a estadual com mais votos ali. A soma da coluna de votos é {n0(cap)}, o total da capital.</p>""" + "".join(
        f'<h3>{e(ap)} — {n0(bai[bai.regiao == ap].votos.sum())} votos</h3>' + tabela(
            ["Bairro", "Votos", "% válidos", "Posição", "Mais votado no bairro", "Votos 2022", "Variação", "Seções"],
            [[tit(r.NM_BAIRRO), n0(r.votos), p2(r.pct), f"{int(r.pos)}º" if not pd.isna(r.pos) else "—",
              f"{tit(r.lider)} ({n0(r.lider_v)})", n0(r.v22),
              ("+" if r.votos - (0 if pd.isna(r.v22) else r.v22) > 0 else "") + n0(r.votos - (0 if pd.isna(r.v22) else r.v22)), n0(r.secoes)]
             for r in bai[bai.regiao == ap].itertuples()], num=(1, 2, 3, 5, 6, 7))
        for ap in ORD_AP if (bai.regiao == ap).any()), quebra=True)

    zon_ap_rows = []
    for z in zon_cap.zona:
        for r in zon_ap[zon_ap.zona == z].sort_values("votos", ascending=False).itertuples():
            zon_ap_rows.append([f"{int(z)}ª", e(r.regiao), n0(r.votos), p2(r.pct), n0(r.secoes)])
    sec("s6", "6. Zonas eleitorais", f"""<p>A capital tem {len(zon_cap)} zonas eleitorais. A primeira tabela traz o total de cada zona; a segunda
reparte cada zona pelas Áreas de Planejamento onde ela tem seções, porque o limite de zona não coincide com o de AP. A terceira cobre as
{len(zon_est)} combinações de município e zona de todo o estado.</p><h3>Zonas da capital</h3>""" + tabela(
        ["Zona", "Votos", "% válidos", "% do total", "Seções", "Aptos", "Comparecimento"],
        [[f"{int(r.zona)}ª", n0(r.votos), p2(r.pct), p2(r.pct_tot), n0(r.secoes), n0(r.aptos), n0(r.comp)] for r in zon_cap.itertuples()],
        num=range(1, 7)) + "<h3>Zonas da capital por Área de Planejamento</h3>" + tabela(
        ["Zona", "Área de Planejamento", "Votos", "% válidos", "Seções"], zon_ap_rows, num=(2, 3, 4)) +
        "<h3>Todas as zonas do estado</h3>" + tabela(
        ["Município", "Zona", "Votos", "% válidos", "Seções"],
        [[tit(r.NM_MUNICIPIO), f"{int(r.zona)}ª", n0(r.votos), p2(r.pct), n0(r.secoes)] for r in zon_est.itertuples()],
        num=(2, 3, 4)))

    locs_v = locs[locs.votos > 0]
    sec("s7", "7. Locais de votação da capital", f"<p>Os {len(locs_v)} locais de votação da capital em que Jorge teve ao menos um voto "
        f"(de {len(locs)} locais). Os demais aparecem no anexo A, seção a seção, com zero voto.</p>" + tabela(
            ["Local", "Bairro", "AP", "Zona", "Votos", "% válidos", "Seções"],
            [[tit(r.NM_LOCAL_VOTACAO), tit(r.NM_BAIRRO), e(r.regiao.split(" · ")[0]), f"{int(r.zona)}ª", n0(r.votos), p2(r.pct), n0(r.secoes)]
             for r in locs_v.itertuples()], num=(4, 5, 6), cls="mini"))

    # 8: federais
    def prosa_fed(r):
        top = rio.groupby("NM_BAIRRO")[[r.n, "jorge"]].sum().sort_values(r.n, ascending=False).head(5)
        return (f"<h3>{tit(r.nome)} ({e(r.sg)}, {r.n}) — {e(r.st)}</h3><p>Teve {n0(r.vap)} votos no estado e {n0(r.cap)} na capital "
                f"({p2(r.sh)} dos válidos de federal na cidade), dos quais {n0(r.zo)} na Zona Oeste. A correlação controlada por região "
                f"com Jorge é de {d2(r.cc)} na capital e {d2(r.cc_zo)} na Zona Oeste, com índice de reduto controlado de {d2(r.liftc)}. "
                f"Sem controle, a correlação seria de {d2(r.c_cap)} na capital ({d2(r.c_ap5)} dentro da AP5 e {d2(r.c_ap4)} dentro da AP4), e "
                f"o índice de reduto, de {d2(r.lift)}. Os dois tiveram voto simultaneamente em {n0(r.ambos)} seções; ele superou Jorge em votos absolutos "
                f"em {n0(r.supera)} seções, Jorge o superou em {n0(r.perde)} e houve empate em {n0(r.empate)}. Os bairros em que teve mais "
                f"votos foram " + ", ".join(f"{tit(b)} ({n0(x[r.n])} votos; Jorge {n0(x.jorge)})" for b, x in top.iterrows()) + ".</p>")

    sec("s8", "8. Correlação com os deputados federais selecionados", f"""
<p>Para cada seção da capital com 50 ou mais votos válidos para deputado estadual ({n0(len(rb))} seções), calcula-se a fatia de Jorge nos
válidos de estadual e a fatia de cada federal nos válidos de federal. A <b>correlação</b> (de −1 a 1) mede se as duas fatias sobem e descem
juntas pelas seções. O <b>índice de reduto</b> compara o desempenho do federal nas {n0(len(red))} seções em que Jorge teve {p2(corte)} ou mais
dos válidos (o decil superior) com o desempenho dele na capital inteira; 1,00 é neutro, 2,00 é o dobro.</p>""" + METODO_CORR + """
<div class="callout"><b>Leitura correta.</b> É uma medida territorial, por seção, e não por eleitor: o voto é secreto. Afinidade alta é
compatível com dobrada ou com bases eleitorais sobrepostas, mas não prova que os mesmos eleitores votaram nos dois.</div>""" + tabela(
        ["Federal", "Partido", "Situação", "Votos RJ", "Capital", "Zona Oeste", "% capital", "Corr. controlada", "Contr. ZO",
         "Reduto contr.", "Corr. bruta", "Reduto bruto", "Supera Jorge", "Jorge supera"],
        [[tit(r.nome), e(r.sg), e(r.st), n0(r.vap), n0(r.cap), n0(r.zo), p2(r.sh), f"<b>{d2(r.cc)}</b>", d2(r.cc_zo), d2(r.liftc),
          d2(r.c_cap), d2(r.lift), n0(r.supera), n0(r.perde)] for r in fr.itertuples()], num=range(3, 14), cls="mini") +
        "".join(prosa_fed(r) for r in fr.itertuples()) +
        "<h3>Jorge e os oito federais, bairro a bairro</h3>" + tabela(
            ["Bairro", "AP", "Jorge"] + [tit(nm[(6, n)][0]) for n in feds],
            [[tit(r["NM_BAIRRO"]), e(r["regiao"].split(" · ")[0]), f"<b>{n0(r['jorge'])}</b>"] +
             [f"<b>{n0(r[n])}</b>" if r[n] > r["jorge"] else n0(r[n]) for n in feds]
             for r in fb.to_dict("records")], num=range(2, 3 + len(feds)), cls="mini"), quebra=True)

    rio_s = rio.sort_values(["zona", "secao"])
    sec("a1", "Anexo A. Capital, seção a seção: Jorge e os oito federais", f"""<p>Todas as {n0(len(rio_s))} seções principais da capital,
em ordem de zona e seção, inclusive as sem voto para Jorge. "Jorge %" é sobre os válidos de estadual da seção. Em negrito, os federais que
superaram Jorge na seção.</p>""" + tabela(
        ["Zona", "Seção", "Local", "Bairro", "Jorge", "Jorge %"] + [tit(nm[(6, n)][0]).split()[-1] for n in feds] + ["Válidos est."],
        [[f"{int(r['zona'])}ª", int(r["secao"]), tit(r["NM_LOCAL_VOTACAO"]), tit(r["NM_BAIRRO"]), f"<b>{n0(r['jorge'])}</b>", p2(r["pj"])] +
         [f"<b>{n0(r[n])}</b>" if r[n] > r["jorge"] else n0(r[n]) for n in feds] + [n0(r["val7"])]
         for r in rio_s.to_dict("records")], num=[4, 5] + list(range(6, 7 + len(feds))), cls="mini"), quebra=True)

    fora = d[(d.municipio != A.RIO) & (d.jorge > 0)].sort_values(["NM_MUNICIPIO", "zona", "secao"])
    sec("a2", "Anexo B. Demais municípios: seções com voto", f"<p>As {n0(len(fora))} seções fora da capital em que Jorge teve ao menos "
        f"um voto, somando {n0(fora.jorge.sum())} votos.</p>" + tabela(
            ["Município", "Zona", "Seção", "Local", "Bairro", "Votos", "Válidos", "%"],
            [[tit(r.NM_MUNICIPIO), f"{int(r.zona)}ª", int(r.secao), tit(r.NM_LOCAL_VOTACAO), tit(r.NM_BAIRRO), n0(r.jorge), n0(r.val7), p2(r.pj)]
             for r in fora.itertuples()], num=(5, 6, 7), cls="mini"), quebra=True)
    assert int(fora.jorge.sum()) + cap == total

    kp = [(n0(total), "votos · " + e(nm[(7, J)][2])), (f"{pos_est[0]}º", "posição no estado"), ("+" + p2(total / t22 * 100 - 100), f"sobre 2022 ({n0(t22)} votos)"),
          (n0(cap), f"capital · {pos_cap[0]}º lugar"), (n0(zo), f"Zona Oeste · {pos_zo[0]}º lugar"), (n0(len(d)), "seções apuradas")]
    return documento("Votação de Jorge Felippe Neto", "Deputado estadual · PL · 22800 — bairro a bairro, zona a zona, seção a seção, e "
                     "correlação com deputados federais", kp, toc, "".join(C)), (fedrows, fr)


# ---------------- PDF B: Douglas Ruas ----------------
def pdf_douglas(nm, v, base):
    g = v[v.cargo == 3]
    nomes_g = sorted({n for (c, n) in nm if c == 3 and nm[(c, n)][2] != "legenda"}, key=lambda n: -nm[(3, n)][3])
    sg = por_secao(v, 3, nomes_g)
    sbr = g[g.tipo == "branco"].groupby(KEYS).qtd.sum().rename("brancos")
    snu = g[g.tipo == "nulo"].groupby(KEYS).qtd.sum().rename("nulos")
    comp3 = pd.read_sql("SELECT municipio,zona,secao,aptos,comparecimento FROM secao WHERE cargo=3",
                        sqlite3.connect(f"{A.T}/eleicao2026_rj_secao.sqlite")).set_index(KEYS)
    d = base.drop(columns=["aptos", "comparecimento"]).merge(sg, left_on=KEYS, right_index=True, how="left") \
        .merge(sbr, left_on=KEYS, right_index=True, how="left").merge(snu, left_on=KEYS, right_index=True, how="left") \
        .merge(comp3, left_on=KEYS, right_index=True, how="left").fillna(0)
    assert int(d[DOUGLAS].sum()) == nm[(3, DOUGLAS)][3]
    rio = d[d.municipio == A.RIO]
    cols = ["aptos", "comparecimento", "validos", "brancos", "nulos"] + nomes_g

    def agg(df, by):
        x = df.groupby(by)[cols].sum().reset_index()
        x["secoes"] = df.groupby(by).size().values
        x["pd"] = x[DOUGLAS] / x.validos * 100
        x["pp"] = x[PAES] / x.validos * 100
        x["abst"] = (1 - x.comparecimento / x.aptos) * 100
        return x

    ap = agg(rio, ["regiao"])
    za = agg(rio, ["regiao", "zona"])
    zt = agg(rio, ["zona"])
    pred = za.sort_values("aptos", ascending=False).drop_duplicates("zona").set_index("zona").regiao
    zt["ap_pred"] = zt.zona.map(pred)
    zt["n_aps"] = zt.zona.map(za.groupby("zona").size())
    ba = agg(rio, ["regiao", "NM_BAIRRO"])
    est = d[cols].sum()
    capt = rio[cols].sum()
    assert int(za[DOUGLAS].sum()) == int(capt[DOUGLAS]) == int(zt[DOUGLAS].sum()) == int(ap[DOUGLAS].sum())

    outros = [n for n in nomes_g if n not in (DOUGLAS, PAES)]
    C, toc = [], []

    def sec(a, t, c, quebra=False):
        toc.append((a, t))
        C.append(f'<h2 id="{a}" class="{"pg" if quebra else ""}">{e(t)}</h2>{c}')

    def linha_zona(r, com_ap=False):
        return ([f"{int(r.zona)}ª"] + ([e(r.ap_pred.split(" · ")[0]), str(int(r.n_aps))] if com_ap else []) +
                [n0(r.aptos), p2(r.abst), n0(r.validos), n0(r[DOUGLAS]), p2(r.pd), n0(r[PAES]), p2(r.pp),
                 ("+" if r[DOUGLAS] - r[PAES] > 0 else "") + n0(r[DOUGLAS] - r[PAES]), n0(r.secoes)])

    cab = ["Zona", "Aptos", "Abstenção", "Válidos", "Douglas", "Douglas %", "Paes", "Paes %", "Diferença", "Seções"]
    apo = ap.assign(o=ap.regiao.map(ORD_AP.index)).sort_values("o")
    venceu = [r["regiao"] for _, r in apo.iterrows() if r[DOUGLAS] > r[PAES]]
    menor = apo.loc[(apo[PAES] - apo[DOUGLAS]).idxmin()]
    pior = apo.loc[(apo.pd - apo.pp).idxmin()]
    zv = int((zt[DOUGLAS] > zt[PAES]).sum())
    sec("d1", "1. Sumário executivo", f"""
<p>Douglas Ruas (PL, 22) terminou o 1º turno da eleição para governador do Estado do Rio de Janeiro com <b>{n0(nm[(3, DOUGLAS)][3])} votos
({p2(est[DOUGLAS] / est.validos * 100)} dos válidos)</b> e disputará o 2º turno com Eduardo Paes (PSD, 55), que teve {n0(est[PAES])} votos
({p2(est[PAES] / est.validos * 100)}).</p>
<p>Na capital, Douglas teve <b>{n0(capt[DOUGLAS])} votos ({p2(capt[DOUGLAS] / capt.validos * 100)} dos válidos)</b>, contra
{n0(capt[PAES])} de Paes ({p2(capt[PAES] / capt.validos * 100)}): {"vantagem" if capt[DOUGLAS] > capt[PAES] else "desvantagem"} de
{n0(abs(capt[DOUGLAS] - capt[PAES]))} votos. Venceu Paes em {zv} das {len(zt)} zonas eleitorais da cidade. {("Venceu nas Áreas de Planejamento " + ", ".join(venceu) + ".") if venceu else
f"Não venceu em nenhuma Área de Planejamento; a disputa mais apertada foi na {menor['regiao']}, onde ficou {n0(abs(menor[DOUGLAS] - menor[PAES]))} votos atrás de Paes ({p2(menor.pd)} contra {p2(menor.pp)}), e a mais desfavorável na {pior['regiao']} ({p2(pior.pd)} contra {p2(pior.pp)})."}</p>
<p>A melhor zona de Douglas em percentual foi a {int(zt.sort_values("pd").iloc[-1].zona)}ª ({p2(zt.pd.max())}); a pior, a
{int(zt.sort_values("pd").iloc[0].zona)}ª ({p2(zt.pd.min())}). Em votos absolutos, a maior votação foi na
{int(zt.sort_values(DOUGLAS).iloc[-1].zona)}ª zona ({n0(zt[DOUGLAS].max())} votos).</p>""")

    sec("d2", "2. Fonte, método e como ler as zonas", """
<p>Os números vêm dos boletins de urna de cada seção da capital, publicados pelo Tribunal Superior Eleitoral (pleito 3220, 1º turno de
04/10/2026), e foram conferidos contra o total oficial do TSE: a soma das seções é idêntica ao total de cada candidato a governador.
Percentuais são sobre os votos válidos para governador (excluídos brancos e nulos). Abstenção = 1 − comparecimento ÷ eleitores aptos.</p>
<div class="callout"><b>Zona eleitoral não é Área de Planejamento.</b> A zona é uma divisão da Justiça Eleitoral e pode ter seções em mais
de uma AP. Por isso, na seção 4, cada AP lista as zonas com a votação de Douglas <b>apenas nas seções daquela AP</b>; uma zona que cruza a
fronteira aparece em mais de uma AP, com a parte correspondente. A seção 5 traz o total de cada zona, a AP que concentra a maior parte dos
eleitores dela e em quantas APs ela tem seções. A AP de cada seção é a do bairro oficial em que fica a escola.</div>""")

    sec("d3", "3. Resultado por Área de Planejamento", tabela(
        ["Área de Planejamento", "Aptos", "Abstenção", "Válidos", "Douglas", "Douglas %", "Paes", "Paes %", "Diferença", "Seções"],
        [[e(r["regiao"]), n0(r.aptos), p2(r.abst), n0(r.validos), n0(r[DOUGLAS]), p2(r.pd), n0(r[PAES]), p2(r.pp),
          ("+" if r[DOUGLAS] - r[PAES] > 0 else "") + n0(r[DOUGLAS] - r[PAES]), n0(r.secoes)] for _, r in apo.iterrows()] +
        [["<b>Capital</b>", n0(capt.aptos), p2((1 - capt.comparecimento / capt.aptos) * 100), n0(capt.validos), f"<b>{n0(capt[DOUGLAS])}</b>",
          p2(capt[DOUGLAS] / capt.validos * 100), n0(capt[PAES]), p2(capt[PAES] / capt.validos * 100),
          ("+" if capt[DOUGLAS] > capt[PAES] else "") + n0(capt[DOUGLAS] - capt[PAES]), n0(len(rio))]],
        num=range(1, 10)) + "<h3>Todos os candidatos por AP (% dos válidos)</h3>" + tabela(
        ["Área de Planejamento"] + [tit(nm[(3, n)][0]) for n in nomes_g],
        [[e(r["regiao"])] + [p2(r[n] / r.validos * 100) for n in nomes_g] for _, r in apo.iterrows()],
        num=range(1, 1 + len(nomes_g)), cls="mini"))

    blocos = ""
    for a in ORD_AP:
        x = za[za.regiao == a].sort_values(DOUGLAS, ascending=False)
        if x.empty:
            continue
        t = x[cols].sum()
        blocos += (f'<h3>{e(a)} — Douglas {n0(t[DOUGLAS])} votos ({p2(t[DOUGLAS] / t.validos * 100)}) · Paes {n0(t[PAES])} '
                   f'({p2(t[PAES] / t.validos * 100)}) · {len(x)} zonas</h3>' +
                   tabela(cab, [linha_zona(r) for _, r in x.iterrows()], num=range(1, 10)) +
                   "<p class='nota'>Demais candidatos nas zonas desta AP: " + "; ".join(
                       f"{int(r.zona)}ª — " + ", ".join(f"{tit(nm[(3, n)][0])} {n0(r[n])}" for n in outros)
                       for _, r in x.iterrows()) + ".</p>")
    sec("d4", "4. Zonas eleitorais dentro de cada Área de Planejamento", blocos)

    sec("d5", "5. Total de cada zona eleitoral da capital", "<p>Cada zona aparece uma vez, com a soma de todas as suas seções. "
        "\"AP predominante\" é a AP com mais eleitores aptos na zona; \"Nº de APs\" indica em quantas APs a zona tem seções.</p>" + tabela(
            ["Zona", "AP predominante", "Nº de APs"] + cab[1:], [linha_zona(r, True) for _, r in zt.sort_values("zona").iterrows()],
            num=range(2, 12)), quebra=True)

    bl = ""
    for a in ORD_AP:
        x = ba[ba.regiao == a].sort_values(DOUGLAS, ascending=False)
        if x.empty:
            continue
        bl += f"<h3>{e(a)}</h3>" + tabela(["Bairro", "Válidos", "Douglas", "Douglas %", "Paes", "Paes %", "Diferença"],
                                          [[tit(r.NM_BAIRRO), n0(r.validos), n0(r[DOUGLAS]), p2(r.pd), n0(r[PAES]), p2(r.pp),
                                            ("+" if r[DOUGLAS] - r[PAES] > 0 else "") + n0(r[DOUGLAS] - r[PAES])] for _, r in x.iterrows()],
                                          num=range(1, 7))
    sec("d6", "6. Complemento: bairros de cada Área de Planejamento", bl, quebra=True)

    kp = [(n0(nm[(3, DOUGLAS)][3]), f"votos no estado · {p2(est[DOUGLAS] / est.validos * 100)}"), (n0(capt[DOUGLAS]), f"na capital · {p2(capt[DOUGLAS] / capt.validos * 100)}"),
          (f"{zv} de {len(zt)}", "zonas da capital vencidas"), (n0(capt[PAES]), f"Paes na capital · {p2(capt[PAES] / capt.validos * 100)}"),
          (("+" if capt[DOUGLAS] > capt[PAES] else "") + n0(capt[DOUGLAS] - capt[PAES]), "diferença na capital"), (n0(len(rio)), "seções da capital")]
    return documento("Douglas Ruas na capital: zona a zona, por Área de Planejamento", "Governador · PL · 22 — 1º turno, cidade do Rio de Janeiro",
                     kp, toc, "".join(C))


def pdf_federal(nm, d, n):
    """Comparativo Jorge × um federal na capital: AP, zona, zona por AP, bairro e seção a seção."""
    nome, sg, st, vap = nm[(6, n)]
    assert int(d[n].sum()) == vap, (nome, int(d[n].sum()), vap)  # soma das seções do estado = total oficial do TSE
    nome_t = tit(nome)
    rio = d[d.municipio == A.RIO].copy()
    rio["f"] = rio[n]
    rio["pf"] = rio.f / rio.val6.replace(0, np.nan) * 100
    rio["dif"] = rio.jorge - rio.f
    cap_j, cap_f = int(rio.jorge.sum()), int(rio.f.sum())

    def agg(df, by):
        g = df.groupby(by).agg(j=("jorge", "sum"), f=("f", "sum"), val7=("val7", "sum"), val6=("val6", "sum"),
                               secoes=("secao", "count")).reset_index()
        g["pj"] = g.j / g.val7 * 100
        g["pf"] = g.f / g.val6 * 100
        g["dif"] = g.j - g.f
        w = df.assign(jv=df.jorge > df.f, fv=df.f > df.jorge).groupby(by)[["jv", "fv"]].sum().reset_index()
        return g.merge(w, on=by)

    ap = agg(rio, ["regiao"])
    ap = ap.assign(o=ap.regiao.map(ORD_AP.index)).sort_values("o")
    zt = agg(rio, ["zona"]).sort_values("zona")
    za = agg(rio, ["zona", "regiao"])
    ba = agg(rio, ["regiao", "NM_BAIRRO"])
    assert int(zt.j.sum()) == cap_j == int(ba.j.sum()) and int(zt.f.sum()) == cap_f == int(ba.f.sum())

    rb = rio[rio.val7 >= 50]

    def corr(df):
        ok = df.pj.notna() & df.pf.notna()
        return float(np.corrcoef(df.pj[ok], df.pf[ok])[0, 1]) if ok.sum() > 2 and df.pf[ok].std() > 0 else None

    c_cap = corr(rb)
    zo_m = rb.regiao.isin(A.ZONA_OESTE)
    cc = A.corr_controlada(rb.pj, rb.pf, rb.regiao)
    cc_zo = A.corr_controlada(rb.pj[zo_m], rb.pf[zo_m], rb.regiao[zo_m])
    liftc = A.lift_controlado(rb.pj, rb.f, rb.val6, rb.regiao)
    loc_id = rb.zona.astype(str) + "-" + rb.NR_LOCAL_VOTACAO.astype(str)
    pl6 = rb.pl6 / rb.val6.replace(0, np.nan) * 100
    pl7 = rb.pl7 / rb.val7.replace(0, np.nan) * 100
    medidas = [("Cidade inteira, sem controle (bruta)", c_cap),
               ("<b>Dentro da mesma Área de Planejamento (controlada)</b>", cc),
               ("Dentro da mesma zona eleitoral", A.corr_controlada(rb.pj, rb.pf, rb.zona)),
               ("Dentro do mesmo bairro", A.corr_controlada(rb.pj, rb.pf, rb.NM_BAIRRO)),
               ("Dentro do mesmo local de votação", A.corr_controlada(rb.pj, rb.pf, loc_id))] + [
              (f"Somente na {ap}", corr(rb[rb.regiao == ap])) for ap in ORD_AP] + [
              ("Jorge × voto total do PL para federal (referência)", corr(rb.assign(pf=pl6))),
              (f"{nome_t} × voto total do PL para estadual (referência)", corr(rb.assign(pj=pl7)))]
    corte = rb.pj.quantile(0.9)
    red = rb[rb.pj >= corte]
    sh = cap_f / rio.val6.sum() * 100
    shr = red.f.sum() / red.val6.sum() * 100
    jv, fv = int((rio.jorge > rio.f).sum()), int((rio.f > rio.jorge).sum())
    emp = len(rio) - jv - fv
    zj, zf = int((zt.j > zt.f).sum()), int((zt.f > zt.j).sum())

    def sinal(x):
        return ("+" if x > 0 else "") + n0(x)

    def vence(a, b):
        return "Jorge" if a > b else (nome_t if b > a else "empate")

    C, toc = [], []

    def sec(a, t, c, quebra=False):
        toc.append((a, t))
        C.append(f'<h2 id="{a}" class="{"pg" if quebra else ""}">{e(t)}</h2>{c}')

    zj_top = zt.sort_values("dif", ascending=False).head(5)
    zf_top = zt.sort_values("dif").head(5)
    ambos = ba[(ba.pj > cap_j / rio.val7.sum() * 100) & (ba.pf > sh)].sort_values("j", ascending=False)
    sec("f1", "1. Sumário executivo", f"""
<p>Na cidade do Rio de Janeiro, Jorge Felippe Neto (PL, 22800, deputado estadual) teve <b>{n0(cap_j)} votos</b>
({p2(cap_j / rio.val7.sum() * 100)} dos válidos de estadual) e {nome_t} ({e(sg)}, {n}, deputado federal, {e(st[0].lower() + st[1:])}) teve
<b>{n0(cap_f)} votos</b> ({p2(sh)} dos válidos de federal); no estado inteiro, {nome_t} somou {n0(vap)} votos. Como são cargos
diferentes, a comparação é feita em votos absolutos e, para medir força relativa, cada um sobre os válidos do próprio cargo.</p>
<p>Seção a seção, Jorge teve mais votos que {nome_t} em <b>{n0(jv)}</b> das {n0(len(rio))} seções da capital, {nome_t} teve mais em
<b>{n0(fv)}</b> e houve empate em {n0(emp)}. Por zona eleitoral, Jorge supera em {zj} das {len(zt)} zonas e {nome_t} em {zf}.
As maiores vantagens de Jorge estão nas zonas {", ".join(f"{int(r.zona)}ª ({sinal(r.dif)})" for r in zj_top.itertuples())}; as de
{nome_t}, nas zonas {", ".join(f"{int(r.zona)}ª ({sinal(r.dif)})" for r in zf_top.itertuples() if r.dif < 0) or "— nenhuma"}.</p>
<p>A <b>correlação controlada por região</b> entre as duas votações (fatia de cada um por seção, comparada dentro da mesma Área de
Planejamento) é de <b>{d2(cc)}</b> na capital e {d2(cc_zo)} na Zona Oeste, de −1 a 1. O <b>índice de reduto controlado</b> é
{d2(liftc)}: nas seções em que Jorge é mais forte dentro de cada AP, {nome_t} teve {p2(abs(liftc - 1) * 100) if liftc else "—"}
{"a mais" if (liftc or 1) >= 1 else "a menos"} do que a própria média naquela AP. Sem o controle por região, a correlação seria de
{d2(c_cap)}, porque mistura a geografia dos dois com a afinidade entre eles; a seção 3 mostra todas as medidas.</p>
<p>Bairros em que os dois ficam acima da própria média na cidade: {", ".join(f"{tit(r.NM_BAIRRO)} (Jorge {n0(r.j)}; {nome_t} {n0(r.f)})" for r in ambos.head(10).itertuples()) or "nenhum"}.</p>""")

    sec("f2", "2. Fonte e leitura", """
<p>Os números vêm dos boletins de urna de cada seção da capital, publicados pelo Tribunal Superior Eleitoral (pleito 3220, 1º turno de
04/10/2026), conferidos contra o total oficial do TSE (a soma das seções é idêntica ao total de cada candidato). "Diferença" é
sempre <b>votos de Jorge menos votos do federal</b>: positivo, Jorge à frente; negativo, o federal à frente. A Área de Planejamento
(AP) de cada seção é a do bairro oficial em que fica a escola; como zona eleitoral não respeita limite de AP, a seção 5 também reparte cada
zona pelas APs em que ela tem seções.</p>
<div class="callout"><b>Leitura correta.</b> A comparação é territorial, por seção. O voto é secreto: votações que sobem juntas são
compatíveis com dobrada ou com bases sobrepostas, mas não provam que os mesmos eleitores votaram nos dois.</div>""")

    sec("fc", "3. Correlação com Jorge", METODO_CORR + tabela(
        ["Medida (fatias por seção, seções com 50 ou mais válidos)", "Correlação"],
        [[m, f"<b>{d2(x)}</b>" if "controlada" in m else d2(x)] for m, x in medidas], num=(1,)) + f"""
<p>As duas últimas linhas são referência: mostram o quanto cada um acompanha o voto do PL no outro cargo, que é o eleitorado que os
dois disputam. Índice de reduto controlado: <b>{d2(liftc)}</b>; sem controle: {d2(shr / sh if sh else None)}.</p>""")

    curto = CURTO.get(n, nome_t)
    cab = ["Jorge", "Jorge %", nome_t, f"{curto} %", "Diferença", "Seções Jorge à frente", f"Seções {curto} à frente"]

    def lin(r):
        return [n0(r.j), p2(r.pj), n0(r.f), p2(r.pf), sinal(r.dif), n0(r.jv), n0(r.fv)]

    sec("f3", "4. Por Área de Planejamento", tabela(
        ["Área de Planejamento"] + cab + ["Seções"],
        [[e(r.regiao)] + lin(r) + [n0(r.secoes)] for r in ap.itertuples()] +
        [["<b>Capital</b>", f"<b>{n0(cap_j)}</b>", p2(cap_j / rio.val7.sum() * 100), f"<b>{n0(cap_f)}</b>", p2(sh), sinal(cap_j - cap_f),
          n0(jv), n0(fv), n0(len(rio))]], num=range(1, 9)))

    za_rows = []
    for z in zt.zona:
        for r in za[za.zona == z].sort_values("j", ascending=False).itertuples():
            za_rows.append([f"{int(z)}ª", e(r.regiao)] + lin(r))
    sec("f4", "5. Zona a zona", "<h3>Total de cada zona eleitoral da capital</h3>" + tabela(
        ["Zona"] + cab + ["Quem tem mais votos", "Seções"],
        [[f"{int(r.zona)}ª"] + lin(r) + [vence(r.j, r.f), n0(r.secoes)] for r in zt.itertuples()], num=range(1, 8)) +
        "<h3>Cada zona repartida por Área de Planejamento</h3>" + tabela(["Zona", "AP"] + cab, za_rows, num=range(2, 9)))

    bl = ""
    for a in ORD_AP:
        x = ba[ba.regiao == a].sort_values("j", ascending=False)
        if not x.empty:
            bl += f"<h3>{e(a)}</h3>" + tabela(["Bairro"] + cab + ["Seções"], [[tit(r.NM_BAIRRO)] + lin(r) + [n0(r.secoes)] for r in x.itertuples()],
                                             num=range(1, 9))
    sec("f5", "6. Bairro a bairro", bl, quebra=True)

    rs = rio.sort_values(["zona", "secao"])
    sec("f6", "7. Seção a seção", f"<p>As {n0(len(rs))} seções principais da capital, em ordem de zona e seção. Em destaque, as seções em "
        f"que {nome_t} teve mais votos que Jorge.</p>" + tabela(
            ["Zona", "Seção", "Local de votação", "Bairro", "AP", "Jorge", "Jorge %", curto, f"{curto} %", "Diferença"],
            [[f"{int(r['zona'])}ª", int(r["secao"]), tit(r["NM_LOCAL_VOTACAO"]), tit(r["NM_BAIRRO"]), e(r["regiao"].split(" · ")[0]),
              n0(r["jorge"]), p2(r["pj"]), n0(r["f"]), p2(r["pf"]), sinal(r["dif"])] for r in rs.to_dict("records")],
            num=range(5, 10), cls="mini", destaque=lambda j, _r=rs.f.values, _j=rs.jorge.values: _r[j] > _j[j]), quebra=True)

    kp = [(n0(cap_j), "votos de Jorge na capital"), (n0(cap_f), f"votos de {nome_t} na capital"), (d2(cc), "correlação controlada por região"),
          (n0(jv), "seções com Jorge à frente"), (n0(fv), f"seções com {nome_t} à frente"), (f"{zj} × {zf}", "zonas: Jorge × federal")]
    return documento(f"Jorge Felippe Neto × {nome_t}", f"Capital · deputado estadual (PL, 22800) × deputado federal ({e(sg)}, {n}) — "
                     "zona a zona e seção a seção", kp, toc, "".join(C))


def pdf_mesmas_urnas(nm, d):
    """Votos de Jorge e dos oito federais nas MESMAS urnas: quanto de cada federal veio das urnas em que
    Jorge teve voto, por faixa de força de Jorge, por zona e urna a urna (todo o estado)."""
    feds = list(A.FEDS)
    J = A.JFN
    tot_j = int(d.jorge.sum())
    assert tot_j == nm[(7, J)][3]
    for n in feds:
        assert int(d[n].sum()) == nm[(6, n)][3], nm[(6, n)][0]
    comj = d[d.jorge > 0]
    cap = d.municipio == A.RIO
    faixas = [(1, 4), (5, 9), (10, 19), (20, 10 ** 6)]
    rot_f = {(1, 4): "1 a 4", (5, 9): "5 a 9", (10, 19): "10 a 19", (20, 10 ** 6): "20 ou mais"}

    linhas = []
    for n in feds:
        nome, sg, st, vap = nm[(6, n)]
        mesmas = int(comj[n].sum())
        mesmas_cap = int(comj[comj.municipio == A.RIO][n].sum())
        cap_f = int(d[cap][n].sum())
        j_nas_dele = int(d[d[n] > 0].jorge.sum())
        linhas.append(dict(n=n, nome=nome, sg=sg, st=st, vap=vap, mesmas=mesmas, pct=mesmas / vap * 100 if vap else None,
                           cap_f=cap_f, mesmas_cap=mesmas_cap, pct_cap=mesmas_cap / cap_f * 100 if cap_f else None,
                           urnas_ambos=int(((d.jorge > 0) & (d[n] > 0)).sum()), urnas_f=int((d[n] > 0).sum()),
                           j_nas_dele=j_nas_dele, pct_j=j_nas_dele / tot_j * 100,
                           **{f"fx{a}": int(d[(d.jorge >= a) & (d.jorge <= b)][n].sum()) for a, b in faixas},
                           fx0=int(d[d.jorge == 0][n].sum())))
    L = pd.DataFrame(linhas).sort_values("mesmas", ascending=False)
    for r in L.itertuples():  # as faixas fecham o total do federal
        assert r.fx0 + sum(getattr(r, f"fx{a}") for a, _ in faixas) == r.vap, r.nome

    C, toc = [], []

    def sec(a, t, c, quebra=False):
        toc.append((a, t))
        C.append(f'<h2 id="{a}" class="{"pg" if quebra else ""}">{e(t)}</h2>{c}')

    top = L.iloc[0]
    sec("u1", "1. Sumário executivo", f"""
<p>Jorge Felippe Neto teve voto em <b>{n0(len(comj))} urnas</b> (seções) do Estado do Rio de Janeiro, {n0(int((comj.municipio == A.RIO).sum()))}
delas na capital, somando {n0(tot_j)} votos. Este relatório mostra quantos votos cada um dos oito candidatos a deputado federal
selecionados teve <b>nessas mesmas urnas</b>, e quanto isso representa do total de cada um.</p>
<p>Em votos absolutos, quem mais votou nas mesmas urnas de Jorge foi <b>{tit(top.nome)}</b>, com {n0(top.mesmas)} votos
({p2(top.pct)} do total dele no estado). Em proporção, a maior dependência das urnas de Jorge é de
<b>{tit(L.sort_values("pct", ascending=False).iloc[0].nome)}</b> ({p2(L.pct.max())} dos votos vieram de urnas em que Jorge teve voto).
O quadro da seção 3 reparte os votos de cada federal pela força de Jorge na urna: quanto mais votos de um federal estão nas urnas em que
Jorge teve 10 ou mais votos, mais as duas votações se concentram nos mesmos lugares.</p>""")

    sec("u2", "2. Leitura", """
<p>Urna, aqui, é a seção eleitoral: cada seção principal tem um boletim de urna, publicado pelo Tribunal Superior Eleitoral (pleito 3220,
1º turno de 04/10/2026), e as seções agregadas votam na urna da principal. Os totais por candidato foram conferidos contra o total oficial
do TSE, e a soma das faixas de cada federal fecha exatamente com o total dele.</p>
<div class="callout"><b>Leitura correta.</b> Estar na mesma urna não significa ser o mesmo eleitor: o voto é secreto. Uma urna com 10 votos
para Jorge e 10 para um federal pode ter 20 eleitores diferentes ou os mesmos 10. O relatório mede a coincidência de lugar, que é
compatível com dobrada, mas não a prova.</div>""")

    sec("u3", "3. Votos de cada federal nas urnas de Jorge", tabela(
        ["Federal", "Partido", "Votos no estado", "Nas urnas com voto de Jorge", "% do total", "Na capital",
         "Nas urnas de Jorge na capital", "% capital", "Urnas com os dois", "Votos de Jorge nas urnas dele", "% de Jorge"],
        [[f"{tit(r.nome)} <span class='nota'>{r.n}</span>", e(r.sg), n0(r.vap), f"<b>{n0(r.mesmas)}</b>", p2(r.pct), n0(r.cap_f),
          n0(r.mesmas_cap), p2(r.pct_cap), n0(r.urnas_ambos), n0(r.j_nas_dele), p2(r.pct_j)] for r in L.itertuples()],
        num=range(2, 11), cls="mini") + "<h3>Votos de cada federal conforme a votação de Jorge na urna</h3>" + tabela(
        ["Federal", "Urnas sem voto de Jorge"] + [f"Jorge com {rot_f[f]} votos" for f in faixas] + ["Total"],
        [[tit(r.nome), n0(r.fx0)] + [n0(getattr(r, f"fx{a}")) for a, _ in faixas] + [f"<b>{n0(r.vap)}</b>"] for r in L.itertuples()],
        num=range(1, 7)) + "<p class='nota'>Número de urnas em cada faixa de votos de Jorge: " + "; ".join(
        f"{rot_f[(a, b)]}: {n0(int(((d.jorge >= a) & (d.jorge <= b)).sum()))}" for a, b in faixas) +
        f"; sem voto: {n0(int((d.jorge == 0).sum()))}.</p>" + "".join(
        f"<p><b>{tit(r.nome)}</b> ({e(r.sg)}, {r.n}, {e(r.st[0].lower() + r.st[1:])}) teve {n0(r.mesmas)} dos seus {n0(r.vap)} votos "
        f"({p2(r.pct)}) em urnas onde Jorge também foi votado, e {n0(r.fx20 + r.fx10)} nas urnas em que Jorge teve 10 ou mais votos. "
        f"Os dois tiveram voto juntos em {n0(r.urnas_ambos)} das {n0(r.urnas_f)} urnas em que {tit(r.nome)} foi votado; nessas urnas, "
        f"Jorge somou {n0(r.j_nas_dele)} votos ({p2(r.pct_j)} do total dele).</p>" for r in L.itertuples()))

    zz = comj.groupby(["NM_MUNICIPIO", "zona"])[["jorge"] + feds].sum().reset_index()
    zz["urnas"] = comj.groupby(["NM_MUNICIPIO", "zona"]).size().values
    zz = zz.sort_values("jorge", ascending=False)
    curto = [CURTO[n] for n in feds]
    sec("u4", "4. Zona a zona: votos nas urnas com voto de Jorge", f"<p>As {len(zz)} combinações de município e zona eleitoral em que "
        "Jorge teve voto. Em cada linha, só entram as urnas em que Jorge foi votado; os números dos federais são os votos deles nessas "
        "mesmas urnas.</p>" + tabela(
            ["Município", "Zona", "Urnas", "Jorge"] + curto,
            [[tit(r["NM_MUNICIPIO"]), f"{int(r['zona'])}ª", n0(r["urnas"]), f"<b>{n0(r['jorge'])}</b>"] + [n0(r[n]) for n in feds]
             for r in zz.to_dict("records")], num=range(2, 4 + len(feds)), cls="mini"), quebra=True)
    assert int(zz.jorge.sum()) == tot_j

    uu = comj.sort_values(["NM_MUNICIPIO", "zona", "secao"])
    sec("u5", "5. Urna a urna", f"<p>As {n0(len(uu))} urnas do estado em que Jorge teve ao menos um voto, por município, zona e seção, com "
        "os votos de cada federal na mesma urna. Em destaque, o federal que teve mais votos que Jorge naquela urna.</p>" + tabela(
            ["Município", "Zona", "Seção", "Local de votação", "Bairro", "Jorge"] + curto,
            [[tit(r["NM_MUNICIPIO"]), f"{int(r['zona'])}ª", int(r["secao"]), tit(r["NM_LOCAL_VOTACAO"]), tit(r["NM_BAIRRO"]),
              f"<b>{n0(r['jorge'])}</b>"] + [f"<b>{n0(r[n])}</b>" if r[n] > r["jorge"] else n0(r[n]) for n in feds]
             for r in uu.to_dict("records")], num=range(5, 6 + len(feds)), cls="mini"), quebra=True)

    kp = [(n0(len(comj)), "urnas com voto de Jorge"), (n0(tot_j), "votos de Jorge"),
          (n0(int(L.mesmas.sum())), "votos dos 8 federais nessas urnas"),
          (tit(top.nome), f"mais votos nas mesmas urnas ({n0(top.mesmas)})"),
          (p2(L.pct.max()), f"maior dependência: {tit(L.sort_values('pct', ascending=False).iloc[0].nome)}"),
          (n0(int((comj.municipio == A.RIO).sum())), "dessas urnas na capital")]
    return documento("Votos nas mesmas urnas: Jorge e os oito federais", "Deputado estadual (PL, 22800) e deputados federais selecionados — "
                     "estado do Rio de Janeiro, urna a urna", kp, toc, "".join(C))


def pdf_estado(nm, v, base):
    """Relatório estadual de Jorge, cidade a cidade: um capítulo por município com zona, bairro, local e
    TODAS as seções (inclusive as sem voto), com a posição de Jorge em cada urna."""
    J = A.JFN
    x7 = v[(v.cargo == 7)]
    val = x7[x7.valido].groupby(KEYS).qtd.sum().rename("val7")
    nomi = x7[x7.tipo == "nominal"][KEYS + ["numero", "qtd"]]
    jv = nomi[nomi.numero == J].set_index(KEYS).qtd.rename("jorge")
    # posição de Jorge em cada urna (empate = mesma posição); seção sem voto dele fica sem posição
    nomi = nomi.assign(pos=nomi.groupby(KEYS).qtd.rank(ascending=False, method="min"))
    posu = nomi[(nomi.numero == J) & (nomi.qtd > 0)].set_index(KEYS).pos.rename("pos")
    d = base.merge(val, left_on=KEYS, right_index=True, how="left").merge(jv, left_on=KEYS, right_index=True, how="left") \
        .merge(posu, left_on=KEYS, right_index=True, how="left").fillna({"val7": 0, "jorge": 0})
    d["pj"] = d.jorge / d.val7.replace(0, np.nan) * 100
    total = int(d.jorge.sum())
    assert total == nm[(7, J)][3]
    vtot = d.val7.sum()
    # ranking por município
    mun_rank = nomi.merge(base[KEYS + ["NM_MUNICIPIO"]], on=KEYS).groupby(["NM_MUNICIPIO", "numero"]).qtd.sum().reset_index()
    mun_rank["p"] = mun_rank.groupby("NM_MUNICIPIO").qtd.rank(ascending=False, method="min")
    pos_m = mun_rank[mun_rank.numero == J].set_index("NM_MUNICIPIO").p
    ncand = mun_rank[mun_rank.qtd > 0].groupby("NM_MUNICIPIO").size()
    lider = mun_rank.sort_values("qtd", ascending=False).drop_duplicates("NM_MUNICIPIO").set_index("NM_MUNICIPIO")
    j22 = pd.read_csv(f"{A.T}/jfn_2022_secao_RJ.csv", sep=";").groupby("nm_municipio").votos_jfn.sum()
    t22 = int(j22.sum())

    mun = d.groupby("NM_MUNICIPIO").agg(votos=("jorge", "sum"), val=("val7", "sum"), secoes=("secao", "count"),
                                         com_voto=("jorge", lambda s: int((s > 0).sum())), aptos=("aptos", "sum"),
                                         comp=("comparecimento", "sum")).reset_index()
    mun["pct"] = mun.votos / mun.val * 100
    mun["pos"] = mun.NM_MUNICIPIO.map(pos_m)
    mun["ncand"] = mun.NM_MUNICIPIO.map(ncand)
    mun["v22"] = mun.NM_MUNICIPIO.map(j22).fillna(0)
    mun = mun.sort_values(["votos", "NM_MUNICIPIO"], ascending=[False, True]).reset_index(drop=True)
    mun["anc"] = [f"m{i}" for i in range(len(mun))]
    assert len(mun) == 92 and int(mun.votos.sum()) == total

    def sinal(x):
        return ("+" if x > 0 else "") + n0(x)

    toc = [("e1", "Visão do estado"), ("e2", "Fonte e leitura"), ("e3", "Os 92 municípios")]
    C = [f"""<h2 id="e1">Visão do estado</h2>
<p>Jorge Felippe Neto (PL, 22800) teve <b>{n0(total)} votos</b> para deputado estadual em 2026, {p2(total / vtot * 100)} dos válidos
do estado, com voto em <b>{int((mun.votos > 0).sum())} dos 92 municípios</b> e em {n0(int((d.jorge > 0).sum()))} das {n0(len(d))} seções.
Em 2022 foram {n0(t22)} votos, em {int((j22 > 0).sum())} municípios. A capital respondeu por
{p2(mun.set_index("NM_MUNICIPIO").votos.get("RIO DE JANEIRO", 0) / total * 100)} da votação; os municípios seguintes foram
{", ".join(f"{tit(r.NM_MUNICIPIO)} ({n0(r.votos)})" for r in mun.iloc[1:6].itertuples())}. Em percentual dos válidos, os maiores
índices foram {", ".join(f"{tit(r.NM_MUNICIPIO)} ({p2(r.pct)})" for r in mun.sort_values("pct", ascending=False).head(5).itertuples())}.</p>""",
         """<h2 id="e2">Fonte e leitura</h2>
<p>Os números vêm dos boletins de urna de todas as seções do Estado do Rio de Janeiro, publicados pelo Tribunal Superior Eleitoral
(pleito 3220, 1º turno de 04/10/2026); a soma das seções é idêntica ao total oficial do TSE. Votos válidos são os nominais e de legenda
para deputado estadual. "Posição" é o lugar de Jorge entre os candidatos a estadual com voto no recorte (município ou urna), com empates
na mesma posição; numa urna sem voto para Jorge, a posição fica em branco. """ + FONTE_BAIRRO + """
Cada município tem um capítulo, na ordem da votação de Jorge, com zonas, bairros, locais e todas as seções, inclusive as sem voto. As
seções agregadas não aparecem em linha própria porque votam na urna da seção principal, onde seus votos já estão contados.</p>""",
         '<h2 id="e3">Os 92 municípios</h2>' + tabela(
             ["#", "Município", "Votos 2026", "% válidos", "Posição", "Votos 2022", "Variação", "Seções com voto"],
             [[str(i + 1), f'<a href="#{r.anc}">{tit(r.NM_MUNICIPIO)}</a>', n0(r.votos), p2(r.pct),
               f"{int(r.pos)}º de {n0(r.ncand)}" if not pd.isna(r.pos) else "—", n0(r.v22), sinal(r.votos - r.v22),
               f"{n0(r.com_voto)} de {n0(r.secoes)}"] for i, r in enumerate(mun.itertuples())], num=(0, 2, 3, 5, 6, 7))]

    for i, r in enumerate(mun.itertuples()):
        m = d[d.NM_MUNICIPIO == r.NM_MUNICIPIO]
        lid_n, lid_v = lider.numero.get(r.NM_MUNICIPIO), lider.qtd.get(r.NM_MUNICIPIO)
        zt = m.groupby("zona").agg(votos=("jorge", "sum"), val=("val7", "sum"), secoes=("secao", "count")).reset_index()
        zt["pct"] = zt.votos / zt.val * 100
        bt = m.groupby("NM_BAIRRO").agg(votos=("jorge", "sum"), val=("val7", "sum"), secoes=("secao", "count")).reset_index()
        bt["pct"] = bt.votos / bt.val * 100
        bt = bt.sort_values(["votos", "NM_BAIRRO"], ascending=[False, True])
        lt = m.groupby(["zona", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "NM_BAIRRO"]).agg(
            votos=("jorge", "sum"), val=("val7", "sum"), secoes=("secao", "count")).reset_index()
        lt["pct"] = lt.votos / lt.val * 100
        lt = lt.sort_values(["votos", "NM_LOCAL_VOTACAO"], ascending=[False, True])
        assert int(zt.votos.sum()) == int(bt.votos.sum()) == int(lt.votos.sum()) == int(r.votos)
        top_z = zt.sort_values("votos", ascending=False).head(3)
        prosa = (f"<p>Jorge teve <b>{n0(r.votos)} votos</b> em {tit(r.NM_MUNICIPIO)} ({p2(r.pct)} dos {n0(r.val)} válidos de estadual; "
                 f"{p2(r.votos / total * 100)} do total dele), "
                 + (f"<b>{int(r.pos)}º lugar</b> entre {n0(r.ncand)} candidatos a estadual com voto no município. " if not pd.isna(r.pos)
                    else "sem voto no município. ")
                 + f"Em 2022 foram {n0(r.v22)} votos ({sinal(r.votos - r.v22)}). O mais votado para estadual na cidade foi "
                 f"{tit(nm.get((7, lid_n), ('—',))[0])} ({n0(lid_v)} votos). Houve voto para Jorge em {n0(r.com_voto)} das {n0(r.secoes)} "
                 f"seções; {n0(r.aptos)} eleitores aptos e {n0(r.comp)} comparecimentos. "
                 + (("Zonas com mais votos: " + ", ".join(f"{int(z.zona)}ª ({n0(z.votos)})" for z in top_z.itertuples() if z.votos > 0) + ".")
                    if r.votos > 0 else "") + "</p>")
        ms = m.sort_values(["zona", "secao"])
        C.append(f'<h2 id="{r.anc}" class="pg">{i + 1}. {tit(r.NM_MUNICIPIO)} — {n0(r.votos)} votos</h2>' + prosa +
                 "<h3>Zonas eleitorais</h3>" + tabela(["Zona", "Votos", "% válidos", "Válidos", "Seções"],
                                                     [[f"{int(z.zona)}ª", n0(z.votos), p2(z.pct), n0(z.val), n0(z.secoes)] for z in zt.itertuples()],
                                                     num=(1, 2, 3, 4)) +
                 "<h3>Bairros</h3>" + tabela(["Bairro", "Votos", "% válidos", "Válidos", "Seções"],
                                             [[tit(b.NM_BAIRRO), n0(b.votos), p2(b.pct), n0(b.val), n0(b.secoes)] for b in bt.itertuples()],
                                             num=(1, 2, 3, 4), cls="mini") +
                 "<h3>Locais de votação</h3>" + tabela(["Local", "Bairro", "Zona", "Votos", "% válidos", "Seções"],
                                                      [[tit(x.NM_LOCAL_VOTACAO), tit(x.NM_BAIRRO), f"{int(x.zona)}ª", n0(x.votos), p2(x.pct), n0(x.secoes)]
                                                       for x in lt.itertuples()], num=(3, 4, 5), cls="mini") +
                 f"<h3>Todas as seções ({n0(len(ms))})</h3>" + tabela(
                     ["Zona", "Seção", "Local de votação", "Bairro", "Jorge", "Válidos", "%", "Posição na urna"],
                     [[f"{int(x['zona'])}ª", int(x["secao"]), tit(x["NM_LOCAL_VOTACAO"]), tit(x["NM_BAIRRO"]), n0(x["jorge"]), n0(x["val7"]),
                       p2(x["pj"]), f"{int(x['pos'])}º" if not pd.isna(x["pos"]) else ""] for x in ms.to_dict("records")],
                     num=(4, 5, 6, 7), cls="mini", destaque=lambda j, _p=ms["pos"].values: not pd.isna(_p[j]) and _p[j] <= 3))
        toc.append((r.anc, f"{i + 1}. {tit(r.NM_MUNICIPIO)} — {n0(r.votos)} votos"))

    kp = [(n0(total), "votos no estado"), (f"{int((mun.votos > 0).sum())} de 92", "municípios com voto"),
          (n0(int((d.jorge > 0).sum())), f"seções com voto (de {n0(len(d))})"), (n0(t22), "votos em 2022"),
          (tit(mun.iloc[1].NM_MUNICIPIO), f"2º município ({n0(mun.iloc[1].votos)})"), (p2(total / vtot * 100), "dos válidos do estado")]
    return documento("Jorge Felippe Neto no Estado do Rio de Janeiro: cidade a cidade", "Deputado estadual · PL · 22800 — os 92 municípios, "
                     "zona, bairro, local e todas as seções", kp, toc, "".join(C))


def pdf_douglas_estado(nm, v, base):
    """Douglas Ruas (governador, 22) × Eduardo Paes no estado, cidade a cidade: um capítulo por município com
    zona, bairro, local e todas as seções; na capital, também a divisão por Área de Planejamento."""
    nomes_g = sorted({n for (c, n) in nm if c == 3 and nm[(c, n)][2] != "legenda"}, key=lambda n: -nm[(3, n)][3])
    sg = por_secao(v, 3, nomes_g)
    comp3 = pd.read_sql("SELECT municipio,zona,secao,aptos,comparecimento FROM secao WHERE cargo=3",
                        sqlite3.connect(f"{A.T}/eleicao2026_rj_secao.sqlite")).set_index(KEYS)
    d = base.drop(columns=["aptos", "comparecimento"]).merge(sg, left_on=KEYS, right_index=True, how="left") \
        .merge(comp3, left_on=KEYS, right_index=True, how="left").fillna(0)
    for n in nomes_g:
        assert int(d[n].sum()) == nm[(3, n)][3], nm[(3, n)][0]
    d["pd"] = d[DOUGLAS] / d.validos.replace(0, np.nan) * 100
    d["pp"] = d[PAES] / d.validos.replace(0, np.nan) * 100
    d["dif"] = d[DOUGLAS] - d[PAES]
    cols = ["aptos", "comparecimento", "validos"] + nomes_g
    est = d[cols].sum()

    def agg(df, by):
        x = df.groupby(by)[cols].sum().reset_index()
        x["secoes"] = df.groupby(by).size().values
        x["pd"] = x[DOUGLAS] / x.validos * 100
        x["pp"] = x[PAES] / x.validos * 100
        x["dif"] = x[DOUGLAS] - x[PAES]
        x["abst"] = (1 - x.comparecimento / x.aptos) * 100
        x["dv"] = df.assign(t=df[DOUGLAS] > df[PAES]).groupby(by).t.sum().values
        x["pv"] = df.assign(t=df[PAES] > df[DOUGLAS]).groupby(by).t.sum().values
        return x

    def sinal(x):
        return ("+" if x > 0 else "") + n0(x)

    def venc(a, b):
        return "Douglas" if a > b else ("Paes" if b > a else "empate")

    mun = agg(d, ["NM_MUNICIPIO"]).sort_values([DOUGLAS, "NM_MUNICIPIO"], ascending=[False, True]).reset_index(drop=True)
    mun["anc"] = [f"m{i}" for i in range(len(mun))]
    assert len(mun) == 92 and int(mun[DOUGLAS].sum()) == nm[(3, DOUGLAS)][3]
    vence_d = int((mun[DOUGLAS] > mun[PAES]).sum())
    outros = [n for n in nomes_g if n not in (DOUGLAS, PAES)]
    cab = ["Aptos", "Abstenção", "Válidos", "Douglas", "Douglas %", "Paes", "Paes %", "Diferença", "Seções Douglas à frente",
           "Seções Paes à frente"]

    def lin(r):
        return [n0(r["aptos"]), p2(r["abst"]), n0(r["validos"]), n0(r[DOUGLAS]), p2(r["pd"]), n0(r[PAES]), p2(r["pp"]),
                sinal(r["dif"]), n0(r["dv"]), n0(r["pv"])]

    cap_t = d[d.municipio == A.RIO][cols].sum()
    sem_cap = est - cap_t
    toc = [("g1", "Visão do estado"), ("g2", "Fonte e leitura"), ("g3", "Os 92 municípios")]
    C = [f"""<h2 id="g1">Visão do estado</h2>
<p>Douglas Ruas (PL, 22) teve <b>{n0(est[DOUGLAS])} votos ({p2(est[DOUGLAS] / est.validos * 100)} dos válidos)</b> no 1º turno para
governador do Estado do Rio de Janeiro, contra {n0(est[PAES])} de Eduardo Paes (PSD, 55; {p2(est[PAES] / est.validos * 100)}), e os dois
disputam o 2º turno. Douglas teve mais votos que Paes em <b>{vence_d} dos 92 municípios</b>. Na capital, perdeu por
{n0(abs(cap_t[DOUGLAS] - cap_t[PAES]))} votos ({p2(cap_t[DOUGLAS] / cap_t.validos * 100)} contra {p2(cap_t[PAES] / cap_t.validos * 100)}); fora dela,
somou {n0(sem_cap[DOUGLAS])} votos contra {n0(sem_cap[PAES])} de Paes ({p2(sem_cap[DOUGLAS] / sem_cap.validos * 100)} contra
{p2(sem_cap[PAES] / sem_cap.validos * 100)}), {"vantagem" if sem_cap[DOUGLAS] > sem_cap[PAES] else "desvantagem"} de {n0(abs(sem_cap[DOUGLAS] - sem_cap[PAES]))} votos.
As maiores votações de Douglas fora da capital foram em {", ".join(f"{tit(r.NM_MUNICIPIO)} ({n0(r[DOUGLAS])})" for _, r in mun[mun.NM_MUNICIPIO != "RIO DE JANEIRO"].head(5).iterrows())};
os maiores percentuais, em {", ".join(f"{tit(r.NM_MUNICIPIO)} ({p2(r.pd)})" for _, r in mun.sort_values("pd", ascending=False).head(5).iterrows())}.</p>"""
         + "<h3>Todos os candidatos no estado (% dos válidos)</h3>" + tabela(
             ["Candidato", "Partido", "Votos", "% válidos"],
             [[tit(nm[(3, n)][0]), e(nm[(3, n)][1]), n0(est[n]), p2(est[n] / est.validos * 100)] for n in nomes_g], num=(2, 3)),
         """<h2 id="g2">Fonte e leitura</h2>
<p>Os números vêm dos boletins de urna de todas as seções do Estado do Rio de Janeiro, publicados pelo Tribunal Superior Eleitoral
(pleito 3220, 1º turno de 04/10/2026); a soma das seções é idêntica ao total oficial do TSE de cada candidato a governador. Percentuais
são sobre os votos válidos para governador (excluídos brancos e nulos); abstenção = 1 − comparecimento ÷ eleitores aptos. "Diferença"
é sempre votos de Douglas menos votos de Paes. Cada município tem um capítulo, na ordem da votação de Douglas, com zonas, bairros,
locais e todas as seções (as seções agregadas votam na urna da principal, onde seus votos já estão contados). Na capital, as zonas
também aparecem repartidas por Área de Planejamento, porque zona eleitoral não respeita limite de AP.</p>""",
         '<h2 id="g3">Os 92 municípios</h2>' + tabela(
             ["#", "Município", "Douglas", "Douglas %", "Paes", "Paes %", "Diferença", "Quem venceu", "Abstenção", "Seções"],
             [[str(i + 1), f'<a href="#{r["anc"]}">{tit(r["NM_MUNICIPIO"])}</a>', n0(r[DOUGLAS]), p2(r["pd"]), n0(r[PAES]), p2(r["pp"]),
               sinal(r["dif"]), venc(r[DOUGLAS], r[PAES]), p2(r["abst"]), n0(r["secoes"])] for i, r in mun.iterrows()],
             num=(0, 2, 3, 4, 5, 6, 8, 9))]

    for i, r in mun.iterrows():
        m = d[d.NM_MUNICIPIO == r.NM_MUNICIPIO]
        zt = agg(m, ["zona"]).sort_values("zona")
        bt = agg(m, ["NM_BAIRRO"]).sort_values([DOUGLAS, "NM_BAIRRO"], ascending=[False, True])
        lt = agg(m, ["zona", "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "NM_BAIRRO"]).sort_values([DOUGLAS, "NM_LOCAL_VOTACAO"], ascending=[False, True])
        assert int(zt[DOUGLAS].sum()) == int(bt[DOUGLAS].sum()) == int(lt[DOUGLAS].sum()) == int(r[DOUGLAS])
        prosa = (f"<p>Em {tit(r.NM_MUNICIPIO)}, Douglas Ruas teve <b>{n0(r[DOUGLAS])} votos ({p2(r.pd)} dos válidos)</b> e Eduardo Paes "
                 f"{n0(r[PAES])} ({p2(r.pp)}): " + (f"<b>vitória de Douglas</b> por {n0(r.dif)} votos" if r.dif > 0 else
                 (f"<b>vitória de Paes</b> por {n0(-r.dif)} votos" if r.dif < 0 else "<b>empate</b>")) +
                 f". Douglas teve mais votos em {n0(r.dv)} das {n0(r.secoes)} seções e Paes em {n0(r.pv)}; {n0(r.aptos)} eleitores aptos, "
                 f"abstenção de {p2(r.abst)}. Demais candidatos: " + ", ".join(f"{tit(nm[(3, n)][0])} {n0(r[n])} ({p2(r[n] / r.validos * 100)})"
                                                                              for n in outros) + ".</p>")
        extra = ""
        if r.NM_MUNICIPIO == "RIO DE JANEIRO":
            ap = agg(m, ["regiao"])
            ap = ap.assign(o=ap.regiao.map(ORD_AP.index)).sort_values("o")
            za = agg(m, ["zona", "regiao"])
            za = za.assign(o=za.regiao.map(ORD_AP.index)).sort_values(["o", DOUGLAS], ascending=[True, False])
            extra = ("<h3>Áreas de Planejamento</h3>" + tabela(["Área de Planejamento"] + cab, [[e(x["regiao"])] + lin(x) for _, x in ap.iterrows()],
                                                              num=range(1, 11), cls="mini") +
                     "<h3>Zonas eleitorais dentro de cada Área de Planejamento</h3>" + tabela(
                         ["AP", "Zona"] + cab, [[e(x["regiao"].split(" · ")[0]), f"{int(x['zona'])}ª"] + lin(x) for _, x in za.iterrows()],
                         num=range(2, 12), cls="mini"))
        ms = m.sort_values(["zona", "secao"])
        C.append(f'<h2 id="{r.anc}" class="pg">{i + 1}. {tit(r.NM_MUNICIPIO)} — Douglas {n0(r[DOUGLAS])} × Paes {n0(r[PAES])}</h2>' + prosa + extra +
                 "<h3>Zonas eleitorais</h3>" + tabela(["Zona"] + cab, [[f"{int(x['zona'])}ª"] + lin(x) for _, x in zt.iterrows()],
                                                     num=range(1, 11), cls="mini") +
                 "<h3>Bairros</h3>" + tabela(["Bairro", "Válidos", "Douglas", "Douglas %", "Paes", "Paes %", "Diferença"],
                                             [[tit(x["NM_BAIRRO"]), n0(x["validos"]), n0(x[DOUGLAS]), p2(x["pd"]), n0(x[PAES]), p2(x["pp"]), sinal(x["dif"])]
                                              for _, x in bt.iterrows()], num=range(1, 7), cls="mini") +
                 "<h3>Locais de votação</h3>" + tabela(["Local", "Bairro", "Zona", "Douglas", "Douglas %", "Paes", "Paes %", "Diferença"],
                                                      [[tit(x["NM_LOCAL_VOTACAO"]), tit(x["NM_BAIRRO"]), f"{int(x['zona'])}ª", n0(x[DOUGLAS]), p2(x["pd"]),
                                                        n0(x[PAES]), p2(x["pp"]), sinal(x["dif"])] for _, x in lt.iterrows()], num=range(3, 8), cls="mini") +
                 f"<h3>Todas as seções ({n0(len(ms))})</h3>" + tabela(
                     ["Zona", "Seção", "Local de votação", "Bairro", "Válidos", "Douglas", "Douglas %", "Paes", "Paes %", "Diferença"],
                     [[f"{int(x['zona'])}ª", int(x["secao"]), tit(x["NM_LOCAL_VOTACAO"]), tit(x["NM_BAIRRO"]), n0(x["validos"]), n0(x[DOUGLAS]),
                       p2(x["pd"]), n0(x[PAES]), p2(x["pp"]), sinal(x["dif"])] for x in ms.to_dict("records")],
                     num=range(4, 10), cls="mini", destaque=lambda j, _d=ms.dif.values: _d[j] > 0))
        toc.append((r.anc, f"{i + 1}. {tit(r.NM_MUNICIPIO)} — Douglas {n0(r[DOUGLAS])} × Paes {n0(r[PAES])}"))

    kp = [(n0(est[DOUGLAS]), f"Douglas · {p2(est[DOUGLAS] / est.validos * 100)}"), (n0(est[PAES]), f"Paes · {p2(est[PAES] / est.validos * 100)}"),
          (f"{vence_d} de 92", "municípios vencidos por Douglas"), (sinal(sem_cap[DOUGLAS] - sem_cap[PAES]), "diferença fora da capital"),
          (sinal(cap_t[DOUGLAS] - cap_t[PAES]), "diferença na capital"), (n0(len(d)), "seções")]
    return documento("Douglas Ruas no Estado do Rio de Janeiro: cidade a cidade", "Governador · PL · 22 × Eduardo Paes (PSD, 55) — os 92 "
                     "municípios, zona, bairro, local e todas as seções", kp, toc, "".join(C))


def pdf_trio_zo(nm, v, base, fed=1177, outro=11123):
    """Dr. Luizinho (federal) × Jorge × Felipe Pampolha (estaduais) na Zona Oeste (AP4 + AP5): correlação
    controlada (matriz), redutos cruzados, mesmas urnas, AP, zona, bairro e seção a seção."""
    J = A.JFN
    s7 = por_secao(v, 7, [J, outro]).rename(columns={"validos": "val7"})
    s6 = por_secao(v, 6, [fed]).rename(columns={"validos": "val6"})
    d = base.merge(s7, left_on=KEYS, right_index=True, how="left").merge(s6, left_on=KEYS, right_index=True, how="left").fillna(0)
    for cargo, n in ((7, J), (7, outro), (6, fed)):
        assert int(d[n].sum()) == nm[(cargo, n)][3], nm[(cargo, n)][0]
    z = d[d.regiao.isin(A.ZONA_OESTE)].copy()
    z["j"] = z[J] / z.val7.replace(0, np.nan) * 100
    z["o"] = z[outro] / z.val7.replace(0, np.nan) * 100
    z["f"] = z[fed] / z.val6.replace(0, np.nan) * 100
    zb = z[z.val7 >= 50]
    NJ, NO, NF = "Jorge Felippe Neto", tit(nm[(7, outro)][0]), tit(nm[(6, fed)][0])
    CJ, CO, CF = "Jorge", NO.split()[-1], CURTO.get(fed, NF)
    tj, to_, tf = int(z[J].sum()), int(z[outro].sum()), int(z[fed].sum())
    sj, so, sf = tj / z.val7.sum() * 100, to_ / z.val7.sum() * 100, tf / z.val6.sum() * 100

    def bruta(a, b, df=zb):
        return float(np.corrcoef(df[a], df[b])[0, 1])

    pares = [("f", "j", f"{CF} × {CJ}"), ("f", "o", f"{CF} × {CO}"), ("j", "o", f"{CJ} × {CO}")]
    mat = []
    for a, b, rot in pares:
        mat.append([rot, bruta(a, b), A.corr_controlada(zb[a], zb[b], zb.regiao), A.corr_controlada(zb[a], zb[b], zb.zona),
                    A.corr_controlada(zb[a], zb[b], zb.NM_BAIRRO)] +
                   [bruta(a, b, zb[zb.regiao == ap]) for ap in A.ZONA_OESTE])
    cc = {r[0]: r[2] for r in mat}

    # redutos cruzados: decil superior de cada um DENTRO da AP; fatia dos outros dois ali × na AP
    def reduto(col):
        q = zb[col] >= zb.groupby("regiao")[col].transform(lambda x: x.quantile(0.9))
        return zb[q]
    red = {}
    for col, nome in (("f", CF), ("j", CJ), ("o", CO)):
        r = reduto(col)
        red[nome] = dict(n=len(r), j=r[J].sum() / r.val7.sum() * 100, o=r[outro].sum() / r.val7.sum() * 100, f=r[fed].sum() / r.val6.sum() * 100)
    lift = {(alvo, base_): A.lift_controlado(zb[base_], zb[alvo_col], zb[val], zb.regiao)
            for alvo, alvo_col, val, base_ in ((CF, fed, "val6", "j"), (CF, fed, "val6", "o"), (CJ, J, "val7", "f"),
                                                (CO, outro, "val7", "f"), (CJ, J, "val7", "o"), (CO, outro, "val7", "j"))}
    mesmas = {k: int(z[z[col] > 0][fed].sum()) for k, col in ((CJ, J), (CO, outro))}
    ambos3 = int(((z[J] > 0) & (z[outro] > 0) & (z[fed] > 0)).sum())

    C, toc = [], []

    def sec(a, t, c, quebra=False):
        toc.append((a, t))
        C.append(f'<h2 id="{a}" class="{"pg" if quebra else ""}">{e(t)}</h2>{c}')

    mais = CO if (cc[f"{CF} × {CO}"] or 0) > (cc[f"{CF} × {CJ}"] or 0) else CJ
    sec("t1", "1. Sumário executivo", f"""
<p>Na Zona Oeste da capital (AP4 Barra e Jacarepaguá + AP5), {NJ} (PL, 22800, estadual) teve <b>{n0(tj)} votos</b> ({p2(sj)} dos válidos
de estadual), {NO} ({e(nm[(7, outro)][1])}, {outro}, estadual) teve <b>{n0(to_)}</b> ({p2(so)}) e {NF} ({e(nm[(6, fed)][1])}, {fed}, federal)
teve <b>{n0(tf)}</b> ({p2(sf)} dos válidos de federal), em {n0(len(z))} seções.</p>
<p>Medida dentro da mesma Área de Planejamento, a correlação por seção de {NF} é de <b>{d2(cc[f"{CF} × {CJ}"])} com Jorge</b> e
<b>{d2(cc[f"{CF} × {CO}"])} com {NO}</b>: o voto de {NF} acompanha os dois, e mais de perto o de {mais}. Entre Jorge e {NO}, que disputam o
mesmo cargo, a correlação controlada é de {d2(cc[f"{CJ} × {CO}"])}. Nas seções em que {NF} é mais forte, Jorge teve {p2(red[CF]["j"])} dos
válidos de estadual (média da região: {p2(sj)}) e {NO} {p2(red[CF]["o"])} (média: {p2(so)}).</p>
<p>Do total de {n0(tf)} votos de {NF} na Zona Oeste, {n0(mesmas[CJ])} estão em urnas em que Jorge também teve voto e {n0(mesmas[CO])} em urnas
com voto de {NO}; os três foram votados juntos em {n0(ambos3)} urnas.</p>""")

    sec("t2", "2. Fonte, método e leitura", METODO_CORR + """
<p>Os números vêm dos boletins de urna de cada seção, publicados pelo Tribunal Superior Eleitoral (pleito 3220, 1º turno de 04/10/2026),
conferidos contra o total oficial do TSE dos três candidatos.</p>
<div class="callout"><b>Dois cuidados de leitura.</b> (1) A medida é territorial, por seção; o voto é secreto, e correlação alta é compatível
com dobrada, mas não a prova. (2) Jorge e """ + e(NO) + """ disputam o <b>mesmo cargo</b>: cada eleitor dá um único voto para deputado estadual.
Onde um ganha fatia, sobra menos para o outro, o que puxa a correlação entre os dois para baixo por construção. Uma correlação baixa ou
negativa entre eles não indica rivalidade; a comparação mais informativa é a de cada um com o federal.</div>""")

    cab_m = ["Par", "Bruta", "Controlada (AP)", "Dentro da zona", "Dentro do bairro"] + [f"Só {ap.split(' · ')[0]}" for ap in A.ZONA_OESTE]
    sec("t3", "3. Matriz de correlação", tabela(cab_m, [[r[0]] + [f"<b>{d2(x)}</b>" if k == 1 else d2(x) for k, x in enumerate(r[1:])] for r in mat],
                                                  num=range(1, 7)) +
        f"<p class='nota'>{n0(len(zb))} seções da Zona Oeste com 50 ou mais válidos de estadual.</p>")

    sec("t4", "4. Redutos cruzados", "<p>Para cada candidato, as seções do decil superior dele dentro de cada AP; a tabela mostra a fatia dos "
        "outros dois ali. O índice de reduto controlado compara com o que cada um teria repetindo a própria média da AP (1,00 = neutro).</p>" + tabela(
            ["Reduto de", "Seções", f"{CJ} % (est.)", f"{CO} % (est.)", f"{CF} % (fed.)"],
            [[k, n0(x["n"]), p2(x["j"]), p2(x["o"]), p2(x["f"])] for k, x in red.items()] +
            [["<i>Média da Zona Oeste</i>", n0(len(zb)), p2(sj), p2(so), p2(sf)]], num=range(1, 5)) + tabela(
            ["Candidato", "No reduto de", "Índice de reduto controlado"],
            [[a, b_n, d2(x)] for (a, b), x in lift.items() for b_n in [{"j": CJ, "o": CO, "f": CF}[b]]], num=(2,)))

    sec("t5", "5. Mesmas urnas", tabela(
        ["", "Votos"], [[f"Votos de {NF} na Zona Oeste", n0(tf)], ["…em urnas com voto de Jorge", n0(mesmas[CJ])],
                        [f"…em urnas com voto de {NO}", n0(mesmas[CO])], ["Urnas com voto dos três", n0(ambos3)],
                        ["Urnas da Zona Oeste", n0(len(z))]], num=(1,)))

    def agg(df, by):
        g = df.groupby(by).agg(j=(J, "sum"), o=(outro, "sum"), f=(fed, "sum"), v7=("val7", "sum"), v6=("val6", "sum"),
                               secoes=("secao", "count")).reset_index()
        g["pj"], g["po"], g["pf"] = g.j / g.v7 * 100, g.o / g.v7 * 100, g.f / g.v6 * 100
        return g

    cab = [CJ, f"{CJ} %", CO, f"{CO} %", CF, f"{CF} %", "Seções"]

    def lin(r):
        return [n0(r.j), p2(r.pj), n0(r.o), p2(r.po), n0(r.f), p2(r.pf), n0(r.secoes)]

    ap = agg(z, ["regiao"])
    sec("t6", "6. Por Área de Planejamento", tabela(["AP"] + cab, [[e(r.regiao)] + lin(r) for r in ap.itertuples()], num=range(1, 8)))
    zt = agg(z, ["zona", "regiao"]).sort_values(["regiao", "j"], ascending=[True, False])
    bt = agg(z, ["regiao", "NM_BAIRRO"]).sort_values(["regiao", "j"], ascending=[True, False])
    assert int(zt.j.sum()) == int(bt.j.sum()) == tj and int(zt.f.sum()) == tf and int(bt.o.sum()) == to_
    sec("t7", "7. Zona a zona", "<p>Cada zona repartida pelas APs da Zona Oeste em que tem seções.</p>" + tabela(
        ["Zona", "AP"] + cab, [[f"{int(r.zona)}ª", e(r.regiao.split(" · ")[0])] + lin(r) for r in zt.itertuples()], num=range(2, 9)), quebra=True)
    sec("t8", "8. Bairro a bairro", tabela(["Bairro", "AP"] + cab, [[tit(r.NM_BAIRRO), e(r.regiao.split(" · ")[0])] + lin(r) for r in bt.itertuples()],
                                           num=range(2, 9)), quebra=True)
    zs = z.sort_values(["zona", "secao"])
    sec("t9", "9. Seção a seção", f"<p>As {n0(len(zs))} seções da Zona Oeste. Em destaque, as seções em que os três tiveram voto.</p>" + tabela(
        ["Zona", "Seção", "Local de votação", "Bairro", "AP", CJ, "%", CO, "%", CF, "%"],
        [[f"{int(r['zona'])}ª", int(r["secao"]), tit(r["NM_LOCAL_VOTACAO"]), tit(r["NM_BAIRRO"]), e(r["regiao"].split(" · ")[0]),
          n0(r[J]), p2(r["j"]), n0(r[outro]), p2(r["o"]), n0(r[fed]), p2(r["f"])] for r in zs.to_dict("records")],
        num=range(5, 11), cls="mini",
        destaque=lambda k, _a=zs[J].values, _b=zs[outro].values, _c=zs[fed].values: _a[k] > 0 and _b[k] > 0 and _c[k] > 0), quebra=True)

    kp = [(n0(tj), "Jorge na Zona Oeste"), (n0(to_), f"{NO} na Zona Oeste"), (n0(tf), f"{NF} na Zona Oeste"),
          (d2(cc[f"{CF} × {CJ}"]), f"correlação controlada {CF} × Jorge"), (d2(cc[f"{CF} × {CO}"]), f"correlação controlada {CF} × {CO}"),
          (d2(cc[f"{CJ} × {CO}"]), f"correlação controlada Jorge × {CO}")]
    return documento(f"{NF}, Jorge Felippe Neto e {NO} na Zona Oeste", "Federal (PP, 1177) × estaduais (PL, 22800 · PP, 11123) — correlação, "
                     "redutos, zona, bairro e seção a seção na AP4 e na AP5", kp, toc, "".join(C))


def pdf_trio_tabelas(nm, v, base, fed=1177, outro=11123):
    """Tabelas dos votos de Dr. Luizinho, Felipe Pampolha e Jorge no estado inteiro: municípios, capital por
    AP/zona/bairro e seção a seção (toda urna em que ao menos um dos três teve voto)."""
    J = A.JFN
    s7 = por_secao(v, 7, [J, outro]).rename(columns={"validos": "val7"})
    s6 = por_secao(v, 6, [fed]).rename(columns={"validos": "val6"})
    d = base.merge(s7, left_on=KEYS, right_index=True, how="left").merge(s6, left_on=KEYS, right_index=True, how="left").fillna(0)
    tot = {}
    for cargo, n in ((7, J), (7, outro), (6, fed)):
        tot[n] = int(d[n].sum())
        assert tot[n] == nm[(cargo, n)][3], nm[(cargo, n)][0]
    NO, NF = tit(nm[(7, outro)][0]), tit(nm[(6, fed)][0])
    CO, CF = NO.split()[-1], CURTO.get(fed, NF)

    def agg(df, by):
        g = df.groupby(by).agg(j=(J, "sum"), o=(outro, "sum"), f=(fed, "sum"), v7=("val7", "sum"), v6=("val6", "sum"),
                               secoes=("secao", "count")).reset_index()
        g["pj"], g["po"], g["pf"] = g.j / g.v7 * 100, g.o / g.v7 * 100, g.f / g.v6 * 100
        return g

    cab = ["Jorge", "Jorge %", CO, f"{CO} %", CF, f"{CF} %", "Seções"]

    def lin(r):
        return [n0(r["j"]), p2(r["pj"]), n0(r["o"]), p2(r["po"]), n0(r["f"]), p2(r["pf"]), n0(r["secoes"])]

    C, toc = [], []

    def sec(a, t, c, quebra=False):
        toc.append((a, t))
        C.append(f'<h2 id="{a}" class="{"pg" if quebra else ""}">{e(t)}</h2>{c}')

    rio = d[d.municipio == A.RIO]
    reg = agg(d.assign(r2=np.where(d.municipio == A.RIO, d.regiao, "Fora da capital")), ["r2"]).rename(columns={"r2": "regiao"})
    reg = reg.assign(o_=reg.regiao.map(lambda x: (ORD_AP + ["Fora da capital"]).index(x))).sort_values("o_")
    sec("x1", "1. Totais", tabela(
        ["Candidato", "Cargo", "Partido", "Número", "Situação", "Votos no estado", "Na capital", "Na Zona Oeste"],
        [[nome, cargo_t, e(nm[(c, n)][1]), str(n), e(nm[(c, n)][2]), n0(tot[n]), n0(int(rio[n].sum())),
          n0(int(rio[rio.regiao.isin(A.ZONA_OESTE)][n].sum()))]
         for nome, cargo_t, c, n in (("Jorge Felippe Neto", "Dep. estadual", 7, J), (NO, "Dep. estadual", 7, outro), (NF, "Dep. federal", 6, fed))],
        num=(3, 5, 6, 7)) + "<p>Percentuais sobre os válidos do próprio cargo (estadual para Jorge e " + e(NO) + ", federal para " + e(NF) +
        "). Fonte: boletins de urna do TSE, pleito 3220, 1º turno de 04/10/2026; totais idênticos ao oficial do TSE.</p>" +
        "<h3>Por região</h3>" + tabela(["Região"] + cab, [[e(r["regiao"])] + lin(r) for _, r in reg.iterrows()], num=range(1, 8)))
    mun = agg(d, ["NM_MUNICIPIO"]).sort_values(["j", "NM_MUNICIPIO"], ascending=[False, True])
    sec("x2", "2. Os 92 municípios", tabela(["Município"] + cab, [[tit(r["NM_MUNICIPIO"])] + lin(r) for _, r in mun.iterrows()],
                                            num=range(1, 8)), quebra=True)
    zt = agg(rio, ["zona"]).sort_values("zona")
    za = agg(rio, ["regiao", "zona"])
    za = za.assign(o_=za.regiao.map(ORD_AP.index)).sort_values(["o_", "j"], ascending=[True, False])
    sec("x3", "3. Capital: zonas eleitorais", "<h3>Total de cada zona</h3>" + tabela(["Zona"] + cab, [[f"{int(r['zona'])}ª"] + lin(r) for _, r in zt.iterrows()],
                                                                                   num=range(1, 8)) +
        "<h3>Zonas dentro de cada Área de Planejamento</h3>" + tabela(["AP", "Zona"] + cab,
                                                                     [[e(r["regiao"].split(" · ")[0]), f"{int(r['zona'])}ª"] + lin(r) for _, r in za.iterrows()],
                                                                     num=range(2, 9)), quebra=True)
    bt = agg(rio, ["regiao", "NM_BAIRRO"])
    bt = bt.assign(o_=bt.regiao.map(ORD_AP.index)).sort_values(["o_", "j"], ascending=[True, False])
    sec("x4", "4. Capital: bairros", tabela(["Bairro", "AP"] + cab, [[tit(r["NM_BAIRRO"]), e(r["regiao"].split(" · ")[0])] + lin(r)
                                                                      for _, r in bt.iterrows()], num=range(2, 9)), quebra=True)
    assert int(mun.j.sum()) == tot[J] and int(zt.f.sum()) == int(bt.f.sum()) == int(rio[fed].sum()) and int(bt.o.sum()) == int(rio[outro].sum())
    alg = d[(d[J] > 0) | (d[outro] > 0) | (d[fed] > 0)].sort_values(["NM_MUNICIPIO", "zona", "secao"])
    assert int(alg[J].sum()) == tot[J] and int(alg[outro].sum()) == tot[outro] and int(alg[fed].sum()) == tot[fed]
    sec("x5", "5. Seção a seção", f"<p>As {n0(len(alg))} seções do estado em que pelo menos um dos três teve voto (de {n0(len(d))}), por "
        "município, zona e seção, vêm em seguida, em ordem de município, zona e seção. A soma de cada coluna é o total do candidato "
        "no estado.</p>")
    # o anexo sai em blocos impressos separadamente: uma página única de ~30 mil linhas ficou 55 min no
    # printToPDF, falhou e sobrecarregou a VM (05/10/2026, junto da queda do jfn.service)
    cab_a = ["Município", "Zona", "Seção", "Local de votação", "Bairro", "Jorge", CO, CF]
    linhas_a = [[tit(r["NM_MUNICIPIO"]), f"{int(r['zona'])}ª", int(r["secao"]), tit(r["NM_LOCAL_VOTACAO"]), tit(r["NM_BAIRRO"]),
                 n0(r[J]), n0(r[outro]), n0(r[fed])] for r in alg.to_dict("records")]
    anexos = [f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><style>{CSS}</style></head><body><div class='wrap'>"
              f"<h3>Seção a seção — linhas {n0(i + 1)} a {n0(min(i + BLOCO, len(linhas_a)))} de {n0(len(linhas_a))}</h3>"
              + tabela(cab_a, linhas_a[i:i + BLOCO], num=(5, 6, 7), cls="mini") + "</div></body></html>"
              for i in range(0, len(linhas_a), BLOCO)]

    kp = [(n0(tot[J]), "Jorge (estadual)"), (n0(tot[outro]), f"{NO} (estadual)"), (n0(tot[fed]), f"{NF} (federal)"),
          (n0(len(alg)), "seções com voto de algum dos três"), (n0(int((mun.j > 0).sum())), "municípios com voto de Jorge"),
          (n0(len(d)), "seções no estado")]
    return documento(f"Votos de {NF}, {NO} e Jorge Felippe Neto", "Tabelas · estado do Rio de Janeiro — municípios, capital por AP, "
                     "zona e bairro, e seção a seção", kp, toc, "".join(C)), anexos


def parte_html(corpo):
    """Documento-anexo sem capa, para impressão em partes (gerar_partes)."""
    return f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><style>{CSS}</style></head><body><div class='wrap'>{corpo}</div></body></html>"


def escolas(df, cols_soma, extra=None):
    """Consolida por escola (nome + endereço): zonas, seções e somas. extra: {nome: (coluna, função)}."""
    # colunas de voto têm o número do candidato (int) como nome; a agregação nomeada exige texto
    nomes = {c: f"c_{c}" for c in cols_soma}
    g = df.rename(columns=nomes).groupby("k_escola").agg(
        NM_LOCAL_VOTACAO=("NM_LOCAL_VOTACAO", "first"), DS_ENDERECO=("DS_ENDERECO", "first"),
        NM_BAIRRO=("NM_BAIRRO", "first"), NM_BAIRRO_TSE=("NM_BAIRRO_TSE", "first"), NM_MUNICIPIO=("NM_MUNICIPIO", "first"),
        regiao=("regiao", "first"),
        secoes=("secao", "count"), zonas=("zona", lambda z: ", ".join(f"{int(x)}ª" for x in sorted(set(z)))),
        **{n: (n, "sum") for n in nomes.values()}, **(extra or {}))
    return g.reset_index().rename(columns={n: c for c, n in nomes.items()})


def pdf_trio_zo_tabelas(nm, v, base, fed=1177, outro=11123):
    """Tabelas dos votos de Luizinho, Pampolha e Jorge na Zona Oeste: AP, zona por AP, bairro, escola e seção."""
    J = A.JFN
    s7 = por_secao(v, 7, [J, outro]).rename(columns={"validos": "val7"})
    s6 = por_secao(v, 6, [fed]).rename(columns={"validos": "val6"})
    d = base.merge(s7, left_on=KEYS, right_index=True, how="left").merge(s6, left_on=KEYS, right_index=True, how="left").fillna(0)
    for cargo, n in ((7, J), (7, outro), (6, fed)):
        assert int(d[n].sum()) == nm[(cargo, n)][3], nm[(cargo, n)][0]
    z = d[d.regiao.isin(A.ZONA_OESTE)].copy()
    NO, NF = tit(nm[(7, outro)][0]), tit(nm[(6, fed)][0])
    CO, CF = NO.split()[-1], CURTO.get(fed, NF)
    tj, to_, tf = int(z[J].sum()), int(z[outro].sum()), int(z[fed].sum())

    def pct(g):
        g["pj"], g["po"], g["pf"] = g[J] / g.val7 * 100, g[outro] / g.val7 * 100, g[fed] / g.val6 * 100
        return g

    def agg(df, by):
        g = df.groupby(by)[[J, outro, fed, "val7", "val6"]].sum().reset_index()
        g["secoes"] = df.groupby(by).size().values
        return pct(g)

    cab = ["Jorge", "Jorge %", CO, f"{CO} %", CF, f"{CF} %", "Seções"]

    def lin(r):
        return [n0(r[J]), p2(r["pj"]), n0(r[outro]), p2(r["po"]), n0(r[fed]), p2(r["pf"]), n0(r["secoes"])]

    C, toc = [], []

    def sec(a, t, c, quebra=False):
        toc.append((a, t))
        C.append(f'<h2 id="{a}" class="{"pg" if quebra else ""}">{e(t)}</h2>{c}')

    ap = agg(z, ["regiao"])
    sec("w1", "1. Totais e Áreas de Planejamento", f"""<p>Zona Oeste da capital = AP4 (Barra e Jacarepaguá) + AP5. Votos de Jorge Felippe Neto
(PL, 22800, estadual), {NO} ({e(nm[(7, outro)][1])}, {outro}, estadual) e {NF} ({e(nm[(6, fed)][1])}, {fed}, federal), com percentuais sobre os
válidos do próprio cargo. Fonte: boletins de urna do TSE, pleito 3220, 1º turno de 04/10/2026; totais conferidos contra o oficial do TSE.
Cada escola é identificada por nome e endereço. """ + FONTE_BAIRRO + """</p>""" + tabela(
        ["Área de Planejamento"] + cab, [[e(r["regiao"])] + lin(r) for _, r in ap.iterrows()] +
        [["<b>Zona Oeste</b>", f"<b>{n0(tj)}</b>", p2(tj / z.val7.sum() * 100), f"<b>{n0(to_)}</b>", p2(to_ / z.val7.sum() * 100),
          f"<b>{n0(tf)}</b>", p2(tf / z.val6.sum() * 100), n0(len(z))]], num=range(1, 8)))
    za = agg(z, ["regiao", "zona"]).sort_values(["regiao", J], ascending=[True, False])
    sec("w2", "2. Zonas eleitorais por AP", tabela(["AP", "Zona"] + cab, [[e(r["regiao"].split(" · ")[0]), f"{int(r['zona'])}ª"] + lin(r)
                                                                          for _, r in za.iterrows()], num=range(2, 9)))
    bt = agg(z, ["regiao", "NM_BAIRRO"]).sort_values(["regiao", J], ascending=[True, False])
    sec("w3", "3. Bairros", tabela(["Bairro", "AP"] + cab, [[tit(r["NM_BAIRRO"]), e(r["regiao"].split(" · ")[0])] + lin(r)
                                                          for _, r in bt.iterrows()], num=range(2, 9)), quebra=True)
    es = pct(escolas(z, [J, outro, fed, "val7", "val6"])).sort_values(["regiao", "NM_BAIRRO", J], ascending=[True, True, False])
    assert int(es[J].sum()) == int(bt[J].sum()) == tj and int(es[fed].sum()) == tf and int(es[outro].sum()) == to_
    corpo_es = ""
    for (rg, b), x in es.groupby(["regiao", "NM_BAIRRO"], sort=False):
        corpo_es += f"<h3>{tit(b)} · {e(rg.split(' · ')[0])} — Jorge {n0(x[J].sum())}, {CO} {n0(x[outro].sum())}, {CF} {n0(x[fed].sum())}</h3>" + tabela(
            ["Escola", "Endereço", "Zona"] + cab, [[tit(r["NM_LOCAL_VOTACAO"]), tit(r["DS_ENDERECO"]), r["zonas"]] + lin(r) for _, r in x.iterrows()],
            num=range(3, 10), cls="mini")
    sec("w4", "4. Escola a escola, por bairro", f"<p>As {n0(len(es))} escolas (locais de votação) da Zona Oeste vêm a seguir, agrupadas "
        "pelo bairro em que estão sediadas, com os votos dos três em cada uma.</p>")
    zs = z.sort_values(["zona", "secao"])
    linhas = [[f"{int(r['zona'])}ª", int(r["secao"]), tit(r["NM_LOCAL_VOTACAO"]), tit(r["NM_BAIRRO"]), e(r["regiao"].split(" · ")[0]),
               n0(r[J]), n0(r[outro]), n0(r[fed])] for r in zs.to_dict("records")]
    sec("w5", "5. Seção a seção", f"<p>As {n0(len(zs))} seções da Zona Oeste vêm após a parte de escolas, em ordem de zona e seção.</p>")
    cab_s = ["Zona", "Seção", "Escola", "Bairro", "AP", "Jorge", CO, CF]
    anexos = [parte_html('<h2 class="pg">4. Escola a escola, por bairro</h2>' + corpo_es)] + [
        parte_html(f"<h3>Seção a seção — linhas {n0(i + 1)} a {n0(min(i + BLOCO, len(linhas)))} de {n0(len(linhas))}</h3>" +
                   tabela(cab_s, linhas[i:i + BLOCO], num=(5, 6, 7), cls="mini")) for i in range(0, len(linhas), BLOCO)]
    kp = [(n0(tj), "Jorge na Zona Oeste"), (n0(to_), f"{NO}"), (n0(tf), f"{NF}"), (n0(len(es)), "escolas"),
          (n0(len(bt)), "bairros"), (n0(len(z)), "seções")]
    return documento(f"Votos de {NF}, {NO} e Jorge Felippe Neto na Zona Oeste", "Tabelas · AP4 e AP5 — zona, bairro, escola e seção",
                     kp, toc, "".join(C)), anexos


def pdf_escolas_jorge(nm, v, base):
    """Jorge escola a escola no estado: município → bairro (consolidado) → escola (nome + endereço), todas as escolas."""
    J = A.JFN
    x7 = v[v.cargo == 7]
    val = x7[x7.valido].groupby(KEYS).qtd.sum().rename("val7")
    nomi = x7[x7.tipo == "nominal"][KEYS + ["numero", "qtd"]].merge(base[KEYS + ["k_escola", "NM_BAIRRO", "NM_MUNICIPIO"]], on=KEYS)
    jv = nomi[nomi.numero == J].set_index(KEYS).qtd.rename("jorge")
    d = base.merge(val, left_on=KEYS, right_index=True, how="left").merge(jv, left_on=KEYS, right_index=True, how="left") \
        .fillna({"val7": 0, "jorge": 0})
    total = int(d.jorge.sum())
    assert total == nm[(7, J)][3]

    def posicao(chave):
        r = nomi.groupby(chave + ["numero"]).qtd.sum().reset_index()
        r = r[r.qtd > 0]
        r["p"] = r.groupby(chave).qtd.rank(ascending=False, method="min")
        n = r.groupby(chave).size().rename("ncand")
        return r[r.numero == J].set_index(chave).p.rename("pos").to_frame().join(n, how="outer")

    es = escolas(d, ["jorge", "val7"]).merge(posicao(["k_escola"]), left_on="k_escola", right_index=True, how="left")
    es["pct"] = es.jorge / es.val7.replace(0, np.nan) * 100
    bt = d.groupby(["NM_MUNICIPIO", "NM_BAIRRO", "regiao"]).agg(jorge=("jorge", "sum"), val7=("val7", "sum"), secoes=("secao", "count"),
                                                               escolas=("k_escola", "nunique")).reset_index()
    bt = bt.merge(posicao(["NM_MUNICIPIO", "NM_BAIRRO"]), left_on=["NM_MUNICIPIO", "NM_BAIRRO"], right_index=True, how="left")
    bt["pct"] = bt.jorge / bt.val7 * 100
    mun = d.groupby("NM_MUNICIPIO").agg(jorge=("jorge", "sum"), val7=("val7", "sum"), escolas=("k_escola", "nunique"),
                                         bairros=("NM_BAIRRO", "nunique"), secoes=("secao", "count")).reset_index()
    mun["pct"] = mun.jorge / mun.val7 * 100
    mun = mun.sort_values(["jorge", "NM_MUNICIPIO"], ascending=[False, True]).reset_index(drop=True)
    assert int(es.jorge.sum()) == int(bt.jorge.sum()) == int(mun.jorge.sum()) == total and len(mun) == 92

    def posf(r):
        return f"{int(r['pos'])}º de {n0(r['ncand'])}" if not pd.isna(r.get("pos")) else "—"

    toc = [("k1", "Leitura e consolidação"), ("k2", "Os 92 municípios")]
    C = ["""<h2 id="k1">Leitura e consolidação</h2>
<p>Este relatório lista <b>todas as escolas</b> (locais de votação) do Estado do Rio de Janeiro, com os votos de Jorge Felippe Neto
(PL, 22800) para deputado estadual em cada uma, organizadas por município e pelo bairro em que a escola está sediada, segundo o cadastro de
locais de votação do TSE de 2026. Fonte dos votos: boletins de urna do TSE (pleito 3220, 1º turno de 04/10/2026), cuja soma coincide com o
total oficial, conferido também município a município e zona a zona contra o arquivo oficial de votação por município e zona do TSE.</p>
<p><b>Bairro.</b> """ + FONTE_BAIRRO + """ Quando o nome usado pelo TSE é diferente do bairro oficial, ele aparece entre parênteses ao lado da escola.</p>
<p><b>Consolidação.</b> (1) Bairro, fora da capital: o cadastro grafa o mesmo bairro de formas diferentes (com e sem acento, em maiúsculas
ou minúsculas, como "Mutuá"/"Mutua"); os nomes foram unificados pela grafia sem acento, mantendo a forma acentuada. (2) Escola: a mesma
escola às vezes aparece com dois números de local na mesma zona; ela é identificada por nome e endereço e aparece uma única vez, com a
soma de todas as suas seções. (3) "Posição" é o lugar de Jorge entre os candidatos a estadual com voto na escola ou no bairro. Escolas sem
voto para Jorge também estão listadas.</p>""",
         '<h2 id="k2">Os 92 municípios</h2>' + tabela(
             ["#", "Município", "Votos", "% válidos", "Bairros", "Escolas", "Seções"],
             [[str(i + 1), tit(r["NM_MUNICIPIO"]), n0(r["jorge"]), p2(r["pct"]), n0(r["bairros"]), n0(r["escolas"]), n0(r["secoes"])]
              for i, r in mun.iterrows()], num=(0, 2, 3, 4, 5, 6))]
    partes, atual, n_atual = [], "", 0
    for i, m in mun.iterrows():
        b = bt[bt.NM_MUNICIPIO == m.NM_MUNICIPIO].copy()
        if m.NM_MUNICIPIO == "RIO DE JANEIRO":
            b = b.assign(o_=b.regiao.map(ORD_AP.index)).sort_values(["o_", "jorge"], ascending=[True, False])
        else:
            b = b.sort_values(["jorge", "NM_BAIRRO"], ascending=[False, True])
        cap_ap = m.NM_MUNICIPIO == "RIO DE JANEIRO"
        corpo = (f'<h2 class="pg">{i + 1}. {tit(m.NM_MUNICIPIO)} — {n0(m.jorge)} votos ({p2(m.pct)})</h2>'
                 f"<p>{n0(m.bairros)} bairros, {n0(m.escolas)} escolas e {n0(m.secoes)} seções.</p><h3>Bairros</h3>" + tabela(
                     ["Bairro"] + (["AP"] if cap_ap else []) + ["Votos", "% válidos", "Posição", "Escolas", "Seções"],
                     [[tit(r["NM_BAIRRO"])] + ([e(r["regiao"].split(" · ")[0])] if cap_ap else []) +
                      [n0(r["jorge"]), p2(r["pct"]), posf(r), n0(r["escolas"]), n0(r["secoes"])] for _, r in b.iterrows()],
                     num=range(1 + cap_ap, 6 + cap_ap), cls="mini"))
        n_linhas = len(b)
        for _, br in b.iterrows():
            x = es[(es.NM_MUNICIPIO == m.NM_MUNICIPIO) & (es.NM_BAIRRO == br.NM_BAIRRO)].sort_values(["jorge", "NM_LOCAL_VOTACAO"], ascending=[False, True])
            corpo += (f"<h3>{tit(br.NM_BAIRRO)}{' · ' + e(br.regiao.split(' · ')[0]) if cap_ap else ''} — {n0(br.jorge)} votos em {n0(len(x))} escolas</h3>"
                      + tabela(["Escola", "Endereço", "Zona", "Seções", "Válidos", "Votos", "%", "Posição"],
                               [[tit(r["NM_LOCAL_VOTACAO"]) + (f" <span class='nota'>(TSE: {tit(r['NM_BAIRRO_TSE'])})</span>"
                                                                   if A.chave_texto(r["NM_BAIRRO_TSE"]) != A.chave_texto(r["NM_BAIRRO"]) else ""),
                                 tit(r["DS_ENDERECO"]), r["zonas"], n0(r["secoes"]), n0(r["val7"]), n0(r["jorge"]),
                                 p2(r["pct"]), posf(r)] for _, r in x.iterrows()], num=range(3, 8), cls="mini"))
            n_linhas += len(x)
        toc.append((f"m{i}", f"{i + 1}. {tit(m.NM_MUNICIPIO)} — {n0(m.jorge)} votos"))
        if n_atual and n_atual + n_linhas > BLOCO:
            partes.append(parte_html(atual))
            atual, n_atual = "", 0
        atual += corpo
        n_atual += n_linhas
    if atual:
        partes.append(parte_html(atual))
    kp = [(n0(total), "votos de Jorge"), (n0(len(es)), "escolas no estado"), (n0(int((es.jorge > 0).sum())), "escolas com voto"),
          (n0(len(bt)), "bairros"), (n0(int((es.pos == 1).sum())), "escolas em que Jorge foi o mais votado"), ("92", "municípios")]
    # sumário sem link: os capítulos vêm em partes impressas separadamente
    toc_sem_link = toc[:2]
    principal = documento("Jorge Felippe Neto escola a escola", "Deputado estadual · PL · 22800 — estado do Rio de Janeiro, município a município, "
                          "bairro a bairro", kp, toc_sem_link, "".join(C) + "<h2>Municípios (capítulos a seguir)</h2><ol>" +
                          "".join(f"<li>{e(t.split('. ', 1)[1])}</li>" for _, t in toc[2:]) + "</ol>")
    return principal, partes


def pdf_transferencia_ap5(nm, v, base, fed=1177, outro=11123, n_boot=200, n_top=25):
    """Cruzamento urna a urna dos votos de Dr. Luizinho na AP5 com os de Jorge (e Pampolha): fatos contados
    (coincidência, faixas, teto possível) + estimativa ecológica de Goodman com os n_top estaduais da AP5
    separados (sem isso, aliados de Luizinho omitidos inflavam a taxa de Pampolha: 6.010 → 5.227) + destino
    federal dos eleitores de Jorge. Estimativa, não contagem: o voto é secreto."""
    from scipy.optimize import lsq_linear
    J = A.JFN
    ap5 = base[base.regiao == A.ZONA_OESTE[1]]
    x7 = v[v.cargo == 7].merge(ap5[KEYS], on=KEYS)
    top = x7[x7.tipo == "nominal"].groupby("numero").qtd.sum().sort_values(ascending=False)
    K = list(top.index[:n_top])
    assert J in K and outro in K
    piv = x7[(x7.tipo == "nominal") & x7.numero.isin(K)].pivot_table(index=KEYS, columns="numero", values="qtd", aggfunc="sum").fillna(0)
    comp = pd.read_sql("SELECT municipio,zona,secao,comparecimento AS comp6 FROM secao WHERE cargo=6",
                       sqlite3.connect(f"{A.T}/eleicao2026_rj_secao.sqlite")).set_index(KEYS)
    x6 = v[(v.cargo == 6) & (v.tipo == "nominal")].merge(ap5[KEYS], on=KEYS)
    topf = [int(f) for f in x6.groupby("numero").qtd.sum().sort_values(ascending=False).head(30).index]
    assert fed in topf
    pf = x6[x6.numero.isin(topf)].pivot_table(index=KEYS, columns="numero", values="qtd", aggfunc="sum")
    d = piv.join(comp, how="inner").join(pf.rename(columns=lambda c: f"f{int(c)}"), how="left").fillna(0)
    d["resto"] = d.comp6 - d[K].sum(axis=1)
    d = d.reset_index().merge(ap5[KEYS + ["NM_LOCAL_VOTACAO", "NM_BAIRRO"]], on=KEYS, how="left")
    L = d[f"f{fed}"]
    TL, TJ, TO = int(L.sum()), int(d[J].sum()), int(d[outro].sum())
    assert TL == int(v[(v.cargo == 6) & (v.tipo == "nominal") & (v.numero == fed)].merge(ap5[KEYS], on=KEYS).qtd.sum())
    NO, NF = tit(nm[(7, outro)][0]), tit(nm[(6, fed)][0])
    CO, CF = NO.split()[-1], CURTO.get(fed, NF)
    cols = K + ["resto"]
    X = d[cols].values.astype(float)
    w = 1 / np.sqrt(np.maximum(d.comp6.values, 1))
    tot = d[cols].sum()
    iJ, iO = cols.index(J), cols.index(outro)

    def fit(y, idx=slice(None)):
        return lsq_linear(X[idx] * w[idx, None], y[idx] * w[idx], bounds=(0, 1)).x

    b = fit(L.values.astype(float))
    est_j, est_o = b[iJ] * TJ, b[iO] * TO
    rng = np.random.default_rng(1)
    bs = []
    for _ in range(n_boot):
        ix = rng.choice(len(d), len(d))
        bb = fit(L.values.astype(float), ix)
        bs.append((bb[iJ] * TJ, bb[iO] * TO))
    bs = np.array(bs)
    (lj, hj), (lo, ho) = np.percentile(bs[:, 0], [2.5, 97.5]), np.percentile(bs[:, 1], [2.5, 97.5])
    teto_j, teto_o = int(np.minimum(d[J], L).sum()), int(np.minimum(d[outro], L).sum())
    viz_j = float((L * d[J] / d.comp6.replace(0, np.nan)).sum())
    viz_o = float((L * d[outro] / d.comp6.replace(0, np.nan)).sum())
    alloc = pd.DataFrame({"cand": [nm.get((7, c), ("Demais estaduais, legenda, brancos e nulos",))[0] if c != "resto" else "Demais estaduais, legenda, brancos e nulos" for c in cols],
                          "partido": [nm.get((7, c), (0, ""))[1] if c != "resto" else "" for c in cols], "base": tot.values, "taxa": b,
                          "votos": b * tot.values}).sort_values("votos", ascending=False)
    # destino federal dos eleitores de Jorge e de Pampolha
    dest = []
    for f in topf:
        bb = fit(d[f"f{f}"].values.astype(float))
        dest.append((tit(nm[(6, f)][0]), nm[(6, f)][1], int(d[f"f{f}"].sum()), bb[iJ] * 100, bb[iJ] * TJ, bb[iO] * 100, bb[iO] * TO))
    dest = pd.DataFrame(dest, columns=["fed", "sg", "votos", "tj", "ej", "to", "eo"]).sort_values("ej", ascending=False).reset_index(drop=True)
    pos_l = int(dest.index[dest.fed == NF][0]) + 1

    # fatos contados
    faixas = [(1, 4), (5, 9), (10, 19), (20, 10 ** 6)]
    rot = {(1, 4): "1 a 4", (5, 9): "5 a 9", (10, 19): "10 a 19", (20, 10 ** 6): "20 ou mais"}

    def faixa_l(col):
        out = [("sem voto", int((d[col] == 0).sum()), int(L[d[col] == 0].sum()))]
        for a_, z_ in faixas:
            m = (d[col] >= a_) & (d[col] <= z_)
            out.append((rot[(a_, z_)], int(m.sum()), int(L[m].sum())))
        return out

    d["e_j"], d["e_o"] = b[iJ] * d[J], b[iO] * d[outro]
    d["teto_j"], d["teto_o"] = np.minimum(d[J], L), np.minimum(d[outro], L)

    C, toc = [], []

    def sec(k, t, c, quebra=False):
        toc.append((k, t))
        C.append(f'<h2 id="{k}" class="{"pg" if quebra else ""}">{e(t)}</h2>{c}')

    sec("v1", "1. Sumário executivo", f"""
<p>Na AP5, {NF} teve <b>{n0(TL)} votos</b>; Jorge Felippe Neto teve {n0(TJ)} e {NO} {n0(TO)}. Cruzando as {n0(len(d))} urnas:</p>
<p><b>Fatos contados.</b> {n0(int(L[d[J] > 0].sum()))} dos {n0(TL)} votos de {NF} ({p2(L[d[J] > 0].sum() / TL * 100)}) estão em urnas em que Jorge
também foi votado. Somando, urna a urna, o menor entre os votos de Jorge e os de {NF}, o <b>máximo possível</b> de eleitores de Jorge que
votaram em {NF} é {n0(teto_j)}; para {NO}, esse teto é {n0(teto_o)}, porque a base dele na AP5 é menor.</p>
<p><b>Estimativa.</b> Pelo modelo urna a urna, <b>cerca de {n0(est_j)} eleitores de Jorge votaram em {NF}</b> (faixa provável de
{n0(lj)} a {n0(hj)}; {p2(b[iJ] * 100)} da base de Jorge), e cerca de {n0(est_o)} eleitores de {NO} (de {n0(lo)} a {n0(ho)};
{p2(b[iO] * 100)} da base dele). As duas faixas se sobrepõem: estatisticamente, as contribuições de Jorge e de {NO} para {NF} na AP5 são
equivalentes. Jorge tem a base maior; {NO} tem a taxa maior, o que é coerente com ele ser do mesmo partido de {NF}.</p>
<p><b>Destino dos eleitores de Jorge.</b> Entre os federais, {NF} é o <b>{pos_l}º que mais recebeu votos dos eleitores de Jorge</b> na AP5
(cerca de {n0(dest.loc[pos_l - 1, "ej"])}){", atrás apenas de " + dest.loc[0, "fed"] + f" (cerca de {n0(dest.loc[0, 'ej'])})" if pos_l == 2 else ""}.
Para comparação, sem nenhuma afinidade (cada eleitor de Jorge votando em {NF} na mesma proporção que o resto da sua urna), seriam só
{n0(viz_j)}: a votação de Jorge levou a {NF} cerca de {d2(est_j / viz_j) if viz_j else "—"} vezes o que o acaso levaria.</p>""")

    sec("v2", "2. Método e cuidados", f"""
<p>Cada eleitor dá um voto para estadual e um para federal. "Transferir" significa quantos eleitores que votaram em Jorge para estadual
votaram também em {NF} para federal. O voto é secreto, então esse número é <b>estimado</b> pela forma como as votações variam juntas pelas
urnas (regressão ecológica de Goodman): em cada urna, os votos de {NF} são decompostos em uma taxa dos eleitores de cada um dos {n_top}
estaduais mais votados da AP5 — tratados separadamente — mais uma taxa do restante do comparecimento (demais estaduais, legenda,
brancos e nulos). As taxas ficam entre 0% e 100%, a regressão pondera pelo tamanho da urna, e a faixa provável (95%) vem de {n_boot}
reamostragens das urnas.</p>
<div class="callout"><b>Correção em relação à primeira versão.</b> A primeira versão separava só Jorge, {NO} e "o resto". Como {NF} tem outros
aliados entre os estaduais, os votos que vieram deles caíam na conta de quem é forte nas mesmas urnas, e a taxa de {NO} saía inflada
(cerca de 6.010). Com os {n_top} estaduais separados, a estimativa de {NO} cai para cerca de {n0(est_o)}, e a de Jorge fica estável
(cerca de {n0(est_j)}).</div>
<p><b>Cuidados.</b> O modelo supõe que a taxa de cada grupo é parecida entre as urnas da AP5. É inferência sobre urnas, não identificação
de eleitores. O <b>teto</b> (seção 3) não depende de modelo: é o máximo matematicamente possível em cada urna, somado.</p>""")

    sec("v3", "3. Fatos contados urna a urna", tabela(
        ["", "Jorge", NO],
        [["Votos na AP5", n0(TJ), n0(TO)],
         [f"Urnas com voto do candidato (de {n0(len(d))})", n0(int((d[J] > 0).sum())), n0(int((d[outro] > 0).sum()))],
         [f"Votos de {NF} nessas urnas", n0(int(L[d[J] > 0].sum())), n0(int(L[d[outro] > 0].sum()))],
         [f"Teto: máximo possível de eleitores do candidato que votaram em {NF}", f"<b>{n0(teto_j)}</b>", f"<b>{n0(teto_o)}</b>"]],
        num=(1, 2)) + f"<h3>Votos de {NF} conforme a votação de Jorge na urna</h3>" + tabela(
        ["Votos de Jorge na urna", "Urnas", f"Votos de {NF}"], [[a_, n0(u), n0(lv)] for a_, u, lv in faixa_l(J)], num=(1, 2)) +
        f"<h3>Votos de {NF} conforme a votação de {NO} na urna</h3>" + tabela(
        [f"Votos de {NO} na urna", "Urnas", f"Votos de {NF}"], [[a_, n0(u), n0(lv)] for a_, u, lv in faixa_l(outro)], num=(1, 2)))

    sec("v4", "4. Estimativa: de onde vieram os votos de " + NF, tabela(
        ["Origem", "Faixa provável (IC 95%)", "Taxa estimada", "Votos estimados", "Teto possível", "Sem afinidade (acaso)"],
        [["Eleitores de Jorge", f"{n0(lj)} a {n0(hj)}", p2(b[iJ] * 100), f"<b>{n0(est_j)}</b>", n0(teto_j), n0(viz_j)],
         [f"Eleitores de {NO}", f"{n0(lo)} a {n0(ho)}", p2(b[iO] * 100), f"<b>{n0(est_o)}</b>", n0(teto_o), n0(viz_o)]], num=range(1, 6)) +
        "<h3>Todas as origens estimadas (estaduais da AP5)</h3>" + tabela(
            ["Base de origem", "Partido", "Eleitores na AP5", "Taxa estimada", f"Votos estimados para {NF}"],
            [[tit(r.cand), e(r.partido), n0(r.base), p2(r.taxa * 100), n0(r.votos)] for r in alloc.itertuples() if r.votos >= 0.5] +
            [["<b>Total estimado</b>", "", "", "", f"<b>{n0(alloc.votos.sum())}</b> (real: {n0(TL)})"]], num=(2, 3, 4), cls="mini"))

    sec("v5", "5. Para quais federais foram os eleitores de Jorge", f"<p>O mesmo modelo, aplicado a cada um dos 30 federais mais votados da AP5, "
        f"estima quantos eleitores de Jorge (e de {NO}) votaram em cada um. A soma não chega à base inteira porque parte dos eleitores votou em "
        "federais fora desta lista, na legenda, em branco ou nulo.</p>" + tabela(
            ["#", "Federal", "Partido", "Votos na AP5", "Taxa entre eleitores de Jorge", "De Jorge", f"Taxa entre eleitores de {CO}", f"De {CO}"],
            [[str(i + 1), f"<b>{e(r.fed)}</b>" if r.fed == NF else e(r.fed), e(r.sg), n0(r.votos), p2(r.tj), n0(r.ej), p2(r.to), n0(r.eo)]
             for i, r in dest.iterrows()], num=(0, 3, 4, 5, 6, 7), cls="mini", destaque=lambda k, _f=dest.fed.values: _f[k] == NF))

    zt = d.groupby("zona").agg(urnas=("secao", "count"), L=(f"f{fed}", "sum"), j=(J, "sum"), o=(outro, "sum"), tj=("teto_j", "sum"),
                               to=("teto_o", "sum"), ej=("e_j", "sum"), eo=("e_o", "sum")).reset_index().sort_values("L", ascending=False)
    sec("v6", "6. Zona a zona", "<p>Em cada zona da AP5: os votos dos três, o teto possível e a estimativa (taxas da AP5 aplicadas às urnas da "
        "zona).</p>" + tabela(
            ["Zona", "Urnas", CF, "Jorge", CO, "Teto de Jorge", "Estimado de Jorge", f"Teto de {CO}", f"Estimado de {CO}"],
            [[f"{int(r.zona)}ª", n0(r.urnas), n0(r.L), n0(r.j), n0(r.o), n0(r.tj), n0(r.ej), n0(r.to), n0(r.eo)] for r in zt.itertuples()],
            num=range(1, 9)))

    us = d.sort_values(["zona", "secao"])
    sec("v7", "7. Urna a urna", f"<p>As {n0(len(us))} urnas da AP5. \"Teto\" é o máximo possível de eleitores do candidato que votaram em {NF} "
        "naquela urna; \"Estimado\" aplica a taxa estimada aos votos do candidato na urna. Em destaque, as urnas em que Jorge teve 10 ou "
        "mais votos.</p>" + tabela(
            ["Zona", "Seção", "Escola", "Bairro", CF, "Jorge", "Teto J.", "Estim. J.", CO, "Teto P.", "Estim. P."],
            [[f"{int(r['zona'])}ª", int(r["secao"]), tit(r["NM_LOCAL_VOTACAO"]), tit(r["NM_BAIRRO"]), n0(r[f"f{fed}"]), n0(r[J]), n0(r["teto_j"]),
              d2(r["e_j"]), n0(r[outro]), n0(r["teto_o"]), d2(r["e_o"])] for r in us.to_dict("records")],
            num=range(4, 11), cls="mini", destaque=lambda k, _a=us[J].values: _a[k] >= 10), quebra=True)

    kp = [(n0(TL), f"votos de {NF} na AP5"), (n0(est_j), f"estimados de eleitores de Jorge ({n0(lj)}–{n0(hj)})"),
          (n0(est_o), f"estimados de eleitores de {CO} ({n0(lo)}–{n0(ho)})"), (n0(teto_j), "teto possível vindo de Jorge"),
          (f"{pos_l}º", f"{CF} entre os federais dos eleitores de Jorge"), (n0(len(d)), "urnas da AP5")]
    return documento(f"{NF} e Jorge Felippe Neto na AP5: cruzamento urna a urna", f"Quantos eleitores de Jorge e de {NO} votaram em {NF} — "
                     "fatos contados, teto possível e estimativa", kp, toc, "".join(C))


def pdf_auditoria(nm, v, base):
    """Nota de auditoria dos números de Jorge: conferência contra o arquivo oficial do TSE por município e zona
    (2026 e 2022), correções feitas e o efeito do bairro oficial da Prefeitura, escola por escola."""
    J = A.JFN
    T = A.T
    usa = ["NR_TURNO", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "CD_CARGO", "NR_CANDIDATO", "QT_VOTOS_NOMINAIS"]

    def oficial(ano, nr):
        o = pd.read_csv(f"{T}/votacao_candidato_munzona_{ano}_RJ.csv", sep=";", encoding="latin1", dtype=str, usecols=usa)
        o = o[(o.CD_CARGO == "7") & (o.NR_CANDIDATO == nr) & (o.NR_TURNO == "1")]
        return o.assign(municipio=o.CD_MUNICIPIO.astype(int), zona=o.NR_ZONA.astype(int), v=o.QT_VOTOS_NOMINAIS.astype(int)) \
            .groupby(["municipio", "zona", "NM_MUNICIPIO"]).v.sum().reset_index()

    o26 = oficial(2026, str(J))
    jv = v[(v.cargo == 7) & (v.tipo == "nominal") & (v.numero == J)].groupby(["municipio", "zona"]).qtd.sum().rename("bu").reset_index()
    cz = o26.merge(jv, on=["municipio", "zona"], how="outer").fillna(0)
    cz["dif"] = cz.bu - cz.v
    o22 = oficial(2022, "70800")
    j22 = pd.read_csv(f"{T}/jfn_2022_secao_RJ.csv", sep=";")
    m22 = o22.groupby("NM_MUNICIPIO").v.sum().to_frame("of").join(j22.groupby("nm_municipio").votos_jfn.sum().rename("meu"), how="outer").fillna(0)

    d = base.copy()
    jsec = v[(v.cargo == 7) & (v.tipo == "nominal") & (v.numero == J)].groupby(KEYS).qtd.sum().rename("jorge")
    d = d.merge(jsec, left_on=KEYS, right_index=True, how="left").fillna({"jorge": 0})
    rio = d[d.municipio == A.RIO].copy()
    # AP pelo critério antigo (nome do TSE): lista por nome, AP3 por padrão — só para mostrar o antes
    rio["ap_antes"] = rio.NM_BAIRRO_TSE.map(lambda b: A.BAIRRO_AP.get(str(b).upper(), "AP3 · Zona Norte"))
    # mesmo bairro, nome diferente no TSE: sem isso a comparação mostra "Recreio" sumindo e "Recreio dos Bandeirantes" surgindo
    alias = {"RECREIO": "RECREIO DOS BANDEIRANTES", "FREGUESIA JPA": "FREGUESIA (JACAREPAGUÁ)", "OSWALDO CRUZ": "OSVALDO CRUZ",
             "SÃO CRISTÓVÃO": "IMPERIAL DE SÃO CRISTÓVÃO", "FREGUESIA (ILHA DO GOVERNADOR)": "FREGUESIA (ILHA)",
             "FUNDÃO": "CIDADE UNIVERSITÁRIA"}
    rio["NM_BAIRRO_TSE"] = rio.NM_BAIRRO_TSE.map(lambda b: alias.get(str(b).upper(), b))
    antes = rio.groupby("NM_BAIRRO_TSE").jorge.sum()
    depois = rio.groupby("NM_BAIRRO").jorge.sum()
    chaves = sorted(set(antes.index.map(A.chave_texto)) | set(depois.index.map(A.chave_texto)))
    a_k = antes.groupby(antes.index.map(A.chave_texto)).sum()
    d_k = depois.groupby(depois.index.map(A.chave_texto)).sum()
    nome_k = {A.chave_texto(b): b for b in list(antes.index) + list(depois.index)}
    nome_k.update({A.chave_texto(b): b for b in depois.index})
    bd = pd.DataFrame({"bairro": [nome_k[k] for k in chaves], "antes": [a_k.get(k, 0) for k in chaves], "depois": [d_k.get(k, 0) for k in chaves]})
    bd["dif"] = bd.depois - bd.antes
    bd["ap"] = [A.regiao(A.RIO, b) if A.chave_texto(b) in set(depois.index.map(A.chave_texto)) else "—" for b in bd.bairro]
    bd = bd[(bd.antes > 0) | (bd.depois > 0)].sort_values(["depois", "antes"], ascending=False)
    ap_antes = rio.groupby("ap_antes").jorge.sum()
    ap_depois = rio.groupby("regiao").jorge.sum()
    es = rio.groupby("k_escola").agg(nome=("NM_LOCAL_VOTACAO", "first"), end=("DS_ENDERECO", "first"), tse=("NM_BAIRRO_TSE", "first"),
                                     of=("NM_BAIRRO", "first"), ap=("regiao", "first"), apa=("ap_antes", "first"), jorge=("jorge", "sum")).reset_index()
    div = es[es.tse.map(A.chave_texto) != es.of.map(A.chave_texto)].sort_values("jorge", ascending=False)
    n_nome = int(base[(base.municipio == A.RIO)].drop_duplicates("k_escola").pipe(
        lambda x: ((x.NM_BAIRRO_TSE.map(A.chave_texto) != x.NM_BAIRRO.map(A.chave_texto)).sum())) - len(div))
    assert int(bd.antes.sum()) == int(bd.depois.sum()) == int(rio.jorge.sum())

    C, toc = [], []

    def sec(k, t, c, quebra=False):
        toc.append((k, t))
        C.append(f'<h2 id="{k}" class="{"pg" if quebra else ""}">{e(t)}</h2>{c}')

    ok = lambda b: "✔ confere" if b else "✘ diverge"  # noqa: E731
    sec("q1", "1. O que foi conferido", tabela(
        ["Conferência", "Fonte independente", "Resultado"],
        [["Total de Jorge em 2026", "Total oficial do TSE (resultados por candidato)", f"{n0(int(jsec.sum()))} = {n0(nm[(7, J)][3])} · {ok(int(jsec.sum()) == nm[(7, J)][3])}"],
         ["Jorge por município e zona, 2026", "Arquivo oficial de votação por município e zona do TSE",
          f"{len(cz)} combinações; diferenças: {int((cz.dif != 0).sum())} · {ok((cz.dif == 0).all())}"],
         ["Total e municípios de 2022 (70800)", "Arquivo oficial de 2022 por município e zona", f"{n0(int(m22.of.sum()))} = {n0(int(m22.meu.sum()))}; "
          f"municípios com diferença: {int((m22.of != m22.meu).sum())} · {ok((m22.of == m22.meu).all())}"],
         ["Soma dos votos de cada cargo por urna", "Comparecimento registrado no próprio boletim", "37.675 urnas, nenhuma divergência · ✔ confere"],
         ["Candidatos e percentuais", "Totais oficiais do TSE por candidato (inclui % exato)", "1.928 candidatos e 1.883 percentuais idênticos · ✔ confere"],
         ["Bairro de cada escola da capital", "Malha oficial de 167 bairros da Prefeitura",
          f"{len(div) + n_nome} de {len(es)} escolas com nome do TSE diferente do oficial: {n_nome} são só outro nome do mesmo bairro "
          f"(ex.: Recreio / Recreio dos Bandeirantes) e {len(div)} ficam em outro bairro oficial · corrigido (seções 3 a 5)"]]) +
        "<p>Conclusão: <b>a contagem de votos estava correta</b> em todos os níveis (estado, município, zona e urna). O que estava errado era a "
        "<b>atribuição de bairro e de Área de Planejamento</b> na capital, que dependia do nome dado pelo cadastro do TSE. A seção 2 lista "
        "todas as correções feitas.</p>")

    sec("q2", "2. Correções feitas", "<ol>" + "".join(f"<li>{x}</li>" for x in [
        "<b>Bairro oficial da Prefeitura na capital.</b> O bairro passou a ser o oficial, definido pela localização de cada escola na malha "
        "oficial de bairros; o nome dado pelo TSE diverge em cerca de 19% das escolas (ex.: escolas de Jabour registradas como Senador Camará; "
        "várias escolas de Bangu registradas como Padre Miguel). A Área de Planejamento passou a vir da mesma malha, e não mais do nome.",
        "<b>Área de Planejamento por nome.</b> Nomes do TSE que não são bairros oficiais caíam na AP3 por padrão — \"Catiri\" e \"São Jorge\" "
        f"ficam na AP5, entre outros; {int((div.ap != div.apa).sum())} escolas mudaram de AP.",
        "<b>Grafias.</b> Bairros grafados de dois jeitos (\"Tomás\"/\"Tomas Coelho\", \"Mutuá\"/\"Mutua\", \"Andrade Araújo\"/\"Araujo\") "
        "e em caixa baixa (\"barra olímpica\") saíam partidos; foram unificados.",
        "<b>Escolas duplicadas.</b> 43 escolas apareciam com dois números de local; cada escola agora é identificada por nome e endereço.",
        "<b>Votos anulados.</b> Votos em números fora da lista oficial (candidaturas com votos anulados pelo TSE) entravam como válidos e "
        "distorciam percentuais; passaram a ser anulados, como no total oficial.",
        "<b>Correlação.</b> A correlação bruta por seção misturava geografia com afinidade; a medida principal passou a ser a correlação "
        "controlada por região (ex.: Pazuello de −0,01 para +0,05).",
        "<b>Transferência para Dr. Luizinho na AP5.</b> O primeiro modelo separava só Jorge, Pampolha e \"o resto\" e inflava a estimativa "
        "de Pampolha (6.010); com os 25 estaduais da AP5 separados, Jorge ~4.922 e Pampolha ~5.227 — empate estatístico."]) + "</ol>")

    sec("q3", "3. Seus votos por Área de Planejamento: antes e depois", tabela(
        ["Área de Planejamento", "Antes (nome do TSE)", "Depois (bairro oficial)", "Diferença"],
        [[e(ap), n0(ap_antes.get(ap, 0)), n0(ap_depois.get(ap, 0)), ("+" if ap_depois.get(ap, 0) > ap_antes.get(ap, 0) else "") +
          n0(ap_depois.get(ap, 0) - ap_antes.get(ap, 0))] for ap in ORD_AP] +
        [["<b>Capital</b>", n0(int(ap_antes.sum())), n0(int(ap_depois.sum())), "0"]], num=(1, 2, 3)))

    sec("q4", "4. Seus votos por bairro: antes e depois", "<p>\"Antes\" agrupa pelo nome do bairro no cadastro do TSE; \"depois\", pelo "
        "bairro oficial da Prefeitura em que fica a escola. O total da capital não muda; muda a divisão entre bairros.</p>" + tabela(
            ["Bairro", "AP (oficial)", "Antes", "Depois", "Diferença"],
            [[tit(r.bairro), e(r.ap.split(" · ")[0]), n0(r.antes), f"<b>{n0(r.depois)}</b>", ("+" if r.dif > 0 else "") + n0(r.dif)]
             for r in bd.itertuples()], num=(2, 3, 4), cls="mini"), quebra=True)

    sec("q5", "5. Escolas em que o bairro do TSE difere do oficial", f"<p>As {len(div)} escolas da capital que ficam em outro bairro oficial, "
        "com o nome de bairro usado pelo TSE, o bairro oficial em que a escola fica e os votos de Jorge nela. Diferenças só de grafia ou de nome "
        "do mesmo bairro (Recreio / Recreio dos Bandeirantes, Freguesia JPA / Freguesia (Jacarepaguá) e semelhantes) não estão na lista. "
        "Nomes que não são bairros oficiais (Jardim Bangu, Vila Kennedy dentro de Bangu, Catiri, Augusto Vasconcelos, Rio das Pedras) "
        "aparecem como diferença, porque a escola fica dentro de um bairro oficial de outro nome.</p>" + tabela(
            ["Escola", "Endereço", "Bairro no TSE", "Bairro oficial", "AP", "Votos"],
            [[tit(r.nome), tit(r.end), tit(r.tse), f"<b>{tit(r.of)}</b>", e(r.ap.split(" · ")[0]), n0(r.jorge)] for r in div.itertuples()],
            num=(5,), cls="mini"), quebra=True)

    sec("q6", "6. Conferência município por zona contra o TSE", "<p>Votos de Jorge em 2026 por município e zona: arquivo oficial do TSE × soma dos "
        "boletins de urna usada nos relatórios.</p>" + tabela(
            ["Município", "Zona", "Oficial TSE", "Boletins de urna", "Diferença"],
            [[tit(r.NM_MUNICIPIO), f"{int(r.zona)}ª", n0(r.v), n0(r.bu), n0(r.dif)] for r in cz.sort_values(["NM_MUNICIPIO", "zona"]).itertuples()],
            num=(2, 3, 4), cls="mini"), quebra=True)

    kp = [(n0(int(jsec.sum())), "votos, iguais ao oficial"), (f"{len(cz)} / {int((cz.dif != 0).sum())}", "zonas conferidas / divergências"),
          (n0(len(div)), "escolas em outro bairro oficial"), (n0(int((div.ap != div.apa).sum())), "escolas que mudaram de AP"),
          (n0(int(ap_depois.get(A.ZONA_OESTE[1], 0))), "AP5 (bairro oficial)"),
          (n0(int(ap_depois.get(A.ZONA_OESTE[0], 0) + ap_depois.get(A.ZONA_OESTE[1], 0))), "Zona Oeste (bairro oficial)")]
    return documento("Auditoria dos números de Jorge Felippe Neto", "O que foi conferido, o que estava errado e o que mudou", kp, toc, "".join(C))


def pdf_bairros_jorge(nm, v, base):
    """Jorge bairro a bairro, cidade a cidade: todos os bairros dos 92 municípios (capital por AP, bairro oficial),
    com votos, % válidos, posição, mais votado no bairro, 2022 e variação."""
    J = A.JFN
    x7 = v[v.cargo == 7]
    val = x7[x7.valido].groupby(KEYS).qtd.sum().rename("val7")
    nomi = x7[x7.tipo == "nominal"][KEYS + ["numero", "qtd"]].merge(base[KEYS + ["NM_MUNICIPIO", "NM_BAIRRO"]], on=KEYS)
    jv = nomi[nomi.numero == J].set_index(KEYS).qtd.rename("jorge")
    d = base.merge(val, left_on=KEYS, right_index=True, how="left").merge(jv, left_on=KEYS, right_index=True, how="left").fillna({"val7": 0, "jorge": 0})
    total = int(d.jorge.sum())
    assert total == nm[(7, J)][3]
    rk = nomi.groupby(["NM_MUNICIPIO", "NM_BAIRRO", "numero"]).qtd.sum().reset_index()
    rk = rk[rk.qtd > 0]
    rk["p"] = rk.groupby(["NM_MUNICIPIO", "NM_BAIRRO"]).qtd.rank(ascending=False, method="min")
    pos = rk[rk.numero == J].set_index(["NM_MUNICIPIO", "NM_BAIRRO"]).p
    ncand = rk.groupby(["NM_MUNICIPIO", "NM_BAIRRO"]).size()
    lid = rk.sort_values("qtd", ascending=False).drop_duplicates(["NM_MUNICIPIO", "NM_BAIRRO"]).set_index(["NM_MUNICIPIO", "NM_BAIRRO"])
    # 2022 pelo mesmo critério de bairro (oficial na capital, TSE unificado fora)
    l22 = A.locais(2022)
    l22 = l22[l22.CD_TIPO_SECAO_AGREGADA == "1"].drop_duplicates(KEYS)[KEYS + ["NM_BAIRRO"]]
    j22 = pd.read_csv(f"{A.T}/jfn_2022_secao_RJ.csv", sep=";").rename(columns={"cd_municipio": "municipio"}).merge(l22, on=KEYS, how="left")
    b22 = j22.groupby(["nm_municipio", "NM_BAIRRO"]).votos_jfn.sum()
    b22 = b22.groupby([b22.index.get_level_values(0), b22.index.get_level_values(1).map(A.chave_texto)]).sum()
    bt = d.groupby(["NM_MUNICIPIO", "NM_BAIRRO", "regiao"]).agg(jorge=("jorge", "sum"), val7=("val7", "sum"), secoes=("secao", "count"),
                                                               escolas=("k_escola", "nunique")).reset_index()
    bt["pct"] = bt.jorge / bt.val7.replace(0, np.nan) * 100
    idx = list(zip(bt.NM_MUNICIPIO, bt.NM_BAIRRO))
    bt["pos"] = [pos.get(k) for k in idx]
    bt["ncand"] = [ncand.get(k) for k in idx]
    bt["lider"] = [tit(nm.get((7, lid.numero.get(k)), ("—",))[0]) if k in lid.index else "—" for k in idx]
    bt["lider_v"] = [lid.qtd.get(k, 0) for k in idx]
    bt["v22"] = [b22.get((m, A.chave_texto(b)), 0) for m, b in idx]
    assert int(bt.jorge.sum()) == total
    mun = bt.groupby("NM_MUNICIPIO").agg(jorge=("jorge", "sum"), val7=("val7", "sum"), bairros=("NM_BAIRRO", "nunique"),
                                          v22=("v22", "sum")).reset_index()
    mun["pct"] = mun.jorge / mun.val7 * 100
    mun = mun.sort_values(["jorge", "NM_MUNICIPIO"], ascending=[False, True]).reset_index(drop=True)
    t22 = int(j22.votos_jfn.sum())

    def sinal(x):
        return ("+" if x > 0 else "") + n0(x)

    def linhas(x, com_ap):
        return [[tit(r["NM_BAIRRO"])] + ([e(r["regiao"].split(" · ")[0])] if com_ap else []) +
                [n0(r["jorge"]), p2(r["pct"]), f"{int(r['pos'])}º de {n0(r['ncand'])}" if not pd.isna(r["pos"]) else "—",
                 f"{r['lider']} ({n0(r['lider_v'])})", n0(r["v22"]), sinal(r["jorge"] - r["v22"]), n0(r["escolas"]), n0(r["secoes"])]
                for _, r in x.iterrows()]

    cab = ["Bairro", "Votos", "% válidos", "Posição", "Mais votado no bairro", "2022", "Variação", "Escolas", "Seções"]
    toc = [("b1", "Leitura"), ("b2", "Os 92 municípios")]
    C = [f"""<h2 id="b1">Leitura</h2>
<p>Votos de Jorge Felippe Neto (PL, 22800) para deputado estadual em 2026, bairro a bairro, em cada um dos 92 municípios do Estado do Rio
de Janeiro: {n0(total)} votos ({n0(t22)} em 2022). Fonte: boletins de urna do TSE (pleito 3220, 1º turno de 04/10/2026), conferidos contra o
total oficial e contra o arquivo oficial do TSE por município e zona. {FONTE_BAIRRO} "Posição" é o lugar de Jorge entre os candidatos a
estadual com voto no bairro; "Mais votado" é o candidato a estadual com mais votos ali. A coluna 2022 usa o mesmo critério de bairro
aplicado aos locais de votação de 2022.</p>""",
         '<h2 id="b2">Os 92 municípios</h2>' + tabela(
             ["#", "Município", "Votos", "% válidos", "2022", "Variação", "Bairros"],
             [[str(i + 1), f'<a href="#m{i}">{tit(r["NM_MUNICIPIO"])}</a>', n0(r["jorge"]), p2(r["pct"]), n0(r["v22"]),
               sinal(r["jorge"] - r["v22"]), n0(r["bairros"])] for i, r in mun.iterrows()], num=(0, 2, 3, 4, 5, 6))]
    for i, m in mun.iterrows():
        x = bt[bt.NM_MUNICIPIO == m.NM_MUNICIPIO]
        cap = m.NM_MUNICIPIO == "RIO DE JANEIRO"
        corpo = f'<h2 id="m{i}" class="pg">{i + 1}. {tit(m.NM_MUNICIPIO)} — {n0(m.jorge)} votos ({p2(m.pct)})</h2>'
        if cap:
            for ap in ORD_AP:
                y = x[x.regiao == ap].sort_values(["jorge", "NM_BAIRRO"], ascending=[False, True])
                corpo += f"<h3>{e(ap)} — {n0(y.jorge.sum())} votos em {len(y)} bairros</h3>" + tabela(cab, linhas(y, False), num=(1, 2, 3, 5, 6, 7, 8), cls="mini")
        else:
            y = x.sort_values(["jorge", "NM_BAIRRO"], ascending=[False, True])
            corpo += tabela(cab, linhas(y, False), num=(1, 2, 3, 5, 6, 7, 8), cls="mini")
        C.append(corpo)
        toc.append((f"m{i}", f"{i + 1}. {tit(m.NM_MUNICIPIO)} — {n0(m.jorge)} votos"))
    kp = [(n0(total), "votos de Jorge"), (n0(len(bt)), "bairros no estado"), (n0(int((bt.jorge > 0).sum())), "bairros com voto"),
          (n0(int((bt.pos == 1).sum())), "bairros em que Jorge é o mais votado"), (n0(t22), "votos em 2022"), ("92", "municípios")]
    return documento("Jorge Felippe Neto bairro a bairro, cidade a cidade", "Deputado estadual · PL · 22800 — os 92 municípios do Estado do Rio "
                     "de Janeiro", kp, toc, "".join(C))


async def gerar_partes(htmls, nome):
    """Imprime cada parte num PDF próprio e junta na ordem: tabela gigante numa página só trava o Chromium."""
    from pypdf import PdfWriter
    partes = []
    for k, h in enumerate(htmls):
        A.checar_neutro(h, f"{nome} parte {k}")
        destino = f"{OUT}/.{nome}.parte{k}.pdf"
        await html_to_pdf(h, destino, timeout_s=900)
        partes.append(destino)
    w = PdfWriter()
    for f in partes:
        w.append(f)
    w.write(f"{OUT}/{nome}.pdf")
    for f in partes:
        os.remove(f)
    open(f"{OUT}/{nome}.html", "w").write("".join(htmls))
    print(nome, os.path.getsize(f"{OUT}/{nome}.pdf") // 1024, "KB", len(htmls), "partes")


async def gerar(html, nome):
    A.checar_neutro(html, nome)
    open(f"{OUT}/{nome}.html", "w").write(html)
    await html_to_pdf(html, f"{OUT}/{nome}.pdf", timeout_s=1500)
    print(nome, os.path.getsize(f"{OUT}/{nome}.pdf") // 1024, "KB")


def main():
    nm, v, base = carregar()
    alvo = sys.argv[1] if len(sys.argv) > 1 else "ambos"
    if alvo in ("douglas", "ambos"):
        asyncio.run(gerar(pdf_douglas(nm, v, base), "Douglas_Ruas_2026_zonas_por_AP_capital"))
    if alvo in ("jorge", "ambos"):
        html, _ = pdf_jorge(nm, v, base)
        asyncio.run(gerar(html, "Jorge_Felippe_Neto_2026_votacao_completa"))
    if alvo == "bairros":
        asyncio.run(gerar(pdf_bairros_jorge(nm, v, base), "Jorge_Felippe_Neto_2026_bairro_a_bairro_cidade_a_cidade"))
    if alvo == "auditoria":
        asyncio.run(gerar(pdf_auditoria(nm, v, base), "Auditoria_numeros_Jorge_Felippe_Neto_2026"))
    if alvo == "transferencia":
        asyncio.run(gerar(pdf_transferencia_ap5(nm, v, base), "Transferencia_Jorge_Pampolha_para_Luizinho_2026_AP5"))
    if alvo == "trio_zo_tabelas":
        principal, anexos = pdf_trio_zo_tabelas(nm, v, base)
        asyncio.run(gerar_partes([principal] + anexos, "Tabelas_Luizinho_Pampolha_Jorge_2026_zona_oeste"))
    if alvo == "escolas":
        principal, partes = pdf_escolas_jorge(nm, v, base)
        asyncio.run(gerar_partes([principal] + partes, "Jorge_Felippe_Neto_2026_escola_a_escola"))
    if alvo == "trio_tabelas":
        principal, anexos = pdf_trio_tabelas(nm, v, base)
        asyncio.run(gerar_partes([principal] + anexos, "Tabelas_Luizinho_Pampolha_Jorge_2026_estado"))
    if alvo == "trio":
        asyncio.run(gerar(pdf_trio_zo(nm, v, base), "Luizinho_Jorge_Pampolha_2026_zona_oeste"))
    if alvo == "douglas_estado":
        asyncio.run(gerar(pdf_douglas_estado(nm, v, base), "Douglas_Ruas_2026_estado_cidade_a_cidade"))
    if alvo == "estado":
        asyncio.run(gerar(pdf_estado(nm, v, base), "Jorge_Felippe_Neto_2026_estado_cidade_a_cidade"))
    if alvo == "urnas":
        asyncio.run(gerar(pdf_mesmas_urnas(nm, secoes_jorge_feds(v, base)), "Votos_nas_mesmas_urnas_Jorge_e_federais_2026"))
    if alvo == "federais":
        d = secoes_jorge_feds(v, base)
        for n in A.FEDS:
            slug = re.sub(r"[^A-Za-z0-9]+", "_", unicodedata.normalize("NFKD", tit(nm[(6, n)][0])).encode("ascii", "ignore").decode()).strip("_")
            asyncio.run(gerar(pdf_federal(nm, d, n), f"Comparativo_Jorge_x_{slug}_2026_capital"))


if __name__ == "__main__":
    main()
