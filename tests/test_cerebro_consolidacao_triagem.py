# -*- coding: utf-8 -*-
"""Consolidação: o que dá para decidir SEM modelo, e o aceite que não desalinha o registro local.

Medido em 20/11/2026 (fila de produção, só leitura): 34 pares abertos e 0 chamadas ao modelo em duas noites (a
assinatura cedeu à perícia integral). 23 dos 34 são memórias de MESMO MOLDE sobre processos/empresas diferentes
— semelhança ≥ 0,90 pelo texto-padrão, nenhum identificador em comum. Não precisam de modelo.
Sem rede, sem modelo, sem tocar em data/."""
import pytest

from compliance_agent import cerebro_compartilhado as C
from compliance_agent import cerebro_consolidacao as K


def _par(a, b, ta, tb, chave_a=None):
    lado = lambda i, t, ch: {"id": i, "kind": "semantica", "subject": "s", "content": t, "chave": ch,  # noqa: E731
                             "created_at": "2026-11-10T00:00:00+00:00"}
    return {"sim": 0.95, "a": lado(a, ta, chave_a), "b": lado(b, tb, None)}


@pytest.fixture
def con(tmp_path):
    c = K._con(tmp_path / "fila.db")
    yield c
    c.close()


def test_pares_sem_identificador_em_comum_fecham_como_distintos_sem_modelo(con):
    K.colher(con, [
        _par(1, 2, "Emergência SEI-270042/000123/2024: contrato de R$ 1.000,00.", "Emergência SEI-270042/000999/2025: contrato de R$ 9.000,00."),
        # controle: mesmo processo dos dois lados → pode ser o mesmo fato ou contradição: fica para o modelo
        _par(3, 4, "SEI-270042/000123/2024: pago R$ 1.000,00.", "SEI-270042/000123/2024: pago R$ 1.200,00."),
        # controle: um lado sem identificador → não há como afirmar que são fatos distintos
        _par(5, 6, "Rubrica v3 da perícia: candidata.", "Rubrica v5 da perícia SEI-270042/000123/2024: candidata."),
    ])
    assert K.triar(con) == {"distintos_sem_modelo": 1, "seguem_para_o_modelo": 2}
    lin = con.execute("SELECT estado, modelo, motivo FROM fila WHERE a=1").fetchone()
    assert (lin["estado"], lin["modelo"]) == ("distintos", "regra:identificadores-disjuntos") and "270042/000999/2025" in lin["motivo"]
    assert K.resumo(con) == {"aberto": 2, "distintos": 1}
    assert K.triar(con)["distintos_sem_modelo"] == 0                    # idempotente


def test_aceitar_fato_com_chave_passa_pelo_registro_local_e_a_proxima_correcao_substitui_o_certo(con, tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DATA", tmp_path)
    enviados = []

    def http(caminho, corpo=None, mcp=False):
        enviados.append(corpo)
        return {"status": "gravada", "id": 100 + len(enviados)}
    monkeypatch.setattr(C, "_http", http)
    assert C.lembrar("caso:x", "fato original do caso x", "semantica")["id"] == 101
    K.colher(con, [_par(101, 7, "fato original do caso x", "o mesmo fato do caso x, dito de outro jeito", chave_a="caso:x")])
    con.execute("UPDATE fila SET estado='proposto', veredito='mesmo_fato', proposta='fato do caso x, texto único'")
    r = K.decidir(con, 1, True)
    assert r["estado"] == "aceito" and r["revogar_a_mao"] == 7
    assert enviados[-1]["supersedes"] == 101 and enviados[-1]["chave"] == "caso:x"
    # a rotina dona da chave corrige depois: tem de substituir a versão ACEITA (102), não a que já saiu (101)
    C.lembrar("caso:x", "fato do caso x corrigido pela rotina", "semantica")
    assert enviados[-1]["supersedes"] == 102


def test_controle_aceitar_fato_sem_chave_vai_direto_e_nao_cria_linha_no_registro(con, tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DATA", tmp_path)
    enviados = []
    monkeypatch.setattr(C, "_http", lambda caminho, corpo=None, mcp=False: enviados.append(corpo) or {"status": "gravada", "id": 55})
    K.colher(con, [_par(8, 9, "fato solto A", "fato solto A de novo")])
    con.execute("UPDATE fila SET estado='proposto', veredito='mesmo_fato', proposta='fato solto, texto único'")
    assert K.decidir(con, 1, True)["estado"] == "aceito"
    assert enviados[0]["supersedes"] == 8 and enviados[0]["chave"] is None
    reg = C.conectar()
    assert reg.execute("SELECT COUNT(*) FROM cerebro").fetchone()[0] == 0
    reg.close()
