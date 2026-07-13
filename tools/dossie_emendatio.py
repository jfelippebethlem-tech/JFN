#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dossiê consolidado — ONG Contato × Ambiente Jovem (SEAS) × Operação Emendatio.

Reúne: (a) mapa do dinheiro real (SIAFE/TFE local, OB=pagamento) da ONG Contato e da SOLAZER;
(b) estrutura de controle a qualquer tempo; (c) fatos confirmados da Operação Emendatio (fontes
citadas); (d) análise rigorosa do vínculo de Thiago Pampolha (institucional × parentesco não
provado). Indícios para apuração; presunção de legitimidade; nada fabricado. HTML→PDF Kroll.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB = REPO / "data" / "compliance.db"
CNPJ_ONG = "03686998000118"
CNPJ_SOL = "28008530000103"
_NORM = "REPLACE(REPLACE(REPLACE(favorecido_cpf,'.',''),'/',''),'-','')"


def _brl(v) -> str:
    return f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _ob_por_ug(con, cnpj):
    return con.execute(
        f"SELECT ug_codigo,MAX(ug_nome),COUNT(*),ROUND(SUM(valor),2),MIN(data_pagamento),MAX(data_pagamento) "
        f"FROM ordens_bancarias WHERE {_NORM}=? GROUP BY ug_codigo ORDER BY 4 DESC", (cnpj,)).fetchall()


def _ob_por_ano(con, cnpj):
    return con.execute(
        f"SELECT substr(data_pagamento,1,4),COUNT(*),ROUND(SUM(valor),2) FROM ordens_bancarias "
        f"WHERE {_NORM}=? AND length(data_pagamento)>=4 GROUP BY 1 ORDER BY 1", (cnpj,)).fetchall()


def _total(con, cnpj):
    return con.execute(f"SELECT COUNT(*),ROUND(SUM(valor),2) FROM ordens_bancarias WHERE {_NORM}=?",
                       (cnpj,)).fetchone()


def _secao_contratados() -> str:
    """Seção do cruzamento dos contratados (folha nominal pública × benefício/TSE/folha).
    Só entra se o cruzamento (data/ajovem_cruzamento.json) já estiver pronto."""
    fp = REPO / "data" / "ajovem_cruzamento.json"
    if not fp.exists():
        return ("<h2>Contratados do projeto — cruzamento (em processamento)</h2>"
                "<p class='pend'>A folha de pagamento nominal pública (~832 contratados com CPF) está "
                "sendo cruzada com benefício assistencial, candidaturas (TSE) e folhas estadual/ALERJ/"
                "municipal. Entra na próxima versão.</p>")
    d = json.load(open(fp))
    r = d["resumo"]
    ach = d["achados"]

    def linhas_cand():
        out = []
        for a in ach:
            if not a["candidaturas"]:
                continue
            cds = "; ".join(
                f"{c['ano']} {c['cargo']}/{c['municipio']} ({c['partido']})"
                + (" — ELEITO" if str(c.get('eleito')).lower() in ('1', 'true', 's', 'sim', 'eleito') else "")
                for c in a["candidaturas"])
            nasc = next((f"{c['mun_nasc']}/{c['uf_nasc']}" if c.get('mun_nasc') else c.get('uf_nasc', '')
                         for c in a["candidaturas"] if c.get('uf_nasc')), "")
            out.append(f"<tr><td>{a['nome']}</td><td>{a['funcao']}</td><td>{cds}</td><td>{nasc}</td></tr>")
        return "".join(out)

    # HONESTIDADE: só o match por CPF (forte) é achado; por nome = homônimo (nomes comuns casam com
    # dezenas de beneficiários distintos) → DESCARTADO, contado à parte como "a conferir".
    def _forte(a, chave):
        return [x for x in a[chave] if str(x.get("via", "")).startswith("CPF")]

    benef_forte = [a for a in ach if _forte(a, "beneficio")]
    nom_forte = [a for a in ach if _forte(a, "nomeacao")]
    n_benef_nome = sum(1 for a in ach if a["beneficio"] and not _forte(a, "beneficio"))
    n_nom_nome = sum(1 for a in ach if a["nomeacao"] and not _forte(a, "nomeacao"))

    def linhas_benef():
        out = []
        for a in benef_forte:
            bs = "; ".join(f"{b['programa']} ({b['de']}→{b['ate']}, {b['meses']}m)"
                           for b in _forte(a, "beneficio"))
            out.append(f"<tr><td><b>{a['nome']}</b></td><td>…{a['cpf_mask'][-4:]}</td><td>{a['funcao']}</td><td>{bs}</td></tr>")
        return "".join(out)

    cand_html = linhas_cand() or "<tr><td colspan='4' class='fonte'>Nenhum contratado com candidatura localizada no TSE.</td></tr>"
    benef_html = linhas_benef() or "<tr><td colspan='4' class='fonte'>Nenhum contratado com benefício confirmado por CPF.</td></tr>"
    return f"""
<h2>Contratados do projeto — cruzamento nominal (folha pública × candidaturas × benefício × outras folhas)</h2>
<p>Fonte: <b>folhas de pagamento mensais publicadas pela própria ONG</b> (dpto FECAM), nominais e com CPF.
Universo de <b>{r['total_contratados']} contratados distintos</b> (dedup. por CPF, fev/2022–abr/2024),
cruzado com candidaturas (TSE), benefício assistencial (fragmento de CPF) e folhas estadual (CPF
exato)/ALERJ/municipal (nome). <b>Regra de prova:</b> só o casamento por <b>CPF</b> é tratado como
achado; o casamento por <b>nome</b> é homônimo provável (nomes comuns coincidem com dezenas de
beneficiários distintos) e foi <b>descartado</b> — reportado apenas como massa "a conferir".</p>
<div class="kpis">
  <div class="kpi"><div class="n">{r['total_contratados']}</div><div class="l">contratados (folha pública, dedup. por CPF)</div></div>
  <div class="kpi"><div class="n">{len(benef_forte)}</div><div class="l">benefício confirmado por CPF (defensável)</div></div>
  <div class="kpi"><div class="n">{r['ja_candidatos']}</div><div class="l">já foram candidatos (TSE)</div></div>
  <div class="kpi"><div class="n">{len(nom_forte)}</div><div class="l">nomeação estadual confirmada por CPF</div></div>
  <div class="kpi"><div class="n">{n_benef_nome}+{n_nom_nome}</div><div class="l">matches só por nome (homônimo, descartados)</div></div>
</div>
<div class="callout warn"><div class="t">🚩 Exposição de dados (LGPD) pela própria OS</div>
Os <b>CPFs de todos os ~500 empregados</b> estão publicados na internet, sem tarja, nas folhas de
pagamento da ONG — fato reportável em si (art. 46 LGPD). Neste dossiê os CPFs são mascarados.</div>
<h3>Contratados que constam recebendo benefício assistencial (confirmado por CPF)</h3>
<p class="fonte">Match por fragmento de CPF + nome — defensável. Incompatibilidade de renda a verificar
(salário do projeto ~R$ 2,3 mil); Bolsa Família/BPC exigem baixa renda.</p>
<table><tr><th>Nome</th><th>CPF</th><th>Função</th><th>Benefício (trajetória)</th></tr>{benef_html}</table>
<h3>Contratados que já foram candidatos (TSE) — inclui naturalidade (origem)</h3>
<table><tr><th>Nome</th><th>Função no projeto</th><th>Candidatura(s)</th><th>Naturalidade</th></tr>{cand_html}</table>
<p class="fonte">Nota de honestidade: {n_benef_nome} contratados casaram com benefício e {n_nom_nome} com
folha ALERJ/municipal <b>apenas por nome</b> — não confirmados (homônimo provável), portanto não
elencados. A confirmação individual exige o CPF completo (requisição formal / Cadastro Único).</p>
"""


