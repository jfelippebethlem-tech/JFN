# -*- coding: utf-8 -*-
"""FOTO × QUANTITATIVO — boletim de medição contra relatório fotográfico (compliance_agent/foto_quantitativo.py).

Casos reais do acervo (INEA 35/2023, Geo Ambiental, SEI-070002/005897/2024; AGRO RJ 020001/002796/2025) e
negativos sintéticos. Cada falso positivo medido na 1ª rodada virou um teste aqui."""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from compliance_agent import foto_quantitativo as fq

GEO = Path("data/sei_arquivo/070002_005897_2024")
AGRO = Path("data/sei_arquivo/020001_002796_2025")
real_geo = pytest.mark.skipif(not (GEO / "manifest.json").exists(), reason="acervo SEI não presente nesta máquina")
real_agro = pytest.mark.skipif(not (AGRO / "manifest.json").exists(), reason="acervo SEI não presente nesta máquina")


# ── papel do documento e nº da medição ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("titulo,papel,n", [
    ("Relatório Fotográfico - 7ª Medição (71848120)", "relatorio", 7),
    ("Anexo 7ª Medição (71846953)", "boletim", 7),
    ("Anexo 02 - MEDIÇÃO 11° (97451519)", "boletim", 11),
    ("Anexo 2 - BOLETIM MEDIÇÃO 4° (97626554)", "boletim", 4),
    ("Anexo 3 - Memória de Cálculo 13ª Medição Complementar (119632901)", "memoria", 13),
    ("Anexo 7 - Diário de Obras 9ª Medição (105980378)", "diario", 9),
    ("Parecer Técnico - 7ª Medição (71846588)", "aceite", 7),
    ("Anexo Notas Fiscais - 7ª Medição (71846992)", None, 7),
    ("Guia de ISS e Comp. de Pagto. 43ª Medição (Exc. nf.827) (146280831)", None, 43),
    ("Anexo 4.1 - Relatório Fotográfico de Avanço Físico (95817039)", "relatorio", None),
    ("Anexo 0 - Carta de Encaminhamento de Medição (95811404)", None, None),
])
def test_papel_e_numero(titulo, papel, n):
    assert fq.papel_do_titulo(titulo) == papel
    assert fq.numero_medicao(titulo) == n


@real_geo
def test_pacote_da_7a_medicao_geo_liga_boletim_relatorio_e_nl():
    pk = next(p for p in fq.medicoes(GEO) if p["n"] == 7)
    assert [d["i"] for d in pk["boletim"]] == [26]
    assert [d["i"] for d in pk["relatorio"]] == [29]
    assert "2024NL00584" in pk["nl"]
    assert "2024OB01070" in pk["ob"]


# ── itens do boletim: só o que a aritmética fecha ──────────────────────────────────────────────────────────

@real_geo
def test_itens_da_7a_medicao_fecham_e_1_10_nao_vira_numero():
    pk = next(p for p in fq.medicoes(GEO) if p["n"] == 7)
    its = fq.itens_boletim(fq._texto_pacote(GEO, pk["boletim"]))
    assert len(its) == 37
    i11 = next(x for x in its if x["item"] == "1.1")
    assert (i11["qc"], i11["ant"], i11["per"], i11["acum"], i11["saldo"]) == (12.0, 4.03, 1.0, 5.03, 6.97)
    assert next(x for x in its if x["item"] == "1.10")["pu"] == 6.18   # "1.10" é o ITEM seguinte, não 1,1


@real_geo
def test_item_produtivo_improdutivo_com_sufixo():
    pk = next(p for p in fq.medicoes(GEO) if p["n"] == 20)
    its = fq.itens_boletim(fq._texto_pacote(GEO, pk["boletim"]))
    assert {"1.7-P", "1.7-I"} <= {x["item"] for x in its}


def test_aritmetica_trivial_x_mais_zero_nao_e_acumulado():
    # 020001/002796/2025: "23.942,48 | 0 | 23.942,48" (valor em R$) virava 23.942 placas acumuladas
    txt = "1.3\nPLACA DE SINALIZAÇÃO PREVENTIVA\nUN\n32\nR$ 61,69\nR$ 1.974,08\n23.942,48\n0,00\n23.942,48\n"
    it = fq.itens_boletim(txt)[0]
    assert it["acum"] is None


