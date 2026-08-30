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
    por = defaultdict(dict)
    for doc, nome, ano, pago in rows:
        por[(str(doc), str(nome))][ano] = pago
    achados, universo = [], 0
    for (doc, nome), anos in por.items():
        total = sum(anos.values())
        if total < piso:
            continue
        universo += 1
        if len(anos) == 1:
            ano = next(iter(anos))
            achados.append({"cnpj": doc, "nome": nome, "exercicio": ano, "pago": total,
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
            "_nota": f"série cobre {faixa[0]}–{faixa[1]}. Quem aparece só em {faixa[0]} ou "
                     f"{faixa[1]} sai do achado: pode ter começado antes ou continuado depois"}


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


LENTES = (empenhado_sem_pagamento, superempenho, fornecedor_de_exercicio_unico)
CONTROLES = (cascata_coerente, qualidade_cadastral)


if __name__ == "__main__":
    print(f"{'lente':56s} {'casos':>7s} {'universo':>9s} {'preval.':>8s} {'massa':>20s}")
    print("─" * 104)
    for fn in LENTES + CONTROLES:
        r = fn()
        pv = f"{r['prevalencia']*100:.2f}%" if r["prevalencia"] is not None else "INDISP."
        print(f"{r['lente'][:56]:56s} {r['n']:7,} {r['universo']:9,} {pv:>8s} "
              f"R$ {moeda(r['massa']):>17s}")