def _seas_obs(con):
    return con.execute(
        f"SELECT data_pagamento,numero_ob,valor FROM ordens_bancarias WHERE {_NORM}=? AND ug_codigo='240100' "
        f"ORDER BY data_pagamento", (CNPJ_ONG,)).fetchall()


def _secao_jose_ricardo() -> str:
    """Ficha do gestor José Ricardo Ferreira de Brito — o nó que liga os enredos, hoje na CEDAE."""
    return """
<h2>9. José Ricardo Ferreira de Brito — o gestor que atravessa os enredos</h2>
<p>É a figura que costura o caso: assina/gere nos <b>dois</b> programas das entidades de Raphael
Gonçalves (Esporte RJ→SOLAZER e Ambiente Jovem→Con-tato) e hoje ocupa uma diretoria na CEDAE, a
estatal do acordo de R$ 900 mi (seção 10). CPF 120.362.787-44.</p>
<table><tr><th>Período</th><th>Cargo</th><th>Órgão</th></tr>
<tr><td>2011–2013</td><td>Consultor especial</td><td>ALERJ</td></tr>
<tr><td>—</td><td>Presidente</td><td>SUDERJ (Superintendência de Desportos)</td></tr>
<tr><td>2017–2018</td><td>Chefe de Gabinete / depois Secretário</td><td>Esporte, Lazer e Juventude</td></tr>
<tr><td>—</td><td>Subsecretário Executivo</td><td>SEAS (Ambiente)</td></tr>
<tr><td><b>abr–dez/2022</b></td><td><b>Secretário do Ambiente INTERINO</b> (substituiu Pampolha na campanha)</td><td>SEAS</td></tr>
<tr><td><b>out/2025 →</b></td><td><b>Diretor de Saneamento e Grande Operação (DSG)</b></td><td>CEDAE</td></tr></table>
<div class="callout"><div class="t">Por que importa</div>
Foi <b>ex-subordinado direto de Pampolha</b> (não coincidência de pasta): assinou pela SEAS o Contrato
de Gestão 001/2021 do Ambiente Jovem e foi cobrado pelo TCE-RJ no caso "Esporte RJ" (Proc. 107.485-1/2016)
— <b>absolvido em 26/03/2025</b>. No CPF dele consta apenas a diretoria da CEDAE (QSA confirma); nenhuma
outra empresa nem sanção localizada. <b>Não</b> é citado na Operação Emendatio.</div>"""


# ── CEDAE — acordo R$ 900 mi (subagente, imprensa nomeada; nº do processo TCE a confirmar) ────
_CEDAE_TIMELINE = [
    ("03/10/2025", "Termo de Conciliação assinado (Estado/CEDAE/Agenersa/Águas do Rio 1 e 4 SPE), em reunião emergencial noturna"),
    ("06/10/2025", "Castro envia ofício indicando José Ricardo Ferreira de Brito à diretoria da CEDAE (3 dias após o acordo)"),
    ("~15/10/2025", "Cons. José Gomes Graciosa SUSPENDE o acordo (liminar), por denúncia dos dep. Luiz Paulo e Jari Oliveira"),
    ("16/10/2025", "MPRJ abre inquérito civil (lesão ao erário / governança)"),
    ("12/11/2025", "Pampolha (revisor) abre divergência p/ derrubar a liminar → empate 3×3"),
    ("26/11/2025", "Julgamento encerra 4×3 pela liberação (voto de minerva do presidente Pacheco); no MESMO dia a CEDAE cria a Diretoria de Sustentabilidade e nomeia Philipe Campello"),
]


