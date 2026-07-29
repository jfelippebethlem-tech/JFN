# -*- coding: utf-8 -*-
"""A fase de EXECUÇÃO existia no papel e nunca rodou sobre a base.

`detectores.rodar_execucao` orquestra X1–X6 (crescimento de aditivo, prorrogação perpétua,
execução financeira, carona, jogo de planilha, entrega fantasma). Os seis estão implementados e
testados desde sempre — e não tinham **nenhum chamador de produção**: `varredura_certames`
cobre E/J/P, `varredura_orgaos` cobre J1/P3/C6/C, `coletor_edital` para no julgamento. Resultado
medido em 2026-07-29: `achado_detector` com **zero** linhas de detector X.

Este módulo liga a fase de execução ao dado que a casa já tem — `pcrj_contratos` (54.624, com
`valor_inicial` e `valor_global`) e `contrato_aditivo` (1.728, com `valor_acrescido`,
`prazo_aditado_dias`, `vigencia_fim` e `objeto`).

Os testes abaixo travam sobretudo a HONESTIDADE da montagem do contexto, porque é onde a família
aditivo erra: prorrogação classificada como acréscimo de valor é o falso positivo clássico —
o PNCP grava o período renovado em `valorAcrescido` e `qualif_acrescimo` vem '1' para quase tudo
(medido em `contratos/thoughts`, caso AVANTY +R$ 51 mi que era renovação de 12 meses).
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.varredura_execucao import (
    DETECTORES_EXECUCAO,
    contratos_com_aditivo,
    varrer_contrato,
)
from compliance_agent.varredura_execucao_ctx import montar_contexto

_PNCP = "00000000000191-2-000123/2024"


@pytest.fixture()
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE pcrj_contratos (
            numero_controle_pncp TEXT, ano INT, orgao_cnpj TEXT, orgao_nome TEXT, unidade TEXT,
            fornecedor_documento TEXT, fornecedor_nome TEXT, tipo TEXT, objeto TEXT,
            valor_inicial REAL, valor_global REAL, data_assinatura TEXT,
            vigencia_ini TEXT, vigencia_fim TEXT, num_aditivos INT);
        CREATE TABLE contrato_aditivo (
            id INTEGER PRIMARY KEY, numero_controle_pncp TEXT, sequencial_termo INT,
            numero_termo TEXT, objeto TEXT, valor_acrescido REAL, valor_global REAL,
            prazo_aditado_dias INT, vigencia_fim TEXT, qualif_acrescimo TEXT,
            qualif_vigencia TEXT, qualif_reajuste TEXT, fundamento_legal TEXT);
    """)
    return c


def _contrato(con, **kw):
    d = {"numero_controle_pncp": _PNCP, "ano": 2024, "orgao_cnpj": "00000000000191",
         "orgao_nome": "Secretaria X", "unidade": "SEC", "fornecedor_documento": "11222333000181",
         "fornecedor_nome": "Alfa Ltda", "tipo": "Contrato",
         "objeto": "prestação de serviços de limpeza predial", "valor_inicial": 1_000_000.0,
         "valor_global": 1_000_000.0, "data_assinatura": "2024-01-10",
         "vigencia_ini": "2024-01-15", "vigencia_fim": "2025-01-14", "num_aditivos": 0}
    d.update(kw)
    con.execute(f"INSERT INTO pcrj_contratos VALUES ({','.join('?' * len(d))})", tuple(d.values()))
    con.commit()


def _aditivo(con, **kw):
    d = {"id": None, "numero_controle_pncp": _PNCP, "sequencial_termo": 1, "numero_termo": "1",
         "objeto": "", "valor_acrescido": 0.0, "valor_global": 1_000_000.0,
         "prazo_aditado_dias": 0, "vigencia_fim": "", "qualif_acrescimo": "1",
         # fundamento em branco por padrão: ele DECIDE antes do qualificador (art. 124 =
         # reequilíbrio, art. 125 = acréscimo), então deixá-lo preenchido no fixture mascararia
         # justamente o caminho do qualificador que alguns testes querem exercitar.
         "qualif_vigencia": "0", "qualif_reajuste": "0", "fundamento_legal": ""}
    d.update(kw)
    con.execute(f"INSERT INTO contrato_aditivo VALUES ({','.join('?' * len(d))})", tuple(d.values()))
    con.commit()


