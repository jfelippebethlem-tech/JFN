"""Lentes de EXECUÇÃO ORÇAMENTÁRIA e de QUALIDADE DO DADO na despesa da Prefeitura do Rio.

Segundo bloco do catálogo `docs/PCRJ-100-IDEIAS-DETECCAO.md` (famílias G e L). O primeiro
bloco — fornecedor, vínculo e porte — está em `tools/lentes_pcrj.py`.

A CASCATA DA DESPESA (Lei 4.320/64)
-----------------------------------
**Empenho** (art. 58) reserva a dotação. **Liquidação** (art. 63) reconhece que o credor
cumpriu — é o atesto. **Pagamento** (art. 64) quita. As três etapas são desiguais em força
probatória, e a casa já errou por tratá-las como sinônimo: só o pagamento é despesa realizada.

Daí as lentes deste módulo: cada degrau que não avança para o seguinte é um fato administrativo
com explicação possível (restos a pagar, cancelamento, glosa) e com risco próprio.

CONTROLES, não só detectores
----------------------------
Duas funções aqui não procuram irregularidade: procuram **defeito no dado**. `cascata_coerente`
e os testes de qualidade cadastral existem para dizer se o resto é confiável. Um acervo que
falha nesses controles não sustenta nenhuma das outras lentes.
"""
from __future__ import annotations

import re
from collections import defaultdict

from compliance_agent.pcrj.universo import conectar, filtro_sql
from compliance_agent.reporting.intel_base import moeda

# grupo/modalidade do universo contratual, mas SEM o filtro `pago > 0`: estas lentes procuram
# justamente o pagamento que não houve
BASE_CONTRATUAL = "substr(natureza,2,1) IN ('3','4') AND substr(natureza,3,2)='90'"


def _faixa_da_serie(con) -> tuple[int, int]:
    """Primeiro e último exercício do acervo. Sem isso, toda lente de execução mente na borda:
    o que ficou empenhado e não pago em 2023 pode ter virado resto a pagar quitado em 2024 —
    exercício que a base não tem."""
    lo, hi = con.execute("SELECT min(exercicio), max(exercicio) FROM pcrj_despesa").fetchone()
    return int(lo or 0), int(hi or 0)


# ── empenhado que nunca virou pagamento ─────────────────────────────────────────────────────

