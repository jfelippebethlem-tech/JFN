"""Lentes de detecção sobre a despesa da Prefeitura do Rio de Janeiro.

Implementa as hipóteses do catálogo `docs/PCRJ-100-IDEIAS-DETECCAO.md` que o acervo sustenta
HOJE, como funções versionadas — a casa não publica número que não venha de função com critério
por extenso.

O DENOMINADOR
-------------
Toda lente roda sobre o **universo contratual** de `compliance_agent.pcrj.universo`
(R$ 30.639.884.897,31 · 57.545 linhas · 8.406 credores), não sobre os R$ 89,62 bi brutos. Ranquear
o bruto ranqueia folha, dívida e precatório — sempre vencem por tamanho.

A RÉGUA
-------
Prevalência decide. Sinal que marca metade do acervo não discrimina nada; cada lente devolve a
sua prevalência junto com os casos, e o `__main__` a imprime. Nenhuma lente devolve "0" quando o
dado falta: devolve `None` com o motivo — INDISPONÍVEL ≠ 0.

LIMITES HERDADOS DA FONTE (medidos, não supostos)
-------------------------------------------------
- `pcrj_despesa.unidade` é **nula em 100,00%** das 78.595 linhas: não há granularidade abaixo do
  órgão. Toda lente de unidade gestora está bloqueada na origem.
- A base **não tem data, número de empenho nem objeto**. O grão temporal mínimo é o exercício.
- `doc_socio` de `socios_receita` vem **mascarado**, e a máscara **colide**. O casamento de sócio
  é feito por `nome_norm`, que carrega risco de homonímia — declarado em cada achado.
- Cobertura: despesa 2019–2023. Nada aqui fala do que veio depois.
"""
from __future__ import annotations

import re
from collections import defaultdict

from compliance_agent.pcrj.universo import conectar, filtro_sql
from compliance_agent.reporting.intel_base import moeda

# LC 123/2006, art. 3º: ME até R$ 360.000,00/ano; EPP até R$ 4.800.000,00/ano de receita bruta.
TETO_EPP_ANUAL = 4_800_000.00
TETO_ME_ANUAL = 360_000.00

# Elementos em que o pagamento a PESSOA FÍSICA é anômalo: pressupõem fornecedor empresarial.
ELEMENTOS_TIPICOS_DE_PJ = {
    "39": "serviços de terceiros — pessoa jurídica",
    "37": "locação de mão de obra",
    "51": "obras e instalações",
    "52": "equipamentos e material permanente",
    "40": "serviços de tecnologia da informação",
}


def _cnpj_basico(doc: str | None) -> str | None:
    """Raiz de 8 dígitos. Documento mascarado ('***201901**') não tem raiz utilizável."""
    d = re.sub(r"\D", "", str(doc or ""))
    return d[:8] if len(d) == 14 else None


# CNAE cujo domínio de um órgão é ESTRUTURAL, não captura: monopólio natural, concessão ou
# serviço em que a Administração não escolhe fornecedor. Medido: dos 24 achados brutos da lente
# de quase-exclusividade, 10 eram a LIGHT no Fundo de Iluminação Pública (até 100% do órgão-ano)
# e 5 um plano de saúde em fundo de assistência — nenhum é "captura de órgão".
_CNAE_ESTRUTURAL = re.compile(
    r"distribui[çc][ãa]o de energia|gera[çc][ãa]o de energia|capta[çc][ãa]o.*[áa]gua|"
    r"esgoto|saneamento|telefonia|telecomunica|correio|banco|planos de sa[úu]de|"
    r"metrovi[áa]rio|ferrovi[áa]rio|conces", re.I)


