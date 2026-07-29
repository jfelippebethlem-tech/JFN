# -*- coding: utf-8 -*-
"""A virada de natureza — e as duas afirmações que ela NÃO pode fazer.

A régua da casa já dizia em prosa que vencedor + sinal societário muda a peça, e `escalada`
já aceitava o gatilho. Faltava quem produzisse o gatilho: alguém tinha de olhar o vencedor,
olhar as perdedoras e dizer se há caminho entre eles.

As duas armadilhas que estes testes travam:

  · **Vínculo sozinho não é direcionamento.** Sem achado de restritividade, empresas ligadas
    entre si indicam competição aparente — que é problema de outra natureza, com outra peça.
  · **Ausência de caminho não é lisura.** Perdedora sem QSA conhecido não gera vínculo, e o
    resultado tem de dizer isso em vez de devolver um "nada consta" que parece atestado.
"""
from __future__ import annotations

from compliance_agent.osint.direcionamento_consumado import avaliar, montar_grafo

_SOCIO = {"cpf": "123.456.789-00", "nome": "João da Silva", "desde": "2019-03-11"}
VENC = {"cnpj": "11.222.333/0001-81", "nome": "Alfa Ltda", "socios": [_SOCIO]}
PERD_LIGADA = {"cnpj": "44.555.666/0001-72", "nome": "Beta Ltda", "socios": [_SOCIO]}
PERD_SOLTA = {"cnpj": "77.888.999/0001-63", "nome": "Gama Ltda",
              "socios": [{"cpf": "987.654.321-00", "nome": "Maria Souza"}]}
PERD_SEM_DADO = {"cnpj": "10.101.101/0001-10", "nome": "Delta Ltda"}


# ───────────────────────── a virada ───────────────────────────────────────────────────────────

def test_restritividade_mais_vinculo_e_direcionamento_consumado():
    r = avaliar(VENC, [PERD_LIGADA, PERD_SOLTA], clausula_restritiva=True)
    assert r["veredito"] == "direcionamento_consumado"
    assert r["peca_sugerida"] == "representacao"
    assert r["gatilho_escalada"]["vinculo_societario_vencedor"] is True
    assert "competição era aparente" in r["resumo"]


def test_vinculo_SEM_restritividade_nao_e_direcionamento():
    """Empresas ligadas entre si é concentração/competição aparente — outra peça, outro problema."""
    r = avaliar(VENC, [PERD_LIGADA], clausula_restritiva=False)
    assert r["veredito"] == "competicao_aparente"
    assert r["peca_sugerida"] == "diligencia"
    assert r["gatilho_escalada"]["vinculo_societario_vencedor"] is False


def test_o_caminho_sai_explicitado_com_fonte():
    r = avaliar(VENC, [PERD_LIGADA], clausula_restritiva=True)
    lig = r["ligadas"][0]
    assert lig["saltos"] == 2 and lig["forca"] > 0.8
    assert "João da Silva" in lig["narrativa"] and "QSA" in lig["narrativa"]


# ───────────────────────── ausência não é lisura ──────────────────────────────────────────────

def test_sem_vinculo_o_resultado_nao_atesta_lisura():
    r = avaliar(VENC, [PERD_SOLTA], clausula_restritiva=True)
    assert r["veredito"] == "sem_vinculo_apurado"
    assert "não prova lisura" in r["resumo"]


def test_perdedora_sem_dado_entra_na_cobertura_nao_no_veredito():
    r = avaliar(VENC, [PERD_SEM_DADO, PERD_SOLTA], clausula_restritiva=True)
    assert r["cobertura"]["sem_dado"] == 1 and r["cobertura"]["com_dado"] == 1
    assert "lacuna de captura" in r["resumo"]


def test_cobertura_e_sempre_declarada():
    r = avaliar(VENC, [PERD_LIGADA, PERD_SOLTA, PERD_SEM_DADO], clausula_restritiva=True)
    c = r["cobertura"]
    assert c["perdedoras"] == 3 and c["com_dado"] + c["sem_dado"] == 3
    assert 0 < c["frac_coberta"] <= 1


# ───────────────────────── os falsos positivos conhecidos ─────────────────────────────────────

def test_predio_compartilhado_nao_liga_vencedor_a_perdedora():
    """'Rua da Assembleia 10' tem 318 CNPJs — prédio não é vínculo."""
    v = {**VENC, "socios": [], "endereco": {"logradouro": "Rua da Assembleia, 10"}}
    p = {**PERD_SOLTA, "socios": [], "endereco": {"logradouro": "Rua da Assembleia, 10"}}
    assert avaliar(v, [p], clausula_restritiva=True)["veredito"] == "sem_vinculo_apurado"


def test_mesma_SALA_liga():
    v = {**VENC, "socios": [],
         "endereco": {"logradouro": "Rua da Assembleia, 10", "complemento": "sala 1203"}}
    p = {**PERD_SOLTA, "socios": [],
         "endereco": {"logradouro": "Rua da Assembleia, 10", "complemento": "sala 1203"}}
    assert avaliar(v, [p], clausula_restritiva=True)["veredito"] == "direcionamento_consumado"


def test_socio_sem_CPF_liga_apenas_por_nome_e_nao_basta():
    """Homonímia não identifica pessoa — a aresta existe para aparecer, não para pesar."""
    s = {"nome": "João da Silva"}
    v = {**VENC, "socios": [s]}
    p = {**PERD_SOLTA, "socios": [s]}
    assert avaliar(v, [p], clausula_restritiva=True)["veredito"] == "sem_vinculo_apurado"


def test_mesmo_IP_liga():
    v = {**VENC, "socios": [], "ip": "200.1.2.3"}
    p = {**PERD_SOLTA, "socios": [], "ip": "200.1.2.3"}
    assert avaliar(v, [p], clausula_restritiva=True)["veredito"] == "direcionamento_consumado"


def test_contador_comum_isolado_nao_basta_no_piso_padrao():
    """Mercado regional concentra contabilidade — guard já validado no P2."""
    v = {**VENC, "socios": [], "contador_crc": "CRC-RJ 12345"}
    p = {**PERD_SOLTA, "socios": [], "contador_crc": "CRC-RJ 12345"}
    assert avaliar(v, [p], clausula_restritiva=True)["veredito"] == "sem_vinculo_apurado"
    frouxo = avaliar(v, [p], clausula_restritiva=True, forca_minima=0.2)
    assert frouxo["veredito"] == "direcionamento_consumado"


# ───────────────────────── robustez ───────────────────────────────────────────────────────────

def test_sem_perdedores_nao_quebra():
    r = avaliar(VENC, [], clausula_restritiva=True)
    assert r["veredito"] == "sem_vinculo_apurado" and r["cobertura"]["perdedoras"] == 0


def test_entrada_suja_nao_quebra():
    r = avaliar(VENC, [None, "lixo", {}], clausula_restritiva=True)
    assert r["veredito"] == "sem_vinculo_apurado"


def test_grafo_pode_ser_inspecionado_a_parte():
    g = montar_grafo(VENC, [PERD_LIGADA])
    assert g.arestas and all(a.fonte for a in g.arestas)


def test_resultado_sempre_traz_ressalva():
    assert "INDÍCIO" in avaliar(VENC, [PERD_LIGADA], clausula_restritiva=True)["ressalva"]