def _secao_cedae() -> str:
    tl = "".join(f"<tr><td>{d}</td><td>{e}</td></tr>" for d, e in _CEDAE_TIMELINE)
    return f"""
<h2>10. CEDAE — o acordo de R$ 900 milhões (Águas do Rio) e as diretorias</h2>
<p>Instrumento: <b>Termo de Conciliação de 03/10/2025</b> entre Estado, CEDAE, Agenersa e a
concessionária <b>Águas do Rio 1 e 4 SPE S.A.</b> (grupo Aegea). Não é pagamento direto: é um
<b>desconto de 24,13%</b> no valor da água que a CEDAE vende à concessionária <b>até 2056</b>, somando
<b>~R$ 900 milhões</b> (podendo chegar a ~R$ 1,4 bi). Justificativa: divergência entre os índices de
cobertura de esgoto do edital de 2021 e a realidade, constatada ao pagar a outorga final em dez/2024.</p>
<table><tr><th>Data</th><th>Evento</th></tr>{tl}</table>
<div class="callout"><div class="t">🚩 Achado de governança — o Termo NÃO foi deliberado pelo Conselho de Administração</div>
Fato confirmado (não ausência de pesquisa): o Termo de Conciliação de 03/10/2025 <b>não passou por
deliberação do Conselho de Administração da CEDAE</b>. A própria <b>suspensão do TCE-RJ (14/10/2025,
Cons. Graciosa)</b> apontou como vício a "<b>inexistência de deliberação do Conselho de Administração
da Cedae</b>", além da falta de parecer jurídico prévio, estudo técnico e manifestação da PGE. Nas atas
do CA o tema só aparece <b>a posteriori</b> (Ata 828ª, 21/10/2025, como relato). A íntegra das atas
consta do Anexo C.</div>
<div class="callout"><div class="t">Os atos das nomeações (fonte primária — atas do CA)</div>
<b>José Ricardo Ferreira de Brito (DSG):</b> eleito na <b>827ª Reunião do CA, 10/10/2025</b> (Ofício GG
nº 207/2025 de Castro, 06/10/2025 — em substituição a Daniel Okumura); posse 13/10/2025; processo
SEI-150001/013307/2025. <b>Philipe Campello (DSU):</b> eleito na <b>833ª Reunião, 26/11/2025</b> (Ofício
GG nº 223/2025, 19/11/2025); a <b>Diretoria de Sustentabilidade foi criada por AGE de 26/11/2025</b>
(alteração estatutária proposta em 21/10). Publicação: <b>DOERJ nº 227, Parte V, 10/12/2025, p. 1</b>;
registro JUCERJA 00007336076.</div>
<div class="callout"><div class="t">🚩 O eixo de risco (quid pro quo EM TESE)</div>
Pampolha — hoje conselheiro do TCE-RJ, indicado pelo governador Cláudio Castro — deu o <b>voto de
divergência decisivo</b> que liberou o acordo (4×3), enquanto <b>dois de seus ex-auxiliares na SEAS</b>
(José Ricardo Ferreira de Brito, DSG; e Philipe Campello, ex-presidente do INEA, Sustentabilidade) eram
nomeados diretores da <b>mesma estatal</b> que arca com a conta. <b>Composição do voto (26/11/2025):</b>
a favor de derrubar a liminar — Pampolha, Marcelo Verdini Maia, Andreia Siqueira Martins e o presidente
Márcio Pacheco (minerva); contra — José Gomes Graciosa (relator), Marianna Montebello Willeman e Rodrigo
Melo do Nascimento. O <b>MPRJ</b> instaurou inquérito civil (2ª Promotoria de Tutela Coletiva do
Patrimônio Público da Capital, promotor Alberto Flores Camargo, 15/10/2025).</div>
<div class="callout warn"><div class="t">🔒 O processo do acordo está sob ACESSO RESTRITO no TCE-RJ</div>
A consulta pública do TCE-RJ, para o interessado "Águas do Rio", devolve apenas "processos internos que
não estão autorizados para consulta pública" — <b>não há número nem PDF públicos</b> do voto/acórdão
(por isso a imprensa não os divulga). Obter a íntegra exige acesso interno (SEI) ou requerimento formal
(LAI) ao TCE — ao contrário do processo do Esporte RJ (Anexo B), que é público. <b>Desdobramentos:</b>
em 01/03/2026 a 9ª Câmara do TJRJ restabeleceu liminar mantendo o desconto; em jul/2026 a nova direção
da CEDAE passou a tentar <b>anular</b> o desconto de 24,13%, alegando prejuízo de até R$ 25 bilhões.</div>
<div class="callout info"><div class="t">Ressalvas de rigor</div>
<b>Não</b> é fato provado — é materialidade para representação, com inquérito do MPRJ em curso. Pampolha
<b>não</b> assinou a concessão de 2021 (à época era Secretário do Ambiente; só virou vice em 2023) —
o conflito apontado é o <b>atual</b>. Não há registro de que ele tenha se declarado impedido; a CPI na
ALERJ foi anunciada, não instaurada. Números do processo no TCE e atos do DOERJ das nomeações: a
confirmar em fonte primária.</div>"""


def _secao_inea_seas(con) -> str:
    """Maiores contratos de INEA/SEAS na gestão Pampolha (dado primário TFE) + achado de método."""
    norm = "REPLACE(REPLACE(REPLACE(favorecido_cpf,'.',''),'/',''),'-','')"
    tops = con.execute(
        f"SELECT MAX(favorecido_nome), ug_codigo, COUNT(*), ROUND(SUM(valor),2) FROM ordens_bancarias "
        f"WHERE ug_codigo IN ('240100','240200','243200') AND substr(data_pagamento,1,4) BETWEEN '2020' "
        f"AND '2024' AND length({norm})=14 GROUP BY {norm},ug_codigo ORDER BY 4 DESC LIMIT 15", ()).fetchall()
    _UGN = {"240100": "SEAS", "240200": "SEAS-PSAM", "243200": "INEA"}
    linhas = "".join(
        f"<tr><td>{(r[0] or '')[:42]}</td><td>{_UGN.get(r[1], r[1])}</td><td class='num'>{r[2]}</td>"
        f"<td class='num'>R$ {_brl(r[3])}</td></tr>" for r in tops if (r[0] or "") != "FOLHA DE PAGAMENTOS")
    return f"""
<h2>11. INEA e SEAS na gestão Pampolha — maiores contratos (2020–2024)</h2>
<p>Pagamentos efetivos (OB) das UGs ambientais — Secretaria do Ambiente (240100), SEAS-PSAM (240200,
saneamento da Baía de Guanabara) e INEA (243200) — na gestão de Pampolha. Maiores credores:</p>
<table><tr><th>Credor</th><th>UG</th><th>OBs</th><th>Total pago</th></tr>{linhas}</table>
<div class="callout warn"><div class="t">🚩 Idoneidade — a maior credora do INEA está impedida</div>
A <b>Construtora Lytoranea</b> (~R$ 202 mi do INEA em macrodrenagem) consta com <b>impedimento/proibição
de contratar</b> (sanção federal — Fundação Oswaldo Cruz, jun–ago/2026). Idoneidade atual comprometida.</div>
<div class="callout info"><div class="t">Achado de método (importante)</div>
As <b>grandes obras de INEA/SEAS foram por LICITAÇÃO</b> (critério Menor Preço, Lei 8.666) — as
macro-obras de drenagem e saneamento passaram por concorrência. A <b>dispensa/inexigibilidade</b>, foco
de risco, concentra-se na <b>rota de OS / contrato de gestão</b> (Ambiente Jovem R$ 96 mi; Ceperj "Mais
Acesso" R$ 26 mi) — é ali a contratação direta, não nas obras. <b>Recorrentes</b> nas duas pastas
ambientais (sinal a aprofundar): Hydra Engenharia (R$ 89,9 mi), Construtora Brasform (R$ 74,3 mi) e
Trial Ambiental (R$ 37,6 mi).</div>"""


# ── parlamentares (subagente A, fonte A Tribuna RJ) ──────────────────────────────────
_DEP_FED = ["Carlos Jordy (PL)", "Chiquinho Brazão", "Hugo Leal (PSD)", "Jorge Braz (Republicanos)",
            "Laura Carneiro (PSD)", "Luiz Antônio Corrêa (PP)", "Otoni de Paula (MDB)",
            "Sóstenes Cavalcante (PL)"]
_EX_DEP = ["Clarissa Garotinho", "João Carlos Soares Rangel", "Pedro Augusto", "Ricardo da Karol",
           "Roberto Sales", "Wladmir Garotinho"]

