# -*- coding: utf-8 -*-
"""empresa_fenix — empresa BAIXADA/INAPTA que recebeu (valor de favorecido_resumo, situação case-insens.)."""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.cruzamentos_intel import empresa_fenix


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "t.db")
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE empresas (cnpj TEXT, razao_social TEXT, data_abertura TEXT, situacao TEXT);
    CREATE TABLE favorecido_resumo (favorecido_cpf TEXT, favorecido_nome TEXT, total_pago REAL, n_obs INTEGER);
    CREATE TABLE ob_orcamentaria_siafe (credor TEXT, valor REAL, data_emissao TEXT, status TEXT);
    """)
    con.executemany("INSERT INTO empresas VALUES (?,?,?,?)", [
        ("11111111000111", "MORTA LTDA", "2005-01-01", "BAIXADA"),
        ("22222222000122", "MINUSCULA LTDA", "2005-01-01", "Inapta"),   # case minúsculo
        ("33333333000133", "VIVA LTDA", "2005-01-01", "ATIVA"),          # ativa, não recém → não entra
        ("44444444000144", "CONSORCIO ABC SPE", "2024-06-01", "ATIVA"),  # SPE recém → excluída
        ("55555555000155", "RECEM LTDA", "2025-06-01", "ATIVA"),         # aberta ≤12m antes da 1ª OB
    ])
    con.executemany("INSERT INTO favorecido_resumo (favorecido_cpf,total_pago,n_obs) VALUES (?,?,?)", [
        ("11111111000111", 500000.0, 10), ("22222222000122", 90000.0, 3),
        ("33333333000133", 9_000_000.0, 50), ("44444444000144", 8_000_000.0, 5),
        ("55555555000155", 1_000_000.0, 4)])
    # 1ª OB de RECEM em 2025-08 (aberta 2025-06 → 2 meses) → recém_aberta
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('55555555000155', 100000, '10/08/2025', 'Contabilizado')")
    con.commit()
    con.close()
    return p


def test_defunta_baixada_e_inapta_case_insensitive(db):
    d = empresa_fenix(db_path=db)
    assert d["ok"] is True
    tipos = {a["cnpj"]: a["tipo"] for a in d["achados"]}
    assert tipos.get("11111111000111") == "defunta"       # BAIXADA
    assert tipos.get("22222222000122") == "defunta"       # 'Inapta' (minúsculo) reconhecido
    assert d["n_defunta"] == 2
    # valor vem de favorecido_resumo (TFE incluso), não só OB SIAFE
    morta = next(a for a in d["achados"] if a["cnpj"] == "11111111000111")
    assert morta["total_recebido"] == 500000.0 and morta["n_obs"] == 10


def test_ativa_regular_nao_entra_e_spe_excluida(db):
    d = empresa_fenix(db_path=db)
    cnpjs = {a["cnpj"] for a in d["achados"]}
    assert "33333333000133" not in cnpjs                  # ATIVA regular
    assert "44444444000144" not in cnpjs                  # SPE (excluída mesmo recém)


def test_recem_aberta_dispara(db):
    d = empresa_fenix(db_path=db)
    recem = [a for a in d["achados"] if a["tipo"] == "recem_aberta"]
    assert any(a["cnpj"] == "55555555000155" for a in recem)


def test_total_defunta_e_ressalva_temporal(db):
    d = empresa_fenix(db_path=db)
    assert d["total_defunta"] == pytest.approx(590000.0)  # 500k + 90k
    assert "APÓS o pagamento" in d["ressalva"] and "Indício" in d["ressalva"]


# ── pago DEPOIS da baixa: só OB CONTABILIZADA é pagamento (24/09/2026) ──────────────────────────────
# A manchete "pago a empresa morta" somava OB anulada/excluída: R$ 586.272.022,50 → R$ 579.308.009,79.
from compliance_agent.cruzamentos_intel import _pagou_apos_baixa  # noqa: E402

_ISO = "substr(data_emissao,7,4)||'-'||substr(data_emissao,4,2)||'-'||substr(data_emissao,1,2)"


@pytest.fixture()
def con_baixa(tmp_path):
    estab = str(tmp_path / "estab.db")
    e = sqlite3.connect(estab)
    e.execute("CREATE TABLE estabelecimentos (cnpj TEXT, cnpj_basico TEXT, matriz_filial TEXT, "
              "situacao_cadastral TEXT, data_situacao TEXT, motivo_situacao TEXT)")
    e.execute("CREATE TABLE empresas (cnpj_basico TEXT, razao_social TEXT, natureza_cod TEXT)")
    e.executemany("INSERT INTO estabelecimentos VALUES (?, substr(?, 1, 8), ?, ?, ?, ?)", [
        (c, c, mf, sit, d, mot) for c, mf, sit, d, mot in [
            ('11111111000111', '1', 'BAIXADA', '20240101', '01'),
            ('22222222000122', '1', 'ATIVA', '20240101', '00'),     # data = quando FICOU ativa, não baixa
            ('33333333000133', '1', 'BAIXADA', '20240101', '02'),   # incorporada: a sucessora recebe
            ('44444444000144', '1', 'BAIXADA', '20240101', '01'),   # órgão público federal extinto
            ('55555555000155', '1', 'BAIXADA', '20240101', '01'),   # cartório extinto na reorganização
            ('66666666000166', '1', 'ATIVA', '20050101', '00'),     # matriz ATIVA ...
            ('66666666000247', '2', 'BAIXADA', '20240101', '01'),   # ... da filial baixada
            ('77777777000177', '1', 'INAPTA', '20240101', '63'),   # inapta que só recebeu por decisão judicial
            ('88888888000188', '1', 'INAPTA', '20240101', '15'),   # inapta (inexistência de fato) — sustenta
        ]])
    e.executemany("INSERT INTO empresas VALUES (?, ?, ?)", [
        ('11111111', 'MORTA LTDA', '2062'), ('44444444', 'MINISTERIO X', '1015'),
        ('55555555', 'CARTORIO DO 9 OFICIO', '3034'), ('66666666', 'GRANDE SA', '2046'),
        ('77777777', 'CREDORA JUDICIAL LTDA', '2062'), ('88888888', 'INSTITUTO Y', '3999')])
    e.commit(); e.close()
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(f"ATTACH DATABASE '{estab}' AS estab")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (credor TEXT, valor REAL, data_emissao TEXT, status TEXT, "
                "ug_emitente TEXT DEFAULT '100100', processo TEXT DEFAULT 'SEI-100001/000001/2024')")
    con.executemany("INSERT INTO ob_orcamentaria_siafe (credor, valor, data_emissao, status) "
                    "VALUES ('11111111000111', ?, ?, ?)", [
        (1000.0, "10/06/2023", "Contabilizado"),   # antes da baixa — não conta
        (2000.0, "10/03/2024", "Contabilizado"),   # depois — conta
        (5000.0, "11/03/2024", "Anulado"),         # depois, mas ANULADA — não é pagamento
        (7000.0, "12/03/2024", "Excluído"),        # idem
    ])
    yield con
    con.close()


def test_pago_apos_baixa_soma_so_ob_contabilizada(con_baixa):
    r = _pagou_apos_baixa(con_baixa, "11111111000111", "2024-03-12", _ISO)
    assert r["data_baixa"] == "2024-01-01"
    assert r["pagou_apos_baixa"] is True
    assert r["valor_apos_baixa"] == 2000.0 and r["n_ob_apos_baixa"] == 1


def test_sem_data_de_baixa_e_indisponivel_nao_regular(con_baixa):
    r = _pagou_apos_baixa(con_baixa, "99999999000199", "2024-03-12", _ISO)
    assert r["pagou_apos_baixa"] is None and r["data_baixa"] is None


# Revisão cética de 13/11/2026: 91 de 146 "mortas" estavam ATIVAS no dump (data_situacao = data em que
# ficaram ativas) e boa parte do resto era sucessão. Nenhuma das duas é "pago a empresa morta".
@pytest.mark.parametrize("cnpj", ["22222222000122", "33333333000133"])
def test_ativa_ou_sucessao_nao_e_empresa_morta(con_baixa, cnpj):
    con_baixa.execute("INSERT INTO ob_orcamentaria_siafe (credor, valor, data_emissao, status) "
                      "VALUES (?, 3000.0, '10/03/2024', 'Contabilizado')", (cnpj,))
    r = _pagou_apos_baixa(con_baixa, cnpj, "2024-03-12", _ISO)
    assert r["pagou_apos_baixa"] is None and r["data_baixa"] is None


# Verificação de 13/11/2026 (ficha D1 da revisão cética): depois de tirar ATIVA e sucessão, a manchete ainda
# trazia órgão público extinto, cartório extinto na reorganização das serventias, filial baixada de matriz ATIVA
# e pagamento por decisão judicial (Encargos Gerais com processo da PGE). Nenhum é "pago a empresa morta": saem
# da soma, contados à parte com o motivo — nunca somem calados.
def _pago_depois(con, cnpj, ug="100100", processo="SEI-100001/000001/2024", valor=3000.0):
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?, ?, '10/03/2024', 'Contabilizado', ?, ?)",
                (cnpj, valor, ug, processo))


@pytest.mark.parametrize("cnpj,motivo", [
    ("44444444000144", "natureza_publica"),
    ("55555555000155", "cartorio"),
    ("66666666000247", "filial_de_matriz_ativa"),
])
def test_ente_publico_cartorio_e_filial_de_matriz_ativa_saem_da_manchete(con_baixa, cnpj, motivo):
    _pago_depois(con_baixa, cnpj)
    r = _pagou_apos_baixa(con_baixa, cnpj, "2024-03-12", _ISO)
    assert r["pagou_apos_baixa"] is False and r["valor_apos_baixa"] == 0.0
    assert r["fora_da_manchete"] == motivo and r["valor_fora_da_manchete"] == 3000.0


def test_pagamento_judicial_sai_da_soma(con_baixa):
    _pago_depois(con_baixa, "77777777000177", ug="370200", processo="SEI-140001/033119/2024")
    r = _pagou_apos_baixa(con_baixa, "77777777000177", "2024-03-12", _ISO)
    assert r["pagou_apos_baixa"] is False and r["valor_apos_baixa"] == 0.0
    assert r["fora_da_manchete"] == "pagamento_judicial" and r["valor_fora_da_manchete"] == 3000.0


def test_inapta_por_inexistencia_paga_depois_sustenta_e_judicial_parcial_e_descontado(con_baixa):
    _pago_depois(con_baixa, "88888888000188", valor=10000.0)
    _pago_depois(con_baixa, "88888888000188", ug="370200", processo="SEI-140017/000001/2021", valor=500.0)
    r = _pagou_apos_baixa(con_baixa, "88888888000188", "2024-03-12", _ISO)
    assert r["pagou_apos_baixa"] is True and r["fora_da_manchete"] is None
    assert r["valor_apos_baixa"] == 10000.0 and r["n_ob_apos_baixa"] == 1
    assert r["valor_fora_da_manchete"] == 500.0


def test_manchete_soma_so_o_sustentado_e_conta_o_resto_por_motivo(tmp_path, monkeypatch):
    import compliance_agent.cruzamentos_intel as C
    raiz = tmp_path / "raiz"
    (raiz / "data").mkdir(parents=True)
    e = sqlite3.connect(str(raiz / "data" / "receita_estab.db"))
    e.executescript("""CREATE TABLE estabelecimentos (cnpj TEXT, cnpj_basico TEXT, matriz_filial TEXT,
        situacao_cadastral TEXT, data_situacao TEXT, motivo_situacao TEXT);
        CREATE TABLE empresas (cnpj_basico TEXT, razao_social TEXT, natureza_cod TEXT);""")
    e.executemany("INSERT INTO estabelecimentos VALUES (?, substr(?, 1, 8), '1', ?, '20240101', ?)", [
        ("88888888000188", "88888888000188", "INAPTA", "15"),
        ("44444444000144", "44444444000144", "BAIXADA", "01")])
    e.executemany("INSERT INTO empresas VALUES (?, ?, ?)", [("88888888", "INSTITUTO Y", "3999"),
                                                           ("44444444", "MINISTERIO X", "1015")])
    e.commit(); e.close()
    p = str(tmp_path / "c.db")
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE empresas (cnpj TEXT, razao_social TEXT, data_abertura TEXT, situacao TEXT);
    CREATE TABLE favorecido_resumo (favorecido_cpf TEXT, favorecido_nome TEXT, total_pago REAL, n_obs INTEGER);
    CREATE TABLE ob_orcamentaria_siafe (credor TEXT, valor REAL, data_emissao TEXT, status TEXT,
        ug_emitente TEXT, processo TEXT);""")
    con.executemany("INSERT INTO empresas VALUES (?, ?, '2000-01-01', ?)", [
        ("88888888000188", "INSTITUTO Y", "INAPTA"), ("44444444000144", "MINISTERIO X", "BAIXADA")])
    con.executemany("INSERT INTO favorecido_resumo VALUES (?, '', ?, 1)", [("88888888000188", 9000.0),
                                                                           ("44444444000144", 7000.0)])
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?, ?, '10/03/2024', 'Contabilizado', '100100', '')", [
        ("88888888000188", 9000.0), ("44444444000144", 7000.0)])
    con.commit(); con.close()
    monkeypatch.setattr(C, "_REPO", raiz)
    d = C.empresa_fenix(db_path=p)
    assert d["n_defunta_confirmada"] == 1 and d["total_apos_baixa"] == 9000.0
    assert d["fora_da_manchete"] == {"natureza_publica": {"n": 1, "valor": 7000.0}}
    assert d["n_pagou_so_antes"] == 0
    assert "indício" in d["ressalva"].lower() and "conferir" in d["ressalva"].lower()