def empenhado_sem_pagamento(db_path=None, piso: float = 100_000.0) -> dict:
    """Dotação empenhada que não gerou pagamento algum no exercício.

    Empenho é reserva, não despesa — cancelá-lo é legítimo e comum. O que se examina é o
    **volume reservado e não executado**, porque ele: (a) trava dotação que poderia atender outra
    finalidade; (b) quando reiterado no mesmo fornecedor, sugere planejamento que não se
    concretiza; (c) alimenta restos a pagar, que a Lei de Responsabilidade Fiscal (art. 42) limita
    no fim de mandato.

    NÃO É o mesmo que `liquidado_sem_pagamento`: ali houve atesto — o credor cumpriu e não
    recebeu. Aqui pode não ter havido nem entrega.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        universo = con.execute(f"SELECT count(*) FROM pcrj_despesa WHERE {BASE_CONTRATUAL} "
                               f"AND empenhado > 0").fetchone()[0]
        rows = con.execute(
            f"SELECT exercicio, orgao, credor_nome, credor_documento, natureza, empenhado, "
            f"liquidado FROM pcrj_despesa WHERE {BASE_CONTRATUAL} AND empenhado >= ? "
            f"AND (pago IS NULL OR pago = 0) ORDER BY empenhado DESC", (piso,)).fetchall()
        _, ultimo = _faixa_da_serie(con)
    finally:
        con.close()
    todos = [{"exercicio": a, "orgao": o, "credor": n, "cnpj": d, "natureza": nat,
              "empenhado": e, "liquidado": liq or 0.0, "houve_atesto": bool(liq),
              "no_ultimo_exercicio_da_serie": a == ultimo}
             for a, o, n, d, nat, e, liq in rows]
    # A BORDA DOMINA — medido: 430 dos 460 (93%) estão no último exercício da série. "Não pagou
    # em 2023" numa base que TERMINA em 2023 é resto a pagar normal, quitado em 2024, exercício
    # que a base não tem. Publicar os 460 seria publicar o corte temporal como se fosse achado.
    achados = [a for a in todos if not a["no_ultimo_exercicio_da_serie"]]
    return {"lente": f"empenhado sem pagamento em exercício ENCERRADO (piso R$ {moeda(piso)})",
            "universo": universo, "n": len(achados),
            "prevalencia": len(achados) / universo if universo else None,
            "massa": sum(a["empenhado"] for a in achados), "achados": achados,
            "n_com_atesto": sum(1 for a in achados if a["houve_atesto"]),
            "na_borda_da_serie": [a for a in todos if a["no_ultimo_exercicio_da_serie"]],
            "_nota": f"empenho é RESERVA, não despesa realizada; `houve_atesto` separa o que já "
                     f"passou pela liquidação — esse é o caso grave. O último exercício da série "
                     f"({ultimo}) sai do achado e vai para `na_borda_da_serie`: ali o "
                     f"não-pagamento é resto a pagar, não indício"}


# ── superempenho: reserva muito acima do que se pagou ───────────────────────────────────────

def superempenho(db_path=None, fracao: float = 0.50, piso: float = 1_000_000.0) -> dict:
    """Empenho relevante em que o pago ficou abaixo de `1 - fracao` do reservado.

    Empenhar R$ 10 milhões e pagar R$ 2 milhões pode ser cancelamento legítimo — ou estimativa
    inflada que reserva dotação sem lastro de execução. O corte pede empenho de pelo menos
    R$ 1.000.000,00 para que a diferença tenha materialidade, e ignora quem não pagou NADA (isso
    é a lente anterior, com natureza distinta).
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        universo = con.execute(f"SELECT count(*) FROM pcrj_despesa WHERE {BASE_CONTRATUAL} "
                               f"AND empenhado >= ?", (piso,)).fetchone()[0]
        rows = con.execute(
            f"SELECT exercicio, orgao, credor_nome, credor_documento, empenhado, liquidado, pago "
            f"FROM pcrj_despesa WHERE {BASE_CONTRATUAL} AND empenhado >= ? AND pago > 0",
            (piso,)).fetchall()
        _, ultimo = _faixa_da_serie(con)
    finally:
        con.close()
    achados = []
    for ano, org, nome, doc, emp, liq, pago in rows:
        if pago >= (1 - fracao) * emp:
            continue
        achados.append({"exercicio": ano, "orgao": org, "credor": nome, "cnpj": doc,
                        "empenhado": emp, "liquidado": liq or 0.0, "pago": pago,
                        "nao_executado": emp - pago, "fracao_paga": pago / emp,
                        "no_ultimo_exercicio_da_serie": ano == ultimo})
    achados.sort(key=lambda a: -a["nao_executado"])
    # mesma doença da lente anterior, e ainda mais aguda: 51 dos 53 (96%) caem no último ano
    conclusivos = [a for a in achados if not a["no_ultimo_exercicio_da_serie"]]
    return {"lente": f"superempenho em exercício ENCERRADO: pago abaixo de {(1-fracao):.0%} do "
                     f"empenhado (empenho ≥ R$ {moeda(piso)})",
            "universo": universo, "n": len(conclusivos),
            "prevalencia": len(conclusivos) / universo if universo else None,
            "massa": sum(a["nao_executado"] for a in conclusivos), "achados": conclusivos,
            "na_borda_da_serie": [a for a in achados if a["no_ultimo_exercicio_da_serie"]],
            "_nota": f"a massa é a DIFERENÇA não executada, não o valor pago. O último exercício "
                     f"({ultimo}) sai do achado: ali o saldo pode ter sido pago no ano seguinte, "
                     f"fora da base. Sem esse corte, 51 dos 53 casos eram borda"}


# ── fornecedor de passagem: um só exercício, valor alto ─────────────────────────────────────