# ── contrato de gestão (subagente B, OCR dos instrumentos originais da própria contratada) ────
_ADITIVOS = [
    ("Contrato de Gestão nº 001/2021", "30/12/2021", "Parceria — Projeto Ambiente Jovem (Anexo I: cronograma de desembolso)", "R$ 42.043.393,00", "R$ 42.043.393,00", "12 meses"),
    ("1º Termo Aditivo", "07/03/2022", "Altera Proposta de Trabalho; cria 100 cargos de auxiliar de integração comunitária", "sem alteração de valor", "R$ 42.043.393,00", "12 meses"),
    ("2º Termo Aditivo", "15/08/2022", "Alteração qualitativa/quantitativa; +25 NUPs; troca de oficinas", "+R$ 10.464.600,52 (+24,89%)", "R$ 52.507.993,52", "→ 16 meses"),
    ("3º Termo Aditivo", "23/04/2023", "Prorrogação de prazo", "sem alteração de valor", "R$ 52.507.993,52", "→ 17m 15d"),
    ("4º Termo Aditivo", "15/06/2023", "Prorrogação; cria Fundo de Reserva; cláusula de reajuste", "+R$ 43.303.737,21", "R$ 95.811.723,88", "→ 29m 15d"),
]
# municípios cobertos (roster de alunos Anos 01–02, subagente B)
_MUNICIPIOS = ("Angra dos Reis, Araruama, Areal, Armação dos Búzios, Arraial do Cabo, Barra do Piraí, "
    "Belford Roxo, Bom Jesus do Itabapoana, Cabo Frio, Cachoeiras de Macacu, Cambuci, Campos dos "
    "Goytacazes, Cantagalo, Carapebus, Cardoso Moreira, Carmo, Casimiro de Abreu, Comendador Levy "
    "Gasparian, Conceição de Macabu, Cordeiro, Duque de Caxias, Engenheiro Paulo de Frontin, "
    "Guapimirim, Iguaba Grande, Itaguaí, Italva, Itaocara, Itaperuna, Itatiaia, Japeri, Macaé, Macuco, "
    "Magé, Maricá, Mendes, Mesquita, Miguel Pereira, Miracema, Nilópolis, Nova Friburgo, Nova Iguaçu, "
    "Paracambi, Paraíba do Sul, Paraty, Paty do Alferes, Petrópolis, Piraí, Porto Real, Quatis, "
    "Queimados, Quissamã, Resende, Rio Bonito, Rio Claro, Rio das Ostras, Rio de Janeiro, Santo "
    "Antônio de Pádua, São Fidélis, São Gonçalo, São João da Barra, São João de Meriti, São José de "
    "Ubá, São Pedro da Aldeia, Sapucaia, Saquarema, Seropédica, Silva Jardim, Tanguá, Teresópolis, "
    "Trajano de Moraes, Três Rios, Valença, Volta Redonda")

_CSS = """
@page { size:A4; margin:15mm 12mm; }
body { font-family:Georgia,'Times New Roman',serif; color:#1a1a1a; font-size:10.5px; line-height:1.55; }
.capa { border-bottom:4px double #7a1f1f; padding-bottom:14px; margin-bottom:16px; }
.classif { color:#7a1f1f; font-weight:700; letter-spacing:2px; font-size:9.5px; font-family:'Helvetica Neue',Arial,sans-serif; }
h1 { font-size:23px; color:#2b0d0d; margin:8px 0 4px; letter-spacing:.2px; }
.sub { color:#555; font-size:10px; }
h2 { font-size:14.5px; color:#7a1f1f; border-bottom:1.5px solid #e0d3d3; padding-bottom:4px; margin-top:22px; page-break-after:avoid; }
h3 { font-size:11.5px; color:#3a1010; margin:13px 0 3px; background:#f5eded; padding:4px 9px; border-left:3px solid #7a1f1f; page-break-after:avoid; }
table { width:100%; border-collapse:collapse; font-size:9.2px; margin:6px 0 12px; font-family:'Helvetica Neue',Arial,sans-serif; }
th,td { text-align:left; padding:4px 7px; border-bottom:1px solid #eee; vertical-align:top; }
th { background:#7a1f1f; color:#fff; font-weight:600; } tr:nth-child(even) td { background:#f9f4f4; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
.callout { border:1px solid #e0c9c9; border-left:4px solid #b71c1c; background:#fdf5f5; border-radius:6px; padding:10px 14px; margin:12px 0; page-break-inside:avoid; }
.callout.warn { border-left-color:#a06a00; background:#fffaf0; }
.callout.info { border-left-color:#1f4e79; background:#f4f8fc; }
.callout .t { font-weight:700; color:#7a1f1f; font-family:'Helvetica Neue',Arial,sans-serif; font-size:10px; margin-bottom:3px; }
.kpis { display:flex; gap:9px; margin:12px 0; flex-wrap:wrap; }
.kpi { border:1px solid #e2d5d5; border-radius:8px; padding:9px 13px; background:#fbf7f7; min-width:120px; }
.kpi .n { font-size:19px; font-weight:700; color:#7a1f1f; line-height:1; font-family:'Helvetica Neue',Arial,sans-serif; }
.kpi .l { font-size:8px; color:#666; margin-top:3px; font-family:'Helvetica Neue',Arial,sans-serif; }
.tag { padding:1px 6px; border-radius:3px; font-size:8.5px; font-weight:700; font-family:'Helvetica Neue',Arial,sans-serif; }
.conf { background:#e6f4ea; color:#1b5e20; } .ind { background:#fff8e1; color:#a06a00; } .nao { background:#fdecea; color:#c62828; }
ul { margin:4px 0 10px; padding-left:20px; } li { margin:2px 0; }
.indice { margin:2px 0 4px; }
.indice .it { font-size:15px; font-weight:700; color:#7a1f1f; letter-spacing:1px; font-family:'Helvetica Neue',Arial,sans-serif; border-bottom:2px solid #7a1f1f; padding-bottom:3px; margin-bottom:6px; }
.indice .ihint { font-size:8.5px; color:#777; font-style:italic; margin-bottom:8px; }
.indice .i1 { font-size:10.5px; margin:3px 0 1px; font-family:'Helvetica Neue',Arial,sans-serif; }
.indice .i1 a { color:#2b0d0d; font-weight:700; text-decoration:none; }
.indice .i2 { font-size:9px; margin:1px 0 1px 22px; font-family:'Helvetica Neue',Arial,sans-serif; }
.indice .i2 a { color:#555; text-decoration:none; }
.indice a:hover { text-decoration:underline; }
.fonte { font-size:8px; color:#888; }
.pend { border:1px dashed #b98; background:#fbf8f4; border-radius:6px; padding:9px 13px; margin:8px 0; font-size:9.5px; }
footer { margin-top:20px; border-top:1px solid #ddd; padding-top:7px; font-size:8px; color:#888; }
"""


