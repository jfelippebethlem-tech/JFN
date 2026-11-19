# -*- coding: utf-8 -*-
"""D11 (aditivo acima do art. 125) — régua única `limites_aditivo.avaliar_contrato` e o detector
da Prefeitura que a usa. Os negativos são os TRÊS "confirmados" que o D11 publicava em
2026-11-19, com o texto verbatim do termo no PNCP; nenhum deles era estouro afirmável."""
from __future__ import annotations

import pytest

from compliance_agent.limites_aditivo import avaliar_contrato

ACR = "Alteração quantitativa para acréscimo do objeto do contrato"


def _t(objeto, valor, seq=1, **kw):
    return {"objeto": objeto, "valor_acrescido": valor, "sequencial_termo": seq, **kw}


# ───────────── controles positivos ─────────────

def test_acrescimo_quantitativo_acima_do_teto_e_VERIFICADO():
    av = avaliar_contrato(100_000, [_t(ACR, 40_000)], "serviço de limpeza")
    assert av["estado"] == "VERIFICADO" and av["pct"] == pytest.approx(0.40)
    assert av["termos"][0]["conta_no_teto"] is True


def test_acrescimos_em_serie_somam_no_teto():
    """Falso negativo clássico: cada termo dentro do teto, a soma fora."""
    av = avaliar_contrato(100_000, [_t(ACR, 15_000, 1), _t(ACR, 15_000, 2)], "serviço")
    assert av["estado"] == "VERIFICADO" and av["pct"] == pytest.approx(0.30)


def test_supressao_nao_compensa_acrescimo():
    """Art. 125: acréscimos e supressões computam-se separadamente."""
    av = avaliar_contrato(100_000, [_t(ACR, 40_000, 1),
                                    _t("Supressão de quantitativo do contrato", -20_000, 2)],
                          "serviço")
    assert av["estado"] == "VERIFICADO" and av["pct"] == pytest.approx(0.40)
    assert av["pct_supressao"] == pytest.approx(0.20)


# ───────────── controles negativos ─────────────

def test_teto_exato_e_licito():
    assert avaliar_contrato(100_000, [_t(ACR, 25_000)], "serviço")["estado"] == "DENTRO_DO_LIMITE"


def test_reforma_tem_teto_de_50():
    av = avaliar_contrato(100_000, [_t(ACR, 40_000)], "Reforma de edifício da sede")
    assert av["teto"] == pytest.approx(0.50) and av["estado"] == "DENTRO_DO_LIMITE"


@pytest.mark.parametrize("objeto", [
    "Prorrogação do prazo de vigência do Contrato por mais 12 meses",
    "Reajuste contratual pelo IPCA",
    "Repactuação dos valores em razão da convenção coletiva",
    "a revisão, a contar de 01/06/2025, dos valores vigentes do benefício",
])
def test_prazo_e_recomposicao_nao_contam(objeto):
    av = avaliar_contrato(100_000, [_t(objeto, 90_000)], "serviço", valor_global=190_000)
    assert av["estado"] == "DENTRO_DO_LIMITE"


def test_sem_termo_global_maior_e_PENDENTE_nunca_VERIFICADO():
    """25 dos 28 achados do D11 eram isto: empenho anual estimado, contrato plurianual."""
    av = avaliar_contrato(260.0 * 10, None, "jardinagem", valor_global=28_500.0,
                          termos_coletados=False)
    assert av["estado"] == "PENDENTE" and av["motivos"] == ["termos_nao_coletados"]
    av2 = avaliar_contrato(10_000, [], "x", valor_global=50_000, termos_coletados=True)
    assert av2["estado"] == "PENDENTE"
    assert av2["motivos"] == ["global_cresceu_sem_termo_publicado"]


def test_valor_inicial_lixo_e_INDISPONIVEL():
    """R$ 23,00 → R$ 748.800,00 (FAETEC): denominador ruim fabrica 3.255.552%."""
    assert avaliar_contrato(23.0, [_t(ACR, 748_777)], "x")["estado"] == "INDISPONIVEL"


