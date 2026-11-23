# -*- coding: utf-8 -*-
"""Extrator determinístico de preços de propostas dos autos SEI (`tools/propostas_sei_extrair`).

A trava central: só entra a linha em que quantidade × unitário = total. Controle POSITIVO (linha que fecha
entra, nos dois formatos: tabela com pipes e texto nativo uma coluna por linha) e NEGATIVO (valor adulterado,
como o Tesseract faz, não fecha e fica fora; CNPJ com DV errado não identifica fornecedor; mapa com dois
fornecedores é ambíguo; órgão público não é fornecedor). Os textos imitam amostras REAIS do acervo.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from tools import propostas_sei_extrair as X

CNPJ_OK = "30.778.749/0001-25"          # DV válido (amostra real: G.P. Vezono, 270060_001402_2023)
CNPJ_OK2 = "03.093.776/0001-91"         # DV válido (Manupa, 270006_039664_2025)
CNPJ_DV_ERRADO = "30.778.749/0001-26"

PIPES = """Item | Equipamentos | Valor Unitário | Quantidade | Total
4 | Andador Pediátrico e Adulto | 278 | 30 | 8340
6 | Aparelho de Luz Infravermelho | 478 | 34 | 16252
9 | Aparelho para Fisioterapia por ondas curtas | 9425 | 15 | 141375
"""

NATIVO = """ITEM
UNID.
DESCRIÇÃO
QTD.
VALOR
UNITÁRIO
VALOR
TOTAL
16
UNID
BERÇO AQUECIDO GRN MODELO NEOSOLUTION
02
Gigante Recém Nascido
R$ 14.900,00
(Quatorze mil e novecentos reais)
R$ 29.800,00
"""


def _doc(cnpj: str, tabela: str) -> str:
    return f"G.P. Vezono Ltda\nCNPJ: {cnpj} - Inscrição Estadual: 797.389.702.110.\nPROPOSTA DE PREÇOS\n{tabela}"


# ───────────── números e a conta ─────────────
def test_numero_nas_grafias_do_acervo():
    assert X.valores("R$ 14.900,00")[0] == [14900.0]
    assert X.valores("12,30")[0] == [12.3]
    assert X.valores("0.0792")[0] == [0.0792]
    assert X.valores("8340")[0] == [8340.0]
    assert 22627200.0 in X.valores("22.627.200")[0]
    assert set(X.valores("1.234")[0]) == {1234.0, 1.234}       # ambíguo: a conta decide
    assert X.valores("14080-620")[0] == []                     # CEP não é número de planilha


def test_conta_fecha_com_arredondamento_e_nao_com_erro_de_leitura():
    assert X.fecha_conta(30, 278, 8340)
    assert X.fecha_conta(3, 0.3333, 1.00)                       # arredondamento de centavo
    assert not X.fecha_conta(30, 278, 8370)                     # um dígito trocado (OCR) não fecha
    assert not X.fecha_conta(1, 1, 1)                           # '1,00 = 1,00' não é item
    assert not X.fecha_conta(0, 278, 0)


# ───────────── controle positivo: os dois formatos ─────────────
def test_tabela_com_pipes_entra_com_item_e_descricao():
    r = X.extrair_linhas(PIPES)
    got = [(l["item"], l["descricao"], l["quantidade"], l["valor_unitario"], l["valor_total"]) for l in r["linhas"]]
    assert got == [(4, "Andador Pediátrico e Adulto", 30.0, 278.0, 8340.0),
                   (6, "Aparelho de Luz Infravermelho", 34.0, 478.0, 16252.0),
                   (9, "Aparelho para Fisioterapia por ondas curtas", 15.0, 9425.0, 141375.0)]
    assert all(l["item_literal"] for l in r["linhas"])
    assert r["linhas"][0]["trecho"] == "4 | Andador Pediátrico e Adulto | 278 | 30 | 8340"


def test_texto_nativo_uma_coluna_por_linha_entra():
    r = X.extrair_linhas(NATIVO)
    assert len(r["linhas"]) == 1
    ln = r["linhas"][0]
    assert (ln["item"], ln["quantidade"], ln["valor_unitario"], ln["valor_total"]) == (16, 2.0, 14900.0, 29800.0)
    assert "BERÇO AQUECIDO" in ln["descricao"]
    assert "R$ 29.800,00" in ln["trecho"]                       # evidência literal


def test_texto_nativo_colunas_na_mesma_linha():
    r = X.extrair_linhas("13 MAO-DE-OBRA DE TECNICO DE EDIFICAÇÕES H 4.224,00 R$31,26 R$ 132.042,24")
    assert [(l["item"], l["quantidade"], l["valor_unitario"]) for l in r["linhas"]] == [(13, 4224.0, 31.26)]


# ───────────── controle negativo ─────────────
def test_valor_adulterado_nao_fecha_a_conta_e_nao_entra():
    adulterado = PIPES.replace("| 16252", "| 16852")             # erro típico do Tesseract (2→8)
    r = X.extrair_linhas(adulterado)
    assert [l["item"] for l in r["linhas"]] == [4, 9]
    assert r["tabela_linhas"] == 3 and r["tabela_fecharam"] == 2  # o que não fechou é CONTADO


def test_nativo_adulterado_nao_entra():
    assert X.extrair_linhas(NATIVO.replace("R$ 29.800,00", "R$ 29.300,00"))["linhas"] == []


def test_paginacao_sem_cara_de_dinheiro_nao_vira_item():
    assert X.extrair_linhas("Página\n1 2 1 2 1 2\n3 4 12")["linhas"] == []


def test_moeda_estrangeira_fica_fora_e_nao_vaza_descricao():
    txt = "001004\n5,000\nENGRENAGEM SATELITE\nUS$\n16.124,590000\nUS$\n80.622,95\nJUNTA\n2\nR$ 73,22\nR$ 146,44\n"
    r = X.extrair_linhas(txt)
    assert r["moeda_estrangeira"] == 1
    assert [(l["descricao"], l["valor_total"]) for l in r["linhas"]] == [("JUNTA", 146.44)]


# ───────────── fornecedor ─────────────
def test_cnpj_valido_no_cabecalho_identifica_o_fornecedor():
    assert X.fornecedor_do_documento(_doc(CNPJ_OK, PIPES)) == ("30778749000125", "ok")


def test_cnpj_com_dv_errado_nao_identifica_ninguem():
    assert X.fornecedor_do_documento(_doc(CNPJ_DV_ERRADO, PIPES)) == (None, "sem_cnpj")


def test_dois_cnpjs_privados_no_cabecalho_e_ambiguo():
    txt = f"MAPA COMPARATIVO\nEmpresa A CNPJ {CNPJ_OK}\nEmpresa B CNPJ {CNPJ_OK2}\n{PIPES}"
    assert X.fornecedor_do_documento(txt) == (None, "ambiguo")


def test_orgao_publico_nao_e_fornecedor():
    txt = f"SECRETARIA DE ESTADO DE EDUCACAO 42.498.659/0001-60\nFornecedor CNPJ {CNPJ_OK}\n{PIPES}"
    assert X.fornecedor_do_documento(txt) == ("30778749000125", "ok")
    publico = {"42498659000160": {"publico": True}, "30778749000125": {"publico": False}}
    assert X.fornecedor_do_documento(txt, publico.get) == ("30778749000125", "ok")


def test_filial_da_mesma_empresa_nao_e_ambiguidade():
    txt = f"CNPJ matriz {CNPJ_OK}\nfilial 30.778.749/0002-06\n"
    assert X.fornecedor_do_documento(txt)[1] == "ok"


# ───────────── ponta a ponta: acervo → proposta_item → J9 ─────────────
@pytest.fixture()
def acervo(tmp_path):
    raiz = tmp_path / "sei_arquivo"
    tag = "080002_019237_2024"
    (raiz / tag / "texto").mkdir(parents=True)
    docs = []
    # dois fornecedores; B = A + 10% em todos os itens (assinatura de markup uniforme)
    tabela_b = """Item | Equipamentos | Valor Unitário | Quantidade | Total
