# -*- coding: utf-8 -*-
"""LAI automatizada (15/09/2026): fatos da base → requerimento nominal e neutro → registro com prazo."""
from __future__ import annotations

import sqlite3

from compliance_agent.lai.fatos import classificar_alvo, fatos_do_alvo
from compliance_agent.lai.registro import atualizar, listar, registrar, vencendo
from compliance_agent.lai.requerimento import montar


def _base(tmp_path):
    db = tmp_path / "pcrj.db"
    if db.exists():
        return db
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE contasrio_contrato (contrato, favorecido_doc, favorecido_nome, orgao, ug, ano, numero_instrumento,
        data_publicacao, objeto, situacao, vigencia_ini, vigencia_fim, processo, forma_contratacao, valor_atualizado,
        total_pago, url_ccon);
    INSERT INTO contasrio_contrato VALUES ('2509437','00801512000157','AGILE CORP SERVICOS ESPECIALIZADOS LTDA',
        '1601 - SME','160001',2025,'2509437','01/07/2025','Manipulação de alimentos','Vencida','01/01/2026','30/06/2026',
        'SME-PRO-2025/38233','Contratação Direta - Dispensa',24000000,23633526.63,'https://x/ccon-web/?contrato=2509437');
    CREATE TABLE contasrio_fiscal (contrato, fiscal_nome, fiscal_doc);
    INSERT INTO contasrio_fiscal VALUES ('2509437','JAZIEL AGUIAR MATOS','053.***.***-21');
    CREATE TABLE pcrj_processo (numero_processo, sistema, assunto, orgao, disponivel, coletado_em);
    INSERT INTO pcrj_processo VALUES ('SME-PRO-2025/38233','SEI.RIO','CONTRATAÇÃO · gerado 01/07/2025','E/SUBG',1,'2026-09-13');
    CREATE TABLE pcrj_sei_busca (termo, prot, processo, titulo, tipo_registro, unidade, data, snippet, capturado_em);
    INSERT INTO pcrj_sei_busca VALUES ('AGILE','7115150','SME-PRO-2025/38233','EXECUÇÃO FINANCEIRA nºSME-PRO-2025/38233 7115150','documento','E/SUBG','04/09/2026',NULL,'x');
    CREATE TABLE pcrj_processo_doc (numero_processo, seq, tipo, titulo, texto, url, coletado_em);
    INSERT INTO pcrj_processo_doc VALUES ('SME-PRO-2025/38233',12408,'ccon_termo_de_referencia','TR','texto','u','x');
    """)
    c.commit(); c.close()
    return db


def test_classificar_alvo():
    assert classificar_alvo("000700.007924/2026-97")[0] == "processo_sei"
    assert classificar_alvo("sme-pro-2025/38233") == ("processo_legado", "SME-PRO-2025/38233")
    assert classificar_alvo("00.801.512/0001-57") == ("cnpj", "00801512000157")
    assert classificar_alvo("2509437")[0] == "contrato" and classificar_alvo("Agile Corp")[0] == "nome"


def test_fatos_reunem_contrato_processo_documentos_e_fiscais(tmp_path):
    f = fatos_do_alvo("2509437", _base(tmp_path))
    assert f["tipo_alvo"] == "contrato" and f["esfera_sugerida"] == "prefeitura"
    assert [p["numero"] for p in f["processos"]] == ["SME-PRO-2025/38233"]
    p = f["processos"][0]
    assert p["documentos_vistos"][0]["prot"] == "7115150" and p["documentos_obtidos"][0]["seq"] == 12408
    assert f["fiscais"][0]["fiscal_nome"] == "JAZIEL AGUIAR MATOS"


def test_requerimento_e_nominal_fundamentado_e_neutro(tmp_path):
    from compliance_agent.reporting.neutralidade import garantir_neutro
    r = montar(fatos_do_alvo("SME-PRO-2025/38233", _base(tmp_path)))
    t = r["texto"]
    assert "12.527/2011" in t and "5.394/2012" in t and "art. 7º, §2º" in t
    assert "documento SEI nº 7115150" in t and "SME-PRO-2025/38233" in t and "JAZIEL AGUIAR MATOS" in t
    assert "R$ 23.633.526,63" in t and r["itens_pedido"] >= 6 and r["prazo_dias"] == 20
    garantir_neutro(t, contexto="teste LAI")
    assert montar(fatos_do_alvo("00.000.000/0001-91", _base(tmp_path)), esfera="estado")["destinatario"].startswith("Serviço de Informação")


def test_registro_status_e_prazo(tmp_path):
    db = tmp_path / "lai.db"
    i = registrar("SME-PRO-2025/38233", "prefeitura", "e-SIC PCRJ", ["SME-PRO-2025/38233"], ["2509437"], 7, None, "/tmp/x.md", db_path=db)
    r = atualizar(i, "protocolado", protocolo="2026.09.000123", db_path=db)
    assert r["status"] == "protocolado" and r["prazo_resposta"] and r["protocolo"] == "2026.09.000123"
    assert listar(db_path=db)[0]["vencido"] is False and vencendo(30, db_path=db)[0]["id"] == i
    try:
        atualizar(i, "inventado", db_path=db)
        raise AssertionError("status inválido aceito")
    except ValueError:
        pass


def test_gerar_fecha_o_ciclo(tmp_path, monkeypatch):
    import importlib
    g = importlib.import_module("compliance_agent.lai.gerar")   # o pacote exporta a FUNÇÃO gerar; o módulo vem por nome
    monkeypatch.setattr(g, "_OUT", tmp_path / "reports")
    r = g.gerar("2509437", db_path=_base(tmp_path), lai_db=tmp_path / "lai.db")
    assert r["ok"] and r["id"] == 1 and r["path_md"].endswith(".md") and r["documentos_nomeados"] == 1
    assert "PEDIDO:" in r["texto"] and r["resumo"].startswith("LAI #1")


def test_alvo_sem_arvore_vai_para_a_prioridade_do_sweep(tmp_path, monkeypatch):
    import importlib
    g = importlib.import_module("compliance_agent.lai.gerar")
    monkeypatch.setattr(g, "_PRIORIDADE", tmp_path / "prio.txt")
    g._priorizar_no_sweep(["SME-PRO-2025/38233", "000700.007924/2026-97"])
    g._priorizar_no_sweep(["SME-PRO-2025/38233"])   # idempotente
    assert (tmp_path / "prio.txt").read_text().split() == ["SME-PRO-2025/38233", "000700.007924/2026-97"]
