"""O PORQUÊ de cada grupo de foto repetida (pedido do dono, 18/11/2026) — `tools.fotos_reciclagem_acervo.classificar`.

Cada regra é um falso positivo MEDIDO na varredura do acervo inteiro (907 processos, 66.321 regiões de foto):
  R1 o mesmo documento SEI juntado em dois lugares;  R2 documento da empresa (programa de integridade, PGR, certidão)
  juntado em vários processos;  R3 a mesma medição repetida no anexo e no parecer;  R4 o relatório inteiro
  reapresentado (texto idêntico — relatório socioambiental da 33ª e da 34ª medição do INEA, 070002_005874_2024).
E o controle positivo: medições DIFERENTES, com período diferente no texto, ficam A CONFERIR — nunca descartadas.
"""
from __future__ import annotations

import json

import pytest

import tools.fotos_reciclagem_acervo as T


@pytest.fixture
def acervo(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "ARQUIVO", tmp_path)
    T.info_documento.__defaults__[0].clear()
    T._contratos.__defaults__[0].clear()
    T._manifesto.__defaults__[0].clear()

    def processo(slug, docs):
        d = tmp_path / slug
        (d / "texto").mkdir(parents=True)
        man = []
        for i, titulo, texto in docs:
            rel = f"texto/{i:03d}.txt"
            (d / rel).write_text(f"[{titulo}]\n{texto}", encoding="utf-8")
            man.append({"i": str(i), "titulo": titulo, "texto": rel})
        (d / "manifest.json").write_text(json.dumps({"docs": man}), encoding="utf-8")
    return processo


def _g(*ocs):
    oc = [{"processo": p, "doc": i} for p, i in ocs]
    return {"ocorrencias": oc, "processos": sorted({p for p, _ in ocs})}


_CORPO = "Relatório fotográfico do serviço de desassoreamento executado no canal. " * 8


def test_r1_mesmo_documento_sei(acervo):
    acervo("070002_000001_2024", [(5, "Relatório Fotográfico - 3ª Medição (88524810)", _CORPO + "Período: 01/03/2024 a 31/03/2024")])
    acervo("070002_000002_2024", [(9, "Relatório Fotográfico - 3ª Medição (88524810)", _CORPO + "Período: 01/03/2024 a 31/03/2024 x")])
    r = T.classificar(_g(("070002_000001_2024", 5), ("070002_000002_2024", 9)))
    assert r["regra"] == "R1_mesmo_documento_sei" and r["classe"] == "inocente-comprovada"


def test_r4_relatorio_reapresentado_texto_identico(acervo):
    texto = _CORPO + "quarta etapa do projeto, janeiro a agosto de 2023"
    acervo("070002_005874_2024", [(284, "Relatório Socioambiental - 33ª Medição - PARTE I (89987976)", texto),
                                  (290, "Relatório Socioambiental 34ª Medição - PARTE I (90019845)", texto)])
    r = T.classificar(_g(("070002_005874_2024", 284), ("070002_005874_2024", 290)))
    assert r["regra"] == "R4_texto_identico" and r["classe"] == "inocente-provável"


def test_r2_documento_da_empresa_nao_e_execucao(acervo):
    acervo("260005_003310_2026", [(15, "Programa de integridade (129418599)", _CORPO + " ética e conformidade A")])
    acervo("260005_012007_2025", [(19, "Programa de integridade (120055024)", _CORPO + " ética e conformidade B")])
    r = T.classificar(_g(("260005_003310_2026", 15), ("260005_012007_2025", 19)))
    assert r["regra"] == "R2_nao_execucao" and r["classe"] == "inocente-provável"


def test_r3_mesma_medicao_no_anexo_e_no_relatorio(acervo):
    acervo("070002_005897_2024", [(190, "Anexo 13ª Medição (84775845)", _CORPO + "boletim"),
                                  (193, "Relatório Fotográfico - 13ª Medição (84777327)", _CORPO + "fotos")])
    r = T.classificar(_g(("070002_005897_2024", 190), ("070002_005897_2024", 193)))
    assert r["regra"] == "R3_mesma_medicao" and r["classe"] == "inocente-comprovada"


def test_mesma_medicao_em_contratos_diferentes_nao_e_descartada(acervo):
    """"1ª medição" do contrato A e "1ª medição" do contrato B NÃO é a mesma medição."""
    acervo("070002_008296_2022", [(3, "Relatório Fotográfico - 1ª Medição (92109020)", _CORPO + "Contrato 23/2022 x")])
    acervo("070002_008301_2022", [(4, "Relatório Fotográfico - 1ª Medição (92122150)", _CORPO + "Contrato 25/2022 y")])
    r = T.classificar(_g(("070002_008296_2022", 3), ("070002_008301_2022", 4)))
    assert r["regra"] == "a_conferir" and r["classe"] is None


def test_controle_positivo_medicoes_diferentes_ficam_a_conferir(acervo):
    acervo("070002_005897_2024", [
        (140, "Relatório Fotográfico 11ª Medição (80260742)", _CORPO + "\nPeríodo: 23/06/2024 à 22/07/2024 – CONTRATO: 35/2023"),
        (269, "Relatório Fotográfico 16ª Medição (90123001)", _CORPO + "\n16ª MEDIÇÃO – 23/11/2024 A 15/12/2024")])
    r = T.classificar(_g(("070002_005897_2024", 140), ("070002_005897_2024", 269)))
    assert r["regra"] == "a_conferir" and r["medicoes"] == [11, 16] and r["periodos_distintos_no_texto"]
    assert any("23/06/2024" in t for t in r["trechos_periodo"])