def test_acumulado_acima_do_contratado_com_saldo_negativo_e_achado(tmp_path):
    txt = ("1.1\n01.001.0001-0\nPAVIMENTO\nM2\n100,00\n10,00\n1.000,00\n"
           "80,00\n800,00\n40,00\n400,00\n120,00\n1.200,00\n-20,00\n-200,00\n")
    it = fq.itens_boletim(txt)[0]
    assert (it["ant"], it["per"], it["acum"], it["saldo"]) == (80.0, 40.0, 120.0, -20.0)
    pasta = tmp_path / "p"
    (pasta / "texto").mkdir(parents=True)
    (pasta / "texto" / "000.txt").write_text(txt, encoding="utf-8")
    pk = {"n": 1, "boletim": [{"i": 0, "titulo": "Planilha de Medição", "texto": "texto/000.txt"}], "memoria": [],
          "relatorio": [], "diario": [], "aceite": [], "nl": [], "ob": []}
    r = fq.confrontar_medicao(pasta, pk, titulos_processo="Planilha de Medição")
    s = [x for x in r["sinais"] if x["tipo"] == "ACUMULADO_EXCEDE_CONTRATADO"]
    assert s and s[0]["excesso"] == 20.0 and s[0]["porque"]["classe"] == "sem-explicação"
    r2 = fq.confrontar_medicao(pasta, pk, titulos_processo="1º Termo Aditivo ao Contrato 12/2024")
    assert [x for x in r2["sinais"] if x["tipo"] == "ACUMULADO_EXCEDE_CONTRATADO"][0]["porque"]["classe"] == \
        "inocente-provável"


def test_quantidade_antes_da_unidade_ocr_ponto_decimal():
    txt = "1.01 | EMOP | 01.016.0 809-9 SERVÍCIOS TOPOGRÁFICOS | 8.00 | MÊS | R$ 17.582.02 | R$ 140.656.16 |"
    it = fq.itens_boletim(txt)[0]
    assert (it["qc"], it["pu"], it["unidade"]) == (8.0, 17582.02, "mês")


# ── frentes: o mesmo lugar escrito de outro jeito ──────────────────────────────────────────────────────────

def test_mesmo_local_ordem_trocada_e_erro_de_digitacao():
    assert fq.mesmo_local(fq._toks_local("CABO FRIO - CANAL MARIMBOMDO"), fq._toks_local("CANAL MARIMBONDO – CABO FRIO"))
    assert fq.mesmo_local(fq._toks_local("BUZIOS - RIO ARETÊ"), fq._toks_local("BUZIOS – CANAL DO ARETÊ"))
    assert fq.mesmo_local(fq._toks_local("RIO DAS OSTRAS - RIO MEDEIROS"),
                          fq._toks_local("RIO MEDEIROS – RIO DAS OSTAS"))
    assert not fq.mesmo_local(fq._toks_local("IGUABA GRANDE - RIO UBÁS"),
                              fq._toks_local("IGUABA GRANDE – CANAL BOA VISTA"))


def test_frente_provavel_exige_nome_proprio_do_corpo_nao_so_municipio():
    assert fq.mesma_frente_provavel("BUZIOS - CASA DO PESCADOR", "BUZIOS - CANAL MERCADO DO PESCADOR")
    assert not fq.mesma_frente_provavel("IGUABA GRANDE - RIO UBÁS", "IGUABA GRANDE – CANAL BOA VISTA")
    assert not fq.mesma_frente_provavel("SÃO PEDRO DA ALDEIA - ESTRADA VELHA DE BUZIOS", "BUZIOS - RIO ARETÊ")


