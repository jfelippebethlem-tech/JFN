"""Inexigibilidade × os próprios autos (SEEDUC × EUREKA, SEI-030001/103373/2024, lido em 27/09/2026)."""
import sqlite3

from compliance_agent.inexigibilidade_coerencia import analisar

CONTRATO = {"titulo": "Contrato SEEDUC Nº 02-2025", "texto": "decorrente de Inexigibilidade, mediante as cláusulas"}
ETP = {"titulo": "Estudo Técnico Preliminar 88761125", "texto": (
    "*Os ISBNs: serão utilizados como referência, sendo possível por parte do licitante a indicação, se houver, de "
    "versões mais recentes e/ou outras editoras, desde que tenham características físicas similares. "
    "Este material foi adquirido pela SEEDUC através do processo SEI-030029/008726/2023, Contrato SEEDUC nº 14/2023. "
    "A equipe técnica recomenda a aquisição, observando-se a modalidade licitatória que melhor atenda.")}


def _db(tmp_path):
    p = tmp_path / "c.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE contratos_tcerj (processo TEXT, sei_norm TEXT, cnpj TEXT, fornecedor TEXT)")
    c.executemany("INSERT INTO contratos_tcerj VALUES (?,?,?,?)", [
        ("SEI-030001/103373/A/2024", "0300011033732024", "06982873000123", "EUREKA"),
        ("SEI-030029/008726/2023", "0300290087262023", "09175434000105", "PHOTONLUX DISTRIBUIDORA")])
    c.commit(); c.close()
    return p


def test_eureka_acende_as_tres_regras(tmp_path):
    r = analisar([CONTRATO, ETP], "SEI-030001/103373/2024", db_path=_db(tmp_path))
    tipos = {a["tipo"]: a for a in r["achados"]}
    assert r["grau"] == "vermelho"
    assert set(tipos) == {"etp_admite_equivalente", "etp_recomenda_licitacao", "objeto_ja_fornecido_por_outro"}
    assert "PHOTONLUX" in tipos["objeto_ja_fornecido_por_outro"]["diz"]


def test_pregao_que_cita_art_74_nao_e_inexigibilidade(tmp_path):
    ed = {"titulo": "Minuta de Edital - Pregão Eletrônico", "texto": "vedado o art. 74 ... modalidade licitatória pretendida"}
    assert analisar([ed], "SEI-070002/015404/2022", db_path=_db(tmp_path))["grau"] == "nao_aplicavel"


def test_citacao_sem_contexto_de_compra_anterior_nao_acusa(tmp_path):
    etp = {"titulo": "Termo de Referência", "texto": "conforme orientação do processo SEI-030029/008726/2023 sobre cursos"}
    r = analisar([CONTRATO, etp], "SEI-030001/103373/2024", db_path=_db(tmp_path))
    assert not [a for a in r["achados"] if a["tipo"] == "objeto_ja_fornecido_por_outro"]


def test_qualificacao_tecnica_com_similares_nao_e_equivalencia_do_objeto(tmp_path):
    tr = {"titulo": "Termo de Referência", "texto": "a prévia experiência em atividades congêneres ou similares ao objeto licitado"}
    r = analisar([CONTRATO, tr], "SEI-1/1/2025", db_path=_db(tmp_path))
    assert r["grau"] == "verde"
