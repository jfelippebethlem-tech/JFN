"""Lentes de CONTRATO, LICITAÇÃO e TERCEIRO SETOR na Prefeitura do Rio.

Terceiro bloco do catálogo `docs/PCRJ-100-IDEIAS-DETECCAO.md` (famílias H, I e J). Os outros
dois estão em `tools/lentes_pcrj.py` (fornecedor e vínculo) e `tools/lentes_pcrj_execucao.py`
(execução orçamentária e qualidade do dado).

O QUE ESTE BLOCO **NÃO** PODE MEDIR — leia antes de concluir ausência
--------------------------------------------------------------------
- **Aditivo por valor está bloqueado na origem.** Em `pcrj_contratos` do Município,
  `valor_global` é idêntico a `valor_inicial` em **1.987 de 1.987 registros (100,00%)**. Zero
  contratos acima do teto de 25% do art. 125 da Lei 14.133/2021 NÃO é ausência de aditivo: é
  ausência de dado. Resta a contagem `num_aditivos`, que existe.
- **`amparo` é nulo em 2.449 de 2.449 licitações (100,00%)** — não dá para testar enquadramento
  de dispensa/inexigibilidade por esta base. O que dá é ler o texto do edital, e isso está em
  `tools/fracionamento_dispensa_pcrj.py`.
- **`tcerj_licitante` não tem a capital**: 0 de 126.251 registros. Licitante único não é testável.
- A janela de `pcrj_contratos` do Município é **2021–2026**, com 23 registros antes de 2024. A
  interseção com a despesa (2019–2023) é praticamente nula.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from compliance_agent.pcrj.universo import conectar
from compliance_agent.reporting.intel_base import moeda

RAIZ_PCRJ = "42498733"
_ONDE = f"substr(orgao_cnpj,1,8)='{RAIZ_PCRJ}'"


# ── contratos ───────────────────────────────────────────────────────────────────────────────

def aditivos_em_serie(db_path=None, minimo: int = 3) -> dict:
    """Contrato com `minimo` ou mais termos aditivos.

    Aditivo é lícito (art. 124 da Lei 14.133/2021). O que se examina é a **série**: contrato que
    recebe três, quatro, seis aditivos deixou de ser o contrato licitado — e a jurisprudência do
    TCU trata a sucessão de aditivos como indício de projeto básico deficiente ou de fuga à nova
    licitação.

    ⚠️ Só a CONTAGEM é medível. O valor dos aditivos está bloqueado: `valor_global` espelha
    `valor_inicial` em 100% dos registros municipais, então o teste do teto de 25% (art. 125) é
    **impossível nesta base**, não negativo.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        rows = con.execute(
            f"SELECT numero_controle_pncp, ano, fornecedor_nome, fornecedor_documento, objeto, "
            f"valor_global, num_aditivos, data_assinatura, vigencia_ini, vigencia_fim, tipo "
            f"FROM pcrj_contratos WHERE {_ONDE}").fetchall()
    finally:
        con.close()
    universo = len(rows)
    achados = [{"contrato": c, "ano": a, "fornecedor": f, "cnpj": d, "objeto": o,
                "valor": v or 0.0, "n_aditivos": n, "assinatura": ass,
                "vigencia": f"{vi} a {vf}", "tipo": t}
               for c, a, f, d, o, v, n, ass, vi, vf, t in rows if (n or 0) >= minimo]
    achados.sort(key=lambda x: (-x["n_aditivos"], -x["valor"]))
    com_algum = sum(1 for r in rows if (r[6] or 0) >= 1)
    return {"lente": f"contrato com {minimo}+ termos aditivos",
            "universo": universo, "n": len(achados),
            "prevalencia": len(achados) / universo if universo else None,
            "massa": sum(a["valor"] for a in achados), "achados": achados,
            "com_ao_menos_um_aditivo": com_algum,
            "_nota": "só a CONTAGEM é medível — `valor_global` espelha `valor_inicial` em 100% "
                     "dos registros, o que torna o teto de 25% (art. 125) intestável nesta base"}