def _ressalva_estrutural(con, cnpj: str, nome: str) -> str | None:
    """Diz por que o domínio deste credor pode ser estrutural — ou None se não for o caso.

    Declara a ressalva, NÃO remove o achado: quem examina precisa ver o caso e a razão de ele
    provavelmente não ser irregularidade. Sumir com ele esconderia também o dia em que a
    concessionária cobrar demais."""
    d = re.sub(r"\D", "", str(cnpj or ""))
    row = con.execute(
        "SELECT atividade_princ, natureza_jur FROM empresas "
        "WHERE replace(replace(replace(cnpj,'.',''),'/',''),'-','') = ?", (d,)).fetchone()
    cnae, natjur = (row or (None, None))
    if cnae and _CNAE_ESTRUTURAL.search(str(cnae)):
        return f"setor estrutural (CNAE: {cnae})"
    if natjur and str(natjur).strip().startswith("1"):
        return f"credor é ente/órgão público (natureza jurídica {natjur}) — repasse, não compra"
    if re.search(r"tribunal|minist[ée]rio p[úu]blico|prefeitura|estado do|uni[ãa]o|"
                 r"c[âa]mara municipal|defensoria", str(nome or ""), re.I):
        return "credor é órgão público pelo nome — repasse entre entes, não contratação"
    # sem CNAE na base, o nome ainda entrega a concessão: o VLT Carioca escapava por não ter
    # cadastro em `empresas`, e concessão é justamente o caso em que não há escolha de fornecedor
    if re.search(r"concession[áa]ri|\bconc[.\s]|companhia de [áa]gua|"
                 r"empresa de correios", str(nome or ""), re.I):
        return "credor é concessionária pelo nome — o objeto decorre de concessão, não de escolha"
    return None


# ── L1 · ME/EPP que recebeu acima do teto de enquadramento no ano ────────────────────────────

