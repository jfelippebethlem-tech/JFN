# -*- coding: utf-8 -*-
"""Propostas GÊMEAS: markup uniforme, planilha derivada e trechos literalmente iguais.

PEDIDO DO DONO (2026-07-30), verbatim: "criar um detector de semelhança de propostas, se dois
concorrentes respondem com as mesmas frases, parágrafos, ou se simplesmente simulam uma proposta
alterando valores de forma fixa, como diferença de 5% em todos os itens por exemplo."

O QUE FOI ACHADO ANTES DE ESCREVER UMA LINHA. O detector **já existia** —
`compliance_agent/sei/conluio_propostas.py`, com markup uniforme (o exemplo dos 5% está no docstring
dele), preços quase idênticos e texto similar — e estava **ÓRFÃO**: os únicos hits fora do próprio
arquivo eram um comentário em `editais/screens_conluio.py:11` e um teste. Zero callers. Sexto caso do
padrão "construído, testado, nunca rodado" nesta casa.

E estava FAMINTO: a tabela `proposta_item` tinha **77 linhas** em toda a base.

TRÊS DEFEITOS/LACUNAS REAIS que estes testes travam:

  1. `_chave_item` DESCARTAVA NÚMEROS. Era `[w for w in desc.split() if len(w) > 3][:6]`, então
     "PARAFUSO INOX 3/8" e "PARAFUSO INOX 1/2" colidiam na mesma chave; com `setdefault`, só o
     primeiro item sobrevivia. Uma lista de 12 itens virava 1 par, caía abaixo do `min_itens` e o
     detector devolvia `None` — cegueira da chave, não ausência de conluio.
  2. Faltava o que o dono pediu de mais concreto: os TRECHOS iguais. O Jaccard dizia "0,87 similar";
     ninguém instaura processo com um índice. `frases_identicas` devolve o trecho verbatim.
  3. Faltava pegar markup quando a lista não casa inteira. `markup_linear` testa a FORMA (os pares
     caem numa reta pela origem, R²≈1 com coeficiente ≠1 = planilha derivada).
"""
from __future__ import annotations

from compliance_agent.sei import conluio_propostas as C


def _lista(pcts, base=100.0, n=6, fator=1.0):
    """Itens com MEDIDA no nome — é o que a chave antiga colapsava."""
    return [{"descricao": f"parafuso sextavado inox 3/{i}", "valor_unitario": (base + i * 7) * fator}
            for i in range(2, 2 + n)] if pcts is None else pcts


_A = _lista(None)
_B = _lista(None, fator=0.95)     # -5% em TODOS os itens: o exemplo literal do dono


# ── a chave do item ─────────────────────────────────────────────────────────────────────────────
def test_chave_do_item_distingue_a_MEDIDA():
    """Sem isto, uma planilha inteira colapsa num item e o detector devolve None calado."""
    chaves = {C._chave_item(x["descricao"]) for x in _A}
    assert len(chaves) == len(_A), (
        "itens que diferem só pela medida colapsaram na mesma chave — é o bug que fazia "
        "12 itens virarem 1 par e o detector emudecer"
    )


def test_item_sem_descricao_nao_inventa_chave():
    assert C._chave_item("") == ""
    assert C._chave_item("   ") == ""


# ── markup uniforme: o pedido literal ───────────────────────────────────────────────────────────
def test_diferenca_fixa_de_5_por_cento_em_todos_os_itens_e_pega():
    r = C.markup_uniforme(_A, _B)
    assert r is not None, "o caso que o dono descreveu não acendeu"
    assert r["pct"] == -5.0
    assert r["n_itens"] == len(_A)
    assert r["cv"] == 0.0


def test_dispersao_natural_de_mercado_NAO_acende():
    """Concorrência real não produz razão constante. Se acendesse aqui, marcaria a base inteira."""
    irregular = [{"descricao": x["descricao"],
                  "valor_unitario": x["valor_unitario"] * f}
                 for x, f in zip(_A, (0.88, 1.04, 0.97, 1.12, 0.91, 1.06))]
    assert C.markup_uniforme(_A, irregular) is None


def test_lista_curta_nao_sustenta_markup():
    """2 itens alinhados é coincidência barata; o piso existe para não virar falso positivo."""
    assert C.markup_uniforme(_A[:2], _B[:2]) is None