def build_html() -> str:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ong_ug, ong_ano, ong_tot = _ob_por_ug(con, CNPJ_ONG), _ob_por_ano(con, CNPJ_ONG), _total(con, CNPJ_ONG)
    sol_ug, sol_tot = _ob_por_ug(con, CNPJ_SOL), _total(con, CNPJ_SOL)
    seas = _seas_obs(con)
    inea_seas_html = _secao_inea_seas(con)   # precisa do con aberto — computa antes do close
    con.close()
    hoje = datetime.now().strftime("%d/%m/%Y")
    seas_tot = sum(r[2] for r in seas)

    def linhas_ug(rows):
        return "".join(
            f"<tr><td>{r[0]}</td><td>{(r[1] or '')[:52]}</td><td class='num'>{r[2]}</td>"
            f"<td class='num'>R$ {_brl(r[3])}</td><td>{r[4]}→{r[5]}</td></tr>" for r in rows)

    ong_ug_html = linhas_ug(ong_ug)
    sol_ug_html = linhas_ug(sol_ug)
    ong_ano_html = "".join(
        f"<tr><td>{r[0]}</td><td class='num'>{r[1]}</td><td class='num'>R$ {_brl(r[2])}</td></tr>" for r in ong_ano)
    seas_html = "".join(
        f"<tr><td>{r[0]}</td><td>{r[1]}</td><td class='num'>R$ {_brl(r[2])}</td></tr>" for r in seas)
    dep_html = "".join(f"<li>{d}</li>" for d in _DEP_FED)
    exdep_html = "".join(f"<li>{d}</li>" for d in _EX_DEP)

    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>{_CSS}</style></head><body>
<div class="capa">
  <div class="classif">CONFIDENCIAL — SUBSÍDIO PARA APURAÇÃO / CONTROLE EXTERNO</div>
  <h1>Pente-fino — ONG Con-tato, Projeto Ambiente Jovem (SEAS) e a Operação Emendatio</h1>
  <div class="sub">Emitido em {hoje} · Fiscalização de controle externo · Fontes: SIAFE/TFE-RJ (pagamentos),
  Receita Federal (QSA), imprensa e órgãos oficiais (fatos da operação, com URL). OB = pagamento
  efetivo — empenho não entra. Indícios para apuração; presunção de legitimidade dos atos.</div>
</div>

<div class="kpis">
  <div class="kpi"><div class="n">R$ {_brl(ong_tot[1])}</div><div class="l">pago pelo Estado à ONG Con-tato ({ong_tot[0]} OBs)</div></div>
  <div class="kpi"><div class="n">R$ {_brl(seas_tot)}</div><div class="l">só da SEAS (240100), 2022–2024</div></div>
  <div class="kpi"><div class="n">R$ {_brl(sol_tot[1])}</div><div class="l">pago à SOLAZER (mesmo dono de fato)</div></div>
  <div class="kpi"><div class="n">R$ 96 mi</div><div class="l">contrato de gestão SEAS após aditivos (imprensa)</div></div>
  <div class="kpi"><div class="n">R$ 100 mi</div><div class="l">bloqueio patrimonial — STF</div></div>
  <div class="kpi"><div class="n">09/07/2026</div><div class="l">deflagração da Operação Emendatio (PF)</div></div>
</div>

<h2>Sumário executivo</h2>
<p>A <b>ONG Con-tato</b> (Centro de Pesquisas e de Ações Sociais e Culturais — CNPJ 03.686.998/0001-18)
recebeu do Estado do Rio, em pagamentos efetivos (Ordens Bancárias), <b>R$ {_brl(ong_tot[1])}</b> em {ong_tot[0]} OBs,
dos quais <b>R$ {_brl(seas_tot)}</b> pela Secretaria de Estado do Ambiente e Sustentabilidade (SEAS) entre 2022 e 2024 —
janela do contrato de gestão do <b>Projeto Ambiente Jovem</b>. Em 09/07/2026 a Polícia Federal deflagrou a
<b>Operação Emendatio</b>, que apura desvio de emendas parlamentares por meio de organizações sociais;
<b>Raphael da Silva Gonçalves</b>, apontado como o operador de fato da ONG e ex-assessor do conselheiro do
TCE-RJ Domingos Brazão, foi preso. O STF (min. Alexandre de Moraes) determinou bloqueio de R$ 100 milhões.
Este dossiê consolida o <b>mapa do dinheiro</b> (dado primário do SIAFE), a <b>estrutura de controle da ONG
a qualquer tempo</b>, um <b>segundo veículo</b> ligado ao mesmo operador (SOLAZER), os <b>fatos confirmados
da operação</b> e uma <b>análise rigorosa e reservada</b> do vínculo do vice-governador Thiago Pampolha —
que, até aqui, é <b>institucional</b>, não havendo fonte que o aponte como investigado nem que comprove
parentesco com os Gonçalves.</p>

<h2>1. Mapa do dinheiro — ONG Con-tato (dado primário, SIAFE/TFE)</h2>
<p>Pagamentos efetivos por órgão pagador. Só Ordem Bancária conta como pagamento (empenho e liquidação não).</p>
<table><tr><th>UG</th><th>Órgão pagador</th><th>OBs</th><th>Total pago</th><th>Período</th></tr>{ong_ug_html}
<tr><td colspan="2"><b>TOTAL</b></td><td class="num"><b>{ong_tot[0]}</b></td><td class="num"><b>R$ {_brl(ong_tot[1])}</b></td><td></td></tr></table>
<h3>Evolução anual</h3>
<table><tr><th>Ano</th><th>OBs</th><th>Total pago</th></tr>{ong_ano_html}</table>

