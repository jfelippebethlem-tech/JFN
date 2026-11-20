# -*- coding: utf-8 -*-
"""Ficha do acervo: a conferência por código descarta o que não está no texto (nunca corrige), o texto vem por
valor fiscalizatório e sem a etiqueta da casa, e a gravação não sobrescreve ficha existente."""
import json
import sqlite3

from tools import sei_ficha_acervo as A

FONTE = ("=== DOCUMENTO: Contrato 12/2025 ===\n"
         "Contratada: ALFA SERVIÇOS LTDA, CNPJ 12.345.678/0001-90, valor global de R$ 1.234.567,89, "
         "assinado em 03/02/2025 pela Secretaria de Estado de Saúde.\n"
         "=== DOCUMENTO: Parecer ===\nOpina pela legalidade da contratação direta com fundamento no art. 75.")

FICHA = {
    "objeto": "serviços", "nivel_risco": "alto",
    "documentos": [
        {"tipo": "contrato", "ponto": "p", "doc_ref": "Contrato 12/2025",
         "trecho": "valor global de R$ 1.234.567,89, assinado em 03/02/2025"},                 # confere
        {"tipo": "relatório fotográfico", "ponto": "p", "doc_ref": "Relatório",
         "trecho": "registro fotográfico da entrega de 10.000 unidades"},                     # inventado
        {"tipo": "parecer jurídico", "ponto": "p", "doc_ref": "Parecer",
         "trecho": "Opina pela legalidade ... com fundamento no art. 75"},                     # reticências
    ],
    "red_flags": [
        '[Doc: Parecer — "contratação direta com fundamento no art. 75"] dispensa a verificar',  # confere
        '[Doc: Contrato — "sem pesquisa de preços"] sobrepreço',                                  # inventada
        "flag sem citação",                                                                       # sem formato
    ],
    "cnpjs": ["12.345.678/0001-90", "99.999.999/0001-99"],
    "valores": ["R$ 1.234.567,89", "R$ 5.000.000,00"],
    "datas": ["03/02/2025", "31/12/2025"],
    "partes": ["ALFA SERVIÇOS LTDA", "BETA COMÉRCIO"],
}


def test_conferir_descarta_o_que_nao_esta_no_texto():
    ok, rel = A.conferir(FICHA, FONTE)
    assert [d["tipo"] for d in ok["documentos"]] == ["contrato", "parecer jurídico"]
    assert rel["documentos"] == [2, 3]
    assert len(ok["red_flags"]) == 1 and rel["red_flags"] == [1, 3]
    assert ok["cnpjs"] == ["12.345.678/0001-90"]
    assert ok["valores"] == ["R$ 1.234.567,89"]
    assert ok["datas"] == ["03/02/2025"]
    assert ok["partes"] == ["ALFA SERVIÇOS LTDA"]
    assert ok["nivel_risco"] == "" and rel["nivel_risco_modelo"] == "alto"   # palpite registrado, não gravado


def test_nucleo_do_item_anotado_e_conferido():
    f = dict(FICHA, valores=["R$ 1.234.567,89 (valor global, NL 2025NL00384)", "R$ 9.999,99 (inventado)"],
             datas=["03/02/2025 (assinatura)", "31/12/2025 (vigência)"],
             partes=["ALFA SERVIÇOS LTDA (contratada)", "Secretaria de Estado de Saúde", "GAMA (não existe)"],
             cnpjs=["12.345.678/0001-90 (ALFA)", "11.111.111/0001-11 (citada)"])
    ok, rel = A.conferir(f, FONTE + " Nota de Liquidação 2025NL00384.")     # a anotação também tem de estar no texto
    assert ok["valores"] == ["R$ 1.234.567,89 (valor global, NL 2025NL00384)"]
    assert ok["datas"] == ["03/02/2025 (assinatura)"]
    assert ok["partes"] == ["ALFA SERVIÇOS LTDA (contratada)", "Secretaria de Estado de Saúde"]
    assert ok["cnpjs"] == ["12.345.678/0001-90 (ALFA)"]
    assert rel["valores"] == [1, 2] and rel["partes"] == [2, 3]


def test_trecho_curto_ou_vazio_nao_confere():
    fn = A.V._normal(FONTE)
    assert not A.trecho_confere("", fn)
    assert not A.trecho_confere("art. 75", fn)       # < 8 caracteres não prova nada
    assert A.trecho_confere("“Opina pela legalidade”", fn)