def test_frente_zerada_na_memoria_nao_cobra_foto():
    txt = ("1.13-P\nBUZIOS - CANAL ACEROLA\n19.005.0010-2\n0\n-\n"
           "1.13-P\nSILVA JARDIM - RIO BIQUINHA\n19.005.0010-2\n1\n317,27\n")
    z = fq.frentes_zeradas(txt)
    assert fq._toks_local("BUZIOS - CANAL ACEROLA") in z
    assert fq._toks_local("SILVA JARDIM - RIO BIQUINHA") not in z
    txt_a = "BUZIOS - LAGOA EST. ÁLVARO GONÇALVES\nQuantidade\nHoras\n%\n1,00 un\nx\n0,00 h\nx\n70,00%\n=\n0,00 h\n"
    assert fq._toks_local("BUZIOS - LAGOA EST. ÁLVARO GONÇALVES") in fq.frentes_zeradas(txt_a)


@real_geo
def test_nbsp_na_legenda_nao_some_com_a_frente():
    pk = next(p for p in fq.medicoes(GEO) if p["n"] == 12)
    loc = fq.locais(fq._texto_pacote(GEO, pk["relatorio"]))
    assert any(fq.mesmo_local(k, fq._toks_local("RIO DAS OSTRAS - RIO JUNDIÁ")) for k in loc)


@real_geo
def test_geo_mapas_nao_sao_foto_sem_legenda_e_13a_e():
    meds = {p["n"]: p for p in fq.medicoes(GEO)}
    t7 = {s["tipo"] for s in fq.confrontar_medicao(GEO, meds[7])["sinais"]}
    assert "FOTOS_SEM_LEGENDA" not in t7      # 17 páginas mudas = mapas de 18 frentes (029_p04)
    s13 = [s for s in fq.confrontar_medicao(GEO, meds[13])["sinais"] if s["tipo"] == "FOTOS_SEM_LEGENDA"]
    assert s13 and s13[0]["grau"] == "lacuna"


@real_geo
def test_geo_23a_biquinha_medida_sem_foto_e_acerola_zerada_nao():
    meds = {p["n"]: p for p in fq.medicoes(GEO)}
    s23 = {s["local"]: s for s in fq.confrontar_medicao(GEO, meds[23])["sinais"] if s["tipo"] == "FRENTE_MEDIDA_SEM_FOTO"}
    assert "SILVA JARDIM - RIO BIQUINHA" in s23 and s23["SILVA JARDIM - RIO BIQUINHA"]["horas_medidas"] > 600
    s20 = {s.get("local") for s in fq.confrontar_medicao(GEO, meds[20])["sinais"]}
    assert "BUZIOS - CANAL ACEROLA" not in s20


@real_agro
def test_agro_sem_legenda_e_lacuna_com_porque_da_memoria():
    pk = fq.medicoes(AGRO)[0]
    r = fq.confrontar_medicao(AGRO, pk)
    assert not [s for s in r["sinais"] if s["tipo"] == "ACUMULADO_EXCEDE_CONTRATADO"]
    s = [x for x in r["sinais"] if x["tipo"] == "RELATORIO_SEM_LEGENDA"][0]
    assert s["grau"] == "lacuna" and s["porque"]["classe"] in fq.CLASSES_PORQUE


# ── datas ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_periodo_com_e_sem_ano_no_inicio():
    assert fq.periodo("Período: 23/02/2024 à 22/03/2024 – CONTRATO")[:2] == (date(2024, 2, 23), date(2024, 3, 22))
    assert fq.periodo("PERÍODO MEDIDO: 04/04 à 05/05/2025")[:2] == (date(2025, 4, 4), date(2025, 5, 5))
    assert fq.periodo("PERÍODO DE 15/12 A 14/01/2025")[:2] == (date(2024, 12, 15), date(2025, 1, 14))


def test_carimbo_ignora_assinatura_do_sei():
    txt = ("Documento assinado eletronicamente por FULANO, em 09/04/2024, às 10:33\n"
           "Foto 3 - escavação 12/08/2024 09:37\n")
    assert fq.carimbos(txt) == [(date(2024, 8, 12), "Foto 3 - escavação 12/08/2024 09:37")]