def test_caso_DPE_termo_de_outro_contrato():
    """31443526000170-2-000006/2024: contrato de decoração floral de R$ 35.140,00; o termo
    publicado sob ele é de PASSAGENS AÉREAS, +R$ 133.650,00 com global R$ 668.250,00 — 25% de
    R$ 534.600,00, base que não é a deste contrato. Antes: 380,3% 'confirmado', alerta ALTA."""
    termo = _t("Alteração quantitativa para acréscimo do objeto do contrato nº 04/2024, relativo à "
               "prestação de serviços de fornecimento de passagens aéreas", 133_650.0,
               valor_global=668_250.0, fundamento_legal="art. 125, da Lei nº 14.133/2021")
    av = avaliar_contrato(35_140.0, [termo], "SERVIÇOS DE DECORAÇÃO FLORAL PARA EVENTOS")
    assert av["estado"] == "PENDENTE"
    assert "base_do_termo_incompativel_com_o_contrato" in av["motivos"]


def test_caso_TCE_termo_declara_25_por_cento():
    """30051023000196-2-000027/2025: o termo diz 'o que equivale a 25% (vinte e cinco por cento)
    do valor inicial atualizado'; o PNCP dá inicial de R$ 779.106,60 e acréscimo de R$ 973.883,25
    (125%). A base publicada é que está errada — o termo se declara no teto."""
    termo = _t("Acréscimo quantitativo consistente em aumento dos quantitativos dos serviços de "
               "gerenciamento do abastecimento e fornecimento de combustíveis (gasolina, etanol, "
               "diesel S10), o que equivale a 25% (vinte e cinco por cento) do valor inicial "
               "atualizado, ", 973_883.25, valor_global=0.0)
    av = avaliar_contrato(779_106.60, [termo], "gerenciamento do abastecimento de combustíveis")
    assert av["estado"] == "PENDENTE"
    assert "percentual_declarado_no_termo_dentro_do_teto" in av["motivos"]


def test_caso_VR_rente_ao_teto_pela_base_nao_atualizada():
    """42498600000171-2-000489/2024: 'o acréscimo de 25 % ao Contrato nº 02/2024', +R$ 20.000,00
    sobre inicial cru de R$ 75.840,00 = 26,4%."""
    termo = _t("Constitui objeto do presente Termo Aditivo o acréscimo de 25 % ao Contrato nº 02/2024",
               20_000.0, fundamento_legal='art. 124, inciso I, alínea "b" da Lei Federal nº 14.133/2021')
    av = avaliar_contrato(75_840.0, [termo], "benefício refeição/alimentação")
    assert av["estado"] == "PENDENTE"
    assert "excesso_cabe_na_atualizacao_do_valor_inicial" in av["motivos"]


def test_termo_misto_que_pode_estourar_nao_e_dentro_do_limite():
    av = avaliar_contrato(100_000, [_t(ACR, 10_000, 1),
                                    _t("reequilíbrio e acréscimo de quantitativos", 30_000, 2)],
                          "serviço")
    assert av["estado"] == "PENDENTE"
    assert av["motivos"] == ["natureza_indeterminada_pode_estourar"]


# ───────────── o detector da Prefeitura ─────────────

