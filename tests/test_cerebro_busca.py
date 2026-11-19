# -*- coding: utf-8 -*-
"""Busca fundida do segundo cérebro (fase 1) — sem rede: as pernas remotas são trocadas por listas fixas."""
import pytest

from compliance_agent import cerebro_busca as B
from compliance_agent.cerebro_compartilhado import CerebroIndisponivel


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    (v / "casos").mkdir(parents=True)
    (v / "processos").mkdir()
    (v / ".obsidian").mkdir()
    (v / "casos" / "pericia-bombeiros-funesbom-2024.md").write_text(
        "---\nresumo: perícia do corpo de bombeiros\n---\n# Perícia Bombeiros\nPagamentos do FUNESBOM em 2024.\n",
        encoding="utf-8")
    (v / "casos" / "grupo-caneca.md").write_text(
        "# Grupo Caneca\nCNPJ 33.780.199/0001-77 recebeu da Fundação Saúde.\n", encoding="utf-8")
    (v / "processos" / "270131.md").write_text("# Processo\nbombeiros bombeiros bombeiros perícia\n", encoding="utf-8")
    (v / ".obsidian" / "lixo.md").write_text("bombeiros", encoding="utf-8")
    monkeypatch.setattr(B, "VAULT", v)
    monkeypatch.setattr(B, "INDICE", tmp_path / "indice.db")
    return v


def test_termos_tira_acento_e_palavra_vazia():
    assert B.termos("e a perícia sobre os bombeiros?") == ["pericia", "bombeiros"]
    assert B.termos("quanto a SEEDUC pagou em 2025") == ["seeduc", "pagou", "2025"]


def test_entidades_reconhece_cnpj_processo_e_ug():
    e = B.entidades("empresa 33.780.199/0001-77 no SEI-080001/013827/2024, UG 294200")
    assert ("cnpj", "33780199000177") in e
    assert B.entidades("protocolo 33780199000178") == []          # 14 dígitos com verificador errado não é CNPJ
    assert ("processo", "080001/013827/2024") in e
    assert ("ug", "294200") in e
    assert B.entidades("blindados da pm em 2023") == []          # controle negativo: ano não é entidade


def test_caminho_da_nota_e_relativo_ao_vault():
    assert B._nota("/home/ubuntu/sync/vault/casos/x.md") == "casos/x.md"
    assert B._nota("casos/x.md") == "casos/x.md"


def test_indice_local_acha_pela_palavra_sem_acento_e_ignora_pasta_oculta(vault):
    r = B.indexar(forcar=True)
    assert r["notas"] == 3                                        # .obsidian fica fora
    notas = [x["nota"] for x in B._perna_local("pericia dos bombeiros")]
    assert notas[0] == "casos/pericia-bombeiros-funesbom-2024.md"   # nome do arquivo e título pesam mais que repetição
    assert B._perna_local("e a o de") == []                       # só palavra vazia: não consulta


def test_indice_local_e_incremental_e_tira_nota_removida(vault):
    B.indexar(forcar=True)
    assert B.indexar(forcar=True)["regravadas"] == 0
    (vault / "casos" / "grupo-caneca.md").unlink()
    assert B.indexar(forcar=True)["removidas"] == 1
    assert B._perna_local("caneca") == []


def test_bm25_local_da_a_ordem_e_o_vetor_so_resgata(vault, monkeypatch):
    monkeypatch.setitem(B._FUNCOES, "brain", lambda q: [{"nota": "shared:sessao.md", "trecho": "do cérebro"},
                                                         {"nota": "casos/pericia-bombeiros-funesbom-2024.md"}])
    r = B.buscar_fundido("pericia bombeiros", k=5)
    notas = [f["nota"] for f in r["notas"]]
    assert notas[0] == "casos/pericia-bombeiros-funesbom-2024.md"          # a ordem é a do BM25, não a do cérebro
    assert notas[-1] == "shared:sessao.md" and r["notas"][-1]["resgate"]   # o que só o cérebro tem entra no fim
    assert r["notas"][0]["pernas"] == {"local": 1, "brain": 2} and not r["notas"][0]["resgate"]
    assert all(v.startswith("ok") for v in r["pernas"].values())


def test_resgate_ocupa_no_maximo_dois_lugares_de_uma_lista_cheia(vault, monkeypatch):
    for i in range(12):
        (vault / "casos" / f"bombeiros-{i:02d}.md").write_text("# x\nbombeiros\n", encoding="utf-8")
    monkeypatch.setitem(B._FUNCOES, "brain", lambda q: [{"nota": f"shared:s{i}.md"} for i in range(9)])
    r = B.buscar_fundido("bombeiros", k=10)
    assert [f["resgate"] for f in r["notas"]] == [False] * 8 + [True] * 2


def test_identificador_citado_vem_na_frente(vault, monkeypatch):
    (vault / "processos" / "080001.md").write_text("# P\nSEI-080001/013827/2024 pago.\n", encoding="utf-8")
    (vault / "casos" / "tem.md").write_text("# tem tem tem\n o que tem no processo\n", encoding="utf-8")
    monkeypatch.setitem(B._FUNCOES, "brain", lambda q: [])
    monkeypatch.setattr(B.cerebro, "DATA", vault)                 # sem propagacao.db: só a frase no índice local
    f = B.buscar_fundido("o que tem no processo 080001/013827/2024", k=5)["notas"][0]
    assert f["nota"] == "processos/080001.md" and f["pernas"].get("entidade") == 1


def test_perna_fora_do_ar_e_dita_e_todas_fora_levanta(vault, monkeypatch):
    def fora(q):
        raise CerebroIndisponivel("sem rede")
    monkeypatch.setitem(B._FUNCOES, "brain", fora)
    r = B.buscar_fundido("pericia bombeiros")
    assert r["pernas"]["brain"].startswith("INDISPONÍVEL") and r["pernas"]["local"].startswith("ok")
    assert r["notas"]                                             # a perna local segura a resposta
    monkeypatch.setitem(B._FUNCOES, "local", fora)
    monkeypatch.setitem(B._FUNCOES, "entidade", fora)
    with pytest.raises(CerebroIndisponivel):
        B.buscar_fundido("pericia bombeiros")


def test_sem_primaria_a_ordem_e_a_do_vetor(vault, monkeypatch):
    monkeypatch.setitem(B._FUNCOES, "brain", lambda q: [{"nota": "a.md"}, {"nota": "b.md"}, {"nota": "c.md"}])
    r = B.buscar_fundido("pericia bombeiros", k=3, sem=("local", "entidade"))
    assert [f["nota"] for f in r["notas"]] == ["a.md", "b.md", "c.md"]
