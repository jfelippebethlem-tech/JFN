# -*- coding: utf-8 -*-
"""Grafo de vínculos — e as três formas de ele virar ruído inútil.

Ligar tudo a tudo produz o grafo em que qualquer empresa alcança qualquer outra em dois saltos.
Os testes abaixo travam as decisões que impedem isso, todas vindas de erro já medido na casa:

  1. **Prédio não é sala.** "RUA DA ASSEMBLEIA 10" tem 318 CNPJs; por SALA, o mesmo acervo dá
     grupos que significam alguma coisa. A aresta de prédio existe para aparecer, não para pesar.
  2. **Nome não é pessoa.** Homonímia já custou correção; nome sem documento entra com força 0,10
     e declarado, nunca como identidade.
  3. **A cadeia vale o elo mais fraco.** A força do caminho é o PRODUTO — dois saltos por sócio
     comum valem mais que um salto por prédio compartilhado, e é assim que tem de ser quando se
     vai afirmar vínculo numa peça.
"""
from __future__ import annotations

import pytest

from compliance_agent.osint.vinculos import (
    TIPOS_ARESTA,
    GrafoVinculos,
    classificar_endereco,
    mascarar_cpf,
    no_pf,
    no_pj,
)

VENCEDORA = no_pj("11.222.333/0001-81", "Alfa Ltda")
PERDEDORA = no_pj("44.555.666/0001-72", "Beta Ltda")
SOCIO = no_pf("123.456.789-00", "João da Silva")


# ───────────────────────────── vocabulário fechado ────────────────────────────────────────────

def test_tipo_de_aresta_desconhecido_e_recusado():
    g = GrafoVinculos()
    assert g.ligar(VENCEDORA, PERDEDORA, "amizade", fonte="x") is None
    assert g.arestas == []


def test_aresta_sem_fonte_e_recusada():
    """Aresta que não pode entrar em peça não deveria existir no grafo."""
    g = GrafoVinculos()
    assert g.ligar(VENCEDORA, SOCIO, "socio_de", fonte="") is None


def test_toda_aresta_forte_declara_a_explicacao_inocente():
    """Presunção de legitimidade: o elo forte precisa vir com a hipótese lícita ao lado."""
    for t in TIPOS_ARESTA.values():
        if t.forca >= 0.7 and t.id not in ("socio_de", "mesmo_socio", "servidor_de",
                                           "parente_de", "sucessora_de", "mesmo_registrante"):
            assert t.exculpatoria, f"{t.id} forte e sem exculpatória"


# ───────────────────────────── prédio × sala ──────────────────────────────────────────────────

@pytest.mark.parametrize("logradouro,complemento,esperado", [
    ("Rua da Assembleia, 10", "", "mesmo_predio"),
    ("Rua da Assembleia, 10", "sala 1203", "mesma_sala"),
    ("Av. Rio Branco, 156", "conj. 2801", "mesma_sala"),
    ("Av. Rio Branco, 156", "andar 12", "mesma_sala"),
    ("Rua X, 5 - Coworking Central", "", "mesmo_predio"),
])
def test_complemento_distingue_sala_de_predio(logradouro, complemento, esperado):
    assert classificar_endereco(logradouro, complemento)[0] == esperado


def test_predio_sem_complemento_registra_a_ressalva():
    _, obs = classificar_endereco("Rua da Assembleia, 10", "")
    assert any("PRÉDIO" in o for o in obs)


def test_coworking_e_declarado_como_endereco_que_nao_liga():
    _, obs = classificar_endereco("Rua X, 5", "escritório virtual sala 10")
    assert any("não liga" in o for o in obs)


def test_predio_compartilhado_sozinho_nao_sustenta_vinculo():
    g = GrafoVinculos()
    g.ligar_endereco(VENCEDORA, PERDEDORA, logradouro="Rua da Assembleia, 10",
                     fonte="Receita Federal")
    r = g.caminho(VENCEDORA, PERDEDORA, forca_minima=0.5)
    assert r["encontrado"] is False, "prédio compartilhado virou vínculo"


def test_mesma_sala_sustenta():
    g = GrafoVinculos()
    g.ligar_endereco(VENCEDORA, PERDEDORA, logradouro="Rua da Assembleia, 10",
                     complemento="sala 1203", fonte="Receita Federal", data="2026-07-01")
    r = g.caminho(VENCEDORA, PERDEDORA, forca_minima=0.5)
    assert r["encontrado"] is True and r["forca"] >= 0.7


# ───────────────────────────── nome não é pessoa ──────────────────────────────────────────────