def me_epp_acima_do_teto(db_path=None) -> dict:
    """Empresa declarada ME ou EPP na Receita que recebeu, num único exercício, mais do que o
    teto do seu porte.

    Critério: LC 123/2006, art. 3º — EPP é quem aufere receita bruta anual **até**
    R$ 4.800.000,00; ME, até R$ 360.000,00. Receber acima disso do MESMO ente, num só ano, é
    incompatível com o enquadramento declarado. Não prova fraude: a empresa pode ter sido
    desenquadrada no curso do ano (art. 3º, §9º) — mas o pagamento acima do teto pelo poder
    público é o que se examina, porque o enquadramento lhe rendeu tratamento favorecido.

    O teto é limite **inclusivo** ("até"): só marca quem passa dele.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        porte = {r[0]: (r[1], r[2]) for r in con.execute(
            "SELECT cnpj_basico, porte_cod, porte_txt FROM empresas_cadastro")}
        rows = con.execute(
            f"SELECT exercicio, credor_documento, credor_nome, sum(pago) FROM pcrj_despesa "
            f"WHERE {filtro_sql()} GROUP BY 1,2,3").fetchall()
    finally:
        con.close()

    achados, universo = [], 0
    for ano, doc, nome, pago in rows:
        raiz = _cnpj_basico(doc)
        if not raiz or raiz not in porte:
            continue
        cod, txt = porte[raiz]
        # o código vem com zero à esquerda na Receita ('01', '03', '05') — comparar com '1'
        # devolvia universo ZERO, e a lente honestamente reportou INDISPONÍVEL em vez de
        # "nenhum caso". Normalizar é obrigatório; presumir o formato foi o erro.
        teto = {"01": TETO_ME_ANUAL, "03": TETO_EPP_ANUAL}.get(str(cod).zfill(2))
        if teto is None:
            continue                       # porte 5 = demais; não há teto a violar
        universo += 1
        if pago > teto:
            achados.append({"exercicio": ano, "cnpj": doc, "nome": nome, "pago": pago,
                            "porte": txt, "teto": teto, "razao": pago / teto})
    achados.sort(key=lambda a: -a["pago"])
    # DOIS CORTES, força probatória diferente — publicar um só seria escolher em silêncio:
    #  FORTE  — acima de R$ 4.800.000,00, o teto MÁXIMO do Simples. Nenhum enquadramento da LC
    #           123 admite esse recebimento anual; não há desenquadramento que o explique.
    #  AMPLO  — acima do teto do PRÓPRIO porte declarado. Inclui a ME que passou de R$ 360.000,00,
    #           o que pode ser mero desenquadramento no curso do ano (art. 3º, §9º) — por isso é
    #           indício mais fraco, e vai rotulado como tal.
    fortes = [a for a in achados if a["pago"] > TETO_EPP_ANUAL]
    return {"lente": "ME/EPP acima do teto de enquadramento (LC 123/2006, art. 3º)",
            "universo": universo, "n": len(fortes),
            "prevalencia": len(fortes) / universo if universo else None,
            "massa": sum(a["pago"] for a in fortes), "achados": fortes,
            "corte_amplo": {"n": len(achados), "massa": sum(a["pago"] for a in achados),
                            "prevalencia": len(achados) / universo if universo else None,
                            "achados": achados,
                            "_nota": "acima do teto do porte declarado; a ME entre R$ 360 mil e "
                                     "R$ 4,8 mi pode ter sido desenquadrada no curso do ano"}}


# ── L2 · credor com sanção de efeito AMPLO vigente durante o exercício pago ──────────────────

def sancao_de_efeito_amplo(db_path=None) -> dict:
    """Credor pago pela PCRJ enquanto pesava sobre ele sanção que veda contratar em TODOS os
    entes federativos.

    Usa `knowledge.efeito_sancao`: presença no CEIS/CNEP **não é vedação**. Só entram as
    categorias de efeito AMPLO — declaração de inidoneidade (art. 156, IV e §5º da Lei
    14.133/2021), impedimento sem prazo, interdição de atividades e dissolução compulsória.
    Impedimento com prazo (art. 156, III) fica **fora**: o §4º o restringe ao ente sancionador.

    Vigência é aferida contra o EXERCÍCIO, não contra a data do pagamento — a base não tem data.
    Por isso o achado é de exercício em que houve sobreposição, e o passo seguinte é confrontar
    a data real da OB.
    """
    from compliance_agent.knowledge.efeito_sancao import AMPLO, efeito

    con = conectar(db_path or "data/compliance.db")
    try:
        sanc = defaultdict(list)
        for cpf_cnpj, cat, ini, fim in con.execute(
                "SELECT cpf_cnpj, categoria, data_inicio, data_fim FROM sancoes_federais"):
            if efeito(cat)["efeito"] == AMPLO:
                sanc[re.sub(r"\D", "", str(cpf_cnpj or ""))].append((cat, ini, fim))
        rows = con.execute(
            f"SELECT exercicio, credor_documento, credor_nome, sum(pago) FROM pcrj_despesa "
            f"WHERE {filtro_sql()} GROUP BY 1,2,3").fetchall()
    finally:
        con.close()

    achados, universo = [], 0
    for ano, doc, nome, pago in rows:
        d = re.sub(r"\D", "", str(doc or ""))
        if len(d) != 14:
            continue                       # mascarado ou PF: fora, não é "sem sanção"
        universo += 1
        vig = [(c, i, f) for c, i, f in sanc.get(d, [])
               if (i or "9999") <= f"{ano}-12-31" and (f is None or f == "" or f >= f"{ano}-01-01")]
        if vig:
            achados.append({"exercicio": ano, "cnpj": doc, "nome": nome, "pago": pago,
                            "sancoes": vig})
    achados.sort(key=lambda a: -a["pago"])
    return {"lente": "credor sob sanção de efeito AMPLO no exercício pago",
            "universo": universo, "n": len(achados),
            "prevalencia": len(achados) / universo if universo else None,
            "massa": sum(a["pago"] for a in achados), "achados": achados}


# ── L3 · pessoa física recebendo em elemento típico de pessoa jurídica ───────────────────────

def pessoa_fisica_em_elemento_de_pj(db_path=None) -> dict:
    """Pagamento a CPF em elemento de despesa que pressupõe fornecedor empresarial.

    Serviços de PJ (39), locação de mão de obra (37), obras (51), equipamento permanente (52) e
    TIC (40) não são, por natureza, prestados por pessoa física. Pagamento a CPF nesses elementos
    ou é erro de classificação, ou é contratação que deveria ter sido de PJ.

    ⚠️ O documento vem **mascarado** nos dados abertos, e a máscara COLIDE (18 máscaras reúnem
    mais de um credor, concentrando R$ 155,27 mi). Por isso o agrupamento é por (documento,
    NOME), nunca por documento sozinho. CPF não é exibido — LGPD.
    """
    con = conectar(db_path or "data/compliance.db")
    marks = ",".join(f"'{e}'" for e in ELEMENTOS_TIPICOS_DE_PJ)
    try:
        universo = con.execute(f"SELECT count(*) FROM pcrj_despesa WHERE {filtro_sql()} "
                               f"AND substr(natureza,5,2) IN ({marks})").fetchone()[0]
        rows = con.execute(
            f"SELECT credor_documento, credor_nome, substr(natureza,5,2), exercicio, orgao, sum(pago) "
            f"FROM pcrj_despesa WHERE {filtro_sql()} AND substr(natureza,5,2) IN ({marks}) "
            f"AND length(replace(replace(replace(credor_documento,'.',''),'/',''),'-','')) <> 14 "
            f"GROUP BY 1,2,3,4,5").fetchall()
    finally:
        con.close()
    achados = [{"credor": nome, "mascarado": "*" in str(doc), "elemento": el,
                "elemento_txt": ELEMENTOS_TIPICOS_DE_PJ[el], "exercicio": ano,
                "orgao": org, "pago": pago}
               for doc, nome, el, ano, org, pago in rows]
    achados.sort(key=lambda a: -a["pago"])
    return {"lente": "pessoa física em elemento típico de pessoa jurídica",
            "universo": universo, "n": len(achados),
            "prevalencia": len(achados) / universo if universo else None,
            "massa": sum(a["pago"] for a in achados), "achados": achados}


# ── L4 · salto abrupto de faturamento ano a ano ──────────────────────────────────────────────

def salto_de_faturamento(db_path=None, fator: float = 10.0, base_minima: float = 1_000_000.0) -> dict:
    """Credor cujo recebimento anual salta `fator`× ou mais de um exercício para o seguinte.

    Exige base ≥ R$ 1.000.000,00 no ano anterior: sem piso, um credor que recebeu R$ 100,00 e
    passou a R$ 5.000,00 apareceria como salto de 50×, o que é ruído aritmético e não sinal.
    O par é de exercícios CONSECUTIVOS — crescimento espalhado por anos é expansão, não salto.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        rows = con.execute(
            f"SELECT credor_documento, credor_nome, exercicio, sum(pago) FROM pcrj_despesa "
            f"WHERE {filtro_sql()} GROUP BY 1,2,3").fetchall()
    finally:
        con.close()
    por_credor = defaultdict(dict)
    for doc, nome, ano, pago in rows:
        por_credor[(str(doc), str(nome))][ano] = pago
    achados, pares = [], 0
    for (doc, nome), anos in por_credor.items():
        for ano in sorted(anos):
            ant = anos.get(ano - 1)
            if ant is None or ant < base_minima:
                continue
            pares += 1
            if anos[ano] >= fator * ant:
                achados.append({"credor": nome, "cnpj": doc, "de": ano - 1, "para": ano,
                                "pago_antes": ant, "pago_depois": anos[ano],
                                "razao": anos[ano] / ant})
    achados.sort(key=lambda a: -a["pago_depois"])
    return {"lente": f"salto de {fator:.0f}× ou mais no recebimento anual "
                     f"(base ≥ R$ {moeda(base_minima)})",
            "universo": pares, "n": len(achados),
            "prevalencia": len(achados) / pares if pares else None,
            "massa": sum(a["pago_depois"] for a in achados), "achados": achados}