# ───────────────────────── natureza do aditivo: o falso positivo da família ────────────────────

def test_prorrogacao_nao_vira_acrescimo_de_valor(con):
    """O PNCP grava o período renovado em `valorAcrescido` e `qualif_acrescimo` vem '1'.

    Quem discrimina é o OBJETO. Sem isso, uma renovação de 12 meses entra no teto do art. 125
    como se fosse acréscimo quantitativo — foi exatamente o caso AVANTY (+R$ 51 mi).
    """
    _contrato(con)
    _aditivo(con, objeto="prorrogação do prazo de vigência por 12 meses",
             valor_acrescido=500_000.0, prazo_aditado_dias=365, qualif_acrescimo="1")
    ctx = montar_contexto(con, _PNCP)
    tipos = [a["tipo"] for a in ctx["aditivos"]]
    assert tipos == ["prazo"], f"prorrogação classificada como {tipos}"
    assert ctx["aditivos"][0]["valor"] is None, "aditivo de prazo não pode carregar valor"


def test_reajuste_nao_entra_no_teto(con):
    _contrato(con)
    _aditivo(con, objeto="reajuste contratual pelo IPCA", valor_acrescido=80_000.0,
             qualif_reajuste="1")
    ctx = montar_contexto(con, _PNCP)
    assert ctx["aditivos"][0]["tipo"] == "reajuste"


def test_acrescimo_de_valor_e_reconhecido(con):
    _contrato(con)
    _aditivo(con, objeto="acréscimo de 20% no quantitativo de postos", valor_acrescido=200_000.0)
    ctx = montar_contexto(con, _PNCP)
    a = ctx["aditivos"][0]
    assert a["tipo"] == "valor" and a["valor"] == pytest.approx(200_000.0)


def test_supressao_vem_negativa(con):
    """Art. 125 computa acréscimo e supressão SEPARADAMENTE — quem separa é o X1."""
    _contrato(con)
    _aditivo(con, objeto="supressão de itens do contrato", valor_acrescido=150_000.0)
    ctx = montar_contexto(con, _PNCP)
    assert ctx["aditivos"][0]["valor"] == pytest.approx(-150_000.0)


def test_objeto_mudo_cai_no_qualificador_e_declara_a_fonte(con):
    """Sem texto no objeto, o qualificador do PNCP é o que resta — e a origem fica registrada."""
    _contrato(con)
    _aditivo(con, objeto="", valor_acrescido=300_000.0, qualif_acrescimo="1")
    a = montar_contexto(con, _PNCP)["aditivos"][0]
    assert a["tipo"] == "valor"
    assert a["origem_tipo"] == "qualificador_pncp"


def test_objeto_com_texto_prevalece_sobre_o_qualificador(con):
    _contrato(con)
    _aditivo(con, objeto="prorrogação de vigência", valor_acrescido=300_000.0,
             qualif_acrescimo="1")
    a = montar_contexto(con, _PNCP)["aditivos"][0]
    assert a["tipo"] == "prazo" and a["origem_tipo"] == "objeto"


# ───────────────────── reequilíbrio × acréscimo: achado real da 1ª varredura ──────────────────
# Os textos abaixo são VERBATIM de `contrato_aditivo` (contrato 30051023000196-2-000348/2024,
# MPRJ, auxílio alimentação). A primeira varredura sobre a base real produziu ali um X1
# 'confirmado' com score 1.0 — estouro crítico do art. 125 — somando R$ 40,6 mi que são
# REVISÃO de valores com fundamento expresso no art. 124, II, "d": reequilíbrio econômico-
# financeiro, que por definição NÃO consome o teto de acréscimo. O achado era fabricado.

