# -*- coding: utf-8 -*-
"""Valor global atualizado lido dos termos aditivos nos autos (aditivo_autos + perícia contábil).

As frases dos aditivos reproduzem a redação PÚBLICA do Termo Aditivo 23/2024 – INEA (contrato 06/2023,
processo SEI-070002/007444/2022, publicado no DOERJ); o resto é sintético."""
import json
from datetime import date
from pathlib import Path

import pytest

from compliance_agent import aditivo_autos as AD
from compliance_agent import pericia_contabil as pc
from compliance_agent import vinculo_ob_contrato as vo
from tests.test_pericia_contabil import _base_estado

CONTRATO = "0700020074442022"
OUTRO = "0700020099992023"

INEA_23 = (
    "[Termo Aditivo 23/2024 - INEA (77710535)] Governo do Estado do Rio de Janeiro TERMO ADITIVO N° 23/2024 – INEA "
    "PROCESSO Nº SEI-070002/007444/2022 PRIMEIRO TERMO ADITIVO AO CONTRATO Nº 06/2023, QUE TEM POR OBJETO "
    "PRORROGAÇÃO DO PRAZO CONTRATUAL SEM RENÚNCIA DE REAJUSTE.\n"
    "CLÁUSULA SEXTA (Do Valor do Termo Aditivo e do Contrato): Dá-se ao termo aditivo o valor de R$ 4.926.622,68 "
    "(quatro milhões, novecentos e vinte e seis mil seiscentos e vinte e dois reais e sessenta e oito centavos) "
    "totalizando o contrato o valor de R$ 17.725.621,68 (dezessete milhões, setecentos e vinte e cinco mil, "
    "seiscentos e vinte e um reais e sessenta e oito centavos). PARÁGRAFO ÚNICO: O contrato ora aditado foi "
    "reajustado através de Termo de Apostilamento, no valor de R$ 555.886,35 referente ao 1°aniversário, conforme "
    "Processo SEI-070002/017712/2023, em cumprimento à CLÁUSULA QUINTA do Contrato n° 06/2023, totalizando o valor "
    "global do contrato com o Reajustamento o total de R$ 18.281.508,03 (dezoito milhões, duzentos e oitenta e um "
    "mil, quinhentos e oito reais e três centavos).\n"
    "Rio de Janeiro, 02 de maio de 2024\nDocumento assinado eletronicamente por Fulano, em 02/05/2024, às 10:00.\n"
    "DIÁRIO OFICIAL — EXTRATO DE CONTRATO INSTRUMENTO: Contrato nº 286/2024/HUPE. VALOR DO CONTRATO: "
    "R$ 12.598.227,29. Outro extrato: totalizando o contrato o valor de R$ 99.999.999,99.")
SO_PRAZO = ("[Termo Aditivo 5/2025 (90000001)] TERMO ADITIVO N° 5/2025 PROCESSO SEI-070002/007444/2022 "
            "QUARTO TERMO ADITIVO AO CONTRATO Nº 06/2023, QUE TEM POR OBJETO A PRORROGAÇÃO DO PRAZO DE EXECUÇÃO "
            "POR 90 DIAS, MANTIDAS AS DEMAIS CLÁUSULAS.\nDocumento assinado eletronicamente por Fulano, em 01/02/2025.")
SEM_TOTAL = ("[Termo Aditivo 7/2025 (95000001)] TERMO ADITIVO N° 7/2025 PROCESSO SEI-070002/007444/2022 "
             "QUINTO TERMO ADITIVO AO CONTRATO Nº 06/2023. Acréscimo quantitativo de 20% sobre os itens 3 e 4, "
             "no valor de R$ 1.200.000,00 conforme planilha anexa.\nDocumento assinado eletronicamente, em 03/03/2025.")
DE_OUTRO = ("[Termo Aditivo 9/2025 (99000001)] TERMO ADITIVO N° 9/2025 PROCESSO SEI-070002/009999/2023 "
            "PRIMEIRO TERMO ADITIVO AO CONTRATO Nº 11/2024. totalizando o valor global do contrato com o "
            "Reajustamento o total de R$ 77.000.000,00.\nDocumento assinado eletronicamente, em 05/05/2025.")


