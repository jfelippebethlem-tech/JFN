# -*- coding: utf-8 -*-
"""aditivos_estouro (cruzamentos_intel) — pct sobre o ACRÉSCIMO REAL (contrato_aditivo qualif='1') quando
existe; sem ele, vg−vi (inclui reajuste) vira indício NÃO confirmado (acrescimo_confirmado=False), rebaixado
na ordenação — nunca removido (honestidade)."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.cruzamentos_intel import aditivos_estouro


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE pcrj_contratos (
        numero_controle_pncp TEXT, fornecedor_nome TEXT, fornecedor_documento TEXT, orgao_nome TEXT,
        unidade TEXT, objeto TEXT, valor_inicial REAL, valor_global REAL, num_aditivos INTEGER,
        vigencia_fim TEXT);
    CREATE TABLE contrato_aditivo (
        numero_controle_pncp TEXT, qualif_acrescimo TEXT, valor_acrescido REAL, objeto TEXT);
    """)
    ins = ("INSERT INTO pcrj_contratos VALUES (?,?,?,?,?,?,?,?,?,?)")
    con.executemany(ins, [
        # K1: vg−vi=+40% MAS acréscimo real (qualif='1') = 10% → reajuste explica; NÃO é achado
        ("K1", "ALFA", "11111111000111", "SMS", "SMS", "serviço de limpeza", 100000.0, 140000.0, 1, "2025-12-31"),
        # K2: acréscimo real = 30% → estouro CONFIRMADO
        ("K2", "BETA", "22222222000122", "SMS", "SMS", "serviço de manutenção", 100000.0, 140000.0, 1, "2025-12-31"),
        # K3: sem contrato_aditivo → vg−vi=+50% vira indício NÃO confirmado (rebaixado, não removido)
        ("K3", "GAMA", "33333333000133", "SME", "SME", "fornecimento de merenda", 100000.0, 150000.0, 1, "2025-12-31"),
        # K4: acréscimo real de EXATAMENTE 25% — o art. 125 permite acréscimo ATÉ 25%; no teto é
        # LÍCITO. Medido no acervo em 2026-08-10: quatro dos sete estouros com acréscimo granular
        # confirmado estavam em 25,000000% e eram acusação de ilegalidade onde não havia.
        ("K4", "DELTA", "44444444000144", "MPRJ", "MPRJ", "mudanças e transportes", 100000.0, 125000.0, 1, "2025-12-31"),
    ])
    # O discriminador é o OBJETO, não o `qualif_acrescimo`. A versão anterior deste fixture
    # usava `qualif='2'` para dizer "isto é reajuste" — convenção que não existe na base real,
    # onde o campo vem '1' para quase tudo (medido em `contratos/thoughts`, caso AVANTY). Note
    # que os dois termos do K1 trazem qualif='1', como no PNCP de verdade: se o filtro fosse o
    # qualificador, o reajuste de R$ 30 mil entraria no teto do art. 125.
    con.executemany("INSERT INTO contrato_aditivo VALUES (?,?,?,?)", [
        ("K1", "1", 10000.0, "acréscimo quantitativo de itens"),
        ("K1", "1", 30000.0, "reajuste contratual pelo IPCA"),
        ("K2", "1", 30000.0, "acréscimo de quantitativo do contrato"),
        ("K4", "1", 25000.0, "acréscimo de quantitativo do contrato"),
    ])
    con.commit()
    con.close()
    return p


def test_pct_sobre_acrescimo_real_exclui_reajuste(db):
    d = aditivos_estouro(db_path=db)
    assert d["ok"]
    contratos = {a["contrato"] for a in d["achados"]}
    assert "K1" not in contratos  # acréscimo real 10% < 25% — o +40% era reajuste
    k2 = next(a for a in d["achados"] if a["contrato"] == "K2")
    assert k2["pct"] == pytest.approx(30.0)
    assert k2["acrescimo_confirmado"] is True
    assert k2["estoura_teto"] is True


def test_sem_acrescimo_real_marca_nao_confirmado_e_rebaixa(db):
    d = aditivos_estouro(db_path=db)
    k3 = next(a for a in d["achados"] if a["contrato"] == "K3")
    assert k3["acrescimo_confirmado"] is False
    assert k3["pct"] == pytest.approx(50.0)  # vg−vi, sem confirmação granular
    # ordenação: K2 (confirmado, 30%) vem ANTES de K3 (não confirmado, 50%)
    ordem = [a["contrato"] for a in d["achados"]]
    assert ordem.index("K2") < ordem.index("K3")