def test_nome_sem_documento_e_aresta_fraca_e_declarada():
    g = GrafoVinculos()
    a = g.ligar(VENCEDORA, PERDEDORA, "nome_igual_sem_documento",
                fonte="QSA", detalhe="ambas têm sócio 'João da Silva'")
    assert a.forca <= 0.15
    assert "homonímia" in TIPOS_ARESTA["nome_igual_sem_documento"].exculpatoria


def test_no_de_pessoa_sem_cpf_nao_colide_com_no_documentado():
    assert no_pf("", "João da Silva") != no_pf("123.456.789-00", "João da Silva")


def test_documento_com_ou_sem_pontuacao_e_o_mesmo_no():
    assert no_pj("11.222.333/0001-81") == no_pj("11222333000181")


# ───────────────────────────── o caminho ──────────────────────────────────────────────────────

def _grafo_caso() -> GrafoVinculos:
    g = GrafoVinculos()
    g.rotular(VENCEDORA, "Alfa Ltda")
    g.rotular(PERDEDORA, "Beta Ltda")
    g.rotular(SOCIO, "João da Silva")
    g.ligar(SOCIO, VENCEDORA, "socio_de", fonte="Receita Federal/QSA", data="2019-03-11")
    g.ligar(SOCIO, PERDEDORA, "socio_de", fonte="Receita Federal/QSA", data="2021-08-02")
    return g


def test_caminho_por_socio_comum_e_narrado_com_fonte():
    r = _grafo_caso().caminho(VENCEDORA, PERDEDORA)
    assert r["encontrado"] and r["saltos"] == 2
    assert "João da Silva" in r["narrativa"]
    assert "Receita Federal/QSA" in r["narrativa"]
    assert all(p["fonte"] for p in r["passos"])


def test_caminho_forte_de_dois_saltos_vence_caminho_fraco_de_um():
    """A força é o PRODUTO: o elo fraco enfraquece a cadeia, e é isso que se quer."""
    g = _grafo_caso()
    g.ligar_endereco(VENCEDORA, PERDEDORA, logradouro="Rua da Assembleia, 10",
                     fonte="Receita Federal")
    r = g.caminho(VENCEDORA, PERDEDORA)
    assert r["saltos"] == 2, "o caminho curto e fraco foi preferido ao longo e forte"
    assert r["forca"] > 0.8


def test_sem_caminho_devolve_o_motivo_nao_um_vazio_ambiguo():
    g = GrafoVinculos()
    g.ligar(SOCIO, VENCEDORA, "socio_de", fonte="QSA")
    r = g.caminho(VENCEDORA, PERDEDORA)
    assert r["encontrado"] is False and "nenhum caminho" in r["motivo"]


def test_limite_de_saltos_e_respeitado():
    g = GrafoVinculos()
    cadeia = [no_pj(f"0000000000000{i}") for i in range(6)]
    for a, b in zip(cadeia, cadeia[1:]):
        g.ligar(a, b, "mesmo_socio", fonte="QSA")
    assert g.caminho(cadeia[0], cadeia[-1], max_saltos=2)["encontrado"] is False
    assert g.caminho(cadeia[0], cadeia[-1], max_saltos=5)["encontrado"] is True


def test_o_resultado_traz_a_ressalva_de_indicio():
    r = _grafo_caso().caminho(VENCEDORA, PERDEDORA)
    assert "INDÍCIO" in r["ressalva"]


def test_cada_passo_carrega_a_exculpatoria_do_tipo():
    g = GrafoVinculos()
    g.ligar(VENCEDORA, PERDEDORA, "mesmo_contador", fonte="peças do certame",
            detalhe="CRC 12345")
    r = g.caminho(VENCEDORA, PERDEDORA, forca_minima=0.2)
    assert "mercado regional" in r["passos"][0]["exculpatoria"]


# ───────────────────────────── grupo de fato ──────────────────────────────────────────────────

def test_grupo_reune_so_quem_esta_ligado_por_aresta_forte():
    g = _grafo_caso()
    outra = no_pj("77.888.999/0001-63")
    g.ligar_endereco(VENCEDORA, outra, logradouro="Rua da Assembleia, 10",
                     fonte="Receita Federal")
    grupo = g.grupo(VENCEDORA, forca_minima=0.5)
    assert SOCIO in grupo and PERDEDORA in grupo
    assert outra not in grupo, "vizinho por prédio entrou no grupo econômico"


# ───────────────────────────── LGPD na saída ──────────────────────────────────────────────────

def test_cpf_e_mascarado_na_saida():
    assert mascarar_cpf("sócio CPF 123.456.789-00") == "sócio CPF 123.***.***-00"
    assert mascarar_cpf("CPF 12345678900") == "CPF 123.***.***-00"


def test_mascarar_nao_estraga_cnpj():
    assert "11.222.333/0001-81" in mascarar_cpf("CNPJ 11.222.333/0001-81")