def _pasta(raiz: Path, chave: str, docs: dict[str, str]) -> Path:
    p = raiz / f"{chave[:6]}_{chave[6:12]}_{chave[12:]}"
    (p / "texto").mkdir(parents=True, exist_ok=True)
    man = {"processo": vo.formatar(chave), "docs": []}
    for i, (titulo, txt) in enumerate(docs.items()):
        nome = f"{i:03d}.txt"
        (p / "texto" / nome).write_text(txt, encoding="utf-8")
        man["docs"].append({"i": str(i), "titulo": titulo, "texto": f"texto/{nome}"})
    (p / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return p


def test_controle_positivo_caso_inea_valor_global_com_reajuste():
    e = AD.extrair_valor(INEA_23)
    assert e["valor"] == pytest.approx(18_281_508.03)                 # o global com reajuste, não o do termo
    assert "18.281.508,03" in e["trecho"]


def test_extrato_do_diario_oficial_de_outro_contrato_nao_entra():
    assert AD.corpo(INEA_23).find("12.598.227,29") == -1
    assert AD.extrair_valor(INEA_23)["valor"] != pytest.approx(99_999_999.99)


def test_frases_do_mesmo_nivel_com_valores_distintos_nao_extrai():
    t = ("TERMO ADITIVO PROCESSO SEI-070002/007444/2022 totalizando o contrato o valor de R$ 10.000,00 e, na "
         "cláusula seguinte, totalizando o contrato o valor de R$ 20.000,00.")
    assert AD.extrair_valor(t) is None


def test_mais_recente_e_negativos_outro_contrato_e_so_prazo(tmp_path):
    p = _pasta(tmp_path, "0700020055152024", {
        "Termo Aditivo 23/2024 - INEA (77710535)": INEA_23,
        "Termo Aditivo 9/2025 (99000001)": DE_OUTRO,                   # aditivo de OUTRO contrato no mesmo processo
        "Termo Aditivo 5/2025 (90000001)": SO_PRAZO,                   # mais recente que o 23/2024, só de prazo
        "Despacho (99500000)": "totalizando o valor global do contrato com o Reajustamento o total de R$ 1,00",
    })
    ads = AD.aditivos_do_contrato([(p, False)], CONTRATO, {OUTRO, "0700020099992023"}, vo.chaves_citadas)
    assert [a["doc_sei"] for a in ads] == [77710535, 90000001]       # o de outro contrato e o despacho ficam fora
    s = AD.situacao(ads)
    assert s["estado"] == AD.COM_VALOR and s["valor"] == pytest.approx(18_281_508.03)
    assert s["numero"] == "23/2024" and s["data"] == "02/05/2024"


def test_processo_de_pagamento_sem_o_processo_do_contrato_no_cabecalho_nao_conta(tmp_path):
    p = _pasta(tmp_path, "0700020055152024", {"Termo Aditivo 23/2024 - INEA (77710535)": INEA_23})
    assert AD.aditivos_do_contrato([(p, False)], "0700020011112022", set(), vo.chaves_citadas) == []


def test_aditivo_mais_recente_sem_total_extraido_e_sem_valor(tmp_path):
    p = _pasta(tmp_path, "0700020074442022", {"Termo Aditivo 23/2024 - INEA (77710535)": INEA_23,
                                              "Termo Aditivo 7/2025 (95000001)": SEM_TOTAL})
    s = AD.situacao(AD.aditivos_do_contrato([(p, True)], CONTRATO, set(), vo.chaves_citadas))
    assert s["estado"] == AD.SEM_VALOR and s["doc_sei"] == 95000001


# ── perícia: contrato A da base sintética (valor 100.000,00; pago 135.000,00 → A_MAIOR) ───────────────────
A_PROC = "1000010000012024"


def _aditivo_a(total: str) -> str:
    return (f"TERMO ADITIVO N° 1/2024 PROCESSO SEI-100001/000001/2024 PRIMEIRO TERMO ADITIVO. totalizando o valor "
            f"global do contrato com o Reajustamento o total de R$ {total}.\n"
            "Documento assinado eletronicamente por Fulano, em 01/06/2024.")


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(vo, "ARQUIVO", tmp_path / "arq")
    return _base_estado(tmp_path)


def _a(db):
    return {r["id"]: r for r in pc.avaliar_estado(db, corte=date(2026, 7, 1))}["A"]


def test_pericia_controle_sem_aditivo_segue_a_maior(base):
    a = _a(base)
    assert a["categoria"] == "A_MAIOR" and a["fonte_valor"] == ""


def test_pericia_aditivo_maior_que_o_pago_tira_do_a_maior(base, tmp_path):
    _pasta(tmp_path / "arq", A_PROC, {"Termo Aditivo 1/2024 (50000001)": _aditivo_a("150.000,00")})
    a = _a(base)
    assert a["categoria"] != "A_MAIOR" and a["valor_atualizado"] == pytest.approx(150_000.0)
    assert "doc SEI 50000001" in a["fonte_valor"] and "150.000,00" in a["criterio_valor"]


def test_pericia_pago_acima_do_valor_aditado_segue_a_maior_com_essa_base(base, tmp_path):
    _pasta(tmp_path / "arq", A_PROC, {"Termo Aditivo 1/2024 (50000001)": _aditivo_a("120.000,00")})
    a = _a(base)
    assert a["categoria"] == "A_MAIOR" and a["excesso_global"] == pytest.approx(15_000.0)
    assert "último termo aditivo lido nos autos" in a["ressalvas"]


def test_pericia_aditivo_sem_valor_extraido_nunca_e_a_maior(base, tmp_path):
    _pasta(tmp_path / "arq", A_PROC, {"Termo Aditivo 7/2025 (95000001)": SEM_TOTAL.replace(
        "SEI-070002/007444/2022", "SEI-100001/000001/2024")})
    a = _a(base)
    assert a["categoria"] == "INDETERMINADO" and a["motivo"] == "aditivo_nos_autos_sem_valor_extraido"
    assert a["motivo"] in pc.MOTIVOS


def test_minuta_e_documento_sobre_o_aditivo_nao_sao_o_termo(tmp_path):
    p = _pasta(tmp_path, CONTRATO, {"Minuta de Termo Aditivo (98441299)": INEA_23,
                                    "Parecer sobre Termo Aditivo (98441300)": INEA_23,
                                    "Primeiro Termo Aditivo (98441301)": INEA_23})
    assert [a["doc_sei"] for a in AD.aditivos_do_contrato([(p, True)], CONTRATO, set(), vo.chaves_citadas)] == [
        98441301]
