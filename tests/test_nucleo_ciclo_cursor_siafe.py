# -*- coding: utf-8 -*-
"""O ciclo do Núcleo tem de AVANÇAR sobre o SIAFE, não reler um top-600 fixo do espelho TFE.

Medido em 11/11/2026: `pericias_novas: 0` todo dia desde 25/10. O pool era `.limit(limite*3)` = as 600 maiores
OBs do `ordens_bancarias` (TFE), cortado ANTES de filtrar o já periciado — esgotadas as 600, o ciclo volta vazio
para sempre (padrão "teto de coleta era do parâmetro"). E lia o espelho TFE, contra a regra "OB → SIAFE".
Agora: cursor (valor desc, rowid) sobre `ob_orcamentaria_siafe`, só OB Contabilizada, pulando o já periciado
e seguindo página a página até achar `limite` novas.
"""
from __future__ import annotations

import pytest

sa = pytest.importorskip("sqlalchemy")


def _sessao(n_obs: int, sancionado: str | None = None):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    s = sessionmaker(bind=create_engine("sqlite:///:memory:"))()
    s.execute(text("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT,"
                   " status TEXT, credor TEXT, nome_credor TEXT, processo TEXT, valor REAL, exercicio INTEGER)"))
    s.execute(text("CREATE TABLE sancoes_federais (cpf_cnpj TEXT, categoria TEXT, data_inicio TEXT, data_fim TEXT)"))
    for i in range(n_obs):
        s.execute(text("INSERT INTO ob_orcamentaria_siafe VALUES (:n,'290100','15/03/2026','Contabilizado',"
                       "'11222333000181','X LTDA','SEI-1',:v,2026)"), {"n": f"2026OB{i:05d}", "v": 1e6 - i})
    # anulada e excluída NÃO são pagamento — nunca entram, por maiores que sejam
    s.execute(text("INSERT INTO ob_orcamentaria_siafe VALUES ('2026OB99998','290100','01/01/2026','Anulado',"
                   "'1','A',NULL,9e9,2026)"))
    s.execute(text("INSERT INTO ob_orcamentaria_siafe VALUES ('2026OB99999','290100','01/01/2026','Excluído',"
                   "'1','A',NULL,8e9,2026)"))
    if sancionado:
        s.execute(text("INSERT INTO sancoes_federais VALUES (:d,'Suspensão','2025-01-01','2027-01-01')"),
                  {"d": sancionado})
        s.execute(text("INSERT INTO ob_orcamentaria_siafe VALUES ('2026OB50000','170100','10/02/2026',"
                       "'Contabilizado',:d,'S LTDA','SEI-2',20000,2026)"), {"d": sancionado})
    s.commit()
    return s


@pytest.fixture
def periciadas(monkeypatch, tmp_path):
    monkeypatch.setenv("NUCLEO_MEMORIA_DB", str(tmp_path / "mem.db"))
    import compliance_agent.nucleo.adaptador_db as A
    vistos = []

    class _L:
        class veredito:
            achados = []

    def _fake(session, ob, enriquecer=False):
        vistos.append(ob)
        from compliance_agent.nucleo.memoria_pericial import _conectar
        con = _conectar()
        con.execute("INSERT INTO pericias(referencia, quando) VALUES(?, '2026-11-11')", (ob.referencia_pericia,))
        con.commit()
        con.close()
        return _L()

    monkeypatch.setattr(A, "periciar_ob", _fake)
    return vistos


def test_so_ob_contabilizada_do_siafe(periciadas):
    from compliance_agent.nucleo.ciclo import _periciar_base
    r = _periciar_base(_sessao(3), limite=10)
    assert r["pericias_novas"] == 3
    assert {o.numero_ob for o in periciadas} == {"2026OB00000", "2026OB00001", "2026OB00002"}
    assert all(o.referencia_pericia.startswith("siafe:") for o in periciadas)
    assert periciadas[0].favorecido_cpf == "11222333000181" and periciadas[0].valor == 1e6


def test_cursor_avanca_alem_das_ja_periciadas(periciadas):
    """Com as 1.500 maiores já feitas, o ciclo seguinte acha as próximas — não volta vazio."""
    from compliance_agent.nucleo.ciclo import _periciar_base
    s = _sessao(1_510)
    assert _periciar_base(s, limite=1_500)["pericias_novas"] == 1_500
    periciadas.clear()
    r = _periciar_base(s, limite=200)
    assert r["pericias_novas"] == 10, "o top fixo esgotado era o defeito: zero novas desde 25/10"
    assert periciadas[0].numero_ob == "2026OB01500"
    assert _periciar_base(s, limite=200)["pericias_novas"] == 0   # acabou de verdade, não por teto


def test_sancionado_entra_primeiro_mesmo_abaixo_do_corte(periciadas):
    from compliance_agent.nucleo.ciclo import _periciar_base
    _periciar_base(_sessao(5, sancionado="99888777000166"), limite=2)
    assert periciadas[0].favorecido_cpf == "99888777000166"


def test_periciar_ob_usa_a_referencia_e_a_fonte_do_siafe(monkeypatch, tmp_path):
    """`ob:<id>` é a chave do TFE; OB do SIAFE é (numero_ob, ug, exercício) e a fonte tem de dizer SIAFE."""
    monkeypatch.setenv("NUCLEO_MEMORIA_DB", str(tmp_path / "mem.db"))
    import compliance_agent.nucleo.adaptador_db as A
    from types import SimpleNamespace
    capt = {}
    monkeypatch.setattr(A, "periciar", lambda contratacao, fornecedor, usar_memoria: capt.update(c=contratacao))
    monkeypatch.setattr(A, "_fornecedor_de_empresa", lambda e, s=None: SimpleNamespace(
        cnpj="", nome="", doacoes_eleitorais=[], sancionado=True))
    s = _sessao(0)
    ob = SimpleNamespace(referencia_pericia="siafe:2026OB1:290100:2026", fonte_pericia="siafe_ob",
                         favorecido_cpf="", valor=10.0, data_emissao=None, ug_nome="290100")
    A.periciar_ob(s, ob)
    assert capt["c"].identificador == "siafe:2026OB1:290100:2026"
    assert capt["c"].fonte == "siafe_ob"
