# -*- coding: utf-8 -*-
"""Vigência da sanção é NA DATA DO FATO, pela régua única `sancao_abrangencia.vigente_em` (O4.11, 24/11/2026).

No snapshot de 24/11/2026, 24.707 das 25.475 sanções têm data_fim nula ou futura. Nula é legítima em "sem prazo
determinado", multa e publicação extraordinária — mas 682 são "COM prazo determinado" sem data final, e o detector
C7 e o `indice_certame` contavam fim nulo como vigente para sempre (cópias divergentes da régua)."""
from __future__ import annotations

import sqlite3

from compliance_agent.detectores.c7_sancionada_contratada import C7SancionadaContratada
from compliance_agent.editais import indice_certame


def _s(categoria, ini="2020-01-01", fim=None):
    return {"cadastro": "CEIS", "categoria": categoria, "data_inicio": ini, "data_fim": fim,
            "orgao": "CGU", "uf": "RJ"}


def test_c7_com_prazo_determinado_sem_fim_nao_e_vigente():
    r = C7SancionadaContratada().avaliar({
        "processo": "X", "data_referencia": "2025-06-10",
        "sancoes": [_s("Impedimento/proibição de contratar com prazo determinado")]})
    assert r.valores["n_vigentes"] == 0 and r.status == "descartado"


def test_c7_sem_prazo_sem_fim_segue_vigente_e_posterior_ao_fato_nao():
    det = C7SancionadaContratada()
    r = det.avaliar({"processo": "X", "data_referencia": "2025-06-10",
                     "sancoes": [_s("Declaração de Inidoneidade sem prazo determinado")]})
    assert r.valores["n_vigentes"] == 1
    r2 = det.avaliar({"processo": "X", "data_referencia": "2019-06-10",
                      "sancoes": [_s("Declaração de Inidoneidade sem prazo determinado")]})
    assert r2.valores["n_vigentes"] == 0           # sanção começou depois do ato


def _con_sancoes(categoria, fim):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE sancoes_federais (cadastro, cpf_cnpj, nome, categoria, data_inicio, data_fim, orgao,"
                " uf, processo, fundamentacao)")
    con.execute("INSERT INTO sancoes_federais VALUES ('CEIS','11111111000111','X',?, '2020-01-01', ?, 'CGU','RJ','','')",
                (categoria, fim))
    con.execute("CREATE TABLE fantasma_score (cnpj, score, classificacao)")
    return con


def _flag(con):
    fam = indice_certame._f_fraude_cadastral(con, {"vencedores": ["11111111000111"], "data_pub": "2025-06-10"})
    return next(f for f in fam["flags"] if f["flag"] == "sancao_vigente_a_epoca")


def test_indice_certame_com_prazo_sem_fim_nao_acende():
    assert _flag(_con_sancoes("Impedimento/proibição de contratar com prazo determinado", None))["valor"] == 0.0


def test_indice_certame_sem_prazo_e_prazo_aberto_acendem():
    assert _flag(_con_sancoes("Declaração de Inidoneidade sem prazo determinado", None))["valor"] == 1.0
    assert _flag(_con_sancoes("Impedimento/proibição de contratar com prazo determinado", "2027-01-01"))["valor"] == 1.0