def test_foto_antes_do_periodo_e_contradicao_salvo_legenda_de_antes(tmp_path):
    pasta = tmp_path / "p"
    (pasta / "texto").mkdir(parents=True)
    (pasta / "texto" / "0.txt").write_text("Período: 23/08/2024 a 22/09/2024", encoding="utf-8")
    (pasta / "texto" / "1.txt").write_text("Período: 23/08/2024 a 22/09/2024\nfrente A 12/08/2024 09:37\n"
                                           "situação antes da limpeza 10/08/2024 08:00\n", encoding="utf-8")
    pk = {"n": 13, "boletim": [{"i": 0, "titulo": "Anexo 13ª Medição", "texto": "texto/0.txt"}], "memoria": [],
          "relatorio": [{"i": 1, "titulo": "Relatório Fotográfico - 13ª Medição", "texto": "texto/1.txt"}],
          "diario": [], "aceite": [], "nl": [], "ob": []}
    s = [x for x in fq.confrontar_medicao(pasta, pk)["sinais"] if x["tipo"] == "FOTO_FORA_DO_PERIODO"]
    cls = {x["data_foto"]: x["porque"]["classe"] for x in s}
    assert cls == {"2024-08-12": "contradição", "2024-08-10": "inocente-provável"}


# ── diário: rótulo do formulário não é o que se preencheu ──────────────────────────────────────────────────

def test_diario_rotulo_em_todo_dia_nao_e_parada():
    dias = []
    for d in range(1, 11):
        extra = "SEM ATIVIDADES - CHUVA FORTE" if d == 5 else "Escavação no trecho 2"
        dias.append(f"DATA: {d:02d}/06/2025\nNão houve atividade\n3 - Chuvoso\nParalisado\n{extra}\n")
    r = fq.dias_do_diario("\n".join(dias), (date(2025, 6, 1), date(2025, 6, 30)))
    assert len(r) == 10
    assert [x["data"].day for x in r if x["parado"]] == [5]
    assert [x["data"].day for x in r if x["chuva"]] == [5]


# ── SIAFE: só OB paga ──────────────────────────────────────────────────────────────────────────────────────

def test_ob_paga_so_contabilizada_nao_devolvida_com_numero():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, valor, nl, nome_credor, "
                "credor, tipo_ob, finalidade, status, status_envio, processo)")
    rows = [("2024OB00001", "243200", "05/04/2024", 100.0, "2024NL00584", "GEO", "18463305000103", "", "",
             "Contabilizado", "Processado e Pago", "SEI-070002/005897/2024"),
            ("2024OB00002", "243200", "05/04/2024", 100.0, "2024NL00584", "GEO", "18463305000103", "", "",
             "Contabilizado", "Erro no Pagamento", "SEI-070002/005897/2024"),
            ("2024OB00003", "243200", "05/04/2024", 100.0, "2024NL00584", "GEO", "18463305000103", "", "",
             "Cancelado", "", "SEI-070002/005897/2024"),
            ("", "243200", "05/04/2024", 100.0, "2024NL00584", "GEO", "18463305000103", "", "",
             "Contabilizado", "", "SEI-070002/005897/2024")]
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    obs = fq.obs_pagas_do_processo(con, "070002/005897/2024")
    assert [o["numero_ob"] for o in obs] == ["2024OB00001"]
    assert obs[0]["data"] == date(2024, 4, 5)


def test_cpf_de_credor_e_mascarado():
    assert fq._cnpj_mascarado("12345678901") == "***.456.789-**"
    assert fq._cnpj_mascarado("18463305000103") == "18463305000103"


# ── memória de cálculo copiada de outra medição ────────────────────────────────────────────────────────────

def test_memoria_copiada_sintetica_e_negativo(tmp_path):
    pasta = tmp_path / "p"
    (pasta / "texto").mkdir(parents=True)
    linhas = "".join(f"1.21-P\nMUNICIPIO X - RIO {chr(65 + k)}{chr(65 + k)}{chr(65 + k)}OS\n19.004.0016-2\n1\n{100 + k},50\n"
                     for k in range(22))
    outra = "".join(f"1.21-P\nMUNICIPIO X - RIO {chr(65 + k)}{chr(65 + k)}{chr(65 + k)}OS\n19.004.0016-2\n1\n{200 + k},50\n"
                    for k in range(22))
    for i, t in enumerate((linhas, linhas, outra)):
        (pasta / "texto" / f"{i}.txt").write_text(t, encoding="utf-8")

    def pk(n, i):
        return {"n": n, "boletim": [{"i": i, "titulo": f"Anexo {n}ª Medição", "texto": f"texto/{i}.txt"}],
                "memoria": [], "relatorio": [], "diario": [], "aceite": [], "nl": [], "ob": []}
    pks = [pk(21, 0), pk(23, 1), pk(24, 2)]
    c = fq.memorias_copiadas(pasta, pks)
    assert id(pks[1]) in c and c[id(pks[1])]["de"] == 21 and c[id(pks[1])]["iguais"] == 22
    assert id(pks[2]) not in c and id(pks[0]) not in c


