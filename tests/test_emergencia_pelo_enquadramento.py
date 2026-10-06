# -*- coding: utf-8 -*-
"""Emergência se prova pelo ENQUADRAMENTO LEGAL, não por a palavra aparecer no objeto.

`eh_emergencial` lia só o texto do objeto (`emergenc`). Medido em 2026-08-11 nas 20.113 linhas de
`compras_diretas_tcerj`:

    objeto diz "emergencial" ............................ 1.800
    enquadramento é art. 75, VIII ....................... 1.504
    os DOIS ..............................................  613

Isto é, os critérios mal se sobrepõem. **891 contratações são dispensa emergencial pela lei e o
detector não as via** — R$ 2,60 bi — porque o objeto delas diz *"PEITO DE FRANGO"*, *"CESTA
ALIMENTOS"*, *"AQUISIÇÃO DE MEDICAMENTO DE USO VETERINÁRIO"*. Somando o art. 24, IV da Lei
8.666/93 (o dispositivo equivalente da lei anterior, ainda vivo no acervo em 514 linhas), são
**1.001 contratações e R$ 2,80 bi** fora do alcance da régua.

O caso que revelou isso: a AGILE CORP × SEEDUC teve contratos emergenciais em 2023 sob a Lei
8.666 (art. 24, IV) e em 2024 sob a Lei 14.133 (art. 75, VIII) — a cadeia atravessa a mudança da
lei, e uma régua presa a uma redação vê só metade dela.

O CAMINHO INVERSO CONTINUA VALENDO: 1.187 linhas dizem "emergencial" no objeto sob outro
fundamento (portarias federais, art. 24 de outros incisos). O objeto não deixa de ser sinal —
ele deixa de ser o ÚNICO sinal.
"""
from __future__ import annotations

from compliance_agent.fracionamento_emergencia import agrupar_emergencias, eh_emergencial


def test_objeto_emergencial_continua_valendo():
    assert eh_emergencial("CONTRATAÇÃO EMERGENCIAL DE LIMPEZA") is True
    assert eh_emergencial("AQUISIÇÃO DE CADEIRAS") is False


def test_enquadramento_art_75_VIII_basta_mesmo_com_objeto_banal():
    """O caso literal do acervo: objeto "PEITO DE FRANGO", dispensa emergencial na lei."""
    assert eh_emergencial("PEITO DE FRANGO", "Lei nº 14.133/2021, Art. 75º, VIII") is True
    assert eh_emergencial("PEITO DE FRANGO", "Lei n 14.133/2021, Art. 75, VIII") is True


def test_art_24_IV_da_8666_e_o_mesmo_instituto_na_lei_anterior():
    assert eh_emergencial("COLETA DE RESÍDUOS", "Com base no art.24, inciso IV da Lei 8.666/93") is True


def test_outros_incisos_do_art_75_NAO_sao_emergencia():
    """O inciso II é dispensa por VALOR e tem régua própria (`sweep_fracionamento_tcerj`).
    Confundi-los devolveria a mistura que o módulo existe para desfazer."""
    assert eh_emergencial("MATERIAL DE ESCRITÓRIO", "Lei nº 14.133/2021, Art. 75º, II") is False
    assert eh_emergencial("SERVIÇO TÉCNICO", "Lei n 14.133/2021, Art. 74, I") is False


def test_art_24_de_OUTRO_inciso_nao_entra():
    assert eh_emergencial("COMPRA", "Art. 24, II da Lei 8.666/93") is False


def test_sem_enquadramento_o_comportamento_e_o_de_antes():
    """Chamador antigo, que passa só o objeto, não muda de resultado."""
    assert eh_emergencial("AQUISIÇÃO DE CADEIRAS") is False
    assert eh_emergencial("CONTRATAÇÃO EMERGENCIAL") is True


def test_agrupar_aceita_a_linha_COM_enquadramento():
    linhas = [("SEEDUC", 2024, "AGILE", 100.0, "PEITO DE FRANGO",
               "Lei nº 14.133/2021, Art. 75º, VIII")] * 5
    g = agrupar_emergencias(linhas, minimo=5)
    assert len(g) == 1 and g[0]["n"] == 5


def test_agrupar_aceita_a_linha_SEM_enquadramento(  ):
    """Compatibilidade: o chamador que ainda entrega 5 campos continua funcionando."""
    linhas = [("SEEDUC", 2024, "AGILE", 100.0, "CONTRATAÇÃO EMERGENCIAL")] * 5
    g = agrupar_emergencias(linhas, minimo=5)
    assert len(g) == 1 and g[0]["n"] == 5


def test_agrupar_ignora_o_que_nao_e_emergencia_por_nenhum_dos_dois_criterios():
    linhas = [("SEEDUC", 2024, "X", 100.0, "CADEIRAS", "Lei nº 14.133/2021, Art. 75º, II")] * 9
    assert agrupar_emergencias(linhas, minimo=5) == []


def test_carregar_entrega_UMA_linha_por_processo(tmp_path):
    """`compras_diretas_tcerj` tem uma linha por ITEM, e o campo `valor` repete o TOTAL DO
    PROCESSO em cada uma delas.

    Medido em 2026-08-11: dos 1.486 processos com 2+ linhas, **1.485 têm `valor` idêntico em
    todas**. Somar linha a linha infla o acervo inteiro em **2,30×** — R$ 39,65 bi somados contra
    R$ 17,20 bi reais. No DETRAN/2025 isso virou "6 contratações emergenciais, R$ 148,8 mi" onde
    há **um** processo de R$ 24,8 mi (seis itens de vigilância: armada/desarmada, diurno/noturno,
    supervisor). A aritmética fecha: a soma de `quantidade × valor_unitario` dos seis itens, vezes
    os 6 meses de vigência, dá exatamente o `valor` repetido.

    O sweep IRMÃO já fazia certo — `sweep_fracionamento_tcerj` lê `MAX(valor) ... GROUP BY
    processo`, com o comentário "1 linha por processo". A régua existia numa cópia só.

    É a mesma família do fracionamento que esteve 26× inflado: contar LINHA quando a unidade do
    fenômeno é o PROCESSO.
    """
    import sqlite3

    from tools.sweep_emergencia_recorrente import carregar

    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE compras_diretas_tcerj (processo TEXT, unidade TEXT,"
                " ano_processo INT, fornecedor TEXT, valor REAL, objeto TEXT,"
                " enquadramento_legal TEXT)")
    con.executemany("INSERT INTO compras_diretas_tcerj VALUES (?,?,?,?,?,?,?)", [
        # um processo, seis itens, o TOTAL repetido em cada linha
        ("SEI-1/1/2025", "DETRAN", 2025, "FXX", 24_806_748.42, f"ITEM {i}",
         "Lei n 14.133/2021, Art. 75, VIII") for i in range(6)
    ] + [
        ("SEI-2/2/2025", "DETRAN", 2025, "FXX", 1_000.0, "OUTRO",
         "Lei n 14.133/2021, Art. 75, VIII"),
    ])
    con.commit()
    linhas = carregar(con)
    con.close()
    assert len(linhas) == 2, "seis itens do mesmo processo são UMA contratação"
    assert sum(l[3] for l in linhas) == 24_806_748.42 + 1_000.0
