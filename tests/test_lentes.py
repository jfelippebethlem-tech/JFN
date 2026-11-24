# -*- coding: utf-8 -*-
"""Lentes (O3.3, plano §3.6) e a prioridade única com a lente: config/lentes.yaml conferido contra o índice de UGs do
SIAFE (sigla errada recusa), órgão SEI DERIVADO da coleta (nunca escrito à mão), filtro + bônus, a lente só mexe
DENTRO do degrau de valor (não pula estrato), sem lente a ordem é a do sei_sweep, componentes gravados (explicável),
e o replay de paridade sobre estado gravado (sem navegador)."""
import json
import sqlite3

import pytest

from compliance_agent.aplicacao.estagios import arvore as A
from compliance_agent.fluxo import lentes as L
from compliance_agent.fluxo import prioridade as PR
from compliance_agent.fluxo.prioridade import Sinais

M = 1_000_000.00


def _indice(tmp_path, ugs):
    p = tmp_path / "ug_index.json"
    p.write_text(json.dumps({"atualizado_em": "x", "ugs": ugs}))
    return p


def _yaml(tmp_path, texto):
    p = tmp_path / "lentes.yaml"
    p.write_text(texto, encoding="utf-8")
    return p


_LENTE = """versao: 1
lentes:
  bombeiros:
    filtro: {ug: ['160100', '166100'], orgao_sei: {derivar: siafe, posse_minima: 0.8, minimo_obs: 3}}
    conferir_siafe: {'160100': SEDEC, '166100': FUNESBOM}
    prioridade: 0.2
"""


# ── configuração ─────────────────────────────────────────────────────────────────────────────────────────────
def test_config_real_confere_com_o_indice_do_siafe():
    lentes = L.carregar()
    b = lentes["bombeiros"]
    assert {"160100", "166100"} <= b.ugs and b.prioridade == 0.2 and b.regra_orgao["derivar"] == "siafe"


def test_sigla_que_nao_confere_com_o_siafe_e_recusada(tmp_path):
    idx = _indice(tmp_path, {"160100": "SEDEC", "166100": "OUTRO"})
    with pytest.raises(L.ErroLente, match="não confere"):
        L.carregar(_yaml(tmp_path, _LENTE), idx)
    with pytest.raises(L.ErroLente, match="ilegível"):
        L.carregar(_yaml(tmp_path, _LENTE), tmp_path / "nao_existe.json")


def test_orgao_sei_escrito_a_mao_e_recusado(tmp_path):
    idx = _indice(tmp_path, {"160100": "SEDEC", "166100": "FUNESBOM"})
    with pytest.raises(L.ErroLente, match="derivar"):
        L.carregar(_yaml(tmp_path, _LENTE.replace("{derivar: siafe, posse_minima: 0.8, minimo_obs: 3}", "['27']")),
                   idx)


def _fonte():
    f = sqlite3.connect(":memory:")
    f.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob, ug_emitente, data_emissao, status, processo, valor, "
              "exercicio, tipo_ob, finalidade)")
    linhas = ([(f"OB{i}", "166100", "10/04/2026", "Contabilizado", f"SEI-270006/{i:06d}/2026", 10.0 * (i + 1), 2026,
                "", "") for i in range(6)]
              + [("OBX", "999999", "10/04/2026", "Contabilizado", "SEI-270006/000099/2026", 1.0, 2026, "", ""),
                 ("OBY", "300100", "10/01/2025", "Contabilizado", "SEI-080001/000001/2025", 5 * M, 2025, "", ""),
                 ("OBZ", "166100", "10/01/2025", "Contabilizado", "SEI-080001/000002/2025", 7.0, 2025, "", "")]
              + [(f"OBW{i}", "300100", "10/01/2025", "Contabilizado", f"SEI-080001/0001{i:02d}/2025", 1.0, 2025, "", "")
                 for i in range(5)])
    f.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?)", linhas)
    f.execute("CREATE TABLE contratos_tcerj (processo, unidade)")
    f.execute("INSERT INTO contratos_tcerj VALUES ('SEI-270003/000010/2024', 'FUNESBOM - FUNDO ESPECIAL')")
    return f


def _lentes(tmp_path, fonte):
    idx = _indice(tmp_path, {"160100": "SEDEC", "166100": "FUNESBOM", "300100": "OUTRA"})
    res, med = L.resolver(L.carregar(_yaml(tmp_path, _LENTE), idx), fonte)
    return res, med, idx


def test_orgao_sei_derivado_da_posse_nas_obs(tmp_path):
    fonte = _fonte()
    res, med, _ = _lentes(tmp_path, fonte)
    assert res["bombeiros"].orgao_sei == frozenset({"27"})               # 6 das 7 OBs do prefixo 27 (0,857 ≥ 0,8)
    assert med["bombeiros"]["medida"]["27"] == [6, 7, 0.8571] and med["bombeiros"]["medida"]["08"][:2] == [1, 7]
    assert L.derivar_orgao_sei(fonte, {"160100", "166100"}, 0.95, 3)[0] == []    # posse abaixo do limiar: não entra
    assert L.derivar_orgao_sei(fonte, {"160100", "166100"}, 0.8, 8)[0] == []     # poucas OBs: não entra