<h2>2. O contrato de gestão do Ambiente Jovem (SEAS) — instrumento, aditivos e signatários</h2>
<p>Instrumento único: <b>Contrato de Gestão nº 001/2021</b>, processo administrativo
<b>SEI-070026/000705/2021</b> (unidade SEAS), originado do <b>Chamamento Público nº 002/2021</b>.
Base legal: Lei Estadual 6.470/2013 (OS ambiental) e Decreto 45.792/2016. Fonte de recurso:
<b>FECAM — Fonte 151</b> (Fundo Estadual de Conservação Ambiental). Dados lidos nos instrumentos
originais publicados pela própria contratada (OCR).</p>
<div class="callout"><div class="t">🚩 Qualificação, chamamento e assinatura em 24 horas</div>
A OS foi qualificada por ato publicado no <b>DOERJ de 10/12/2021</b>; a sessão pública do chamamento
ocorreu em <b>29/12/2021</b> e o contrato foi assinado <b>no dia seguinte, 30/12/2021</b> — janela de
um dia entre seleção e assinatura, ao apagar do exercício. Houve chamamento (não foi dispensa), mas a
celeridade e o encerramento de ano são pontos a examinar na regularidade do certame.</div>
<table><tr><th>Instrumento</th><th>Assinatura</th><th>Objeto</th><th>Valor do ato</th><th>Acumulado</th><th>Prazo</th></tr>
{"".join(f"<tr><td>{a[0]}</td><td>{a[1]}</td><td>{a[2]}</td><td class='num'>{a[3]}</td><td class='num'>{a[4]}</td><td>{a[5]}</td></tr>" for a in _ADITIVOS)}</table>
<div class="callout warn"><div class="t">🚩 Valor contratado × valor efetivamente pago</div>
Valor final do contrato após aditivos: <b>R$ 95.811.723,88</b>. Pagamentos efetivos rastreados no
SIAFE pela SEAS: <b>R$ {_brl(seas_tot)}</b> — diferença de ~R$ {_brl(95811723.88 - seas_tot)} entre o
contratado e o pago pela pasta (a conferir na prestação de contas: saldo não pago, glosa, ou execução
por outra fonte/UG). Registre-se ainda divergência de <b>R$ 6,85</b> entre o total do 2º TA e a base
declarada no 4º TA — a reconciliar.</div>
<h3>Signatários dos instrumentos (leitura das páginas de assinatura)</h3>
<table><tr><th>Pela SEAS (contratante)</th><th>Pela ONG Con-tato (contratada)</th></tr>
<tr><td><b>José Ricardo Ferreira de Brito</b> — Subsecretário Executivo / depois Secretário de Estado (CPF 120.362.787-44)</td>
<td><b>Cíntia Gonçalves Duarte</b> — Presidente (CPF 056.664.877-60). Diretor Financeiro (prest. contas 2º TA): Arilton Fernandes</td></tr></table>
<h3>Pagamentos efetivos da SEAS (SIAFE, UG 240100) — gestão Pampolha</h3>
<table><tr><th>Data de pagamento</th><th>Nº OB</th><th>Valor</th></tr>{seas_html}
<tr><td colspan="2"><b>TOTAL SEAS</b></td><td class="num"><b>R$ {_brl(seas_tot)}</b></td></tr></table>

<h2>3. Estrutura de controle da ONG — a qualquer tempo</h2>
<table><tr><th>Pessoa</th><th>Papel</th><th>Período / sinal</th></tr>
<tr><td><b>Cíntia Gonçalves Duarte</b></td><td>Presidente</td><td>02/05/2019–02/05/2023 — janela dos R$ {_brl(seas_tot)} da SEAS</td></tr>
<tr><td><b>Tathyane Ferreira Höfke</b></td><td>Diretoria Executiva (QSA atual)</td><td>ingresso no QSA em 14/05/2025</td></tr>
<tr><td><b>Raphael da Silva Gonçalves</b></td><td>Operador de fato (imprensa); marido de Cíntia</td><td>preso na Emendatio, 09/07/2026</td></tr></table>
<div class="callout warn"><div class="t">🚩 Troca de controle após o grosso dos pagamentos</div>
O ingresso da atual dirigente no quadro societário público (14/05/2025) é <b>posterior</b> a R$ 148,7 milhões
já pagos à ONG (≈71% do total) — sinal de sucessão/reorganização societária a verificar, coincidente com o
avanço das investigações.</div>

<h2>4. Segundo veículo do mesmo operador — SOLAZER O Clube dos Excepcionais</h2>
<p><b>Raphael da Silva Gonçalves</b> também é <b>presidente</b> da <b>SOLAZER O Clube dos Excepcionais</b>
(CNPJ 28.008.530/0001-03), que recebeu do Estado <b>R$ {_brl(sol_tot[1])}</b> em {sol_tot[0]} OBs:</p>
<table><tr><th>UG</th><th>Órgão pagador</th><th>OBs</th><th>Total pago</th><th>Período</th></tr>{sol_ug_html}</table>
<p>Somados os dois veículos ligados ao mesmo operador de fato, o volume de recursos públicos estaduais
alcança <b>R$ {_brl((ong_tot[1] or 0) + (sol_tot[1] or 0))}</b> (na base local, 2019+). Ambas as entidades foram
alimentadas, entre outras fontes, pelo <b>Fundo Estadual de Assistência Social</b> (UG 326100).</p>
<div class="callout"><div class="t">🚩 A SOLAZER já foi condenada a devolver dinheiro — caso "Esporte RJ" (TCE-RJ)</div>
Muito antes do Ambiente Jovem, a SOLAZER foi <b>Organização Social do programa "Esporte RJ"</b> da
Secretaria de Esporte/SUDERJ, pelo <b>Contrato de Gestão nº 002/2015</b> (Lote 1), no valor de
<b>R$ 22.407.351,78</b> — do qual recebeu <b>R$ 20.351.788,20</b> até 2018. O TCE-RJ (Processo
<b>nº 107.485-1/2016</b>) auditou e apontou <b>dano ao erário de ~R$ 21 milhões</b>: dos 31 núcleos
visitados em 2018, só 5 tinham atividade; prestações de contas com fotos/relatórios repetidos. A OS
ECOS (Processo 107.484-7/16) recebeu R$ 3.949.760,54 no mesmo programa. O contrato 002/2015 foi
assinado pelo então Chefe de Gabinete <b>Bernardo Roberto Cardoso Pinto</b>. <span class="fonte">A
íntegra dos autos do TCE consta do Anexo B.</span></div>

