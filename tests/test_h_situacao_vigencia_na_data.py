# -*- coding: utf-8 -*-
"""A situação cadastral era aferida HOJE e cobrada como se fosse à ÉPOCA.

`H-SITUACAO` saía CONFIRMADO, nível ALTO e peso 20, escrita "Pagamento/contratação de empresa
não-ativa é vedado" — a partir do retrato atual da Receita, sem nenhuma comparação de datas.

Medido em 2026-08-04 sobre a base inteira: dos **75 CNPJs hoje irregulares** que receberam do
Estado, **59 (78,7%)** tiveram TODO o pagamento ANTERIOR à data da irregularidade. A empresa
estava regular quando foi paga. O maior deles recebeu R$ 9,37 mi até 28/11/2023 e só foi BAIXADA
em 26/12/2025.

É a família do caso Fênix ("R$ 4 bi pagos a empresa morta", que era ~218× demais): confundir o
estado de hoje com o estado à época. O dado que faltava sempre existiu — `receita_estab.db` traz
`data_situacao`, indexado por CNPJ, a 0 ms por consulta; o caminho usado lia a tabela `empresas`,
que guarda só o retrato.
"""
import datetime as dt

import pytest

from compliance_agent import investigacao_dd as I


def _hip_situacao(monkeypatch, *, quando, ultima, situacao="INAPTA"):
    monkeypatch.setattr(I, "_situacao_com_data", lambda c, db_path=None: (situacao, quando))
    monkeypatch.setattr(I, "_ultimo_pagamento_ob", lambda c, db_path=None: ultima)
    r = I.investigar("11222333000181", cadastral={"situacao": situacao},
                     usar_rede=False, usar_beneficios=False)
    return next((h for h in r["hipoteses"] if h["codigo"] == "H-SITUACAO"), None)


def test_irregularidade_POSTERIOR_ao_pagamento_nao_acusa_ato_vedado(monkeypatch):
    h = _hip_situacao(monkeypatch, quando=dt.date(2025, 12, 26), ultima=dt.date(2023, 11, 28),
                      situacao="BAIXADA")
    assert h["status"] == "INDICIO" and h["nivel"] == "BAIXO"
    assert h["peso"] < 20
    assert "POSTERIOR" in h["evidencia"]
    assert "vedado" not in h["evidencia"], "seguia acusando ato vedado sobre pagamento regular"


def test_pagamento_DEPOIS_da_irregularidade_continua_confirmado(monkeypatch):
    """O caso IDESI: INAPTA em 28/01/2026 e OB contabilizada em 23/03/2026. A correção não pode
    desarmar a acusação verdadeira — só a anacrônica."""
    h = _hip_situacao(monkeypatch, quando=dt.date(2026, 1, 28), ultima=dt.date(2026, 3, 23))
    assert h["status"] == "CONFIRMADO" and h["peso"] == 20
    assert "28/01/2026" in h["evidencia"] and "vedado" in h["evidencia"]


def test_sem_data_da_situacao_declara_o_limite_em_vez_de_afirmar(monkeypatch):
    """INDISPONÍVEL ≠ 0 e INDISPONÍVEL ≠ confirmado: sem a data não se afere a vigência no ato."""
    h = _hip_situacao(monkeypatch, quando=None, ultima=dt.date(2024, 5, 2))
    assert h["status"] == "INDICIO"
    assert "não foi apurada" in h["evidencia"]
    assert 3 < h["peso"] < 20


def test_sem_pagamento_conhecido_nao_vira_absolvicao(monkeypatch):
    """Sem OB no SIAFE não se conclui que o pagamento foi anterior — a irregularidade com data
    conhecida segue confirmada, apenas sem a frase sobre pagamento posterior."""
    h = _hip_situacao(monkeypatch, quando=dt.date(2026, 1, 28), ultima=None)
    assert h["status"] == "CONFIRMADO"
    assert "pagamento posterior" not in h["evidencia"]


def test_empresa_ATIVA_nao_gera_a_hipotese(monkeypatch):
    r = I.investigar("11222333000181", cadastral={"situacao": "ATIVA"},
                     usar_rede=False, usar_beneficios=False)
    assert not [h for h in r["hipoteses"] if h["codigo"] == "H-SITUACAO"]


@pytest.mark.slow
def test_a_base_primaria_responde_com_data(tmp_path):
    """A data existe e é barata: `receita_estab.db` é indexado por CNPJ. Se este teste passar a
    pular, a correção acima degrada para o ramo 'data não apurada' — que é honesto, mas cego."""
    import pathlib
    if not (pathlib.Path.home() / "JFN" / "data" / "receita_estab.db").exists():
        pytest.skip("receita_estab.db ausente")
    sit, quando = I._situacao_com_data("28470707000180")
    assert sit == "INAPTA" and quando == dt.date(2026, 1, 28)
