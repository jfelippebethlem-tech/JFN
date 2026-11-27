"""27/11/2026 — folha do TJRJ (Anexo VIII). Três defeitos medidos: (1) o GED passou a entregar o HTML direto e o
coletor só aceitava ZIP → 06 e 08/2026 viravam «sem publicação»; (2) a deduplicação não tinha o mês → quem já
aparecera nunca era gravado nos meses seguintes; (3) títulos e legendas da planilha entravam como servidores."""
import io
import sqlite3
import zipfile

from compliance_agent.collectors import folha_tjrj as T

HTML = ("<html><table>"
        "<tr><td>TRIBUNAL DE JUSTIÇA DO ESTADO DO RIO DE JANEIRO</td><td></td><td></td><td></td></tr>"
        "<tr><td>MAGISTRADOS</td><td></td><td></td><td></td></tr>"
        "<tr><td>Nome</td><td>Lotação</td><td>Cargo</td><td>Total</td></tr>"
        "<tr><td>FULANA DE TAL</td><td>GAB. DES X</td><td>ANALISTA JUDICIARIO B-8</td><td>36.374,09</td></tr>"
        "</table></html>")


def test_arquivo_em_zip_ou_html_direto():
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("a.html", HTML.encode("latin-1"))
    assert "FULANA" in T._texto_do_arquivo(z.getvalue())
    assert "FULANA" in T._texto_do_arquivo(HTML.encode("latin-1"))           # o formato de 2026
    assert T._texto_do_arquivo(b"%PDF-1.4 ...") == ""


def test_titulos_da_planilha_nao_viram_servidor():
    regs = T.parsear(HTML, "2026-08")
    assert [(r["nome"], r["cargo"], r["bruto"]) for r in regs] == [("FULANA DE TAL", "ANALISTA JUDICIARIO B-8", 36374.09)]


def test_foto_por_mes(monkeypatch):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE registros_folha (id INTEGER PRIMARY KEY, cpf, nome, orgao_codigo, orgao_nome, cargo, vinculo,"
                " competencia, remuneracao_bruta, remuneracao_liquida, abonos, descontos, fonte, created_at)")

    class _C:                                                                # ingerir fecha a conexão: não deixar
        def __getattr__(self, k):
            return (lambda: None) if k == "close" else getattr(con, k)
    monkeypatch.setattr(T, "abrir_banco", lambda: _C())
    r = T.parsear(HTML, "2026-05")[0]
    assert T.ingerir([r]) == 1
    assert T.ingerir([r]) == 0                                               # mesmo mês: não duplica
    assert T.ingerir([{**r, "competencia": "2026-08"}]) == 1                 # outro mês: grava (antes: 0)
    assert con.execute("SELECT count(*) FROM registros_folha").fetchone()[0] == 2