4 | Andador Pediátrico e Adulto | 305,80 | 30 | 9.174,00
6 | Aparelho de Luz Infravermelho | 525,80 | 34 | 17.877,20
9 | Aparelho para Fisioterapia por ondas curtas | 10.367,50 | 15 | 155.512,50
"""
    for i, (cnpj, tab) in enumerate([(CNPJ_OK, PIPES), (CNPJ_OK2, tabela_b)]):
        nome = f"texto/00{i}_proposta.txt"
        (raiz / tag / nome).write_text(f"[Proposta {i}] (tipo: proposta)\n\n" + _doc(cnpj, tab), encoding="utf-8")
        docs.append({"i": str(i), "titulo": f"Proposta {i}", "tipo": "proposta", "texto": nome, "ocr": False})
    docs.append({"i": "9", "titulo": "Despacho", "tipo": "despacho", "texto": "texto/009.txt"})
    (raiz / tag / "manifest.json").write_text(json.dumps({"processo": "SEI-080002/019237/2024", "docs": docs}),
                                              encoding="utf-8")
    return raiz


def test_ponta_a_ponta_persiste_e_o_j9_ve_o_markup(acervo, tmp_path):
    r = X.processar(acervo)
    m = r["medidas"]
    assert (m["docs"], m["com_fornecedor"], m["linhas_validas"], m["certames_2mais_fornecedores"]) == (2, 2, 6, 1)
    assert list(r["por_certame"]) == ["080002/19237/2024"]           # chave de _chave_processo
    db = tmp_path / "c.db"
    assert X.persistir(r["por_certame"], db) == 6
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM proposta_item WHERE fonte='sei_proposta'").fetchone()[0] == 6
    assert con.execute("SELECT COUNT(*) FROM proposta_item_evidencia WHERE trecho LIKE '4 | Andador%'"
                       ).fetchone()[0] == 2
    con.close()
    assert X.persistir(r["por_certame"], db) == 6                    # idempotente
    j9 = X.analisar(db)
    assert j9["avaliados"] == 1
    # B = A × 1,10  ⇔  A = B × 0,909 (a ordem do par depende da ordem dos CNPJs)
    assert any(a["tipo"] == "markup_uniforme" and round(abs(a["pct"])) in (9, 10) and a["cv"] == 0
               for a in j9["achados"])


def test_ponta_a_ponta_sem_conluio_nao_acusa(acervo, tmp_path):
    p = next(acervo.glob("*/texto/001_proposta.txt"))
    # B com preços independentes (dispersão irregular), contas fechando
    p.write_text(_doc(CNPJ_OK2, """Item | Equipamentos | Valor Unitário | Quantidade | Total
