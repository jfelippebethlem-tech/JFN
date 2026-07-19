# -*- coding: utf-8 -*-
"""Testes do minerador do D.O. RIO (pcrj_doe_materia → eventos estruturados)."""
from compliance_agent.pcrj import doe_minerador as m

# trecho sintético com o padrão real de extrato de ata (OCR do D.O. RIO)
_TEXTO_ATA = (
    "EXTRATO DA ATA DE REGISTRO DE PREÇOS Nº 455/2026 Órgão Gestor: Secretaria "
    "Municipal de Saúde. Objeto: aquisição de medicamentos. Processo: 09/000.179/2026 "
    "Modalidade: Pregão Eletrônico - SMS/SRP nº 90334/2026 Validade da Ata: 12 meses. "
    "Empresa Vencedora: PHARMAHOSP COMERCIO DE MEDICAMENTOS LTDA - Item 26. "
    "CNPJ: 12.345.678/0001-90 EMAIL: compras.hmsa@gmail.com Valor Total Adjudicado: "
    "R$ 2.159.344,95 "
    "EXTRATO DA ATA DE REGISTRO DE PREÇOS Nº 456/2026 Órgão Gestor: Secretaria "
    "Municipal de Saúde. Objeto: medicamentos. Processo: 09/000.180/2026 "
    "Empresa Vencedora: PHARMAHOSP COMERCIO DE MEDICAMENTOS LTDA - Itens: 1, 2. "
    "CNPJ: 12.345.678/0001-90 Valor Total Adjudicado: R$ 500.000,00 "
    "PHARMAHOSP COMERCIO DE MEDICAMENTOS LTDA 2026NE000857"
)


def test_valor_br():
    assert m.valor_br("2.159.344,95") == 2159344.95
    assert m.valor_br("709.262,6240") == 709262.624
    assert m.valor_br("") == 0.0
    assert m.valor_br("lixo") == 0.0


def test_minerar_atas_tripe_vencedor():
    atas = m.minerar_atas(_TEXTO_ATA)
    assert len(atas) == 2
    a = atas[0]
    assert a["cnpj"] == "12345678000190"
    assert a["ata"] == "455"
    assert a["ano"] == 2026
    assert a["valor_adjudicado"] == 2159344.95
    assert "Secretaria Municipal de Saúde" in (a["orgao_gestor"] or "")


def test_minerar_atas_descarta_cnpj_incompleto():
    txt = ("Empresa Vencedora: FULANO LTDA - Item 1. CNPJ: 123/0001 "
           "Valor Total Adjudicado: R$ 10.000,00")
    assert m.minerar_atas(txt) == []


def test_extrair_empenhos_rotula_empenho():
    emp = m.extrair_empenhos(_TEXTO_ATA)
    assert emp
    assert emp[0]["empenho"] == "2026NE000857"
    assert emp[0]["natureza"] == "empenho"   # nunca 'pago'
    assert all(e["natureza"] == "empenho" for e in emp)


def test_extrair_gmails():
    g = m.extrair_gmails(_TEXTO_ATA)
    assert "compras.hmsa@gmail.com" in g


def test_concentracao_vencedor_synthetic(tmp_path, monkeypatch):
    # DB sintético com uma matéria contendo 2 atas do mesmo CNPJ
    import sqlite3
    dbp = tmp_path / "pcrj.db"
    con = sqlite3.connect(dbp)
    con.execute("CREATE TABLE pcrj_doe_materia (id_materia TEXT PRIMARY KEY, data TEXT, "
                "orgao TEXT, termo_busca TEXT, texto TEXT)")
    con.execute("INSERT INTO pcrj_doe_materia VALUES (?,?,?,?,?)",
                ("x1", "2026-07-14", None, "saude", _TEXTO_ATA))
    con.commit()
    con.close()

    def _fake_conectar(db_path=None):
        c = sqlite3.connect(dbp)
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(m.db, "conectar", _fake_conectar)

    r = m.concentracao_vencedor(min_atas=2, min_valor=100_000.0)
    assert r["ok"] and r["n"] == 1
    ach = r["achados"][0]
    assert ach["cnpj"] == "12345678000190"
    assert ach["n_atas"] == 2
    assert ach["valor_adjudicado"] == 2659344.95
    assert "ressalva" in r and "empenho" in r["ressalva"].lower()

    g = m.canal_informal()
    assert g["n"] >= 1
    assert any("gmail.com" in a["email"] for a in g["achados"])