# ── L5 · liquidado sem pagamento correspondente ──────────────────────────────────────────────

def liquidado_sem_pagamento(db_path=None, piso: float = 10_000.0) -> dict:
    """Despesa LIQUIDADA (serviço atestado, dívida reconhecida) sem pagamento no exercício.

    Liquidação é o reconhecimento de que o credor cumpriu: art. 63 da Lei 4.320/64. Liquidar e
    não pagar é ou restos a pagar processados — legítimo, mas com custo e risco — ou atesto sem
    quitação. Aqui NÃO se aplica o filtro `pago > 0` do universo contratual, pela razão óbvia de
    que a lente procura justamente o pago igual a zero; o resto do corte permanece.
    """
    con = conectar(db_path or "data/compliance.db")
    base = ("substr(natureza,2,1) IN ('3','4') AND substr(natureza,3,2)='90'")
    try:
        universo = con.execute(f"SELECT count(*) FROM pcrj_despesa WHERE {base} "
                               f"AND liquidado > 0").fetchone()[0]
        rows = con.execute(
            f"SELECT exercicio, orgao, credor_nome, credor_documento, natureza, liquidado, pago "
            f"FROM pcrj_despesa WHERE {base} AND liquidado >= ? "
            f"AND (pago IS NULL OR pago = 0) ORDER BY liquidado DESC", (piso,)).fetchall()
    finally:
        con.close()
    achados = [{"exercicio": a, "orgao": o, "credor": n, "cnpj": d, "natureza": nat,
                "liquidado": liq, "pago": pg or 0.0} for a, o, n, d, nat, liq, pg in rows]
    return {"lente": f"liquidado sem pagamento no exercício (piso R$ {moeda(piso)})",
            "universo": universo, "n": len(achados),
            "prevalencia": len(achados) / universo if universo else None,
            "massa": sum(a["liquidado"] for a in achados), "achados": achados}