<h2>5. Operação Emendatio (PF, 09/07/2026) — fatos confirmados por fonte</h2>
<h3>Presos e investigados</h3>
<table><tr><th>Nome</th><th>Papel apontado</th><th>Situação</th></tr>
<tr><td>Raphael da Silva Gonçalves</td><td>Ex-assessor de Domingos Brazão (TCE-RJ); operava a ONG Con-tato; denunciado pelo MP por fraude a licitações</td><td>Preso (09/07/2026)</td></tr>
<tr><td>Robson Calixto Fonseca ("Peixe")</td><td>PM reformado; homem de confiança de Domingos Brazão; condenado no caso Marielle</td><td>Preso</td></tr>
<tr><td>Chiquinho Brazão</td><td>Ex-deputado federal cassado; mandante no caso Marielle; usuário apontado do esquema</td><td>Busca e apreensão; já preso (Marielle)</td></tr>
<tr><td>Domingos Brazão</td><td>Conselheiro do TCE-RJ; irmão de Chiquinho; mandante no caso Marielle</td><td>Investigado; já preso (Marielle)</td></tr>
<tr><td>Cíntia Gonçalves Duarte</td><td>Presidente da ONG Con-tato; esposa de Raphael</td><td>Citada; sem relato de prisão</td></tr>
<tr><td>Pedro Augusto</td><td>Ex-deputado federal; usuário apontado da ONG</td><td>Investigado (contexto)</td></tr></table>
<p><b>Números da operação:</b> 2 prisões preventivas, 21 buscas e apreensões, ~60 policiais federais,
<b>bloqueio de R$ 100 milhões</b> (STF, min. Alexandre de Moraes). Crimes apurados: <b>peculato, lavagem de
dinheiro e organização criminosa</b>. É desdobramento de apuração iniciada em 2024 sobre a ONG Con-tato.</p>
<h3>Volume financeiro apontado (imprensa)</h3>
<table><tr><th>Item</th><th>Valor</th><th>Observação</th></tr>
<tr><td>33 emendas parlamentares</td><td class="num">~R$ 137 mi</td><td>desde 2019</td></tr>
<tr><td>Contrato SEAS — Ambiente Jovem</td><td class="num">R$ 42→52→~96 mi</td><td>30/12/2021, sem licitação</td></tr>
<tr><td>Contrato Fundação Ceperj — "Mais Acesso"</td><td class="num">~R$ 26 mi</td><td>—</td></tr>
<tr><td>Prefeitura do Rio</td><td class="num">~R$ 120 mi</td><td>licitação cancelada em maio/2024</td></tr></table>
<h3>Parlamentares que destinaram emendas à ONG (rastreabilidade orçamentária)</h3>
<p class="fonte">A citação como autor de emenda é dado de rastreabilidade, não imputação de crime.</p>
<table><tr><th>Deputados federais</th><th>Ex-deputados federais</th></tr>
<tr><td><ul>{dep_html}</ul></td><td><ul>{exdep_html}</ul></td></tr></table>
<h3>Modus operandi apontado pela PF</h3>
<p>Desvio de recursos de emendas destinadas a entidades sem fins lucrativos por meio de <b>pagamentos
indevidos, empresas interpostas (de fachada), superfaturamento e inexecução</b>, com mecanismos para ocultar
origem e destino dos valores, supostamente retornando à família Brazão e a Pedro Augusto. A ONG negou os
fatos e afirmou que o relatório da PF "não aponta nem atribui a ela" desvio.</p>

<h2>6. Thiago Pampolha — análise rigorosa e reservada</h2>
<div class="callout info"><div class="t">Conclusão da verificação (com o desfecho do TCE)</div>
<span class="tag conf">VÍNCULO INSTITUCIONAL — CONFIRMADO</span> Thiago Pampolha Gonçalves chefiou
<b>duas</b> pastas que contrataram as entidades de Raphael Gonçalves: <b>Secretaria de Esporte, Lazer e
Juventude</b> (2017–2018 — programa "Esporte RJ", OS SOLAZER/ECOS) e <b>Secretaria do Ambiente/SEAS</b>
(2020–2024 — Ambiente Jovem, ONG Con-tato). É apontado como idealizador do Ambiente Jovem, celebrado sem
licitação em 30/12/2021.
<br><br>
<span class="tag conf">TCE — ABSOLVIDO (2025)</span> No caso "Esporte RJ", o TCE-RJ havia <b>cobrado</b>
Pampolha em 2019 (ao lado de Marco Antônio Neves Cabral, José Ricardo Ferreira de Brito, do ordenador
Francisco Harilton Alves Bandeira e da diretora Lenise Monteiro Nunes Mendonça). Mas em
<b>26/03/2025 o Plenário do TCE-RJ, por unanimidade, AFASTOU a responsabilidade de Pampolha e de Brito</b>
(comprovado que não praticaram atos que contribuíssem para as irregularidades). A apuração <b>prossegue</b>
contra Cabral, os servidores e as OS. <b>É correção relevante: Pampolha foi absolvido nesse processo.</b>
<br><br>
<span class="tag nao">EMENDATIO / PARENTESCO — NÃO</span> <b>Nenhuma</b> cobertura da Operação Emendatio o
cita como investigado, e <b>nenhuma fonte</b> afirma parentesco entre ele e Raphael/Cíntia Gonçalves — o
sobrenome "Gonçalves" não é evidência de vínculo familiar. Este dossiê não afirma parentesco.</div>
<p><b>Leitura de fiscalização (honesta):</b> o que é fato é um <b>padrão institucional</b> — as pastas
chefiadas por Pampolha contrataram, em dois momentos, entidades do mesmo operador (SOLAZER e Con-tato),
e o gestor <b>José Ricardo Ferreira de Brito</b> aparece nos dois enredos (cobrado no Esporte RJ e
signatário do Ambiente Jovem). Isso justifica acompanhamento, mas <b>não</b> equivale a imputação: no
único processo de contas já julgado (Esporte RJ), Pampolha foi <b>absolvido</b>. Registre-se, sem
imputação, que ele tomou posse como <b>conselheiro do TCE-RJ em 21/05/2025</b>.</p>

<h2>7. Núcleos de Pertencimento (NUPs) — onde o projeto foi executado</h2>
<p>Fonte oficial: relação de NUPs (com endereço e data de inauguração) e relação de alunos por
município, publicadas pela contratada. <b>141 NUPs</b> inaugurados entre abr/2022 e out/2022,
cobrindo <b>~73 municípios</b> do Estado do Rio. Relação de alunos: <b>Ano 01 — 5.663 alunos</b>;
<b>Ano 02 — 5.320 alunos</b> (a imprensa citou "~2.600", recorte de fase; a meta institucional era
12.500 jovens).</p>
<div class="callout info"><div class="t">Maior concentração de alunos (Ano 01 / Ano 02)</div>
Rio de Janeiro (1.673 / 1.963) · Campos dos Goytacazes (567 / 89) · Belford Roxo (485 / 91) ·
Nova Iguaçu (349 / 177) · São José de Ubá (165 / 0) · São Gonçalo (139 / 87).</div>
<p><b>Municípios cobertos (roster Anos 01–02):</b> {_MUNICIPIOS}.</p>
<p><b>NUPs na capital (amostra):</b> Complexo do Alemão, Bangu/Vila Aliança/Vila Kennedy/Senador
Camará, Manguinhos, Jacarezinho, Muzema, Rio das Pedras/Itanhangá, Praça Seca/Chacrinha, Campinho,
Cosmos, Paciência, Padre Miguel, Magalhães Bastos, Realengo, Santa Cruz, Sepetiba, Campo Grande,
Serrinha, Borel (Tijuca), Freguesia, Lins, Parque União (Maré), Pavuna, Turano, Vargem Grande/Taquara.
Belford Roxo concentra 10 NUPs; Campos ~13. <span class="fonte">Lista completa nível-endereço (141
linhas) no material de trabalho — anexável.</span></p>

