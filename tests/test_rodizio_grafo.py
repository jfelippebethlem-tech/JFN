# -*- coding: utf-8 -*-
"""Grafo de rodízio CROSS-ata — motor determinístico + guardas do extrator best-effort.

O motor de grafo é testado com verdade-terreno sintética; o extrator, com os falsos-positivos
REAIS que o corpus revelou (órgão contratante no preâmbulo, CNPJ sem marcador de resultado).
"""
from compliance_agent import rodizio_grafo as RG

A, B, C, D = "11111111000111", "22222222000122", "33333333000133", "44444444000144"


def _reg(certame, vencedor, presentes):
    return {"certame": certame,
            "participantes": [{"cnpj": p, "venceu": (p == vencedor)} for p in presentes]}


# ── motor de grafo (núcleo testável) ─────────────────────────────────────────

def test_cobertura_fantasma_participa_e_nunca_vence():
    regs = [_reg(f"c{i}", A if i % 2 else B, [A, B, C]) for i in range(4)]  # C nunca vence
    p = RG.detectar_padroes(RG.construir_grafo(regs), min_certames=3)
    fantasmas = {c["licitante"] for c in p["cobertura"]}
    assert C in fantasmas and A not in fantasmas and B not in fantasmas
    c = next(x for x in p["cobertura"] if x["licitante"] == C)
    assert c["participou"] == 4 and c["venceu"] == 0


def test_rodizio_par_alterna_vitorias_equilibrio_perfeito():
    regs = [_reg("c1", A, [A, B]), _reg("c2", B, [A, B]),
            _reg("c3", A, [A, B]), _reg("c4", B, [A, B])]
    p = RG.detectar_padroes(RG.construir_grafo(regs), min_juntos=3)
    assert len(p["rodizio"]) == 1
    r = p["rodizio"][0]
    assert sorted(r["par"]) == sorted([A, B]) and r["juntos"] == 4
    assert r["vitorias"] == [2, 2] and r["equilibrio"] == 1.0


def test_roster_trio_que_anda_junto():
    regs = [_reg(f"c{i}", A, [A, B, C]) for i in range(3)]
    p = RG.detectar_padroes(RG.construir_grafo(regs), min_juntos=3)
    assert p["roster"] and p["roster"][0]["tamanho"] == 3
    assert sorted(p["roster"][0]["membros"]) == sorted([A, B, C])


def test_certame_com_um_participante_nao_entra_no_grafo():
    g = RG.construir_grafo([_reg("c1", A, [A])])  # sem disputa
    assert g["n_certames"] == 0 and not g["licitantes"]


def test_concorrencia_saudavel_sem_padrao():
    # 4 vencedores distintos, sem par recorrente → nada
    regs = [_reg("c1", A, [A, B]), _reg("c2", C, [C, D]),
            _reg("c3", B, [B, C]), _reg("c4", D, [D, A])]
    p = RG.detectar_padroes(RG.construir_grafo(regs), min_certames=3, min_juntos=3)
    assert not p["cobertura"] and not p["rodizio"] and not p["roster"]


def test_thresholds_conservadores_nao_disparam_com_amostra_pequena():
    regs = [_reg("c1", A, [A, B, C]), _reg("c2", A, [A, B, C])]  # C perde 2x < min 3
    p = RG.detectar_padroes(RG.construir_grafo(regs), min_certames=3)
    assert not p["cobertura"]


# ── extrator best-effort: guardas contra os FP reais do corpus ───────────────

def test_extrator_exclui_orgao_contratante():
    txt = ("Ata. A empresa 11.111.111/0001-11 foi declarada vencedora. "
           "A licitante 22.222.222/0001-22 foi inabilitada por falta de atestado.")
    ext = RG.extrair_participantes_ata(txt, orgao_cnpj="11.111.111/0001-11")
    ids = {p["cnpj"] for p in ext["participantes"]}
    assert "11111111000111" not in ids and "22222222000122" in ids


def test_extrator_exclui_preambulo_do_contratante():
    # FP real: a Fundação contratante 'neste ato representada' vinha como fantasma perdedor
    txt = ("A FUNDACAO, inscrita no CNPJ 99.999.999/0001-99, neste ato representada por seu diretor, "
           "resolve. A licitante 22.222.222/0001-22 foi inabilitada. A 33.333.333/0001-33 foi vencedora.")
    ext = RG.extrair_participantes_ata(txt)
    ids = {p["cnpj"] for p in ext["participantes"]}
    assert "99999999000199" not in ids
    assert "22222222000122" in ids and "33333333000133" in ids


def test_extrator_ignora_cnpj_sem_marcador_de_resultado():
    txt = ("Contrato firmado. A empresa 55.555.555/0001-55 presta serviço. "
           "A licitante 22.222.222/0001-22 foi inabilitada. A 33.333.333/0001-33 foi vencedora.")
    ext = RG.extrair_participantes_ata(txt)
    ids = {p["cnpj"] for p in ext["participantes"]}
    assert "55555555000155" not in ids  # sem vencedor/perdedor por perto → não é licitante


def test_extrator_classifica_vencedor_e_perdedor_por_proximidade():
    txt = "A 22.222.222/0001-22 foi inabilitada; a 33.333.333/0001-33 foi declarada vencedora."
    ext = RG.extrair_participantes_ata(txt)
    by = {p["cnpj"]: p["venceu"] for p in ext["participantes"]}
    assert by["33333333000133"] is True and by["22222222000122"] is False


def test_pipeline_reporta_cobertura_de_extracao():
    atas = [{"certame": "c1", "texto": "sem cnpj nenhum aqui"},
            {"certame": "c2", "texto": "A 22.222.222/0001-22 inabilitada; a 33.333.333/0001-33 vencedora."}]
    res = RG.analisar_atas(atas)
    assert res["cobertura_extracao"]["atas_entrada"] == 2
    assert res["cobertura_extracao"]["atas_avaliaveis"] == 1
