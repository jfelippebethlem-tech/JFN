# -*- coding: utf-8 -*-
"""Soma do PAGO de um processo: OB do SIAFE ligada pelo nº do processo E pela NL/PD/OB juntada nos autos.

18/11/2026 — 4 agentes de perícia, na leitura integral de 40 processos, acharam a soma por `processo` SUBCONTANDO
(OB com `processo` vazio em 2021–2023, OB gravada no processo-mãe / de outra unidade) e DUPLICANDO (OB devolvida e
reemitida; regularização de OB devolvida). Os casos abaixo reproduzem as linhas REAIS do SIAFE de cada caso.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from compliance_agent import ob_processo as P
from compliance_agent.sei import manifesto_norm

COLS = ("numero_ob", "ug_emitente", "ug_liquidante", "data_emissao", "status", "status_envio", "nl", "pd", "gd",
        "credor", "processo", "tipo_regularizacao", "valor", "exercicio")


@pytest.fixture(autouse=True)
def _acervo_vazio(monkeypatch, tmp_path):
    """O acervo REAL nunca decide o teste: cada teste monta a sua pasta de autos."""
    monkeypatch.setattr(manifesto_norm, "_BASE", tmp_path / "sei_arquivo")
    (tmp_path / "sei_arquivo").mkdir()
    return tmp_path / "sei_arquivo"


def _base(linhas: list[dict], gds: list[tuple] = (), nls: list[tuple] = ()) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.execute(f"CREATE TABLE ob_orcamentaria_siafe ({', '.join(COLS)}, PRIMARY KEY (numero_ob, ug_emitente, exercicio))")
    for l in linhas:
        d = {"ug_liquidante": l.get("ug_emitente"), "status": "Contabilizado", "status_envio": "Processado e Pago",
             "nl": "", "pd": "", "gd": "", "processo": "", "tipo_regularizacao": "", "data_emissao": "01/01/2025",
             "exercicio": int(l["numero_ob"][:4]), **l}
        con.execute(f"INSERT INTO ob_orcamentaria_siafe VALUES ({','.join('?' * len(COLS))})", [d[c] for c in COLS])
    con.execute("CREATE TABLE gd_siafe (numero TEXT, ug_emitente TEXT, exercicio INT, ano_gd INT, data_emissao TEXT, "
                "tipo_baixa TEXT, status TEXT, ug_liquidante TEXT, ob TEXT, valor REAL, coletado_em TEXT)")
    for numero, ug, ob, valor, status in gds:
        con.execute("INSERT INTO gd_siafe VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (numero, ug, int(numero[:4]), int(numero[:4]), "", "Banco", status, ug, ob, valor, ""))
    con.execute("CREATE TABLE nl_siafe (numero TEXT, ug_emitente TEXT, exercicio INT, credor TEXT, valor REAL, "
                "processo TEXT, status TEXT)")
    for numero, ug, credor, valor in nls:
        con.execute("INSERT INTO nl_siafe VALUES (?,?,?,?,?,?,?)", (numero, ug, int(numero[:4]), credor, valor, "",
                                                                      "Contabilizado"))
    return con


def _autos(raiz: Path, numero: str, docs: list[tuple[str, str]]) -> Path:
    """docs = [(titulo, texto)] → data/sei_arquivo/<tag>/{manifest.json, texto/NNN.txt}."""
    tag = numero.replace("SEI-", "").replace("/", "_")
    pasta = raiz / tag
    (pasta / "texto").mkdir(parents=True)
    man = {"processo": numero, "docs": []}
    for i, (titulo, texto) in enumerate(docs):
        rel = f"texto/{i:03d}.txt"
        (pasta / rel).write_text(f"[{titulo}] (fase: despesa · tipo: outro)\n\n{texto}", encoding="utf-8")
        man["docs"].append({"i": i, "titulo": titulo, "tipo": "outro", "texto": rel})
    (pasta / "manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    return pasta


def _espelho(tipo: str, ug: str, numero: str, valor: str, credor: str, *, nl: str = "", ob: str = "",
             processo: str = "") -> str:
    """Espelho do SIAFE-Rio como o SEI o guarda em texto (layout real de NL/PD/OB/GD)."""
    cab = {"NL": "Nota de Liquidação", "PD": "Programação de Desembolso Orçamentária",
           "OB": "Ordem Bancária Orçamentária", "GD": "Guia Devolução"}[tipo]
    linhas = ["Governo do Estado do Rio de Janeiro", cab, "Identificação", "UG Emitente", "Documento", "Emissão",
              f"{ug} - UNIDADE", numero, "10/11/26", "Valor por Extenso", "Valor", valor, "Detalhamento"]
    if ob:
        linhas += ["Ordem Bancária", ob]
    if nl:
        linhas += ["Nota Liquidação", nl]
    linhas += ["Credor", f"{credor} - CREDOR LTDA"]
    if processo:
        linhas += ["Processo", processo]
    return "\n".join(linhas)


def _um(con, numero, **kw) -> dict:
    m = P.obs_por_processo(con, [numero], **kw)
    return m.get(P.chave_processo(numero)) or {}


# ── 1. grafia variante: Seleta (SEI-210108/000153/2023) — 35 OB / R$ 39.340.668,31 ────────────────────────────
SELETA = [("2024OB00074", 865813.24), ("2024OB00500", 869123.56), ("2024OB00640", 830857.92),
          ("2024OB01038", 878430.09), ("2024OB01382", 864300.49), ("2024OB01489", 940792.41),
          ("2024OB02012", 902464.12), ("2024OB02256", 923555.78), ("2024OB02656", 904991.81),
          ("2024OB02970", 1193172.09), ("2024OB03362", 966424.77), ("2024OB03481", 918241.72),
          ("2025OB00135", 974537.11), ("2025OB00517", 718329.39), ("2025OB00836", 809260.27),
          ("2025OB01050", 867929.58), ("2025OB01595", 821262.37), ("2025OB02087", 851156.17),
          ("2025OB02549", 789635.78), ("2025OB03070", 802274.48), ("2025OB03405", 799386.38),
          ("2025OB03819", 801497.76), ("2025OB04346", 913681.92), ("2025OB04381", 402829.19),
          ("2025OB04839", 1483407.36), ("2026OB00155", 1538936.74), ("2026OB00438", 1576951.29),
          ("2026OB00785", 1574642.09), ("2026OB01109", 1745400.6), ("2026OB01523", 1736855.3),
          ("2026OB01842", 1770663.67), ("2026OB02159", 1707916.04), ("2026OB02488", 1839093.67),
          ("2026OB02927", 1863267.27), ("2026OB03172", 1893585.88)]
_GRAFIA_SELETA = {"2025OB04346": "210108/000153/2023", "2025OB04381": "210108/000153/2023",
                  "2026OB00438": "210108/000153/2023", "2024OB00074": "SEI-210108/000153/23"}


def test_seleta_grafias_variantes_somam_35_ob():
    con = _base([{"numero_ob": ob, "ug_emitente": "250100", "credor": "01234567000189", "valor": v,
                  "processo": _GRAFIA_SELETA.get(ob, "SEI-210108/000153/2023")} for ob, v in SELETA])
    d = _um(con, "SEI-210108/000153/2023", autos=False)
    assert d["n"] == 35
    assert round(d["total"], 2) == 39340668.31
    assert round(d["por_via"]["processo_exato"], 2) == 35581392.67                  # o que a regra exata achava
    assert round(d["por_via"]["processo_normalizado"], 2) == round(39340668.31 - 35581392.67, 2)
    assert {o["numero_ob"] for o in d["obs"] if o["via"] == "processo_normalizado"} == set(_GRAFIA_SELETA)


def test_locasem_ano_com_dois_digitos():
    con = _base([{"numero_ob": "2024OB00155", "ug_emitente": "250100", "credor": "1", "valor": 740679.67,
                  "processo": "SEI-210108/000165/23"},
                 {"numero_ob": "2024OB00504", "ug_emitente": "250100", "credor": "1", "valor": 959578.21,
                  "processo": "SEI-210108/000165/2023"}])
    d = _um(con, "SEI-210108/000165/2023", autos=False)
    assert d["n"] == 2 and round(d["total"], 2) == round(740679.67 + 959578.21, 2)
    assert [o["via"] for o in d["obs"] if o["numero_ob"] == "2024OB00155"] == ["processo_normalizado"]


# ── 2. devolução + reemissão: Lar São Francisco (SEI-080001/035583/2026) ───────────────────────────────────────
LAR = "53221255004995"
_LAR_OBS = [{"numero_ob": "2026OB16652", "ug_emitente": "296100", "credor": LAR, "valor": 4378264.15,
             "nl": "2026NL09849", "pd": "2026PD17747", "status_envio": "Enviado ao Banco", "data_emissao": "10/11/2026",
             "processo": "SEI-080001/035583/2026"},
            {"numero_ob": "2026OB16931", "ug_emitente": "296100", "credor": LAR, "valor": 4378264.15,
             "nl": "2026NL09849", "pd": "2026PD18426", "status_envio": "Enviado ao Banco", "data_emissao": "13/11/2026",
             "processo": "SEI-080001/035583/2026"},
            # mesmo nº de OB em OUTRA UG: não é deste processo
            {"numero_ob": "2026OB16652", "ug_emitente": "180100", "credor": "83446729704", "valor": 637.0,
             "nl": "2026NL13493", "processo": "SEI-030001/078861/2026"}]


def test_lar_sao_francisco_gd_dos_autos_desconta_a_devolvida(_acervo_vazio):
    _autos(_acervo_vazio, "SEI-080001/035583/2026", [
        ("Guia de Devolução 2026GD00778", _espelho("GD", "296100", "2026GD00778", "4.378.264,15", LAR,
                                                   ob="2026OB16652", nl="2026NL09849"))])
    d = _um(_base(_LAR_OBS), "SEI-080001/035583/2026")
    assert round(d["total"], 2) == 4378264.15
    dev = [o for o in d["obs"] if o["numero_ob"] == "2026OB16652"][0]
    assert dev["valor_efetivo"] == 0.0 and "2026GD00778" in dev["nota"]


def test_lar_sao_francisco_gd_da_base_tambem_desconta():
    con = _base(_LAR_OBS, gds=[("2026GD00778", "296100", "2026OB16652", 4378264.15, "Contabilizado")])
    assert round(_um(con, "SEI-080001/035583/2026", autos=False)["total"], 2) == 4378264.15


def test_gd_anulada_nao_desconta():
    con = _base(_LAR_OBS, gds=[("2026GD00778", "296100", "2026OB16652", 4378264.15, "Anulado")])
    assert round(_um(con, "SEI-080001/035583/2026", autos=False)["total"], 2) == 8756528.30


def test_mvt_erro_no_pagamento_fora_e_sua_gd_nao_desconta_a_reemissao():
    con = _base([{"numero_ob": "2025OB12711", "ug_emitente": "180100", "credor": "14619967000160",
                  "valor": 30131810.59, "status_envio": "Erro no Pagamento", "gd": "2025GD00158",
                  "processo": "SEI-030001/056588/2025"},
                 {"numero_ob": "2025OB13675", "ug_emitente": "180100", "credor": "14619967000160",
                  "valor": 30131810.59, "processo": "SEI-030001/056588/2025"}],
                gds=[("2025GD00158", "180100", "2025OB12711", 30131810.59, "Contabilizado")])
    d = _um(con, "SEI-030001/056588/2025", autos=False)
    assert d["n"] == 1 and round(d["total"], 2) == 30131810.59


# ── 3. regularização de OB devolvida: SES × OPAS (SEI-080001/022031/2021), R$ 56,8 mi contados uma vez ────────
OPAS = "04096431000154"


def _opas():
    return _base([
        {"numero_ob": "2022OB03647", "ug_emitente": "296100", "credor": OPAS, "valor": 56800000.0,
         "pd": "2022PD03693", "gd": "2022GD00390", "data_emissao": "01/04/2022"},
        {"numero_ob": "2022OB16321", "ug_emitente": "296100", "credor": OPAS, "valor": 25244265.04,
         "pd": "2022PD17064", "status_envio": "Enviado Manualmente", "tipo_regularizacao": "OB já encaminhada ao banco",
         "data_emissao": "09/11/2022"},
        {"numero_ob": "2022OB16322", "ug_emitente": "296100", "credor": OPAS, "valor": 31555734.96,
         "pd": "2022PD17065", "status_envio": "Enviado Manualmente", "tipo_regularizacao": "OB já encaminhada ao banco",
         "data_emissao": "09/11/2022"},
        {"numero_ob": "2024OB04340", "ug_emitente": "296100", "credor": OPAS, "valor": 18631500.0,
         "nl": "2024NL01442", "processo": "SEI-080001/022031/2021"},
        # OUTRO processo (emenda), mesmo credor e UG — nada nos autos o cita: não entra
        {"numero_ob": "2024OB19653", "ug_emitente": "296100", "credor": OPAS, "valor": 200000.0,
         "nl": "2024NL09875", "processo": "SEI-080001/025976/2024"},
        # processo vazio, mesmo credor/UG, outro projeto: nada nos autos o cita — não entra
        {"numero_ob": "2023OB03645", "ug_emitente": "296100", "credor": OPAS, "valor": 5773123.95,
         "pd": "2023PD00266"},
    ])


def test_opas_regularizacao_conta_os_56_8_mi_uma_vez(_acervo_vazio):
    _autos(_acervo_vazio, "SEI-080001/022031/2021", [
        ("Programação de Desembolso - PD 03693", _espelho("PD", "296100", "2022PD03693", "56.800.000,00", OPAS,
                                                          nl="2022NL02152", processo="sei-080001/022031/21")),
        ("Relação de Ordens Bancárias Externas 2022OB16321",
         _espelho("OB", "296100", "2022OB16321", "25.244.265,04", OPAS, nl="2022NL11525",
                  processo="SEI-080001/022031/21")),
        ("Relação de Ordens Bancárias Externas 2022OB16322",
         _espelho("OB", "296100", "2022OB16322", "31.555.734,96", OPAS, nl="2022NL11525",
                  processo="SEI-080001/022031/21")),
    ])
    d = _um(_opas(), "SEI-080001/022031/2021")
    assert round(d["total"], 2) == round(56800000.0 + 18631500.0, 2)
    vias = {o["numero_ob"]: o["via"] for o in d["obs"]}
    assert vias["2022OB03647"] == "pd_dos_autos" and vias["2022OB16321"] == "ob_dos_autos"
    assert "2024OB19653" not in vias and "2023OB03645" not in vias
    # a OB devolvida (GD na própria OB, valor da guia não coletado) fica FORA, marcada — nunca some calada
    orig = [o for o in d["obs"] if o["numero_ob"] == "2022OB03647"][0]
    assert orig["valor_efetivo"] == 0.0 and orig["marca"] == "devolvida_sem_valor"
    assert d["piso"] is True


def test_sem_autos_regularizacao_nao_e_inventada():
    d = _um(_opas(), "SEI-080001/022031/2021", autos=False)
    assert round(d["total"], 2) == 18631500.0 and d["n"] == 1


# ── 4. ponte pela NL dos autos (OB de 2021–2023 sem processo) e os negativos ─────────────────────────────────
CRED = "11222333000144"


def test_nl_dos_autos_puxa_ob_sem_processo_com_credor_ug_e_valor_coerentes(_acervo_vazio):
    _autos(_acervo_vazio, "SEI-210108/000001/2023", [
        ("Nota de Liquidação - NL 2023NL00073", _espelho("NL", "250100", "2023NL00073", "1.000,00", CRED))])
    con = _base([
        {"numero_ob": "2023OB00100", "ug_emitente": "250100", "credor": CRED, "valor": 990.0, "nl": "2023NL00073"},
        # mesma NL em OUTRA UG (outro processo): não entra
        {"numero_ob": "2023OB00100", "ug_emitente": "294200", "credor": CRED, "valor": 500.0, "nl": "2023NL00073",
         "processo": "SEI-080002/000001/2023"},
        # mesma NL/UG mas OUTRO credor (OCR trocou dígito? retenção?): não entra
        {"numero_ob": "2023OB00101", "ug_emitente": "250100", "credor": "99888777000166", "valor": 10.0,
         "nl": "2023NL00073"},
    ])
    d = _um(con, "SEI-210108/000001/2023")
    assert d["n"] == 1 and d["total"] == 990.0
    assert d["obs"][0]["via"] == "nl_dos_autos" and round(d["por_via"]["nl_dos_autos"], 2) == 990.0


def test_nl_dos_autos_nao_passa_do_valor_da_nl(_acervo_vazio):
    _autos(_acervo_vazio, "SEI-210108/000001/2023", [
        ("Nota de Liquidação - NL 2023NL00073", _espelho("NL", "250100", "2023NL00073", "1.000,00", CRED))])
    con = _base([{"numero_ob": "2023OB00100", "ug_emitente": "250100", "credor": CRED, "valor": 990.0,
                  "nl": "2023NL00073", "data_emissao": "05/01/2023"},
                 {"numero_ob": "2023OB00200", "ug_emitente": "250100", "credor": CRED, "valor": 990.0,
                  "nl": "2023NL00073", "data_emissao": "05/02/2023"}])
    d = _um(con, "SEI-210108/000001/2023")
    assert d["n"] == 0 and d["total"] == 0.0
    assert {x["numero_ob"] for x in d["candidatas"]} == {"2023OB00100", "2023OB00200"}


def test_nl_citada_como_referencia_historica_nao_puxa_ob_de_outro_processo(_acervo_vazio):
    _autos(_acervo_vazio, "SEI-210108/000002/2024", [
        ("Despacho de Formalização de Liquidação de Despesa",
         "Conforme a 2023NL00073 do contrato anterior, encaminho para liquidação da 2024NL00010."),
        ("Nota de Liquidação - NL 2024NL00010", _espelho("NL", "250100", "2024NL00010", "500,00", CRED))])
    con = _base([
        {"numero_ob": "2023OB00100", "ug_emitente": "250100", "credor": CRED, "valor": 990.0, "nl": "2023NL00073",
         "processo": "SEI-210108/000001/2023"},                      # é do processo ANTERIOR — fica lá
        {"numero_ob": "2024OB00010", "ug_emitente": "250100", "credor": CRED, "valor": 500.0, "nl": "2024NL00010"},
    ])
    d = _um(con, "SEI-210108/000002/2024")
    assert {o["numero_ob"] for o in d["obs"]} == {"2024OB00010"}


def test_ob_de_outro_processo_entra_so_com_o_espelho_juntado(_acervo_vazio):
    """Caxias × Bangu (SEI-150001/002095/2024): a OB de janeiro foi gravada no processo de Bangu; o espelho da OB,
    o da PD e o da NL estão juntados nos autos de Caxias, com o mesmo credor, UG e valor."""
    _autos(_acervo_vazio, "SEI-150001/002095/2024", [
        ("Ordem 2024OB00251 JAN/2024 NF 113", _espelho("OB", "140100", "2024OB00251", "4.296.815,37",
                                                        "21602870000100", nl="2024NL00042",
                                                        processo="SEI-150001/002094/2024"))])
    con = _base([{"numero_ob": "2024OB00251", "ug_emitente": "140100", "credor": "21602870000100",
                  "valor": 4296815.37, "nl": "2024NL00042", "pd": "2024PD00320",
                  "processo": "SEI-150001/002094/2024"},
                 {"numero_ob": "2024OB00483", "ug_emitente": "140100", "credor": "21602870000100",
                  "valor": 4294926.62, "processo": "SEI-150001/002095/2024"}])
    d = _um(con, "SEI-150001/002095/2024")
    assert round(d["total"], 2) == round(4296815.37 + 4294926.62, 2)
    o = [x for x in d["obs"] if x["numero_ob"] == "2024OB00251"][0]
    assert o["via"] == "ob_dos_autos" and o["processo_siafe"] == "SEI-150001/002094/2024"


def test_ob_nos_autos_fora_da_base_e_reportada_a_parte_nunca_somada(_acervo_vazio):
    _autos(_acervo_vazio, "SEI-210108/000003/2025", [
        ("Ordem Bancária 2025OB09999", _espelho("OB", "250100", "2025OB09999", "7.777,77", CRED))])
    d = _um(_base([]), "SEI-210108/000003/2025")
    assert d["total"] == 0.0 and d["n"] == 0
    assert d["nos_autos_fora_da_base"] == [{"numero_ob": "2025OB09999", "ug": "250100", "valor": 7777.77,
                                            "doc": "Ordem Bancária 2025OB09999"}]


def test_espelho_com_valor_divergente_nao_casa(_acervo_vazio):
    """OCR que troca dígito do nº da OB cai noutra OB do mesmo credor: o VALOR do espelho barra."""
    _autos(_acervo_vazio, "SEI-210108/000004/2025", [
        ("Ordem Bancária 2025OB00110", _espelho("OB", "250100", "2025OB00110", "1.234,56", CRED))])
    con = _base([{"numero_ob": "2025OB00110", "ug_emitente": "250100", "credor": CRED, "valor": 9999.0}])
    d = _um(con, "SEI-210108/000004/2025")
    assert d["n"] == 0 and d["candidatas"][0]["motivo"].startswith("valor")


def test_ob_nao_paga_nunca_entra_mesmo_citada(_acervo_vazio):
    _autos(_acervo_vazio, "SEI-210108/000005/2025", [
        ("Ordem Bancária 2025OB00120", _espelho("OB", "250100", "2025OB00120", "100,00", CRED))])
    con = _base([{"numero_ob": "2025OB00120", "ug_emitente": "250100", "credor": CRED, "valor": 100.0,
                  "status": "Anulado"}])
    d = _um(con, "SEI-210108/000005/2025")
    assert d["n"] == 0 and d["descartadas"][0]["motivo"] == "nao_paga_no_siafe"


# ── 5. compatibilidade: quem consome `mapa_obs_siafe` continua lendo n/total/datas ─────────────────────────────
def test_mapa_obs_siafe_delega_e_mantem_o_formato(_acervo_vazio):
    from tools import lex_execucao as L
    _autos(_acervo_vazio, "SEI-080001/035583/2026", [
        ("Guia de Devolução 2026GD00778", _espelho("GD", "296100", "2026GD00778", "4.378.264,15", LAR,
                                                   ob="2026OB16652"))])
    m = L.mapa_obs_siafe(_base(_LAR_OBS), ["SEI-080001/035583/2026"])
    d = m["080001/35583/2026"]
    assert d["n"] == 1 and round(d["total"], 2) == 4378264.15 and d["datas"] == ["13/11/2026"]


def test_mapa_obs_siafe_so_traz_processo_com_pagamento(_acervo_vazio):
    """Contrato antigo: chave presente ⇔ há OB paga (`lex_execucao._contestados` testa `in m`)."""
    from tools import lex_execucao as L
    _autos(_acervo_vazio, "SEI-210108/000003/2025", [
        ("Ordem Bancária 2025OB09999", _espelho("OB", "250100", "2025OB09999", "7.777,77", CRED))])
    assert L.mapa_obs_siafe(_base([]), ["SEI-210108/000003/2025"]) == {}