def vigencia_acima_do_prazo(db_path=None, anos: int = 5) -> dict:
    """Contrato com vigência superior a `anos`.

    A Lei 14.133/2021 admite até 5 anos para serviços contínuos (art. 107) e até 10 anos nas
    hipóteses do art. 108/109. Passar de 5 não é, por si, ilegalidade — exige o enquadramento
    correto. A lente ordena para conferência.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        rows = con.execute(
            f"SELECT numero_controle_pncp, fornecedor_nome, objeto, valor_global, "
            f"vigencia_ini, vigencia_fim, tipo FROM pcrj_contratos WHERE {_ONDE} "
            f"AND vigencia_ini IS NOT NULL AND vigencia_fim IS NOT NULL").fetchall()
    finally:
        con.close()
    # Medir por ANO-CALENDÁRIO é grosseiro e produz falso positivo: 2026-09-23 -> 2031-09-22 dá
    # "5" na subtração de anos, mas são 5 anos MENOS UM DIA — dentro do limite. Há 65 contratos
    # exatamente nesse formato. A conta correta é em DIAS.
    import datetime
    limite_dias = round(anos * 365.25)
    achados = []
    for c, f, o, v, vi, vf in ((r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows):
        try:
            ini = datetime.date.fromisoformat(str(vi)[:10])
            fim = datetime.date.fromisoformat(str(vf)[:10])
        except ValueError:
            continue
        dias = (fim - ini).days
        if dias > limite_dias:
            achados.append({"contrato": c, "fornecedor": f, "objeto": o, "valor": v or 0.0,
                            "vigencia_ini": vi, "vigencia_fim": vf, "duracao_dias": dias,
                            "duracao_anos": round(dias / 365.25, 2)})
    achados.sort(key=lambda a: -a["duracao_dias"])
    return {"lente": f"contrato com vigência superior a {anos} anos",
            "universo": len(rows), "n": len(achados),
            "prevalencia": len(achados) / len(rows) if rows else None,
            "massa": sum(a["valor"] for a in achados), "achados": achados,
            "_nota": "duração medida em DIAS (limite = anos × 365,25). Por ano-calendário, 65 "
                     "contratos de '2026-09-23 a 2031-09-22' apareceriam como 5 anos quando são "
                     "5 anos menos um dia. Acima do limite exige enquadramento nos arts. 107 a "
                     "109 da Lei 14.133 — a lente ordena, não afirma ilegalidade"}


def sazonalidade_das_assinaturas(db_path=None) -> dict:
    """MEDIDA — em que meses o Município assina contrato, e qual é o pico.

    A hipótese que eu vinha testando era a *corrida de dezembro*: assinar às pressas para não
    perder dotação, com pesquisa de preços comprimida e execução empurrada para o exercício
    seguinte. Dezembro de fato tem **1,75×** o esperado sob distribuição uniforme (290 contra
    166).

    **Mas dezembro não é o pico.** A série mensal inteira mostra **março com 336** assinaturas
    contra 290 de dezembro. Eu teria publicado "corrida de dezembro" sobre um mês que é o
    segundo. Por isso esta função devolve a série completa e nomeia o **pico medido**, em vez de
    partir do mês que a hipótese esperava encontrar.

    Continua sendo MEDIDA, não alarme: sazonalidade de assinatura tem explicações
    administrativas legítimas (ciclo orçamentário, renovação anual de contratos contínuos).
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        rows = con.execute(
            f"SELECT data_assinatura, valor_global FROM pcrj_contratos WHERE {_ONDE} "
            f"AND data_assinatura IS NOT NULL AND data_assinatura <> ''").fetchall()
    finally:
        con.close()
    por_mes = defaultdict(lambda: [0, 0.0])
    for dt, v in rows:
        try:
            m = int(str(dt)[5:7])
        except ValueError:
            continue
        por_mes[m][0] += 1
        por_mes[m][1] += (v or 0.0)
    total = sum(q for q, _ in por_mes.values())
    esperado = total / 12 if total else 0
    serie = [{"mes": m, "contratos": q, "valor": v, "share": q / total if total else None,
              "razao_vs_uniforme": (q / esperado) if esperado else None}
             for m, (q, v) in sorted(por_mes.items())]
    pico = max(serie, key=lambda x: x["contratos"]) if serie else None
    dez = por_mes.get(12, [0, 0.0])
    return {"lente": "MEDIDA — sazonalidade das assinaturas de contrato",
            "universo": total, "n": pico["contratos"] if pico else 0,
            "prevalencia": (pico["contratos"] / total) if (pico and total) else None,
            "massa": pico["valor"] if pico else 0.0,
            "achados": serie,
            "mes_de_pico": pico["mes"] if pico else None,
            "esperado_se_uniforme": esperado,
            "dezembro": {"contratos": dez[0], "valor": dez[1],
                         "razao_vs_uniforme": (dez[0] / esperado) if esperado else None},
            "_nota": "o pico é MEDIDO, não presumido: dezembro tem 1,75× o esperado, mas MARÇO "
                     "tem mais assinaturas. Sazonalidade tem causa administrativa legítima "
                     "(ciclo orçamentário, renovação anual) — é medida, não alarme"}


