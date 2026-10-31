# -*- coding: utf-8 -*-
"""Perícia tripla — jurídica, forense, financeira.

O que estes testes protegem:
1. o CORTE DE CAPTURA. Sem ele, "falta o edital" pode ser "nossa captura não trouxe o edital", e a
   lente acusaria a Administração de um vício que é nosso. 2.066 de 3.259 lidos passam no corte;
2. a ORDENAÇÃO POR GRAVIDADE. Falta de pesquisa de preços (3,9%, peso 5) tem de vir antes de falta
   de instrumento (54,8%, peso 1) — sinal raro ordena, sinal comum descreve.
"""
import json
import sqlite3


def _banco(falta, numero="030001/000001/2025"):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE sei_leitura_dupla (numero_sei TEXT, ia TEXT)")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (processo TEXT, valor REAL, status TEXT,"
                " nome_credor TEXT)")
    ia = json.dumps({"interpretacao": {"o_que_e": "Aquisição de material.",
                                       "o_que_falta": falta}})
    con.execute("INSERT INTO sei_leitura_dupla VALUES (?,?)", (numero, ia))
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,1e6,'Contabilizado','X')",
                (f"SEI-{numero}",))
    return con


def test_pesquisa_de_precos_pesa_mais_que_instrumento(monkeypatch):
    """Sinal raro ordena a fila; sinal comum descreve o contexto."""
    from tools import pericia_tripla as p
    monkeypatch.setattr(p, "captura_completa", lambda: {"030001/000001/2025"})

    caro = p.periciar(_banco("Falta a pesquisa de preços que demonstre vantajosidade."))
    # "instrumento contratual" isolado, sem a palavra "cópia" — que também casaria "cadeia
    # documental" (peso 2) e somaria 3. A soma de marcas é INTENCIONAL: um processo a que faltam
    # duas coisas pesa mais que o que carece de uma só. O teste isola para medir a régua.
    comum = p.periciar(_banco("Falta o instrumento contratual que ampare a despesa."))
    assert caro[0]["peso"] > comum[0]["peso"], "pesquisa de preços deveria pesar mais"
    assert caro[0]["peso"] == 5 and comum[0]["peso"] == 1


def test_marcas_SOMAM_quando_faltam_varias_coisas(monkeypatch):
    """Dois documentos ausentes pesam mais que um — foi o que meu primeiro teste não previu."""
    from tools import pericia_tripla as p
    monkeypatch.setattr(p, "captura_completa", lambda: {"030001/000001/2025"})
    r = p.periciar(_banco("Falta cópia do contrato que ampare a despesa."))
    # casa "instrumento" (1) + "cadeia documental" (2), porque diz *cópia* de um documento citado
    assert r[0]["peso"] == 3 and len(r[0]["marcas"]) == 2


def test_corte_de_captura_exclui_processo_nao_completo(monkeypatch):
    """Sem o corte, lacuna DA CAPTURA vira acusação contra a Administração."""
    from tools import pericia_tripla as p
    monkeypatch.setattr(p, "captura_completa", lambda: set())     # nenhum completo
    assert p.periciar(_banco("Falta o edital de licitação.")) == []
    # sem o corte, aparece — é o modo de conferência
    assert len(p.periciar(_banco("Falta o edital de licitação."), corte_de_captura=False)) == 1


def test_tres_lentes_somam_no_mesmo_processo(monkeypatch):
    from tools import pericia_tripla as p
    monkeypatch.setattr(p, "captura_completa", lambda: {"030001/000001/2025"})
    r = p.periciar(_banco("Falta a pesquisa de preços, o termo de recebimento assinado pelo "
                          "fiscal do contrato e o edital de licitação."))
    assert set(r[0]["lentes"]) == {"financeira", "forense", "juridica"}
    assert r[0]["peso"] >= 5 + 5 + 3


def test_sem_o_que_falta_nao_entra(monkeypatch):
    from tools import pericia_tripla as p
    monkeypatch.setattr(p, "captura_completa", lambda: {"030001/000001/2025"})
    assert p.periciar(_banco(None)) == []
    assert p.periciar(_banco("")) == []


def test_ob_nao_contabilizada_nao_soma(monkeypatch):
    from tools import pericia_tripla as p
    monkeypatch.setattr(p, "captura_completa", lambda: {"030001/000001/2025"})
    con = _banco("Falta a pesquisa de preços.")
    con.execute("UPDATE ob_orcamentaria_siafe SET status='Anulado'")
    r = p.periciar(con)
    assert len(r) == 1 and r[0]["pago"] == 0.0, "OB anulada não é pagamento"


def test_pesos_sao_coerentes_com_a_prevalencia():
    """Documenta a régua: quanto mais raro o vício, maior o peso."""
    from tools.pericia_tripla import LENTES
    peso = {rot: p for _, rot, _, p in LENTES}
    assert peso["pesquisa de preços"] > peso["habilitação fiscal (CND/FGTS)"]
    assert peso["fiscal designado"] > peso["instrumento (contrato/ARP)"]
    assert peso["atesto / prova de execução"] > peso["parecer jurídico / PGE"]
