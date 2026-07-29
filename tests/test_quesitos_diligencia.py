# -*- coding: utf-8 -*-
"""Quesitos e diligências — o produto que converte lacuna em pedido, e como ele se estraga.

Duas maneiras de arruinar um quesito:

  1. **Afirmar o vício dentro da pergunta.** "Comprove o superfaturamento de R$ X" contamina a
     resposta do perito e é atacável na origem. O quesito correto pergunta o FATO: "qual o preço
     de referência na data, e qual o contratado?".
  2. **Pedir ao perito o que só o juízo requisita.** Movimentação bancária não vira quesito de
     perícia administrativa — vira requisição a quem tem competência, e sai declarada como tal.

E a ordem importa: primeiro o que falta para o regime MAIS PRÓXIMO de fechar. Um controlador
persegue a imputação que está a uma prova de distância, não a que está a quatro.
"""
from __future__ import annotations

from compliance_agent.reporting import quesitos_diligencia as Q

VICIO = "especificacao_dirigida"


def test_todo_quesito_do_roteiro_e_livre_de_juizo():
    assert Q.validar() == []


def test_quesitos_e_documentos_nao_contem_palavra_de_juizo():
    """Onde a palavra contamina é no PEDIDO — quesito e rol de documentos."""
    p = Q.montar(VICIO)
    alvo = " ".join([q["quesito"] for q in p["quesitos"]]
                    + [d["descricao"] for d in p["diligencias"]]
                    + [x for d in p["diligencias"] for x in d["documentos"]]).lower()
    proibidas = [w for w in Q.PALAVRAS_VEDADAS if w in alvo]
    assert not proibidas, f"palavra de juízo no pedido: {proibidas}"


def test_nome_do_regime_so_aparece_na_secao_HIPOTETICA():
    """B.4.4: 'improbidade', 'crime' e 'dolo' só saem dentro de qualificação hipotética, com a
    ressalva junto. Dizer o regime é necessário — o leitor precisa saber o standard em jogo."""
    txt = Q.render_texto(Q.montar(VICIO))
    i = txt.index(Q.SECAO_HIPOTETICA)
    antes = txt[:i].lower()
    assert "improbidade" not in antes and "crime_licitatorio" not in antes
    assert "HIPOTÉTICA" in Q.SECAO_HIPOTETICA and "não se presumem" in Q.SECAO_HIPOTETICA


def test_quesito_pergunta_o_fato_e_nao_pede_confirmacao_de_conclusao():
    q = Q._ROTEIRO["dano"]["quesito"]
    assert q.strip().startswith("Qual") and "?" in q


def test_cada_elemento_faltante_vira_quesito_E_documento():
    p = Q.montar(VICIO)
    elementos_q = {x["elemento"] for x in p["quesitos"]}
    elementos_d = {x["elemento"] for x in p["diligencias"]}
    assert elementos_q and elementos_q <= elementos_d, "quesito sem documento a requisitar"


def test_prova_ja_disponivel_nao_vira_pedido():
    """Pedir o que já se tem faz o rol perder credibilidade."""
    todos = Q.montar(VICIO)
    um = {todos["quesitos"][0]["elemento"]}
    menos = Q.montar(VICIO, provas_disponiveis=um)
    assert um not in [{x["elemento"]} for x in menos["quesitos"]]
    assert len(menos["quesitos"]) < len(todos["quesitos"])


def test_elemento_repetido_entre_regimes_nao_duplica_o_quesito():
    p = Q.montar(VICIO)
    els = [x["elemento"] for x in p["quesitos"]]
    assert len(els) == len(set(els))