def contrato_assinado_apos_o_inicio_da_vigencia(db_path=None) -> dict:
    """CONTROLE — contrato cuja assinatura é posterior ao início da própria vigência.

    Contrato retroativo: a execução começou antes do instrumento. É vício formal e indício de
    que o serviço já vinha sendo prestado sem cobertura.

    Medido em 30/08/2026: **0 casos**. Resultado esperado é zero; o controle existe para avisar
    quando deixar de ser.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        rows = con.execute(
            f"SELECT numero_controle_pncp, fornecedor_nome, data_assinatura, vigencia_ini, "
            f"valor_global FROM pcrj_contratos WHERE {_ONDE} AND data_assinatura IS NOT NULL "
            f"AND vigencia_ini IS NOT NULL AND data_assinatura > vigencia_ini").fetchall()
        universo = con.execute(f"SELECT count(*) FROM pcrj_contratos WHERE {_ONDE}").fetchone()[0]
    finally:
        con.close()
    return {"lente": "CONTROLE — contrato assinado APÓS o início da vigência (retroativo)",
            "universo": universo, "n": len(rows),
            "prevalencia": len(rows) / universo if universo else None,
            "massa": sum((r[4] or 0.0) for r in rows),
            "achados": [{"contrato": c, "fornecedor": f, "assinatura": a, "vigencia_ini": vi,
                         "valor": v or 0.0} for c, f, a, vi, v in rows],
            "_nota": "resultado esperado é zero"}


# ── licitação ───────────────────────────────────────────────────────────────────────────────

def vencedor_contumaz(db_path=None, minimo: int = 5) -> dict:
    """Fornecedor vencedor em `minimo` ou mais certames do Município.

    Ganhar muito não é irregularidade — pode ser eficiência. É sinal de **onde olhar**: o
    fornecedor recorrente concentra o risco de direcionamento, e o cruzamento com as demais
    lentes (sanção, porte, vínculo) é o que dá sentido ao número.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        rows = con.execute(
            "SELECT pr.fornecedor_cnpj, pr.fornecedor_nome, pr.certame, pr.valor_homologado "
            "FROM pncp_resultado pr JOIN edital_documento ed "
            "ON ed.numero_controle_pncp = pr.certame "
            f"WHERE substr(ed.orgao_cnpj,1,8)='{RAIZ_PCRJ}' AND pr.fornecedor_cnpj IS NOT NULL"
        ).fetchall()
    finally:
        con.close()
    por = defaultdict(lambda: {"certames": set(), "valor": 0.0, "nome": None})
    for cnpj, nome, cert, v in rows:
        d = re.sub(r"\D", "", str(cnpj))
        por[d]["certames"].add(cert)
        por[d]["valor"] += (v or 0.0)
        por[d]["nome"] = nome
    achados = [{"cnpj": d, "nome": x["nome"], "n_certames": len(x["certames"]),
                "homologado": x["valor"]}
               for d, x in por.items() if len(x["certames"]) >= minimo]
    achados.sort(key=lambda a: (-a["n_certames"], -a["homologado"]))
    return {"lente": f"fornecedor vencedor em {minimo}+ certames do Município",
            "universo": len(por), "n": len(achados),
            "prevalencia": len(achados) / len(por) if por else None,
            "massa": sum(a["homologado"] for a in achados), "achados": achados,
            "_nota": "ganhar muito não é irregularidade — é onde olhar. Cruzar com sanção, porte "
                     "e vínculo é o que dá sentido ao número"}