def test_no_teto_exato_NAO_e_estouro(db):
    """Art. 125: os acréscimos são admitidos ATÉ 25%. Exatamente no teto o contrato está DENTRO
    da lei — `pct >= teto` acusava ilegalidade onde não havia."""
    d = aditivos_estouro(db_path=db)
    k4 = [a for a in d["achados"] if a["contrato"] == "K4"]
    assert not k4 or k4[0]["estoura_teto"] is False, (
        "acréscimo de exatamente 25% é lícito — não pode ser marcado como estouro do art. 125")


def test_um_centavo_acima_do_teto_sai_PENDENTE_nao_some(db):
    """O corte tem de continuar cortando — a correção não pode virar falso NEGATIVO silencioso.
    Desde 2026-11-19 (régua única `avaliar_contrato`), um centavo acima do teto pelo inicial CRU
    não é afirmado como estouro: o art. 125 mede sobre o inicial ATUALIZADO, e um excesso de até
    10% do teto cabe na correção monetária (caso VR Benefícios, 26,4% × 25% declarado). Ele fica
    na lista como PENDENTE, com o motivo — nunca desaparece."""
    import sqlite3 as _sq
    con = _sq.connect(db)
    con.execute("INSERT INTO pcrj_contratos VALUES "
                "('K5','EPSILON','55555555000155','MPRJ','MPRJ','serviço',100000.0,125001.0,1,'2025-12-31')")
    con.execute("INSERT INTO contrato_aditivo VALUES ('K5','1',25001.0,'acréscimo de quantitativo')")
    con.commit(); con.close()
    d = aditivos_estouro(db_path=db)
    k5 = next(a for a in d["achados"] if a["contrato"] == "K5")
    assert k5["estoura_teto"] is False
    assert k5["estado"] == "PENDENTE"
    assert "excesso_cabe_na_atualizacao_do_valor_inicial" in k5["motivos"]


def test_declara_que_a_base_e_o_inicial_CRU(db):
    """O art. 125 mede sobre o "valor inicial ATUALIZADO"; esta varredura roda sobre todo o PNCP,
    onde não há índice. Sem declarar a base, um percentual rente ao teto acusa ilegalidade que pode
    não existir — foi o que quase aconteceu com o VR Benefícios (nosso 26,4% × "25%" declarado no
    próprio termo, sobre base atualizada)."""
    a = aditivos_estouro(db_path=db)["achados"][0]
    assert "atualizado" in a["base_do_percentual"]
    assert "valor_inicial" in a["base_do_percentual"]


def test_k2_acima_da_folga_continua_VERIFICADO(db):
    """Controle positivo: 30% (acima de 25% + a folga de atualização) segue afirmado."""
    k2 = next(a for a in aditivos_estouro(db_path=db)["achados"] if a["contrato"] == "K2")
    assert k2["estado"] == "VERIFICADO" and k2["tipo"] == "estouro"


def test_termos_lidos_sem_acrescimo_nao_viram_estouro_pelo_global(db):
    """Falso positivo medido em 2026-11-19 (167 de 169 "estouros" do Estado): o termo foi lido, é
    PRORROGAÇÃO, e o global cresceu 100% — o intel caía no `vg − vi` e acusava estouro."""
    import sqlite3 as _sq
    con = _sq.connect(db)
    con.execute("INSERT INTO pcrj_contratos VALUES "
                "('K6','ZETA','66666666000166','SEEDUC','SEEDUC','serviço contínuo',100000.0,200000.0,1,'2026-12-31')")
    con.execute("INSERT INTO contrato_aditivo VALUES ('K6','0',100000.0,"
                "'Prorrogação do prazo de vigência por mais 12 meses')")
    con.commit(); con.close()
    assert "K6" not in {a["contrato"] for a in aditivos_estouro(db_path=db)["achados"]}


def test_universo_e_o_da_esfera_nao_a_tabela(db):
    d = aditivos_estouro(db_path=db)
    assert d["contratos_analisados"] == 4
