# -*- coding: utf-8 -*-
"""Tentado e BARRADO é uma cegueira diferente de nunca tocado — e é limite institucional.

O cartão de cobertura dizia quantos processos a casa consegue ler e quantos nunca tocou, e calava
sobre os que ela TENTOU ler e não conseguiu: o processo existe, o itkava tem login, e a árvore não
abre. Isso não se resolve com código — resolve-se com pedido formal de acesso.

Medido em 2026-08-04 sobre o registro de controle: **422 de 1.248 processos tentados (33,8%)**
estão como RESTRITO/RESTRITO?, e a restrição é da UNIDADE, não do processo:

    040014 Fundo Único de Previdência ......  93% (52 de 56)
    260006/080001 Fundo Estadual de Saúde ..  58% / 52%
    080002 Fundação Saúde ..................  50% (130 de 261)
    270131 / 270003 / 270006 ...............  1% a 3%

Metade da Saúde está fora de alcance — e a Fundação Saúde é justamente a entidade que paga 27% de
tudo por TAC/indenização (R$ 2,81 bi).
"""
import json
import sqlite3

from compliance_agent.reporting import cobertura_captura as C


def _ambiente(tmp_path, registro, com_ob=True):
    (tmp_path / "data").mkdir(exist_ok=True)
    acervo = tmp_path / "data" / "sei_arquivo"
    acervo.mkdir()
    (tmp_path / "data" / "sei_restritos.json").write_text(json.dumps(registro), encoding="utf-8")
    db = tmp_path / "data" / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE ordens_bancarias (numero_sei TEXT, ug_nome TEXT)")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (processo TEXT, valor REAL, status TEXT)")
    if com_ob:
        con.executemany("INSERT INTO ordens_bancarias VALUES (?,?)",
                        [("SEI-040014/000001/2024", "FUNDO UNICO DE PREVIDENCIA")] * 3)
    con.commit(); con.close()
    return db, acervo


def _registro(n_restritos, n_ok, prefixo="040014"):
    r = {}
    for i in range(n_restritos):
        r[f"r{i}"] = {"prefixo": prefixo, "status": "RESTRITO"}
    for i in range(n_ok):
        r[f"o{i}"] = {"prefixo": prefixo, "status": "OK"}
    return r


def test_a_restricao_e_medida_e_nomeada_por_unidade(tmp_path):
    db, acervo = _ambiente(tmp_path, _registro(52, 4))
    r = C.medir(db=db, acervo=acervo)["restricao"]
    assert r["disponivel"] is True
    assert r["processos_tentados"] == 56 and r["restritos"] == 52
    u = r["por_unidade"][0]
    assert u["ug"] == "040014" and u["pct"] == 93
    assert "PREVIDENCIA" in u["nome"], "unidade sem nome não serve para pedir acesso"


def test_RESTRITO_interrogacao_conta_como_fora_de_alcance(tmp_path):
    """Uma leitura já é porta fechada para efeito de cobertura — o que a segunda decide é se a
    marca vira definitiva para o sweep, não se a casa conseguiu ler."""
    reg = _registro(0, 2)
    reg["x"] = {"prefixo": "040014", "status": "RESTRITO?"}
    db, acervo = _ambiente(tmp_path, reg)
    assert C.medir(db=db, acervo=acervo)["restricao"]["restritos"] == 1


def test_unidade_com_poucos_processos_nao_entra_no_ranking(tmp_path):
    """Duas leituras de uma unidade não sustentam "93% restrito" — ruído vira manchete falsa."""
    db, acervo = _ambiente(tmp_path, _registro(2, 0))
    assert C.medir(db=db, acervo=acervo)["restricao"]["por_unidade"] == []


def test_sem_registro_o_bloco_se_declara_indisponivel(tmp_path):
    (tmp_path / "data").mkdir()
    acervo = tmp_path / "data" / "sei_arquivo"; acervo.mkdir()
    db = tmp_path / "data" / "c.db"; sqlite3.connect(db).close()
    # sem `ob_orcamentaria_siafe` o resto fica INDISPONÍVEL, mas o bloco de restrição existe e se
    # declara honestamente — calar duas coisas por falta de uma seria pior.
    assert C.medir(db=db, acervo=acervo)["restricao"] == {"disponivel": False}


def test_sem_tabela_de_ob_ainda_mede_sem_o_nome(tmp_path):
    """Perder o nome da unidade não pode apagar a medição da porta fechada."""
    db, acervo = _ambiente(tmp_path, _registro(30, 5), com_ob=False)
    r = C.medir(db=db, acervo=acervo)["restricao"]
    assert r["restritos"] == 30 and r["por_unidade"][0]["nome"] == ""