# ── planilha derivada com lista PARCIAL ─────────────────────────────────────────────────────────
def test_markup_linear_pega_planilha_derivada_que_o_cv_deixa_passar():
    """Faixa de preço LARGA + linhas baratas arredondadas: o cv cega, a regressão pega.

    Este é o cenário REAL de planilha de obra (R$ 8,50 a R$ 9.500,00). Quem copia a coluna do
    concorrente e multiplica arredonda os centavos das linhas baratas — porque é o que uma pessoa
    faz. O desvio relativo dos itens pequenos estoura o `cv ≤ 2%` e o padrão desaparece do
    `markup_uniforme`; a regressão pondera por magnitude e o recupera.

    (A hipótese óbvia — "um item fora da regra" — foi TESTADA E REPROVADA: outlier de +20% a +60%
    cega os dois. Não refazer por aquele caminho.)
    """
    vals = [8.5, 12.0, 47.0, 180.0, 650.0, 1900.0, 4200.0, 9500.0]
    a = [{"descricao": f"insumo tipo {i} ref {i}0", "valor_unitario": v} for i, v in enumerate(vals)]
    b = [{"descricao": x["descricao"],
          "valor_unitario": (round(x["valor_unitario"] * 1.12) if x["valor_unitario"] * 1.12 < 100
                             else x["valor_unitario"] * 1.12)} for x in a]

    assert C.markup_uniforme(a, b) is None, "o cenário tem de ser cego para o cv por item"
    r = C.markup_linear(a, b)
    assert r is not None, "a regressão devia recuperar o padrão que o cv perdeu"
    assert r["r2"] >= 0.995 and abs(r["pct"] - 12.0) < 1.0 and r["n_itens"] == len(a)


def test_markup_linear_nao_acende_em_preco_igual():
    """Coeficiente 1 é 'preço igual', que é outro indício (precos_identicos) — não este."""
    assert C.markup_linear(_A, [dict(x) for x in _A]) is None


# ── trechos literalmente iguais: a evidência citável ────────────────────────────────────────────
_TRECHO = ("Declaramos ainda que os precos ofertados incluem todos os tributos encargos sociais "
           "e demais despesas indiretas incidentes sobre o objeto licitado")


def test_frases_identicas_devolve_o_TRECHO_e_nao_so_um_numero():
    a = "A empresa ALFA apresenta sua proposta comercial para o presente certame. " + _TRECHO
    b = "A empresa BETA, com outra razao social e outro CNPJ, oferta o seguinte. " + _TRECHO
    r = C.frases_identicas(a, b)
    assert r is not None
    assert r["n_trechos"] >= 1
    assert any(_TRECHO.split(" incluem")[0][:40] in t for t in r["trechos"]), (
        "o trecho verbatim é a evidência que vai lado a lado no laudo — sem ele, é só um índice"
    )


def test_frase_curta_NAO_conta():
    """'conforme o edital' coincide em toda proposta do país. Foi assim que o P1 acusou 71%."""
    assert C.frases_identicas("conforme o edital.", "conforme o edital.") is None


def test_texto_sem_coincidencia_literal_nao_acende():
    a = "A empresa ALFA declara conhecer integralmente os termos do instrumento convocatorio."
    b = "Nossa sociedade informa estar ciente das condicoes estabelecidas no ato de convocacao."
    assert C.frases_identicas(a, b) is None


# ── exculpatórias: sem elas o detector marca metade da base ─────────────────────────────────────
def test_mercado_homogeneo_rebaixa_preco_identico_sem_silenciar():
    """Commodity/preço tabelado gera preço igual LEGÍTIMO. Rebaixa; nunca apaga o achado."""
    iguais = [dict(x) for x in _A]
    r = C.detectar([{"fornecedor": "ALFA", "itens": _A}, {"fornecedor": "BETA", "itens": iguais}],
                   mercado_homogeneo=True)
    pid = [i for i in r["indicios"] if i["tipo"] == "precos_identicos"]
    assert pid, "o indício não pode DESAPARECER com a exculpatória — só ser rebaixado"
    assert pid[0]["grau_rebaixado"] is True
    assert "ATENUANTE" in pid[0]["obs"]
    assert r["exculpatorias"]["mercado_homogeneo"] is True


