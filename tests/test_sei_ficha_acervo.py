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
    ok, rel = A.conferir(f, FONTE)
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