@real_geo
def test_geo_23a_memoria_e_copia_da_21a_e_frente_explicada_pelo_controle():
    r = fq.confrontar_processo(GEO)
    m23 = next(m for m in r["medicoes"] if m["n"] == 23)
    cop = [s for s in m23["sinais"] if s["tipo"] == "MEMORIA_COPIADA"]
    assert cop and cop[0]["copia_da_medicao"] == 21 and cop[0]["porque"]["classe"] == "contradição"
    biq = next(s for s in m23["sinais"] if s.get("local") == "SILVA JARDIM - RIO BIQUINHA")
    assert biq["porque"]["classe"] == "inocente-provável" and "CÓPIA da 21ª" in biq["porque"]["explicacao"]


def test_item_inteiro_com_codigo_e_saldo_antes_menos_medido():
    # SEHIS × Augusto Velloso (490001/000249/2026), 2ª medição: "saldo antes | medido | saldo atual | acumulado"
    txt = ("1\n13.373.0020-0\nPISO\nDE\nCONCRETO\nM2\n39.000,00\n125,01\n4.875.390,00\n"
           "8.310,29\n8.310,29\n0,00\n39.000,00\n")
    it = fq.itens_boletim(txt)[0]
    assert (it["item"], it["per"], it["acum"], it["saldo"]) == ("1", 8310.29, 39000.0, 0.0)


def test_acumulado_zero_trivial_perde_para_o_positivo():
    txt = "1.1\nX\nM\n100,00\n2,00\n200,00\n0,00\n100,00\n"
    it = fq.itens_boletim(txt)[0]
    assert it["acum"] == 0.0 and it["saldo"] == 100.0       # só há o par trivial: medida nenhuma
    txt2 = "1.1\nX\nM\n100,00\n2,00\n200,00\n60,00\n40,00\n0,00\n100,00\n"
    assert fq.itens_boletim(txt2)[0]["acum"] == 60.0


def test_diario_sem_dia_do_periodo_e_contradicao(tmp_path):
    pasta = tmp_path / "p"
    (pasta / "texto").mkdir(parents=True)
    (pasta / "texto" / "0.txt").write_text("PERÍODO DE 16/06/2026 A 30/06/2026", encoding="utf-8")
    (pasta / "texto" / "1.txt").write_text("INICIO CONTRATO | 2025-10-03 00:00:00\n" + "Escavação. " * 300,
                                           encoding="utf-8")
    pk = {"n": 1, "boletim": [{"i": 0, "titulo": "Planilha 1ª Medição", "texto": "texto/0.txt"}], "memoria": [],
          "relatorio": [], "diario": [{"i": 1, "titulo": "Diário de Obras", "texto": "texto/1.txt"}],
          "aceite": [], "nl": [], "ob": []}
    pk["relatorio"] = [{"i": 1, "titulo": "Relatório Fotográfico", "texto": "texto/1.txt"}]
    s = [x for x in fq.confrontar_medicao(pasta, pk)["sinais"] if x["tipo"] == "DIARIO_SEM_DIA_DO_PERIODO"]
    # só a data de cabeçalho (início de OUTRO contrato): lacuna, não contradição
    assert s and s[0]["porque"]["classe"] == "sem-explicação" and "2025-10-03" in s[0]["datas_no_diario"]
    (pasta / "texto" / "1.txt").write_text("".join(f"Data: {d:02d}/04/2026\nEscavação. " + "x " * 200
                                                   for d in range(1, 8)), encoding="utf-8")
    s = [x for x in fq.confrontar_medicao(pasta, pk)["sinais"] if x["tipo"] == "DIARIO_SEM_DIA_DO_PERIODO"]
    assert s[0]["porque"]["classe"] == "contradição"        # dias de OUTRO mês, nenhum do período
    (pasta / "texto" / "1.txt").write_text("".join(f"Data: {d:02d}/06/2025\nEscavação. " + "x " * 200
                                                   for d in range(16, 23)), encoding="utf-8")
    s = [x for x in fq.confrontar_medicao(pasta, pk)["sinais"] if x["tipo"] == "DIARIO_SEM_DIA_DO_PERIODO"]
    assert s[0]["porque"]["classe"] == "inocente-provável"  # mesmo mês, ano trocado


