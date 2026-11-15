# -*- coding: utf-8 -*-
"""Perícia contábil — decisão do dono de 14/11/2026. Dados 100% sintéticos.

1. Desdobramentos de ata / vários registros do MESMO processo de origem ao MESMO credor: perícia POR GRUPO
   (GRUPO_ATA_DENTRO / GRUPO_ATA_A_MAIOR / GRUPO_ATA_INDETERMINADO), nunca somada ao A_MAIOR individual.
2. Concessionária (energia, água/esgoto, gás, telefonia), cota condominial e assinatura: o "valor do contrato" é
   estimativa — o que seria A_MAIOR vai à classe própria CONSUMO_CONTINUO, com contagem e soma separadas.
Controles positivos E negativos em cada regra."""
import sqlite3
from datetime import date

import pytest

from compliance_agent import pericia_contabil as pc
from compliance_agent import pericia_contabil_rotina as rot

CORTE = date(2026, 11, 1)


def _db(tmp_path, contratos, obs, empresas=()):
    """contratos: (id, processo, sei_norm, data_contratacao ISO, valor, objeto, cnpj, vig_ini, vig_fim)
    obs: (numero, data DD/MM/AAAA, cnpj, processo, valor[, ug])"""
    db = tmp_path / "g.db"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE contratos_tcerj (id TEXT, processo TEXT, sei_norm TEXT, data_contratacao TEXT, valor_contrato REAL,
      status TEXT, unidade TEXT, objeto TEXT, fornecedor TEXT, cnpj TEXT, vig_inicio TEXT, vig_fim TEXT,
      num_contratacao TEXT);
    CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, ug_pagadora TEXT, data_emissao TEXT,
      status TEXT, credor TEXT, nome_credor TEXT, processo TEXT, valor REAL, exercicio INTEGER,
      nl TEXT DEFAULT '', competencia TEXT DEFAULT '', gd TEXT DEFAULT '', status_envio TEXT DEFAULT '');
    CREATE TABLE empresas (cnpj TEXT, atividade_princ TEXT);
    """)
    con.executemany(
        "INSERT INTO contratos_tcerj (id,processo,sei_norm,data_contratacao,valor_contrato,status,unidade,objeto,"
        "fornecedor,cnpj,vig_inicio,vig_fim,num_contratacao) VALUES (?,?,?,?,?,'Ativo','ORGAO',?,'FORN',?,?,?,?)",
        [(c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7], c[8], c[0]) for c in contratos])
    con.executemany(
        "INSERT INTO ob_orcamentaria_siafe (numero_ob,ug_emitente,ug_pagadora,data_emissao,status,credor,nome_credor,"
        "processo,valor,exercicio,status_envio) VALUES (?,?,?,?,'Contabilizado',?,'F',?,?,?,'Processado e Pago')",
        [(o[0], o[5] if len(o) > 5 else "800800", o[5] if len(o) > 5 else "800800", o[1], o[2], o[3], o[4],
          int(o[1][6:])) for o in obs])
    con.executemany("INSERT INTO empresas VALUES (?,?)", list(empresas))
    con.commit()
    con.close()
    return {r["id"]: r for r in pc.avaliar_estado(db, corte=CORTE)}


CRED = "12121212000112"
BASE = "3000010000012025"


def _ata(valores, obs, objeto="AQUISIÇÃO DE MEDICAMENTOS.", sufixos="ABCDEFG"):
    """N desdobramentos (sufixo A, B, …) do processo SEI-300001/000001/2025 ao mesmo credor — o sei_norm do TCE-RJ é
    o processo SEM o sufixo (forma medida na base real)."""
    return [(f"D{s}", f"SEI-300001/000001-{s}/2025", BASE, "2025-03-01T00:00:00.000", v, objeto, CRED, "01/03/2025",
             "28/02/2026") for s, v in zip(sufixos, valores)], obs


def _obs(valores, processo="SEI-300001/000001/2025", mes0=4):
    return [(f"2025OB{i:05d}", f"10/{mes0 + i:02d}/2025", CRED, processo, v) for i, v in enumerate(valores)]


# ───────────────────────── processo de origem do registro com lista de processos ─────────────────────────

@pytest.mark.parametrize("processo,esperado", [
    ("SEI-080002/000408/1/2024, SEI-080002/000408/2/2024, SEI-080002/000408/A/2024", ("0800020004082024", "")),
    ("SEI-270032/000072-A/2022, SEI-270032/000072-B/2022", ("2700320000722022", "")),
    ("SEI-180001/000559/I/2025, SEI-180001/000559B/2025, SEI-180001/000559C/2025", ("1800010005592025", "")),
    ("SEI-180002/003187/2/2026", ("1800020031872026", "")),
    # controles negativos: processos de origem distintos não se agrupam; sem SEI não há chave
    ("SEI-270042/000192/2021, SEI-270042/001221/2021", (None, "processos_de_origem_distintos")),
    ("SEI-360343/000230/2023, SEI-360343/000230D/2025", (None, "processos_de_origem_distintos")),
    ("02/000934/2024", (None, "")), ("", (None, "")), (None, (None, "")),
])
def test_base_do_processo(processo, esperado):
    assert pc.base_do_processo(processo) == esperado


def test_regua_conservadora_tira_valor_repetido_e_ata_mestre():
    assert pc.regua_conservadora([100.0, 50.0]) == pytest.approx(150.0)
    assert pc.regua_conservadora([100.0, 100.0]) == pytest.approx(100.0)          # mesmo registro duas vezes?
    assert pc.regua_conservadora([30.0, 70.0, 100.0]) == pytest.approx(100.0)     # 100 = 30 + 70 (ata-mestre?)
    assert pc.regua_conservadora([30.0, 70.0, 500.0]) == pytest.approx(600.0)


# ───────────────────────── grupo de ata ─────────────────────────

def test_grupo_dentro_da_soma_dos_desdobramentos(tmp_path):
    res = _db(tmp_path, *_ata([100_000.0, 50_000.0], _obs([70_000.0, 50_000.0])))
    for i in ("DA", "DB"):
        r = res[i]
        assert r["categoria"] == "GRUPO_ATA_DENTRO", r
        assert r["pago"] is None and r["diferenca"] is None        # o pago é do GRUPO — nunca somado por contrato
        assert r["grupo_pago"] == pytest.approx(120_000.0) and r["grupo_regua"] == pytest.approx(150_000.0)
        assert r["grupo_n"] == 2 and r["grupo_n_obs"] == 2 and r["vinculo"] == "grupo_ata"
    assert res["DA"]["grupo_ata"] == res["DB"]["grupo_ata"]


def test_grupo_acima_da_soma_e_estado_proprio_fora_do_a_maior(tmp_path):
    res = _db(tmp_path, *_ata([100_000.0, 50_000.0], _obs([100_000.0, 100_000.0])))
    assert {r["categoria"] for r in res.values()} == {"GRUPO_ATA_A_MAIOR"}
    assert res["DA"]["grupo_diferenca"] == pytest.approx(50_000.0)
    rs = pc.resumo(list(res.values()))[pc.ESTADO]
    assert rs["A_MAIOR"] == 0 and rs["excesso_a_maior"] == 0       # a manchete individual não recebe o grupo
    g = rs["grupos_ata"]
    assert g["n"] == 1 and g["GRUPO_ATA_A_MAIOR"] == 1             # um grupo, contado UMA vez
    assert g["excesso"] == pytest.approx(50_000.0) and g["pago"] == pytest.approx(200_000.0)
    assert rs["GRUPO_ATA_A_MAIOR"] == 2                            # contratos na classe


def test_grupo_com_ob_so_em_outro_processo_e_indeterminado(tmp_path):
    res = _db(tmp_path, *_ata([100_000.0, 50_000.0], _obs([70_000.0], processo="SEI-999999/000001/2025")))
    assert res["DA"]["categoria"] == "GRUPO_ATA_INDETERMINADO"
    assert res["DA"]["motivo"] == "ob_do_credor_fora_do_processo" and res["DA"]["grupo_pago"] is None


def test_grupo_sem_ob_na_base_e_indeterminado_nunca_dentro(tmp_path):
    res = _db(tmp_path, *_ata([100_000.0, 50_000.0], []))
    assert res["DA"]["categoria"] == "GRUPO_ATA_INDETERMINADO" and res["DA"]["motivo"] == "credor_sem_ob_na_base"


def test_valor_repetido_que_decide_o_resultado_e_indeterminado(tmp_path):
    # 100k + 100k: pode ser o MESMO registro duas vezes; pago 150k só cabe se forem dois
    res = _db(tmp_path, *_ata([100_000.0, 100_000.0], _obs([150_000.0])))
    assert res["DA"]["categoria"] == "GRUPO_ATA_INDETERMINADO" and res["DA"]["motivo"] == "registro_repetido_no_grupo"


def test_valor_repetido_que_nao_decide_fica_dentro(tmp_path):
    res = _db(tmp_path, *_ata([100_000.0, 100_000.0], _obs([90_000.0])))
    assert res["DA"]["categoria"] == "GRUPO_ATA_DENTRO"


def test_ob_do_credor_em_outro_processo_da_mesma_ug_impede_afirmar_dentro(tmp_path):
    obs = _obs([100_000.0]) + [("2025OB09999", "10/09/2025", CRED, "SEI-999999/000001/2025", 80_000.0)]
    res = _db(tmp_path, *_ata([100_000.0, 50_000.0], obs))
    assert res["DA"]["categoria"] == "GRUPO_ATA_INDETERMINADO"
    assert res["DA"]["motivo"] == "dentro_com_ob_fora_do_processo"
    # controle: a OB alheia em OUTRA UG não pesa (a regra é a mesma do "a menor" individual)
    obs2 = _obs([100_000.0]) + [("2025OB09999", "10/09/2025", CRED, "SEI-999999/000001/2025", 80_000.0, "111111")]
    (tmp_path / "b").mkdir()
    res2 = _db(tmp_path / "b", *_ata([100_000.0, 50_000.0], obs2))
    assert res2["DA"]["categoria"] == "GRUPO_ATA_DENTRO"


def test_ob_anterior_ao_primeiro_desdobramento_nao_sustenta_a_maior(tmp_path):
    # OB do processo de origem antes do 1º desdobramento publicado = há desdobramento fora da base (TCE-RJ só 2023+)
    obs = _obs([100_000.0, 100_000.0]) + [("2025OB00777", "10/01/2025", CRED, "SEI-300001/000001/2025", 5_000.0)]
    res = _db(tmp_path, *_ata([100_000.0, 50_000.0], obs))
    assert res["DA"]["categoria"] == "GRUPO_ATA_INDETERMINADO"
    assert res["DA"]["motivo"] == "ob_anterior_ao_primeiro_desdobramento"


def test_pago_a_frente_dos_desdobramentos_publicados_nao_sustenta_a_maior(tmp_path):
    # Caso real (IVB, 14/11/2026): desdobramentos A, D, U publicados; OB de R$ 651 mil paga ANTES de existir o U —
    # paga um desdobramento que o TCE-RJ não publicou para este credor (B…T). Nada se afirma.
    contratos = [
        ("DA", "SEI-300001/000001/A/2025", BASE, "2025-03-01T00:00:00.000", 10_000.0, "AQUISIÇÃO.", CRED, "", ""),
        ("DU", "SEI-300001/000001/U/2025", BASE, "2025-09-01T00:00:00.000", 50_000.0, "AQUISIÇÃO.", CRED, "", "")]
    obs = [("2025OB00001", "10/04/2025", CRED, "SEI-300001/000001/2025", 10_000.0),
           ("2025OB00002", "10/05/2025", CRED, "SEI-300001/000001/2025", 40_000.0),     # antes do U: à frente
           ("2025OB00003", "10/10/2025", CRED, "SEI-300001/000001/2025", 30_000.0)]
    res = _db(tmp_path, contratos, obs)
    assert res["DA"]["categoria"] == "GRUPO_ATA_INDETERMINADO"
    assert res["DA"]["motivo"] == "pago_a_frente_dos_desdobramentos_publicados"
    # controle: mesmo total, mas pago depois de cada desdobramento existir → o excesso se sustenta
    obs2 = [("2025OB00001", "10/04/2025", CRED, "SEI-300001/000001/2025", 10_000.0),
            ("2025OB00002", "10/10/2025", CRED, "SEI-300001/000001/2025", 70_000.0)]
    (tmp_path / "b").mkdir()
    res2 = _db(tmp_path / "b", contratos, obs2)
    assert res2["DA"]["categoria"] == "GRUPO_ATA_A_MAIOR"


def test_ob_depois_do_fim_de_todos_os_desdobramentos_nao_sustenta_a_maior(tmp_path):
    obs = _obs([100_000.0, 50_000.0]) + [("2026OB00001", "10/08/2026", CRED, "SEI-300001/000001/2025", 50_000.0)]
    res = _db(tmp_path, *_ata([100_000.0, 50_000.0], obs))
    assert res["DA"]["categoria"] == "GRUPO_ATA_INDETERMINADO"
    assert res["DA"]["motivo"] == "ob_apos_fim_da_vigencia_registrada"


def test_registro_com_lista_de_desdobramentos_sozinho_forma_grupo(tmp_path):
    lista = "SEI-300001/000001/A/2025, SEI-300001/000001/B/2025"
    contratos = [("M", lista, BASE + BASE, "2025-03-01T00:00:00.000", 100_000.0, "AQUISIÇÃO DE GASES.", CRED,
                  "01/03/2025", "28/02/2026")]
    res = _db(tmp_path, contratos, _obs([60_000.0]))
    assert res["M"]["categoria"] == "GRUPO_ATA_DENTRO" and res["M"]["grupo_n"] == 1
    assert res["M"]["grupo_pago"] == pytest.approx(60_000.0)


def test_processos_de_origem_distintos_ficam_indeterminados_com_motivo(tmp_path):
    lista = "SEI-300001/000001/2025, SEI-300001/000002/2025"
    contratos = [("X", lista, "30000100000120253000010000022025", "2025-03-01T00:00:00.000", 100_000.0, "AQUISIÇÃO.",
                  CRED, "01/03/2025", "28/02/2026")]
    res = _db(tmp_path, contratos, _obs([60_000.0]))
    assert res["X"]["categoria"] == "GRUPO_ATA_INDETERMINADO" and res["X"]["motivo"] == "processos_de_origem_distintos"


def test_contrato_individual_e_lista_do_mesmo_processo_somam_uma_vez(tmp_path):
    contratos = [
        ("I", "SEI-300001/000001/2025", BASE, "2025-03-01T00:00:00.000", 100_000.0, "AQUISIÇÃO.", CRED, "01/03/2025",
         "28/02/2026"),
        ("M", "SEI-300001/000001/A/2025, SEI-300001/000001/B/2025", BASE + BASE, "2025-03-01T00:00:00.000", 40_000.0,
         "AQUISIÇÃO.", CRED, "01/03/2025", "28/02/2026")]
    res = _db(tmp_path, contratos, _obs([120_000.0]))
    assert res["I"]["categoria"] == res["M"]["categoria"] == "GRUPO_ATA_DENTRO"
    assert res["I"]["pago"] is None and res["I"]["grupo_regua"] == pytest.approx(140_000.0)


def test_contrato_unico_do_processo_segue_a_regua_individual(tmp_path):
    contratos = [("U", "SEI-300001/000001/2025", BASE, "2025-03-01T00:00:00.000", 100_000.0, "AQUISIÇÃO DE CADEIRAS",
                  CRED, "01/03/2025", "28/02/2026")]
    res = _db(tmp_path, contratos, _obs([150_000.0]))
    assert res["U"]["categoria"] == "A_MAIOR" and res["U"]["pago"] == pytest.approx(150_000.0)
    assert not res["U"].get("grupo_ata")


# ───────────────────────── consumo contínuo ─────────────────────────

@pytest.mark.parametrize("objeto,cnae,esperado", [
    ("PAGAMENTO DE JUROS E MULTAS.", "Distribuição de energia elétrica", "concessionaria"),
    ("ATENDER AS DEMANDAS DA FUNDAÇÃO", "Captação, tratamento e distribuição de água", "concessionaria"),
    ("CONTRATAÇÃO DE EMPRESA CONCESSIONÁRIA - ÁGUA/SANEAMENTO.", "3600601", "concessionaria"),
    ("DESPESAS DE JUROS", "Serviços de telefonia fixa comutada - STFC", "concessionaria"),
    ("SERVIÇO DE FORNECIMENTO DE ENERGIA NAS UNIDADES ESCOLARES.", None, "concessionaria"),
    ("PRESTAÇÃO DE SERVIÇOS PÚBLICOS DE ABASTECIMENTO DE ÁGUA E ESGOTAMENTO SANITÁRIO", None, "concessionaria"),
    ("COTAS DE CONDOMÍNIO, DO EXERCÍCIO DE 2025, DO 23º ANDAR", None, "cota_condominial"),
    ("DESTINA-SE A COBRIR DESPESAS", "Condomínios prediais", "cota_condominial"),
    ("DESTINA-SE A COBRIR DESPESAS", "8112500", "cota_condominial"),
    ("FORNECIMENTO DE ASSINATURA ANUAL, PARA ACESSO A PLATAFORMA DE PESQUISA", None, "assinatura"),
    ("ACESSO A PORTAL COMPRAS ELETRÔNICAS - ACESSO AO SERVIÇO DE PORTAL BANCO DE PREÇOS.", None, "assinatura"),
    # controles negativos
    ("AQUISIÇÃO DE ÁGUA MINERAL EM GARRAFÃO", None, None),
    ("AQUISIÇÃO DE APARELHOS TELEFÔNICOS", "Serviços de telefonia fixa comutada - STFC", None),
    ("INSTALAÇÃO DE SISTEMA DE ENERGIA SOLAR FOTOVOLTAICA", None, None),
    ("SERVIÇOS DE MANUTENÇÃO ELÉTRICA", "Instalação e manutenção elétrica", None),
    ("FABRICAÇÃO DE QUADROS", "Fabricação de equipamentos para distribuição e controle de energia elétrica", None),
    ("AQUISIÇÃO DE CERTIFICADO PARA ASSINATURA DIGITAL", None, None),
    ("PRAZO CONTADO A PARTIR DA ASSINATURA DO CONTRATO", None, None),
    ("AQUISIÇÃO DE VALE-TRANSPORTE EM CARTÃO MAGNÉTICO.", None, None),
    ("PROVEDOR DE ACESSO À INTERNET", "6190601", None),
    ("AQUISIÇÃO DE CADEIRAS", None, None), ("", None, None),
])
def test_classe_consumo(objeto, cnae, esperado):
    assert pc.classe_consumo(objeto, cnae) == esperado


def test_concessionaria_acima_do_valor_vai_a_consumo_continuo_com_soma_propria(tmp_path):
    luz = "55555555000155"
    contratos = [
        ("L", "SEI-300001/000009/2025", "3000010000092025", "2025-03-01T00:00:00.000", 3_000.0,
         "PAGAMENTO DE JUROS E MULTAS.", luz, "01/03/2025", "28/02/2026"),
        ("U", "SEI-300001/000001/2025", BASE, "2025-03-01T00:00:00.000", 100_000.0, "AQUISIÇÃO DE CADEIRAS", CRED,
         "01/03/2025", "28/02/2026")]
    obs = _obs([150_000.0]) + [("2025OB08888", "10/05/2025", luz, "SEI-300001/000009/2025", 69_000.0)]
    res = _db(tmp_path, contratos, obs, empresas=[(luz, "Distribuição de energia elétrica")])
    l = res["L"]
    assert l["categoria"] == "CONSUMO_CONTINUO" and l["subtipo"] == "concessionaria"
    assert l["diferenca"] == pytest.approx(66_000.0) and l["pago"] == pytest.approx(69_000.0)
    assert "estimativa" in l["ressalvas"]
    rs = pc.resumo(list(res.values()))[pc.ESTADO]
    assert rs["A_MAIOR"] == 1 and rs["excesso_a_maior"] == pytest.approx(50_000.0)   # só as cadeiras
    assert rs["CONSUMO_CONTINUO"] == 1 and rs["consumo_continuo"] == pytest.approx(66_000.0)


def test_concessionaria_conforme_nao_muda_de_classe(tmp_path):
    luz = "55555555000155"
    contratos = [("L", "SEI-300001/000009/2025", "3000010000092025", "2025-03-01T00:00:00.000", 100_000.0,
                  "AQUISIÇÃO DE CADEIRAS", luz, "01/03/2025", "28/02/2026")]
    obs = [("2025OB08888", "10/05/2025", luz, "SEI-300001/000009/2025", 100_000.0)]
    res = _db(tmp_path, contratos, obs, empresas=[(luz, "Distribuição de energia elétrica")])
    assert res["L"]["categoria"] == "CONFORME"


def test_prefeitura_consumo_continuo_pelo_objeto():
    row = ("1", "55555555000155", "LIGHT", "ORG", "UG", "FORNECIMENTO DE ENERGIA ELÉTRICA", "Ativo", "01/01/2025",
           "31/12/2025", "P", 10_000.0, 50_000.0, "2026-11-01", "01/01/2025", 2025, 50_000.0)
    r = pc._avaliar_um_pcrj(row)
    assert r["categoria"] == "CONSUMO_CONTINUO" and r["subtipo"] == "concessionaria"


# ───────────────────────── rotina (payload do painel) ─────────────────────────

def test_rotina_separa_consumo_e_grupos_da_manchete(tmp_path):
    luz = "55555555000155"
    contratos = _ata([100_000.0, 50_000.0], [])[0] + [
        ("L", "SEI-300001/000009/2025", "3000010000092025", "2025-03-01T00:00:00.000", 3_000.0, "JUROS.", luz,
         "01/03/2025", "28/02/2026")]
    obs = _obs([100_000.0, 100_000.0]) + [("2025OB08888", "10/05/2025", luz, "SEI-300001/000009/2025", 69_000.0)]
    res = _db(tmp_path, contratos, obs, empresas=[(luz, "Distribuição de energia elétrica")])
    e = rot.resumir(list(res.values()))["esferas"][pc.ESTADO]
    assert e["placar"]["A_MAIOR"] == 0 and e["a_maior"] == [] and e["excesso_a_maior"] == 0
    cc = e["consumo_continuo"]
    assert cc["n"] == 1 and cc["excesso"] == pytest.approx(66_000.0) and len(cc["itens"]) == 1
    assert cc["criterio"] and cc["itens"][0]["subtipo"] == "concessionaria"
    g = e["grupos_ata"]
    assert g["n_grupos"] == 1 and g["placar_grupos"]["GRUPO_ATA_A_MAIOR"] == 1
    assert g["excesso_a_maior"] == pytest.approx(50_000.0) and g["criterio"]
    assert len(g["a_maior"]) == 1 and g["a_maior"][0]["grupo_n"] == 2
    assert g["a_maior"][0]["grupo_diferenca"] == pytest.approx(50_000.0)
