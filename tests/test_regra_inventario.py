# -*- coding: utf-8 -*-
"""Catracas do inventário vivo (CST-11, COR-13, CNF-15, CST-04) — e as provas de que acusam (COR-15).

Enumera por código (regex, sem importar `server`) e confronta com `config/qualidade_inventario.yaml`.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

from compliance_agent.qualidade import catraca, inventario as I

DETECTORES_YAML = I.REPO / "config" / "qualidade_detectores.yaml"


@lru_cache(maxsize=1)
def _conf() -> dict:
    return I.confrontar()


def _lista(itens) -> str:
    return "\n  " + "\n  ".join(itens[:60])


# ───────────────────────────── CST-11: superfície inventariada ─────────────────────────────

def test_toda_rota_tem_entrada_completa():
    c = _conf()
    assert not c["sem_entrada"]["rotas"], (
        "CST-11: rota /api sem entrada em config/qualidade_inventario.yaml › rotas (declare classe, afirma, fonte):"
        + _lista(c["sem_entrada"]["rotas"]))
    assert not c["incompletas"]["rotas"], ("CST-11: rota com classe inválida ou `afirma` vazio:"
                                           + _lista(c["incompletas"]["rotas"]))


def test_rota_inventariada_existe():
    morta = _conf()["entrada_morta"]["rotas"]
    assert not morta, "CST-11: entrada morta (a rota não existe mais no código) — apague do inventário:" + _lista(morta)


def test_todo_card_e_chip_tem_manchete():
    c = _conf()
    assert not c["sem_entrada"]["manchetes"], ("CST-11: card do cockpit/chip da mesa sem manchete no inventário:"
                                               + _lista(c["sem_entrada"]["manchetes"]))
    assert not c["entrada_morta"]["manchetes"], ("CST-11: manchete de card/chip que não existe mais:"
                                                 + _lista(c["entrada_morta"]["manchetes"]))
    assert not c["incompletas"]["manchetes"], "CST-11: manchete incompleta:" + _lista(c["incompletas"]["manchetes"])


def test_manchete_aponta_rota_existente():
    rotas = I.rotas()
    ruins = [f"{m['id']}: {m['rota']}" for m in I.carregar().get("manchetes", []) if m["rota"] not in rotas]
    assert not ruins, "CST-11: manchete aponta rota que não existe:" + _lista(ruins)


def test_toda_aba_tem_entrada():
    c = _conf()
    assert not c["sem_entrada"]["abas"], "CST-11: aba do painel sem entrada:" + _lista(c["sem_entrada"]["abas"])
    assert not c["entrada_morta"]["abas"], "CST-11: aba inventariada que sumiu:" + _lista(c["entrada_morta"]["abas"])


def test_peca_do_lex_inventariada_existe():
    assert not _conf()["entrada_morta"]["lex"], "CST-11: peça do Lex inventariada sem arquivo:" + _lista(
        _conf()["entrada_morta"]["lex"])


# ───────────────────────────── catracas-catraca (só descem) ─────────────────────────────

def test_catraca_rotas_com_fonte_a_declarar():
    atual = I.fonte_a_declarar(I.carregar())
    excesso = catraca.cresceu(atual, catraca.ler_base("inventario_fonte_a_declarar"))
    assert not excesso, catraca.mensagem("CST-11", "rota que AFIRMA sem fonte declarada", excesso)


def test_dados_do_painel_tem_gerador_existente():
    """COR-13: gerador declarado aponta para arquivo do repositório; "A DECLARAR" só desce."""
    sg = _conf()["sem_gerador"]
    inexistentes = [f"{a}: {m}" for a, m in sg.items() if m != I.A_DECLARAR]
    assert not inexistentes, "COR-13: gerador declarado não existe:" + _lista(inexistentes)
    atual = {a: 1 for a, m in sg.items() if m == I.A_DECLARAR}
    excesso = catraca.cresceu(atual, catraca.ler_base("inventario_dados_sem_gerador"))
    assert not excesso, catraca.mensagem("COR-13", "arquivo de dados do painel sem gerador versionado", excesso)


def test_relatorio_fonte_existe():
    morta = _conf()["entrada_morta"]["relatorios"]
    assert not morta, "CNF-15: relatório inventariado aponta arquivo-fonte inexistente:" + _lista(morta)


def test_catraca_relatorio_sem_neutralidade():
    """CNF-15: relatório sem `garantir_neutro` só diminui; relatório NOVO nasce com o gate."""
    atual = {r: 1 for r in _conf()["relatorio_sem_neutro"]}
    excesso = catraca.cresceu(atual, catraca.ler_base("inventario_relatorio_sem_neutro"))
    assert not excesso, catraca.mensagem("CNF-15", "entregável sem gate de neutralidade", excesso)


def test_gates_declarados_batem_com_o_codigo():
    """O campo `gates` do YAML não pode afirmar gate que o código não chama (o inventário também afirma)."""
    inv = I.carregar()
    real = I.relatorios_gate(inv=inv)
    nome_gate = {"garantir_neutro": "neutro", "garantir_neutro_exceto_dados": "neutro", "gate_citacoes": "citacoes",
                 "sanear_parecer": "citacoes", "render_html": "render_html"}
    mentiras = [f"{r}: {g}" for r, e in inv["relatorios"].items() for g in e.get("gates") or []
                if not real[r].get(nome_gate.get(g, g))]
    assert not mentiras, "CNF-15: gate declarado que o código não chama:" + _lista(mentiras)


# ───────────────────────────── CST-04: detector registrado ─────────────────────────────

def test_detector_e_funcao_intel_no_registro_de_detectores():
    if not DETECTORES_YAML.exists():
        pytest.fail("CST-04: config/qualidade_detectores.yaml ainda não existe — o registro de detectores é "
                    "pré-requisito desta catraca (outro autor).")
    texto = DETECTORES_YAML.read_text(encoding="utf-8")
    faltam = [n for n in I.detectores_registro() + I.funcoes_intel() if not re.search(rf"\b{re.escape(n)}\b", texto)]
    assert not faltam, "CST-04/CST-11: detector ou função intel servida sem entrada no registro:" + _lista(faltam)


# ───────────────────────────── PROVAS (COR-15): a catraca fica vermelha ─────────────────────────────

def _repo_sintetico(tmp_path: Path, rotas_yaml: dict, extra: str = "") -> tuple[Path, Path]:
    (tmp_path / "rotas").mkdir()
    (tmp_path / "rotas" / "x.py").write_text(
        'from fastapi import APIRouter\nrouter = APIRouter()\n\n\n@router.get("/api/x/velha")\ndef velha():\n'
        '    """Afirma algo velho."""\n' + extra, encoding="utf-8")
    inv = {"rotas": rotas_yaml, "manchetes": [], "abas": {}, "relatorios": {}, "dados_painel": {}}
    arq = tmp_path / "inv.yaml"
    arq.write_text(yaml.safe_dump(inv, allow_unicode=True), encoding="utf-8")
    return tmp_path, arq


def test_prova_rota_nova_sem_entrada_e_acusada(tmp_path):
    repo, arq = _repo_sintetico(
        tmp_path, {"/api/x/velha": {"classe": "afirma", "afirma": "algo", "fonte": "t"}},
        extra='\n\n@router.post("/api/x/nova")\ndef nova():\n    return {}\n')
    c = I.confrontar(repo, arq)
    assert c["sem_entrada"]["rotas"] == ["/api/x/nova"]
    assert c["contagens"]["rotas"] == 2


def test_prova_entrada_morta_e_acusada(tmp_path):
    repo, arq = _repo_sintetico(tmp_path, {"/api/x/velha": {"classe": "afirma", "afirma": "a", "fonte": "t"},
                                           "/api/x/sumiu": {"classe": "afirma", "afirma": "b", "fonte": "t"}})
    c = I.confrontar(repo, arq)
    assert c["entrada_morta"]["rotas"] == ["/api/x/sumiu"]
    assert not c["sem_entrada"]["rotas"]


def test_prova_rota_incompleta_e_fonte_a_declarar(tmp_path):
    repo, arq = _repo_sintetico(tmp_path, {"/api/x/velha": {"classe": "afirma", "afirma": "", "fonte": "A DECLARAR"}})
    c = I.confrontar(repo, arq)
    assert c["incompletas"]["rotas"] == ["/api/x/velha"]
    assert c["fonte_a_declarar"] == ["/api/x/velha"]
    assert catraca.cresceu(I.fonte_a_declarar(I.carregar(arq)), {})  # base vazia ⇒ vermelho


def test_prova_relatorio_sem_neutro_e_gerador_inexistente(tmp_path):
    repo, arq = _repo_sintetico(tmp_path, {"/api/x/velha": {"classe": "afirma", "afirma": "a", "fonte": "t"}})
    (repo / "rel.py").write_text("def gerar():\n    return render_html({})\n", encoding="utf-8")
    inv = I.carregar(arq)
    inv["relatorios"] = {"novo": {"fonte_codigo": "rel.py", "gates": ["render_html"]}}
    inv["dados_painel"] = {"data/x.json": {"gerador": "tools/nao_existe.py", "rota": "/api/x/velha"},
                           "data/y.json": {"gerador": "A DECLARAR", "rota": "/api/x/velha"}}
    arq.write_text(yaml.safe_dump(inv, allow_unicode=True), encoding="utf-8")
    c = I.confrontar(repo, arq)
    assert c["relatorio_sem_neutro"] == ["novo"]
    assert c["sem_gerador"] == {"data/x.json": "gerador inexistente: tools/nao_existe.py", "data/y.json": "A DECLARAR"}


def test_prova_card_sem_manchete(tmp_path):
    repo, arq = _repo_sintetico(tmp_path, {"/api/x/velha": {"classe": "afirma", "afirma": "a", "fonte": "t"}})
    (repo / "static/js/src/abas").mkdir(parents=True)
    (repo / I.COCKPIT).write_text("g.innerHTML=[ckCard('novo','Novo','','bgteal','g_x')].join('');", encoding="utf-8")
    assert I.confrontar(repo, arq)["sem_entrada"]["manchetes"] == ["cki-novo"]