_REVISAO = (
    'Constitui objeto do presente instrumento a revisão, a contar de 01/06/2025, dos valores '
    'vigentes do benefício individual do beneficiário "I (Membros/Servidores/Voluntários)" do '
    'auxílio alimentação e refeição do Contrato nº 82/2024, referente a prestação de serviços '
    'de emissão e entrega de cartões eletrônicos'
)
_MISTO = (
    'Constitui objeto do presente instrumento as seguintes alterações contratuais: a) revisão, '
    'a contar de 1º de fevereiro de 2026, dos valores vigentes do benefício individual do '
    'beneficiário "I (Membros/Servidores/Voluntários)" do auxílio alimentação e refeição do '
    'Contrato nº 82/2024, com fundamento no art. 124, II, "d" da Lei nº 14.133/21, conforme '
    'processo nº 301295-9/2025; b) acréscimo quantitativo de 25% do valor do contrato'
)


def test_revisao_de_valores_nao_entra_no_teto(con):
    """Revisão do art. 124, II, 'd' é reequilíbrio — recompõe, não aumenta escopo."""
    _contrato(con)
    _aditivo(con, objeto=_REVISAO, valor_acrescido=40_656_773.0, qualif_acrescimo="1")
    a = montar_contexto(con, _PNCP)["aditivos"][0]
    assert a["tipo"] == "reajuste", f"revisão classificada como {a['tipo']}"
    assert a["origem_tipo"] == "objeto"


def test_aditivo_misto_nao_e_chutado_para_nenhum_lado(con):
    """Um termo que faz revisão E acréscimo traz UM valor só, que cobre os dois.

    Contá-lo inteiro como acréscimo infla o percentual do art. 125; contá-lo como zero esconde um
    acréscimo real. Sem a memória de cálculo não dá para repartir — então o termo é declarado
    `misto`, fica fora do cálculo do teto e a lacuna aparece na cobertura. Declarar é honesto;
    escolher um dos dois lados seria inventar.
    """
    _contrato(con)
    _aditivo(con, objeto=_MISTO, valor_acrescido=9_953_842.34, qualif_acrescimo="1")
    ctx = montar_contexto(con, _PNCP)
    a = ctx["aditivos"][0]
    assert a["tipo"] == "misto"
    assert a["valor"] is None, "valor misto não pode entrar no teto do art. 125"
    assert "aditivo_misto" in ctx["lacunas"]


def test_reequilibrio_por_fundamento_legal_tambem_conta(con):
    """Quando o objeto é mudo mas o fundamento cita o art. 124, o fundamento decide."""
    _contrato(con)
    _aditivo(con, objeto="alteração contratual", valor_acrescido=100_000.0,
             fundamento_legal='art. 124, II, "d" da Lei 14.133/2021')
    a = montar_contexto(con, _PNCP)["aditivos"][0]
    assert a["tipo"] == "reajuste"


def test_aporte_e_acrescimo_de_valor(con):
    """'Formalizar o aporte ao Contrato' aparece 3× na base e não estava no vocabulário."""
    _contrato(con)
    _aditivo(con, objeto="Formalizar o aporte ao Contrato nº 2419892, em razão da "
                         "obrigatoriedade do pagamento da assistência financeira",
             valor_acrescido=625_267.44)
    a = montar_contexto(con, _PNCP)["aditivos"][0]
    assert a["tipo"] == "valor" and a["valor"] == pytest.approx(625_267.44)


