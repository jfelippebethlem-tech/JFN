# -*- coding: utf-8 -*-
"""Os seis órgãos do estado → câmara (adaptador TCE-RJ)."""
from compliance_agent.contratos import db as cd
from compliance_agent.contratos import estado


def _seed(con):
    cd.init_schema(con)
    con.execute("""create table if not exists contratos_tcerj (id integer primary key, processo text,
        sei_norm text, ano_processo int, data_contratacao text, valor_contrato real, status text,
        unidade text, objeto text, fornecedor text, cnpj text, vig_inicio text, vig_fim text,
        criterio_julgamento text)""")
    con.execute("""create table if not exists ob_orcamentaria_siafe (numero_ob text, processo text,
        credor text, nome_credor text, valor real)""")
    con.execute("""insert into contratos_tcerj (id, processo, valor_contrato, unidade, objeto,
        fornecedor, cnpj, vig_inicio, vig_fim) values
        (1,'SEI-030/2024',5000000,'DETRAN - DEPARTAMENTO','locação de sistema','ACME LTDA',
         '11.222.333/0001-81','2024-01-01','2025-01-01')""")
    con.execute("insert into ob_orcamentaria_siafe (numero_ob, processo, valor) values ('OB1','SEI-030/2024',4800000)")
    con.commit()


def test_orgaos_estado_tem_seis():
    assert len(estado.ORGAOS_ESTADO) == 6
    assert "SAUDE" in estado.ORGAOS_ESTADO and "DETRAN" in estado.ORGAOS_ESTADO


def test_montar_dossie_tcerj(tmp_path):
    con = cd.conectar(tmp_path / "t.db"); _seed(con)
    row = con.execute("select * from contratos_tcerj where id=1").fetchone()
    d = estado.montar_dossie_tcerj(con, row)
    assert d["contrato"]["fornecedor_documento"] == "11222333000181"
    assert d["contrato"]["valor_inicial"] == 5000000
    assert d["pagamentos"]["pago"] == 4800000       # ligado por processo
    assert d["aditivos"] == []                        # TCE-RJ não traz termos


def test_orgao_de_unidade():
    assert estado.orgao_de_unidade("FSERJ - FUNDAÇÃO SAÚDE") == "SAUDE"
    assert estado.orgao_de_unidade("SEEDUC - EDUCAÇÃO") == "EDUCACAO"
    assert estado.orgao_de_unidade("PREFEITURA XPTO") is None