def test_casa_por_ug_ou_por_orgao_e_bonus(tmp_path):
    res, _, _ = _lentes(tmp_path, _fonte())
    b = res["bombeiros"]
    assert L.casa(b, {"166100"}, "080001/000002/2025") == "ug:166100"
    assert L.casa(b, set(), "270137/000001/2024") == "orgao_sei:27"   # processo que nenhuma OB cita
    assert L.casa(b, {"300100"}, "080001/000001/2025") is None
    assert L.bonus(res, {"166100"}, "x") == (0.2, ["bombeiros"]) and L.bonus(res, set(), "080001/1/2025") == (0.0, [])


# ── prioridade com a lente ───────────────────────────────────────────────────────────────────────────────────
def test_lente_soma_no_degrau_de_valor_e_nao_pula_estrato():
    com = Sinais(ob_paga=4_000.0, bonus_lente=0.2, lente="bombeiros")
    assert PR.chave(com) < PR.chave(Sinais(ob_paga=500_000.0))           # +0,2 ≈ 250× o valor (10^2,4)
    assert PR.chave(Sinais(ob_paga=2 * M)) < PR.chave(com)
    assert PR.chave(Sinais(lacuna_provada=True)) < PR.chave(com)          # lente nunca passa de estrato
    assert PR.chave(Sinais(osint=True)) < PR.chave(Sinais(ob_paga=9e9, bonus_lente=0.2))
    assert PR.inteiro(com) < PR.inteiro(Sinais(ob_paga=500_000.0))


def test_sem_lente_a_ordem_por_valor_e_a_de_antes():
    vals = [0.0, 1.0, 9.99, 10.0, 1e3, 1e6 - 0.01, 1e6, 3.3e8, 1e11]
    assert sorted(vals, key=lambda v: PR.chave(Sinais(ob_paga=v))) == sorted(vals, reverse=True)


def test_explicar_grava_bonus_e_escalar():
    e = PR.explicar(Sinais(ob_paga=1e6, bonus_lente=0.2, lente="bombeiros"))
    assert e["bonus_lente"] == 0.2 and e["escalar_valor"] == pytest.approx(6 / 12 + 0.2, abs=1e-6)
    assert e["sinais"]["lente"] == "bombeiros"


# ── fila e paridade (replay, sem navegador) ──────────────────────────────────────────────────────────────────
def test_fila_filtra_pela_lente_e_explica(tmp_path, monkeypatch):
    fonte = _fonte()
    res, _, idx = _lentes(tmp_path, fonte)
    monkeypatch.setattr(L, "INDICE_UG", idx)
    sel = A.fila(fonte, res, "bombeiros", extras={"legado_sei_sweep": {"SEI-270137/000001/2024"}}, sinais={},
                 fracao_couto=0)
    procs = [it.processo for it, _ in sel]
    assert "080001/000001/2025" not in procs                             # outra UG, outro órgão
    assert {"080001/000002/2025", "270003/000010/2024", "270137/000001/2024"} <= set(procs)
    assert procs[0] == "270006/000005/2026"                              # maior OB paga do 27 (60,00) com bônus
    e = dict((it.processo, ex) for it, ex in sel)
    assert e["270003/000010/2024"]["lente_motivo"] == {"bombeiros": "ug:166100"}   # contrato: UG pela sigla do SIAFE
    assert e["270137/000001/2024"]["fontes"] == ["legado_sei_sweep"]
    geral = A.fila(fonte, res, None, sinais={}, fracao_couto=0)
    assert [it.processo for it, _ in geral][0] == "080001/000001/2025"   # R$ 5 mi sem lente ainda vem antes


def test_paridade_relata_o_que_falta(tmp_path, monkeypatch):
    fonte = _fonte()
    res, _, idx = _lentes(tmp_path, fonte)
    monkeypatch.setattr(L, "INDICE_UG", idx)
    log = tmp_path / "sweep.out"
    log.write_text("[x]   [1/2] SEI-270006/000001/2026 → 12 docs · ficha\n"
                   "[x]   [2/2] SEI-270999/000001/2024 → 3 docs\n"
                   "[x]   [3/3] SEI-080001/000001/2025 → 0 docs\n", encoding="utf-8")
    r = A.paridade(fonte, res, "bombeiros", log, extras={})
    assert r["capturados_sweep_antigo"] == 2 and r["contido"] is False and r["faltando_lista"] == ["270999/000001/2024"]
    r2 = A.paridade(fonte, res, "bombeiros", log, extras={"legado_sei_sweep": {"270999/000001/2024"}})
    assert r2["contido"] and r2["capturados_so_pelo_legado"] == 1