def test_texto_por_valor_sem_etiqueta(tmp_path):
    p = tmp_path / "030001_000001_2025"
    (p / "texto").mkdir(parents=True)
    (p / "texto" / "000_despacho.txt").write_text(
        "[Despacho 1] (fase: tramitacao · tipo: despacho)\n\nEncaminho os autos para providências cabíveis.",
        encoding="utf-8")
    (p / "texto" / "001_parecer.txt").write_text(
        "[Parecer Jurídico 2] (fase: controle · tipo: parecer_juridico)\n\nOpina pela legalidade do ajuste celebrado.",
        encoding="utf-8")
    man = {"docs": [{"i": 0, "titulo": "Despacho 1", "texto": "texto/000_despacho.txt"},
                    {"i": 1, "titulo": "Parecer Jurídico 2", "texto": "texto/001_parecer.txt"}]}
    (p / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    texto, cob = A.texto_para_ficha(p)
    assert texto.index("Parecer Jurídico 2") < texto.index("Despacho 1")    # valor antes da posição
    assert "(fase:" not in texto                                            # etiqueta da casa não vaza
    assert cob["docs_lidos"] == 2 and cob["docs_fora_do_teto"] == 0


def test_gravar_nao_sobrescreve_e_registra_verificacao(tmp_path):
    con = sqlite3.connect(tmp_path / "c.db")
    con.execute("CREATE TABLE sei_ficha (numero_sei TEXT PRIMARY KEY, objeto TEXT, modalidade TEXT, "
                "fundamento_legal TEXT, resumo TEXT, analise TEXT, nivel_risco TEXT, relevante INTEGER, valores TEXT, "
                "cnpjs TEXT, partes TEXT, datas TEXT, red_flags TEXT, documentos TEXT, n_docs INTEGER, "
                "fonte_modelo TEXT, cached_at TEXT, atualizado_em TEXT, situacao TEXT, pericia_contabil TEXT, "
                "pericia_juridica TEXT)")
    con.execute("INSERT INTO sei_ficha (numero_sei, objeto, fonte_modelo) VALUES ('SEI-030001/000002/2025','antiga','cache')")
    A._garantir_coluna(con)
    ok, rel = A.conferir(FICHA, FONTE)
    A.gravar(con, "SEI-030001/000001/2025", ok, {"conferido": rel}, "m#acervo-v1")
    A.gravar(con, "SEI-030001/000002/2025", ok, {"conferido": rel}, "m#acervo-v1")
    r = dict(zip(("obj", "n", "v", "fm"), con.execute(
        "SELECT objeto, n_docs, verificacao, fonte_modelo FROM sei_ficha WHERE numero_sei='SEI-030001/000001/2025'").fetchone()))
    assert r["n"] == 2 and json.loads(r["v"])["conferido"]["red_flags"] == [1, 3] and r["fm"] == "m#acervo-v1"
    assert con.execute("SELECT objeto FROM sei_ficha WHERE numero_sei='SEI-030001/000002/2025'").fetchone()[0] == "antiga"


# ── texto corrido (20/11/2026): medido em 300 fichas já pagas — 119 fatos sem fonte em 44 delas eram gravados ──
FONTE2 = (FONTE + "\n=== DOCUMENTO: Nota de Liquidação ===\nNL 2025NL00384 de R$ 598.933,17 e NL 2025NL00776 de "
          "R$ 539.621,97, emitidas em 3 de fevereiro de 2025. Total do item | 12369.6\nTotal | 1687510.7199999998\n"
          "Contrato no valor de R$ 9.055.523,47.")


def _narrativa(**campos):
    return A.conferir({"documentos": [], "red_flags": [], **campos}, FONTE2)


def test_frase_com_fato_sem_fonte_e_descartada_e_contada():
    ok, rel = _narrativa(
        resumo="Contrato de R$ 1.234.567,89 com a ALFA. Pago em 31/12/2025 pela OB 2025OB99999 no valor de R$ 7.777,77.",
        analise="A contratada tem CNPJ 99.999.999/0001-99. Verificar o art. 75 da Lei 14.133/2021 e os 25% do aditivo.")
    assert ok["resumo"] == "Contrato de R$ 1.234.567,89 com a ALFA."
    assert ok["analise"] == "Verificar o art. 75 da Lei 14.133/2021 e os 25% do aditivo."   # lei e % não são "valor"
    n = rel["narrativa"]
    assert n["frases"] == [2, 4] and n["fatos_sem_fonte"] == 4
    assert {"31/12/2025", "2025OB99999", "R$ 7.777,77", "99.999.999/0001-99"} == set(n["exemplos"])


def test_outra_grafia_do_mesmo_fato_nao_e_ausencia():
    ok, rel = _narrativa(resumo="Liquidações de 03/02/2025 (NL 2025NL00384). Item de R$ 12.369,60. "
                                "Total de R$ 1.687.510,72. Contrato de R$ 9,06 milhões.",
                         valores=["R$ 12.369,60", "R$ 1.687.510,72"], datas=["03/02/2025 (liquidação)"])
    assert rel["narrativa"]["fatos_sem_fonte"] == 0 and rel["narrativa"]["frases"] == [4, 4]
    assert len(ok["valores"]) == 2 and ok["datas"] == ["03/02/2025 (liquidação)"]


def test_conta_do_modelo_e_refeita_pelo_codigo():
    soma = "As liquidações de R$ 598.933,17 e R$ 539.621,97 somam R$ 1.138.555,14."
    ok, rel = _narrativa(analise=soma + " A diferença é de R$ 59.311,20. O saldo seria de R$ 222.333,44.")
    assert ok["analise"] == soma + " A diferença é de R$ 59.311,20."       # soma e diferença conferem; o saldo não
    assert rel["narrativa"]["derivados_conferidos"] == 2 and rel["narrativa"]["fatos_sem_fonte"] == 1
    errado, rel = _narrativa(analise="As liquidações de R$ 598.933,17 e R$ 539.621,97 somam R$ 1.138.555,15.")
    assert errado["analise"] == "" and rel["narrativa"]["fatos_sem_fonte"] == 1    # um centavo fora = descartada


def test_arredondamento_so_vale_para_valor_que_existe():
    ok, _ = _narrativa(resumo="Contrato de R$ 9,1 mi. Aditivo de R$ 3,2 mi.")
    assert ok["resumo"] == "Contrato de R$ 9,1 mi."


def test_anotacao_e_resto_da_red_flag_tambem_sao_conferidos():
    ok, rel = A.conferir({
        "documentos": [{"tipo": "contrato", "ponto": "Valor global de R$ 1.234.567,89. Aditivo de R$ 400.000,00.",
                        "doc_ref": "Contrato", "trecho": "valor global de R$ 1.234.567,89"}],
        "red_flags": ['[Doc: Parecer — "contratação direta com fundamento no art. 75"] dispensa a verificar',
                      '[Doc: Parecer — "contratação direta com fundamento no art. 75"] sobrepreço de R$ 88.888,88'],
        "valores": ["R$ 1.234.567,89 (valor global)", "R$ 1.234.567,89 (NL 2025NL55555)"],
    }, FONTE2)
    assert ok["documentos"][0]["ponto"] == "Valor global de R$ 1.234.567,89."     # o documento fica: o trecho é literal
    assert len(ok["red_flags"]) == 1 and rel["red_flags"] == [1, 2]
    assert ok["valores"] == ["R$ 1.234.567,89 (valor global)"] and rel["valores"] == [1, 2]
    assert rel["narrativa"]["itens_descartados"] == 2


def test_fonte_de_conferencia_inclui_o_processo_inteiro(tmp_path):
    """O acervo muda entre o envio e a conferência: o fato fora da janela de hoje, mas no processo, confere."""
    p = tmp_path / "030001_000009_2025"
    (p / "texto").mkdir(parents=True)
    (p / "texto" / "000_nl.txt").write_text("Nota de Liquidação 2024NL00461 de R$ 5.062,88.", encoding="utf-8")
    fonte = A.fonte_de_conferencia(p, "=== DOCUMENTO: Despacho ===\nEncaminho os autos.")
    ok, rel = A.conferir({"documentos": [], "red_flags": [], "resumo": "NL 2024NL00461 de R$ 5.062,88."}, fonte)
    assert ok["resumo"] and rel["narrativa"]["fatos_sem_fonte"] == 0
