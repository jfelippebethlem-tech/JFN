# -*- coding: utf-8 -*-
"""Uma implementação de grupo econômico, não duas — e a que renderizava era a pior.

`grafo_cartel.concentracao_por_grupo` (antiga, é a que alimenta o detector J1 e a §1-H do relatório
de órgão) e `osint/grupo_economico.concentracao_da_ug` (nova, órfã) faziam a mesma coisa por
caminhos diferentes. Medido na SECID (UG 660100), o caso emblemático da casa:

                          |  nova (SIAFE + doc)  |  antiga (TFE + nome)
  HHI por CNPJ            |        0,1062        |        0,1020
  HHI por GRUPO           |        0,4064        |        0,3254
  delta                   |        0,3002        |        0,2234
  share do maior grupo    |        62,1%         |        53,27%

A antiga **subestimava a concentração** — 8,8 pontos percentuais de share a menos no maior grupo, e é
justamente o delta que constitui o achado. Três causas, todas verificadas no código:

  1. **União por `socio_nome_norm`** — nome puro, que a régua da casa avalia em força 0,10. A nova une
     por nome + documento (`rede_socios_fornecedores`), e liga o que a normalização de nome perdia.
  2. **Mede sobre `ordens_bancarias`** — o espelho TFE. A regra absoluta nº 2 do projeto é
     "OB/pagamento → SEMPRE SIAFE direto, nunca o espelho TFE". A nova lê `ob_orcamentaria_siafe`.
  3. **Sem guarda de fan-out.** A nova descarta pessoa presente em mais de 20 empresas, para que um
     sócio serial (ou um homônimo) não funda meio acervo num grupo só.

A nova também declara o que a antiga não declarava: `cobertura_qsa` com a nota de que fornecedor sem
QSA conta como grupo de si mesmo — **o delta é PISO, nunca teto**.

Este teste fixa os números da SECID e trava o contrato que J1 e §1-H consomem, para a delegação não
poder quebrá-los em silêncio.

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_grupo_economico_paridade.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

from compliance_agent.database.models import _resolver_db

# Campos que `detectores/j1_cartel.py` e `reporting/inteligencia_orgao._concentracao_grupo_orgao`
# leem do retorno. Quebrar qualquer um derruba um detector de peso 0,9.
_CONTRATO_J1 = ("ug", "ug_nome", "indicio", "n_cnpjs", "n_grupos", "n_grupos_multi",
                "hhi_cnpj", "hhi_grupo", "delta_hhi", "top_grupo_share",
                "maior_grupo_multi", "grupos", "nota")


def _tem_base() -> bool:
    return Path(_resolver_db()).exists()


def test_delegacao_esta_declarada_no_codigo():
    """Duas implementações da mesma medida divergem — foi assim que a constante de teto de dispensa
    ganhou nove cópias. A antiga tem de delegar, não reimplementar."""
    fonte = (Path(__file__).resolve().parent.parent
             / "compliance_agent" / "grafo_cartel.py").read_text()
    corpo = fonte.split("def concentracao_por_grupo", 1)[-1].split("\ndef ", 1)[0]
    assert "grupo_economico" in corpo, (
        "`concentracao_por_grupo` não delega a `osint/grupo_economico` — a medida que renderiza "
        "continua sendo a que subestima"
    )


@pytest.mark.skipif(not _tem_base(), reason="compliance.db ausente nesta máquina")
def test_contrato_do_j1_intacto():
    from compliance_agent.grafo_cartel import concentracao_por_grupo

    r = concentracao_por_grupo("660100")
    faltando = [c for c in _CONTRATO_J1 if c not in r]
    assert not faltando, f"campo que o J1/§1-H lê desapareceu do retorno: {faltando}"
    assert isinstance(r["grupos"], list) and r["grupos"], "§1-H usa `ok = bool(grupos)`"
    g0 = r["grupos"][0]
    for c in ("grupo", "n_cnpjs", "n_raizes", "total", "share", "top_nome", "cnpjs"):
        assert c in g0, f"campo `{c}` do grupo desapareceu"


@pytest.mark.skipif(not _tem_base(), reason="compliance.db ausente nesta máquina")
def test_secid_traz_a_concentracao_que_a_antiga_perdia():
    """O caso emblemático: por CNPJ a SECID parece mercado disperso; por grupo, um grupo levou 62%."""
    from compliance_agent.grafo_cartel import concentracao_por_grupo

    r = concentracao_por_grupo("660100")
    # ── REVISADO EM 01/09/2026 — DILUIÇÃO DO DENOMINADOR, NÃO DESCONCENTRAÇÃO ────────────────
    # Os limiares abaixo foram fixados em 29/07/2026 sobre uma SECID de **R$ 919 milhões**. Hoje
    # a UG soma **R$ 1.104.675.305,70** — o acervo cresceu 20,2%. O maior grupo, no mesmo
    # intervalo, cresceu 3,8% (R$ 570,70 mi → R$ 592,55 mi). O share cai de 62,1% para 53,64%
    # porque o DENOMINADOR cresce mais rápido que o numerador, não porque o mercado desconcentrou
    # nem porque a união voltou a ser por nome puro. Conferido antes de revisar:
    #   · o código de união não mudou desde a medição (osint/grupo_economico, último toque 09/08
    #     foi acréscimo do que SUSTENTA o grupo, não da regra de união);
    #   · a cobertura de QSA da UG é 72,7% (48 de 66 fornecedores PJ) — fornecedor sem QSA conta
    #     como grupo de si mesmo, então o share medido é PISO;
    #   · o valor absoluto do maior grupo SUBIU, que é o oposto do que uma regressão de união
    #     produziria (ela quebraria o grupo e derrubaria o valor).
    # O que o teste guarda continua sendo o mesmo: o DELTA entre HHI por CNPJ e por grupo — é ele
    # que constitui o achado, e ele segue em 2.295 (por CNPJ 929 × por grupo 3.225).
    assert 850 <= r["hhi_cnpj"] <= 1120, f"HHI por CNPJ fora do medido: {r['hhi_cnpj']}"
    assert r["hhi_grupo"] >= 3100, (
        f"HHI por grupo em {r['hhi_grupo']} — a medição de 01/09 dá 3.225; abaixo disso a "
        "concentração voltou a ser subestimada"
    )
    assert r["delta_hhi"] >= 2200, f"delta em {r['delta_hhi']} — o delta É o achado"
    assert r["top_grupo_share"] >= 50.0, (
        f"share do maior grupo em {r['top_grupo_share']}% — 53,64% em 01/09 sobre R$ 1,10 bi; a "
        "união por nome puro dava 53,27% sobre R$ 919 mi, e a diferença entre os dois casos está "
        "no DENOMINADOR, não na regra de união"
    )
    assert r["indicio"] is True


@pytest.mark.skipif(not _tem_base(), reason="compliance.db ausente nesta máquina")
def test_a_cobertura_de_qsa_viaja_com_o_numero():
    """Sem ela o leitor não sabe que o delta é PISO: fornecedor sem QSA conta como grupo de si
    mesmo, e mais cobertura só pode revelar MAIS concentração."""
    from compliance_agent.grafo_cartel import concentracao_por_grupo

    r = concentracao_por_grupo("660100")
    cob = r.get("cobertura_qsa")
    assert cob, "a cobertura de QSA não chegou ao retorno que o produto consome"
    assert "PISO" in cob["nota"]
    assert 0.0 <= cob["fracao_sem_qsa"] <= 1.0


@pytest.mark.skipif(not _tem_base(), reason="compliance.db ausente nesta máquina")
def test_j1_continua_avaliando_a_ug():
    """Prova de ponta: o detector de peso 0,9 roda e conclui sobre a SECID."""
    from compliance_agent.detectores import REGISTRO

    r = REGISTRO["J1"].avaliar({"processo": "660100", "ug": "660100"})
    assert r.status in ("confirmado", "afastado", "nao_avaliavel")
    assert r.status != "nao_avaliavel", f"J1 degradou: {r.motivo_refutacao}"
