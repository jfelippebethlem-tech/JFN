"""27/11/2026: casamento com benefícios sociais pela máscara PÚBLICA de cada fonte. O QSA mostra os dígitos 4–9 do CPF
(6), a folha do RJ os dígitos 3–8 (6); o Portal da Transparência mostra 4–9. Sócio casa com 6 dígitos; servidor só
pode casar pelos 5 comuns (4–8) — usar a janela errada casaria pessoas diferentes."""
import sqlite3

from tools.beneficios import chaves as C


def _con():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE socios_fornecedor (cnpj, socio_nome, socio_doc)")
    con.execute("CREATE TABLE registros_folha (nome, cpf, orgao_nome, cargo, vinculo, competencia, remuneracao_bruta, fonte)")
    # mesma pessoa fictícia: QSA ***456789** (dígitos 4–9); folha XX345678XXX (dígitos 3–8)
    con.execute("INSERT INTO socios_fornecedor VALUES ('11222333000181', 'José da Silva', '***456789**')")
    con.execute("INSERT INTO socios_fornecedor VALUES ('11222333000181', 'Empresa PJ', '11222333000181')")
    con.execute("INSERT INTO registros_folha VALUES ('JOSÉ  DA SILVA', 'XX345678XXX', 'DPRJ', 'ASSESSOR', 'CARGO COMISSAO', '2026-06', 9000.5, 'dprj_transparencia')")
    # GESPERJ grava a máscara do Portal (***.456.789-**) como XX456789XXX: janela 4–9, 6 dígitos
    con.execute("INSERT INTO registros_folha VALUES ('MARIA SOUZA', 'XX456789XXX', 'SEEDUC', 'ASSESSOR', 'CARGO COMISSAO', '2026-06', 7000.0, 'gesperj_estado')")
    con.execute("INSERT INTO registros_folha VALUES ('SEM JANELA', 'XX456789XXX', 'TJ', 'X', 'Y', '2026-06', 1.0, 'tjrj_anexo8')")
    return con


def test_socio_usa_os_6_digitos_4_a_9_e_ignora_pj():
    assert C.chaves_socios(_con()) == {"JOSE DA SILVA|456789": ["11222333000181"]}


def test_servidor_janela_por_fonte():
    v = C.chaves_servidores(_con())
    assert sorted(v) == ["JOSE DA SILVA|45678", "MARIA SOUZA|456789"]   # DPRJ 3–8 → 5 comuns; GESPERJ 4–9 → 6; TJ fora
    assert v["JOSE DA SILVA|45678"]["meses"] == {"2026-06": 9000.5}
    assert "456789"[:5] == "45678"                                # a mesma pessoa no Portal (***.456.789-**)