def test_nl_de_guia_nao_liga_ob_a_outra_medicao(tmp_path):
    import json as _j
    pasta = tmp_path / "p"
    pasta.mkdir()
    docs = [{"i": 0, "titulo": "Anexo 4ª Medição (1)"}, {"i": 1, "titulo": "Nota de Liquidação - NL 2025NL03532 (2)"},
            {"i": 2, "titulo": "Anexo 6ª Medição (3)"}, {"i": 3, "titulo": "Guia GRE IRRF R$ 125.948,00 - 2025NL03532 (4)"},
            {"i": 4, "titulo": "Ordem Bancária Orçamentária 2025OB06150 / R$ 8.566.466,22 (5)"}]
    (pasta / "manifest.json").write_text(_j.dumps({"processo": "x", "docs": docs}), encoding="utf-8")
    m = {p["n"]: p for p in fq.medicoes(pasta)}
    assert m[4]["nl"] == ["2025NL03532"] and m[6]["nl"] == [] and m[6]["ob"] == ["2025OB06150"]


def test_periodo_do_relatorio_antes_do_inicio_do_contrato_e_erro_de_ano(tmp_path):
    # SEI-330001/000578/2025 (Plenaplan, Valença), 8ª: boletim 05/2025 × relatório "01/05/2024 a 31/05/2024";
    # o diário diz "INÍCIO DO CONTRATO: 01/10/2024" — o período do relatório não pode existir.
    pasta = tmp_path / "p"
    (pasta / "texto").mkdir(parents=True)
    (pasta / "texto" / "0.txt").write_text("PLANILHA DE MEDIÇÃO PERÍODO DE 01/05 A 31/05/2025", encoding="utf-8")
    (pasta / "texto" / "1.txt").write_text("Período de Referência\n01/05/2024 a 31/05/2024\nfoto", encoding="utf-8")
    (pasta / "texto" / "2.txt").write_text("INÍCIO DO CONTRATO: 01/10/2024", encoding="utf-8")
    pk = {"n": 8, "boletim": [{"i": 0, "titulo": "BOLETIM DE MEDIÇÃO 8ª", "texto": "texto/0.txt"}], "memoria": [],
          "relatorio": [{"i": 1, "titulo": "RELATÓRIO FOTOGRÁFICO 8ª", "texto": "texto/1.txt"}],
          "diario": [{"i": 2, "titulo": "Diário de Obras 8ª", "texto": "texto/2.txt"}], "aceite": [], "nl": [], "ob": []}
    s = [x for x in fq.confrontar_medicao(pasta, pk)["sinais"] if x["tipo"] == "PERIODO_RELATORIO_DIVERGE"]
    assert s and s[0]["porque"]["classe"] == "inocente-comprovada"
    (pasta / "texto" / "2.txt").write_text("sem data de início", encoding="utf-8")
    s = [x for x in fq.confrontar_medicao(pasta, pk)["sinais"] if x["tipo"] == "PERIODO_RELATORIO_DIVERGE"]
    assert s[0]["porque"]["classe"] == "inocente-provável"


# ── falsos positivos da 1ª rodada no acervo (18/11/2026), cada um virou regra ───────────────────────────────

