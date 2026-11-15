# -*- coding: utf-8 -*-
"""Cliente do segundo cérebro (compliance_agent/cerebro_compartilhado.py): nada sensível sai da máquina, correção
vai com `supersedes`, e cérebro fora do ar deixa a descoberta na fila (nunca "gravada" sem resposta). Sem rede."""
from __future__ import annotations

import pytest

from compliance_agent import cerebro_compartilhado as C


@pytest.fixture()
def con(tmp_path):
    c = C._con(tmp_path / "p.db")
    yield c
    c.close()


@pytest.mark.parametrize("texto", [
    "o sócio de CPF 123.456.789-09 assinou",
    "CPF 12345678909 no contrato",
    "favorecido ***.456.789-** (mascarado)",
    "favorecido 000.***.***-00",
    "contato fulano@orgao.rj.gov.br",
    "senha: abc123 do portal",
    "TOKEN=xyz",
    "painel em https://host.exemplo/Zq7Xw2Lk9Vb4Nc6Mt1Rp8Ys3Df5Gh0Ja",
    "chave sk0aB3dE5fG7hI9jK1lM3nO5pQ7rS9tU1vW3x",
])
def test_recusa_dado_pessoal_e_segredo(texto):
    assert C.recusar(texto) is not None                # controle positivo


@pytest.mark.parametrize("texto", [
    "Perícia contábil: Estado 40.218 contratos, 63 acima do valor; pago R$ 1.115.424.837,83",
    "Empresa de CNPJ 19.088.605/0001-04 e 19088605000104 no processo SEI-270131/000548/2023",
    "Correção de regra em 14/11/2026 (b28e3209): OB com duas ou mais Guias de Devolução",
    "painel em https://jfn-core.exemplo.net/painel",
])
def test_nao_recusa_fato_publico(texto):
    assert C.recusar(texto) is None                    # controle negativo: CNPJ, processo, valor e hash curto passam


def test_registrar_e_idempotente_e_correcao_reabre_o_envio(con):
    assert C.registrar("k", "placar 63", con=con) == "novo"
    assert C.registrar("k", "placar 63", con=con) == "igual"
    con.execute("UPDATE cerebro SET mem_id=7, hash_enviado=hash WHERE chave='k'")
    assert C.registrar("k", "placar 61", con=con) == "corrigido"
    assert C.resumo(con)["pendentes"] == 1


def test_recusado_nao_guarda_o_texto_nem_entra_na_fila(con):
    assert C.registrar("k", "CPF 123.456.789-09", con=con).startswith("recusado")
    conteudo, erro = con.execute("SELECT conteudo, erro FROM cerebro WHERE chave='k'").fetchone()
    assert conteudo is None and erro == "RECUSADO: cpf"
    r = C.resumo(con)
    assert (r["recusadas"], r["pendentes"]) == (1, 0)


def test_correcao_vai_com_supersedes_do_id_anterior(con, monkeypatch):
    enviados = []

    def http(caminho, corpo=None):
        enviados.append(corpo)
        return {"status": "gravada", "id": 100 + len(enviados)}
    monkeypatch.setattr(C, "_http", http)
    C.registrar("k", "placar 63", "semantica", "perícia", con=con)
    assert C.enviar_pendentes(con=con)["enviadas"] == 1
    assert enviados[0]["supersedes"] is None and enviados[0]["source"] == "claude-vm1"
    assert C.enviar_pendentes(con=con) == {"enviadas": 0, "corrigidas": 0, "duplicadas": 0, "falhas": 0, "erro": None}   # idempotente
    C.registrar("k", "placar 61", "semantica", "perícia", con=con)
    assert C.enviar_pendentes(con=con)["corrigidas"] == 1
    assert enviados[1]["supersedes"] == 101            # nunca sobrescreve: substitui pelo id
    assert con.execute("SELECT mem_id FROM cerebro WHERE chave='k'").fetchone()[0] == 102


def test_duplicada_de_outro_fato_nao_vira_id_desta_chave(con, monkeypatch):
    """O cérebro funde texto com similaridade > 0,96 e devolve o id do OUTRO fato. Medido em 14/11/2026: 3 alertas
    de emenda (parlamentares diferentes) gravados como a memória #87, e a correção seguinte substituiria a #87."""
    enviados = []

    def http(caminho, corpo=None):
        enviados.append(corpo)
        if corpo["content"] == "fato B":
            return {"status": "duplicada", "id": 87, "existente": "fato A"}
        return {"status": "gravada", "id": 87}
    monkeypatch.setattr(C, "_http", http)
    C.registrar("a", "fato A", con=con)
    C.registrar("b", "fato B", con=con)
    r = C.enviar_pendentes(con=con)
    assert (r["enviadas"], r.get("duplicadas")) == (1, 1)
    mem, erro = con.execute("SELECT mem_id, erro FROM cerebro WHERE chave='b'").fetchone()
    assert mem is None and "#87" in erro               # nunca herda o id do outro fato
    assert C.enviar_pendentes(con=con)["duplicadas"] == 0          # não reenvia a cada ciclo
    C.registrar("b", "fato B corrigido", con=con)
    C.enviar_pendentes(con=con)
    assert enviados[-1]["supersedes"] is None          # a correção não substitui a #87 (que é o fato A)


def test_duplicada_do_mesmo_texto_vale_como_gravada(con, monkeypatch):
    monkeypatch.setattr(C, "_http", lambda caminho, corpo=None: {"status": "duplicada", "id": 5, "existente": "fato A"})
    C.registrar("a", "fato A", con=con)
    assert C.enviar_pendentes(con=con)["enviadas"] == 1
    assert con.execute("SELECT mem_id FROM cerebro WHERE chave='a'").fetchone()[0] == 5


def test_cerebro_fora_do_ar_deixa_na_fila_e_nao_marca_enviado(con, monkeypatch):
    def http(caminho, corpo=None):
        raise C.CerebroIndisponivel("URLError: timed out")
    monkeypatch.setattr(C, "_http", http)
    C.registrar("a", "fato um", con=con)
    C.registrar("b", "fato dois", con=con)
    r = C.enviar_pendentes(con=con)
    assert r["falhas"] == 1 and "timed out" in r["erro"]          # parou na primeira: não insiste
    res = C.resumo(con)
    assert (res["gravadas"], res["pendentes"]) == (0, 2) and "timed out" in res["ultimo_erro"]


def test_busca_com_cerebro_fora_do_ar_levanta_em_vez_de_lista_vazia(monkeypatch):
    monkeypatch.setattr(C, "URL", "http://127.0.0.1:9")            # porta de descarte: recusa na hora
    monkeypatch.setattr(C, "TETO_S", 2)
    with pytest.raises(C.CerebroIndisponivel):
        C.recordar("qualquer")
    assert C.main(["caso", "qualquer"]) == 2


def test_kind_fora_da_lista_e_erro(con):
    with pytest.raises(ValueError):
        C.registrar("k", "fato", kind="opiniao", con=con)
