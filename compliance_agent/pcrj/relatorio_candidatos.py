# -*- coding: utf-8 -*-
"""Entregável do cruzamento CANDIDATURA × FOLHA DA PREFEITURA — produto da casa.

Gera HTML e PDF por `reporting.render_html` + `html_to_pdf`; nunca `.txt` à mão (invariante da
casa). Os dados vêm de `candidato_x_folha.cruzar`.

A ORDEM DAS SEÇÕES É DELIBERADA: a fonte e as TRÊS SEPARAÇÕES vêm ANTES do número. Relatório ruim
põe o número primeiro e a ressalva no rodapé — e aqui, sem a separação, o número engana: **3.495
pessoas viram 50** depois de aplicar janela de mandato, exclusão de inativo e trava de matrícula
única.

Uso:  python -m compliance_agent.pcrj.relatorio_candidatos [--saida data/relatorios]
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import html
from pathlib import Path

from compliance_agent.pcrj import candidato_x_folha as C
from compliance_agent.reporting.render_html import html_to_pdf, render_html

# Medido em 2026-08-05 nos três com mandato vigente, competência a competência: média das 12
# competências de 2024 contra a média das competências de 2025-2026, na própria folha.
_REMUNERACAO_VIGENTES = [
    ("Prefeito de São Pedro da Aldeia", "Guarda Municipal", "4.314,91", "4.647,21"),
    ("Vice-prefeita de Barra Mansa", "Guarda Municipal", "4.571,19", "4.658,75"),
    ("Prefeito de Quissamã", "Comlurb", "2.848,60", "3.033,56"),
]


def _org(o) -> str:
    """Agrupa a lotação pelo que decide a análise: o órgão, não a sigla da unidade."""
    o = str(o or "—")
    if "Guarda" in o:
        return "Guarda Municipal"
    if "Comlurb" in o:
        return "Comlurb"
    if "Educa" in o:
        return "Educação"
    if any(k in o for k in ("Saúde", "RioSa", "Hospital")):
        return "Saúde / RioSaúde"
    return o.split(" (")[0][:38]


def _tabela(linhas, cols: list[str], chaves: list) -> str:
    th = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    tr = "".join("<tr>" + "".join(f"<td>{html.escape(str(f(x)))}</td>" for f in chaves) + "</tr>"
                 for x in linhas)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"


def montar_contexto(linhas: list[dict] | None = None) -> dict:
    """Contexto do `render_html`. `linhas` permite injetar dados em teste, sem tocar o banco."""
    L = linhas if linhas is not None else C.cruzar()
    r = C.resumo(L)
    chefes = [x for x in L if str(x["cargo"]).upper().startswith(C.CHEFIA)]
    org = collections.Counter(_org(x["orgao"]) for x in L)
    n_turno = org.get("Comlurb", 0) + org.get("Guarda Municipal", 0)

    secoes = [
        {"titulo": "1. O que foi cruzado, e com que fonte", "html":
         "<p>Candidaturas dos <b>dados abertos do TSE</b> (<code>consulta_cand</code>, arquivo do "
         "estado do Rio de Janeiro, que cobre os 92 municípios fluminenses), eleições de "
         "<b>2012, 2014, 2016, 2018, 2020, 2022 e 2024</b> — <b>6.562 candidaturas</b> de "
         "<b>3.718 pessoas</b>.</p>"
         "<p>Folha de pagamento da <b>Prefeitura do Rio</b> (<code>ArquivoTC</code>), 12,1 milhões "
         "de linhas, competências de <b>12/2020 a 05/2026</b> — a janela das gestões Eduardo Paes "
         "e Eduardo Cavaliere. A Câmara Municipal ficou <b>fora</b> deste produto, por definição "
         "do escopo.</p>"
         "<p><b>3.495 pessoas</b> que foram candidatas aparecem em algum momento nessa folha. Esse "
         "número bruto não sustenta juízo nenhum: as três separações da seção 2 são o que lhe dá "
         "sentido.</p>"},
        {"titulo": "2. As três separações que mudam o sentido do número", "html":
         "<p><b>2.1 Janela do mandato.</b> Quem foi eleito em 2012 exerceu de 2013 a 2016; a folha "
         "só começa em 12/2020 e, portanto, nada diz sobre aquele mandato. Contar “presença na "
         "folha a partir de 2021” como sobreposição levava a 23 chefes de executivo. Com a janela "
         "correta — janeiro do ano seguinte à eleição a dezembro do quarto ano — são <b>8</b>.</p>"
         "<p><b>2.2 Inativo não acumula.</b> Aposentados e pensionistas (FUNPREVI e folhas de "
         "previdência) estão fora: o art. 38 da Constituição trata do servidor <b>em atividade</b>. "
         "São 18 dos 131 casos brutos.</p>"
         "<p><b>2.3 Prefeito não é vereador.</b> Art. 38, <b>II</b>: investido no mandato de "
         "Prefeito, o servidor é <b>afastado do cargo</b>, facultada a opção pela remuneração. "
         "Art. 38, <b>III</b>: vereador, <b>havendo compatibilidade de horários</b>, percebe as "
         "vantagens do cargo e o subsídio; não havendo, afasta-se. Estar na folha não prova "
         "irregularidade em nenhuma das duas hipóteses — prova que há o que conferir.</p>"},
        {"titulo": f"3. Resultado: {r['pessoas']} pessoas, {r['municipios']} municípios", "html":
         f"<p>Pessoas eleitas em <b>outro município</b> do Rio de Janeiro com vínculo <b>ativo</b> "
         f"na folha da Prefeitura <b>dentro da janela do mandato</b>: <b>{r['pessoas']}</b>, em "
         f"<b>{r['municipios']} municípios</b> — <b>{r['chefia_executivo']}</b> na chefia do "
         f"executivo (prefeito ou vice) e <b>{r['legislativo']}</b> no legislativo.</p>"
         + _tabela(org.most_common(), ["Órgão no Rio", "Pessoas"],
                   [lambda x: x[0], lambda x: x[1]])
         + f"<p><b>Comlurb e Guarda Municipal somam {n_turno} das {r['pessoas']}</b>. São funções "
           "operacionais de turno fixo no Rio, e é exatamente aí que a compatibilidade de horários "
           "exigida pelo art. 38, III precisa ser demonstrada, não presumida.</p>"},
        {"titulo": f"4. Prioridade: os {len(chefes)} na chefia do executivo", "html":
         _tabela(chefes, ["Eleição", "Cargo", "Município", "Partido", "Meses na folha",
                          "Órgão no Rio", "Nome"],
                 [lambda x: x["ano"], lambda x: x["cargo"], lambda x: x["municipio"],
                  lambda x: x["partido"], lambda x: x["meses_no_mandato"],
                  lambda x: _org(x["orgao"]), lambda x: x["nome_tse"]])
         + "<p>Nesses, o art. 38, II é categórico quanto ao <b>afastamento</b>. A opção pela "
           "remuneração do cargo efetivo é lícita — o que a folha não registra é se houve o "
           "afastamento, porque ela documenta pagamento, não frequência.</p>"},
        {"titulo": "5. Os três com mandato vigente (2025–2028)", "html":
         "<p>A remuneração <b>não cai</b> quando o mandato começa; os três seguem em folha "
         "<code>NORMAL</code>, com valor igual ou maior:</p>"
         + _tabela(_REMUNERACAO_VIGENTES,
                   ["Cargo eletivo", "Órgão no Rio", "Média 2024 (R$)", "Média 2025-26 (R$)"],
                   [lambda x: x[0], lambda x: x[1], lambda x: x[2], lambda x: x[3]])
         + "<p>A busca nominal no Diário Oficial do Município (2024 em diante) <b>não</b> "
           "localizou ato de afastamento, licença ou cessão para nenhum dos três. <b>Isso não é "
           "prova de que não houve</b>: a coleta percorre duas páginas por termo e o texto vem em "
           "nível de página. A conclusão correta é que a via documental é necessária.</p>"
         "<p><b>Providência sugerida:</b> requisitar ficha funcional, ato de afastamento e folha "
         "de frequência dos três, e verificar eventual acúmulo do subsídio do mandato com a "
         "remuneração do cargo efetivo.</p>"},
        {"titulo": "6. Limites desta análise", "html":
         "<p>O TSE <b>mascara o CPF</b> nos dados abertos e a folha da Prefeitura <b>não traz CPF "
         "algum</b>. O casamento é por <b>nome normalizado</b> e é, por natureza, <b>indício — "
         "nunca prova</b>.</p>"
         "<p>A trava aplicada é a mesma da perícia de benefícios: só entra nome com <b>matrícula "
         "única</b> na folha, o que reduz o homônimo dentro da folha e <b>não elimina</b> o "
         "homônimo na população. Cada linha desta lista precisa de confirmação documental antes de "
         "qualquer juízo.</p>"
         "<p>A folha registra <b>pagamento</b>, não frequência nem afastamento. Nenhuma conclusão "
         "sobre acúmulo indevido pode ser tirada apenas dela.</p>"},
    ]

    return {
        "classificacao": "CONFIDENCIAL — USO INTERNO",
        "titulo": "Candidaturas eleitorais e folha da Prefeitura do Rio",
        "subtitulo": "Cruzamento TSE (2012–2024) × folha municipal (12/2020–05/2026) — "
                     "indícios para apuração",
        "metodologia": "Dados abertos TSE (consulta_cand/RJ) × ArquivoTC (folha PCRJ); janela de "
                       "mandato, exclusão de inativos e trava de matrícula única",
        "score": r["chefia_executivo"] * 10, "faixa": "ALTO",
        "rotulo_score": "Casos na chefia do executivo (×10)",
        "top_flags": [
            f"{r['pessoas']} pessoas eleitas em outro município na folha ativa do Rio",
            f"{r['chefia_executivo']} na chefia do executivo (art. 38, II — afastamento)",
            f"{n_turno} das {r['pessoas']} em Comlurb e Guarda Municipal (turno fixo)",
            "3 mandatos vigentes seguem recebendo, sem ato de afastamento localizado",
        ],
        "secoes": secoes,
        "proveniencia": [
            "TSE — dados abertos, consulta_cand_{ano}.zip, arquivo do RJ (2012–2024)",
            "Prefeitura do Rio — ArquivoTC (folha de pagamento), 12/2020 a 05/2026",
            "Diário Oficial do Município do Rio de Janeiro (busca nominal, 2024+)",
        ],
        "ressalva": "Indícios para apuração interna. O casamento é por NOME (o TSE mascara o CPF e "
                    "a folha da Prefeitura não o traz), portanto indício e nunca prova. Presunção "
                    "de legitimidade dos atos administrativos. Nenhum dado indisponível foi "
                    "fabricado; a ausência de ato no Diário Oficial NÃO foi tratada como ausência "
                    "do ato.",
        "_dados": {"linhas": L},
    }


def gerar(saida: str | Path = "data/relatorios", linhas: list[dict] | None = None) -> dict:
    destino = Path(saida)
    destino.mkdir(parents=True, exist_ok=True)
    doc = render_html(montar_contexto(linhas))
    caminho_html = destino / "candidatos_folha_pcrj.html"
    caminho_html.write_text(doc, encoding="utf-8")
    pdf = asyncio.run(html_to_pdf(doc, str(destino / "candidatos_folha_pcrj.pdf")))
    return {"html": str(caminho_html), "pdf": pdf}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--saida", default="data/relatorios")
    a = ap.parse_args()
    for k, v in gerar(a.saida).items():
        print(f"{k.upper():5} {v}")


if __name__ == "__main__":
    main()