4 | Andador Pediátrico e Adulto | 250,00 | 30 | 7.500,00
6 | Aparelho de Luz Infravermelho | 610,00 | 34 | 20.740,00
9 | Aparelho para Fisioterapia por ondas curtas | 8.990,00 | 15 | 134.850,00
"""), encoding="utf-8")
    db = tmp_path / "c.db"
    X.persistir(X.processar(acervo)["por_certame"], db)
    j9 = X.analisar(db)
    assert j9["avaliados"] == 1 and j9["indicios"] == 0


def test_item_que_nao_fechou_nao_empresta_o_numero_ao_seguinte():
    """Real (350169_002111_2022, Graná 298): o item 02 não fecha a conta; o 03 não pode herdar o nº 02."""
    txt = ("Item\nDescrição\nUnid\nQuant.\nValor\nUnitário\nTotal\n"
           "02\nCarne,tipo: CHARQUE TRASEIRO\nKG\n63.529\n152,50\n3.335.272,50\n"
           "03\nCarne, tipo: LAGARTO REDONDO\nKG\n63.529\n149,98\n9.528.079,42\n")
    r = X.extrair_linhas(txt)
    assert [(l["item"], l["valor_unitario"]) for l in r["linhas"]] == [(3, 149.98)]
    assert "LAGARTO" in r["linhas"][0]["descricao"] and "CHARQUE" not in r["linhas"][0]["descricao"]
    assert r["linhas"][0]["trecho"].startswith("03 / Carne, tipo: LAGARTO")    # evidência sem o item anterior


def test_quantidade_com_centavos_segue_a_ordem_do_cabecalho():
    """Real (Milano, mesmo processo): '150.027,60' kg × '42,00' — os dois têm cara de dinheiro; o cabeçalho
    (Quantidade antes de Unitário) decide, não o 'é inteiro'."""
    txt = "Item\nQuantidade\nValor Unitário\nTotal\n01\nCarne ALCATRA\nKG\n150.027,60\n42,00\n6.301.159,20\n"
    ln = X.extrair_linhas(txt)["linhas"][0]
    assert (ln["quantidade"], ln["valor_unitario"]) == (150027.6, 42.0)


def test_linha_repetida_e_item_sem_numero_nao_se_apagam_na_pk():
    """Proposta juntada duas vezes não duplica; item sem nº literal não colide com o literal (PK)."""
    base = {"fornecedor_cnpj": "30778749000125", "quantidade": 2.0, "valor_unitario": 5.0, "valor_total": 10.0,
            "fonte": "sei_proposta", "trecho": "x"}
    linhas = [dict(base, item=1, item_literal=True, descricao="Caneta"),
              dict(base, item=1, item_literal=True, descricao="Caneta"),            # cópia: sai
              dict(base, item=1, item_literal=False, descricao="Lápis")]
    med: dict = {}
    out = X._numerar({"c": linhas}, med)["c"]
    assert [(l["item"], l["descricao"]) for l in out] == [(1, "Caneta"), (X.ITEM_ATRIBUIDO, "Lápis")]
    assert med["linhas_repetidas"] == 1 and med["linhas_persistiveis"] == 2


def test_cnpj_so_no_rodape_identifica_se_for_o_unico_privado():
    import tools.propostas_sei_extrair as X
    miolo = "PROPOSTA COMERCIAL\n" + ("Item de serviço com descrição longa para empurrar o rodapé. " * 80)
    um = miolo + "\nAtenciosamente, EMPRESA X LTDA CNPJ 11.222.333/0001-81"
    dois = um + "\nSubcontratada: OUTRA LTDA CNPJ 11.444.777/0001-61"
    assert X.fornecedor_do_documento(um) == ("11222333000181", "ok_corpo")
    assert X.fornecedor_do_documento(dois) == (None, "ambiguo")


def test_proposta_lida_por_ocr_de_ia_so_entra_confirmada(acervo, tmp_path, monkeypatch):
    """23/11/2026 (`sei/ocr_ia_prova`): proposta cujo texto veio do OCR por IA não vira preço de referência com CNPJ
    ou valores não confirmados; confirmados por segunda leitura, entra igual à nativa."""
    from compliance_agent.sei import ocr_ia_prova as P
    monkeypatch.setattr(P, "LEDGER", tmp_path / "conf.jsonl")
    tag = "080002_019237_2024"
    mp = acervo / tag / "manifest.json"
    man = json.loads(mp.read_text())
    man["docs"][1].update(ocr="True", ocr_motor="surya-ocr-2.5")
    mp.write_text(json.dumps(man))
    m = X.processar(acervo)["medidas"]
    assert (m["linhas_validas"], m["linhas_ocr_ia_a_conferir"]) == (3, 3)
    texto = (acervo / tag / man["docs"][1]["texto"]).read_text()
    P.registrar([{"tag": tag, "i": 1, **x} for x in P.confirmar_numeros(P.extrair(texto), {"tesseract": texto})])
    m = X.processar(acervo)["medidas"]
    assert (m["linhas_validas"], m.get("linhas_ocr_ia_a_conferir", 0)) == (6, 0)