# ── L6 · fornecedor quase-exclusivo do órgão no exercício ────────────────────────────────────

def fornecedor_quase_exclusivo(db_path=None, corte: float = 0.80,
                               piso_orgao: float = 5_000_000.0) -> dict:
    """Um único credor absorve `corte` ou mais do pago contratual de um órgão no exercício.

    O corte de 50% foi DESCARTADO por medição: marcava 35,7% dos órgão-ano — não discrimina.
    A 80% o sinal volta a ser raro. Piso de R$ 5 mi por órgão-ano evita que órgão pequeno, onde
    dois pagamentos já fazem 100%, domine o resultado.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        rows = con.execute(
            f"SELECT exercicio, orgao, credor_documento, credor_nome, sum(pago) FROM pcrj_despesa "
            f"WHERE {filtro_sql()} GROUP BY 1,2,3,4").fetchall()
        # denominador ALTERNATIVO: o orçamento total do órgão, sem o corte contratual. O share
        # sobre as COMPRAS é o que a lente mede, mas publicar só ele engana — na Secretaria de
        # Transportes de 2023 o subsídio tarifário aos consórcios (elemento 41) sai do universo
        # contratual, e o mesmo credor aparece com 80,4% das compras e 52,7% do orçamento.
        total_geral = {(a, o): p for a, o, p in con.execute(
            "SELECT exercicio, orgao, sum(pago) FROM pcrj_despesa WHERE pago > 0 GROUP BY 1,2")}
        por_orgao = defaultdict(list)
        for ano, org, doc, nome, pago in rows:
            por_orgao[(ano, org)].append((doc, nome, pago))
        achados, universo = [], 0
        for (ano, org), cs in por_orgao.items():
            total = sum(p for _, _, p in cs)
            if total < piso_orgao:
                continue
            universo += 1
            doc, nome, pago = max(cs, key=lambda x: x[2])
            if pago / total >= corte:
                tg = total_geral.get((ano, org)) or total
                achados.append({"exercicio": ano, "orgao": org, "credor": nome, "cnpj": doc,
                                "pago": pago, "total_contratual_orgao": total,
                                "share": pago / total,
                                "total_orgao": tg, "share_orcamento_total": pago / tg,
                                "n_credores": len(cs),
                                "ressalva": _ressalva_estrutural(con, doc, nome)})
    finally:
        con.close()
    achados.sort(key=lambda a: -a["pago"])
    exame = [a for a in achados if not a["ressalva"]]
    return {"lente": f"fornecedor com {corte:.0%}+ do pago contratual do órgão no exercício",
            "universo": universo, "n": len(exame),
            "prevalencia": len(exame) / universo if universo else None,
            "massa": sum(a["pago"] for a in exame), "achados": exame,
            # os ressalvados ficam VISÍVEIS, com o motivo — não somem do resultado
            "ressalvados": [a for a in achados if a["ressalva"]],
            "_nota": "`share` é sobre o pago CONTRATUAL do órgão; `share_orcamento_total` é sobre "
                     "o orçamento inteiro. Os dois são verdadeiros e medem coisas diferentes"}


LENTES = (me_epp_acima_do_teto, sancao_de_efeito_amplo, pessoa_fisica_em_elemento_de_pj,
          salto_de_faturamento, liquidado_sem_pagamento, fornecedor_quase_exclusivo)


def rodar_todas(db_path=None) -> list[dict]:
    return [f(db_path) for f in LENTES]


if __name__ == "__main__":
    print(f"{'lente':58s} {'casos':>6s} {'universo':>9s} {'preval.':>8s} {'massa':>20s}")
    print("─" * 106)
    for r in rodar_todas():
        pv = f"{r['prevalencia']*100:.2f}%" if r["prevalencia"] is not None else "INDISP."
        print(f"{r['lente'][:58]:58s} {r['n']:6,} {r['universo']:9,} {pv:>8s} "
              f"R$ {moeda(r['massa']):>17s}")
