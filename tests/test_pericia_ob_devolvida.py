# -*- coding: utf-8 -*-
"""OB devolvida pelo banco não é pagamento na perícia de fornecedor (pente fino 17/11/2026).

A OB devolvida continua 'Contabilizado' no SIAFE; com `status_envio = 'Erro no Pagamento'` a devolução é
integral (`siafe_gd`, 99,5% conferido) e o órgão REEMITE outra OB para a mesma competência. A perícia de
fornecedor (`pericia_sweep._obs_de` → `auditoria_contrato._contabilizadas`) não lia `status_envio`: devolução +
reemissão virava "a MESMA quantia paga 2× na competência" — o T07. O único 🔴 da base (FERREIRAS UP × UG 154100)
era isso: 2025OB00212 (Erro no Pagamento, 2025GD00022) e a reemissão 2025OB00640, R$ 94.999,98 cada, em 02/2025.
Medido (aproximação: mesma quantia ≥ R$ 20 mil 2× na competência): em 910 dos 2.487 pares 🟡/🔴 com T07 o
dobro some ao tirar a devolvida. Base sintética."""
from __future__ import annotations

import sqlite3

from compliance_agent import auditoria_contrato as ac
from compliance_agent import pericia_sweep as ps


def _ob(n, comp, valor=94_999.98, envio="Processado e Pago"):
    mm, aaaa = comp.split("/")
    return {"numero_ob": n, "status": "Contabilizado", "status_envio": envio, "nl": "NL" + n, "re": "RE" + n,
            "pd": "PD" + n, "valor": valor, "competencia": comp, "data_emissao": f"10/{mm}/{aaaa}", "processo": ""}


def test_contabilizada_devolvida_pelo_banco_nao_e_paga():
    obs = [_ob("1", "02/2025", envio="Erro no Pagamento"), _ob("2", "02/2025"), _ob("3", "03/2025", envio="")]
    assert [o["numero_ob"] for o in ac._contabilizadas(obs)] == ["2", "3"]


def test_devolucao_e_reemissao_nao_e_duplicidade_por_competencia():
    obs = [_ob("1", "01/2025"), _ob("2", "02/2025", envio="Erro no Pagamento"), _ob("3", "02/2025"),
           _ob("4", "03/2025"), _ob("5", "04/2025")]
    t07 = ac._t07_duplicidade({"obs": obs, "favorecido": "X LTDA", "orgao": "154100"})
    assert t07["status"] not in ("INDICIO", "CONFIRMADO"), t07


def test_obs_de_traz_o_status_de_envio_e_aceita_base_sem_a_coluna(tmp_path):
    for com_envio in (True, False):
        c = sqlite3.connect(tmp_path / f"b{com_envio}.db")
        c.row_factory = sqlite3.Row
        c.execute("CREATE TABLE ob_orcamentaria_siafe(numero_ob TEXT, status TEXT, nl TEXT, re TEXT, pd TEXT, "
                  "valor REAL, competencia TEXT, data_emissao TEXT, processo TEXT, nome_credor TEXT, credor TEXT, "
                  "ug_emitente TEXT" + (", status_envio TEXT)" if com_envio else ")"))
        c.execute("INSERT INTO ob_orcamentaria_siafe (numero_ob,status,valor,competencia,data_emissao,credor,"
                  "ug_emitente" + (",status_envio" if com_envio else "") + ") VALUES ('1','Contabilizado',10,"
                  "'01/2025','10/01/2025','11111111000111','100100'" + (",'Erro no Pagamento')" if com_envio else ")"))
        o = ps._obs_de(c, "11111111000111", "100100")[0]
        assert o["status_envio"] == ("Erro no Pagamento" if com_envio else "")
        c.close()