<h2>8. FECAM (Fonte 151) — a origem do dinheiro sob escrutínio</h2>
<div class="callout warn"><div class="t">🚩 Fundo custeador já notificado pelo MPRJ</div>
O contrato é custeado pelo <b>FECAM — Fundo Estadual de Conservação Ambiental e Desenvolvimento
Urbano</b> (Fonte 151; Programa de Trabalho 2401.18.541.0438.5645; Natureza 4490.39). Em julho/2025 o
<b>GAEMA/MPRJ notificou a SEAS</b> por medidas de transparência na gestão do FECAM — o que reforça a
relevância de fiscalizar este contrato de gestão, o maior custeado pela fonte no período.</div>

{_secao_contratados()}

{_secao_jose_ricardo()}

{_secao_cedae()}

{inea_seas_html}

<h2>12. Repasses de 2017–2018 e o bloqueio do SIAFE-1</h2>
<div class="callout warn"><div class="t">🚩 SIAFE-1 não liberado para nós em 2017–2018 (INDISPONÍVEL ≠ zero)</div>
A base SIAFE-1 (2016–2023) só expõe, para a nossa conta, a UG da <b>ALERJ (010100)</b> nos exercícios
de 2016 a 2020 — as demais UGs (Secretaria de Esporte 170100, SUDERJ 173100) só aparecem a partir de
2021. Logo, os pagamentos estaduais de 2017–2018 <b>não são acessíveis</b> por essa via com o acesso
atual; obtê-los exige <b>liberação do exercício pelo administrador do SIAFE</b> (ou o processo do
TCE-RJ, Anexo B). O "0" obtido na coleta é limitação de acesso, não ausência de pagamento.</div>
<p>Por fonte alternativa (Portal da Transparência federal e transparência das próprias entidades),
confirmam-se na janela 2017–2018:</p>
<table><tr><th>Entidade</th><th>Ano</th><th>Instrumento</th><th>Órgão / fonte</th><th>Valor liberado</th><th>Processo</th></tr>
<tr><td>SOLAZER (Raphael)</td><td>2018</td><td>Termo de Fomento nº 876220</td><td>Ministério do Esporte (SNEAELIS) — "Esporte e Vida"</td><td class="num">R$ 1.099.999,64</td><td>58000.002715/2018-14 (vig. 21/08/2018)</td></tr>
<tr><td>ONG Con-tato / CPASC</td><td>2018</td><td>Termo de Colaboração nº 097/2018</td><td>Min. Esporte → UNIRIO (TED 06/2018) — "Cidadania em Ação"</td><td class="num">R$ 3.770.919,88</td><td>SICONV 059681/2018 (vig. 01/10/2018→29/11/2019)</td></tr></table>
<p class="fonte">Valores = liberado/pactuado (não confundir com OB). <b>2017:</b> nada localizado para
nenhuma das duas. <b>Estadual 2017–2018 (Esporte/SUDERJ):</b> não localizado por via web (portal RJ é
Vaadin, não indexável) — a apurar pelo SIAFE-1 liberado ou pelos autos do TCE-RJ. Agregado federal
histórico das entidades: SOLAZER R$ 13.099.999,64; Con-tato/CPASC R$ 145.802.031,61.</p>

<h2>13. Situação processual</h2>
<ul>
<li><b>STF</b> (min. Alexandre de Moraes): autorizou prisões, buscas e bloqueio de R$ 100 mi (09/07/2026).</li>
<li><b>PF</b>: inquérito por peculato, lavagem e organização criminosa; desdobra apuração de 2024 sobre a ONG.</li>
<li><b>MP</b>: Raphael da Silva Gonçalves já denunciado por fraude a licitações.</li>
<li><b>Governo do Estado</b>: contrato SEAS/Ambiente Jovem em rescisão, com novo chamamento.</li>
<li><b>Prefeitura do Rio</b>: licitação de ~R$ 120 mi cancelada (maio/2024).</li>
</ul>

<h2>14. Pendências de fonte primária (para blindar cada frente)</h2>
<div class="pend">Itens em apuração, a fechar diretamente na fonte oficial:
<ul>
<li><b>Processo do TCE-RJ do acordo de R$ 900 mi</b> (CEDAE × Águas do Rio) — número do processo,
íntegra do voto/acórdão de 26/11/2025 e da liminar de Graciosa; íntegra do Termo de Conciliação de
03/10/2025 e do parecer da Agenersa (percentual 24,13%).</li>
<li><b>Atos do DOERJ</b> das nomeações na CEDAE (José Ricardo Ferreira de Brito e Philipe Campello,
out–dez/2025) e da criação da Diretoria de Sustentabilidade.</li>
<li><b>Pagamentos estaduais de 2017–2018</b> (Esporte/SUDERJ) — indisponíveis pelo SIAFE-1 (seção 12);
exigem liberação do exercício ou os autos do TCE (Anexo B já cobre o Esporte RJ).</li>
<li><b>Tramitação interna do processo SEI-070026/000705/2021</b> (contrato do Ambiente Jovem) — o
conteúdo substantivo consta do Anexo A pela via pública; falta o trâmite interno.</li>
<li><b>Pente-fino processo a processo</b> dos maiores contratos de INEA/SEAS (seção 11).</li>
</ul>
Nota de honestidade: os controladores da ONG (Cíntia, Raphael, Tathyane) <b>não constam</b> recebendo
benefício assistencial na base do município do Rio (checagem negativa).</div>

<footer>Peça de subsídio à apuração — indícios, não acusação; presunção de legitimidade dos atos
administrativos preservada. Pagamentos: SIAFE/TFE-RJ (Ordem Bancária = pagamento). Fatos da operação:
imprensa e órgãos oficiais com URL registrada no material de trabalho. CPF de terceiros mascarado (LGPD).
Apuração formal compete aos órgãos de controle e ao Ministério Público.</footer>
</body></html>"""


async def main():
    from compliance_agent.reporting.render_html import html_to_pdf
    html = build_html()
    out = str(REPO / "reports" / f"dossie_emendatio_ong_contato_{datetime.now().date()}.pdf")
    await html_to_pdf(html, out)
    print(out)
    return out


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