def test_numero_medicao_formatos_do_acervo():
    assert T.numero_medicao("Relatório Fotográfico - 13ª Medição (84777327)") == 13
    assert T.numero_medicao("Relatório de Medição 22 P0 - 01 a 15/04/2025 - Construverde (98686704)") == 22
    assert T.numero_medicao("Anexo 0 - Med05 - Capa Medição Consórcio (131556379)") == 5
    assert T.numero_medicao("Anexo 0 - Capa 10 medição - Consorcio (146050153)") == 10
    assert T.numero_medicao("Documento Memória de Cálculo - 23 P0 (101980055)") == 23
    assert T.numero_medicao("Anexo 04 - RELATORIO FOTOGRAFICO 11° (97452361)") == 11
    assert T.numero_medicao("Relatório Fotográfico (131087452)") is None
    assert T.numero_medicao("Anexo 04 - Relatório Fotográfico (Avanço Físico) (98248626)") is None


def test_veredito_a_olho_so_vale_se_cobre_todas_as_ocorrencias():
    v = [{"processos": ["A"], "docs": {"A": [1, 2]}, "classe": "contradição", "porque": "x", "trecho": "y"}]
    assert T._veredito(_g(("A", 1), ("A", 2)), v)
    assert T._veredito(_g(("A", 1), ("A", 3)), v) is None
    assert T._veredito(_g(("A", 1), ("B", 2)), v) is None
    so_pagina = [{"processos": ["A"], "pagina_inteira": True, "classe": "inocente-comprovada", "porque": "mapa", "trecho": ""}]
    g = _g(("A", 1), ("A", 2))
    assert T._veredito(g, so_pagina) is None                      # foto recortada não herda o veredito do mapa
    g["ocorrencias"][0]["regiao"] = 0
    assert T._veredito(g, so_pagina)


def test_r5_sem_ceu_fica_pendente_nao_inocenta(acervo):
    acervo("070002_004386_2024", [(20, "Relatório Fotográfico - 23ª Medição (70000001)", _CORPO + "mapa a"),
                                  (51, "Relatório Fotográfico - 25ª Medição (70000002)", _CORPO + "mapa b")])
    g = _g(("070002_004386_2024", 20), ("070002_004386_2024", 51))
    assert T.classificar(g)["regra"] == "a_conferir"
    g["todos_mapa"] = True
    r = T.classificar(g)
    assert r["regra"] == "R5_sem_ceu_nao_conferido" and r["classe"] is None


def test_medicao_e_periodo_lidos_do_corpo_quando_o_titulo_vem_truncado(acervo):
    """SEIOP: "Anexo 4.1 - Relatório Fotográfico de Avanço Físico 6ª M (97726179)" — o nº e o período estão no corpo."""
    acervo("330001_000577_2025", [(40, "Anexo 4.1 - Relatório Fotográfico de Avanço Físico 6ª M (97726179)",
                                   _CORPO + "\nN° da medição:\n06\nPeríodo de Referência:\n01/01/25 a 31/01/25")])
    d = T.info_documento("330001_000577_2025", 40)
    assert d["medicao"] == 6 and "2025-01-01" in d["periodos"]


def test_r6_mesmo_periodo_de_referencia_e_a_mesma_medicao(acervo):
    """SEIOP 330001_000326_2026: a página de fotos da 10ª medição (01/05/2026) juntada como "Anexo 03" e "Anexo 4"."""
    cab = "MEDIÇÃO \nPeríodo de Referência  330001/001080/2025  01/05/2026 a 31/05/2026\n"
    acervo("330001_000326_2026", [(178, "Anexo 02-RELATÓRIO_FOTOGRÁFICO - 10ª MEDIÇÃO_REV00 (134575856)", cab + _CORPO + "a"),
                                  (204, "Anexo 03-Relatório Fotográfico (137081084)", cab + _CORPO + "b")])
    r = T.classificar(_g(("330001_000326_2026", 178), ("330001_000326_2026", 204)))
    assert r["regra"] == "R6_mesmo_periodo_de_referencia" and r["classe"] == "inocente-comprovada"


def test_periodo_de_referencia_formatos():
    assert T.periodo_de_referencia("Período de Referência  330001/001080/2025  01/05/2026") == "2026-05-01"
    assert T.periodo_de_referencia("RELATÓRIO FOTOGRÁFICO – 28ª MEDIÇÃO\nPeríodo: 23/10/2025 a 31/10/2025") == "2025-10-23"
    assert T.periodo_de_referencia("Período de Referência:\n01/01/25 a 31/01/25") == "2025-01-01"
    assert T.periodo_de_referencia("sem data nenhuma") is None


def test_veredito_por_ocorrencia_nao_se_estende_a_foto_vizinha():
    v = [{"processos": ["A"], "ocorrencias": ["A/fotos/001_p01.jpg#1", "A/fotos/009_p01.jpg#1"],
          "classe": "inocente-provável", "porque": "contêiner", "trecho": ""}]
    visto = {"ocorrencias": [{"processo": "A", "doc": 1, "arquivo": "A/fotos/001_p01.jpg", "regiao": 1},
                             {"processo": "A", "doc": 9, "arquivo": "A/fotos/009_p01.jpg", "regiao": 1}]}
    vizinho = {"ocorrencias": [{"processo": "A", "doc": 1, "arquivo": "A/fotos/001_p01.jpg", "regiao": 2},
                               {"processo": "A", "doc": 9, "arquivo": "A/fotos/009_p01.jpg", "regiao": 2}]}
    assert T._veredito(visto, v)
    assert T._veredito(vizinho, v) is None