def test_template_de_mercado_rebaixa_coincidencia_textual():
    a = "Proposta da ALFA para o certame em referencia. " + _TRECHO
    b = "Proposta da BETA para o certame em referencia. " + _TRECHO
    r = C.detectar([{"fornecedor": "ALFA", "texto": a}, {"fornecedor": "BETA", "texto": b}],
                   template_de_mercado=True)
    fi = [i for i in r["indicios"] if i["tipo"] == "frases_identicas"]
    assert fi and fi[0]["grau_rebaixado"] is True


# ── o mesmo fato não conta duas vezes ───────────────────────────────────────────────────────────
def test_markup_uniforme_e_linear_nao_contam_o_MESMO_fato_duas_vezes():
    """Indício contado em dobro é inflação de achado — a casa já pagou isso três vezes numa noite."""
    r = C.detectar([{"fornecedor": "ALFA", "itens": _A}, {"fornecedor": "BETA", "itens": _B}])
    tipos = [i["tipo"] for i in r["indicios"]]
    assert "markup_uniforme" in tipos
    assert "markup_linear" not in tipos


def test_proposta_unica_nao_produz_indicio():
    """Não há par: nada a comparar. Vazio por AUSÊNCIA de par, e o `ok` continua True."""
    r = C.detectar([{"fornecedor": "ALFA", "itens": _A}])
    assert r["ok"] is True and r["indicios"] == [] and r["n_propostas"] == 1


def test_nota_cita_os_detectores_irmaos_para_nao_reimplementar():
    """J2/J3/J5 cobrem faces vizinhas. A nota existe para o leitor não recriar o que já há."""
    nota = C.detectar([])["_nota"]
    for irmao in ("J2", "J3", "J5"):
        assert irmao in nota


def test_casa_o_mesmo_item_escrito_de_outro_jeito_mas_nunca_medida_diferente():
    """18/11/2026: com as 4.516 linhas das propostas SEI, 78% dos itens não têm número e cada fornecedor escreve a
    descrição do seu jeito — a chave exata casava quase nada (J9 = 0 por cegueira, não por ausência). Fallback:
    semelhança ≥ 90 COM as mesmas medidas, um-para-um. Controle negativo: 3/8 × 1/2 nunca casa."""
    from compliance_agent.sei import conluio_propostas as C
    a = [{"descricao": "CANETA ESFEROGRÁFICA AZUL CAIXA COM 50 UNIDADES", "valor_unitario": 30.0},
         {"descricao": "PAPEL A4 BRANCO 75G RESMA 500 FOLHAS", "valor_unitario": 25.0},
         {"descricao": "PARAFUSO SEXTAVADO INOX 3/8", "valor_unitario": 2.0}]
    b = [{"descricao": "Caneta esferografica azul - caixa com 50 unidades", "valor_unitario": 33.0},
         {"descricao": "Papel A4 75g branco resma c/ 500 folhas", "valor_unitario": 27.5},
         {"descricao": "Parafuso sextavado inox 1/2", "valor_unitario": 2.2}]
    pares = C._pares(a, b)
    assert (30.0, 33.0) in pares and (25.0, 27.5) in pares
    assert (2.0, 2.2) not in pares                                     # medida diferente: não é o mesmo item
    assert len(pares) == 2


def test_markup_linear_nao_dispara_com_cotacoes_parecidas_de_tamanhos_diferentes():
    """18/11/2026, caso REAL (490001/1289/2024, mobiliário urbano, 3 cotações): R² 0,997 e 0,9998 porque os itens
    vão de R$ 28 mil a R$ 200 mil — mas a razão B/A varia de 1,007 a 1,087 item a item: não é planilha derivada,
    é cotação parecida. R² pela origem mede o tamanho dos itens, não a constância da razão. Cada item tem de cair
    na reta dentro do arredondamento (1% ou R$ 1,00)."""
    from compliance_agent.sei import conluio_propostas as C
    a = [{"descricao": f"item {i}", "valor_unitario": v} for i, v in
         ((1, 144325.00), (2, 135818.25), (5, 28013.13), (6, 29005.71), (3, 200799.73))]
    b = [{"descricao": f"item {i}", "valor_unitario": v} for i, v in
         ((1, 156875.00), (2, 136757.35), (5, 28911.30), (6, 31023.50))]
    c = [{"descricao": f"item {i}", "valor_unitario": v} for i, v in
         ((1, 151855.00), (2, 140865.94), (5, 30586.26), (6, 30519.06), (3, 207549.30))]
    assert C.markup_linear(a, b) is None
    assert C.markup_linear(a, c) is None