def fornecedor_de_exercicio_unico(db_path=None, piso: float = 10_000_000.0) -> dict:
    """Credor que recebeu valor alto e aparece em UM só exercício.

    ⚠️ Sozinho, "exercício único" NÃO discrimina: **5.225 de 9.241 credores (56,5%)** do acervo
    aparecem em um único ano — é a cauda normal de qualquer carteira de compras. O que
    discrimina é o valor: receber dezenas de milhões e desaparecer é outro fato.

    O corte de R$ 10.000.000,00 foi escolhido por isso, e o resultado deve ser lido junto com a
    janela da base: a despesa cobre **2019–2023**. Quem aparece só em 2023 pode simplesmente ter
    continuado depois do fim da série — por isso o achado marca `no_limite_da_serie`.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        rows = con.execute(
            f"SELECT credor_documento, credor_nome, exercicio, sum(pago) FROM pcrj_despesa "
            f"WHERE {filtro_sql()} GROUP BY 1,2,3").fetchall()
        faixa = con.execute("SELECT min(exercicio), max(exercicio) FROM pcrj_despesa").fetchone()
    finally:
        con.close()
    # AGRUPAR POR RAIZ DE CNPJ, não por (documento, nome): 72 raízes do acervo (0,96%) aparecem
    # com mais de uma razão social — "Companhia Brasileira de Soluções e Serviços" e "ALELO S.A."
    # são o mesmo CNPJ, e "Instituto Gnosis" e "Projeto Social Colibri" também. Agrupar pelo nome
    # partiria a empresa em duas e inventaria "exercício único" onde há continuidade.
    # Documento MASCARADO não tem raiz utilizável: cai fora, com a razão declarada.
    por = defaultdict(lambda: {"anos": {}, "nomes": set(), "doc": None})
    fora_por_mascara = 0
    for doc, nome, ano, pago in rows:
        raiz = re.sub(r"\D", "", str(doc or ""))[:8]
        if len(raiz) != 8 or "*" in str(doc or ""):
            fora_por_mascara += 1
            continue
        por[raiz]["anos"][ano] = por[raiz]["anos"].get(ano, 0.0) + pago
        por[raiz]["nomes"].add(str(nome))
        por[raiz]["doc"] = doc
    achados, universo = [], 0
    for raiz, x in por.items():
        anos = x["anos"]
        total = sum(anos.values())
        if total < piso:
            continue
        universo += 1
        if len(anos) == 1:
            ano = next(iter(anos))
            achados.append({"cnpj": x["doc"], "raiz": raiz, "nome": sorted(x["nomes"])[0],
                            "razoes_sociais": sorted(x["nomes"]), "exercicio": ano,
                            "pago": total,
                            "no_limite_da_serie": ano in (faixa[0], faixa[1])})
    achados.sort(key=lambda a: -a["pago"])
    # Mesma disciplina de borda das outras lentes deste módulo: quem aparece só no PRIMEIRO ou
    # no ÚLTIMO ano da série pode ter começado antes ou continuado depois, fora da janela. Só o
    # que está no MIOLO é conclusivo — apareceu, levou, sumiu, tudo dentro do que se enxerga.
    conclusivos = [a for a in achados if not a["no_limite_da_serie"]]
    return {"lente": f"fornecedor de R$ {moeda(piso)}+ presente em UM só exercício do MIOLO "
                     f"da série",
            "universo": universo, "n": len(conclusivos),
            "prevalencia": len(conclusivos) / universo if universo else None,
            "massa": sum(a["pago"] for a in conclusivos), "achados": conclusivos,
            "na_borda_da_serie": [a for a in achados if a["no_limite_da_serie"]],
            "linhas_fora_por_documento_mascarado": fora_por_mascara,
            "_nota": f"série cobre {faixa[0]}–{faixa[1]}. Quem aparece só em {faixa[0]} ou "
                     f"{faixa[1]} sai do achado: pode ter começado antes ou continuado depois. "
                     f"Agrupa por RAIZ de CNPJ — 0,96% das raízes têm mais de uma razão social, "
                     f"e agrupar pelo nome inventaria 'exercício único' onde há continuidade"}


# ── pico anômalo de gasto num mercado específico ────────────────────────────────────────────

def pico_de_gasto_por_subelemento(db_path=None, fator: float = 5.0,
                                  piso: float = 5_000_000.0,
                                  fracao_novos: float = 0.70) -> dict:
    """Subelemento de despesa cujo gasto num exercício supera `fator` vezes a mediana dos demais.

    O subelemento (posições 5-8 da natureza) é o mercado concreto: 33.90.30.04 é vestuário e
    confecção, 33.90.30.07 é gêneros de alimentação. Uma compra pública tem sazonalidade, mas o
    volume de um mercado não salta de ordem de grandeza sem causa — e a causa pode ser legítima
    (programa novo, emergência sanitária) ou não (compra concentrada em janela, fornecedores que
    aparecem só naquele ano).

    A lente **não afirma irregularidade**: ela nomeia o mercado e o ano em que examinar, e
    devolve junto quantos fornecedores daquele pico aparecem em um só exercício — porque é a
    combinação "volume explode + fornecedores novos que somem" que distingue programa de
    anomalia.

    Achado que motivou a lente: **confecção (33.90.30.04) em 2021 — R$ 166.679.222,10**, contra
    R$ 11.024.608,05 em 2019 e R$ 17.779.630,96 em 2022.

    CORTE POR VARREDURA, não por convenção. Só a razão de volume marca demais — 28,7% dos
    subelementos com 3×, 16,2% com 5×. É a **combinação** com a renovação do elenco que
    discrimina, porque programa novo traz fornecedores conhecidos e anomalia traz gente que
    aparece uma vez:

    | razão | fornecedores novos | subelementos marcados |
    |---|---|---:|
    | ≥ 3× | qualquer | 28,7% |
    | ≥ 5× | qualquer | 16,2% |
    | ≥ 3× | ≥ 70% | 8,8% |
    | **≥ 5×** | **≥ 70%** | **6,6%** |
    | ≥ 5× | ≥ 90% | 3,7% |

    O padrão mais extremo do acervo é o subelemento 3937 em 2019: **R$ 122.478.212,79** contra
    R$ 1–2 milhões nos demais exercícios (**64×**), com **196 de 197 fornecedores (99,5%)
    aparecendo só naquele ano**.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        rows = con.execute(
            f"SELECT substr(natureza,5,4), exercicio, credor_documento, credor_nome, sum(pago) "
            f"FROM pcrj_despesa WHERE {filtro_sql()} GROUP BY 1,2,3,4").fetchall()
    finally:
        con.close()

    por_sub = defaultdict(lambda: defaultdict(float))
    forn = defaultdict(lambda: defaultdict(set))
    for sub, ano, doc, nome, pago in rows:
        por_sub[sub][ano] += pago
        raiz = re.sub(r"\D", "", str(doc or ""))[:8]
        forn[sub][ano].add(raiz or str(nome))

    achados, universo = [], 0
    for sub, anos in por_sub.items():
        if len(anos) < 3 or sum(anos.values()) < piso:
            continue                       # sem série não há "normal" contra o qual comparar
        universo += 1
        vals = sorted(anos.values())
        mediana = (vals[len(vals) // 2] if len(vals) % 2
                   else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2)
        if not mediana:
            continue
        ano_pico = max(anos, key=lambda a: anos[a])
        razao = anos[ano_pico] / mediana
        if razao < fator:
            continue
        # dos fornecedores do ano de pico, quantos só aparecem naquele ano?
        no_pico = forn[sub][ano_pico]
        outros = {f for a, s in forn[sub].items() if a != ano_pico for f in s}
        so_no_pico = no_pico - outros
        novos = len(so_no_pico) / len(no_pico) if no_pico else 0.0
        achados.append({
            "subelemento": sub, "ano_de_pico": ano_pico, "pago_no_pico": anos[ano_pico],
            "mediana_dos_exercicios": mediana, "razao": razao,
            "serie": {a: v for a, v in sorted(anos.items())},
            "fornecedores_no_pico": len(no_pico),
            "fornecedores_so_no_pico": len(so_no_pico),
            "fracao_de_fornecedores_novos": novos if no_pico else None,
            "elenco_renovado": novos >= fracao_novos,
        })
    achados.sort(key=lambda a: -a["pago_no_pico"])
    fortes = [a for a in achados if a["elenco_renovado"]]
    return {"lente": f"subelemento com pico de {fator:.0f}×+ a mediana E elenco de fornecedores "
                     f"renovado em {fracao_novos:.0%}+",
            "universo": universo, "n": len(fortes),
            "prevalencia": len(fortes) / universo if universo else None,
            "massa": sum(a["pago_no_pico"] for a in fortes), "achados": fortes,
            "corte_amplo": {"n": len(achados),
                            "prevalencia": len(achados) / universo if universo else None,
                            "achados": achados,
                            "_nota": "só o pico de volume, sem exigir renovação do elenco"},
            "_nota": "não afirma irregularidade: nomeia o MERCADO e o ANO em que examinar. "
                     "É a COMBINAÇÃO volume-explode + fornecedores-que-somem que discrimina — "
                     "só o volume marca 16,2% dos subelementos"}


# ── CONTROLE: a cascata da despesa é coerente? ──────────────────────────────────────────────

def cascata_coerente(db_path=None) -> dict:
    """CONTROLE de integridade, não detector: liquidado ≤ empenhado e pago ≤ liquidado.

    A Lei 4.320/64 impõe a ordem. Violação é **defeito de dado ou de execução**, e se houver
    muitas, nenhuma lente deste acervo é confiável — inclusive as que já publiquei.

    Medido em 30/08/2026: **0 violações em 78.595 linhas**. O resultado esperado é zero; se um
    dia deixar de ser, este controle é que avisa.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        total = con.execute("SELECT count(*) FROM pcrj_despesa").fetchone()[0]
        liq_maior = con.execute("SELECT count(*) FROM pcrj_despesa "
                                "WHERE liquidado > empenhado + 0.005").fetchone()[0]
        pago_maior = con.execute("SELECT count(*) FROM pcrj_despesa "
                                 "WHERE pago > liquidado + 0.005").fetchone()[0]
        negativos = con.execute("SELECT count(*) FROM pcrj_despesa WHERE empenhado < 0 "
                                "OR liquidado < 0 OR pago < 0").fetchone()[0]
        exemplos = con.execute(
            "SELECT exercicio, orgao, credor_nome, empenhado, liquidado, pago FROM pcrj_despesa "
            "WHERE liquidado > empenhado + 0.005 OR pago > liquidado + 0.005 LIMIT 10").fetchall()
    finally:
        con.close()
    violacoes = liq_maior + pago_maior + negativos
    return {"lente": "CONTROLE — coerência da cascata empenho ≥ liquidação ≥ pagamento",
            "universo": total, "n": violacoes,
            "prevalencia": violacoes / total if total else None,
            "massa": 0.0,
            "achados": [{"exercicio": e, "orgao": o, "credor": c, "empenhado": em,
                         "liquidado": li, "pago": pg} for e, o, c, em, li, pg in exemplos],
            "liquidado_acima_do_empenhado": liq_maior,
            "pago_acima_do_liquidado": pago_maior,
            "valores_negativos": negativos,
            "_nota": "resultado ESPERADO é zero. Diferente de zero invalida as demais lentes "
                     "deste acervo até que se explique"}


# ── qualidade cadastral do credor ───────────────────────────────────────────────────────────

def _digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _dv_cnpj_ok(c: str) -> bool:
    if len(c) != 14 or len(set(c)) == 1:
        return False
    for tam, pesos in ((12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
                       (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])):
        s = sum(int(c[i]) * pesos[i] for i in range(tam))
        d = 0 if s % 11 < 2 else 11 - s % 11
        if int(c[tam]) != d:
            return False
    return True


def _dv_cpf_ok(c: str) -> bool:
    if len(c) != 11 or len(set(c)) == 1:
        return False
    for tam in (9, 10):
        s = sum(int(c[i]) * (tam + 1 - i) for i in range(tam))
        d = 0 if s % 11 < 2 else 11 - s % 11
        if int(c[tam]) != d:
            return False
    return True


def qualidade_cadastral(db_path=None) -> dict:
    """CONTROLE de cadastro do credor: divergências que comprometem qualquer agregação por CNPJ.

    Quatro testes, todos sobre `pcrj_despesa`:

    1. **documento com razões sociais divergentes** — ou o cadastro está corrompido, ou houve
       troca de titularidade não refletida;
    2. **razão social com documentos divergentes** — duplicidade de cadastro; agregar por
       documento perde parte do fornecedor;
    3. **razão social de PJ sob documento de 11 dígitos** — "LTDA", "S.A.", "EIRELI" ou
       "CORPORATION" gravados sob CPF: erro de tipo de pessoa (é o caso da CHINA MEHECO);
    4. **dígito verificador inválido** — documento que não existe. Documento **mascarado** fica
       fora deste teste: não dá para validar o que está oculto, e reprová-lo seria inventar erro.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        rows = con.execute("SELECT credor_documento, credor_nome, sum(pago) FROM pcrj_despesa "
                           "GROUP BY 1,2").fetchall()
    finally:
        con.close()

    por_doc, por_nome = defaultdict(set), defaultdict(set)
    pago_doc = defaultdict(float)
    pj_sob_cpf, dv_ruim, mascarados = [], [], 0
    RX_PJ = re.compile(r"\b(ltda|s\.?\s?a\.?|eireli|corporation|s/a|me|epp|sociedade|"
                       r"compa?nhia|inc\b|llc\b)\b", re.I)
    for doc, nome, pago in rows:
        d = _digitos(doc)
        por_doc[str(doc)].add(str(nome))
        por_nome[str(nome)].add(str(doc))
        pago_doc[str(doc)] += (pago or 0.0)
        if "*" in str(doc or ""):
            mascarados += 1
            continue
        if len(d) == 11 and RX_PJ.search(str(nome or "")):
            pj_sob_cpf.append({"documento_len": 11, "credor": nome, "pago": pago or 0.0})
        if len(d) == 14 and not _dv_cnpj_ok(d):
            dv_ruim.append({"tipo": "CNPJ", "credor": nome, "pago": pago or 0.0})
        elif len(d) == 11 and not _dv_cpf_ok(d):
            dv_ruim.append({"tipo": "CPF", "credor": nome, "pago": pago or 0.0})

    doc_divergente = [{"documento_mascarado": "*" in d, "n_razoes": len(v),
                       "razoes": sorted(v)[:4], "pago": pago_doc[d]}
                      for d, v in por_doc.items() if len(v) > 1]
    nome_divergente = [{"credor": n, "n_documentos": len(v)}
                       for n, v in por_nome.items() if len(v) > 1]
    doc_divergente.sort(key=lambda a: -a["pago"])
    nome_divergente.sort(key=lambda a: -a["n_documentos"])
    return {"lente": "CONTROLE — qualidade cadastral do credor",
            "universo": len(por_doc),
            "n": len(doc_divergente) + len(nome_divergente) + len(pj_sob_cpf) + len(dv_ruim),
            "prevalencia": (len(doc_divergente) / len(por_doc)) if por_doc else None,
            "massa": sum(a["pago"] for a in doc_divergente),
            "achados": doc_divergente[:50],
            "documento_com_razoes_divergentes": len(doc_divergente),
            "razao_com_documentos_divergentes": len(nome_divergente),
            "pj_sob_documento_de_cpf": pj_sob_cpf[:20],
            "n_pj_sob_documento_de_cpf": len(pj_sob_cpf),
            "digito_verificador_invalido": dv_ruim[:20],
            "n_digito_verificador_invalido": len(dv_ruim),
            "documentos_mascarados_fora_do_teste": mascarados,
            "_nota": "documento MASCARADO não entra na validação de dígito: validar o que está "
                     "oculto inventaria erro. A prevalência publicada é a do teste 1"}


LENTES = (empenhado_sem_pagamento, superempenho, fornecedor_de_exercicio_unico,
          pico_de_gasto_por_subelemento)
CONTROLES = (cascata_coerente, qualidade_cadastral)


if __name__ == "__main__":
    print(f"{'lente':56s} {'casos':>7s} {'universo':>9s} {'preval.':>8s} {'massa':>20s}")
    print("─" * 104)
    for fn in LENTES + CONTROLES:
        r = fn()
        pv = f"{r['prevalencia']*100:.2f}%" if r["prevalencia"] is not None else "INDISP."
        print(f"{r['lente'][:56]:56s} {r['n']:7,} {r['universo']:9,} {pv:>8s} "
              f"R$ {moeda(r['massa']):>17s}")