def test_sub_rogacao_e_retificacao_nao_sao_acrescimo(con):
    """Termo que só troca a contratante ou corrige erro material não mexe em valor."""
    _contrato(con)
    _aditivo(con, sequencial_termo=1,
             objeto="O objeto do presente Termo Aditivo é a sub-rogação total com vistas à "
                    "transferência da CONTRATANTE", valor_acrescido=0.0)
    _aditivo(con, sequencial_termo=2,
             objeto="Adequação, face erro material, do Quadro de Alterações de Itens",
             valor_acrescido=0.0)
    tipos = [a["tipo"] for a in montar_contexto(con, _PNCP)["aditivos"]]
    assert tipos == ["outro", "outro"], tipos


def test_indeterminado_com_valor_entra_na_lacuna_e_nao_no_teto(con):
    """65% dos aditivos da base não tinham tipo. Se carregam valor, isso é lacuna DECLARADA."""
    _contrato(con)
    _aditivo(con, objeto="texto que não diz o que é", valor_acrescido=500_000.0,
             qualif_acrescimo="0")
    ctx = montar_contexto(con, _PNCP)
    assert ctx["aditivos"][0]["tipo"] == ""
    assert ctx["aditivos"][0]["valor"] is None
    assert "aditivo_sem_natureza" in ctx["lacunas"]


# ───────────────────────── INDISPONÍVEL ≠ 0 ───────────────────────────────────────────────────

def test_valor_inicial_zero_e_ausencia_nao_zero(con):
    """Denominador do art. 125 igual a zero produziria percentual infinito — e acusação falsa."""
    _contrato(con, valor_inicial=0.0)
    _aditivo(con, objeto="acréscimo", valor_acrescido=100.0)
    ctx = montar_contexto(con, _PNCP)
    assert ctx["valor_inicial"] is None
    assert "valor_inicial" in ctx["lacunas"]


def test_contrato_sem_aditivo_declara_cobertura_e_nao_inventa(con):
    _contrato(con)
    ctx = montar_contexto(con, _PNCP)
    assert ctx["aditivos"] == []
    assert ctx["n_aditivos"] == 0


def test_contrato_inexistente_devolve_contexto_vazio_honesto(con):
    ctx = montar_contexto(con, "nao-existe")
    assert ctx["valor_inicial"] is None and ctx["aditivos"] == []
    assert "contrato" in ctx["lacunas"]


# ───────────────────────── prorrogação (X2) ───────────────────────────────────────────────────

def test_prorrogacoes_alimentam_o_x2(con):
    _contrato(con)
    _aditivo(con, sequencial_termo=1, objeto="prorrogação de vigência", prazo_aditado_dias=365,
             vigencia_fim="2026-01-14")
    _aditivo(con, sequencial_termo=2, objeto="segunda prorrogação", prazo_aditado_dias=365,
             vigencia_fim="2027-01-14")
    ctx = montar_contexto(con, _PNCP)
    assert len(ctx["prorrogacoes"]) == 2
    assert ctx["vigencia_fim_atual"] == "2027-01-14"
    assert all(p["pesquisa_vantajosidade"] is None for p in ctx["prorrogacoes"]), \
        "vantajosidade não consta da base — INDISPONÍVEL, nunca 'ausente'"


def test_vigencia_atual_e_a_data_MAXIMA_nao_a_ultima_linha(con):
    """Aditivo posterior pode trazer data anterior (retificação, termo fora de ordem).

    Pegar "o último da lista" fazia a vigência ENCURTAR — e encurtar vigência faz o X2 subestimar
    a perpetuidade. A data que vale é a maior, e a ordem das linhas não é garantia de nada.
    """
    _contrato(con)
    _aditivo(con, sequencial_termo=1, objeto="prorrogação", prazo_aditado_dias=730,
             vigencia_fim="2027-01-14")
    _aditivo(con, sequencial_termo=2, objeto="prorrogação retificadora", prazo_aditado_dias=30,
             vigencia_fim="2025-02-14")
    assert montar_contexto(con, _PNCP)["vigencia_fim_atual"] == "2027-01-14"