def estimativa_fora_de_escala(db_path=None, fracao_do_orcamento: float = 0.10) -> dict:
    """Licitação cujo valor estimado é impossível diante do próprio orçamento do Município.

    Serve a dois propósitos, e o segundo costuma ser o verdadeiro: (a) superestimativa que
    inflaria a disputa; (b) **erro grave de dado**, que contamina qualquer média calculada sobre
    a base. Medido: há uma dispensa com **R$ 347.037.696.000,00** estimados — sozinha, ela move a
    média das dispensas do Município para R$ 307.148.883,40.

    A âncora é o ORÇAMENTO, não um percentil. Tentei primeiro "100× a mediana" e marquei 10,43%
    do acervo: a mediana das licitações municipais é R$ 62.400,00 (a maioria é dispensa pequena),
    então 100× ela é só o p90 — não é outlier, é a cauda normal. O teste que discrimina compara
    a estimativa com o **maior gasto anual efetivo do Município** medido em `pcrj_despesa`:
    estimar uma fração relevante do orçamento inteiro num único certame é implausível.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        rows = con.execute(
            f"SELECT numero_controle_pncp, ano, modalidade, objeto, valor_estimado, situacao "
            f"FROM pcrj_licitacoes WHERE {_ONDE} AND valor_estimado IS NOT NULL "
            f"AND valor_estimado > 0").fetchall()
        orcamento = con.execute("SELECT max(t) FROM (SELECT sum(pago) t FROM pcrj_despesa "
                                "WHERE pago > 0 GROUP BY exercicio)").fetchone()[0] or 0.0
    finally:
        con.close()
    if not rows or not orcamento:
        return {"lente": "valor estimado fora de escala", "universo": len(rows), "n": 0,
                "prevalencia": None, "massa": 0.0, "achados": [],
                "_indisponivel": "sem orçamento anual medido para servir de âncora"}
    teto = fracao_do_orcamento * orcamento
    achados = [{"certame": c, "ano": a, "modalidade": m, "objeto": o, "valor_estimado": v,
                "situacao": s, "vezes_o_orcamento_anual": v / orcamento}
               for c, a, m, o, v, s in rows if v > teto]
    achados.sort(key=lambda x: -x["valor_estimado"])
    return {"lente": f"valor estimado acima de {fracao_do_orcamento:.0%} do maior gasto anual "
                     f"do Município",
            "universo": len(rows), "n": len(achados),
            "prevalencia": len(achados) / len(rows) if rows else None,
            "massa": sum(a["valor_estimado"] for a in achados), "achados": achados,
            "orcamento_anual_de_referencia": orcamento,
            "_nota": "âncora é o ORÇAMENTO medido, não percentil: '100× a mediana' marcava 10,43% "
                     "porque a mediana municipal é R$ 62.400,00. O achado costuma ser ERRO DE "
                     "DADO, e erro de dado contamina toda média calculada sobre esta base"}


# Termos que deixam o objeto ABERTO: o que entra neles se decide depois da licitação, e é aí
# que o direcionamento cabe.
_RX_OBJETO_ABERTO = re.compile(
    r"\b(diversos|diversas|variados|variadas|afins|congeneres|correlatos|similares|"
    r"entre outros|e outros|dentre outros|demais|assemelhados|em geral|gerais|etc)\b", re.I)


def objeto_generico(db_path=None) -> dict:
    """Licitação cujo objeto fica ABERTO — o que se compra se define depois.

    Objeto impreciso impede pesquisa de preços, comparação de propostas e fiscalização, e é o
    solo em que o direcionamento cresce. O art. 40, §1º, da Lei 14.133/2021 exige objeto
    definido de forma sucinta e clara.

    ⚠️ RÉGUA TROCADA, e a primeira fica registrada porque o erro é instrutivo. Comecei medindo
    **brevidade** — objeto com menos de 3 palavras de conteúdo. Marcava **12,33%** do acervo e o
    topo era *"Aquisição de MOBILIÁRIO ESCOLAR"* (R$ 144,25 mi), *"Aquisição de livros
    didáticos"*, *"Absorvente Higiênico"*. Todos **claros**. Genericidade não é brevidade: um
    objeto curto pode ser preciso, e um objeto longo pode não dizer nada.

    A régua que discrimina procura os termos que deixam o objeto **aberto** — "diversos",
    "afins", "congêneres", "entre outros", "serviços gerais". Marca **7,27%**, e o topo passa a
    ser *"execução de serviços gerais de manutenção"* (R$ 163,68 mi) e *"aquisição de
    medicamentos... com entre outros"*.

    Segue sendo ESTRATO DE ATENÇÃO, não alarme: 7% do acervo é muito para fila. Serve cruzado
    com valor e com as demais lentes.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        rows = con.execute(
            f"SELECT numero_controle_pncp, ano, objeto, valor_estimado, modalidade "
            f"FROM pcrj_licitacoes WHERE {_ONDE}").fetchall()
    finally:
        con.close()
    achados = []
    for c, a, obj, v, m in rows:
        s = unicodedata.normalize("NFKD", str(obj or "")).encode("ascii", "ignore").decode()
        achado = _RX_OBJETO_ABERTO.search(s)
        if achado:
            achados.append({"certame": c, "ano": a, "objeto": obj, "valor_estimado": v or 0.0,
                            "modalidade": m, "termo_aberto": achado.group(0).lower()})
    achados.sort(key=lambda x: -x["valor_estimado"])
    return {"lente": "objeto de licitação com termo que o deixa ABERTO",
            "universo": len(rows), "n": len(achados),
            "prevalencia": len(achados) / len(rows) if rows else None,
            "massa": sum(a["valor_estimado"] for a in achados), "achados": achados,
            "_nota": "ESTRATO de atenção, não alarme: 7% do acervo é muito para ordenar fila "
                     "sozinho. A régua de BREVIDADE foi descartada — marcava 12,33% e o topo era "
                     "'Aquisição de MOBILIÁRIO ESCOLAR', que é claro"}