def test_paralisacao_parcial_nao_e_dia_parado():
    dias = "".join(f"Data:\n{d:02d}/02/2025\nTIRANTE; INJEÇÃO DE CALDA\nOBS: SERVIÇOS NA PONTE 3 PARALISADOS POR "
                   f"DEPENDENCIA DE DESAPROPRIAÇÃO\n" for d in range(3, 8))
    dias += "Data:\n08/02/2025\nNÃO HOUVERAM SERVIÇOS - FINAL DE SEMANA\n"
    r = fq.dias_do_diario(dias, (date(2025, 2, 1), date(2025, 2, 28)))
    assert [x["data"].day for x in r if x["parado"]] == [8]


def test_data_por_extenso_no_rdo():
    r = fq.dias_do_diario("DATA:\nsábado, 1 de março de 2025\nx\nDATA:\ndomingo, 2 de março de 2025\ny\n")
    assert [x["data"] for x in r] == [date(2025, 3, 1), date(2025, 3, 2)]


def test_carimbo_de_fluxo_do_aplicativo_nao_e_data_da_foto():
    txt = ("Aprovado   02/12/2025 15:28\nCriado por: Ana (20/08/2025 13:40)\nEnc. Fabrício Lana    26/07/2024 10:52\n"
           "Foto da vala 03/09/2024 08:15\n")
    assert [d for d, _ in fq.carimbos(txt)] == [date(2024, 9, 3)]


def test_atesto_e_a_primeira_assinatura():
    t = ("Documento assinado eletronicamente por A, Fiscal, em 05/07/2024, às 10:00\n"
         "Documento assinado eletronicamente por B, Coordenador, em 11/07/2024, às 09:00\n")
    assert fq.data_do_ato(t)[0] == date(2024, 7, 5)


def test_periodo_do_relatorio_que_cobre_parte_nao_diverge(tmp_path):
    pasta = tmp_path / "p"
    (pasta / "texto").mkdir(parents=True)
    (pasta / "texto" / "0.txt").write_text("período de 01/01/2024 a 24/02/2024", encoding="utf-8")
    (pasta / "texto" / "1.txt").write_text("Período: 25/01/24 a 24/02/24\nfoto", encoding="utf-8")
    (pasta / "texto" / "2.txt").write_text("Período: 23/10/2024 a 22/11/2024\nfoto", encoding="utf-8")
    pk = {"n": 22, "boletim": [{"i": 0, "titulo": "Anexo 22ª Medição", "texto": "texto/0.txt"}], "memoria": [],
          "relatorio": [{"i": 1, "titulo": "Relatório Fotográfico 22ª", "texto": "texto/1.txt"}], "diario": [],
          "aceite": [], "nl": [], "ob": []}
    assert not [x for x in fq.confrontar_medicao(pasta, pk)["sinais"] if x["tipo"] == "PERIODO_RELATORIO_DIVERGE"]
    pk["relatorio"] = [{"i": 2, "titulo": "Relatório Fotográfico 22ª", "texto": "texto/2.txt"}]
    assert [x for x in fq.confrontar_medicao(pasta, pk)["sinais"] if x["tipo"] == "PERIODO_RELATORIO_DIVERGE"]


def test_periodo_da_medicao_e_o_que_contem_o_diario(tmp_path):
    # 070002/006627/2024: o 1º "Período" do boletim era o da 1ª medição (histórico); o diário estava no mês certo
    pasta = tmp_path / "p"
    (pasta / "texto").mkdir(parents=True)
    (pasta / "texto" / "0.txt").write_text("1ª Período: 15/12/2023 a 31/12/2023\n14ª Período: 01/03/2024 a 31/03/2024",
                                           encoding="utf-8")
    (pasta / "texto" / "1.txt").write_text("".join(f"Data: {d:02d}/03/2024\nescavação\n" for d in range(1, 11)),
                                           encoding="utf-8")
    pk = {"n": 14, "boletim": [{"i": 0, "titulo": "Anexo 14ª Medição", "texto": "texto/0.txt"}], "memoria": [],
          "relatorio": [], "diario": [{"i": 1, "titulo": "Diário de Obras - 14ª Medição", "texto": "texto/1.txt"}],
          "aceite": [], "nl": [], "ob": []}
    r = fq.confrontar_medicao(pasta, pk)
    assert r["periodo"] == ["2024-03-01", "2024-03-31"]