def test_vigencia_original_prevalece_se_nenhum_aditivo_a_estende(con):
    _contrato(con, vigencia_fim="2030-01-01")
    _aditivo(con, objeto="prorrogação", prazo_aditado_dias=30, vigencia_fim="2025-02-14")
    assert montar_contexto(con, _PNCP)["vigencia_fim_atual"] == "2030-01-01"


# ───────────────────────── tipo de objeto (teto 25% × 50%) ────────────────────────────────────

@pytest.mark.parametrize("objeto,esperado", [
    ("reforma do edifício sede", "reforma"),
    ("reforma de equipamento hospitalar", "reforma"),
    ("prestação de serviços de limpeza predial", None),
])
def test_tipo_objeto_define_o_teto(con, objeto, esperado):
    _contrato(con, objeto=objeto)
    assert montar_contexto(con, _PNCP)["tipo_objeto"] == esperado


# ───────────────────────── a varredura ────────────────────────────────────────────────────────

def test_so_roda_detectores_que_a_base_alimenta():
    """X3/X4/X5/X6 pedem pagamento por contrato, itens de ARP e planilha orçamentária — nada
    disso existe nestas tabelas. Rodá-los produziria `nao_avaliavel` em massa, que esconde a
    cobertura real em vez de revelá-la (mesma regra de `varredura_certames`).

    X7 entra porque três dos seus cinco testes (dupla correção, magnitude, reiteração) rodam só
    com data e valor do termo, que a base tem; os outros dois viram lacuna declarada."""
    assert DETECTORES_EXECUCAO == ("X1", "X2", "X7")


def test_varrer_contrato_devolve_achados_e_cobertura(con):
    _contrato(con, valor_inicial=1_000_000.0)
    _aditivo(con, objeto="acréscimo de quantitativo", valor_acrescido=400_000.0)
    r = varrer_contrato(con, _PNCP)
    assert r["contrato"] == _PNCP
    assert r["n_detectores"] == len(DETECTORES_EXECUCAO)
    assert r["n_avaliaveis"] >= 1
    assert "n_nao_avaliaveis" in r and "score_max" in r


def test_estouro_do_teto_do_art_125_e_confirmado(con):
    """40% de acréscimo sobre serviço comum estoura o teto de 25%."""
    _contrato(con, valor_inicial=1_000_000.0)
    _aditivo(con, objeto="acréscimo de quantitativo de postos", valor_acrescido=400_000.0)
    r = varrer_contrato(con, _PNCP)
    x1 = [a for a in r["achados"] if a.detector == "X1"]
    assert x1, f"X1 não confirmou estouro de 40%: {[(a.detector, a.status) for a in r['todos']]}"


def test_acrescimo_dentro_do_teto_nao_vira_achado(con):
    _contrato(con, valor_inicial=1_000_000.0)
    _aditivo(con, objeto="acréscimo de quantitativo", valor_acrescido=50_000.0)  # 5%
    r = varrer_contrato(con, _PNCP)
    assert not [a for a in r["achados"] if a.detector == "X1"]


def test_detector_que_quebra_nao_derruba_a_varredura(con, monkeypatch):
    _contrato(con)
    from compliance_agent import detectores as D

    class Explode:
        id = "X1"

        def avaliar(self, _ctx):
            raise RuntimeError("boom")

    monkeypatch.setitem(D.REGISTRO, "X1", Explode())
    r = varrer_contrato(con, _PNCP)
    assert r["n_detectores"] >= 1  # X2 seguiu


def test_fila_prioriza_por_valor(con):
    _contrato(con, numero_controle_pncp="a", valor_global=10.0, num_aditivos=1)
    _contrato(con, numero_controle_pncp="b", valor_global=1_000_000.0, num_aditivos=1)
    _aditivo(con, numero_controle_pncp="a", objeto="acréscimo")
    _aditivo(con, numero_controle_pncp="b", objeto="acréscimo")
    assert contratos_com_aditivo(con)[0] == "b", "quem fiscaliza começa pelo que pesa"