@pytest.fixture
def con(tmp_path):
    from compliance_agent.emendas import db as edb
    from compliance_agent.pcrj import gastos_db
    c = edb.conectar(tmp_path / "t.db")
    edb.init_schema(c)
    gastos_db.init_schema(c)
    c.execute("""CREATE TABLE IF NOT EXISTS contrato_aditivo (
        id INTEGER PRIMARY KEY AUTOINCREMENT, numero_controle_pncp TEXT NOT NULL,
        sequencial_termo INTEGER, numero_termo TEXT, objeto TEXT, valor_acrescido REAL,
        valor_global REAL, prazo_aditado_dias INTEGER, vigencia_fim TEXT, qualif_acrescimo TEXT,
        qualif_vigencia TEXT, qualif_reajuste TEXT, fundamento_legal TEXT, data_assinatura TEXT,
        tipo_termo TEXT, processo TEXT)""")
    ins = ("INSERT INTO pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj, orgao_nome, "
           "fornecedor_documento, fornecedor_nome, tipo, objeto, valor_inicial, valor_global, "
           "data_assinatura) VALUES (?,?,?,?,?,?,?,?,?,?,?)")
    c.executemany(ins, [
        # Prefeitura, acréscimo de 40% provado no termo → alerta
        ("42498733000148-2-000001/2025", 2025, "42498733000148", "MUNICIPIO DE RIO DE JANEIRO",
         "11222333000181", "ACME", "Contrato", "manutenção predial", 100_000, 100_000, "2025-01-10"),
        # Prefeitura, global 3× sem termo → PENDENTE, sem alerta
        ("42498733000148-2-000002/2025", 2025, "42498733000148", "MUNICIPIO DE RIO DE JANEIRO",
         "44555666000199", "BETA", "Empenho", "material", 10_000, 30_000, "2025-01-10"),
        # federal (Fiocruz) com estouro provado → fora do D11 da Prefeitura
        ("33781055000135-2-000003/2025", 2025, "33781055000135", "FUNDACAO OSWALDO CRUZ",
         "77888999000155", "GAMA", "Contrato", "serviço", 100_000, 160_000, "2025-01-10"),
    ])
    c.executemany("INSERT INTO contrato_aditivo (numero_controle_pncp, sequencial_termo, objeto, "
                  "valor_acrescido, data_assinatura) VALUES (?,?,?,?,?)", [
        ("42498733000148-2-000001/2025", 1, ACR, 40_000, "2025-06-01"),
        ("33781055000135-2-000003/2025", 1, ACR, 60_000, "2025-06-01"),
    ])
    c.commit()
    return c


def test_d11_so_prefeitura_e_so_verificado(con):
    from compliance_agent.pcrj import pericia_gastos
    achados = pericia_gastos.d11_aditivo_estourado(con)
    assert [a["evidencias"]["controle"] for a in achados] == ["42498733000148-2-000001/2025"]
    ev = achados[0]["evidencias"]
    assert ev["estado"] == "VERIFICADO" and ev["pct_acrescimo"] == pytest.approx(40.0)
    assert "termo 1" in achados[0]["descricao"] and "40,0%" in achados[0]["descricao"]


def test_d11_avaliacao_mostra_pendente_e_cobertura(con):
    from compliance_agent.pcrj import pericia_gastos
    av = pericia_gastos.d11_avaliacao(con)
    estados = {x["controle"]: x["estado"] for x in av["itens"]}
    assert estados == {"42498733000148-2-000001/2025": "VERIFICADO",
                       "42498733000148-2-000002/2025": "PENDENTE"}
    assert av["cobertura"]["contratos"] == 2           # o federal não entra no universo
    assert all(x["pago_estado"] == "INDISPONIVEL" and x["pago"] is None for x in av["itens"])


def test_coleta_de_termos_nao_marca_checado_em_falha(con, monkeypatch):
    """`termos_contrato` devolve [] tanto para "sem termos" quanto para erro de rede; marcar como
    consultado numa falha gravaria "não tem aditivo" sem ter lido. A coleta municipal distingue."""
    import asyncio

    from compliance_agent.collectors import pncp

    respostas = {"000001": (True, []), "000002": (False, [])}

    async def fake(cnpj, ano, seq):
        return respostas[str(seq).zfill(6)]
    monkeypatch.setattr(pncp, "_termos_medidos", fake)
    monkeypatch.setattr(pncp, "_parse_id_pncp",
                        lambda n: (n[:14], n.split("/")[1], n.split("-")[2].split("/")[0]))
    r = asyncio.run(pncp.coletar_termos_municipio(con, limite=10, pausa=0))
    chk = dict(con.execute("SELECT numero_controle_pncp, aditivos_checados FROM pcrj_contratos "
                           "WHERE orgao_cnpj='42498733000148'").fetchall())
    assert chk == {"42498733000148-2-000001/2025": 1, "42498733000148-2-000002/2025": 0}
    assert r["falhas"] == 1 and r["consultados"] == 1