# ── terceiro setor ──────────────────────────────────────────────────────────────────────────

def concentracao_do_terceiro_setor(db_path=None, top: int = 10) -> dict:
    """Concentração das transferências a entidades privadas sem fins lucrativos (modalidade 50).

    Não é lente de irregularidade: é de **superfície**. Delimita quanto do orçamento sai por
    transferência (fora, portanto, do universo contratual e das lentes de licitação) e em quantas
    mãos. Repasse concentrado não é ilícito — mas define onde a fiscalização da Lei 13.019/2014
    (prestação de contas de parceria) tem mais a perder se falhar.
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        rows = con.execute(
            "SELECT credor_documento, credor_nome, sum(pago) FROM pcrj_despesa "
            "WHERE substr(natureza,3,2)='50' AND pago > 0 GROUP BY 1,2").fetchall()
        total_geral = con.execute("SELECT sum(pago) FROM pcrj_despesa WHERE pago > 0").fetchone()[0]
    finally:
        con.close()
    por = defaultdict(float)
    nomes = {}
    for doc, nome, p in rows:
        chave = (str(doc), str(nome))           # (documento, NOME): a máscara colide
        por[chave] += p
        nomes[chave] = nome
    ordenado = sorted(por.items(), key=lambda x: -x[1])
    total = sum(por.values())
    acum, n_para_metade = 0.0, 0
    for _, v in ordenado:
        acum += v
        n_para_metade += 1
        if acum >= total / 2:
            break
    return {"lente": "concentração das transferências a entidades privadas (modalidade 50)",
            "universo": len(por), "n": n_para_metade,
            "prevalencia": n_para_metade / len(por) if por else None,
            "massa": total,
            "achados": [{"entidade": nomes[k], "recebido": v, "share": v / total if total else None}
                        for k, v in ordenado[:top]],
            "share_do_orcamento_total": total / total_geral if total_geral else None,
            "_nota": "`n` é quantas entidades bastam para somar METADE do repasse — a medida de "
                     "concentração. Não é lente de irregularidade, é de superfície"}


def entidade_paga_como_servico(db_path=None, razao_minima: float = 10.0,
                               piso: float = 1_000_000.0) -> dict:
    """Entidade sem fins lucrativos que recebe muito mais como SERVIÇO do que como parceria.

    Uma organização da sociedade civil pode receber do poder público por duas portas:
    **transferência** (modalidade 50), que aciona o regime da Lei 13.019/2014 — chamamento
    público, plano de trabalho, prestação de contas específica —, ou **contrato de serviço**
    (3390.39), que segue a Lei 14.133 e o regime de contrato de gestão da Lei 9.637/98.

    Receber pelas duas portas é **a norma, não o desvio**: medido, **243 de 427 entidades
    (56,9%)** fazem isso. Essa hipótese está descartada por prevalência.

    O que discrimina é a **proporção invertida** — a entidade que recebe quase tudo como serviço
    e quase nada como parceria. Pode ser legítimo (organização social com contrato de gestão é
    contratada, não conveniada) ou pode ser a via que dispensa o chamamento público. A lente
    ordena para exame.

    Varredura da razão serviço/transferência, com serviço >= R$ 1.000.000,00:

    | razão | entidades | % de 427 | massa |
    |---|---:|---:|---:|
    | >= 1x | 12 | 2,81% | R$ 361.987.124,43 |
    | >= 3x | 11 | 2,58% | R$ 358.172.505,29 |
    | **>= 10x** | **5** | **1,17%** | **R$ 309.826.411,44** |
    | >= 100x | 2 | 0,47% | R$ 123.623.020,00 |
    """
    con = conectar(db_path or "data/compliance.db")
    try:
        transf, servico, nomes = defaultdict(float), defaultdict(float), {}
        for doc, nome, p in con.execute(
                "SELECT credor_documento, credor_nome, sum(pago) FROM pcrj_despesa "
                "WHERE substr(natureza,3,2)='50' AND pago > 0 GROUP BY 1,2"):
            r = re.sub(r"\D", "", str(doc or ""))[:8]
            if len(r) == 8:
                transf[r] += p
                nomes[r] = nome
        for doc, nome, p in con.execute(
                "SELECT credor_documento, credor_nome, sum(pago) FROM pcrj_despesa "
                "WHERE substr(natureza,3,2)='90' AND substr(natureza,5,2)='39' AND pago > 0 "
                "GROUP BY 1,2"):
            r = re.sub(r"\D", "", str(doc or ""))[:8]
            if r in transf:
                servico[r] += p
                nomes.setdefault(r, nome)
    finally:
        con.close()
    achados = [{"entidade": nomes[r], "raiz": r, "pago_como_servico": servico[r],
                "pago_como_transferencia": transf[r], "razao": servico[r] / transf[r]}
               for r in servico
               if transf[r] > 0 and servico[r] >= piso and servico[r] / transf[r] >= razao_minima]
    achados.sort(key=lambda a: -a["pago_como_servico"])
    return {"lente": f"entidade sem fins lucrativos com {razao_minima:.0f}x+ mais recebimento "
                     f"como servico do que como parceria",
            "universo": len(transf), "n": len(achados),
            "prevalencia": len(achados) / len(transf) if transf else None,
            "massa": sum(a["pago_como_servico"] for a in achados), "achados": achados,
            "recebem_pelas_duas_portas": len(servico),
            "_nota": "receber pelas duas portas e a NORMA (56,9% das entidades) — hipotese "
                     "descartada por prevalencia. O que discrimina e a proporcao invertida. "
                     "Contrato de gestao de organizacao social e legitimo nesta natureza: a "
                     "lente ordena exame, nao afirma fuga ao chamamento publico"}


LENTES = (aditivos_em_serie, vigencia_acima_do_prazo, sazonalidade_das_assinaturas,
          vencedor_contumaz,
          estimativa_fora_de_escala, objeto_generico, concentracao_do_terceiro_setor,
          entidade_paga_como_servico)
CONTROLES = (contrato_assinado_apos_o_inicio_da_vigencia,)


if __name__ == "__main__":
    print(f"{'lente':58s} {'casos':>7s} {'universo':>9s} {'preval.':>8s} {'massa':>20s}")
    print("─" * 106)
    for fn in LENTES + CONTROLES:
        r = fn()
        pv = f"{r['prevalencia']*100:.2f}%" if r["prevalencia"] is not None else "INDISP."
        print(f"{r['lente'][:58]:58s} {r['n']:7,} {r['universo']:9,} {pv:>8s} "
              f"R$ {moeda(r['massa']):>17s}")