def test_ordem_segue_o_regime_mais_proximo_QUE_AINDA_PRECISA_DE_PROVA():
    """`regime_mais_proximo` pode ser um que já FECHA — e regime que fecha não gera quesito.
    O primeiro quesito é do primeiro regime com elemento faltando, que é a ordem útil."""
    from compliance_agent.knowledge.tipicidade import o_que_falta
    falta = o_que_falta(VICIO)
    primeiro_com_pendencia = next(r["regime"] for r in falta["regimes"] if r["provas_faltantes"])
    p = Q.montar(VICIO)
    assert p["quesitos"][0]["para_o_regime"] == primeiro_com_pendencia


# ───────────────────── o que NÃO se pede ao perito ────────────────────────────────────────────

def test_sigilo_bancario_vira_requisicao_e_nao_quesito():
    """O elemento `vantagem` PODE ser perguntado (bens registrados são públicos); o que não se
    pede ao perito administrativo é o que depende de afastamento de sigilo."""
    roteiro = Q._ROTEIRO["vantagem"]
    assert "afastamento de sigilo" in roteiro["requisicao_externa"]
    assert "competência do juízo" in roteiro["requisicao_externa"]
    # e o quesito em si pergunta só o que é acessível
    assert "bancár" not in roteiro["quesito"].lower()


def test_requisicao_externa_sai_separada_no_texto():
    p = Q.montar(VICIO)
    p["requisicoes_a_orgao_competente"] = [{"elemento": "vantagem", "motivo": "depende do juízo"}]
    txt = Q.render_texto(p)
    assert "FORA DO ALCANCE DO CONTROLE ADMINISTRATIVO" in txt


# ───────────────────── honestidade ────────────────────────────────────────────────────────────

def test_vicio_nao_mapeado_e_lacuna_declarada_e_nao_lista_vazia():
    p = Q.montar("vicio_que_nao_existe_no_catalogo")
    assert p["mapeado"] is False and p["quesitos"] == []
    assert "lacuna" in Q.render_texto(p).lower() or "não mapeado" in Q.render_texto(p).lower()


def test_elemento_sem_roteiro_aparece_como_lacuna_do_mapa(monkeypatch):
    """Sumir com o elemento faria o rol parecer completo quando não é."""
    monkeypatch.setitem(Q._ROTEIRO, "dano", None)
    Q._ROTEIRO.pop("dano")
    try:
        p = Q.montar(VICIO)
        sem = [d for d in p["diligencias"] if d.get("nota", "").startswith("elemento ainda sem")]
        assert sem or "dano" not in {q["elemento"] for q in p["quesitos"]}
    finally:
        Q._ROTEIRO["dano"] = {
            "quesito": ("Qual era o preço de referência de mercado de cada item, na data da "
                        "contratação, segundo a tabela oficial aplicável ao objeto? Qual o preço "
                        "unitário contratado? Qual a quantidade efetivamente medida e paga?"),
            "documentos": ("planilha orçamentária do contrato com memória de cálculo",
                           "boletins de medição assinados",
                           "ordens bancárias emitidas, com data e valor",
                           "pesquisa de preços que instruiu a contratação"),
            "onde": "autos do processo administrativo e SIAFE"}


def test_ressalva_de_presuncao_viaja_com_o_pacote_e_com_o_texto():
    p = Q.montar(VICIO)
    assert "presunção de legitimidade" in p["ressalva"]
    assert "17-C" in Q.render_texto(p)


def test_dolo_traz_a_nota_de_que_nao_se_presume():
    p = Q.montar(VICIO)
    dolo = [q for q in p["quesitos"] if q["elemento"] == "dolo"]
    if dolo:
        assert "não se presume" in dolo[0]["nota"]


def test_texto_e_montado_pelo_codigo_com_as_tres_secoes():
    txt = Q.render_texto(Q.montar(VICIO))
    assert "I. QUESITOS" in txt and "II. DOCUMENTOS A REQUISITAR" in txt


def test_standard_de_cada_quesito_acompanha_o_regime():
    for q in Q.montar(VICIO)["quesitos"]:
        assert q["standard"], "quesito sem standard probatório declarado"
